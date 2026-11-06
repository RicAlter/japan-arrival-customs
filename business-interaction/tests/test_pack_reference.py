import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction.pack_reference import reference
class SpecificationReference(unittest.TestCase):
    def test_multi_markers_do_not_infer_count(self):
        for spec in ['拍立得整盒89','整套4','吧唧5枚套组3','明信片set2','SET','ｓｅｔ','卡片BOX','贴纸セット','整袋83','盒装']:
            result=reference(spec);self.assertEqual(result['status'],'likely_multiple_count_pending',spec);self.assertIsNone(result['reference_count'])
    def test_other_nonempty_spec_defaults_to_one(self):
        for spec in ['三角初华2','单个挂件4','本体','透卡','立牌单品89']:
            self.assertEqual(reference(spec)['reference_count'],1)
    def test_english_substring_is_not_set(self):self.assertEqual(reference('offset版本2')['reference_count'],1)
    def test_existing_seventeen_not_overwritten(self):self.assertEqual(reference('拍立得整盒89',17)['reference_count'],17)
    def test_explicit_multi_source_overrides_nonbundle_spec_default(self):self.assertEqual(reference('明信片',14)['reference_count'],14)
    def test_original_tail_quantity_is_retained(self):self.assertEqual(reference('拍立得整盒89')['raw_specification'],'拍立得整盒89')
    def test_blank_or_only_quantity_not_defaulted(self):
        for s in [None,'','   ','89']:self.assertIsNone(reference(s)['reference_count'])
    def test_bad_existing_source_not_replaced_with_one(self):
        for x in [0,-1,'bad','1.5']:self.assertIsNone(reference('单品',x)['reference_count'])
    def test_changed_identity_keeps_old_reference_as_history(self):
        r=reference('新规格',17,False);self.assertIsNone(r['reference_count']);self.assertEqual(r['existing_reference_preserved'],17)
    def test_reference_never_proves_unit_or_middle_layer(self):
        r=reference('单品');self.assertFalse(r['automatic_confirmation']);self.assertFalse(r['original_qty_unit_inferred']);self.assertIsNone(r['packs_per_box']);self.assertIsNone(r['units_per_pack'])
if __name__=='__main__':unittest.main()
