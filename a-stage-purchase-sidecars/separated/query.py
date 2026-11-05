"""Literal-source numeric checks, no unit conversion or box inference."""
from decimal import Decimal,InvalidOperation
from pathlib import Path
HEADERS=['主表行号','JAN','YD','商品名称','规格','采购价原值','采购数量原值','日方Qty原值','原数值差（日方－采购）','核对状态','采购计价单位','采购数量单位','来源规格原文','采购价来源格','采购数量来源格']
def number(value):
    if isinstance(value,bool) or value in (None,''):return None
    try:
        n=Decimal(str(value));return n if n.is_finite() else None
    except InvalidOperation:return None
def classify(purchase,arrival,shared=False):
    q=number(purchase);a=number(arrival)
    if q is None:return '重复来源未分配' if shared else '采购数量来源待核'
    if a is None:return '日方Qty待核'
    return '原数值不同／单位待核' if q!=a else '原数值相同／单位待核'
def coordinate(meta):
    return '\n'.join(Path(s['path']).name+' | '+s['sheet']+'!'+s['cell'] for s in meta.get('sources',[]) if 'path' in s)
def build(refs,row_map):
    byrow={r['source_row']:r for r in row_map};rows=[];differences=[];missing=[]
    for r in refs['rows']:
        n=r['row'];v=r['values'];meta=r['metadata'];pq=meta.get('purchase_quantity',{});pp=meta.get('purchase_unit_price',{})
        arrival=byrow[n]['source']['cells']['qty']['value'];quantity=v['purchase_quantity'];state=classify(quantity,arrival,pq.get('shared_observation',False))
        row=[n,byrow[n]['code'],v['yd'],v['internal_name'],v['specification'],v['purchase_unit_price'],quantity,arrival,None,state,
            pp.get('original_pricing_unit') or '未核实',pq.get('original_unit') or '未核实',pp.get('original_specification_label') or
            next((s.get('quote') for s in pq.get('sources',[]) if s.get('quote')),None),coordinate(pp),coordinate(pq)]
        rows.append(row)
        if state=='原数值不同／单位待核':differences.append(row)
        elif state not in {'原数值相同／单位待核'}:missing.append(row)
    return {'headers':HEADERS,'rows':rows,'differences':differences,'missing':missing,'counts':{'arrival_rows':len(rows),'numeric_differences_pending':len(differences),
        'source_or_mapping_pending':len(missing),'numeric_equal_unit_pending':len(rows)-len(differences)-len(missing),'confirmed_business_mismatches':None},
        'unit_conversion_executed':False,'arrival_qty_substituted':False,'purchase_quantity_sum':None}
