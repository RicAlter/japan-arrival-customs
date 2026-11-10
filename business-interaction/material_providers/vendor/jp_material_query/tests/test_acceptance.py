# -*- coding: utf-8 -*-
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jpmaterial.batch import run_batch
from jpmaterial.input import read_input
from jpmaterial.models import OverallStatus, ProductQuery
from jpmaterial.output import write_excel
from tests.util import ROOT, FakeTransport, build_engine, read_fixture
from tests.test_output import make_input


class AcceptanceTests(unittest.TestCase):
    def test_01_historical_samples_parse(self):
        cases = json.loads((ROOT / "fixtures" / "historical_cases.json").read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 5)
        with TemporaryDirectory() as tmp:
            engine, *_ = build_engine(tmp)
            for case in cases:
                q = ProductQuery(jan=case["jan"], name_ja=case["name_ja"])
                r = engine.query_offline(q, ROOT / "fixtures" / "historical", site_ids=[case["site_id"]])
                self.assertEqual(r.status, OverallStatus.CANDIDATE_READY)
                self.assertEqual(r.recommended.material_original, case["material_original"])
                self.assertEqual(r.recommended.material_zh, case["material_zh"])

    def test_02_multi_component_lossless(self):
        cases = json.loads((ROOT / "fixtures" / "historical_cases.json").read_text(encoding="utf-8"))["cases"]
        multi = [c for c in cases if "、" in c["material_original"] or "," in c["material_original"]]
        self.assertGreaterEqual(len(multi), 3)
        for case in cases:
            self.assertTrue(case["material_zh"])
        for case in multi:
            self.assertIn("、", case["material_zh"])

    def test_03_version_mismatch_not_exact(self):
        with TemporaryDirectory() as tmp:
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, transport=FakeTransport([
                __import__("jpmaterial.transport", fromlist=["HttpResponse"]).HttpResponse(url="", status_code=200, text=read_fixture("negative", "version_mismatch.html"))
            ]))
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版", spec="通常版"), allow_online=True)
            self.assertNotEqual(r.match_status.value, "exact")
            self.assertIsNone(r.recommended)

    def test_04_network_error_not_no_material(self):
        with TemporaryDirectory() as tmp:
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, transport=FakeTransport([
                __import__("jpmaterial.transport", fromlist=["HttpResponse"]).HttpResponse(url="", status_code=None, error="network")
            ]))
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(r.status, OverallStatus.ERROR)
            self.assertNotEqual(r.status, OverallStatus.NO_MATERIAL)

    def test_05_unauthorized_no_request(self):
        with TemporaryDirectory() as tmp:
            transport = FakeTransport(fail_if_called=True)
            engine, *_ = build_engine(tmp, transport=transport)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(transport.calls, [])
            self.assertEqual(r.status, OverallStatus.NOT_AUTHORIZED)

    def test_06_input_not_modified(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            inp = tmp / "input.xlsx"
            make_input(inp)
            before = hashlib.sha256(inp.read_bytes()).hexdigest()
            engine, *_ = build_engine(tmp)
            rows = read_input(inp)
            batch = run_batch(engine, rows)
            write_excel(tmp / "out.xlsx", batch.results, batch.summary, input_path=str(inp), mode="offline_no_network")
            after = hashlib.sha256(inp.read_bytes()).hexdigest()
            self.assertEqual(before, after)
