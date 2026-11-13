"""Regression from captured KMT20261003 problem rows; no network."""
import json,sys,unittest,tempfile,hashlib
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook,load_workbook
from interaction.preparation import resolve
from interaction.preparation_sources import Index
from interaction.matching_repair import select_price
from interaction.material_review import apply_material_reference_overlay,read_evidence
from interaction.material_reference import apply_overlay,canonical_material_return
from material_providers.fast_material_batch import extract,translate
from material_providers.quality import material_quality
F=Path(__file__).parent/'fixtures/kmt20261003-accuracy'
D=json.loads((F/'problem-rows.json').read_text(encoding='utf8'))
class AccuracyTests(unittest.TestCase):
 def test_real_jump_material_is_bounded(self):
  raw=(F/'jump-material-page.html').read_bytes()
  self.assertEqual(hashlib.sha256(raw).hexdigest(),D['jump_raw_sha256'])
  self.assertEqual(extract(raw.decode('utf8'))[0],'アクリル')
  self.assertEqual(translate(extract(raw.decode('utf8'))[0]),'亚克力')
 def test_polluted_old_cache_is_rejected(self):
  self.assertFalse(material_quality(D['jump_polluted_original']))
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'e.json';p.write_text(json.dumps({'candidates':[{'jan':'4530430565337','material_original':D['jump_polluted_original'],'material_zh':'亚克力','url':'https://example.invalid/a','rows':[{'jan':'4530430565337'}],'snapshot':str(F/'jump-material-page.html'),'content_sha256':D['jump_raw_sha256']}]}),encoding='utf8')
   good,bad=read_evidence([p]);self.assertFalse(good);self.assertEqual(bad[0]['reason'],'material_quality_rejected')
 def test_generic_pollution_fails_closed(self):
  self.assertEqual(extract('素材：アクリル\nお気に入り作品に登録する\n{"@context":"https://schema.org"}')[1],'parse_error')
  self.assertTrue(material_quality('本体：PVC、ABS；底座：亚克力；棉100%'))
 def test_empty_yd_never_matches_collection(self):
  jan=D['empty_yd']['jan'];cards={None:[{'material_original':'错误材质','accessories_original':D['empty_yd']['original_T']}]}
  r=resolve(jan,Index([]),cards,[]);self.assertIsNone(r['packaging']['value'])
 def test_empty_yd_retains_independent_code_packaging(self):
  jan=D['empty_yd']['jan'];r=resolve(jan,Index([{'jan':jan,'name':'实际商品','spec':'盒','packaging':'每盒6枚','source':{'kind':'registry'}}]),{None:[{'accessories_original':'错误盒规'}]},[])
  self.assertEqual(r['packaging']['value'],'每盒6枚')
 def test_real_two_auxiliary_price_conflicts(self):
  for n in ['1636','1637']:
   r=D['prices'][n];result=resolve(r['jan'],Index(r['records']),{},[],{'spec':r['spec']});self.assertIsNone(result['values']['price']);self.assertEqual(result['price_review']['category'],'true_price_conflict')
 def test_real_two_order_status_conflicts(self):
  for n in ['1873','1874']:
   r=D['prices'][n];v,a=select_price(r['jan'],r['records'],r['spec']);self.assertIsNone(v);self.assertEqual(a['category'],'order_status_conflict')
 def test_true_missing_is_still_missing(self):
  self.assertEqual(select_price(D['empty_yd']['jan'],[])[1]['category'],'source_missing')
 def test_producer_current_and_return_share_overlay_contract(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);f=d/'b.xlsx';w=Workbook();s=w.active;s.title='核对';s.append(list('ABCDEFGHIJKLMNOPQRST'));s.append(['','','4580821993966','','','实际商品','整盒26','','','日本商品','','','','','人工材质','','YDZB2026071026','','','']);w.save(f)
   report=d/'r.json';report.write_text(json.dumps({'rows':{'2':{'binding':{'jan':'4580821993966','name_ja':'日本商品','spec':'整盒26','yd':'YDZB2026071026'},'library':{'status':'reference_only','yd_link_sources':[{'material_original':'马口铁'}]}}}}),encoding='utf8')
   config={'prepared_file':str(f),'background':str(d),'sheet':'核对'};dual={'reference_report':str(report)}
   self.assertEqual(apply_material_reference_overlay(config,dual)['written_cells'],1)
   record=json.loads((d/'material-reference-overlay.json').read_text(encoding='utf8'));self.assertIn('binding',record['rows']['2'])
   apply_overlay(config,f);self.assertEqual(apply_material_reference_overlay(config,dual)['written_cells'],0)
   # Second pass retains the first original value, so an unchanged return removes decoration.
   returned=canonical_material_return(config,f);check=load_workbook(returned,data_only=True)['核对'];self.assertIsNone(check['S2'].value);self.assertEqual(check['O2'].value,'人工材质')
if __name__=='__main__':unittest.main()
