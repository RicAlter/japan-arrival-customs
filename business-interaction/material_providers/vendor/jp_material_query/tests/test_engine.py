# -*- coding: utf-8 -*-
import unittest
from tempfile import TemporaryDirectory

from jpmaterial.adapters import LocalLibrary
from jpmaterial.models import MatchStatus, MaterialStatus, OverallStatus, ProductQuery
from tests.util import ROOT, build_engine, fixture, read_fixture


class EngineTests(unittest.TestCase):
    def test_offline_historical_cases(self):
        import json
        cases = json.loads((ROOT / "fixtures" / "historical_cases.json").read_text(encoding="utf-8"))["cases"]
        with TemporaryDirectory() as tmp:
            engine, *_ = build_engine(tmp)
            for case in cases:
                with self.subTest(case=case["case_id"]):
                    q = ProductQuery(jan=case["jan"], name_ja=case["name_ja"], name_zh="测试")
                    r = engine.query_offline(q, ROOT / "fixtures" / "historical", site_ids=[case["site_id"]])
                    self.assertEqual(r.status, OverallStatus.CANDIDATE_READY, r.reason)
                    self.assertIsNotNone(r.recommended)
                    self.assertEqual(r.recommended.material_original, case["material_original"])
                    self.assertEqual(r.recommended.material_zh, case["material_zh"])

    def test_local_library_priority(self):
        with TemporaryDirectory() as tmp:
            local = LocalLibrary.load(ROOT / "fixtures" / "local_library.json")
            engine, *_ = build_engine(tmp, local=local)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"))
            self.assertEqual(r.status, OverallStatus.CANDIDATE_READY)
            self.assertEqual(r.recommended.site_id, "local_library")
            self.assertEqual(r.recommended.material_zh, "纸")

    def test_local_conflict(self):
        with TemporaryDirectory() as tmp:
            local = LocalLibrary.load(ROOT / "fixtures" / "local_library.json")
            engine, *_ = build_engine(tmp, local=local)
            r = engine.query(ProductQuery(jan="4571608537534", name_ja="テスト フィギュア 通常版"))
            self.assertEqual(r.status, OverallStatus.CONFLICT)
            self.assertIsNone(r.recommended)

    def test_existing_material_skips(self):
        with TemporaryDirectory() as tmp:
            engine, *_ = build_engine(tmp)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト"), input_material="纸")
            self.assertEqual(r.status, OverallStatus.EXISTING_MATERIAL)
            self.assertEqual(r.action, "keep_existing")

    def test_version_mismatch_not_adopted(self):
        with TemporaryDirectory() as tmp:
            transport_responses = [
                __import__("jpmaterial.transport", fromlist=["HttpResponse"]).HttpResponse(
                    url="", status_code=200, text=read_fixture("negative", "version_mismatch.html")
                )
            ]
            from tests.util import FakeTransport
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, transport=FakeTransport(transport_responses))
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版", spec="通常版"), allow_online=True)
            self.assertEqual(r.status, OverallStatus.NEEDS_REVIEW)
            self.assertIsNone(r.recommended)
            self.assertIn("不一致", r.reason)

    def test_no_material_overall(self):
        with TemporaryDirectory() as tmp:
            from tests.util import FakeTransport
            from jpmaterial.transport import HttpResponse
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, enabled={"amnibus": False, "anime_store": True, "amiami": False, "jumpcs": False, "hobbysearch": False, "animate": False}, transport=FakeTransport([
                HttpResponse(url="", status_code=200, text=read_fixture("negative", "no_material.html"))
            ]))
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(r.status, OverallStatus.NO_MATERIAL)
            self.assertIsNone(r.recommended)

    def test_not_found_overall(self):
        with TemporaryDirectory() as tmp:
            from tests.util import FakeTransport
            from jpmaterial.transport import HttpResponse
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, enabled={"amnibus": False, "anime_store": True, "amiami": False, "jumpcs": False, "hobbysearch": False, "animate": False}, transport=FakeTransport([
                HttpResponse(url="", status_code=200, text=read_fixture("negative", "not_found.html"))
            ]))
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(r.status, OverallStatus.NOT_FOUND)

    def test_unauthorized_all_sites_no_request(self):
        with TemporaryDirectory() as tmp:
            from tests.util import FakeTransport
            transport = FakeTransport(fail_if_called=True)
            engine, *_ = build_engine(tmp, transport=transport)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True, all_sites=True)
            self.assertEqual(transport.calls, [])
            self.assertEqual(r.status, OverallStatus.NOT_AUTHORIZED)

    def test_partial_unauthorized_does_not_claim_no_material(self):
        with TemporaryDirectory() as tmp:
            from tests.util import FakeTransport
            from jpmaterial.transport import HttpResponse
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, enabled={"anime_store": True, "amiami": True, "jumpcs": True, "hobbysearch": True, "animate": False}, transport=FakeTransport([
                HttpResponse(url="", status_code=200, text=read_fixture("negative", "no_material.html"))
            ]))
            # 只有 anime_store 授权且启用，其余站点仍 unauthorized
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(r.status, OverallStatus.NOT_AUTHORIZED)
            self.assertIn("不能据此判定", r.reason)

    def test_conflict_between_sources(self):
        with TemporaryDirectory() as tmp:
            engine, *_ = build_engine(tmp)
            from jpmaterial.models import Evidence, QueryResult
            r = QueryResult(query=ProductQuery(jan="4571608537527", name_ja="テスト"))
            r.candidates = [
                Evidence(site_id="a", site_name="A", material_original="紙", material_zh="纸", match_status=MatchStatus.EXACT, material_status=MaterialStatus.FOUND),
                Evidence(site_id="b", site_name="B", material_original="PVC", material_zh="PVC", match_status=MatchStatus.EXACT, material_status=MaterialStatus.FOUND),
            ]
            engine._aggregate(r)
            self.assertEqual(r.status, OverallStatus.CONFLICT)
            self.assertIsNone(r.recommended)
