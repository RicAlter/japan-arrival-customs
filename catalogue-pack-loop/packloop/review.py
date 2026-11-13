"""Explicit source/internal/declaration unit adapter over the existing B00 ledger."""
from pathlib import Path
from fractions import Fraction
from copy import deepcopy
from .support import load,put,get,Rejected,code_snapshot
from separated.model import old as basic_model
from native22.pricing import decimal
from arrival_core.operations_adapter import finite
from arrival_core.colored_operations import round0
base=None
SHEET='计算审核'
# Stable original columns/IDs are retained; new packaging inputs append at end.
EDIT={'I':'max_unit','K':'qty_unit','L':'amount','N':'factor','O':'conversion_reference','P':'declaration_unit','Q':'boxes','T':'public_name','V':'material_reference','W':'brand','X':'duty_rate','Y':'vat_rate','Z':'tax_reference','AA':'amount_reference','AI':'packs_per_box','AJ':'units_per_pack','AL':'internal_unit','AM':'packaging_reference'}
NUMERIC={'L','N','Q','X','Y','AI','AJ'}
FORMULAS={
 'R':lambda n:f'=IF(AND(ISNUMBER(N{n}),N{n}>0,I{n}<>"",K{n}=I{n},P{n}<>""),J{n}*N{n},"")',
 'S':lambda n:f'=IF(AND(ISNUMBER(R{n}),R{n}>0),ROUND(L{n}/R{n},0),"")',
 'AH':lambda n:f'=IF(AND(ISNUMBER(AI{n}),ISNUMBER(AJ{n})),AI{n}*AJ{n},IF(Q{n}>0,R{n}/Q{n},IF(I{n}="盒",N{n},"")))',
 'AK':lambda n:f'=IF(AND(ISNUMBER(AI{n}),AI{n}>0,ISNUMBER(AJ{n}),AJ{n}>0),AI{n}*AJ{n},"")',
 'AN':lambda n:f'=IF(AL{n}="包",IF(AJ{n}>0,R{n}/AJ{n},""),IF(AL{n}=P{n},R{n},IF(AND(AL{n}="盒",AK{n}>0),R{n}/AK{n},"")))',
 'AO':lambda n:f'=IF(AND(ISNUMBER(AN{n}),AN{n}>0),L{n}/AN{n},"")'}

def current_price(fs):
    p=fs.get('purchase_unit_price');valid=bool(p and p['confirmed'] and p.get('identity_context_hash')==basic_model.identity_context({f['target']:f for f in fs.values()},p['row_id']))
    unit=(p or {}).get('evidence',{}).get('unit')
    return p,valid,bool(valid and (basic_model.minimum_unit(unit) or unit in {'包','盒'})),unit

def prepare(root):
    p=base.prepare(root);p['headers']=list(p['headers'][:34]);p['headers'][5:7]=['已确认采购原单位价','采购原计价单位'];p['headers'][12:14]=['原价比（最大/采购单位）','每原Qty申报数'];p['headers'][33]='每盒申报张/件数'
    p['headers']+=['每盒包数参考/核对','每包申报张/件数','每盒申报张/件数参考','内部计价单位','包装层级与适用依据','内部计价数量','内部计价单价JPY']
    from .runtime import updates
    svc=updates.Service(root);workflow=load(svc.owner['workflow']);snapshot=load(workflow['catalogue_snapshot'])
    for row in p['rows']:
        ref=snapshot['rows'].get(str(row['source_row']),{});pack=ref.get('pack_reference');row['pack_source']={k:ref.get(k) for k in ['pack_reference','pack_candidates','pack_conflict']};row['source_snapshot']={'path':workflow['catalogue_snapshot'],'database_sha256':snapshot['sha256']}
        row['values'] += [pack['packs_per_box'] if pack else None,pack['units_per_pack'] if pack else None,None,None,None,None,None]
        if pack:
            # Reference inputs alone do not pass: AM + explicit confirmation are still required.
            row['values'][13]=None
        row['values'][15]=row['values'][6] if basic_model.minimum_unit(row['values'][6]) else None
    p['editable']=EDIT;p['formulas']={c:[fn(n) for n in range(5,len(p['rows'])+5)] for c,fn in FORMULAS.items()};p['code']=code_snapshot();p['packaging_schema']='source_qty/internal_pricing/declaration_units-separated/1'
    body={k:v for k,v in p.items() if k not in {'plan_id','version_token'}};pid=put(svc.root,body);return {**body,'plan_id':pid,'version_token':pid}

def recalculate(row,v,reference):
    has=any(v.get(k) not in (None,'') for k in ['packs_per_box','units_per_pack','internal_unit','packaging_reference'])
    if not has:return legacy_recalculate(row,v,reference)
    errors=[];raw=row['raw'];fs=row['basic_fields']
    if raw is None:return {'parent_id':row['parent_id'],'errors':['identity_link_pending']}
    for name in ['internal_name','specification','category','channel','yd']:
        if not fs.get(name,{}).get('confirmed'):errors.append('basic_unconfirmed:'+name)
    if row['price_check']['reason']:errors.append(row['price_check']['reason'])
    def num(x):
        value=decimal(x);return Fraction(value) if value is not None and value>0 else None
    packs,inner,q=[num(x) for x in [v.get('packs_per_box'),v.get('units_per_pack'),raw['quantity']]]
    if not packs or packs.denominator!=1:errors.append('packs_per_box_requires_positive_integer')
    if not inner or inner.denominator!=1:errors.append('units_per_pack_requires_positive_integer')
    decl=v.get('declaration_unit');internal=v.get('internal_unit');maximum=v.get('max_unit')
    if not basic_model.minimum_unit(decl):errors.append('declaration_minimum_unit_missing')
    if maximum!=v.get('qty_unit'):errors.append('actual_Qty_unit_must_equal_maximum_unit')
    if not str(v.get('packaging_reference') or '').strip():errors.append('packaging_scope_reference_required')
    if not q:errors.append('actual_quantity_invalid')
    purchase=row['values'][6]
    perbox=packs*inner if packs and inner else None
    units={decl:Fraction(1),'包':inner,'盒':perbox}
    if any(x not in units or not units[x] for x in [maximum,internal,purchase]):errors.append('separate_pricing_source_or_internal_unit_unknown')
    factor=num(v.get('factor'));a=decimal(v.get('amount'));original=decimal(raw['price'])
    if a is None or a<0:errors.append('business_amount_invalid')
    if original is None or original<=0:errors.append('actual_price_input_invalid')
    if a is not None and original is not None and q and Fraction(a)!=q*Fraction(original) and not str(v.get('amount_reference') or '').strip():errors.append('changed_amount_requires_explicit_reference')
    iq=boxes=dq=internal_factor=None
    if not errors or all(e.startswith('basic_unconfirmed:') or e=='packaging_scope_reference_required' for e in errors):
        source_factor=units[maximum];expected_price_ratio=source_factor/units[purchase]
        ratio=row['price_check']['pieces_per_box']
        if not ratio or Fraction(ratio)!=expected_price_ratio:errors.append('price_ratio_conflicts_with_explicit_packaging_units')
        if factor is None or factor.denominator!=1 or factor!=source_factor:errors.append('source_declaration_factor_conflicts_with_packaging')
        dq=q*source_factor;iq=dq/units[internal];internal_factor=units[internal];expected_boxes=dq/perbox
        supplied=num(v.get('boxes'))
        if v.get('boxes') not in (None,'') and supplied!=expected_boxes:errors.append('box_count_conflicts_with_explicit_source_unit')
        boxes=supplied or expected_boxes
        for value in [iq,boxes,iq/boxes,Fraction(a)/iq if a is not None else None]:
            if value is not None:
                try:finite(value)
                except ValueError:errors.append('exact_quantity_or_price_not_representable_in_existing_excel_engine')
    for name in ['duty_rate','vat_rate']:
        if v.get(name) not in (None,''):
            n=decimal(v[name])
            if n is None or not 0<=n<=1:errors.append(name+'_invalid')
    if any(v.get(k) not in (None,'') for k in ['duty_rate','vat_rate']) and not str(v.get('tax_reference') or '').strip():errors.append('tax_reference_required_no_default_rate')
    result={'parent_id':row['parent_id'],'errors':sorted(set(errors)),'values':v,'raw':raw,'purchase_quantity_consumed':False,'professional_approval':False,
        'conversion_reference':str(v.get('conversion_reference') or reference)+'；'+str(v.get('packaging_reference') or ''),
        'quantity':finite(iq) if iq is not None and not errors else None,'amount':str(a) if a is not None else None,'boxes':finite(boxes) if boxes is not None and not errors else None,
        'factor':finite(internal_factor) if internal_factor else None,'physical_pieces_per_box':str(perbox.numerator) if perbox and perbox.denominator==1 else None,
        'packaging_layers':{'packs_per_box':str(packs) if packs else None,'units_per_pack':str(inner) if inner else None,'declaration_units_per_box':str(perbox) if perbox else None,
          'original_quantity':raw['quantity'],'original_quantity_unit':maximum,'purchase_price_unit':purchase,'internal_pricing_unit':internal,'declaration_unit':decl,'source':v.get('packaging_reference'),'source_snapshot':row.get('source_snapshot')},
        'boxes_derived_from_confirmed_box_unit':maximum=='盒'}
    if not errors:result.update(declaration_quantity=finite(dq),execution_round0=round0(Fraction(a)/dq),internal_unit_price=finite(Fraction(a)/iq))
    return result

def finalize_export(*a,**k):return base.finalize_export(*a,**k)

def preview_return(*a,**k):
    # Frozen preview/CAS/archive implementation executes this adapter's formula scope/recalculation.
    return base.preview_return(*a,**k)
