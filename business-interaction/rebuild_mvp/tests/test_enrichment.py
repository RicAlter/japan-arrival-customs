import io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from rebuild_mvp import enrichment as E
from rebuild_mvp import purchase_images as P
from rebuild_mvp.enrichment_export import export
from rebuild_mvp.xlsxio import read_book
from rebuild_mvp.service import digest,handle
from material_foundation import service as M

HEAD=['CartonNo.','Origin','ProductCode(JANCode)','JC','商品图片','商品名称','规格','采购单价（原计价单位）','倍数（采购价÷批发价）','DescriptionofGoods','Qty','卸价（日本JPY）','批发金额（日本JPY）','品类','材质','渠道','YD','网站查找材质','材质参考','盒规原文参考（人工判断）','盒装数','盒规','是否盲盒','总单个数（数量依据）']

def book(path,headers=HEAD,records=None):
    from xml.sax.saxutils import escape
    records=records or [['箱1','JP','4571696823571','','','人工名称','规格','','','日文','4','100','400','','人工O','','YD2026070101','','参考S']]
    def col(i):
        return chr(65+i) if i<26 else 'A'+chr(65+i-26)
    rows=[]
    for n,values in enumerate([headers]+records,1):
        cells=''.join(f'<c r="{col(i)}{n}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' for i,v in enumerate(values))
        if n>1 and headers==HEAD:cells+='<c r="X'+str(n)+'"><f>K'+str(n)+'*2</f><v>8</v></c>'
        rows.append(f'<row r="{n}">{cells}</row>')
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="invoice (計算)" sheetId="1" r:id="rId1"/><sheet name="重さとサイズ" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns}"><sheetData>'+''.join(rows)+'</sheetData></worksheet>')
        z.writestr('xl/worksheets/sheet2.xml',f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1"><v>322</v></c></row></sheetData></worksheet>')

class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.input=self.root/'input.xlsx';book(self.input)
        self.policy=json.loads((E.HERE/'enrichment_policy.json').read_text(encoding='utf8'))
    def request(self,**extra):return {'workflow':'rebuild_mvp_v1','action':'prepare','mode':'enrich_review','batch_id':'TEST','input_file':str(self.input),'output':str(self.root/'run'),'materials':False,'pictures':True,'picture_mode':'embed',**extra}
    def image(self):
        p=self.root/'photo.png';Image.new('RGB',(20,10),'blue').save(p);return {'path':str(p),'sha256':digest(p),'width':20,'height':10}
    def test_export_preserves_manual_formulas_cache_and_weight(self):
        out=self.root/'result.xlsx';img=self.image();r=export(self.input,out,'invoice (計算)',{'2':'亚克力'},{'2':img},self.policy)
        data=read_book(out)['sheets'][0]['rows'][1]
        self.assertEqual(data['values']['O'],'人工O');self.assertEqual(data['values']['R'],'亚克力');self.assertEqual(data['values']['X'],'8');self.assertEqual(data['formulas']['X'],'K2*2')
        self.assertEqual(P.image_rows(out,'invoice (計算)'),{2})
        with zipfile.ZipFile(out) as z:self.assertTrue(all(i.extract_version<=20 for i in z.infolist()))
    def test_no_overwrite_material_or_picture(self):
        first=self.root/'first.xlsx';second=self.root/'second.xlsx';img=self.image();export(self.input,first,'invoice (計算)',{'2':'已查材质'},{'2':img},self.policy)
        result=export(first,second,'invoice (計算)',{'2':'错误覆盖'},{'2':img},self.policy)
        self.assertEqual(result['new_picture_rows'],0);self.assertEqual(result['material_rows'],0)
    def test_export_refuses_existing_output(self):
        with self.assertRaisesRegex(ValueError,'TASK_CONFLICT'):export(self.input,self.input,'invoice (計算)',{}, {},self.policy)
    def test_export_recovers_after_publish_before_job_saved(self):
        out=self.root/'result.xlsx';args=(self.input,out,'invoice (計算)',{'2':'亚克力'},{'2':self.image()},self.policy)
        first=export(*args);second=export(*args);self.assertEqual(first,second)
        temp=self.root/'recover.xlsx';out.rename(temp)
        receipt=out.with_suffix('.export.json');record=json.loads(receipt.read_text(encoding='utf8'));record['temporary']=str(temp);receipt.write_text(json.dumps(record),encoding='utf8')
        self.assertEqual(export(*args),first);self.assertTrue(out.exists())
    def test_current_resume_do_not_duplicate_output(self):
        r=handle(self.request());self.assertNotEqual(r['status'],'failed',r)
        again=handle({'action':'resume','task_root':str(self.root/'run')});self.assertEqual(r['business_files'],again['business_files']);self.assertEqual(r['semantic_sha256'],again['semantic_sha256'])
        self.assertEqual(handle({'action':'current','task_root':str(self.root/'run')})['summary']['blank_picture_rows'],1)
    def test_raw_material_response_reaches_review_without_changing_manual_material(self):
        first=handle(self.request(materials=True,pictures=False,allow_online=False))
        self.assertEqual(first['status'],'partial',first)
        child=json.loads((self.root/'run/materials/job.json').read_text(encoding='utf8'))
        request=child['request']
        response={'request_id':request['id'],'http_status':200,
                  'body':json.dumps({'product':{'variants':[{'barcode':'4571696823571'}],'body_html':'■素材：綿100%'}},ensure_ascii=False)}
        second=handle({'action':'resume','task_root':str(self.root/'run'),'responses':[response]})
        self.assertNotEqual(second['status'],'failed',second)
        self.assertEqual(second['summary']['materials_added'],1,second)
        values=read_book(second['business_files'][0])['sheets'][0]['rows'][1]['values']
        self.assertEqual(values['R'],'100%棉');self.assertEqual(values['O'],'人工O');self.assertEqual(values['S'],'参考S')
        third=handle({'action':'resume','task_root':str(self.root/'run'),'responses':[response]})
        self.assertEqual(second['semantic_sha256'],third['semantic_sha256'])
        self.assertEqual(second['business_files'],third['business_files'])
    def test_source_change_rejected(self):
        handle(self.request());self.input.write_bytes(b'changed')
        r=handle({'action':'resume','task_root':str(self.root/'run')});self.assertEqual(r['error']['code'],'SOURCE_CHANGED')
    def test_user_edit_output_is_preserved(self):
        r=handle(self.request());p=Path(r['business_files'][0]);p.write_bytes(b'user edit')
        r=handle({'action':'current','task_root':str(self.root/'run')});self.assertEqual(r['error']['code'],'SOURCE_CHANGED');self.assertEqual(p.read_bytes(),b'user edit')
    def test_reprepare_different_configuration_rejected(self):
        handle(self.request());r=handle(self.request(batch_id='OTHER'));self.assertEqual(r['error']['code'],'TASK_CONFLICT')
    def test_purchase_matching_yd_constraint_and_dg_scope(self):
        rows=read_book(self.input)['sheets'][0]['rows'][1:];record={'codes':['4571696823571'],'yd':'YD2026070201','url':'https://example.com/other.png'}
        self.assertEqual(P.match(rows,[record],set())['2']['status'],'unresolved')
        record.update(codes=['DG4571696823571'],yd='YD2026070101');self.assertEqual(P.match(rows,[record],set())['2']['status'],'queued')
    def test_purchase_multiple_links_kept_unresolved(self):
        rows=read_book(self.input)['sheets'][0]['rows'][1:];rs=[{'codes':['4571696823571'],'yd':'YD2026070101','url':u} for u in ['https://example.com/a','https://example.com/b']]
        self.assertEqual(P.match(rows,rs,set())['2']['reason'],'图片链接不唯一，待核对')
    def test_dynamic_procurement_headers_and_source_evidence(self):
        p=self.root/'purchase.xlsx';book(p,['单品图片','YD编码','条形码','SKU关联编码','单品名称'],[['https://example.com/a.png','YD2026070101','4571696823571','','款式A']])
        rs,audit=P.observations([{'path':str(p),'role':'purchase_list'}],{'4571696823571'})
        self.assertTrue(rs);self.assertEqual(rs[0]['column'],'A');self.assertEqual(rs[0]['source_sha256'],digest(p));self.assertEqual(rs[0]['row'],2)
    def test_opening_source_excluded(self):
        with self.assertRaises(Exception) as raised:P.observations([{'path':str(self.input),'role':'purchase_list','opening_derived':True}],set())
        self.assertEqual(raised.exception.code,'SOURCE_FORBIDDEN')
    def test_blocked_material_does_not_block_other_sites(self):
        root=self.root/'mat';M.handle({'action':'prepare','input_file':str(self.input),'output':str(root),'sheet':'invoice (計算)','columns':{'code':'C','material':'R'},'nonblocking':True})
        a=M.handle({'action':'next','task_root':str(root)})['request'];self.assertEqual(a['site'],'anime_store')
        M.handle({'action':'submit','task_root':str(root),'request_id':a['id'],'http_status':403,'body':'Forbidden'})
        b=M.handle({'action':'next','task_root':str(root)})['request'];self.assertEqual(b['site'],'colleize')
    def test_all_material_hosts_exhausted_remain_deferred(self):
        job={'request':None,'skipped':[],'policy':{'sites':['anime_store'],'jumpcs_prefix':'4530430'},'host_ready':{},'max_site_attempts':2,'codes':{'1':{'jan':'1','site_index':0,'status':'retry','phase':'start','attempts':[{'status':'error','request':{'site':'anime_store'}}]*2}}}
        M.next_nonblocking(job);self.assertEqual(job['codes']['1']['status'],'deferred')
    def test_html_response_cannot_be_image(self):
        class Response(io.BytesIO):
            headers={'Content-Type':'text/html'}
        with patch.object(P,'public_url'),patch.object(P,'build_opener') as b:
            b.return_value.open.return_value=Response(b'<html>verify-human</html>')
            with self.assertRaisesRegex(ValueError,'IMAGE_ACCESS_BLOCKED'):P.download('https://example.com/photo',self.root,self.policy)
    def test_proxy_fake_dns_only_for_audited_cdn(self):
        import socket
        with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('198.18.0.12',443))]):
            P.public_url('https://img.alicdn.com/a.jpg',self.policy['proxy_dns_cdn_hosts'])
            with self.assertRaisesRegex(ValueError,'IMAGE_URL_INVALID'):P.public_url('https://unknown.example/a.jpg',self.policy['proxy_dns_cdn_hosts'])
        with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaisesRegex(ValueError,'IMAGE_URL_INVALID'):P.public_url('https://img.alicdn.com/a.jpg',self.policy['proxy_dns_cdn_hosts'])
    def test_resume_uses_successful_download(self):
        req=self.request(allow_online=True);rows=read_book(self.input)['sheets'][0]['rows'][1:]
        with patch.object(E,'observations',return_value=([{'codes':['4571696823571'],'yd':'YD2026070101','url':'https://example.com/a'}],[])),patch.object(E,'download',return_value=self.image()) as download:
            r=handle(req);self.assertEqual(r['summary']['purchase_picture_rows_added'],1)
            handle({'action':'resume','task_root':str(self.root/'run')});self.assertEqual(download.call_count,1)
    def test_frozen_input_and_receipts_have_deterministic_semantics(self):
        req=self.request(allow_online=True)
        with patch.object(E,'observations',return_value=([{'codes':['4571696823571'],'yd':'YD2026070101','url':'https://example.com/a'}],[])),patch.object(E,'download',return_value=self.image()):
            first=handle(req);second=handle({**req,'output':str(self.root/'other')})
        self.assertEqual(first['semantic_sha256'],second['semantic_sha256']);self.assertEqual(first['summary']['purchase_picture_rows_added'],second['summary']['purchase_picture_rows_added'])

if __name__=='__main__':unittest.main()
