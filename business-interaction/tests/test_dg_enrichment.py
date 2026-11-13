import unittest
import json
from decimal import Decimal
from interaction.dg_enrichment import dg_alias,enrich_dg
from interaction.preparation_sources import Index
JAN='4550621772719'
ALIAS='DG'+JAN
def result(**kw):
    return {'jan':JAN,'status':'matched','values':{'name':'新网球王子 寝起 睡衣 吧唧徽章贴纸 DG周边','spec':'越前龙马贴纸9','channel':'movic','yd':None,'price':None,**kw}}
def order(**kw):
    return {'jan':ALIAS,'name':'模玩熊 新网球王子 寝起 睡衣 吧唧徽章贴纸 DG周边预定金','spec':'越前龙马 贴纸','channel':'A店代购','yd':'YDZBDG2026081401','order_id':'zbqqdg2026082501','status':'已采购','price':29.0,'currency':'人民币','source':{'kind':'effective_purchase_order','row':11506},**kw}
class DgEnrichmentTests(unittest.TestCase):
    def test_real_case_checked_and_actual_order_is_cny(self):
        r=enrich_dg(result(),Index([order()]))
        self.assertEqual(r['values']['price'],'29元');self.assertEqual(r['values']['yd'],'YDZBDG2026081401');self.assertEqual(r['values']['channel'],'A店代购')
        self.assertEqual(r['dg_enrichment']['replaced_automatic_references']['channel'],'movic');self.assertFalse(r['price_review']['quantity_conversion']);self.assertFalse(r['price_review']['automatic_confirmation'])
    def test_no_global_prefix_stripping_or_index_merge(self):
        ix=Index([order()]);self.assertFalse(ix.lookup(JAN)['records'])
        r=enrich_dg(result(),Index([order(jan='XYZ'+JAN)]));self.assertIsNone(r['values']['price'])
        self.assertIsNone(dg_alias('4550621772718'));self.assertIsNone(dg_alias(ALIAS))
    def test_missing_independent_product_context(self):
        for f in ['name','spec']:self.assertIsNone(enrich_dg(result(**{f:None}),Index([order()]))['values']['yd'])
    def test_different_product_same_numeric_suffix_rejected(self):
        r=enrich_dg(result(),Index([order(name='别的商品')]))
        self.assertIsNone(r['values']['price']);self.assertIsNone(r['values']['yd'])
    def test_different_variant_or_version_not_linked(self):
        for spec in ['不二周助贴纸','越前龙马立牌','Vol2整盒']:
            r=enrich_dg(result(),Index([order(spec=spec)]));self.assertIsNone(r['values']['price']);self.assertIsNone(r['values']['yd'])
    def test_bonus_requires_manual_context(self):
        r=enrich_dg(result(),Index([order()]),{'name_ja':'特典'});self.assertIsNone(r['values']['price']);self.assertIsNone(r['values']['yd'])
    def test_cancelled_observation_blocks_old_quote(self):
        self.assertIsNone(enrich_dg(result(),Index([order(),order(status='已撤销')]))['values']['price'])
    def test_opening_price_not_purchase_quote(self):
        r=enrich_dg(result(),Index([order(price=550,currency='JPY',status=None,source={'kind':'catalogue'})]));self.assertIsNone(r['values']['price'])
    def test_multiple_currencies_not_converted_or_merged(self):
        r=enrich_dg(result(),Index([order(),order(order_id='PO2',currency='JPY',price=550)]))
        self.assertIsNone(r['values']['price']);self.assertEqual(r['price_review']['category'],'unit_or_currency')
    def test_existing_and_source_manual_values_preserved(self):
        r=enrich_dg(result(price=Decimal('600'),yd='YDZBDG2026081401'),Index([order()]));self.assertEqual(r['values']['price'],600);self.assertEqual(r['values']['channel'],'movic')
        r['values']['price']=str(r['values']['price']);json.dumps(r)
        r=enrich_dg(result(),Index([order()]),{'source_channel':'人工渠道','source_purchase_unit_price':'31元','source_yd':'人工YD'})
        self.assertEqual(r['values']['price'],'31元');self.assertEqual(r['values']['channel'],'人工渠道');self.assertEqual(r['values']['yd'],'人工YD')
    def test_conflicting_orders_not_filtered_to_convenient_match(self):
        r=enrich_dg(result(),Index([order(),order(name='别的商品',status='已撤销')]))
        self.assertIsNone(r['values']['price']);self.assertIsNone(r['values']['yd'])
    def test_same_product_reorders_not_conflict(self):
        r=enrich_dg(result(),Index([order(),order(order_id='PO2',yd='OTHER_YD')]))
        self.assertEqual(r['values']['price'],'29元');self.assertEqual(r['price_review']['category'],'safe_dg_order_quote')
if __name__=='__main__':unittest.main()
