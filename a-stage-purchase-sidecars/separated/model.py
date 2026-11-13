"""Same basic-only model; price unit evidence is outside the main workbook."""
from copy import deepcopy
from stage1 import model as old
from .support import Rejected
CONFIRMED=old.CONFIRMED
value=old.value
identity_context=old.identity_context
effective_fields=old.effective_fields
fields_from_baseline=old.fields_from_baseline
ALLOWED={'internal_name','specification','purchase_unit_price','category','material_reference','channel','yd'}
def price_proof(proof):
    return (isinstance(proof,dict) and set(proof)=={'source_ref','currency','unit','kind'}
        and isinstance(proof['source_ref'],str) and bool(proof['source_ref'].strip())
        and proof['currency']=='JPY' and old.unit_resolved(proof['unit'])
        and proof['kind']=='stage1_explicit_business_confirmation')
def eligibility(field,evidence,basis,fields):
    if field['field'] not in ALLOWED:raise Rejected('采购数量和单位在独立查询表，不属于主表确认范围')
    if field['field']!='purchase_unit_price':return old.eligibility(field,evidence,basis,fields)
    n=old.number(field['value']['value'])
    if field['value']['type'] not in {'text','number'} or n is None or n<0:raise Rejected('采购价须为非负有效数值，可先保存待核')
    if not price_proof(evidence):raise Rejected('采购价采用仍须有独立来源和明确原计价单位；不能从Qty或规格猜单位')
    return {'evidence':deepcopy(evidence),'identity_context_hash':identity_context(fields,field['row_id'])}
def recheck(source,sheet,baseline,state):
    fields,report=old.recheck(source,sheet,baseline,state)
    original=effective_fields(baseline,state)
    for target,f in original.items():
        if f['field']=='purchase_unit_price' and f['confirmed']:
            current=price_proof(f.get('evidence')) and f.get('identity_context_hash')==identity_context(original,f['row_id'])
            if current:fields[target]=f
    return fields,report
