"""Versioned human declaration choices, independently retained reference layers.

No rule discovery/publication, tax inference or external knowledge store here.
"""
import copy
from datetime import date
from decimal import Decimal

from .core import Rejected, context, digest, now, decimal, _apply_domain_row, box_tax

FACT_FIELDS = {'product_type','purpose','complete_composition','key_material_features','construction',
               'version','specification','inclusion_conditions','exclusion_conditions'}
FINAL_FIELDS = {'declaration_material','classification_code','classification_basis','tariff_schedule_version',
                'duty_rate','vat_rate','valid_from','valid_through','applicability_date','jurisdiction',
                'origin_conditions','trade_conditions'}
MATERIAL_FIELDS = {'declaration_material'}
ROLE_FIELDS = {'approve_material':'material','approve_classification':'customs','return_decision':'material'}


def head(row):
    versions = row.get('declaration',{}).get('versions',[])
    return versions[-1] if versions else None


def selected_material(row, *, approved_only=True):
    current = head(row)
    if current is None:
        return (row['material']['selected'] or {}).get('translation') if row['reviews']['material'] or not approved_only else None
    if current['context']!=context(row) or (approved_only and (not row['reviews']['material'] or not valid_review(current, 'material'))): return None
    return current['human_final'].get('declaration_material')


def review_payload(record, domain):
    value = {'context':record['context'], 'facts':record['facts'],
             'declaration_material':record['human_final'].get('declaration_material')}
    if domain == 'classification': value['classification'] = {k:v for k,v in record['human_final'].items() if k!='declaration_material'}
    return value


def valid_review(record, domain):
    proof = record['reviews'].get(domain)
    return bool(proof and proof.get('reference') and proof.get('credential_ref')
                and proof.get('payload_hash') == digest(review_payload(record,domain)))


def pending(record, row):
    missing=[]; final=record['human_final']; facts=record['facts']
    for key in sorted(FACT_FIELDS):
        if not facts.get(key): missing.append('fact:'+key)
    for key in sorted(FINAL_FIELDS):
        if not final.get(key) and final.get(key)!='0': missing.append('final:'+key)
    if not record.get('reason'): missing.append('change_reason')
    if not row['reviews']['identity'] or not all(context(row).values()): missing.append('identity_review')
    if record['context'] != context(row): missing.append('identity_context_changed')
    if facts.get('version') and facts['version'] != row['identity']['version']: missing.append('version_mismatch')
    if facts.get('specification') and facts['specification'] != row['identity']['specification']: missing.append('specification_mismatch')
    for d in row['disputes']:
        if d.get('domain') in ('identity','material','tax'):missing.append('dispute:'+d['domain'])
    if record.get('unparsed_note'): missing.append('unparsed_note_requires_clarification')
    if not valid_review(record,'material'): missing.append('material_review')
    if not valid_review(record,'classification'): missing.append('classification_review')
    if all(final.get(k) for k in ('valid_from','valid_through','applicability_date')):
        if not final['valid_from'] <= final['applicability_date'] <= final['valid_through']:
            missing.append('tariff_not_effective_for_applicability_date')
    return sorted(set(missing))


def validate_values(values):
    if not isinstance(values,dict) or set(values)-FACT_FIELDS-FINAL_FIELDS-{'reason'}:
        raise Rejected('最终选择含未知/不允许的字段')
    if any(not isinstance(v,str) for v in values.values()): raise Rejected('决策字段须为文本；数量税率用十进制字符串')
    for key in ('duty_rate','vat_rate'):
        if values.get(key) and not Decimal(0) <= decimal(values[key]) <= Decimal(1): raise Rejected('税率必须为0到1，未知使用空白')
    for key in ('valid_from','valid_through','applicability_date'):
        if values.get(key):
            try:
                if date.fromisoformat(values[key]).isoformat()!=values[key]: raise ValueError()
            except ValueError as exc: raise Rejected('日期必须为YYYY-MM-DD') from exc


def initialize(row, layers):
    value=row.setdefault('declaration',{'schema':'japan-arrival/declaration-1',
        'official_materials':[],'historical_reference_materials':[],'recommendations':[],'versions':[]})
    for kind in ('official_materials','historical_reference_materials','recommendations'):
        for item in layers.get(kind,[]):
            existing=next((i for i in value[kind] if i['id']==item['id']),None)
            if existing and existing!=item: raise Rejected('参考或推荐ID冲突，禁止原地覆盖')
            if existing is None:value[kind].append(copy.deepcopy(item))
    return value


def revise(batch,row,layers,action,values,session,reference,*,note='',tax_parameters=None,resolved_disputes=None):
    """Mutates only a caller-owned staged copy; caller validates scope and authorization."""
    validate_values(values)
    state=initialize(row,layers); old=head(row)
    current=copy.deepcopy(old) if old else {
        'decision_id':digest([batch['id'],row['id']])[:24],'version':0,'row_id':row['id'],
        'context':context(row),'facts':{},'human_final':{},'reason':'',
        'reviews':{'material':None,'classification':None},'original_recommendation_ref':None}
    current['version']+=1;current['supersedes']=old['version'] if old else None
    current['context']=context(row);current['recorded_at']=now()
    current['execution']=session.evidence();current['reference']=reference
    if action in ('edit_decision','adopt_recommendation') or old is None:current['unparsed_note']=note
    original=layers.get('current_recommendation')
    if action=='adopt_recommendation':
        if not original or not original.get('declaration_material'): raise Rejected('没有明确推荐，不能默认采用历史填写')
        values=dict(values,declaration_material=original['declaration_material'])
    if original:current['original_recommendation_ref']=original['id']
    before_material=digest(review_payload(current,'material'))
    before_classification=digest(review_payload(current,'classification'))
    for k,v in values.items():
        if k in FACT_FIELDS:current['facts'][k]=v
        elif k in FINAL_FIELDS:current['human_final'][k]=v
        elif k=='reason':current['reason']=v
    material_changed=before_material!=digest(review_payload(current,'material'))
    classification_changed=before_classification!=digest(review_payload(current,'classification'))
    if material_changed:
        current['reviews']['material']=None;row['reviews']['material']=None
    if material_changed or classification_changed:
        current['reviews']['classification']=None;row['reviews']['tax']=None;row['tax']=None
    current.pop('returned',None);current.pop('revoked',None)
    event_type={'edit_decision':'decision_edited','adopt_recommendation':'recommendation_accepted',
                'approve_material':'material_approved','approve_classification':'classification_approved',
                'return_decision':'decision_rejected','revoke_decision':'decision_revoked',
                'invalidate_classification':'decision_review_invalidated'}[action]
    if action=='invalidate_classification':
        current['reviews']['classification']=None;row['reviews']['tax']=None;row['tax']=None
    if action.startswith('approve_'):
        domain='material' if action=='approve_material' else 'classification'
        required=['change_reason','identity_review','identity_context_changed','version_mismatch',
                  'specification_mismatch','dispute:identity','dispute:material','unparsed_note_requires_clarification']
        errors=pending(current,row)
        if domain=='material': required+=['final:declaration_material']+['fact:'+k for k in FACT_FIELDS]
        else:required+=['final:'+k for k in FINAL_FIELDS]+['fact:'+k for k in FACT_FIELDS]+['material_review','tariff_not_effective_for_applicability_date','dispute:tax']
        blocked=[e for e in errors if e in required]
        if blocked:raise Rejected('最终选择审核尚缺：'+','.join(sorted(blocked)))
        current['reviews'][domain]={'confirmed_by':session.principal,'confirmed_at':now(),
            'reference':reference,'credential_ref':session.credential_ref,'execution_mode':session.mode,
            'payload_hash':digest(review_payload(current,domain)),'decision_version':current['version']}
        if domain=='material':row['reviews']['material']=dict(current['reviews'][domain],kind='declaration_decision')
        elif tax_parameters is not None:
            f=current['human_final'];p={'context':context(row),'classification':f['classification_code'],
                'effective_date':f['applicability_date'],'source':reference,'duty_rate':f['duty_rate'],
                'vat_rate':f['vat_rate'],'formula_version':'historical-box-v1',**tax_parameters}
            if set(tax_parameters)!={'tax_unit_price','tax_unit'}:raise Rejected('税基仅接收逐行明确的单价和单位')
            _apply_domain_row(row,'tax',p,actor=session.principal,evidence=reference,_declaration_commit=True)
            row['reviews']['tax'].update(kind='declaration_decision',decision_version=current['version'],execution_mode=session.mode)
            if row['reviews']['packaging']:box_tax(row)
    if action in ('return_decision','revoke_decision'):
        if not values.get('reason'):raise Rejected('退回须明确原因')
        if action=='revoke_decision' and old is None:raise Rejected('不存在可撤销的决策')
        current['reviews']={'material':None,'classification':None}
        current['revoked' if action=='revoke_decision' else 'returned']=True
        row['reviews']['material']=None;row['reviews']['tax']=None;row['tax']=None
    current['pending']=pending(current,row)
    complete=not current['pending'] and not current.get('returned') and not current.get('revoked')
    current['technical_approval_complete']=complete
    current['learning_eligible']=bool(complete and session.mode=='business')
    current['state']='revoked' if current.get('revoked') else 'returned' if current.get('returned') else ('synthetic_technical_approved' if session.mode=='synthetic_technical_test' else 'effective') if complete else 'pending_classification' if valid_review(current,'material') else 'draft'
    # Original versions/reference arrays never change. Outbox contains a full immutable decision snapshot.
    state['versions'].append(current)
    event={'schema':'japan-arrival/decision-event-1','type':event_type,'row_ids':[row['id']],
        'batch_id':batch['id'],'decision_id':current['decision_id'],'decision_version':current['version'],
        'original_recommendation':copy.deepcopy(original),'previous_final':copy.deepcopy(old['human_final']) if old else None,
        'new_selection':copy.deepcopy(current['human_final']),'reason':current['reason'],'reference':reference,
        'execution':session.evidence(),'scope':context(row),'decision':copy.deepcopy(current),
        'resolved_disputes':copy.deepcopy(resolved_disputes or []),
        'source_refs':copy.deepcopy(row['source']),'previous_event_hash':batch.get('decision_events',[])[-1]['event_id'] if batch.get('decision_events') else None}
    event['event_id']=digest(event)
    batch.setdefault('decision_events',[]).append(event)
    return event
