"""Versioned provisional candidates; never overwrite accepted values or store as facts."""
from collections import defaultdict
from .sources import _iter_records,norm,known
from .matching import _ref,_is_active,_latest_same_record,_order_scope,_price_eligible
from .service import digest,load_json,MvpError

FIELDS={'name','specification','purchase_price','channel','yd','material_reference'}
def price(value,currency):
    return str(value)+('元' if currency in ('CNY','人民币','RMB') else '' if currency in ('JPY','日元','日币') else ' '+currency)
def apply_candidates(rows,config):
    options=config.get('candidate_review') or {}
    if not options.get('enabled'):return rows
    def fill(row,field,choices,note):
        if row['values'].get(field) not in ('',None):return
        distinct={}
        for value,evidence in choices:
            refs=evidence if isinstance(evidence,list) else [evidence]
            if not refs or any(not isinstance(e,dict) or not (e.get('source_id') and e.get('sheet') and e.get('row') and e.get('column') or e.get('source_file') and e.get('source_sha256')) for e in refs):continue
            if str(value).strip():distinct.setdefault(str(value).strip(),[]).extend(refs)
        if not distinct:return
        row.setdefault('review_candidates',{})[field]={'confirmed':False,'note':note,'options':[{'value':v,'evidence':ev} for v,ev in distinct.items()]}
        row['values'][field]='\n'.join((str(i)+'. ' if len(distinct)>1 else '')+v for i,v in enumerate(distinct,1))+'（'+('待选' if len(distinct)>1 else note)+'）'
        row['evidence'][field]=[e for ev in distinct.values() for e in ev]
    for row in rows:
        for issue in row['issues']:
            field=issue.get('field')
            if field not in FIELDS:continue
            choices=[]
            for c in issue.get('candidates',[]):
                value=c.get('value');ev=c.get('sources') or [c.get('source',{})]
                if value in ('',None):continue
                if field=='purchase_price':
                    currency=c.get('currency') or ('JPY' if any(e.get('role')=='business_summary' for e in ev) else '')
                    if not currency:continue
                    value=price(value,currency)
                    if c.get('channel'):value+=' / '+c['channel']
                choices.append((value,ev))
            fill(row,field,choices,'待确认')
    targets=defaultdict(list)
    for row in rows:
        if row.get('matching',{}).get('path')=='unresolved' or any(not row['values'].get(f) for f in ('name','specification','purchase_price','channel')) or (not row['values'].get('yd') and row.get('yd_requirement',{}).get('status')!='not_required'):
            for name in {norm(row['raw'].get('ja')),norm(row['values'].get('name'))}:
                if known(name):targets[name].append(row)
    hits=defaultdict(list);headers=[]
    for source in config['sources'] if targets else []:
        if source['role'] not in {'purchase_list','order_detail','purchase_order'}:continue
        h=digest(source['path']);meta={'source_id':'SRC-'+h[:24]+'-'+source['role'],'sha256':h,'version':source.get('version')}
        audit={'field_maps':[],'skipped_sheets':[]}
        for record in _iter_records(source,meta,audit):
            if source['role']=='purchase_order':headers.append(record);continue
            matched={r['row_id']:r for f in ('name','sku_name','ja') for r in targets.get(norm(record['fields'].get(f)),[])}
            for row in matched.values():hits[row['row_id']].append(record)
    for row in rows:
        records,_=_order_scope(_latest_same_record(hits[row['row_id']]),headers)
        records=[r for r in records if _is_active(r)]
        row['procurement_name_search']={'status':'candidates_only' if records else 'not_found','count':len(records),'automatic_identity_adoption':False}
        if row.get('yd_requirement',{}).get('status')!='not_required':
            fill(row,'yd',[(r['fields']['yd'],_ref(r,'yd')) for r in records if known(r['fields'].get('yd'))],'按名称补')
        for field,sourcefield in [('name','name'),('specification','sku_name'),('channel','channel')]:
            fill(row,field,[(r['fields'][sourcefield],_ref(r,sourcefield)) for r in records if known(r['fields'].get(sourcefield))],'采购候选')
        choices=[]
        for r in records:
            f=r['fields'];currency=f.get('currency','');value=f.get('actual_price') if known(f.get('actual_price')) else f.get('price')
            if known(value) and currency in ('JPY','日元','日币','CNY','RMB','人民币') and _price_eligible(r):
                ref=_ref(r,'actual_price' if known(f.get('actual_price')) else 'price');ref.update(currency=currency,unit=f.get('unit'))
                choices.append((price(value,currency)+(' / '+f['channel'] if f.get('channel') else ''),ref))
        fill(row,'purchase_price',choices,'采购候选')
    if config.get('translation_file'):
        data=load_json(config['translation_file'])
        if data.get('schema')!='arrival-translations/1' or not isinstance(data.get('records'),list):raise MvpError('INPUT_INVALID','译名输入必须为arrival-translations/1')
        for record in data['records']:
            if not record.get('source') or not record.get('japanese_name'):raise MvpError('INPUT_INVALID','译名缺来源或日文原文')
            for row in rows:
                if str(row['raw']['code'])!=str(record.get('code')) or norm(row['raw']['ja'])!=norm(record['japanese_name']):continue
                for f,v in record.get('fields',{}).items():
                    if f not in {'name','specification'}:raise MvpError('INPUT_INVALID','译名只支持名称与规格')
                    fill(row,f,[(v,{'source':record['source'],'source_file':config['translation_file'],'source_sha256':digest(config['translation_file']),'raw_japanese_name':record['japanese_name'],'provisional':True})],'译名待确认')
    return rows
