import unittest,tempfile,pathlib,sqlite3,json,zipfile,copy
from test_enrichment import book
from rebuild_mvp.service import handle
from rebuild_mvp.review_return import overlay
from rebuild_mvp.xlsxio import read_book
from rebuild_mvp.storage import Store
from rebuild_mvp.candidate_pipeline import apply_candidates
from unittest.mock import patch

class ReviewReturn(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name);self.src=self.root/'in.xlsx';book(self.src)
  self.req=dict(workflow='rebuild_mvp_v1',action='prepare',mode='review_return',batch_id='B',input_file=str(self.src),output=str(self.root/'job'))
  self.initial=handle(self.req);self.assertNotEqual(self.initial['status'],'failed',self.initial)
 def submit(self,changes,**extra):
  path=self.root/('return'+str(len(list(self.root.glob('return*'))))+'.xlsx');overlay(self.src,path,'invoice (計算)',changes)
  return handle(dict(workflow='rebuild_mvp_v1',action='resume',task_root=self.req['output'],submitted_file=str(path),expected_revision=0,expected_reference_sha256=self.initial['reference_sha256'],**extra)),path
 def test_partial_acceptance_and_durable_receipt(self):
  result,path=self.submit({'F2':'新名称','V2':'错误盒规','R2':'亚克力'})
  self.assertEqual(result['status'],'partial',result);self.assertEqual(result['accepted_cells'],2)
  output=read_book(result['business_files'][0]);self.assertEqual(output['sheets'][0]['rows'][1]['values']['F'],'新名称')
  repeat=handle(dict(workflow='rebuild_mvp_v1',action='resume',task_root=self.req['output'],submitted_file=str(path)))
  self.assertTrue(repeat['idempotent']);self.assertEqual(handle(dict(action='current',task_root=self.req['output']))['revision'],1)
  db=sqlite3.connect(self.root/'job/candidate.sqlite3');self.assertEqual(db.execute('select count(*) from manual_decisions').fetchone()[0],2);db.close()
 def test_stale_return_and_raw_field_change_rejected(self):
  first,path=self.submit({'F2':'新名'});self.assertEqual(first['status'],'saved')
  second,_=self.submit({'G2':'另一规格'});self.assertEqual(second['error']['code'],'TASK_CONFLICT')
 def test_raw_quantity_immutable(self):
  result,_=self.submit({'K2':'999'});self.assertEqual(result['error']['code'],'TASK_CONFLICT')
 def test_blank_preserved_without_explicit_clear(self):
  result,_=self.submit({'F2':''});self.assertEqual(result['accepted_cells'],0)
  self.assertEqual(read_book(result['business_files'][0])['sheets'][0]['rows'][1]['values']['F'],'人工名称')
 def test_explicit_clear(self):
  result,_=self.submit({'F2':''},clear_cells=['F2']);self.assertEqual(result['accepted_cells'],1)
 def test_current_reference_modification_rejected(self):
  self.src.write_bytes(b'changed');result=handle(dict(action='current',task_root=self.req['output']));self.assertEqual(result['error']['code'],'SOURCE_CHANGED')
 def test_second_return_uses_saved_reference(self):
  first,_=self.submit({'F2':'新名'})
  path=self.root/'second.xlsx';overlay(first['business_files'][0],path,'invoice (計算)',{'G2':'第二轮规格'})
  result=handle(dict(action='resume',task_root=self.req['output'],submitted_file=str(path),expected_revision=1,expected_reference_sha256=first['reference_sha256']))
  self.assertEqual(result['revision'],2);self.assertEqual(read_book(result['business_files'][0])['sheets'][0]['rows'][1]['values']['F'],'新名')
 def test_actual_run_py_accepts_return(self):
  import subprocess,sys
  source=pathlib.Path(__file__).resolve().parents[2]/'run.py';request=self.root/'request.json'
  submitted=self.root/'actual.xlsx';overlay(self.src,submitted,'invoice (計算)',{'R2':'纸、铁'})
  request.write_text(json.dumps(dict(workflow='rebuild_mvp_v1',action='resume',task_root=self.req['output'],submitted_file=str(submitted),expected_revision=0,expected_reference_sha256=self.initial['reference_sha256'])),encoding='utf8')
  result=subprocess.run([sys.executable,'-X','utf8','-B',str(source),'--request',str(request)],capture_output=True,text=True,encoding='utf8')
  self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertEqual(json.loads(result.stdout)['accepted_cells'],1)
 def test_formula_and_images_preserved(self):
  from rebuild_mvp.enrichment_export import export
  from rebuild_mvp.purchase_images import image_rows
  from rebuild_mvp.service import digest
  from PIL import Image
  from rebuild_mvp import enrichment as E
  img=self.root/'image.png';Image.new('RGB',(12,12),'red').save(img)
  pictured=self.root/'pictured.xlsx';policy=json.loads((E.HERE/'enrichment_policy.json').read_text(encoding='utf8'))
  export(self.src,pictured,'invoice (計算)',{}, {'2':{'path':str(img),'sha256':digest(img),'width':12,'height':12}},policy)
  job=self.root/'pictured-job';ref=handle(dict(action='prepare',mode='review_return',batch_id='B',input_file=str(pictured),output=str(job)))
  returned=self.root/'pictured-return.xlsx';overlay(pictured,returned,'invoice (計算)',{'N2':'人工品类'})
  result=handle(dict(action='resume',task_root=str(job),submitted_file=str(returned),expected_revision=0,expected_reference_sha256=ref['reference_sha256']))
  self.assertEqual(result['status'],'saved',result);self.assertEqual(image_rows(result['business_files'][0],'invoice (計算)'),{2})
  with zipfile.ZipFile(pictured) as a,zipfile.ZipFile(result['business_files'][0]) as b:
   for name in a.namelist():
    if name!='xl/worksheets/sheet1.xml':self.assertEqual(a.read(name),b.read(name))

class CandidateBoundary(unittest.TestCase):
 def test_candidates_not_adopted_as_facts(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(pathlib.Path(tmp)/'db.sqlite3');row={'row_id':'r','source_row':2,'sheet':'invoice','raw':{'code':'1'},'values':{'yd':'YD（待确认）'},'evidence':{'yd':[{'source':'test'}]},'issues':[],'review_candidates':{'yd':{'confirmed':False,'options':[{'value':'YD','evidence':{'source':'test'}}]}}}
   try:
    s.save_batch('B',{'source':{'path':'input.xlsx','sha256':'a'*64},'rows':[copy.deepcopy(row)]});s.save_matches('B',[row]);self.assertEqual(s.db.execute('select count(*) from adopted_fields').fetchone()[0],0);self.assertEqual(s.db.execute('select count(*) from candidate_fields').fetchone()[0],1)
   finally:s.close()
 def test_versioned_translation_requires_exact_japanese_identity(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=pathlib.Path(tmp)/'translations.json';p.write_text(json.dumps({'schema':'arrival-translations/1','records':[{'code':'1','japanese_name':'日本原文','source':'user translation','fields':{'name':'中文译名'}}]}),encoding='utf8')
   rows=[{'row_id':'r','raw':{'code':'1','ja':'日本原文'},'matching':{'path':'unresolved'},'values':{},'evidence':{},'issues':[]}]
   apply_candidates(rows,{'candidate_review':{'enabled':True},'sources':[],'translation_file':str(p)})
   self.assertIn('译名待确认',rows[0]['values']['name']);self.assertFalse(rows[0]['review_candidates']['name']['confirmed'])
 def test_name_scan_keeps_provenance_and_existing_value(self):
  rows=[{'row_id':'r','raw':{'code':'1','ja':'日本原文'},'matching':{'path':'unresolved'},'values':{'name':'人工值'},'evidence':{},'issues':[]}]
  rec={'role':'purchase_list','source_id':'s','source_sha256':'a'*64,'sheet':'采购','row':8,'columns':{'yd':'B'},'fields':{'name':'日本原文','yd':'YD2026010101'},'scope':{}}
  with patch('rebuild_mvp.candidate_pipeline.digest',return_value='a'*64),patch('rebuild_mvp.candidate_pipeline._iter_records',return_value=iter([rec])):
   apply_candidates(rows,{'candidate_review':{'enabled':True},'sources':[{'role':'purchase_list','path':'test'}]})
  self.assertEqual(rows[0]['values']['name'],'人工值');self.assertIn('按名称补',rows[0]['values']['yd']);self.assertEqual(rows[0]['review_candidates']['yd']['options'][0]['evidence'][0]['row'],8)
 def test_cancelled_name_quote_does_not_enter_candidates(self):
  rows=[{'row_id':'r','raw':{'code':'1','ja':'日本原文'},'matching':{'path':'unresolved'},'values':{},'evidence':{},'issues':[]}]
  rec={'role':'purchase_list','source_id':'s','source_sha256':'a'*64,'sheet':'采购','row':8,'columns':{'yd':'B'},'fields':{'name':'日本原文','yd':'YD2026010101','status':'取消'},'scope':{}}
  with patch('rebuild_mvp.candidate_pipeline.digest',return_value='a'*64),patch('rebuild_mvp.candidate_pipeline._iter_records',return_value=iter([rec])):
   apply_candidates(rows,{'candidate_review':{'enabled':True},'sources':[{'role':'purchase_list','path':'test'}]})
  self.assertNotIn('yd',rows[0]['values'])
 def test_main_missing_price_only_adds_purchase_candidate(self):
  rows=[{'row_id':'r','raw':{'code':'1','ja':'日本原文'},'matching':{'path':'business_code'},'values':{'name':'主表名称','specification':'主表规格','channel':'主表渠道','yd':'YDKEEP'},'evidence':{},'issues':[]}]
  rec={'role':'purchase_list','source_id':'s','source_sha256':'a'*64,'sheet':'采购','row':8,'columns':{'price':'P'},'fields':{'name':'日本原文','price':'99','currency':'CNY','unit':'原SKU单位'},'scope':{}}
  with patch('rebuild_mvp.candidate_pipeline.digest',return_value='a'*64),patch('rebuild_mvp.candidate_pipeline._iter_records',return_value=iter([rec])):
   apply_candidates(rows,{'candidate_review':{'enabled':True},'sources':[{'role':'purchase_list','path':'test'}]})
  self.assertEqual(rows[0]['values']['name'],'主表名称');self.assertEqual(rows[0]['values']['yd'],'YDKEEP');self.assertIn('99元',rows[0]['values']['purchase_price'])

if __name__=='__main__':unittest.main()
