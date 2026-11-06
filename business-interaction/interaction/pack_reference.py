"""Packaging references quote source text only; counts are human inputs."""
import re
from pathlib import Path
from . import load,save
RULE='USER:2026-11-06:盒规不再计算；提供来源原文供人工判断，不默认1'

def reference(spec,existing=None,context_current=True,source_records=()):
    texts=[];sources=[]
    for source in source_records:
        text=source.get('accessories_original')
        if text is None or not str(text).strip():continue
        sources.append(dict(source))
        if text not in texts:texts.append(text)
    return {'raw_specification':spec,'original_texts':texts,'display_text':'\n'.join(texts) or None,'sources':sources,
        'reference_count':None,'packs_per_box':None,'units_per_pack':None,'existing_reference_preserved':existing,
        'status':'identity_or_spec_changed_needs_source_review' if not context_current else ('original_text_for_manual_judgment' if texts else 'no_original_packaging_text'),
        'rule':RULE,'automatic_confirmation':False,'original_qty_unit_inferred':False,'price_ratio_used':False,'default_one_used':False}

def source_rows(workflow):
    snapshot=load(workflow['catalogue_snapshot'])
    return {n:reference(r.get('specification'),None,True,r.get('material_link_sources',[])) for n,r in snapshot['rows'].items()}

def write_hints(service,background):
    from arrival_core import _p0_frozen as p0
    batch,baseline,_,_,fields,_=service.basics._state(service.bid);byrow={};old={}
    for f in fields.values():byrow.setdefault(f['row_id'],{})[f['field']]=f
    for f in baseline['fields'].values():old.setdefault(f['row_id'],{})[f['field']]=f
    sources=source_rows(load(service.owner['workflow']))
    file=Path(service.root/'objects'/(baseline['copy_sha256']+'.xlsx'));book=p0.Book(file.read_bytes(),'registered-reference.xlsx');sheet=next(s for s in book.sheets if s.name=='invoice (計算)')
    rows={}
    for rid,fs in byrow.items():
        if 'specification' not in fs:continue
        f=fs['specification'];n=int(re.search(r'\d+$',f['cell'])[0]);current=all(fs.get(k,{}).get('value')==old[rid].get(k,{}).get('value') for k in ['product_code','specification','yd'])
        rows[str(n)]={**reference(f['value']['value'],sheet.v(n,'S'),current,sources.get(str(n),{}).get('sources',[])),'source_cell':'S'+str(n),'specification_cell':f['cell'],'row_id':rid}
    from collections import Counter
    body={'rule':RULE,'registered_copy_sha256':baseline['copy_sha256'],'rows':rows,'counts':dict(Counter(r['status'] for r in rows.values())),
        'workbook_or_original_data_changed':False,'automatic_packaging_calculation':False,'original_qty_and_price_units_inferred':False}
    save(background/'规格盒规参考.json',body);return body
