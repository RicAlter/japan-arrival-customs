from copy import deepcopy
import unittest
from rebuild_mvp.yd_selection import yd_date, choose_yd, exempt_missing_benefit_yd
from rebuild_mvp.yd_diagnostics import explain_yd

POLICY={'yd_selection':{'reissue_rule':'latest_valid_embedded_date_same_product_pack','reissue_markers':['再版','再贩','再受注'],'optional_benefit_markers':['特典']}}
def row():return {'row_id':'r','source_row':18,'raw':{'code':'123','ja':'商品','carton':'A'},'values':{'name':'同款再版商品'},'evidence':{},'issues':[]}
def rec(yd, spec='整盒6个', code='123'):
    return {'source_id':yd,'source_sha256':'sha','role':'purchase_list','sheet':'采购','row':2,'fields':{'code':code,'sku':code,'yd':yd,'sku_name':spec},'columns':{'yd':'E'},'scope':{}}
class YdSelectionTests(unittest.TestCase):
    def test_date_not_serial_or_file_date(self):
        self.assertEqual(yd_date('YDZBDG2026070109'),'2026-07-01')
        self.assertIsNone(yd_date('YDZB2026023001'))
        self.assertIsNone(yd_date('YD20260701unknown'))
    def test_same_sku_reissue_newest_date(self):
        r=row();choose_yd(r,[rec('YD2026010199'),rec('YD2026070101')],POLICY)
        self.assertEqual(r['values']['yd'],'YD2026070101')
        self.assertEqual(len(r['yd_selection']['candidates']),2)
    def test_same_date_does_not_choose_largest_suffix(self):
        r=row();choose_yd(r,[rec('YD2026070101'),rec('YD2026070102')],POLICY)
        self.assertNotIn('yd',r['values'])
    def test_invalid_date_stays_conflict(self):
        r=row();choose_yd(r,[rec('YD2026023001'),rec('YD2026070101')],POLICY)
        self.assertNotIn('yd',r['values'])
    def test_packaging_change_not_merged(self):
        r=row();choose_yd(r,[rec('YD2026010101'),rec('YD2026070101','单个')],POLICY)
        self.assertNotIn('yd',r['values'])
    def test_unrelated_product_not_selected(self):
        r=row();choose_yd(r,[rec('YD2026010101'),rec('YD2026070101',code='456')],POLICY)
        self.assertNotIn('yd',r['values'])
    def test_no_reissue_evidence_no_date_guess(self):
        r=row();r['values']['name']='普通商品';choose_yd(r,[rec('YD2026010101'),rec('YD2026070101')],POLICY)
        self.assertNotIn('yd',r['values'])
    def test_operator_confirmed_yd_never_replaced(self):
        r=row();r['values']['yd']='YD2026010101';choose_yd(r,[rec('YD2026070101')],POLICY)
        self.assertEqual(r['values']['yd'],'YD2026010101')
    def test_special_benefit_excludes_missing_yd_only(self):
        r=row();r['raw']['ja']='商品 特典';r['raw']['qty']='3';r['issues']=[{'field':'yd','code':'FIELD_MISSING'},{'field':'name','code':'FIELD_MISSING'}]
        raw=deepcopy(r['raw']);self.assertTrue(exempt_missing_benefit_yd(r,POLICY))
        self.assertEqual(r['raw'],raw);self.assertEqual(len(r['issues']),1)
        diag=explain_yd([r],17);self.assertEqual(diag['total_missing'],0);self.assertEqual(diag['total_exempt'],1)
    def test_benefit_existing_yd_retained(self):
        r=row();r['values'].update(name='特典',yd='YDknown');self.assertFalse(exempt_missing_benefit_yd(r,POLICY))
        self.assertEqual(r['values']['yd'],'YDknown')
