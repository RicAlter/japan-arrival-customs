# -*- coding: utf-8 -*-
import json
import unittest

from jpmaterial.adapters import AmiAmiAdapter, AnimateAdapter, AnimeStoreAdapter, HobbySearchAdapter, JumpCharacterStoreAdapter
from jpmaterial.config import load_glossary, load_sites
from jpmaterial.models import AccessStatus, MatchStatus, MaterialStatus, ProductQuery
from tests.util import ROOT, read_fixture


def policies():
    return {p.site_id: p for p in load_sites(ROOT / "config" / "sites.json")}


def adapter(cls, site_id):
    return cls(policies()[site_id], load_glossary(ROOT / "config"))


class AdapterTests(unittest.TestCase):
    def test_anime_store(self):
        a = adapter(AnimeStoreAdapter, "anime_store")
        q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版")
        e = a.parse_detail(read_fixture("historical", "anime_store", "detail.html"), q)
        self.assertEqual(e.match_status, MatchStatus.EXACT)
        self.assertEqual(e.material_status, MaterialStatus.FOUND)
        self.assertEqual(e.material_original, "紙,スチール等")
        self.assertEqual(e.material_zh, "纸、钢等")
        self.assertEqual(e.jan_on_page, "4571608537527")
        self.assertEqual(e.size_text, "約H180×W120×D80mm")
        self.assertNotIn("180", e.material_original)
        self.assertIn("anime-store.jp/products/4571608537527", e.product_url)

    def test_amiami(self):
        a = adapter(AmiAmiAdapter, "amiami")
        q = ProductQuery(jan="4571608537534", name_ja="テスト フィギュア 通常版")
        refs = a.parse_search(read_fixture("historical", "amiami", "search.json"), q)
        self.assertGreaterEqual(len(refs), 2)
        e = a.parse_detail(read_fixture("historical", "amiami", "detail.json"), q, ref=refs[0])
        self.assertEqual(e.match_status, MatchStatus.EXACT)
        self.assertEqual(e.material_original, "Material: 100% Cotton")
        self.assertEqual(e.material_zh, "棉100%")
        self.assertIn("FIGURE-900001", e.product_url)

    def test_jumpcs(self):
        a = adapter(JumpCharacterStoreAdapter, "jumpcs")
        q = ProductQuery(jan="4530430123452", name_ja="テスト ブリキ缶 通常版")
        e = a.parse_detail(read_fixture("historical", "jumpcs", "detail.html"), q)
        self.assertEqual(e.match_status, MatchStatus.EXACT)
        self.assertEqual(e.material_original, "ブリキ、紙、鉄、PET")
        self.assertEqual(e.material_zh, "马口铁、纸、铁、PET塑料")

    def test_hobbysearch(self):
        a = adapter(HobbySearchAdapter, "hobbysearch")
        q = ProductQuery(jan="4571601234072", name_ja="テスト フィギュア 通常版")
        refs = a.parse_search(read_fixture("historical", "hobbysearch", "search.html"), q)
        self.assertTrue(refs)
        e = a.parse_detail(read_fixture("historical", "hobbysearch", "detail.html"), q, ref=refs[0])
        self.assertEqual(e.match_status, MatchStatus.EXACT)
        self.assertEqual(e.material_original, "本体：PVC・ABS")
        self.assertEqual(e.material_zh, "主体：PVC、ABS塑料")
        self.assertEqual(e.size_text, "約H180mm")

    def test_animate(self):
        a = adapter(AnimateAdapter, "animate")
        q = ProductQuery(jan="4901234567894", name_ja="テスト アクリルスタンド 通常版")
        refs = a.parse_search(read_fixture("historical", "animate", "search.html"), q)
        self.assertTrue(refs)
        e = a.parse_detail(read_fixture("historical", "animate", "detail.html"), q, ref=refs[0])
        self.assertEqual(e.match_status, MatchStatus.EXACT)
        self.assertEqual(e.material_zh, "亚克力、聚酯纤维")
        self.assertFalse(policies()["animate"].enabled)

    def test_not_found(self):
        a = adapter(AnimeStoreAdapter, "anime_store")
        q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版")
        e = a.parse_detail(read_fixture("negative", "not_found.html"), q)
        self.assertEqual(e.match_status, MatchStatus.NOT_FOUND)
        self.assertEqual(e.material_status, MaterialStatus.NOT_CHECKED)

    def test_size_only(self):
        a = adapter(AnimeStoreAdapter, "anime_store")
        q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版")
        e = a.parse_detail(read_fixture("negative", "no_material.html"), q)
        self.assertEqual(e.material_status, MaterialStatus.SIZE_ONLY)
        self.assertEqual(e.material_original, "")

    def test_version_mismatch(self):
        a = adapter(AnimeStoreAdapter, "anime_store")
        q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版", spec="通常版")
        e = a.parse_detail(read_fixture("negative", "version_mismatch.html"), q)
        self.assertEqual(e.match_status, MatchStatus.VERSION_MISMATCH)

    def test_jan_mismatch(self):
        a = adapter(AnimeStoreAdapter, "anime_store")
        q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版")
        e = a.parse_detail(read_fixture("negative", "jan_mismatch.html"), q)
        self.assertEqual(e.match_status, MatchStatus.JAN_MISMATCH)
