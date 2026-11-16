"""Exact physical-carton arithmetic. No SKU quantities or monetary inputs.

Audits/reuses the bounded same-prefix expansion and union/group-weight idea
from arrival_core/_p0_frozen.py and logistics.py at ffcfc05. No legacy state,
forward fill, fixed columns, guessed weight allocation or final projection.
"""
import copy,re,unicodedata
from collections import defaultdict
from fractions import Fraction as F
from .quantity_math import number,exact

POLICY='carton-physical-weight/1'
USABLE={'source_checked','derived'}


def frac(value):return F(int(value['numerator']),int(value['denominator']))if value else None


def expand(value,limit=10000):
    text=unicodedata.normalize('NFKC',str(value if value is not None else'')).strip().upper()
    if not text or len(text)>10000:raise ValueError('CARTON_LABEL_INVALID')
    result=[]
    for token in re.split(r'[,、;；]',text):
        m=re.fullmatch(r'\s*([A-Z]*|箱)([0-9]+)\s*(?:[-~～－–—〜]\s*([A-Z]*|箱)([0-9]+))?\s*',token)
        if not m:raise ValueError('CARTON_LABEL_INVALID')
        prefix,a=m[1],int(m[2]);b=int(m[4])if m[4]else a
        if a<1 or b<a or (m[4]and(m[3]or prefix)!=prefix):raise ValueError('CARTON_RANGE_INVALID')
        if b-a+1+len(result)>limit:raise ValueError('CARTON_RANGE_TOO_LARGE')
        result.extend(prefix+str(i)for i in range(a,b+1))
    if len(set(result))!=len(result):raise ValueError('CARTON_DUPLICATE_IN_LABEL')
    return result


def analyse_group(facts):
    g=copy.deepcopy(facts);g['issues']=list(g.get('issues',[]));states=g['field_states']={}
    blocked={i['field']for i in g['issues']}
    def issue(code,field):g['issues'].append({'code':code,'field':field});states[field]='pending'
    try:g['cartons']=expand(g['carton_raw']);states['identity']='source_checked'
    except ValueError as exc:g['cartons']=[];issue(str(exc),'identity')
    if 'identity'in blocked:states['identity']='pending'
    count=number(g['raw'].get('count'))
    if 'count'in blocked or count is None or count<=0 or count.denominator!=1:issue('WEIGHT_COUNT_INVALID','count')
    elif not g['cartons']or count!=len(g['cartons']):issue('WEIGHT_RANGE_COUNT_MISMATCH','count')
    else:states['count']='source_checked'
    factor={'KG':F(1),'G':F(1,1000)}.get(g['weight_unit'])
    if factor is None:raise ValueError('WEIGHT_UNIT_UNSUPPORTED')
    total=number(g['raw'].get('total_weight'));unit=number(g['raw'].get('unit_weight'))
    g['total_weight_kg']=exact(total*factor)if total is not None else None
    g['unit_weight_kg']=exact(unit*factor)if unit is not None else None
    if 'weight'in blocked or total is None or total<=0:issue('WEIGHT_TOTAL_INVALID','weight')
    else:states['weight']='source_checked'
    if unit is None:
        states['unit_weight']='pending'
    elif 'unit_weight'in blocked or unit<=0:issue('UNIT_WEIGHT_INVALID','unit_weight')
    else:states['unit_weight']='source_checked'
    if states.get('unit_weight')in USABLE and states.get('count')in USABLE and states.get('weight')in USABLE:
        if unit*count!=total:
            issue('WEIGHT_PRODUCT_CONFLICT','weight');states['weight']='conflict';states['unit_weight']='conflict'
    # A group total does not establish a per-carton observation.
    if states.get('weight')not in USABLE:states['unit_weight']='pending'
    g['volume_m3']=None
    if g.get('dimension_unit'):
        scale={'CM':F(1,100),'MM':F(1,1000),'M':F(1)}.get(g['dimension_unit'])
        if scale is None:raise ValueError('DIMENSION_UNIT_UNSUPPORTED')
        dims=[number(g['raw'].get(k))for k in ['width','height','depth']]
        if 'volume'in blocked or count is None or count<=0 or any(x is None or x<=0 for x in dims):issue('VOLUME_INPUT_INVALID','volume')
        else:
            calculated=count*dims[0]*dims[1]*dims[2]*scale**3
            observed=number(g['raw'].get('volume'))
            g['volume_m3']=exact(calculated);states['volume']='derived'
            if g['raw'].get('volume','')!=''and observed!=calculated:
                issue('VOLUME_OBSERVATION_CONFLICT','volume');states['volume']='conflict'
    else:states['volume']='not_requested'
    return g


def inventory(groups,source_issues=()):
    groups=copy.deepcopy(groups);index=defaultdict(list)
    for g in groups:
        for box in g['cartons']:index[box].append(g['id'])
    duplicate={box for box,ids in index.items()if len(ids)>1}
    for g in groups:
        if duplicate.intersection(g['cartons']):
            g['issues'].append({'code':'WEIGHT_CARTON_OVERLAP','field':'identity','cartons':sorted(duplicate.intersection(g['cartons']))})
            for key in ['identity','count','weight','unit_weight','volume']:g['field_states'][key]='conflict'
    def total(field,key):
        included=[g for g in groups if g['field_states'].get(field)in USABLE and g['field_states'].get('count')in USABLE and g['field_states'].get('identity')in USABLE]
        values=[frac(g[key])for g in included]
        return {'value':exact(sum(values,F(0)))if values else None,'covered_groups':len(included),'total_groups':len(groups),
                'complete':bool(groups)and len(included)==len(groups)and not source_issues}
    good=[g for g in groups if g['field_states'].get('count')in USABLE and g['field_states'].get('identity')in USABLE]
    totals={'observed_unique_cartons':len(index),'count':{'value':sum(len(g['cartons'])for g in good),'complete':bool(groups)and len(good)==len(groups)and not source_issues},
            'weight_kg':total('weight','total_weight_kg'),'volume_m3':total('volume','volume_m3'),'duplicate_cartons':sorted(duplicate)}
    return groups,dict(index),totals


def associate(item,groups,index):
    row=copy.deepcopy(item);issues=row.setdefault('issues',[])
    try:boxes=expand(row['carton_raw'])
    except ValueError as exc:boxes=[];issues.append({'code':str(exc),'field':'carton'})
    if any(i['field']=='carton'for i in issues):boxes=[]
    row['cartons']=boxes;byid={g['id']:g for g in groups};links=[]
    for box in boxes:
        ids=index.get(box,[])
        state='source_checked'
        if not ids:state='pending';issues.append({'code':'CARTON_WEIGHT_MISSING','field':'carton','carton':box})
        elif len(ids)>1 or byid[ids[0]]['field_states']['identity']not in USABLE:
            state='conflict';issues.append({'code':'CARTON_WEIGHT_AMBIGUOUS','field':'carton','carton':box})
        elif byid[ids[0]]['field_states'].get('count')not in USABLE:
            state='pending';issues.append({'code':'CARTON_GROUP_COUNT_UNRESOLVED','field':'carton','carton':box})
        elif byid[ids[0]]['field_states'].get('weight')not in USABLE:
            issues.append({'code':'CARTON_GROUP_WEIGHT_UNRESOLVED','field':'weight','carton':box})
        links.append({'carton':box,'group_ids':ids,'state':state})
    row.update(links=links,association='within_carton_set_unallocated'if len(boxes)>1 else'located_in_carton',
               quantities_allocated=False,weight_allocated_to_product=False,status='partial'if issues else'completed')
    return row


def reconcile(rows,groups,index,inventory_totals,coverage,source_issues=()):
    required=set(box for r in rows for box in r['cartons']);observed=set(index)
    weight=F(0);covered=set();contributions=[]
    for g in groups:
        selected=required.intersection(g['cartons']);s=g['field_states']
        if not selected or any(s.get(k)not in USABLE for k in ['identity','count','weight']):continue
        if selected==set(g['cartons']):n=frac(g['total_weight_kg']);basis='group_total_once'
        elif s.get('unit_weight')in USABLE:n=frac(g['unit_weight_kg'])*len(selected);basis='explicit_per_carton_observation'
        else:continue
        weight+=n;covered.update(selected);contributions.append({'group_id':g['id'],'cartons':sorted(selected),'weight_kg':exact(n),'basis':basis})
    missing=sorted(required-observed);extra=sorted(observed-required);unknown=sorted(required-covered)
    issues=list(source_issues)
    if coverage=='complete'and extra:issues.append({'code':'WEIGHT_CARTONS_WITHOUT_ITEMS','field':'coverage','cartons':extra})
    if missing:issues.append({'code':'ITEM_CARTONS_WITHOUT_WEIGHT','field':'coverage','cartons':missing})
    if unknown:issues.append({'code':'LINKED_WEIGHT_INCOMPLETE','field':'weight','cartons':unknown})
    if any(not r['cartons']for r in rows):issues.append({'code':'ITEM_CARTON_IDENTITY_INCOMPLETE','field':'coverage'})
    return {'inventory':inventory_totals,'coverage':coverage,'required_unique_cartons':len(required),'required_cartons':sorted(required),
            'missing_cartons':missing,'unreferenced_inventory_cartons':extra,
            'linked_weight_kg':{'value':exact(weight)if covered else None,'covered_cartons':len(covered),'required_cartons':len(required),
                                'complete':bool(required)and not unknown and all(r['cartons']for r in rows)},
            'unresolved_weight_cartons':unknown,'weight_contributions':contributions,'issues':issues,
            'per_product_weight_allocated':False,'carton_quantity_allocated':False}
