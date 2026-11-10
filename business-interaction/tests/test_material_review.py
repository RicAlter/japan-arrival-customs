import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from interaction.material_review import (review_materials, online_candidates,
                                         material_reference_candidate,
                                         apply_material_reference_overlay)


class DualSourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.file = self.root / 'input.xlsx'
        w = Workbook()
        s = w.active
        s.append(['ProductCode(JANCode)', 'DescriptionofGoods', '规格', '渠道', 'YD', '材质', '网站查找材质', '材质参考'])
        s.append(['4570000000001', '商品A', 'A1', '厂商', 'Y1', '人工棉', '既有R', '数据库展示原文'])
        s.append(['4570000000001', '商品A', 'A1', '厂商', 'Y1', None, None, None])
        s.append(['4570000000001', '商品B', 'B2', '厂商', 'Y1', None, None, None])
        w.save(self.file)
        self.db = self.root / 'library.sqlite3'
        with sqlite3.connect(self.db) as d:
            d.executescript('CREATE TABLE catalogue_entries(entry_id,descriptor_json); CREATE TABLE field_variants(entry_id,field_name,value_json); CREATE TABLE record_links(entry_id,provenance_json,raw_record_sha256);')
            d.execute('INSERT INTO catalogue_entries VALUES(?,?)', ('a', json.dumps({'code_raw': '4570000000001', 'japanese_name': '商品A', 'specification': 'A1', 'yd': 'Y1'})))
            d.execute('INSERT INTO field_variants VALUES(?,?,?)', ('a', 'material_original', json.dumps('棉100%')))
            d.execute('INSERT INTO record_links VALUES(?,?,?)', ('a', '{}', 'original-source-hash'))
        d.close()
        raw = self.root / 'response.html'
        raw.write_text('素材：綿100%', encoding='utf-8')
        self.manifest = self.root / 'candidates.json'
        self.candidate = {'jan': '4570000000001', 'material_original': '綿100%', 'material_zh': '棉100%', 'url': 'https://example.invalid/a', 'status': 200,
                          'snapshot': str(raw), 'content_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                          'match_status': 'exact_jan_name_spec', 'rows': [{'row': 2, 'jan': '4570000000001', 'name_ja': '商品A', 'spec': 'A1', 'yd': 'Y1'}]}
        self.manifest.write_text(json.dumps({'candidates': [self.candidate]}), encoding='utf-8')

    def request(self, name='run'):
        return {'input_file': str(self.file), 'database': str(self.db), 'output': str(self.root / name), 'evidence_manifests': [str(self.manifest)]}

    def test_all_rows_both_sources_and_duplicate_identity(self):
        before = self.file.read_bytes(), self.db.read_bytes()
        r = review_materials(None, self.request())
        self.assertEqual(r['summary']['rows'], 3)
        self.assertEqual(r['summary']['website'], {'found': 2, 'pending': 1})
        self.assertEqual(r['summary']['library'], {'sku_candidate': 2, 'reference_only': 1})
        report = json.loads(Path(r['reference_report']).read_text(encoding='utf-8'))
        self.assertEqual(report['rows']['2']['comparison'], 'same_text')
        self.assertEqual(report['rows']['2']['binding']['manual_material'], '人工棉')
        self.assertEqual((self.file.read_bytes(), self.db.read_bytes()), before)

    def test_conflicting_website_values_retained(self):
        c = {**self.candidate, 'material_zh': '聚酯纤维', 'material_original': 'ポリエステル'}
        self.manifest.write_text(json.dumps({'candidates': [self.candidate, c]}), encoding='utf-8')
        r = review_materials(None, self.request())
        self.assertEqual(r['summary']['website'], {'conflict': 2, 'pending': 1})

    def test_jan_only_evidence_is_not_verified_for_SKU_publication(self):
        self.candidate['match_status']='jan_only'
        self.manifest.write_text(json.dumps({'candidates':[self.candidate]}),encoding='utf-8')
        r=review_materials(None,self.request())
        self.assertEqual(r['summary']['website'],{'pending':3})

    def test_session_reuses_captured_evidence_defaults(self):
        config = self.root / 'session.json'
        config.write_text(json.dumps({'prepared_file': str(self.file), 'database': {'path': str(self.db)},
                          'material_review_settings': {'evidence_manifests': [str(self.manifest)], 'allow_online': False}}), encoding='utf-8')
        r = review_materials(config, {'output': str(self.root / 'from-session')})
        self.assertEqual(r['summary']['website'], {'found': 2, 'pending': 1})
        self.assertFalse(r['summary']['online_executed'])

    def test_bad_snapshot_cannot_be_used(self):
        Path(self.candidate['snapshot']).write_text('modified', encoding='utf-8')
        r = review_materials(None, self.request())
        self.assertEqual(r['summary']['website'], {'pending': 3})
        self.assertEqual(r['summary']['rejected_evidence'], 1)

    def test_online_requires_access_scope_and_budget(self):
        with self.assertRaises(Exception):
            online_candidates([], {'authorized': True}, self.root, {})

    def test_s_reference_distinguishes_exact_sku_and_yd_collection(self):
        self.assertEqual(material_reference_candidate({'status': 'sku_candidate', 'sku_material_values': ['棉100%']}),
                         ('棉100%', 'sku_exact'))
        self.assertEqual(material_reference_candidate({'status': 'reference_only', 'sku_material_values': [],
                                                        'yd_link_sources': [{'material_original': '亚克力'},
                                                                            {'material_original': '纸'}]}),
                         ('亚克力\n纸', 'yd_collection_reference'))
        self.assertEqual(material_reference_candidate({'status': 'reference_only', 'sku_material_values': [],
                                                        'yd_link_sources': []}), (None, 'unavailable'))

    def test_s_overlay_only_fills_blank_reference_and_never_writes_manual_o(self):
        table = self.root / 'overlay.xlsx'
        w = Workbook(); s = w.active; s.title = '核对'
        s.append(['A', 'B', 'ProductCode(JANCode)', 'D', 'E', 'F', '规格', 'H', 'I',
                  'DescriptionofGoods', 'K', 'L', 'M', 'N', '材质', 'P', 'YD',
                  '网站查找材质', '材质参考', 'T'])
        s.append(['', '', '4570000000001', '', '', '', 'A1', '', '', '商品A', '', '', '', '',
                  '人工棉', '', 'Y1', '', '', ''])
        s.append(['', '', '4570000000002', '', '', '', 'B2', '', '', '商品B', '', '', '', '',
                  '人工纸', '', 'Y2', '', '已有S', ''])
        w.save(table)
        report = self.root / 'overlay-report.json'
        report.write_text(json.dumps({'rows': {
            '2': {'binding': {'jan': '4570000000001', 'spec': 'A1', 'name_ja': '商品A', 'yd': 'Y1'},
                  'library': {'status': 'reference_only', 'sku_material_values': [],
                              'yd_link_sources': [{'material_original': '纸'}, {'material_original': '亚克力'}]}},
            '3': {'binding': {'jan': '4570000000002', 'spec': 'B2', 'name_ja': '商品B', 'yd': 'Y2'},
                  'library': {'status': 'sku_candidate', 'sku_material_values': ['PVC'],
                              'yd_link_sources': []}}
        }}), encoding='utf-8')
        result = apply_material_reference_overlay(
            {'prepared_file': str(table), 'background': str(self.root), 'sheet': '核对'},
            {'reference_report': str(report)})
        check = __import__('openpyxl').load_workbook(table, data_only=True)['核对']
        self.assertEqual(check['S2'].value, '亚克力\n纸')
        self.assertEqual(check['S3'].value, '已有S')
        self.assertEqual(check['O2'].value, '人工棉')
        self.assertEqual(check['O3'].value, '人工纸')
        self.assertEqual(result['written_cells'], 1)

    def test_resume_and_changed_input_rejected(self):
        review_materials(None, self.request())
        r = review_materials(None, self.request())
        self.assertEqual(r['summary']['rows'], 3)
        w = Workbook(); w.save(self.file)
        with self.assertRaises(Exception):
            review_materials(None, self.request())


if __name__ == '__main__':
    unittest.main()
