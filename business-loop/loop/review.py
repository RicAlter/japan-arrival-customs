"""Editable calculation review, immutable source facts, server-side recalculation."""
from pathlib import Path
from copy import deepcopy
from fractions import Fraction
from .support import bootstrap,load,save,key,digest,put,get,archive,path,field_fingerprint,Rejected,code_snapshot,check_hashes
from .prices import candidate
from .updates import Service as Updates
from separated.model import old as basic_model
from native22.pricing import decimal
from arrival_core.operations_adapter import finite

SHEET='计算审核'
HEADERS=['原业务行','箱号','JAN','中文名称','规格','已确认采购最小价','采购最小单位','日方实际最大价','最大计价单位','日方Qty','Qty实际单位','业务确认金额JPY',
 '价格推导倍数','核准每最大单位最小数','计价口径／换算依据','申报最小单位','内部盒数','申报数量','执行单价ROUND0','公开申报名称','业务品类','申报材质参考','公开品牌',
 '关税率参考','增值税率参考','税费参考出处','人工金额调整依据','当前检查','采购数量参考','采购数量单位','采购数量采用状态','更新来源坐标','业务行ID','物理每盒最小数']
EDIT={'I':'max_unit','K':'qty_unit','L':'amount','N':'factor','O':'conversion_reference','P':'declaration_unit','Q':'boxes',
      'T':'public_name','V':'material_reference','W':'brand','X':'duty_rate','Y':'vat_rate','Z':'tax_reference','AA':'amount_reference'}
NUMERIC={'L','N','Q','X','Y'}
FORMULAS={'R':lambda n:f'=IF(AND(ISNUMBER(N{n}),N{n}>0,I{n}<>"",K{n}=I{n},P{n}<>""),J{n}*N{n},"")',
 'S':lambda n:f'=IF(AND(ISNUMBER(R{n}),R{n}>0),ROUND(L{n}/R{n},0),"")',
 'AH':lambda n:f'=IF(AND(ISNUMBER(N{n}),N{n}>0,I{n}<>"",K{n}=I{n},P{n}<>""),IF(Q{n}>0,J{n}*N{n}/Q{n},IF(AND(I{n}="盒",K{n}="盒"),N{n},"")),"")'}

def current_price(fs):
    p=fs.get('purchase_unit_price');valid=bool(p and p['confirmed'] and p.get('identity_context_hash')==basic_model.identity_context({f['target']:f for f in fs.values()},p['row_id']))
    # Identity hash keys include only C/F; the per-row projection has those same keys.
    proof=p.get('evidence',{}) if p else {};unit=proof.get('unit')
    return p,valid,bool(valid and basic_model.minimum_unit(unit)),unit

def prepare(root):
    svc=Updates(root);batch,update,view=svc.active();byrow={}
    for f in view['fields'].values():byrow.setdefault(f['row_id'],{})[f['field']]=f
    original={r['id']:r for r in batch['rows']};rows=[];snapshot_hash=key(batch)
    # Procurement candidates stay an independent query snapshot, never arrival Qty.
    workflow=load(svc.owner['workflow']);parent=Path(svc.owner['workflow']).parent
    oldplan=load(parent/'technical/authoring-plan.json')
    query_byrow={r[0]:r for r in oldplan.get('query',{}).get('rows',[])}
    if not query_byrow and (parent/'technical/reference-snapshot.json').exists():
        for r in load(parent/'technical/reference-snapshot.json')['rows']:
            query_byrow[r['row']]=[r['row'],None,None,None,None,None,r['values']['purchase_quantity'],None,None,None,None,r['values'].get('purchase_quantity_unit')]
    for rid,row in original.items():
        fs=byrow.get(rid,{});match=update['matches'].get(rid);raw=match['new'] if match else None
        p,pc,mc,unit=current_price(fs)
        check=candidate(p['value']['value'] if p else None,raw['price'] if raw else None,purchase_confirmed=pc,minimum_unit_confirmed=mc,
            actual_price=update['actual_price_qualified'],comparable=bool(match))
        source_row=row['source']['row'];q=query_byrow.get(source_row,[])
        values=[source_row,raw['carton'] if raw else row['raw'].get('carton'),row['identity']['code'],fs.get('internal_name',{}).get('value',{}).get('value'),
            fs.get('specification',{}).get('value',{}).get('value'),p['value']['value'] if mc else None,unit if mc else None,raw['price'] if raw else None,None,
            raw['quantity'] if raw else None,None,raw['amount'] if raw else None,check['pieces_per_box'],check['pieces_per_box'],None,unit if mc else None,None,None,None,
            None,fs.get('category',{}).get('value',{}).get('value'),None,None,None,None,None,None,
            check['reason'] or '候选待明确计算确认',q[6] if len(q)>6 else None,q[11] if len(q)>11 else None,'候选，仅查询，不投入核算',
            (raw['source']['sheet']+'!H'+str(raw['row'])) if raw else update['issues'].get(rid),rid,None]
        # Keep complete source/confirmation history in its immutable parent
        # snapshot instead of repeating every legacy provenance block in Excel plans.
        compact={}
        for name,f in fs.items():
            compact[name]={k:deepcopy(f[k]) for k in ['target','row_id','field','cell','sheet','value','status','confirmed','identity_context_hash','evidence','confirmation','professional_approval'] if k in f}
            compact[name]['sources']=[{'kind':'inherited_immutable_basic_field','root':str(svc.root),'snapshot_hash':snapshot_hash,'target':f['target']}]
        rows.append({'parent_id':rid,'values':values,'price_check':check,'basic_fields':compact,'raw':raw,'source_row':source_row})
    data={'schema':'loop-calculation-review/1','root':str(svc.root),'batch_id':svc.bid,'base_hash':key(batch),'a_version':view['a_version'],
        'basics_fingerprint':field_fingerprint(view),'update_ref':batch['loop']['active_update'],'mode':svc.owner['mode'],'sheet':SHEET,'headers':HEADERS,
        'rows':rows,'editable':EDIT,'formulas':{c:[fn(n) for n in range(5,len(rows)+5)] for c,fn in FORMULAS.items()},
        'unlinked_new_rows':update['new_unlinked_rows'],'weights_unchanged':update['weights_unchanged'],'code':code_snapshot(),
        'source_totals_consistent':update.get('source_totals_consistent',True),
        'actual_price_qualified':update['actual_price_qualified'],'professional_approval':False,'formal_output':False}
    pid=put(svc.root,data);return {**data,'plan_id':pid,'version_token':pid}

def numeric(v,positive=False):
    n=decimal(v)
    return n if n is not None and (n>0 if positive else n>=0) else None

def recalculate(row,values,reference):
    raw=row['raw'];check=row['price_check'];errors=[];fs=row['basic_fields']
    if raw is None:return {'errors':['identity_link_pending'],'parent_id':row['parent_id']}
    for field in ['internal_name','specification','category','channel','yd']:
        if not fs.get(field,{}).get('confirmed'):errors.append('basic_unconfirmed:'+field)
    if check['reason']:errors.append(check['reason'])
    q=numeric(raw['quantity'],True);a=numeric(values.get('amount'));factor=numeric(values.get('factor'),True)
    if q is None:errors.append('actual_quantity_invalid')
    if a is None:errors.append('business_amount_invalid')
    if factor is None or factor!=factor.to_integral_value():errors.append('conversion_factor_requires_positive_integer')
    unit=values.get('max_unit');qtyunit=values.get('qty_unit');decl=values.get('declaration_unit')
    if not basic_model.unit_resolved(unit) or unit!=qtyunit:errors.append('actual_Qty_unit_must_equal_maximum_unit')
    if not basic_model.minimum_unit(decl) or decl!=row['values'][6]:errors.append('declaration_unit_must_match_confirmed_purchase_minimum_unit')
    if unit and unit==decl and factor is not None and factor!=1:errors.append('same_unit_cannot_have_nonunit_factor')
    if check['pieces_per_box'] and factor is not None and factor!=decimal(check['pieces_per_box']):errors.append('factor_differs_from_exact_price_ratio_needs_independent_resolution')
    boxes=numeric(values.get('boxes'),True)
    boxes_derived=False
    if values.get('boxes') in (None,'') and unit==qtyunit=='盒' and q is not None:boxes=q;boxes_derived=True
    if boxes is None:errors.append('internal_box_count_or_box_unit_confirmation_missing')
    elif q is not None:
        try:finite(Fraction(q)/Fraction(boxes))
        except ValueError:errors.append('internal_box_ratio_not_exact_legacy_contract')
    physical=Fraction(q)*Fraction(factor)/Fraction(boxes) if q is not None and factor is not None and boxes is not None else None
    if physical is not None and (physical<=0 or physical.denominator!=1):errors.append('physical_box_size_not_exact_integer')
    if a is not None and q is not None:
        source_price=numeric(raw['price'],True)
        if source_price is None:errors.append('actual_price_input_invalid')
        elif Fraction(a)!=Fraction(q)*Fraction(source_price) and not str(values.get('amount_reference') or '').strip():errors.append('changed_amount_requires_explicit_reference')
        try:finite(Fraction(a)/Fraction(q))
        except ValueError:errors.append('internal_unit_price_not_exact_excel_number')
    for k in ['duty_rate','vat_rate']:
        if values.get(k) not in (None,''):
            n=decimal(values[k])
            if n is None or not 0<=n<=1:errors.append(k+'_invalid')
    if any(values.get(k) not in (None,'') for k in ['duty_rate','vat_rate']) and not str(values.get('tax_reference') or '').strip():errors.append('tax_reference_required_no_default_rate')
    conversion_ref=str(values.get('conversion_reference') or '').strip() or ('已确认价格角色、精确整数比值及本次明确范围；'+reference)
    result={'parent_id':row['parent_id'],'errors':sorted(set(errors)),'values':values,'raw':raw,'quantity':str(q) if q is not None else None,
        'amount':str(a) if a is not None else None,'boxes':str(boxes) if boxes is not None else None,'boxes_derived_from_confirmed_box_unit':boxes_derived,
        'factor':str(factor) if factor is not None else None,'physical_pieces_per_box':str(physical.numerator) if physical is not None and physical.denominator==1 else None,
        'conversion_reference':conversion_ref,'purchase_quantity_consumed':False,'professional_approval':False}
    if not result['errors']:
        from arrival_core.colored_operations import round0
        result.update(declaration_quantity=finite(Fraction(q)*Fraction(factor)),execution_round0=round0(Fraction(a)/(Fraction(q)*Fraction(factor))))
    return result

def finalize_export(plan,draft_file,output):
    """Protect Artifact-authored inputs and register a generic A02 comparison map."""
    from .review_book import protect
    svc=Updates(plan['root']);canonical=get(svc.root,plan['plan_id'])
    supplied={k:v for k,v in plan.items() if k not in {'plan_id','version_token','draft_file'}}
    if supplied!=canonical or plan['version_token']!=plan['plan_id']:raise Rejected('计算审核计划与已登记来源快照不符')
    check_hashes(canonical['code'])
    data,reg=protect(Path(draft_file).read_bytes(),plan)
    output=Path(output).resolve()
    if output.exists():raise Rejected('不覆盖已发计算审核表')
    output.write_bytes(data);sha=digest(output);archive(path(svc.root/'objects'/(sha+'.xlsx')),data)
    body={'schema':'loop-review-export/1','plan_id':plan['plan_id'],'plan':{k:v for k,v in plan.items() if k not in {'plan_id','version_token'}},
        'file':str(output),'sha256':sha,'registration':reg}
    eid=put(svc.root,body);return {'export_id':eid,'file':str(output),'sha256':sha}

def preview_return(root,export_id,uploaded,*,reference,price_basis_reference=None):
    from native_return.compare import read,compare,passive_links
    from openpyxl import load_workbook
    import io
    svc=Updates(root);export=get(svc.root,export_id);plan=export['plan'];batch,active,_=svc.active()
    check_hashes(plan['code'])
    if key(batch)!=plan['base_hash']:raise Rejected('基础资料或日方版本已变化，旧计算审核表失效')
    issued=path(svc.root/'objects'/(export['sha256']+'.xlsx'))
    if digest(issued)!=export['sha256']:raise Rejected('不可变计算审核发出基准被改动')
    if not str(reference or '').strip():raise Rejected('回传须有明确出处')
    if price_basis_reference is not None and (not isinstance(price_basis_reference,str) or not price_basis_reference.strip()):raise Rejected('计价口径可比依据须为明确出处，不能从整数比值推定')
    raw=Path(uploaded).read_bytes();sha=__import__('hashlib').sha256(raw).hexdigest();archive(path(svc.root/'objects'/(sha+'.xlsx')),raw)
    baseline=issued.read_bytes();a,_=read(baseline,trusted_external=passive_links(baseline));b,_=read(raw,trusted_external=passive_links(baseline))
    try:
        changes=compare(a,b,export['registration'])
        if any(c['field'] not in EDIT.values() for c in changes):raise Rejected('原JAN、源价格、数量或其他只读事实不可修改')
    finally:a.close();b.close()
    book=load_workbook(io.BytesIO(raw),data_only=False);sheet=book[SHEET];facts=[]
    for i,row in enumerate(plan['rows'],5):
        values={name:sheet[col+str(i)].value for col,name in EDIT.items()}
        facts.append(recalculate(row,values,reference))
    book.close()
    body={'schema':'loop-calculation-preview/1','export_id':export_id,'base_hash':key(batch),'update_ref':plan['update_ref'],'mode':plan['mode'],
        'upload':str(path(svc.root/'objects'/(sha+'.xlsx'))),'upload_sha256':sha,'facts':facts,'changes':changes,'reference':reference,
        'blocked_rows':sum(bool(f['errors']) for f in facts),'new_identity_rows_pending':plan['unlinked_new_rows'],
        'weights_unchanged':plan['weights_unchanged'],'actual_price_qualified':plan['actual_price_qualified'],'formula_caches_trusted':False,'formal_output':False}
    body['source_totals_consistent']=plan.get('source_totals_consistent',True)
    body['price_basis_reference']=price_basis_reference
    body['price_comparability_pending']=price_basis_reference is None
    pointer=svc.root/'current-computation.json';current=load(pointer) if pointer.exists() else None
    body['previous_computation']=current['review_preview'] if current and current.get('parent_hash')==key(batch) else None
    if key(svc.store.load(svc.bid))!=key(batch):raise Rejected('回传重算期间基础资料/日方版本变化')
    pid=put(svc.root,body);return {**body,'preview_id':pid,'confirmation_hash':pid}
