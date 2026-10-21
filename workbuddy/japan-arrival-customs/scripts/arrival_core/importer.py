"""KMT stage-3 adapter around the unchanged P0 OOXML parser."""
import csv
import json
from pathlib import Path

from . import _p0_frozen as p0
from .core import Rejected, new_batch, new_row


def import_stage3(path, *, currency, quantity_unit):
    if currency != "JPY":
        raise Rejected("当前KMT第3步模板标明日本JPY，其他币种需确认新适配合同")
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    book = p0.Book(data, str(path))
    sheet = book.sheets[0]
    cfg = p0.CONFIG[3]
    # Explicit adapter, not automatic template recognition. Reject another stage/template.
    headers = {col: p0.clean(sheet.v(1, col)) for col in ("C", "I", "J", "K", "L")}
    if not ("JAN" in headers["C"].upper() and headers["J"] == "Qty"
            and headers["K"] == "UnitPrice(日本JPY)" and headers["L"] == "Subtotal"):
        raise Rejected("不匹配KMT第3步模板；不自动猜列，请另行确认适配合同")
    records = p0.records(book, 3)
    indexed = {r["row"]: r for r in records}
    carry = None
    for ri in sorted(sheet.rows):
        if ri < cfg["start"]:
            continue
        current = sheet.v(ri, cfg["carton"])
        if p0.present(current):
            carry = current
        # P0 requires a code; this extension retains no-code named purchase rows.
        if ri not in indexed and not p0.present(sheet.v(ri, cfg["code"])):
            if any(p0.present(sheet.v(ri, cfg[k])) for k in ("ja", "internal")):
                r = {k: sheet.v(ri, col) for k, col in cfg.items() if k not in ("sheet", "start")}
                r.update(row=ri, sheet=sheet.name, code="", carton=current or carry)
                indexed[ri] = r
    if not indexed:
        raise Rejected("未发现商品明细")
    rows = []
    for ri, record in sorted(indexed.items()):
        cells = {}
        for field, col in cfg.items():
            if field not in ("sheet", "start"):
                c = sheet.cells.get(f"{col}{ri}", {})
                cells[field] = {"cell": f"{col}{ri}", "value": p0.text(c.get("v")),
                                "formula": c.get("f"), "type": c.get("type")}
        source = {"path": str(path), "sha256": book.sha256, "sheet": sheet.name,
                  "row": ri, "stage": 3, "cells": cells}
        raw = {k: (p0.text(v) if v is not None else None) for k, v in record.items()}
        row = new_row(source, raw, currency=currency, quantity_unit=quantity_unit)
        if not row["identity"]["code"]:
            row["identity"]["code_type"] = "absent_not_fabricated"
            row["disputes"].append({"id": "no_source_code", "domain": "identity",
                                    "reason": "无源编码，保留该行，人工确认身份/采购背景"})
        rows.append(row)
    if p0.sha(path.read_bytes()) != book.sha256:
        raise Rejected("读取期间原件发生变化")
    sources = [{"path": str(path), "sha256": book.sha256, "stage": 3}]
    return new_batch(rows, sources)


def attach_p0_findings(batch, directory):
    """Reuse the frozen findings only for the exact audited stage-3 hash."""
    directory = Path(directory)
    baseline = json.loads((directory / "acceptance_baseline.json").read_text(encoding="utf-8"))
    if batch["sources"][0]["sha256"] != baseline["sources"]["3"]["sha256"]:
        raise Rejected("P0证据与当前源文件版本不一致")
    with (directory / "details/review_candidates.csv").open(encoding="utf-8-sig", newline="") as f:
        findings = {int(r["stage3_row"]): r for r in csv.DictReader(f)}
    critical = {"historical_price_difference_pending_policy": "price",
                "packaging_conversion_needs_evidence": "packaging",
                "changed_product_code_identity_review": "identity"}
    for row in batch["rows"]:
        r = findings.get(row["source"]["row"])
        if r is None:
            raise Rejected("P0证据缺少当前明细")
        flags = json.loads(r["flags"])
        row["p0_findings"] = {"flags": flags, "issues": json.loads(r["issues"]),
                              "status": "historical_candidates_not_approval"}
        for flag in flags:
            if flag in critical:
                row["disputes"].append({"id": flag, "domain": critical[flag], "reason": flag})
        for issue in row["p0_findings"]["issues"]:
            row["disputes"].append({"id": issue, "domain": "product", "reason": issue})
    batch["p0_evidence"] = {name: p0.sha((directory / name).read_bytes()) for name in (
        "acceptance_baseline.json", "details/review_candidates.csv")}
    return batch
