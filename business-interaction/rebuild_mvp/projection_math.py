"""Project allowed versioned facts; no price, tax or packaging re-inference."""
from collections import defaultdict
from fractions import Fraction as F
from .quantity_conversion import usable_quantity
from .logistics_math import frac,USABLE
from .quantity_math import exact
from .projection_sources import FIELDS

POLICY='reviewed-r3-draft-pair/1'


def excel_number(value):
    if value is None:return None
    n=frac(value)
    if n.denominator==1:
        return int(n)if len(str(abs(n.numerator)))<=15 else None
    denominator=n.denominator
    for p in [2,5]:
        while denominator%p==0:denominator//=p
    if denominator!=1:return None
    try:
        x=float(n)
        return x if F(str(x))==n and len(str(abs(n.numerator)))<=15 else None
    except (OverflowError,ValueError):return None


def private_tokens(sheet):
    result=set()
    for row in sheet['rows'][1:]:
        for col in ['F','J','P','Q']:
            value=row['values'].get(col,'')
            if value and (col=='Q'or len(str(value))>=4):result.add(str(value))
    return sorted(result,key=lambda x:(-len(x),x))


def weight_cells(logistics):
    owner={};byrow={r['row_id']:r for r in logistics['rows']};groups={g['id']:g for g in logistics['groups']}
    for row in logistics['rows']:
        for box in row['cartons']:owner.setdefault(box,row['row_id'])
    known={};basis=defaultdict(list);unit={}
    for c in logistics['totals']['weight_contributions']:
        group=groups[c['group_id']];owned=defaultdict(list)
        for box in c['cartons']:owned[owner[box]].append(box)
        if len(owned)==1:
            rid=next(iter(owned));known.update({box:True for box in c['cartons']});basis[rid].append({'group_id':c['group_id'],'cartons':c['cartons'],'weight_kg':c['weight_kg'],'basis':c['basis']})
        elif group['field_states'].get('unit_weight')in USABLE:
            for rid,boxes in owned.items():
                known.update({box:True for box in boxes});basis[rid].append({'group_id':c['group_id'],'cartons':boxes,'weight_kg':exact(frac(group['unit_weight_kg'])*len(boxes)),'basis':'explicit_per_carton_source'})
        if group['field_states'].get('unit_weight')in USABLE:
            unit.update({box:frac(group['unit_weight_kg'])for box in c['cartons']})
    output={}
    for rid,row in byrow.items():
        boxes=[b for b,o in owner.items()if o==rid];missing=[b for b in boxes if b not in known]
        weight=sum((frac(x['weight_kg'])for x in basis[rid]),F(0))
        units={unit[b]for b in boxes if b in unit}
        output[rid]={'owned_cartons':boxes,'repeated_cartons':[b for b in row['cartons']if owner.get(b)!=rid],
                     'count':exact(F(len(boxes)))if boxes else None,'weight_kg':exact(weight)if boxes and not missing else None,
                     'unit_weight_kg':exact(next(iter(units)))if boxes and len(units)==1 and all(b in unit for b in boxes)else None,
                     'unresolved_cartons':missing,'basis':basis[rid],'allocated_to_product':False}
    return output


def project_row(q,p,l,public,issues,weights,tokens,output_row=None):
    values={};cells={};problems=list(issues);n=output_row or q['row']
    def missing(field,col,code):
        problems.append({'field':field,'column':col,'code':code});cells[col]={'state':'pending','reason':code}
    def text(col,value,state='inherited',field=None):
        if value in ('',None):missing(field or col,col,'FIELD_MISSING');return
        values[col]=str(value);cells[col]={'state':state,'field':field or col}
    def numeric(col,value,field,state='derived',integer=False):
        number=excel_number(value)
        if number is None or integer and frac(value).denominator!=1:
            missing(field,col,'VALUE_UNAVAILABLE_OR_EXCEL_PRECISION');return
        values[col]=number;cells[col]={'state':state,'field':field,'exact':value}
    if l['cartons']:text('A',l['carton_raw'],field='carton')
    else:missing('carton','A','CARTON_UNRESOLVED')
    text('B',q['scope']['code'],field='code');text('D',q['scope']['origin'],field='origin')
    numeric('E',usable_quantity(q,'box'),'boxes','reference',integer=True)
    numeric('F',usable_quantity(q,'piece'),'pieces',integer=True)
    pricing=p['pricing'];results=pricing['results']
    for key,col in [('piece_price_round0','G'),('rounded_line_amount','P')]:
        result=results.get(key)
        if (result and pricing['field_states'].get(key)in {'derived','inherited'}and result['currency']=='JPY'
                and result['per_unit']==('piece'if key=='piece_price_round0'else'line')):
            numeric(col,result['value'],key,'reference')
        else:missing(key,col,'PRICE_RESULT_UNAVAILABLE')
    formula=None
    if all(col in values for col in ['F','G','P']):
        if F(str(values['F']))*F(str(values['G']))!=frac(cells['P']['exact']):
            values.pop('P');missing('rounded_line_amount','P','PRICE_QUANTITY_CONFLICT')
        else:formula=f'IF(AND(ISNUMBER(G{n}),ISNUMBER(F{n})),G{n}*F{n},"")'
    elif 'P'in values:
        values.pop('P');missing('rounded_line_amount','P','PRICE_INPUT_UNAVAILABLE')
    blind=q['quantity'].get('blind')
    if blind is not None:text('K','是'if blind['value']else'否','reference','blind')
    else:missing('blind','K','BLIND_UNRESOLVED')
    for field,(col,_)in FIELDS.items():
        fact=public.get(field)
        if fact:
            value=str(fact['value'])
            if any(token in value for token in tokens):missing(field,col,'INTERNAL_TEXT_NOT_FOR_CUSTOMS')
            else:text(col,value,'reference'if fact['state']=='reviewed_reference'else'reviewed_source',field)
        else:missing(field,col,'PUBLIC_FIELD_MISSING')
    w=weights[q['row_id']]
    if w['owned_cartons']:
        numeric('Q',w['count'],'physical_cartons','reference',True)
        numeric('R',w['unit_weight_kg'],'explicit_unit_weight','reference')
        numeric('S',w['weight_kg'],'deduplicated_weight','reference')
    # Repeated boxes intentionally have no second count or weight, not a gap.
    if not l['cartons']:missing('physical_cartons','Q','CARTON_UNRESOLVED')
    # The recognized legacy header merges T:X and labels Y/Z ambiguously.
    # Keep upstream dimensions/volume available by contract, but do not choose
    # a row/box representation without a verified display mapping.
    for field,col in [('carton_dimensions','T'),('carton_measure','Y'),('carton_volume','Z')]:
        missing(field,col,'TEMPLATE_DIMENSION_MAPPING_REVIEW')
    for issue in pricing['issues']:
        if issue['code']in {'ORIGINAL_AMOUNT_CONFLICT','ORIGINAL_AMOUNT_INVALID'}:
            problems.append({'field':'original_amount','column':'P','code':issue['code']})
    return {'row_id':q['row_id'],'row':q['row'],'output_row':n,'sheet':q['sheet'],'scope':q['scope'],'values':values,'cells':cells,
            'formula':formula,'public_fields':public,'weight_ownership':w,'issues':problems,
            'rounding_difference':results.get('rounding_difference'),'original_amount_difference':results.get('original_amount_difference'),
            'professional_approved':False,'status':'partial'if problems else'completed'}


def totals(rows):
    output={}
    for col in ['E','F','P','Q','S']:
        included=[r for r in rows if col in r['values']and isinstance(r['values'][col],(int,float))]
        target=[r for r in rows if col not in {'Q','S'}or r['weight_ownership']['owned_cartons']or r['cells'].get('Q',{}).get('state')=='pending']
        total=sum((F(str(r['values'][col]))for r in included),F(0))
        output[col]={'value':exact(total)if included else None,'covered_rows':len(included),'expected_rows':len(target),
                     'complete':len(included)==len(target),'excel_value':excel_number(exact(total))if included else None}
    return output
