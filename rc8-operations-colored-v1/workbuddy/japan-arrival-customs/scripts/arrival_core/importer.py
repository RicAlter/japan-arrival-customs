"""KMT stage-3 and genuine raw-invoice adapters around the frozen OOXML parser."""
import csv
import json
from pathlib import Path

from . import _p0_frozen as p0
from .core import Rejected, new_batch, new_row

RAW_SHEET = "invoice (計算)"
# Both layouts below are observed KMT raw-invoice layouts.  They are explicit
# header contracts, not positional inference.  The second is the genuine KMT
# source preserved in inputs/, while the first remains needed for rc.4 runs.
RAW_LAYOUTS = (
    {"headers": {"C": "ProductCode(JANCode)", "D": "DescriptionofGoods", "G": "Origin",
                 "H": "UnitPrice(日本JPY)", "I": "Qty", "K": "Subtotal"},
     "columns": {"carton": "A", "code": "C", "ja": "D", "origin": "G", "price": "H", "qty": "I", "amount": "K"},
     "id": "kmt-raw-invoice-v1"},
    {"headers": {"D": "ProductCode(JANCode)", "H": "DescriptionofGoods", "K": "Origin",
                 "L": "UnitPrice(日本JPY)", "M": "Qty", "O": "Subtotal"},
     "columns": {"carton": "A", "code": "D", "ja": "H", "origin": "K", "price": "L", "qty": "M", "amount": "O"},
     "id": "kmt-raw-invoice-v2"},
)


def raw_invoice_layout(book):
    sheet = next((s for s in book.sheets if s.name == RAW_SHEET), None)
    if sheet is None:
        return None
    for layout in RAW_LAYOUTS:
        if all(p0.clean(sheet.v(17, col)) == label for col, label in layout["headers"].items()):
            return sheet, layout
    return None


def import_raw_invoice(path, *, currency="JPY", quantity_unit=""):
    """Read the genuine Japanese workbook without inventing a stage-3 authority file.

    Qty and Subtotal are source observations.  The unit remains unknown until an
    exact product/procurement record or a controlled contract supplies it.
    """
    if currency != "JPY":
        raise Rejected("当前日方原表明确为日本JPY；其他币种须建立新模板合同")
    path = Path(path).resolve(strict=True); data = path.read_bytes()
    book = p0.Book(data, str(path)); layout = raw_invoice_layout(book)
    if layout is None:
        raise Rejected("不匹配KMT日方原始发票模板：需要已支持的invoice (計算)第17行完整表头布局")
    sheet, layout = layout; columns = layout["columns"]
    rows=[]; carry=None
    for ri in sorted(sheet.rows):
        if ri < 18: continue
        carton = sheet.v(ri, "A")
        if p0.present(carton): carry=carton
        code=sheet.v(ri,columns["code"]); description=sheet.v(ri,columns["ja"])
        qty=sheet.v(ri,columns["qty"]); amount=sheet.v(ri,columns["amount"])
        # TOTAL and auxiliary calculation rows are not商品明细.  A legitimate
        # no-code purchase is retained when it has a description and Qty/Subtotal.
        if p0.clean(sheet.v(ri,"G")).upper()=="TOTAL": continue
        if not (p0.present(code) or p0.present(description)): continue
        if not (p0.present(qty) or p0.present(amount)): continue
        raw={field:sheet.v(ri,col) for field,col in columns.items()}
        raw.update(internal=None,variant=None,category=None,material=None,channel=None,yd=None)
        if not p0.present(raw["carton"]): raw["carton"]=carry
        cells={}
        for field,col in columns.items():
            cell=sheet.cells.get(f"{col}{ri}",{})
            cells[field]={"cell":f"{col}{ri}","column":col,
                          "value":p0.text(cell.get("v")),"formula":cell.get("f"),"type":cell.get("type")}
        source={"path":str(path),"sha256":book.sha256,"sheet":sheet.name,"row":ri,
                "stage":1,"template":layout["id"],"cells":cells}
        serialized={k:(p0.text(v) if v is not None else None) for k,v in raw.items()}
        row=new_row(source,serialized,currency=currency,quantity_unit=quantity_unit,
                    authority_stage=1,authority_status="preliminary_from_raw_invoice",
                    amount_basis="raw_invoice_subtotal")
        row["identity"]["code_type"]="raw_source_identifier" if row["identity"]["code"] else "absent_not_fabricated"
        row["arrival"]["quantity_meaning"]="warehouse_counted_largest_received_unit"
        row["arrival"]["unit_evidence"] = None
        row["arrival"]["packaging_content"] = None
        row["arrival"]["declaration_quantity"] = None
        row["arrival"]["declaration_unit"] = None
        row["product_lookup"]={"status":"not_configured","matched_records":[],
                               "notice":"未配置已授权的开定/商品资料来源；中文名、品类、YD、材质及单位保持待补"}
        if not row["identity"]["code"]:
            row["disputes"].append({"id":"no_source_code","domain":"identity",
                                    "reason":"日方原表无商品编码；保留原行，不能虚构JAN"})
        for key in ("qty","amount"):
            if p0.numeric_text(raw[key]) is None:
                row["disputes"].append({"id":"invalid_raw_"+key,"domain":"price",
                                        "reason":"日方原表"+("Qty" if key=="qty" else "Subtotal")+"不是有效数值"})
        rows.append(row)
    if not rows: raise Rejected("日方原表未发现商品明细")
    if p0.sha(path.read_bytes()) != book.sha256: raise Rejected("读取期间原件发生变化")
    batch=new_batch(rows,[{"path":str(path),"sha256":book.sha256,"stage":1,
                           "kind":"kmt-raw-invoice-v1","layout":layout["id"],"sheet":sheet.name}])
    batch["input_mode"]="raw_invoice_preliminary"
    batch["arrival_summary"]={"rows":len(rows),"subtotal_jpy":str(sum((p0.numeric_text(r["raw"]["amount"])
        for r in rows if p0.numeric_text(r["raw"]["amount"]) is not None),p0.Decimal(0))),
        "qty_numeric_sum":str(sum((p0.numeric_text(r["raw"]["qty"])
        for r in rows if p0.numeric_text(r["raw"]["qty"]) is not None),p0.Decimal(0))),
        "qty_common_unit":None,"amount_status":"preliminary_arrival_subtotal_not_final_declaration_amount",
        "product_reference_matches":0,"product_reference_pending":len(rows)}
    return batch


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
