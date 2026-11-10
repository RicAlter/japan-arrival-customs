"""Source-original S references after verified JAN/pcs/DG/YD association.

No material inference, splitting, approval, network query or price calculation.
"""
from copy import deepcopy
from collections import defaultdict,Counter
from pathlib import Path
import json,re,sqlite3
import xml.etree.ElementTree as ET
from . import load,save,digest,Rejected
from .preparation_sources import code
from .preparation_workbook import update_cells,Q

def _update_refs(data,sheet,changes):
    from .photo_layout import parts,pack,sheet_member
    p=parts(data);member=sheet_member(p,sheet);root=ET.fromstring(p[member])
    rows={r.get('r'):r for r in root.find(Q+'sheetData')};added=False
    for change in changes:
        address=change['target'];n=address[1:]
        if not address.startswith('S') or n not in rows:raise Rejected('材质参考只更新已登记行的S列')
        row=rows[n]
        if any(c.get('r')==address for c in row):continue
        new=ET.Element(Q+'c',{'r':address})
        following=next((i for i,c in enumerate(row) if c.get('r','').startswith('T')),len(row))
        if following<len(row) and row[following].get('s'):new.set('s',row[following].get('s'))
        row.insert(following,new);added=True
    if added:p[member]=ET.tostring(root,encoding='utf-8',xml_declaration=True);data=pack(data,p)
    return update_cells(data,sheet,changes)


def enrich_material(result,cards,context=None,*,preserve_existing=True):
    from .matching_repair import spec_same,norm
    from .dg_enrichment import name_key,dg_alias
    context=context or {};values=result.get('values',{});jan=result['jan']
    name=context.get('source_internal_name') or values.get('name')
    spec=context.get('source_specification') or values.get('spec');yd=values.get('yd')
    current=result.get('material',{}).get('value') if preserve_existing else None
    if not preserve_existing:
        result['material']={'value':None,'raw':result.get('material',{}).get('raw'),'status':'pending_original_source_review'}
    audit={'executed':True,'candidates':[],'rejected':[],'mixtures_not_split':True,'confirmed':False}
    result['material_reference_review']=audit
    linked_codes={jan}
    for r in result.get('code_links',[]):
        if code(r.get('pcs'))==jan and r.get('jan'):linked_codes.add(code(r['jan']))
    dg=result.get('dg_enrichment',{})
    if dg.get('reason')=='exact_DG_alias_product_and_specification_verified':linked_codes.add(dg['alias'])
    records=result.get('all_identity_candidates',result.get('sources',[]))+dg.get('compatible_records',[])+result.get('pcs_enrichment',{}).get('compatible_records',[])
    seen=set();qualified=[]
    for r in records:
        raws=[r['material']] if r.get('material') else r.get('versions',{}).get('material_original',[])
        for raw in raws:
            if not isinstance(raw,str) or not raw.strip():continue
            item={'raw':raw,'kind':'verified_code_record','jan':r.get('jan'),'sku':r.get('sku'),
                  'name':r.get('name'),'spec':r.get('spec'),'yd':r.get('yd'),'source':r.get('source',{})}
            identity=json.dumps(item,ensure_ascii=False,sort_keys=True,default=str)
            if identity in seen:continue
            seen.add(identity);audit['candidates'].append(item)
            if not name or not r.get('name') or name_key(name)!=name_key(r['name']):
                audit['rejected'].append({**item,'reason':'different_or_unverified_product_name'});continue
            if not spec or not r.get('spec') or not spec_same(spec,r['spec']):
                audit['rejected'].append({**item,'reason':'different_or_unverified_specification'});continue
            actual_codes={code(r.get('jan')),code(r.get('sku'))}
            # Material applicability can be independently evidenced even when a
            # separate reorder/quote observation was not usable for pricing.
            individual_dg=bool(yd and r.get('yd')==yd and dg_alias(jan)==dg.get('alias')
                               and dg.get('alias') in actual_codes and r in dg.get('compatible_records',[]))
            if not linked_codes.intersection(actual_codes) and not individual_dg:
                audit['rejected'].append({**item,'reason':'code_relationship_not_verified'});continue
            if individual_dg:item['relationship']='individual_DG_product_spec_and_existing_YD_verified'
            qualified.append(item)
    yd_records=[]
    for r in cards.get(yd,[]) if yd else []:
        raw=r.get('material_original')
        if not isinstance(raw,str) or not raw.strip():continue
        item={'raw':raw,'kind':'verified_YD_product_collection','yd':yd,'name':r.get('product_name'),'source':r}
        audit['candidates'].append(item)
        if not name or not r.get('product_name') or name_key(name)!=name_key(r['product_name']):
            audit['rejected'].append({**item,'reason':'different_or_unverified_YD_product_name'});continue
        yd_records.append(item)
    audit['qualified_records']=qualified+yd_records
    if current not in (None,''):
        audit.update(status='existing_value_preserved',reason='nonempty_S_reference_or_manual_value_not_overwritten')
        return result
    if result.get('status') in {'special_identity_requires_context','special_reference','substantive_identity_conflict'} or any(x in str(context.get('name_ja') or '') for x in ['特典','自编','自編']):
        audit.update(status='pending',reason='special_or_conflicting_identity_requires_review');return result
    distinct_yd={x['raw'] for x in yd_records};distinct={x['raw'] for x in qualified}
    chosen=None
    if len(distinct_yd)==1:
        parent=next(iter(distinct_yd))
        # A full, labelled YD collection original may encompass a shortened
        # aggregate in a SKU observation. This only selects the complete source;
        # no component is assigned to an individual SKU or written separately.
        compatible=all(all(norm(t) in norm(parent) for t in re.split(r'[,，、;；/\n]+',raw) if t.strip()) for raw in distinct)
        if compatible:chosen=parent
    elif not distinct_yd and len(distinct)==1:chosen=next(iter(distinct))
    if chosen is None:
        audit.update(status='pending',reason='no_qualified_material_original' if not distinct and not distinct_yd else 'different_material_source_originals_require_review')
        return result
    selected=[x for x in yd_records+qualified if x['raw']==chosen]
    scope='product_collection_original_reference' if yd_records else 'source_material_set_reference' if re.search(r'[,，、;；/\n]',chosen) else 'source_record_original_reference'
    audit.update(status='new_source_original_reference',reason='verified_relationship_product_and_specification_full_original',selected=selected,value=chosen,scope=scope)
    result['material']={'value':chosen,'raw':chosen,'status':'linked_original_reference','confirmed':False,'mixtures_not_split':True,'sources':selected}
    return result


def _rows(file,sheet):
    from openpyxl import load_workbook
    w=load_workbook(file,read_only=True,data_only=True)
    try:return list(w[sheet].values)
    finally:w.close()

def binding(row):
    return {'jan':str(row[2] or ''),'name':str(row[5] or ''),'spec':str(row[6] or ''),'name_ja':str(row[9] or ''),'yd':str(row[16] or '')}

def refresh(config,website_history=None):
    """Refresh an existing batch's references without re-registering A03 state."""
    config=load(config) if not isinstance(config,dict) else config
    back=Path(config['background']);file=Path(config['prepared_file']);db=config['database'];before=digest(file)
    if digest(db['path'])!=db['sha256']:raise Rejected('材质资料库固定快照摘要变化')
    cards=defaultdict(list)
    with sqlite3.connect(Path(db['path']).resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        for r in conn.execute('select * from yd_material_lookup'):
            if r['material_original']:cards[r['yd_key']].append(dict(r))
    observed=_rows(file,config['sheet']);evidence=load(back/'evidence.json')['rows'];reviews={};new={}
    prior=load(back/'material-reference-overlay.json').get('rows',{}) if (back/'material-reference-overlay.json').exists() else {}
    for n,old in evidence.items():
        row=observed[int(n)-1];item=deepcopy(old);b=binding(row)
        item['values'].update(name=row[5],spec=row[6],yd=row[16]);item['material']={**item.get('material',{}),'value':row[18]}
        enrich_material(item,cards,{'name_ja':row[9]});audit=item['material_reference_review'];reviews[n]={'binding':b,**audit}
        if audit['status']=='new_source_original_reference':new[n]={'binding':b,'value':audit['value'],'before':row[18],'sources':audit['selected'],'confirmed':False}
    if digest(file)!=before:raise Rejected('材质核验期间当前表变化，未写入')
    overlay={**prior,**new};save(back/'material-reference-overlay.json',{'schema':'linked-material-original-overlay/1','rows':overlay,'database_sha256':db['sha256'],'approved':0})
    result={'schema':'linked-material-original-review/1','database':db,'rows':reviews,'summary':{'rows':len(reviews),'new_reference_rows':len(new),'existing_preserved_rows':sum(r['status']=='existing_value_preserved' for r in reviews.values()),'status_counts':dict(Counter(r['status'] for r in reviews.values())),'rejected_candidate_rows':sum(bool(r['rejected']) for r in reviews.values()),'website_queried':False,'confirmed':0}}
    # Preserve prior website execution reasons; a stopped site is not reported
    # as a fresh attempted query for every row.
    prior_web=back/'material-review-complete.json'
    if prior_web.exists():
        result['website_review_reference']=load(prior_web)
        source=result['website_review_reference'].get('reference_report')
        web_rows=load(source)['rows'] if source else {}
        for n,r in reviews.items():r['website_execution']=web_rows.get(n,{}).get('website_execution',{'status':'not_executed','reason':'nonstandard_code_not_verified_JAN'})
    if website_history:
        import shutil
        p=Path(website_history['path']).resolve(strict=True)
        if digest(p)!=website_history['sha256']:raise Rejected('此前网站查询记录摘要变化')
        target=back/'prior-website-100-summary.json';shutil.copyfile(p,target)
        result['prior_website_history']={'path':str(target),'sha256':digest(target),'summary':load(target),'scope':'prior_100_only_not_new_queries'}
    save(back/'material-reference-review.json',result)
    apply_overlay(config,file)
    return {'summary':result['summary'],'report':str(back/'material-reference-review.json'),'business_files':[str(file)],'formal_output':False}

def apply_overlay(config,file):
    back=Path(config['background']);record=back/'material-reference-overlay.json'
    if not record.exists():return
    rows=_rows(file,config['sheet']);changes=[]
    for n,r in load(record)['rows'].items():
        row=rows[int(n)-1]
        if binding(row)==r['binding'] and row[18] in (None,''):changes.append({'target':'S'+n,'value':r['value']})
    if changes:Path(file).write_bytes(_update_refs(Path(file).read_bytes(),config['sheet'],changes))

def canonical_material_return(config,file):
    record=Path(config['background'])/'material-reference-overlay.json'
    if not record.exists():return file
    rows=_rows(file,config['sheet']);changes=[]
    for n,r in load(record)['rows'].items():
        row=rows[int(n)-1]
        # An unchanged system reference is decoration even when the user edits
        # G or Q. Its applicability is rechecked after saving, never adopted.
        if row[18]==r['value']:
            changes.append({'target':'S'+n,'value':r['before']})
    if not changes:return file
    folder=Path(config['background'])/'material-canonical-returns';folder.mkdir(exist_ok=True)
    target=folder/(digest(file)+'.xlsx');data=_update_refs(Path(file).read_bytes(),config['sheet'],changes)
    if not target.exists():target.write_bytes(data)
    elif target.read_bytes()!=data:raise Rejected('材质参考回传归一化版本冲突')
    return target
