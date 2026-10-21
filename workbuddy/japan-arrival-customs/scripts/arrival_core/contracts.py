"""Explicit first-batch contract. Missing decisions stay null, not guessed."""
import copy
from pathlib import Path

from . import _p0_frozen as p0
from .core import Rejected, digest, proof_valid, require_actor

ROLES = ("business", "identity", "amount", "material", "packaging", "customs", "logistics", "release")


def source(path, kind, sheet=None):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": p0.sha(path.read_bytes()), "kind": kind, "sheet": sheet}


def create_contract(invoice, authority, weights, weight_sheet, *, customs_reference=None, internal_reference=None):
    files = {"invoice": source(invoice, "kmt-invoice-v1"),
             "authority": source(authority, "kmt-stage3-v1"),
             "weights": source(weights, "kmt-weights-v1", weight_sheet)}
    for key, path, kind in (("customs_reference", customs_reference, "kmt-stage5-reference"),
                            ("internal_reference", internal_reference, "kmt-stage6-reference")):
        if path:
            files[key] = source(path, kind)
    return {"schema": "japan-arrival/contract-1", "sources": files,
            "currency": "JPY", "currency_basis": "KMT表头UnitPrice(日本JPY)，本票签核仍待确认",
            "authority_quantity_unit": None, "row_quantity_units": {}, "invoice_quantity_unit": None,
            "weight_unit": "KG", "weight_unit_basis": "所选模板要求合計重量（KGS)",
            "responsibilities": {role: None for role in ROLES}, "approval": None,
            "customs_whitelist_approval": None, "rounding_policy": None,
            "purpose": "controlled_test_draft"}


def validate_contract(contract):
    if contract.get("schema") != "japan-arrival/contract-1" or contract.get("purpose") != "controlled_test_draft":
        raise Rejected("不支持的首票合同或输出用途")
    if contract.get("currency") != "JPY" or contract.get("weight_unit") != "KG":
        raise Rejected("本期KMT适配只支持源表明确的JPY及KG；其他合同需另行确认")
    expected = {"invoice": "kmt-invoice-v1", "authority": "kmt-stage3-v1", "weights": "kmt-weights-v1",
                "customs_reference": "kmt-stage5-reference", "internal_reference": "kmt-stage6-reference"}
    if not {"invoice", "authority", "weights"} <= set(contract["sources"]) or set(contract["sources"]) - set(expected):
        raise Rejected("源合同必须包含日方原表、第3步金额表和明确的箱重表")
    for key, item in contract["sources"].items():
        if item.get("kind") != expected[key]:
            raise Rejected("模板类型不匹配: " + key)
        path = Path(item["path"]).resolve(strict=True)
        if p0.sha(path.read_bytes()) != item["sha256"]:
            raise Rejected("合同源文件哈希不匹配: " + key)
    if not contract["sources"]["weights"].get("sheet"):
        raise Rejected("必须明确箱重工作表，不能猜选")
    if set(contract.get("responsibilities", {})) != set(ROLES):
        raise Rejected("审核职责合同不完整")
    for people in contract["responsibilities"].values():
        if people is not None and (not isinstance(people, list) or not people
                                   or any(not isinstance(p, str) or not p.strip() for p in people)):
            raise Rejected("未确定审核人使用null；已确定时提供明确名单")
    for unit in [contract.get("authority_quantity_unit"), contract.get("invoice_quantity_unit"),
                 *contract.get("row_quantity_units", {}).values()]:
        if unit is not None and (not isinstance(unit, str) or not unit.strip() or unit in ("未知", "待确认")):
            raise Rejected("未确定的数量单位必须为null，不能用占位词冒充确定单位")
    return contract


def quantity_unit(contract, source_row):
    return contract.get("row_quantity_units", {}).get(str(source_row)) or contract.get("authority_quantity_unit") or ""


def contract_status(contract, rows=()):
    missing = []
    approval = contract.get("approval")
    payload = {k: v for k, v in contract.items() if k != "approval"}
    signed = bool(proof_valid(approval) and approval.get("payload_hash") == digest(payload))
    if not signed:
        missing.append("D07_D08_batch_contract_signoff")
    if not contract.get("invoice_quantity_unit"):
        missing.append("D07_invoice_quantity_unit")
    if rows:
        missing.extend("D07_authority_quantity_unit:row"+str(r["source"]["row"]) for r in rows
                       if not quantity_unit(contract, r["source"]["row"]))
    elif not contract.get("authority_quantity_unit") and not contract.get("row_quantity_units"):
        missing.append("D07_authority_quantity_units")
    missing.extend("D08_responsibility:"+role for role in ROLES if not contract["responsibilities"].get(role))
    return {"approved_for_business_review": bool(signed and contract["responsibilities"].get("business")),
            "all_contract_items_complete": not missing, "missing": missing,
            "contract_hash": digest(contract), "formal_output_authorized": False}


def effective_permissions(batch, permissions):
    """P1-B review must satisfy both trusted local roles and the signed batch contract."""
    if "input_contract" not in batch:
        return permissions
    contract = batch["input_contract"]
    if not contract_status(contract, batch["rows"])["approved_for_business_review"]:
        raise Rejected("D07/D08未完整签核；可检查与生成受控草稿，不能冒充正式业务审核")
    allowed = {}
    for actor, roles in permissions.items():
        allowed[actor] = [role for role in roles if actor in (contract["responsibilities"].get(role) or [])]
    return allowed


def sign_contract(contract, *, actor, evidence, permissions):
    """Bootstrap authorization comes from a trusted local contract-admin configuration."""
    from .core import now
    require_actor(actor, "contract", permissions)
    if not evidence:
        raise Rejected("首票合同签核依据必填")
    out = copy.deepcopy(validate_contract(contract))
    out["approval"] = {"confirmed_by": actor, "confirmed_at": now(), "reference": evidence,
                       "payload_hash": digest({k: v for k, v in out.items() if k != "approval"})}
    if not out["responsibilities"].get("business"):
        raise Rejected("至少指定商品基础资料审核责任人；其他未知职责和单位继续待确认")
    return out
