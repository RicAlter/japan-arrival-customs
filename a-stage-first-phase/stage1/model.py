"""A03 model seam: defer all math and use independent purchase evidence."""
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from .support import Rejected,key
from a_confirm import model as legacy

CONFIRMED=legacy.CONFIRMED
value=legacy.value
identity_context=legacy.identity_context
effective_fields=legacy.effective_fields
ALLOWED={'internal_name','specification','purchase_unit_price','purchase_quantity','yd','channel','category',
         'material_reference','purchase_price_unit','purchase_quantity_unit'}
UNIT_FIELDS={'purchase_unit_price':'purchase_price_unit','purchase_quantity':'purchase_quantity_unit'}

def number(raw):
    if isinstance(raw,bool) or raw in (None,''):return None
    try:
        n=Decimal(str(raw));return n if n.is_finite() else None
    except (ValueError,InvalidOperation):return None

def unit_resolved(raw):
    return isinstance(raw,str) and bool(raw.strip()) and not any(v in raw for v in ('未明','未知','待核','待确认','原规格单位','需核对'))

def minimum_unit(raw):
    return unit_resolved(raw) and raw.strip() in {'个','件','枚','张','最小单位','最小单位（个）','最小单位（件）','最小单位（枚）','最小单位（张）'}

def fields_from_baseline(reg,sheet):
    if reg.get('stage1_policy',{}).get('phase')!='basic_only':raise Rejected('不是第一阶段基础资料登记')
    fields=legacy.fields_from_baseline(reg,sheet)
    for f in reg['fields']:
        target=f['sheet']+'!'+f['cell']
        fields[target]['stage1_source_metadata']=deepcopy(f.get('stage1_source_metadata',{}))
    return fields

def eligibility(field,evidence,basis,fields):
    name=field['field'];typ=field['value']['type'];raw=field['value']['value']
    if name not in ALLOWED:raise Rejected('第一阶段不确认此字段：'+field['target'])
    if name in UNIT_FIELDS:
        n=number(raw)
        if typ not in {'number','text'} or n is None or n<0:
            raise Rejected('采购单价/数量须为非负有效数值；可先保存待核')
        other=next((f for f in fields.values() if f['row_id']==field['row_id'] and f['field']==UNIT_FIELDS[name]),None)
        if not other or not unit_resolved(other['value']['value']):raise Rejected('采购原计价/数量单位未明确，不能采用为已确认值')
        required={'source_ref','currency','unit','unit_target','unit_confirmed_with_scope','kind'}
        if not isinstance(evidence,dict) or set(evidence)!=required or not str(evidence['source_ref']).strip():raise Rejected('采购值需独立来源与单位依据')
        if evidence['unit']!=other['value']['value'] or evidence['unit_target']!=other['target'] or evidence['unit_confirmed_with_scope'] is not True:
            raise Rejected('采购值未绑定同时明确确认的单位')
        if evidence['currency']!='JPY' or evidence['kind'] not in {'stage1_purchase_source','stage1_explicit_business_confirmation'}:
            raise Rejected('采购依据币种/适用范围不符')
        return {'evidence':deepcopy(evidence),'identity_context_hash':identity_context(fields,field['row_id'])}
    if name in {'purchase_price_unit','purchase_quantity_unit'}:
        if typ!='text' or not unit_resolved(raw):raise Rejected('单位须由业务明确，未知内容仅保存待核')
        if evidence and (set(evidence)!={'source_ref'} or not str(evidence['source_ref']).strip()):raise Rejected('单位依据格式无效')
        return {'evidence':deepcopy(evidence or {}),'identity_context_hash':identity_context(fields,field['row_id'])}
    return legacy.eligibility(field,evidence,basis,fields)

def recheck(source,baseline_sheet,baseline,state):
    # Deliberately do not import/call native22.calculate/analyze/formula_plan.
    if baseline.get('price_basis',{}).get('status')!='stage1_purchase_reference_only':raise Rejected('第一阶段采购依据类型不符')
    fields=effective_fields(baseline,state)
    byrow={}
    for f in fields.values():byrow.setdefault(f['row_id'],{})[f['field']]=f
    # Confirmation is scoped to the recorded unit and product/specification.
    # Keep immutable past receipts; expose stale purchase values as pending so
    # an explicit later scope can reconfirm the same number under a new unit.
    for f in fields.values():
        if f['field'] not in UNIT_FIELDS or not f['confirmed']:continue
        unit=byrow[f['row_id']].get(UNIT_FIELDS[f['field']]);proof=f.get('evidence',{})
        current=bool(unit and unit['confirmed'] and unit_resolved(unit['value']['value'])
            and f.get('identity_context_hash')==identity_context(fields,f['row_id'])
            and proof.get('unit_target')==unit['target'] and proof.get('unit')==unit['value']['value'])
        if not current:f.update(confirmed=False,status='saved_pending',confirmation_requires_recheck=True)
    report={'schema':'a-box-price-check/1','profile_id':source['profile_id'],'basis':deepcopy(baseline['price_basis']),
        'rows':[],'groups':[],'program_groups':[],'counts':{},'display_marks':[],
        'phase':'basic_only','pricing_deferred':True,'box_inference_executed':False,'price_difference_executed':False,
        'confirmed':False,'can_enter_b':False,'qty_unit_inferred':False,'actual_human_actions':None,'business_exception_total':None}
    return fields,report
