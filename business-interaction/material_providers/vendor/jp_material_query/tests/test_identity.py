# -*- coding: utf-8 -*-
import unittest

from jpmaterial.identity import compare_identity, name_similarity, version_tokens
from jpmaterial.models import MatchStatus


class IdentityTests(unittest.TestCase):
    def test_exact(self):
        c = compare_identity("4571608537527", "テスト フィギュア 通常版", "通常版",
                             "4571608537527", "テスト フィギュア 通常版", "")
        self.assertEqual(c.status, MatchStatus.EXACT)
        self.assertEqual(c.name_score, 1.0)

    def test_version_mismatch(self):
        c = compare_identity("4571608537527", "テスト フィギュア 通常版", "通常版",
                             "4571608537527", "テスト フィギュア 限定版", "")
        self.assertEqual(c.status, MatchStatus.VERSION_MISMATCH)
        self.assertIn("通常版", " ".join(c.version_conflicts))

    def test_name_mismatch(self):
        c = compare_identity("4571608537527", "全く別の商品", "",
                             "4571608537527", "テスト フィギュア 通常版", "")
        self.assertEqual(c.status, MatchStatus.NAME_MISMATCH)

    def test_jan_mismatch(self):
        c = compare_identity("4571608537527", "テスト", "",
                             "4571608537534", "テスト", "")
        self.assertEqual(c.status, MatchStatus.JAN_MISMATCH)

    def test_missing_candidate_jan_never_exact(self):
        c = compare_identity("4571608537527", "テスト", "",
                             "", "テスト", "")
        self.assertEqual(c.status, MatchStatus.JAN_ONLY)

    def test_missing_query_jan(self):
        c = compare_identity("", "テスト", "", "4571608537527", "テスト", "")
        self.assertEqual(c.status, MatchStatus.INVALID_JAN)

    def test_similarity(self):
        self.assertGreater(name_similarity("テスト フィギュア 通常版", "テスト フィギュア 通常版"), 0.9)
        self.assertLess(name_similarity("テスト フィギュア", "全く別の商品"), 0.6)

    def test_version_tokens(self):
        self.assertIn("vol.2", version_tokens("第2弾 vol.2 通常版"))
        self.assertIn("第2弾", version_tokens("第2弾 vol.2 通常版"))
