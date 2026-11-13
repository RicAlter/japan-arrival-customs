"""One sparse A business view over immutable source facts; no B input adapter."""
from copy import deepcopy
from decimal import Decimal
from .support import Rejected, key

CONFIRMED = {'business_confirmed','adopted_reference','reference_confirmed'}
REQUIRED = {'internal_name','category','material_reference'}


def value(typ, raw):
    if typ == 'blank' or raw is None: return {'type':'blank','value':None}
    if typ == 'number':
        from native22.pricing import decimal
        n = decimal(raw)
        if n is None: raise Rejected('非有限数值')
        return {'type':'number','value':format(n.normalize(),'f')}
    if typ not in ('text','error','bool') or (typ=='bool' and not isinstance(raw,bool)) or (typ in ('text','error') and not isinstance(raw,str)):
        raise Rejected('不支持的基础字段类型')
    if typ in ('text','error') and len(raw)>32767: raise Rejected('文本超长')
    return {'type':typ,'value':raw}


def observed(cell):
    raw=cell.get('v')
    return value('number' if isinstance(raw,Decimal) else 'bool' if isinstance(raw,bool) else 'error' if cell.get('type')=='e' else 'blank' if raw in (None,'') else 'text',raw)


def identity_context(fields, row_id):
    return key({k:f['value'] for k,f in fields.items() if f['row_id']==row_id and f['field'] in ('product_code','specification')})


def fields_from_baseline(reg, sheet):
    fields={}
    for f in reg['fields']:
        target=f['sheet']+'!'+f['cell']
        fields[target]={'target':target,'row_id':f['row_id'],'sheet':f['sheet'],'cell':f['cell'],'field':f['field'],
                        'value':observed(sheet.cells.get(f['cell'],{})), 'status':f['status'],'confirmed':False,
                        'sources':f['sources'],'original_formula':f.get('original_formula'),
                        'working_formula':sheet.cells.get(f['cell'],{}).get('f'), 'professional_approval':False}
    for r in reg['row_map']:
        for role,name in [('code','product_code'),('origin','origin')]:
            cell=r['source']['cells'].get(role)
            if not cell:continue
            if role=='origin' and cell['value'] not in ('',None):continue
            target=r['source']['sheet']+'!'+cell['cell']
            fields[target]={'target':target,'row_id':r['row_id'],'sheet':r['source']['sheet'],'cell':cell['cell'],'field':name,
                            'value':observed(sheet.cells.get(cell['cell'],{})), 'status':'source_observation','confirmed':False,
                            'sources':[r['source']], 'original_formula':cell.get('formula'),
                            'working_formula':sheet.cells.get(cell['cell'],{}).get('f'),'professional_approval':False}
    return fields


def effective_fields(baseline, state):
    fields=deepcopy(baseline['fields'])
    for target,record in state['overrides'].items():
        allowed={'row_id','field','value','status','confirmed','professional_approval','evidence','identity_context_hash',
                 'value_origin','sources','prior_sources','confirmation'}
        if set(record)-allowed:raise Rejected('A字段记录含有未允许的属性')
        if target not in fields or record['field']!=fields[target]['field'] or record['row_id']!=fields[target]['row_id']:
            raise Rejected('A字段脱离原行对应')
        if record['value']!=value(record['value']['type'],record['value']['value']) or record['status'] not in CONFIRMED|{'saved_pending'}:
            raise Rejected('A字段内容或状态无效')
        if record['confirmed']!=(record['status'] in CONFIRMED) or record.get('professional_approval') is not False:
            raise Rejected('基础确认状态被混同为专业批准')
        fields[target].update(deepcopy(record))
    return fields


def eligibility(field, evidence, basis, fields):
    typ,raw=field['value']['type'],field['value']['value'];name=field['field']
    if name in REQUIRED and (typ!='text' or not raw.strip() or raw.strip().casefold() in ('未知','待确认','不明','#n/a')):
        raise Rejected('缺项/错误内容只能保存待核，不能确认：'+field['target'])
    if name in ('internal_name','specification','category','material_reference','channel','yd','origin','product_code') and typ not in ('text','blank','number'):
        raise Rejected('该基础字段格式待核：'+field['target'])
    if name=='product_code' and typ!='text': raise Rejected('改码须为保留前导零的文本；空码保持待核')
    if name in ('specification','channel','yd','origin') and typ not in ('text','blank'):
        raise Rejected('文本基础资料格式待核：'+field['target'])
    if name in ('purchase_unit_price','pieces_per_box'):
        from native22.pricing import decimal
        n=decimal(raw) if typ in ('text','number') else None
        if n is None or n<0 or (name=='pieces_per_box' and (n<=0 or n!=n.to_integral_value())):
            raise Rejected('价格/盒规值无效，只能保存待核：'+field['target'])
        required={'source_ref','source_kind','price_basis_hash','currency'} if name=='purchase_unit_price' else {'source_ref','meaning'}
        if not isinstance(evidence,dict) or set(evidence)!=required or not isinstance(evidence.get('source_ref'),str) or not evidence['source_ref'].strip():
            raise Rejected('本批价格/盒规采用需有范围明确的依据：'+field['target'])
        if name=='purchase_unit_price' and (basis.get('status')!='bound_to_dialogue_basis' or evidence['price_basis_hash']!=key(basis) or evidence['currency']!='JPY'
                                          or evidence['source_kind'] not in ('purchase_document','explicit_purchase_price_confirmation')):
            raise Rejected('采购价依据未绑定本批已确认的价格口径')
        if name=='pieces_per_box' and evidence['meaning']!='pieces_per_box':raise Rejected('盒规依据含义不符')
    elif evidence and (set(evidence)!={'source_ref'} or not isinstance(evidence['source_ref'],str) or not evidence['source_ref'].strip()):
        raise Rejected('基础字段依据格式无效')
    return {'evidence':deepcopy(evidence or {}),'identity_context_hash':identity_context(fields,field['row_id'])}


def recheck(source, baseline_sheet, baseline, state):
    from native22.pricing import analyze, decimal
    fields=effective_fields(baseline,state);projection=deepcopy(baseline_sheet)
    source_projection=dict(source);source_projection['sheet']=deepcopy(source['sheet'])
    manual={};query_fields=[]
    for target,f in fields.items():
        fs={'row_id':f['row_id'],'field':f['field'],'status':'candidate' if f['status']=='candidate' else f['status']}
        query_fields.append(fs)
        record=state['overrides'].get(target)
        if not record:continue
        name=f['field'];rid=f['row_id'];raw=f['value']['value']
        confirmed=record['confirmed'] and record.get('identity_context_hash')==identity_context(fields,rid)
        if name=='purchase_unit_price' and confirmed:
            proof=record.get('evidence',{})
            confirmed=(proof.get('price_basis_hash')==key(baseline['price_basis']) and proof.get('currency')=='JPY'
                       and proof.get('source_kind') in ('purchase_document','explicit_purchase_price_confirmation') and bool(proof.get('source_ref')))
        if name=='pieces_per_box' and confirmed:
            confirmed=(record.get('evidence',{}).get('meaning')=='pieces_per_box' and bool(record.get('evidence',{}).get('source_ref')))
        if name in ('purchase_unit_price','pieces_per_box'):
            projection.cells.setdefault(f['cell'],{})['v']=decimal(raw) if f['value']['type'] in ('text','number') else None
            if confirmed:
                if name=='pieces_per_box':source_projection['sheet'].cells.setdefault(f['cell'],{}).pop('f',None)
            else:manual.setdefault(rid,{})[name]=raw
        if name in ('product_code','specification') and f['value']!=baseline['fields'][target]['value']:
            # A saved code/spec is not itself evidence that old prices belong to the new context.
            manual.setdefault(rid,{})[name]=raw
    report=analyze(source_projection,projection,query_fields,baseline['price_basis'],manual=manual)
    report['value_basis']='A03_effective_business_projection_not_uploaded_formula_cache'
    for r in report['rows']:
        r['original_purchase_observation']=str(baseline_sheet.cells.get(r['g_cell'],{}).get('v'))
    return fields,report
