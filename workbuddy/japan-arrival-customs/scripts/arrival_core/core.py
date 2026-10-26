"""Unified detail and review protocol; decimal values cross the API as strings."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction

SCHEMA = "japan-arrival/1"
DOMAINS = ("product", "identity", "price", "material", "packaging", "tax")
PRODUCT_FIELDS = {"internal_name", "customs_name", "category", "channel", "yd",
                  "yd_absence_reason", "frontend_status", "frontend_absence_reason", "procurement", "internal_note"}


class Rejected(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def decimal(value):
    if isinstance(value, (float, bool)) or value is None:
        raise Rejected("金额/数量必须为十进制字符串，不能使用浮点数或空值")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise Rejected("无效十进制值") from exc
    if not result.is_finite():
        raise Rejected("不允许非有限数")
    return result


def positive(value):
    result = decimal(value)
    if result <= 0:
        raise Rejected("数量/换算系数必须大于零")
    return result


def proof_valid(proof):
    return (isinstance(proof, dict) and proof.get("confirmed_by")
            and proof.get("confirmed_at") and proof.get("reference"))


def context(row):
    # No JAN-only reuse, including no-code purchases. Identity is explicitly reviewed.
    return {k: row["identity"][k] for k in ("code", "version", "specification")}


def pricing_basis(row):
    from .business_amount import effective_basis
    return effective_basis(row)


def new_row(source, raw, *, currency, quantity_unit, authority_stage=3,
            authority_status=None, amount_basis=None):
    row_id = digest([source["sha256"], source["sheet"], source["row"]])[:24]
    unavailable = {"#N/A", "#VALUE!", "#REF!", "#DIV/0!", "#NUM!", "#NAME?", "#NULL!", "未找到", ""}
    def value(key):
        v = raw.get(key)
        return "" if v is None or str(v) in unavailable else str(v)
    return {
        "id": row_id, "source": source, "raw": raw,
        "identity": {"code": value("code"), "code_type": "source_identifier",
                     "japanese_name": value("ja"), "version": value("variant"),
                     "specification": "", "relations": []},
        "product": {"internal_name": value("internal"), "customs_name": "",
                    "category": value("category"), "channel": value("channel"),
                    "yd": value("yd"), "yd_absence_reason": "",
                    "frontend_status": "unknown", "frontend_absence_reason": "",
                    "procurement": "unknown", "internal_note": ""},
        "arrival": {"quantity_raw": str(raw.get("qty") or ""), "unit_raw": quantity_unit,
                    "unit_status": "observed" if quantity_unit else "pending_product_or_purchase_lookup",
                    "unit_price_jpy_raw": str(raw.get("price") or ""),
                    "subtotal_jpy_raw": str(raw.get("amount") or ""), "source": source},
        "authority": {"stage": authority_stage, "amount": str(raw.get("amount") or ""), "currency": currency,
                      "quantity": str(raw.get("qty") or ""), "quantity_unit": quantity_unit,
                      "unit_price_observed": str(raw.get("price") or ""), "source": source,
                      "status": authority_status or ("business_confirmed_stage3" if authority_stage == 3 else "preliminary"),
                      "amount_basis": amount_basis or ("stage3_business_source" if authority_stage == 3 else "raw_source")},
        "material": {"candidate": value("material"), "selected": None, "candidates": []},
        "packaging": None, "tax": None,
        "logistics": {"carton_raw": value("carton"), "origin": value("origin")},
        "disputes": [], "reviews": {domain: None for domain in DOMAINS},
    }


def new_batch(rows, sources):
    batch = {"schema": SCHEMA, "id": digest(sources)[:24], "revision": 0,
             "sources": sources, "rows": rows, "events": [],
             "phase": "P1-A-offline", "formal_output_enabled": False}
    validate(batch)
    return batch


def validate(batch):
    if batch.get("schema") != SCHEMA or batch.get("formal_output_enabled") is not False:
        raise Rejected("不支持的数据结构或本阶段禁止正式输出")
    ids = [r["id"] for r in batch["rows"]]
    if len(ids) != len(set(ids)) or not ids:
        raise Rejected("明细必须存在且源行标识不得重复")
    for r in batch["rows"]:
        if r.get('business_amount'):
            from .business_amount import current
            current(r)
        authority = r["authority"]
        stage = authority.get("stage")
        if stage not in (1, 3) or authority["source"] != r["source"]:
            raise Rejected("金额/数量观察值必须绑定原始源行")
        if stage == 1 and (authority.get("status") != "preliminary_from_raw_invoice"
                           or authority.get("amount_basis") != "raw_invoice_subtotal"):
            raise Rejected("日方原表金额只能作为未确认的到货Subtotal观察值")
        if set(r["reviews"]) != set(DOMAINS):
            raise Rejected("审核域不完整")
        if (r["authority"]["amount"] != (r["raw"].get("amount") or "")
                or r["authority"]["quantity"] != (r["raw"].get("qty") or "")):
            raise Rejected("金额/数量观察值不能脱离原始值")
        for key, field in (("amount", "amount"), ("quantity", "qty")):
            cell = r["source"].get("cells", {}).get(field)
            if cell and r["authority"][key] != cell["value"]:
                raise Rejected("金额/数量与原始单元格证据不一致")
        arrival = r.get("arrival")
        if arrival is not None and (arrival.get("quantity_raw") != r["authority"]["quantity"]
                                    or arrival.get("subtotal_jpy_raw") != r["authority"]["amount"]):
            raise Rejected("原始到货Qty/Subtotal记录与源行观察值不一致")
    return batch


def product_errors(row, *, require_frontend=True):
    p = row["product"]
    errors = ["missing_" + k for k in ("internal_name", "customs_name", "category") if not p[k].strip()]
    if not p["yd"] and not p["yd_absence_reason"].strip():
        errors.append("yd_absence_reason_required")
    if require_frontend and p["frontend_status"] not in ("exists", "absent"):
        errors.append("frontend_status_pending")
    if require_frontend and p["frontend_status"] == "absent" and not p["frontend_absence_reason"].strip():
        errors.append("frontend_absence_reason_required")
    return errors


def product_errors_for_batch(batch, row):
    # New business profile follows the user's explicit B1 decision: frontend presence
    # and YD are optional internal references, never inferred from one another.
    # Legacy batches remain replayable under their original stricter checks.
    if batch.get("product_data_policy") == "single-person-v1":
        # Trusted local history is reusable basic-product information, not a
        # customs/declaration approval.  Do not recreate a task merely because
        # the historical archive lacks a customs name or optional front-end/YD.
        return ["missing_" + key for key in ("internal_name", "category") if not row["product"].get(key, "").strip()]
    return product_errors(row, require_frontend=batch.get("product_review_profile") != "exception-first-v1")


def product_disputes(row):
    """Only known, independent professional domains may defer their own review."""
    independent = {"price", "material", "packaging", "tax"}
    return [d for d in row["disputes"] if d.get("domain") not in independent]


def review_package(batch):
    validate(batch)
    ordinary = [r["id"] for r in batch["rows"] if not product_disputes(r) and not product_errors_for_batch(batch,r)
                and not r["reviews"]["product"] and not r.get("product_lookup", {}).get("trusted_history_reused")]
    return {"schema": "japan-arrival/review-1", "batch_id": batch["id"],
            "revision": batch["revision"], "state_hash": digest(batch),
            "ordinary_ids": ordinary,
            "individual_ids": [r["id"] for r in batch["rows"] if not r["reviews"]["product"] and not r.get("product_lookup", {}).get("trusted_history_reused")
                               and (product_disputes(r) or product_errors_for_batch(batch,r))],
            "rows": [{"id": r["id"], "source": r["source"], "identity": r["identity"],
                      "product": r["product"], "disputes": r["disputes"],
                      "missing": product_errors_for_batch(batch,r)} for r in batch["rows"]],
            "notice": "只确认商品资料，不同时批准金额、材质、盒规或税率；不得由AI代签"}


def require_actor(actor, role, permissions):
    if not isinstance(permissions, dict) or not isinstance(actor, str) or not actor or role not in permissions.get(actor, []):
        raise Rejected("审核人未配置对应权限: " + role)


def changed(batch, result, actor, action, rows, evidence):
    if action!='review_lock' and batch.get('active_review_lock'):
        result['active_review_lock']=None
    result["revision"] += 1
    result["events"].append({"at": now(), "actor": actor, "action": action,
                             "rows": rows, "evidence": evidence,
                             "before_hash": digest(batch)})
    return validate(result)


def _patch_product(row, values):
    if not isinstance(values, dict) or not values or set(values) - PRODUCT_FIELDS:
        raise Rejected("补录只允许商品字段")
    if any(not isinstance(v, str) for v in values.values()):
        raise Rejected("商品字段须为文本")
    row["product"].update(values)
    row["reviews"]["product"] = None
    if set(values) & {"category", "customs_name"}:
        row["reviews"]["tax"] = None
        row["tax"] = None


def supplement_many(batch, items, *, actor, evidence, permissions, _declaration_commit=False):
    """One explicit multi-row edit, not N full-state copies or N user clicks."""
    if "input_contract" in batch:
        from .contracts import effective_permissions
        permissions = effective_permissions(batch, permissions)
    require_actor(actor, "business", permissions)
    if not evidence or not isinstance(items, dict) or not items:
        raise Rejected("成组补录必须明确每行字段及依据")
    out = copy.deepcopy(batch)
    rows = {r["id"]: r for r in out["rows"]}
    if set(items) - set(rows):
        raise Rejected("含未知源行，整次补录拒绝")
    for row_id, values in items.items():
        if rows[row_id].get('declaration') and set(values)&{'category','customs_name'} and not _declaration_commit:
            raise Rejected('已有申报决策，请通过B2修改并记录关联归类失效')
        _patch_product(rows[row_id], values)
    return changed(batch, out, actor, "product_supplement", list(items), {"reference": evidence, "values_by_row": items})


def supplement(batch, row_id, values, *, actor, evidence, permissions):
    """Single-row convenience API shares the group validator and mutation path."""
    return supplement_many(batch, {row_id: values}, actor=actor, evidence=evidence, permissions=permissions)


def confirm_products(batch, package, row_ids, *, actor, mode, evidence, permissions, resolutions=None):
    """Atomic product-domain confirmation; independent professional reviews stay pending."""
    if "input_contract" in batch:
        from .contracts import effective_permissions
        permissions = effective_permissions(batch, permissions)
    require_actor(actor, "business", permissions)
    expected = review_package(batch)
    if package != expected:
        raise Rejected("审核包已过期或被修改，请重新导出")
    if not evidence or not row_ids or len(row_ids) != len(set(row_ids)):
        raise Rejected("确认依据及非重复行范围必填")
    rows = {r["id"]: r for r in batch["rows"]}
    if any(i not in rows for i in row_ids):
        raise Rejected("含未知源行")
    if any(rows[i]["reviews"]["product"] for i in row_ids):
        raise Rejected("商品资料已确认，禁止重复确认；如需纠错请先补录修改使确认失效")
    if mode == "batch":
        if set(row_ids) - set(expected["ordinary_ids"]):
            raise Rejected("批量确认含商品/身份争议或缺项，整次拒绝")
    elif mode == "individual":
        if len(row_ids) != 1:
            raise Rejected("争议必须逐项处理")
        row = rows[row_ids[0]]
        if product_errors_for_batch(batch,row):
            raise Rejected("先补齐商品资料及无YD/前台原因")
        blocking_ids = {d["id"] for d in product_disputes(row)}
        if blocking_ids or resolutions:
            # Existing clients may include professional notes; they never resolve those domains.
            if (not isinstance(resolutions, dict) or not blocking_ids <= set(resolutions)
                    or set(resolutions) - {d["id"] for d in row["disputes"]}):
                raise Rejected("每项商品/身份争议必须单独说明依据，不能混入未知争议")
            if any(not isinstance(v, str) or not v.strip() for v in resolutions.values()):
                raise Rejected("争议处理依据不可为空")
    else:
        raise Rejected("未知确认模式")
    out = copy.deepcopy(batch)
    for r in out["rows"]:
        if r["id"] in row_ids:
            r["reviews"]["product"] = {"confirmed_by": actor, "confirmed_at": now(),
                                        "reference": evidence, "mode": mode,
                                        "resolutions": resolutions or {}}
            # Domain approvals remain pending. Keep the dispute history in the event.
            r["disputes"] = [d for d in r["disputes"] if d.get("domain") != "product"]
    return changed(batch, out, actor, "product_" + mode, row_ids,
                   {"reference": evidence, "resolutions": resolutions or {}})


def approve_domain(batch, row_id, domain, payload, *, actor, evidence, permissions):
    """Explicit human decisions only; no inference of rates, coefficients or identities."""
    if "input_contract" in batch:
        from .contracts import effective_permissions
        permissions = effective_permissions(batch, permissions)
    roles = {"identity": "identity", "price": "amount", "material": "material",
             "packaging": "packaging", "tax": "customs"}
    if domain not in roles:
        raise Rejected("不支持的专业审核域")
    require_actor(actor, roles[domain], permissions)
    if not evidence:
        raise Rejected("审核依据不能为空")
    out = copy.deepcopy(batch)
    row = next((r for r in out["rows"] if r["id"] == row_id), None)
    if row is None:
        raise Rejected("未知源行")
    p = _apply_domain_row(row, domain, payload, actor=actor, evidence=evidence)
    return changed(batch, out, actor, "approve_" + domain, [row_id], {"reference": evidence, "payload": p})


def _apply_domain_row(row, domain, payload, *, actor, evidence, _declaration_commit=False):
    """Shared validation/mutation on an isolated row; caller authenticates and commits atomically."""
    p = copy.deepcopy(payload)
    if row.get('declaration') and domain in ('identity','material','tax') and not _declaration_commit:
        raise Rejected('已有申报决策，请通过B2版本化审核；身份变更需新的明确版本流程')
    if domain == "price":
        a = row["authority"]
        if a.get("status") == "preliminary_from_raw_invoice":
            raise Rejected("当前仅为日方原表Subtotal初步到货金额；最终申报金额确认节点尚未批准，不能完成价格域批准")
        if p != {k: a[k] for k in ("amount", "currency", "quantity", "quantity_unit")}:
            raise Rejected("价格审核不能改写来源金额/币种/数量单位")
        decimal(a["amount"]); positive(a["quantity"])
        if not a["currency"] or not a["quantity_unit"]:
            raise Rejected("来源币种及计价单位待确认")
    elif domain == "identity":
        if not all(isinstance(p.get(k), str) and p[k].strip() for k in ("version", "specification")):
            raise Rejected("身份需明确版本和规格（无版本亦需明示）")
        # Code changes/split relations cannot be invented in this API.
        if set(p) != {"version", "specification"}:
            raise Rejected("改码/拆分请提供独立身份映射，P1-A不自动执行")
        row["identity"].update(p)
        row["reviews"]["product"] = None
        for d in ("material", "packaging", "tax"):
            row["reviews"][d] = None
        row["material"]["selected"] = None; row["packaging"] = None; row["tax"] = None
    else:
        if not row["reviews"]["identity"] or p.get("context") != context(row):
            raise Rejected("必须先确认商品身份，证据须匹配本商品/版本/规格")
        if domain == "material":
            if not all(p.get(k) for k in ("original", "translation", "source", "completeness_confirmed")):
                raise Rejected("材质原文、完整译文、来源和人工完整性确认必填")
            if p["completeness_confirmed"] is not True:
                raise Rejected("材质完整性尚未人工确认")
            row["material"]["selected"] = p
        elif domain == "packaging":
            if not all(p.get(k) for k in ("source_unit", "declaration_unit", "internal_unit", "source")):
                raise Rejected("盒规各层单位和来源必填")
            if p["source_unit"] != pricing_basis(row)["quantity_unit"]:
                raise Rejected("盒规采购单位不匹配当前已确认的原始到货单位")
            positive(p.get("declaration_factor")); positive(p.get("pieces_per_box"))
            positive(p.get("internal_quantity")); positive(p.get("internal_boxes"))
            if (Fraction(positive(p["internal_quantity"])) / Fraction(positive(p["internal_boxes"]))
                    != Fraction(positive(p["pieces_per_box"]))):
                raise Rejected("内部数量/盒数与每盒件数不一致")
            row["packaging"] = p
            # A different unit/box basis requires a fresh professional tax decision.
            row["reviews"]["tax"] = None
            row["tax"] = None
        else:
            if p.get("formula_version") != "historical-box-v1":
                raise Rejected("仅支持现有盒装税金公式的显式批准版本")
            for key in ("duty_rate", "vat_rate"):
                if not Decimal(0) <= decimal(p.get(key)) <= Decimal(1):
                    raise Rejected("税率参数必须为0至1，且不能省略")
            positive(p.get("tax_unit_price"))
            if not all(p.get(k) for k in ("classification", "effective_date", "source", "tax_unit")):
                raise Rejected("税号/归类、适用日期、税基单位与来源必填")
            row["tax"] = p
    # Identity-change candidates require a separate mapping contract in P1-B.
    row["disputes"] = [d for d in row["disputes"] if d.get("domain") != domain
                       or d["id"] in ("changed_product_code_identity_review", "original_source_identity")]
    row["reviews"][domain] = {"confirmed_by": actor, "confirmed_at": now(), "reference": evidence}
    return p


def select_historical_material(row, candidates):
    """Return a prefill candidate, never create an approval. Conflicting approvals escalate."""
    trusted = [c for c in candidates if c.get("context") == context(row)
               and c.get("review_status") == "approved" and proof_valid(c.get("approval"))
               and c.get("original") and c.get("translation") and c.get("source")
               and c.get("completeness_confirmed") is True]
    values = {(c["original"], c["translation"]) for c in trusted}
    if len(values) > 1:
        return {"status": "conflict", "selected": None, "candidates": trusted}
    return {"status": "reviewed_history_prefill" if trusted else "pending",
            "selected": copy.deepcopy(trusted[0]) if trusted else None,
            "candidates": copy.deepcopy(candidates)}


def exact_price(row):
    if not row["reviews"]["price"] or not row["reviews"]["packaging"]:
        return {"status": "pending", "reason": "amount_or_packaging_unconfirmed"}
    basis = pricing_basis(row)
    if row.get('business_amount') and basis.get('status') != 'business_confirmed_in_batch':
        return {"status":"pending","reason":"business_amount_fact_version_changed"}
    q = Fraction(positive(basis["quantity"])) * Fraction(positive(row["packaging"]["declaration_factor"]))
    price = Fraction(decimal(basis["amount"])) / q
    return {"status": "exact_ratio_only", "declaration_quantity": str(q),
            "unit_price_numerator": str(price.numerator), "unit_price_denominator": str(price.denominator),
            "automatic_rounding": False, "formal_price": None}


def box_tax(row):
    if not row["reviews"]["tax"] or not row["reviews"]["packaging"]:
        return {"status": "pending", "value": None}
    p, t = row["packaging"], row["tax"]
    if t["tax_unit"] != p["internal_unit"]:
        raise Rejected("税基单位与内部数量单位不一致")
    # Fraction avoids Decimal division rounding, including repeating box ratios.
    price, duty_rate, vat_rate = [Fraction(decimal(t[k])) for k in ("tax_unit_price", "duty_rate", "vat_rate")]
    duty = price * duty_rate
    vat = price * (1 + duty_rate) * vat_rate
    ratio = Fraction(positive(p["internal_quantity"])) / Fraction(positive(p["internal_boxes"]))
    if ratio != Fraction(positive(p["pieces_per_box"])):
        raise Rejected("内部数量/盒数与已确认每盒件数不一致")
    total = (vat + duty) * ratio
    return {"status": "approved_parameters_exact_arithmetic", "duty": str(duty),
            "vat": str(vat), "box_tax": str(total), "currency": pricing_basis(row)["currency"],
            "formula_version": t["formula_version"], "rounding": "not_applied"}


def reconcile_amounts(rows, proposed):
    """No cross-row or cross-product cancellation. Proposed map must cover every row."""
    if set(proposed) != {r["id"] for r in rows}:
        raise Rejected("金额核验必须覆盖完整明细，不得漏行/多行")
    if len({pricing_basis(r)["currency"] for r in rows}) != 1:
        raise Rejected("不同币种不能直接合计或抵消；本期不做汇率换算")
    lines, groups = [], {}
    for r in rows:
        basis = pricing_basis(r)
        delta = Fraction(decimal(proposed[r["id"]])) - Fraction(decimal(basis["amount"]))
        key = digest({"identity": context(r), "currency": basis["currency"],
                      "unit": basis["quantity_unit"],
                      "unidentified_row": r["id"] if not r["identity"]["code"] else None})
        groups[key] = groups.get(key, Fraction(0)) + delta
        lines.append({"id": r["id"], "code": r["identity"]["code"], "delta": str(delta)})
    return {"lines": lines, "products": {k: str(v) for k, v in groups.items()},
            "batch_delta": str(sum(groups.values(), Fraction(0))),
            "passed": all(x["delta"] == "0" for x in lines),
            "adjustment_policy": "unapproved_no_automatic_adjustment"}


def readiness(batch):
    if "input_contract" in batch:
        from .batchflow import workflow_status
        return workflow_status(batch)
    pending = {}
    for r in batch["rows"]:
        reasons = product_errors_for_batch(batch,r) + ["review_" + d for d in DOMAINS if not r["reviews"][d]]
        if r["disputes"]:
            reasons.append("unresolved_disputes")
        pending[r["id"]] = reasons
    return {"rows": pending, "formal_ready": False, "global_gates": [
        "P1-A_formal_renderer_disabled", "D05_customs_whitelist_unapproved",
        "D01_rounding_policy_unapproved", "WorkBuddy_native_trigger_pending",
        "WorkBuddy_D1_rejection_evidence_pending"],
        "notice": "商品批量确认不等于正式放行；缺项不静默删行"}


def customs_preview(row):
    """Internal contract preview only. Never copy internal names, channel, YD or raw metadata."""
    candidate = row["product"]["customs_name"]
    for key in ("internal_name", "yd", "channel"):
        token = row["product"][key]
        if token and token in candidate:
            raise Rejected("申报品名包含内部字段内容，请单独核实: " + key)
    from .declaration_decisions import selected_material
    return {"kind": "internal_field_preview_not_formal", "customs_name": candidate,
            "origin": row["logistics"]["origin"],
            "material": selected_material(row,approved_only=True),
            "price": exact_price(row)}
