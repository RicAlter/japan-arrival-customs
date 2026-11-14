"""Deterministic inheritance of user-authorized existing reviewed information."""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from .sources import code, norm, known

MATERIAL = {'material', 'website_material', 'material_reference'}
SKU_FIELDS = {'category', 'material', 'website_material', 'material_reference', 'pack_reference', 'box_size', 'blind'}
ROW_FIELDS = {'box_count', 'total_pieces'}


def _same_number(a,b):
    try:return Decimal(str(a)) == Decimal(str(b))
    except InvalidOperation:return False


def _same_row(row,record):
    f=record['fields'];raw=row['raw']
    return (norm(f.get('carton'))==norm(raw.get('carton')) and bool(f.get('carton'))
            and norm(f.get('origin'))==norm(raw.get('origin'))
            and _same_number(f.get('qty'),raw.get('qty')))


def _eligible(field,value):
    if not known(value):return False
    if field=='yd':return bool(re.fullmatch(r'YD[A-Za-z0-9_-]+',str(value),re.I))
    if field in ROW_FIELDS|{'box_size'}:
        try:return Decimal(str(value)).is_finite() and Decimal(str(value))>0
        except InvalidOperation:return False
    if field=='blind':return norm(value) in {'是','否','盲盒','盲抽','非盲盒','非盲抽','YES','NO','yes','no'}
    return True


def enrich_reviewed(row, records):
    """Same code+JP SKU scope; counts and YD additionally require same shipment row.

    Previously reviewed category/O/box/blind wins over automatic candidates.
    Explicitly completed workbook wins for R/S reference, never overwrites O
    from the operator. No price, channel, Qty, calculation or formula changes.
    """
    row.setdefault('resolved_issues',[])
    for field in sorted(SKU_FIELDS|ROW_FIELDS|{'yd'}):
        candidates=[r for r in records if _eligible(field,r['fields'].get(field,''))
                    and (field not in ROW_FIELDS|{'yd'} or _same_row(row,r))
                    and (field!='yd' or r['role']=='reviewed_basics')]
        if not candidates:continue
        def rank(record):
            if field in {'website_material','material_reference'}:
                return (0 if record['role']=='completed_reference' else 1,int(record.get('scope',{}).get('priority',100)))
            return (0 if record['role']=='reviewed_basics' else 1,int(record.get('scope',{}).get('priority',100)))
        best=min(rank(r) for r in candidates);candidates=[r for r in candidates if rank(r)==best]
        groups=defaultdict(list)
        for record in candidates:groups[norm(record['fields'][field])].append(record)
        if len(groups)>1:
            row['issues'].append({'code':'REVIEWED_FIELD_CONFLICT','field':field,
                                  'message':'已有业务表同商品存在不同已填值，保留当前结果并待核',
                                  'candidates':[{'value':v,'source_rows':[r['row'] for r in rs]} for v,rs in sorted(groups.items())]})
            continue
        chosen=next(iter(groups.values()));value=chosen[0]['fields'][field]
        # An already adopted YD differs from reviewed one: expose both, not overwrite.
        current=row['values'].get(field)
        if field=='yd' and current and current!=value:
            row['issues'].append({'code':'REVIEWED_FIELD_CONFLICT','field':'yd',
                                  'message':'当前采购YD与运营已填YD不同，保留两方依据待核',
                                  'candidates':[{'value':current},{'value':value,'source_rows':[r['row'] for r in chosen]}]})
            continue
        refs=[]
        for record in chosen:
            refs.append({k:record[k] for k in ['source_id','source_sha256','role','sheet','row']})
            refs[-1].update(column=record['columns'][field],value=record['fields'][field],source_field=field,
                            scope={**deepcopy(record.get('scope',{})),
                                   'adoption_kind':'inherited_user_reviewed_field' if record['role']=='reviewed_basics' else 'user_supplied_completed_reference',
                                   'authority':'2026-11-14 user: reuse existing reviewed fields; completed workbook for material/reference',
                                   'identity_scope':'same_shipment_row' if field in ROW_FIELDS|{'yd'} else 'same_code_and_japanese_name',
                                   'new_calculation':False})
        if current not in ('',None) and current!=value:
            row.setdefault('superseded_automatic_values',{})[field]={'value':current,'evidence':deepcopy(row['evidence'].get(field,[]))}
        row['values'][field]=value;row['evidence'][field]=refs
        retained=[]
        for issue in row['issues']:
            if issue.get('field')==field and issue.get('code') in {'FIELD_MISSING','FIELD_CONFLICT'}:
                row['resolved_issues'].append({**issue,'resolution':'user_reviewed_existing_value','adopted_value':value,'sources':refs})
            else:retained.append(issue)
        row['issues']=retained


def reviewed_index(records):
    index=defaultdict(list)
    for record in records:
        f=record['fields'];key=(code(f.get('code')),norm(f.get('ja')))
        if all(key):index[key].append(record)
    return index
