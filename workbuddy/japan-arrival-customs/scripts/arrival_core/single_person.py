"""Token-free single-person business confirmation.

This path is intentionally narrower than B2's trusted D08 approval path.  It
persists an explicitly confirmed product-data revision and optional host-context
trace, but it cannot approve material/classification/tax/packaging, create a D1
learning event, lock a batch, or enable a formal output.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from .core import Rejected, changed, digest, now, product_disputes, product_errors_for_batch, _patch_product
from .excel_return import read_json, sha
from .storage import atomic_json, check_sources


def operator_context():
    """Use host-provided metadata when present; never accept it from Excel/request."""
    principal = os.environ.get("WORKBUDDY_OPERATOR_ID", "").strip()
    session = os.environ.get("WORKBUDDY_SESSION_ID", "").strip()
    if principal and session:
        return {"source": "workbuddy_host_context", "principal": principal,
                "session_ref": session, "identity_assurance": "host_context_unverified_by_skill"}
    return {"source": "operator_context_unavailable", "principal": None,
            "session_ref": None, "identity_assurance": "unverified_local_confirmation"}


def _allowed(preview):
    if preview["operations"]:
        raise Rejected("单人确认只保存商品基础资料；材质、归类、税率、盒规仍须走专业受控流程")
    if not preview["proposals"]:
        raise Rejected("没有可保存的基础商品资料差异")
    permitted = {"internal_name", "customs_name", "category", "channel", "yd", "yd_absence_reason"}
    if any(item["action"] != "edit_product" or item.get("unparsed_note")
           or not item.get("values") or set(item["values"]) - permitted
           for item in preview["proposals"]):
        raise Rejected("单人确认只能保存结构化商品资料；未解析文本或专业选择保持待确认")


def commit_business_confirmation(service, preview_id, *, confirmed_hash, explicit_confirmation, reference):
    if explicit_confirmation is not True or confirmed_hash != preview_id or not isinstance(reference, str) or not reference.strip():
        raise Rejected("须明确确认已展示的差异版本后才能保存本次业务资料")
    preview = read_json(service._path("previews", preview_id))
    if digest(preview) != preview_id:
        raise Rejected("预览登记被修改")
    _allowed(preview)
    batch = service.store.load(preview["batch_id"])
    check_sources(batch)
    if sha(Path(preview['upload_file']).read_bytes()) != preview['upload_sha256']:
        raise Rejected('回传归档已变更')
    context = operator_context()
    transaction = digest({"kind": "single_person_business_confirmation", "preview_id": preview_id,
                          "upload": preview["upload_sha256"], "reference": reference, "operator": context})
    if transaction in batch.get("single_person_receipts", {}):
        return dict(batch["single_person_receipts"][transaction], replayed=True, current_hash=digest(batch))
    if digest(batch) != preview["base_hash"]:
        raise Rejected("预览已过期；请重新导出并查看差异")
    rebuilt = service.preview(preview["upload_file"], export_id=preview["export_id"], operations=[])
    if rebuilt["preview_id"] != preview_id:
        raise Rejected("回传内容与已展示预览不一致")
    out = copy.deepcopy(batch)
    out['product_data_policy'] = 'single-person-v1'
    rows = {row["id"]: row for row in out["rows"]}
    touched = set()
    for proposal in preview["proposals"]:
        for row_id in proposal["row_ids"]:
            row = rows[row_id]
            if row.get('declaration') and set(proposal['values']) & {'category', 'customs_name'}:
                raise Rejected('已有申报决定的品类/申报品名更正须使用B2关联失效流程')
            for field, value in proposal["values"].items():
                if field not in {"internal_name", "customs_name", "category", "channel", "yd", "yd_absence_reason"}:
                    raise Rejected("单人确认不能写入非商品基础字段")
            _patch_product(row, proposal['values'])
            touched.add(row_id)
        out.setdefault("return_issue_notes", []).append(proposal)
    # Confirmation is deliberately limited to ordinary, complete product facts.
    confirmed = []
    for row_id in sorted(touched):
        row = rows[row_id]
        if not product_errors_for_batch(out, row) and not product_disputes(row):
            row["reviews"]["product"] = {"confirmed_by": context["principal"], "confirmed_at": now(),
                                           "reference": reference, "mode": "single_person_business_confirmation",
                                           "identity_assurance": context["identity_assurance"]}
            confirmed.append(row_id)
    receipt = {"kind": "single_person_business_confirmation", "transaction_id": transaction,
               "preview_id": preview_id, "upload_sha256": preview["upload_sha256"],
               "operator": context, "reference": reference, "saved_product_rows": sorted(touched),
               "confirmed_product_rows": confirmed, "professional_approvals": 0, "decision_events": 0,
               "formal_output": False, "d1_learning_eligible": False}
    library = out.get("product_library") or out.get("input_contract", {}).get("product_library")
    library_receipt = {"status": "not_configured"}
    if library and library.get("path"):
        records = [{"sheet": "arrival_skill_queue", "row": index,
                    "code": row["identity"].get("code", ""), "japanese_name": row["identity"].get("japanese_name", ""),
                    "version": row["identity"].get("version", ""), "internal_name": row["product"].get("internal_name", ""),
                    "customs_name": row["product"].get("customs_name", ""), "category": row["product"].get("category", ""),
                    "channel": row["product"].get("channel", ""), "yd": row["product"].get("yd", ""), "packaging_label": ""}
                   for index, row in enumerate((rows[row_id] for row_id in sorted(touched)), 1) if row["identity"].get("code")]
        queue_id = transaction
        queue = {"kind": "product_maintenance_queue", "queue_id": queue_id, "library": library,
                 "batch_id": out["id"], "batch_revision": out["revision"] + 1,
                 "records": records, "confirmation": {"kind": "product_maintenance_queue", "queue_id": queue_id,
                 "reference": reference, "arrival_transaction": transaction, "source_batch": out["id"]}}
        queue_path = service.store.root / "product_maintenance_queue" / (queue_id + ".json")
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(queue_path, queue)
        library_receipt = {"status": "queued_for_product_maintenance", "queue_file": str(queue_path),
                           "records": len(records), "database_written_by_arrival_skill": False}
    receipt["product_library_write"] = library_receipt
    out.setdefault("single_person_receipts", {})[transaction] = receipt
    out = changed(batch, out, context["principal"] or "single_person_unverified", "single_person_business_confirmation",
                  sorted(touched), receipt)
    service.store.save(out, expected_hash=digest(batch))
    return dict(receipt, replayed=False, current_hash=digest(out), product_library=library_receipt)
