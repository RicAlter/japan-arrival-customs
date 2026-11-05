import unittest,tempfile,json
from pathlib import Path
from dataclasses import replace
from a_assets.rules import ProductSource,name_candidate,yd_candidate,material_candidate
from a_assets.archive import archive_files,verify_archive,resolve_archived,sha

class Rules(unittest.TestCase):
    def setUp(self):
        self.source=ProductSource('4900000000001','YD-SYNTHETIC','合成系列商品名','合成角色A','synthetic-source!D2')
    def test_name_uses_product_field_and_keeps_sku_separate(self):
        r=name_candidate('4900000000001','YD-SYNTHETIC',self.source)
        self.assertEqual((r['product_name'],r['specification']),('合成系列商品名','合成角色A'))
        self.assertFalse(r['confirmed']);self.assertFalse(r['professional_approval'])
    def test_sku_cannot_replace_missing_product_name(self):
        with self.assertRaises(ValueError):name_candidate(self.source.jan,self.source.yd,replace(self.source,product_name=None))
    def test_same_yd_different_jan_is_rejected(self):
        with self.assertRaises(ValueError):name_candidate('4900000000002',self.source.yd,self.source)
    def test_same_jan_different_yd_is_rejected(self):
        with self.assertRaises(ValueError):name_candidate(self.source.jan,'OTHER',self.source)
    def test_DG_alias_is_YD_only(self):
        r=yd_candidate(self.source.jan,'DG'+self.source.jan,self.source.yd,'synthetic-source!A2')
        self.assertEqual(r['scope'],['yd']);self.assertFalse(r['quantity_price_packaging_transfer'])
        with self.assertRaises(ValueError):name_candidate(self.source.jan,self.source.yd,replace(self.source,jan='DG'+self.source.jan))
    def test_screenshot_override_needs_evidence(self):
        with self.assertRaises(ValueError):name_candidate(self.source.jan,self.source.yd,self.source,override='更正标题')
        r=name_candidate(self.source.jan,self.source.yd,self.source,override='更正标题',override_evidence='synthetic-user-image-sha256')
        self.assertEqual(r['product_name'],'更正标题');self.assertFalse(r['confirmed'])
    def test_empty_yd_does_not_make_name_match(self):
        with self.assertRaises(ValueError):name_candidate(self.source.jan,'',replace(self.source,yd=''))
    def test_link_material_scope_must_match(self):
        with self.assertRaises(ValueError):material_candidate('A','B','纸',link_scope_authorization='user-synthetic')
        with self.assertRaises(ValueError):material_candidate('A','A','纸')
    def test_ambiguous_material_is_retained_pending(self):
        r=material_candidate('A','A','纸,PP',link_scope_authorization='user-synthetic')
        self.assertEqual(r['value'],'纸,PP');self.assertEqual(r['display_color'],'red');self.assertFalse(r['can_enter_b'])
    def test_material_selection_requires_category_and_evidence(self):
        r=material_candidate('A','A','马口铁,亚克力',selected='亚克力',product_category='立牌',category_evidence='synthetic-row!I2',selection_evidence='synthetic-user-category-map',link_scope_authorization='synthetic-user-scope')
        self.assertEqual(r['value'],'亚克力');self.assertEqual(r['original_text'],'马口铁,亚克力');self.assertFalse(r['professional_approval'])
    def test_material_outside_link_source_is_rejected(self):
        with self.assertRaises(ValueError):
            material_candidate('A','A','马口铁,亚克力',selected='PP',product_category='透卡',category_evidence='synthetic-row!I2',selection_evidence='synthetic-user-map',link_scope_authorization='synthetic-user-scope')

class Archive(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.a=self.root/'a.xlsx';self.a.write_bytes(b'synthetic xlsx bytes; no real workbook')
    def tearDown(self):self.tmp.cleanup()
    def item(self,p,role='reference'):
        return {'path':str(p),'role':role,'sha256':sha(p)}
    def run_archive(self,items):
        return archive_files({'schema':'a-stage-explicit-assets/1','files':items},self.root/'archive')
    def test_originals_preserved_and_aliases_not_independent(self):
        b=self.root/'b.xlsx';b.write_bytes(self.a.read_bytes());before=sha(self.a)
        m=self.run_archive([self.item(self.a),self.item(b,'process')])
        self.assertEqual(m['unique_contents'],1);self.assertEqual(m['physical_entries'],2)
        self.assertEqual(sha(self.a),before);self.assertTrue(verify_archive(m))
    def test_same_filename_different_contents_preserves_versions(self):
        other=self.root/'other';other.mkdir();b=other/'a.xlsx';b.write_bytes(b'different synthetic contents')
        m=self.run_archive([self.item(self.a),self.item(b)])
        self.assertEqual(m['unique_contents'],2)
        self.assertNotEqual(m['records'][0]['archive_relative_path'],m['records'][1]['archive_relative_path'])
    def test_changed_source_rejected_before_archive_creation(self):
        item=self.item(self.a);self.a.write_bytes(b'changed synthetic source')
        with self.assertRaises(ValueError):self.run_archive([item])
        self.assertFalse((self.root/'archive').exists())
    def test_existing_archive_never_overwritten(self):
        self.run_archive([self.item(self.a)])
        with self.assertRaises(ValueError):self.run_archive([self.item(self.a)])
    def test_tampered_archive_rejected(self):
        m=self.run_archive([self.item(self.a)]);p=resolve_archived(m,str(self.a),sha(self.a));p.write_bytes(b'tampered')
        with self.assertRaises(ValueError):verify_archive(m)
    def test_path_traversal_rejected(self):
        m=self.run_archive([self.item(self.a)]);m['records'][0]['archive_relative_path']='../a.xlsx'
        with self.assertRaises(ValueError):verify_archive(m)
    def test_old_version_is_resolved_after_original_changes(self):
        oldsha=sha(self.a);m=self.run_archive([self.item(self.a)]);self.a.write_bytes(b'new source version')
        self.assertEqual(sha(resolve_archived(m,str(self.a),oldsha)),oldsha)
        with self.assertRaises(ValueError):resolve_archived(m,str(self.a),sha(self.a))
    def test_contradictory_duplicate_declarations_rejected(self):
        item=self.item(self.a);wrong={**item,'sha256':'0'*64}
        with self.assertRaises(ValueError):self.run_archive([item,wrong])

if __name__=='__main__':unittest.main()
