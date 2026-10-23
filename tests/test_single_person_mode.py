import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workbuddy" / "japan-arrival-customs" / "scripts"))

from arrival_core.core import digest, new_batch, new_row, product_errors_for_batch
from arrival_core.excel_return import ReturnService
from arrival_core.product_library import ProductLibrary
from arrival_core.single_person import _allowed, commit_business_confirmation
from arrival_core.storage import atomic_json


class SinglePersonModeTests(unittest.TestCase):
    def _batch(self, directory, source_directory=None):
        source_file = Path(source_directory or directory) / "source.xlsx"
        source_file.write_bytes(b"source-file")
        source = {"path": str(source_file), "sha256": __import__("hashlib").sha256(source_file.read_bytes()).hexdigest(),
                  "sheet": "invoice (計算)", "row": 18,
                  "cells": {"amount": {"value": "100"}, "quantity": {"value": "2"}}}
        row = new_row(source, {"code": "4900000000001", "ja": "テスト商品", "qty": "2", "amount": "100", "price": "50"},
                      currency="JPY", quantity_unit="", authority_stage=1,
                      authority_status="preliminary_from_raw_invoice", amount_basis="raw_invoice_subtotal")
        batch = new_batch([row], [source])
        batch["product_review_profile"] = "exception-first-v1"
        batch['product_data_policy'] = 'single-person-v1'
        return batch

    def test_exception_profile_does_not_make_internal_yd_a_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = self._batch(directory)
            errors = product_errors_for_batch(batch, batch["rows"][0])
        self.assertIn("missing_internal_name", errors)
        self.assertNotIn("yd_absence_reason_required", errors)

    def test_rejects_professional_or_unparsed_changes(self):
        with self.assertRaisesRegex(ValueError, "专业受控流程"):
            _allowed({"operations": [{"action": "approve_material"}], "proposals": []})
        with self.assertRaisesRegex(ValueError, "结构化商品资料"):
            _allowed({"operations": [], "proposals": [{"action": "edit_product", "unparsed_note": "猜测"}]})

    def test_one_confirmation_creates_revision_and_candidate_only_library_record(self):
        with tempfile.TemporaryDirectory() as directory:
          with tempfile.TemporaryDirectory() as source_directory:
            root = Path(directory) / "state"
            root.mkdir()
            batch = self._batch(directory, source_directory)
            library = ProductLibrary.create(Path(directory) / "product-library.sqlite3")
            batch["product_library"] = {"path": str(library.path)}
            service = ReturnService(root)
            service.store.save(batch)
            export_id = "a" * 64
            uploaded = root / "uploaded.xlsx"
            uploaded.write_bytes(b"controlled-upload")
            preview = {"contract": "test", "export_id": export_id, "batch_id": batch["id"],
                       "base_hash": digest(batch), "upload_sha256": __import__("hashlib").sha256(uploaded.read_bytes()).hexdigest(),
                       "upload_file": str(uploaded), "edits": [], "operations": [], "issue_notes": [],
                       "decision_differences": [], "base_is_current": True,
                       "proposals": [{"action": "edit_product", "row_ids": [batch["rows"][0]["id"]],
                                      "values": {"internal_name": "测试中文名", "customs_name": "测试申报品名", "category": "玩具"},
                                      "reason": "", "reference": "业务核对", "unparsed_note": "", "issue_id": "Q001"}]}
            preview_id = digest(preview)
            preview_path = service._path("previews", preview_id)
            preview_path.parent.mkdir(parents=True)
            atomic_json(preview_path, preview)
            service.preview = lambda *_args, **_kwargs: dict(preview, preview_id=preview_id)
            with patch.dict(os.environ, {"WORKBUDDY_OPERATOR_ID": "", "WORKBUDDY_SESSION_ID": ""}):
                receipt = commit_business_confirmation(service, preview_id, confirmed_hash=preview_id,
                                                      explicit_confirmation=True, reference="本票业务确认")
                replay = commit_business_confirmation(service, preview_id, confirmed_hash=preview_id,
                                                       explicit_confirmation=True, reference="本票业务确认")
                self.assertTrue(replay['replayed'])
            saved = service.store.load(batch["id"])
            row = saved["rows"][0]
            self.assertFalse(receipt["formal_output"])
            self.assertFalse(receipt["d1_learning_eligible"])
            self.assertEqual(receipt["professional_approvals"], 0)
            self.assertEqual(row["product"]["customs_name"], "测试申报品名")
            self.assertEqual(row["reviews"]["product"]["mode"], "single_person_business_confirmation")
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(library.lookup("4900000000001")["candidates"]["customs_name"], "测试申报品名")
            self.assertFalse(library.statistics()["declaration_decisions_stored"])


if __name__ == "__main__":
    unittest.main()
