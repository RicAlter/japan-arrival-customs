# -*- coding: utf-8 -*-
import unittest

from jpmaterial.material import extract_material, is_size_only, looks_like_material
from jpmaterial.translate import translate_material


class MaterialExtractionTests(unittest.TestCase):
    def test_anime_bullet_label_and_size_separation(self):
        html = """<table>
        <tr><th>JANコード</th><td>4571608537527</td></tr>
        <tr><th>■素材</th><td>紙,スチール等</td></tr>
        <tr><th>サイズ</th><td>約H180×W120×D80mm</td></tr>
        </table>"""
        e = extract_material(html)
        self.assertTrue(e.found)
        self.assertEqual(e.original, "紙,スチール等")
        self.assertIn("180", e.size_text)
        self.assertNotIn("180", e.original)

    def test_label_next_line(self):
        e = extract_material("商品仕様\n素材\nPVC・ABS\nサイズ\n約H100mm")
        self.assertTrue(e.found)
        self.assertEqual(e.original, "PVC・ABS")

    def test_body_field(self):
        e = extract_material("素材：本体：PVC・ABS\nサイズ：約H180mm")
        self.assertTrue(e.found)
        self.assertIn("PVC", e.original)

    def test_material_english_label(self):
        e = extract_material("Material: 100% Cotton\nSize: H180mm")
        self.assertTrue(e.found)
        self.assertEqual(e.original, "Material: 100% Cotton")

    def test_size_only(self):
        e = extract_material("サイズ：約H180×W120×D80mm")
        self.assertFalse(e.found)
        self.assertTrue(e.size_text)
        self.assertTrue(is_size_only("約H180×W120×D80mm"))

    def test_no_material(self):
        e = extract_material("テスト商品\nJANコード：4571608537527")
        self.assertFalse(e.found)
        self.assertEqual(e.original, "")

    def test_multi_component_not_lost(self):
        e = extract_material("素材：ブリキ、紙、鉄、PET")
        self.assertEqual(e.original, "ブリキ、紙、鉄、PET")
        self.assertEqual(translate_material(e.original).zh, "马口铁、纸、铁、PET塑料")

    def test_material_hint(self):
        self.assertTrue(looks_like_material("PVC・ABS"))
        self.assertTrue(looks_like_material("紙,スチール等"))
        self.assertFalse(looks_like_material("約H180mm"))


class TranslationTests(unittest.TestCase):
    def test_historical_cases(self):
        cases = {
            "紙,スチール等": "纸、钢等",
            "Material: 100% Cotton": "棉100%",
            "ブリキ、紙、鉄、PET": "马口铁、纸、铁、PET塑料",
            "本体：PVC・ABS": "主体：PVC、ABS塑料",
            "アクリル、ポリエステル": "亚克力、聚酯纤维",
        }
        for src, expected in cases.items():
            with self.subTest(src=src):
                self.assertEqual(translate_material(src).zh, expected)

    def test_keep_unknown_japanese(self):
        r = translate_material("ポリ乳酸、紙")
        self.assertIn("ポリ乳酸", r.zh)
        self.assertIn("纸", r.zh)
        self.assertIn("ポリ乳酸", r.unknown_terms)

    def test_percentage(self):
        self.assertEqual(translate_material("綿100%").zh, "棉100%")
        self.assertEqual(translate_material("Polyester 100%").zh, "聚酯纤维100%")

    def test_chinese_passthrough(self):
        self.assertEqual(translate_material("纸、钢等").zh, "纸、钢等")

    def test_does_not_add_components(self):
        r = translate_material("紙")
        self.assertEqual(r.zh, "纸")
        self.assertNotIn("塑料", r.zh)
