import unittest,json,tempfile,zipfile,sys,subprocess
from pathlib import Path
from unittest.mock import patch
from material_foundation.parsing import extract,translate,parse
from material_foundation.service import handle,load,checksum
Q='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
JAN='4530430565337'
def xlsx(path,material=''):
    def c(a,v):return f'<c r="{a}" t="inlineStr"><is><t>{v}</t></is></c>'
    xml=f'<worksheet xmlns="{Q}"><sheetData><row r="1">'+''.join(c(a,v) for a,v in [('A1','JAN'),('B1','网站查找材质'),('C1','网址'),('D1','站名')])+'</row>'
    for n in (2,3):xml+=f'<row r="{n}">'+c(f'A{n}',JAN)+(c(f'B{n}',material) if n==2 else '')+f'<c r="E{n}"><f>1+1</f><v>2</v></c></row>'
    xml+='</sheetData></worksheet>'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{Q}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="数据" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',xml);z.writestr('xl/media/original.bin',b'preserved-image');z.writestr('unrelated.xml',b'<keep/>')

class Parsing(unittest.TestCase):
    def test_complete_and_percent(self):
        self.assertEqual(translate('紙,スチール等')['zh'],'纸、钢等')
        self.assertEqual(translate('綿100%')['zh'],'100%棉')
        self.assertEqual(translate('Material cotton')['zh'],'Material 棉')
    def test_components_and_unknown(self):
        result=translate('本体：アクリル、台座：ABS、謎素材20%')
        self.assertIn('本体：亚克力',result['zh']);self.assertIn('底座：ABS树脂',result['zh']);self.assertIn('謎素材20%',result['zh'])
    def test_hanzi_always_translated(self):self.assertEqual(translate('紙、鉄、合成紙')['zh'],'纸、铁、合成纸')
    def test_labels_priority_and_empty_fallback(self):
        self.assertEqual(extract('■素材：\n■仕様：真鍮製/色入れ')['original'],'真鍮製/色入れ')
        self.assertEqual(extract('■仕様：ABS\n■素材：紙')['original'],'紙')
    def test_label_next_line_html(self):self.assertEqual(extract('<table><tr><th>素材</th><td>紙、鉄、PET</td></tr></table>')['original'],'紙、鉄、PET')
    def test_size_cleaned(self):self.assertEqual(extract('素材：紙 約W50×H70mm ※注意')['original'],'紙')
    def test_hobby_body_more_complete(self):self.assertEqual(extract('素材：PET\n商品説明\n●素材：紙、鉄、PET','hobbysearch')['original'],'紙、鉄、PET')
    def test_no_material(self):self.assertIsNone(extract('サイズ：50mm\n商品名：カード'))
    def test_exact_json_jan_required(self):
        result=parse('colleize',JAN,'detail',json.dumps({'janCode':'OTHER','material':'紙'}),'x');self.assertEqual(result['status'],'identity_mismatch')
    def test_colleize_search_filtered_results(self):
        r=parse('colleize',JAN,'search',json.dumps({'goods':[{'id':1,'janCode':JAN},{'id':2,'janCode':'OTHER'}]}),'x');self.assertEqual(r['ids'],['1'])
    def test_amiami_search_and_detail_preserve_percent(self):
        r=parse('amiami',JAN,'search',json.dumps({'items':[{'jancode':JAN,'gcode':'G1'}]}),'x');self.assertEqual(r['ids'],['G1'])
        r=parse('amiami',JAN,'detail',json.dumps({'item':{'gcode':'G1','spec':['Material: 100% Cotton','Size: 20mm']}}),'x','G1');self.assertEqual(translate(r['original'])['zh'],'100%棉')
    def test_surugaya_same_title_wrong_jan_rejected(self):
        self.assertEqual(parse('surugaya',JAN,'detail','<p>商品詳細 素材：紙 JAN：4530430565338</p>','x')['status'],'identity_mismatch')
    def test_anime_json_exact_barcode(self):
        r=parse('anime_store',JAN,'detail',json.dumps({'product':{'variants':[{'barcode':JAN}],'body_html':'■素材：紙、鉄等'}}),'x');self.assertEqual(r['original'],'紙、鉄等')
    def test_cloudflare_not_notfound(self):self.assertEqual(parse('anime_store',JAN,'detail','Just a moment captcha','x')['status'],'error')
    def test_real_historical_jump_page(self):
        path=Path(__file__).resolve().parents[2]/'tests/fixtures/kmt20261003-accuracy/jump-material-page.html'
        result=parse('jumpcs',JAN,'detail',path.read_text(encoding='utf-8'),'https://jumpcs.shueisha.co.jp/shop/g/g'+JAN+'/')
        self.assertEqual(result['status'],'found');self.assertIn('アクリル',result['original'])
    def test_checksum_right_to_left(self):self.assertTrue(checksum(JAN));self.assertFalse(checksum(JAN[:-1]+'8'))

class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.input=self.base/'raw.xlsx';xlsx(self.input);self.root=self.base/'job'
        r=handle({'action':'prepare','input_file':str(self.input),'sheet':'数据','output':str(self.root)});self.assertNotEqual(r['status'],'failed',r)
    def tearDown(self):self.tmp.cleanup()
    def call(self,action,**kw):return handle({'action':action,'task_root':str(self.root),**kw})
    def test_dedupe_and_stable_request(self):
        self.assertEqual(self.call('current')['unique_codes'],1);a=self.call('next');self.assertEqual(a['request'],self.call('next')['request'])
    def test_403_retries_same_code_site_no_false_notfound(self):
        a=self.call('next')['request'];r=self.call('submit',request_id=a['id'],http_status=403,body='blocked');self.assertEqual(r['status'],'retry')
        self.assertEqual(self.call('resume')['counts'],{'retry':1});self.assertEqual(self.call('next')['status'],'waiting')
        with patch('material_foundation.service.clock',return_value=99999999999):b=self.call('next')['request']
        self.assertEqual((a['jan'],a['site']),(b['jan'],b['site']))
    def found(self):
        a=self.call('next')['request'];body=json.dumps({'product':{'variants':[{'barcode':JAN}],'body_html':'■素材：綿100%'}})
        return a,self.call('submit',request_id=a['id'],http_status=200,body=body),body
    def test_first_found_stops_all_later_sites(self):
        a,r,b=self.found();self.assertEqual(r['counts'],{'found':1});self.assertEqual(self.call('next')['status'],'completed')
    def test_idempotent_submission(self):
        a,r,b=self.found();self.assertEqual(self.call('submit',request_id=a['id'],http_status=200,body=b)['counts'],{'found':1})
        self.assertEqual(self.call('submit',request_id=a['id'],http_status=200,body='other')['error']['code'],'TASK_CONFLICT')
    def test_stage_writeback_preserves_other_cells_images_formula(self):
        self.found();r=self.call('writeback');self.assertNotEqual(r['status'] if 'status'in r else '', 'failed',r);self.assertEqual(r['filled_cells'],6);self.assertEqual(r['non_target_differences'],0)
    def test_fresh_disk_user_value_protected(self):
        self.found();xlsx(self.input,'人工已填');r=self.call('writeback');self.assertEqual(r['filled_cells'],3);self.assertEqual(r['skipped'][0]['row'],2)
    def test_lock_blocks_write(self):
        self.found();self.input.with_name('~$'+self.input.name).touch();self.assertEqual(self.call('writeback')['error']['code'],'TASK_CONFLICT')
    def test_no_material_advances_but_error_does_not(self):
        a=self.call('next')['request'];r=self.call('submit',request_id=a['id'],http_status=200,body=json.dumps({'product':{'variants':[{'barcode':JAN}],'body_html':'商品名のみ'}}))
        with patch('material_foundation.service.clock',return_value=99999999999):b=self.call('next')['request']
        self.assertEqual(b['site'],'colleize');self.assertIn('name='+JAN,b['url'])
    def test_run_py_real_entry(self):
        request=self.base/'request.json';request.write_text(json.dumps({'workflow':'material_query_v1','action':'current','task_root':str(self.root)}),encoding='utf-8')
        script=Path(__file__).resolve().parents[2]/'run.py';r=subprocess.run([sys.executable,'-X','utf8','-B',str(script),'--request',str(request)],capture_output=True,text=True,encoding='utf-8');self.assertEqual(r.returncode,0,r.stderr+r.stdout);self.assertEqual(json.loads(r.stdout)['unique_codes'],1)
    def test_external_fetch_is_explicit(self):
        job=load(self.root/'job.json');job['codes'][JAN]['site_index']=3
        from rebuild_mvp.service import save_json
        save_json(self.root/'job.json',job);self.assertEqual(self.call('fetch',allow_online=True)['status'],'needs_external_fetch')
    def test_code_drift_stops_resume(self):
        with patch('material_foundation.service.code_binding',return_value='changed'):
            self.assertEqual(self.call('resume')['error']['code'],'SOURCE_CHANGED')
    def test_official_record_prevents_website_query(self):
        r=handle({'action':'prepare','input_file':str(self.input),'sheet':'数据','output':str(self.base/'official'),'official_records':[{'jan':JAN,'original':'綿100%','source':{'file':'provided official material table','row':2}}]})
        self.assertEqual(r['counts'],{'found':1})
    def test_final_notfound_only_after_all_applicable_sites(self):
        for expected in ('anime_store','colleize','amiami','hobbysearch','jumpcs','surugaya'):
            with patch('material_foundation.service.clock',return_value=99999999999):request=self.call('next')['request']
            self.assertEqual(request['site'],expected)
            body=json.dumps({'product':{'variants':[{'barcode':JAN}],'body_html':'サイズ：20mm'}}) if expected=='anime_store' else json.dumps({'goods':[]}) if expected=='colleize' else json.dumps({'items':[]}) if expected=='amiami' else 'JAN：'+JAN+' サイズ：20mm'
            self.call('submit',request_id=request['id'],http_status=200,body=body)
        self.assertEqual(self.call('next')['counts'],{'not_found':1})
