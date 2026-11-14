import copy
import unittest
from rebuild_mvp.reviewed import enrich_reviewed
from rebuild_mvp.sources import known,ALLOWED


def item(role='reviewed_basics',**fields):
    data={'code':'00123','ja':'日本商品 A','carton':'B1','origin':'JP','qty':'10',**fields}
    return {'source_id':role,'source_sha256':'a'*64,'role':role,'sheet':'invoice','row':2,
            'fields':data,'columns':{k:'N' for k in data},'scope':{'priority':0}}

def row():
    return {'row_id':'r1','raw':{'code':'00123','ja':'日本商品 A','carton':'B1','origin':'JP','qty':'10','jpy_price':'500','amount':'5000'},
            'values':{},'evidence':{},'issues':[]}


class ReviewedTests(unittest.TestCase):
    def test_category_pack_blind_material_without_recalculation(self):
        r=row();original=copy.deepcopy(r['raw'])
        enrich_reviewed(r,[item(category='徽章',box_size='10',blind='是',material='铁')])
        self.assertEqual(r['values']['box_size'],'10');self.assertEqual(r['values']['blind'],'是')
        self.assertEqual(r['values']['category'],'徽章');self.assertEqual(r['raw'],original)
        self.assertNotIn('box_count',r['values'])

    def test_completed_material_preferred_reference_but_not_O_override(self):
        r=row()
        enrich_reviewed(r,[item(material='纸',website_material='旧参考'),
                           item('completed_reference',material='塑料',website_material='纸、PET新完整原文')])
        self.assertEqual(r['values']['material'],'纸')
        self.assertEqual(r['values']['website_material'],'纸、PET新完整原文')

    def test_price_channel_and_full_reference_YD_never_copied(self):
        r=row();enrich_reviewed(r,[item('completed_reference',purchase_price='9',channel='旧渠道',yd='YD123')])
        self.assertFalse(r['values'])
        self.assertNotIn('yd',ALLOWED['completed_reference'])

    def test_reviewed_YD_resolves_missing_with_exact_shipment_scope(self):
        r=row();r['issues']=[{'code':'FIELD_CONFLICT','field':'yd','candidates':[{'value':'YD1'},{'value':'YD2'}]}]
        enrich_reviewed(r,[item(yd='YD1')]);self.assertEqual(r['values']['yd'],'YD1')
        self.assertFalse(r['issues']);self.assertTrue(r['resolved_issues'])

    def test_reviewed_YD_other_box_or_qty_not_reused(self):
        for change in [{'carton':'B2'},{'qty':'20'}]:
            r=row();enrich_reviewed(r,[item(yd='YD1',**change)])
            self.assertNotIn('yd',r['values'])

    def test_different_current_YD_not_silently_overwritten(self):
        r=row();r['values']['yd']='YD2';enrich_reviewed(r,[item(yd='YD1')])
        self.assertEqual(r['values']['yd'],'YD2');self.assertEqual(r['issues'][0]['code'],'REVIEWED_FIELD_CONFLICT')

    def test_counts_only_from_same_row_not_sibling_box(self):
        r=row();enrich_reviewed(r,[item('completed_reference',box_count='10',total_pieces='60',carton='B2')])
        self.assertNotIn('box_count',r['values'])
        enrich_reviewed(r,[item('completed_reference',box_count='10',total_pieces='60')])
        self.assertEqual(r['values']['total_pieces'],'60')

    def test_conflicting_reviewed_values_not_first_row(self):
        r=row();enrich_reviewed(r,[item(box_size='6'),item(box_size='10')])
        self.assertNotIn('box_size',r['values']);self.assertTrue(r['issues'])

    def test_formula_error_not_adopted_as_YD_or_material(self):
        self.assertFalse(known('#N/A'));self.assertFalse(known('#VALUE!'))
        r=row();enrich_reviewed(r,[item(yd='#N/A',material='#VALUE!')]);self.assertFalse(r['values'])

    def test_reviewed_name_spec_fill_blank_only_same_shipment(self):
        r=row();r['values']['specification']='本次重新匹配规格'
        enrich_reviewed(r,[item(name='运营已核中文名称',specification='旧规格6个入')])
        self.assertEqual(r['values']['name'],'运营已核中文名称')
        self.assertEqual(r['values']['specification'],'本次重新匹配规格')
        other=row();enrich_reviewed(other,[item(name='其他箱名称',carton='B2')])
        self.assertNotIn('name',other['values'])

    def test_YD_reason_output_row_follows_dynamic_header(self):
        from rebuild_mvp.yd_diagnostics import explain_yd
        r=row();r['source_row']=8
        self.assertEqual(explain_yd([r],header_row=3)['rows'][0]['output_row'],6)


if __name__=='__main__':unittest.main()
