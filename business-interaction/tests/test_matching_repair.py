import unittest
from interaction.matching_repair import select_price,spec_same,resolve_repaired
from interaction.preparation_sources import Index
from interaction.preparation import _legacy_resolve

def order(price,**kw):return {'jan':'4570111256505','spec':'刹那','price':price,'currency':'JPY','status':'已采购','source':{'kind':'effective_purchase_order'},**kw}
class RepairTests(unittest.TestCase):
 def test_order_quote_beats_history_precision(self):
  v,r=select_price('4570111256505',[order(777.4),{'jan':'4570111256505','price':'777.39662','currency':'JPY','source':{'kind':'catalogue'}}],'刹那9');self.assertEqual(str(v),'777.4');self.assertEqual(r['category'],'safe_order_quote')
 def test_known_same_unit_precision_is_not_conflict(self):
  v,r=select_price('4570111256505',[order('777.4',price_unit='件',precision_basis_reference='SYNTHETIC: documented allocation precision'),order('777.39662',price_unit='件',precision_basis_reference='SYNTHETIC: documented allocation precision')],'刹那');self.assertIsNotNone(v);self.assertTrue(r['precision_only'])
 def test_different_real_order_quotes_not_guessed(self):
  v,r=select_price('4570111256505',[order(100,price_unit='件'),order(150,price_unit='件')],'刹那');self.assertIsNone(v);self.assertEqual(r['category'],'true_price_conflict')
 def test_unknown_units_do_not_justify_precision_merge(self):
  v,r=select_price('4570111256505',[order(777.4),order('777.39662')],'刹那');self.assertIsNone(v);self.assertEqual(r['category'],'unit_or_currency')
 def test_currency_and_units_separate(self):
  for other in [order(100,currency='CNY'),order(100,price_unit='盒')]:
   v,r=select_price('4570111256505',[order(100,price_unit='件'),other],'刹那');self.assertIsNone(v);self.assertEqual(r['category'],'unit_or_currency')
 def test_cancelled_or_other_variant_not_used(self):
  v,r=select_price('4570111256505',[order(100,cancelled='是')],'刹那');self.assertIsNone(v)
  v,r=select_price('4570111256505',[order(100,spec='洛克昂')],'刹那');self.assertIsNone(v);self.assertEqual(r['category'],'substantive_identity_conflict')
 def test_multiple_YD_ordinary_is_normal(self):
  rs=[order(100,yd='Y1',name='商品'),order(100,yd='Y2',name='商品 追定金')]
  r=resolve_repaired('4570111256505',Index(rs),{},[],_legacy_resolve);self.assertEqual(str(r['values']['price']),'100');self.assertFalse(r['ordinary_multiple_YD_is_conflict'])
 def test_bonus_repeated_code_not_merged(self):
  rs=[order(100,yd='Y1',name='商品A'),order(100,yd='Y2',name='商品B')]
  r=resolve_repaired('4570111256505',Index(rs),{},[],_legacy_resolve,{'name_ja':'特典'});self.assertEqual(r['status'],'special_identity_requires_context');self.assertEqual(r['values'],{})
 def test_substantive_count_version_not_normalized_away(self):
  self.assertTrue(spec_same('刹那9','刹那'));self.assertFalse(spec_same('全8种','全6种'));self.assertFalse(spec_same('vol.3','vol.2'));self.assertFalse(spec_same('刹那私服','刹那'))

 def test_light_spec_prefixes_and_source_counts(self):
  for a,b in [('吧唧整盒16','整盒'),('立牌A：坂田銀時140','A坂田銀時'),('BIG立牌②1','BIG立牌②'),('Vol.1数量15','Vol.1'),('01A6（差2）','01A'),('Ｃ库洛米60','Ｃ库洛米也')]:self.assertTrue(spec_same(a,b),(a,b))
  for a,b in [('徽章A','立牌A'),('全8种','全6种'),('Vol.1','Vol.2'),('刹那私服','刹那')]:self.assertFalse(spec_same(a,b))

 def test_cancelled_snapshot_blocks_older_effective_quote(self):
  v,r=select_price('4570111256505',[order(100,order_id='PO'),order(100,order_id='PO',status='已撤销')],'刹那');self.assertIsNone(v)

 def test_partial_cut_flag_is_not_order_cancellation(self):
  v,r=select_price('4570111256505',[order(585.76,has_cut='是',cut_quantity=2)],'刹那');self.assertEqual(str(v),'585.76')

 def test_observed_aliases_and_purchase_count_notes(self):
  for a,b in [('整盒20→17','整盒'),('吧唧整盒3','心吧唧整盒'),('立牌露西亚24','七海露西亚立牌'),('立牌波音9','宝生波音立牌'),('立牌莉娜3','洞院莉娜立牌')]:self.assertTrue(spec_same(a,b),(a,b))
  self.assertFalse(spec_same('幼少刹那','刹那'));self.assertFalse(spec_same('每盒20→17','每盒20'))

 def test_numerically_close_orders_are_not_automatically_allocation_precision(self):
  v,r=select_price('4570111256505',[order('777.4',price_unit='件'),order('777.39662',price_unit='件')],'刹那');self.assertIsNone(v)
