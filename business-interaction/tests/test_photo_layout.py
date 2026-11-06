import sys,unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction.category_reference import suggest
from interaction.photo_layout import formula,address,reference,unprotect,package_xml

class BusinessTypeReference(unittest.TestCase):
    def row(self,jp,material=None,old=None):return {'jp':jp,'spec':None,'ai_material':material,'ai_category':old}
    def test_plush_illustration_does_not_change_phone_stand_function(self):
        r=self.row('アクリルスマホスタンド 福原多聞（パーカーぬいぐるみ）','亚克力','毛绒')
        self.assertEqual(suggest(r)['value'],'站牌')
    def test_badge_with_plush_art_is_badge(self):self.assertEqual(suggest(self.row('缶バッジ（ぽてぬいアート）'))['value'],'徽章')
    def test_cardcase_function_beats_keyholder_word(self):self.assertEqual(suggest(self.row('カードケース キーホルダー付き'))['value'],'卡套')
    def test_coaster_function_uses_user_distinctions(self):
        self.assertEqual(suggest(self.row('ペーパーコースター','纸'))['value'],'收藏卡片')
        self.assertEqual(suggest(self.row('アクリルコースター','亚克力'))['value'],'挂牌')
        self.assertEqual(suggest(self.row('コースター','PVC'))['value'],'摆件')
        self.assertIsNone(suggest(self.row('コースター','纸、PP、亚克力'))['value'])
    def test_plush_age_and_chain_are_never_guessed(self):
        d=suggest(self.row('ぬいぐるみマスコット','聚酯纤维'))
        self.assertIsNone(d['value']);self.assertTrue(d['pending']);self.assertIn('年龄',d['basis'])
    def test_material_original_is_not_normalized_or_rewritten(self):
        r=self.row('クリアカード','纸,pp');before=deepcopy(r);suggest(r);self.assertEqual(r,before)
    def test_acrylic_clip_uses_user_display_type(self):self.assertEqual(suggest(self.row('アクリルクリップ'))['value'],'站牌')
    def test_reference_never_approves_business_type(self):self.assertFalse(suggest(self.row('アクリルスタンド'))['human_confirmation'])

class InsertingPhotoColumn(unittest.TestCase):
    def test_amount_references_follow_inserted_column(self):self.assertEqual(formula('J2*K2'),'K2*L2')
    def test_absolute_and_mixed_refs_remain_absolute_and_mixed(self):self.assertEqual(formula('$J2*K$2+$D$2'),'$K2*L$2+$D$2')
    def test_quoted_address_is_not_rewritten(self):self.assertEqual(formula('IF(A2="J2",J2,0)'),'IF(A2="J2",K2,0)')
    def test_unrelated_sheet_formulas_keep_own_columns(self):self.assertEqual(formula('B2*C2',False),'B2*C2')
    def test_other_sheet_reference_to_arrival_is_shifted(self):self.assertEqual(formula("'invoice (計算)'!L2",False),"'invoice (計算)'!M2")
    def test_named_range_and_filter_expand(self):self.assertEqual(reference("'invoice (計算)'!$B$1:$S$1313",False),"'invoice (計算)'!$B$1:$T$1313")
    def test_all_sheet_and_workbook_protection_removed(self):
        p={'xl/workbook.xml':b'<workbook><workbookProtection lockStructure="1"/></workbook>','xl/worksheets/sheet1.xml':b'<worksheet><sheetProtection sheet="1"/><sheetData/></worksheet>'};unprotect(p)
        self.assertNotIn(b'Protection',p['xl/workbook.xml']);self.assertNotIn(b'Protection',p['xl/worksheets/sheet1.xml'])
    def test_package_manifest_uses_excel_compatible_default_namespace(self):
        import xml.etree.ElementTree as ET
        ns='http://schemas.openxmlformats.org/package/2006/content-types';root=ET.Element('{'+ns+'}Types');ET.SubElement(root,'{'+ns+'}Default',{'Extension':'jpg','ContentType':'image/jpeg'})
        raw=package_xml(root,ns);self.assertIn(b'<Types xmlns=',raw);self.assertEqual(ET.fromstring(raw)[0].get('ContentType'),'image/jpeg')
if __name__=='__main__':unittest.main()
