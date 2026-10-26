"""P1-B connects original inputs and historical candidates to the existing unified detail."""
import copy
from collections import Counter
from fractions import Fraction
from pathlib import Path

from . import _p0_frozen as p0
from . import __version__
from .contracts import contract_status, quantity_unit, validate_contract
from .core import (DOMAINS, Rejected, box_tax, decimal, digest, exact_price, product_errors,
                   review_package, validate, product_errors_for_batch)
from .importer import import_stage3, import_raw_invoice
from .logistics import read_weights, reconcile_logistics


def read_stage(path, stage):
    path = Path(path).resolve(strict=True)
    book = p0.Book(path.read_bytes(), str(path))
    sheet = book.sheets[0]
    if stage == 1 and not ("JAN" in p0.clean(sheet.v(17, "D")) and p0.clean(sheet.v(17, "M")) == "Qty"):
        raise Rejected("日方原表不匹配KMT原始模板")
    if stage == 5 and not (p0.clean(sheet.v(1, "A")) == "箱号" and "Descriptions" in p0.clean(sheet.v(1, "C"))):
        raise Rejected("申报历史参考表不匹配KMT第5步模板")
    if stage == 6 and not ("JAN" in p0.clean(sheet.v(1, "C")) and p0.clean(sheet.v(1, "H")) == "盒装数"):
        raise Rejected("内部历史参考表不匹配KMT第6步模板")
    rows = p0.records(book, stage)
    cfg = p0.CONFIG[stage]; seen = {r["row"] for r in rows}; carry = None
    for ri in sorted(sheet.rows):
        if ri < cfg["start"]:
            continue
        cv = sheet.v(ri, cfg["carton"])
        if p0.present(cv): carry = cv
        if ri in seen or p0.present(sheet.v(ri, cfg["code"])):
            continue
        if any(p0.present(sheet.v(ri, cfg[k])) for k in ("ja", "internal", "customs_name") if k in cfg):
            row = {k: sheet.v(ri, col) for k,col in cfg.items() if k not in ("sheet", "start")}
            row.update(row=ri, sheet=sheet.name, sha256=book.sha256, file=str(path), code="", carton=cv or carry)
            row["carton_key"] = p0.carton(row["carton"])
            rows.append(row)
    return book, sorted(rows, key=lambda r:r["row"])


def serial(record):
    return {k: (p0.text(v) if v is not None else None) for k,v in record.items()}


def import_batch(contract):
    contract = copy.deepcopy(validate_contract(contract))
    files = contract["sources"]
    if contract.get("input_mode")=="raw_invoice_preliminary":
        return import_raw_batch(contract)
    batch = import_stage3(files["authority"]["path"], currency=contract["currency"], quantity_unit="")
    batch["phase"] = "P1-B-controlled-draft"
    batch["input_contract"] = contract
    batch["sources"] = [dict(v, role=k) for k,v in files.items()]
    batch["id"] = digest({"sources": batch["sources"], "contract": contract, "adapter_version": __version__})[:24]
    _, originals = read_stage(files["invoice"]["path"], 1)
    left = []
    for row in batch["rows"]:
        row["authority"]["quantity_unit"] = quantity_unit(contract, row["source"]["row"])
        left.append({"code": row["identity"]["code"], "carton_key": p0.carton(row["logistics"]["carton_raw"]),
                     "ja": row["identity"]["japanese_name"], "row": row["source"]["row"]})
    links = p0.link(left, originals, ["code", "carton_key"])
    used = set()
    for row, (l, original, meta) in zip(batch["rows"], links):
        unique = (bool(l["code"]) and meta["status"] == "unique" and original is not None
                  and p0.clean(l["ja"]) == p0.clean(original.get("ja")))
        if unique:
            used.add(original["row"])
            row["original_purchase"] = {"status": "unique_source_alignment_not_approval", "record": serial(original),
                                        "quantity_unit": contract.get("invoice_quantity_unit")}
        else:
            # Candidates are evidence only. Neither old-code inference nor range splits approve identity.
            candidates = [r for r in originals if p0.clean(r.get("ja")) == p0.clean(l["ja"])
                          and set(p0.expand(r.get("carton")) or []) & set(p0.expand(row["logistics"]["carton_raw"]) or [])]
            row["original_purchase"] = {"status": "identity_pending", "candidates": [serial(r) for r in candidates],
                                        "quantity_unit": contract.get("invoice_quantity_unit")}
            if not any(d["id"] == "original_source_identity" for d in row["disputes"]):
                row["disputes"].append({"id": "original_source_identity", "domain": "identity",
                                        "reason": "原表与第3步未能按同码/箱号/日文名唯一对应；改码/拆分需证据"})
    authority_numeric = [p0.numeric_text(r["authority"]["quantity"]) for r in batch["rows"]]
    batch["original_input_summary"] = {"rows": len(originals), "unique_alignments": len(used),
        "unresolved_authority_rows": sum(r["original_purchase"]["status"] == "identity_pending" for r in batch["rows"]),
        "unassigned_original_rows": [r["row"] for r in originals if r["row"] not in used],
        "source_quantity_observed": p0.text(p0.sumv(originals,"qty")),
        "authority_quantity_observed": str(sum((q for q in authority_numeric if q is not None), p0.Decimal(0))),
        "invalid_authority_quantity_rows": [r["source"]["row"] for r,q in zip(batch["rows"],authority_numeric) if q is None],
        "quantity_unit_comparison_approved": False}
    for key, stage in (("customs_reference", 5), ("internal_reference", 6)):
        if key not in files:
            continue
        _, observations = read_stage(files[key]["path"], stage)
        for row, (_, found, meta) in zip(batch["rows"], p0.link(left, observations, ["code", "carton_key"])):
            row.setdefault("historical", {})[key] = {"match": meta["status"], "review_status": "candidate_only",
                "record": serial(found) if found is not None and meta["status"] == "unique" and row["identity"]["code"] else None}
    batch["weight_data"] = read_weights(files["weights"]["path"], files["weights"]["sheet"])
    batch["logistics_check"] = reconcile_logistics(batch["rows"], batch["weight_data"])
    if contract.get("product_library"):
        from .product_library import apply_candidates
        apply_candidates(batch, contract["product_library"]["path"])
    return validate(batch)


def import_raw_batch(contract):
    """Build the unified detail directly from the unprocessed Japanese workbook."""
    contract=copy.deepcopy(validate_contract(contract));files=contract["sources"]
    batch=import_raw_invoice(files["invoice"]["path"],currency=contract["currency"],quantity_unit="")
    batch["phase"]="P0-raw-preliminary-draft"
    batch["product_review_profile"]="exception-first-v1"
    batch["product_data_policy"]="single-person-v1"
    batch["input_contract"]=contract
    batch["sources"]=[dict(v,role=k) for k,v in files.items()]
    batch["id"]=digest({"sources":batch["sources"],"contract":contract,"adapter_version":__version__})[:24]
    for row in batch["rows"]:
        unit=quantity_unit(contract,row["source"]["row"])
        row["authority"]["quantity_unit"]=unit
        row["arrival"]["unit_raw"]=unit
        row["arrival"]["unit_status"]="contract_confirmed" if unit else "pending_product_or_purchase_lookup"
        record={"stage":1,"file":files["invoice"]["path"],"sha256":files["invoice"]["sha256"],
                "sheet":row["source"]["sheet"],"row":row["source"]["row"],
                "code":row["identity"]["code"],"ja":row["identity"]["japanese_name"],
                "carton":row["logistics"]["carton_raw"],"origin":row["logistics"]["origin"],
                "qty":row["authority"]["quantity"],"price":row["authority"]["unit_price_observed"],
                "amount":row["authority"]["amount"]}
        row["original_purchase"]={"status":"raw_invoice_source","record":record,"quantity_unit":unit,
                                  "notice":"原始Qty为仓库点收最大到货单位；单位未确认时不得解释为件"}
    numeric=[p0.numeric_text(r["authority"]["quantity"]) for r in batch["rows"]]
    batch["original_input_summary"]={"rows":len(batch["rows"]),"unique_alignments":len(batch["rows"]),
        "unresolved_authority_rows":0,"unassigned_original_rows":[],
        "source_quantity_observed":str(sum((v for v in numeric if v is not None),p0.Decimal(0))),
        "authority_quantity_observed":str(sum((v for v in numeric if v is not None),p0.Decimal(0))),
        "invalid_authority_quantity_rows":[r["source"]["row"] for r,v in zip(batch["rows"],numeric) if v is None],
        "quantity_unit_comparison_approved":False,"quantity_common_unit":None,
        "notice":"数值合计不代表共同物理单位；逐行单位待开定/采购资料或合同确认"}
    left=[{"code":r["identity"]["code"],"carton_key":p0.carton(r["logistics"]["carton_raw"]),
           "ja":r["identity"]["japanese_name"],"row":r["source"]["row"]} for r in batch["rows"]]
    for key,stage in (("customs_reference",5),("internal_reference",6)):
        if key not in files:continue
        _,observations=read_stage(files[key]["path"],stage)
        for row,(_,found,meta) in zip(batch["rows"],p0.link(left,observations,["code","carton_key"])):
            row.setdefault("historical",{})[key]={"match":meta["status"],"review_status":"candidate_only",
                "record":serial(found) if found is not None and meta["status"]=="unique" and row["identity"]["code"] else None}
    batch["weight_data"]=read_weights(files["weights"]["path"],files["weights"]["sheet"])
    batch["logistics_check"]=reconcile_logistics(batch["rows"],batch["weight_data"])
    if contract.get("product_library"):
        from .product_library import apply_candidates
        apply_candidates(batch, contract["product_library"]["path"])
    if not contract.get("product_library"):
        batch["arrival_summary"].update({"product_reference_matches":0,
                                         "product_reference_pending":len(batch["rows"])})
    return validate(batch)


def conversion(row):
    from .core import pricing_basis
    if not row["reviews"]["packaging"]:
        return {"status": "pending", "declaration_quantity": None, "declaration_unit": None,
                "reason": "packaging_evidence_unconfirmed"}
    pack = row["packaging"]
    basis = pricing_basis(row)
    if pack["source_unit"] != basis["quantity_unit"]:
        raise Rejected("采购/计价数量单位与已确认换算依据不一致")
    quantity = Fraction(decimal(basis["quantity"])) * Fraction(decimal(pack["declaration_factor"]))
    if quantity <= 0:
        raise Rejected("换算数量必须大于零")
    return {"status": "confirmed_exact_conversion", "source_quantity": basis["quantity"],
            "source_unit": pack["source_unit"], "factor": pack["declaration_factor"],
            "declaration_quantity": str(quantity), "declaration_unit": pack["declaration_unit"],
            "internal_boxes": pack["internal_boxes"], "internal_quantity": pack["internal_quantity"],
            "pieces_per_box": pack["pieces_per_box"], "evidence": row["reviews"]["packaging"]}


def professional_queue(batch):
    return {domain: [{"id": row["id"], "source": row["source"], "disputes": [d for d in row["disputes"] if d.get("domain") == domain],
                      "review": row["reviews"][domain]} for row in batch["rows"]
                     if not row["reviews"][domain] or any(d.get("domain") == domain for d in row["disputes"])]
            for domain in DOMAINS if domain != "product"}


def reconcile_quantities(batch):
    """Distinguish exact math from missing unit/identity evidence; never infer a new coefficient."""
    checks=[]
    from .core import pricing_basis
    for row in batch["rows"]:
        basis = pricing_basis(row)
        pending=[]
        original=row.get("original_purchase",{})
        record=original.get("record") or {}
        original_unit=original.get("quantity_unit")
        authority_unit=basis["quantity_unit"]
        # A raw invoice row is already its own traceable source row.  It has not
        # been enriched or approved, but it does not need a second identity
        # alignment before the received quantity can be shown.
        if original.get("status") not in ("unique_source_alignment_not_approval", "raw_invoice_source"):
            pending.append("original_identity_pending")
        if not original_unit or not authority_unit:pending.append("quantity_units_pending")
        raw_equal=None
        if record and original_unit and authority_unit:
            if original_unit!=authority_unit:
                pending.append("invoice_to_authority_conversion_evidence_required")
            else:
                try:raw_equal=decimal(record["qty"])==decimal(basis["quantity"])
                except Rejected:pending.append("invalid_source_quantity")
                if raw_equal is False:pending.append("original_quantity_change_needs_confirmation")
        converted=conversion(row)
        if converted["status"]=="pending":pending.append("packaging_pending")
        price=exact_price(row)
        exact_amount_equal=None
        if price["status"]=="exact_ratio_only":
            exact_amount_equal=(Fraction(price["declaration_quantity"])*Fraction(int(price["unit_price_numerator"]),int(price["unit_price_denominator"]))
                                ==Fraction(decimal(basis["amount"])))
        else:pending.append("amount_review_pending")
        checks.append({"id":row["id"],"original_quantity":record.get("qty"),"original_unit":original_unit,
                       "authority_quantity":basis["quantity"],"authority_unit":authority_unit,
                       "same_unit_original_quantity_equal":raw_equal,"conversion":converted,
                       "exact_amount_equal":exact_amount_equal,"pending":pending,"passed":not pending and exact_amount_equal is True})
    return {"passed":all(r["passed"] for r in checks),"rows":checks,
            "pending_rows":sum(not r["passed"] for r in checks),"automatic_coefficients_inferred":0}


def workflow_status(batch):
    package = review_package(batch)
    row_pending = {}
    for row in batch["rows"]:
        row_pending[row["id"]] = product_errors_for_batch(batch,row) + ["review_"+d for d in DOMAINS if not row["reviews"][d]]
        if row["disputes"]:
            row_pending[row["id"]].append("unresolved_disputes")
    logistics = reconcile_logistics(batch["rows"], batch["weight_data"]) if "weight_data" in batch else {"passed": False}
    contract = contract_status(batch["input_contract"], batch["rows"]) if "input_contract" in batch else {"missing": ["D07_D08_contract_missing"]}
    return {"formal_ready": False, "formal_export_implemented": False, "draft_allowed": True,
            "rows": row_pending, "contract": contract, "logistics": logistics,
            "quantities": reconcile_quantities(batch),
            "counts": {"total": len(batch["rows"]), "product_confirmed": sum(bool(r["reviews"]["product"]) for r in batch["rows"]),
                       "product_batch_eligible": len(package["ordinary_ids"]), "product_individual_pending": len(package["individual_ids"])},
            "global_gates": ["D05_customs_whitelist_unapproved", "D01_no_automatic_rounding",
                             "WorkBuddy_native_trigger_pending", "WorkBuddy_D1_rejection_evidence_pending",
                             "formal_export_disabled_until_separate_release_authorization"],
            "notice": "合同与专业审核缺项保持待确认；受控草稿不表示正式放行"}


def require_formal_release(batch):
    # No switch/command/config value can silently turn a test draft into an official document.
    raise Rejected("正式输出禁用：D05白名单、业务签核及WorkBuddy集成证据尚未齐备；仅允许受控测试草稿")
