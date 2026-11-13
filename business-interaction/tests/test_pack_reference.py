import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction.pack_reference import reference
class SpecificationReference(unittest.TestCase):
    def test_no_spec_or_old_reference_becomes_a_count(self):
        for spec in ['拍立得整盒89','整套4','set','本体','单品','透卡',None,'89']:
            for old in [None,1,17,14,'bad']:
                r=reference(spec,old);self.assertIsNone(r['reference_count']);self.assertFalse(r['default_one_used'])
    def test_original_sentence_is_not_parsed_or_translated(self):
        raw='明信片1包2枚、1盒7包；吧唧全10种'
        r=reference('明信片整盒',source_records=[{'accessories_original':raw,'source_row':9}])
        self.assertEqual(r['display_text'],raw);self.assertIsNone(r['packs_per_box']);self.assertIsNone(r['units_per_pack'])
    def test_sources_remain_separate_even_when_text_is_repeated(self):
        a={'accessories_original':'本体','source_row':1};b={**a,'source_row':2}
        r=reference('本体',source_records=[a,b]);self.assertEqual(r['display_text'],'本体');self.assertEqual(len(r['sources']),2)
    def test_conflicting_originals_are_both_quoted(self):
        r=reference('整盒',source_records=[{'accessories_original':'1盒7包'},{'accessories_original':'1盒8包'}])
        self.assertEqual(r['display_text'],'1盒7包\n1盒8包');self.assertIsNone(r['reference_count'])
    def test_missing_original_is_blank(self):self.assertIsNone(reference('整盒17')['display_text'])
    def test_original_tail_quantity_is_retained(self):self.assertEqual(reference('拍立得整盒89')['raw_specification'],'拍立得整盒89')
    def test_changed_identity_keeps_history_without_adoption(self):
        r=reference('新规格',17,False);self.assertEqual(r['status'],'identity_or_spec_changed_needs_source_review');self.assertEqual(r['existing_reference_preserved'],17)
    def test_reference_never_proves_units_or_approval(self):
        r=reference('单品');self.assertFalse(r['automatic_confirmation']);self.assertFalse(r['original_qty_unit_inferred']);self.assertFalse(r['price_ratio_used'])
    def test_price_ratio_never_produces_count_even_when_integer(self):
        from interaction.manual_pack import no_price_inference
        for price in ['700','701']:
            r=no_price_inference('100',price,purchase_confirmed=True,minimum_unit_confirmed=True,actual_price=True,comparable=True)
            self.assertIsNone(r['pieces_per_box']);self.assertIsNone(r['exact_ratio']);self.assertIsNone(r['reason'])
    def test_missing_price_confirmation_still_blocks(self):
        from interaction.manual_pack import no_price_inference
        self.assertEqual(no_price_inference('100','700')['reason'],'actual_japanese_price_unconfirmed')
if __name__=='__main__':unittest.main()
