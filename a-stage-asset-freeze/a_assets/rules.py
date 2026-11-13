"""Explicit field semantics and evidence scopes, independent of workbook layout."""
from dataclasses import dataclass
import re

def text(value):
    if isinstance(value, bool):
        raise ValueError('布尔值不能作为商品编码')
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()

@dataclass(frozen=True)
class ProductSource:
    jan: str
    yd: str
    product_name: str | None
    sku_name: str | None
    evidence_ref: str

def name_candidate(jan, yd, source: ProductSource, *, override=None, override_evidence=None):
    """Same-row JAN+YD is necessary; product name never falls back to SKU."""
    if not text(jan) or not text(yd) or (text(jan),text(yd)) != (text(source.jan),text(source.yd)):
        raise ValueError('名称必须由同一来源记录的JAN与YD同时一致支持')
    if not text(source.evidence_ref):
        raise ValueError('缺少来源坐标')
    if not text(source.product_name):
        raise ValueError('商品名称缺失，不能用单品名称或角色名代替')
    if override is not None and (not text(override) or not text(override_evidence)):
        raise ValueError('名称覆盖必须有本次明确依据')
    return {'product_name':text(override) if override is not None else text(source.product_name),
            'specification':text(source.sku_name) or None,'source':source.evidence_ref,
            'override_evidence':override_evidence,'status':'candidate','confirmed':False,
            'display_color':'yellow','professional_approval':False}

def yd_candidate(jan, source_jan, yd, evidence_ref):
    """DG is an explicit YD lookup alias only, never a name/price/unit rule."""
    jan=text(jan);source_jan=text(source_jan)
    if not jan or source_jan not in {jan,'DG'+jan} or not text(yd) or not text(evidence_ref):
        raise ValueError('YD对应或出处不足')
    return {'yd':text(yd),'source':evidence_ref,'scope':['yd'],
            'match':'exact' if jan==source_jan else 'DG+JAN',
            'quantity_price_packaging_transfer':False,'confirmed':False,'status':'candidate'}

def material_candidate(arrival_yd, source_yd, original_text, *, selected=None,
                       product_category=None, category_evidence=None, selection_evidence=None,
                       link_scope_authorization=None):
    """Preserve full supplier text; selection needs a concrete product type and basis.

    This helper does not infer a composition from a bag of material words.
    It records a separately evidenced selection or returns the whole text pending.
    """
    if not text(arrival_yd) or text(arrival_yd)!=text(source_yd) or not text(original_text):
        raise ValueError('缺少相同YD链接材质依据')
    if not text(link_scope_authorization):
        raise ValueError('材质必须有链接适用范围依据')
    resolved=all(text(v) for v in (selected,product_category,category_evidence,selection_evidence))
    if resolved:
        parts=lambda value:{v.casefold() for v in re.split(r'[,，、;；\s]+',text(value)) if v}
        if not parts(selected).issubset(parts(original_text)):
            raise ValueError('选定材料不在已提供的链接材质范围内')
    return {'value':text(selected) if resolved else original_text,'original_text':original_text,
            'product_category':product_category,'category_evidence':category_evidence,
            'selection_evidence':selection_evidence,'link_scope_authorization':link_scope_authorization,
            'status':'candidate' if resolved else 'pending_reference',
            'display_color':'yellow' if resolved else 'red','confirmed':False,
            'professional_approval':False,'can_enter_b':False}
