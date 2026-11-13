"""Reference candidates from frozen read-only sources; purchase Qty is independent."""
from collections import Counter,defaultdict
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from .support import Rejected,digest,load

UNKNOWN_UNIT='原规格单位（待核）'

def collect(source,config):
    from native_copy.references import query
    from arrival_core import _p0_frozen as p0
    from purchase_v4_intake import split_spec_quantity
    for key in ['prior_registration','prior_workbook','registry','quantity_links']:
        if digest(Path(config[key]))!=config[key+'_sha256']:raise Rejected('参考输入版本变化：'+key)
    prior=load(config['prior_registration']);book=p0.Book(Path(config['prior_workbook']).read_bytes(),'stage1-prior-reference.xlsx')
    sheet=next(s for s in book.sheets if s.name==source['sheet'].name)
    registry=p0.Book(Path(config['registry']).read_bytes(),'archived-purchase-reference.xlsx')
    regsheet=next(s for s in registry.sheets if s.name=='25.6.1-至今报单汇总')
    fresh=query(config['library_config'],source,config['batch_label'])
    fields={(f['cell'],f['field']):f for f in prior['fields']}
    byrow=defaultdict(list);all_links=load(config['quantity_links'])['links']
    used=Counter(l['purchase_observation_id'] for l in all_links)
    for l in all_links:byrow[l['arrival_row']].append(l)
    result=[];counts=Counter();ai_records={r['row']:r for r in prior.get('assistant_reference_columns',{}).get('records',[])}
    prior_map={r['source_row']:r for r in prior['row_map']}
    for row in source['rows']:
        n=row['source_row'];old=prior_map[n]
        if str(old['code'])!=str(row['code']) or old['japanese_name']!=row['japanese_name']:
            raise Rejected('参考原行与新副本不对应，不能凭JAN重排')
        for col in ['A','B','C','I','J','K','L']:
            if source['sheet'].v(n,col)!=sheet.v(n,col):raise Rejected('原始事实不一致：'+col+str(n))
        values={};metadata={};statuses={}
        for col,name in [('E','internal_name'),('F','specification'),('M','category'),('N','material_reference'),('O','channel'),('P','yd')]:
            f=fields[(col+str(n),name)];values[name]=sheet.v(n,col)
            statuses[name]=f['status'] if values[name] not in (None,'') else 'unknown'
            metadata[name]={'sources':deepcopy(f['sources']),'prior_reference_export':prior['export_id'],'confirmed':False}
        g=fields[('G'+str(n),'purchase_unit_price')];values.update(purchase_unit_price=None,purchase_quantity=None,purchase_price_unit=None,purchase_quantity_unit=None)
        statuses.update({k:'unknown' for k in ['purchase_unit_price','purchase_quantity','purchase_price_unit','purchase_quantity_unit']})
        price_sources=g.get('sources',[])
        if len(price_sources)==1:
            sr=price_sources[0]['provenance']['row'];code=str(regsheet.v(sr,'B')).strip()
            if code==str(row['code']):
                rawprice=regsheet.v(sr,'E');specraw=regsheet.v(sr,'D')
                if isinstance(rawprice,Decimal) and rawprice>=0:
                    values['purchase_unit_price']=str(rawprice);values['purchase_price_unit']=UNKNOWN_UNIT
                    statuses['purchase_unit_price']=statuses['purchase_price_unit']='candidate'
                    metadata['purchase_unit_price']={'sources':[{'path':config['registry'],'sha256':config['registry_sha256'],'sheet':regsheet.name,'cell':'E'+str(sr),'quote':str(rawprice)}],
                        'original_price':str(rawprice),'original_currency':'JPY','original_pricing_unit':None,'original_specification_label':str(specraw),
                        'unit_status':'source_specification_unit_not_known_minimum','minimum_unit_confirmed':False,'normalized_minimum_unit_price':None}
                    metadata['purchase_price_unit']={'sources':metadata['purchase_unit_price']['sources'],'original_unit_unknown':True}
                    counts['purchase_price_reference']+=1
        links=byrow[n]
        if len(links)==1 and used[links[0]['purchase_observation_id']]==1:
            link=links[0];sr=link['source_row'];code=str(regsheet.v(sr,'B')).strip()
            spec,q,kind=split_spec_quantity(regsheet.v(sr,'D'))
            if code==str(row['code']) and q is not None and q==link['quantity']:
                values['purchase_quantity']=q;values['purchase_quantity_unit']=UNKNOWN_UNIT
                statuses['purchase_quantity']=statuses['purchase_quantity_unit']='candidate'
                metadata['purchase_quantity']={'sources':[{'path':config['registry'],'sha256':config['registry_sha256'],'sheet':regsheet.name,'cell':'D'+str(sr),'quote':str(regsheet.v(sr,'D'))}],
                    'observation_id':link['purchase_observation_id'],'original_quantity':q,'original_unit':None,'unit_status':'unconfirmed_source_specification_unit',
                    'source_quantity_kind':'business_registry_procurement_reference','effective_for_this_batch_confirmed':False,'arrival_qty_substituted':False,'shared_observation':False}
                metadata['purchase_quantity_unit']={'sources':metadata['purchase_quantity']['sources'],'original_unit_unknown':True}
                counts['purchase_quantity_reference']+=1
        elif links:
            metadata['purchase_quantity']={'sources':deepcopy(links),'reason':'采购记录重复关联到货行或存在多候选，不分摊、不按到货Qty兜底','arrival_qty_substituted':False,'shared_observation':True}
            counts['quantity_shared_or_ambiguous_rows']+=1
        # These are assistant reference fields, never values in the human columns.
        ai_category=sheet.v(n,'Q');ai_material=sheet.v(n,'R')
        result.append({'row':n,'row_id':row['row_id'],'values':values,'statuses':statuses,'metadata':metadata,
            'ai_category':ai_category,'ai_material':ai_material,'ai_material_color':ai_records.get(n,{}).get('material_color','yellow')})
    return {'rows':result,'counts':dict(counts),'fresh_query':fresh,'reference_only':True,'purchase_quantity_total':None,'arrival_qty_substituted':False}
