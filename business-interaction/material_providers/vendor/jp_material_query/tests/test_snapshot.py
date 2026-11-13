# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jpmaterial.batch import run_batch
from jpmaterial.input import read_input
from jpmaterial.models import OverallStatus, ProductQuery
from tests.test_output import make_input
from tests.util import build_engine, read_fixture


class SnapshotTests(unittest.TestCase):
    def _write_snapshot(self, tmp: Path, site: str, jan: str):
        d = tmp / "snapshots" / site / jan
        d.mkdir(parents=True)
        (d / "detail.html").write_text(read_fixture("historical", "anime_store", "detail.html"), encoding="utf-8")
        return tmp / "snapshots"

    def test_snapshot_query_without_login_or_network(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snap = self._write_snapshot(tmp, "anime_store", "4571608537527")
            engine, *_ = build_engine(tmp)
            q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版")
            r = engine.query_snapshots(q, snap)
            self.assertEqual(r.status, OverallStatus.CANDIDATE_READY)
            self.assertEqual(r.recommended.material_zh, "纸、钢等")
            self.assertIn("未联网", r.attempts[0].message)

    def test_snapshot_missing_is_not_no_material(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "snapshots").mkdir()
            engine, *_ = build_engine(tmp)
            r = engine.query_snapshots(ProductQuery(jan="4571608537527", name_ja="テスト"), tmp / "snapshots")
            self.assertEqual(r.status, OverallStatus.NOT_CHECKED)
            self.assertEqual(r.action, "manual_snapshot")
            self.assertIn("未找到本地快照", r.reason)

    def test_batch_with_snapshot(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snap = self._write_snapshot(tmp, "anime_store", "4571608537527")
            inp = tmp / "input.xlsx"
            make_input(inp)
            engine, *_ = build_engine(tmp)
            rows = read_input(inp)
            batch = run_batch(engine, rows, snapshot_dir=str(snap))
            self.assertEqual(len(batch.results), 1)
            self.assertEqual(batch.results[0].status, OverallStatus.CANDIDATE_READY)
            self.assertEqual(batch.results[0].recommended.material_zh, "纸、钢等")
