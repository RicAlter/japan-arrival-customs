"""Read-only adapter from committed B2 states. No new human approval authority."""
import copy,json
from datetime import datetime
from pathlib import Path

from .core import Rejected,digest,context
from .contracts import effective_permissions,contract_status
from .storage import Store,check_sources
from .excel_return import decision_event_stream
from .declaration_decisions import FACT_FIELDS,FINAL_FIELDS,valid_review,validate_values

LAYERS=('official_materials','historical_reference_materials','recommendations')
TYPES={'decision_edited','recommendation_accepted','material_approved','classification_approved',
       'decision_rejected','decision_review_invalidated','decision_revoked','automatic_rule_applied','rule_executed'}

def stamp(value):
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is None:raise ValueError('审核时间必须带时区')
    return parsed

def validate_events(events):
    previous=None;versions={};ids=set()
    for e in events:
        if e['schema']!='japan-arrival/decision-event-1' or e['type'] not in TYPES:raise Rejected('未知决策事件')
        if digest({k:v for k,v in e.items() if k not in ('event_id','transaction_id')})!=e['event_id']:
            raise Rejected('决策事件哈希不符')
        if e['event_id'] in ids or e['previous_event_hash']!=previous:raise Rejected('事件重复或链不完整')
        ids.add(e['event_id']);previous=e['event_id'];d=e['decision'];key=e['decision_id'];old=versions.get(key)
        if (d['decision_id']!=key or d['version']!=e['decision_version'] or
            e['row_ids']!=[d['row_id']] or d['context']!=e['scope'] or
            d['human_final']!=e['new_selection'] or d['execution']!=e['execution']):raise Rejected('事件与决策不一致')
        if d['version']!=(old['version']+1 if old else 1) or d['supersedes']!=(old['version'] if old else None):
            raise Rejected('决策版本继承不连续')
        if e['previous_final']!=(old['human_final'] if old else None):raise Rejected('旧选择与版本链不符')
        validate_values(dict(d['facts'],**d['human_final'],reason=d['reason']))
        stamp(d['recorded_at']);versions[key]=d
    return versions

def authorization(batch,events,config):
    """Capture public authorization facts, never export session tokens or their hashes.

    The B2 host's administrator-protected configuration is the trust boundary. Its
    public attestation is sealed by the library commit, so later token rotation or
    source removal does not make the index the only remaining evidence.
    """
    config_hash=digest(config) if config else None;result={}
    for e in events:
        d=e['decision'];checks={}
        for domain,role in (('material','material'),('classification','customs')):
            proof=d['reviews'].get(domain);errors=[];grant=None
            contract=batch.get('input_contract')
            if not contract or not contract_status(contract,batch['rows'])['approved_for_business_review']:
                errors.append('missing_signed_D08')
            if not proof:errors.append('missing_review')
            else:
                try:
                    # Inherited material approval may refer to an earlier decision version.
                    origin=next(x for x in events if x['decision_id']==d['decision_id'] and
                                x['decision_version']==proof['decision_version'])
                    ex=origin['execution']
                    if origin['type']!=('material_approved' if domain=='material' else 'classification_approved'):
                        errors.append('not_human_approval_event')
                    if origin['decision']['reviews'].get(domain)!=proof:errors.append('review_origin_mismatch')
                    if ex.get('config_hash')!=config_hash:errors.append('trusted_config_not_available')
                    entries=[s for s in (config or {}).get('sessions',[]) if s['principal']==proof['confirmed_by']
                             and s['credential_ref']==proof['credential_ref'] and s['mode']==proof['execution_mode']]
                    grant=next((s for s in entries if role in s['roles'] and
                        stamp(proof['confirmed_at'])<=stamp(s['expires_at'])),None)
                    if not grant:errors.append('role_or_credential_invalid_at_review')
                    if ex['principal']!=proof['confirmed_by'] or ex['mode']!=proof['execution_mode'] or role not in ex['roles']:
                        errors.append('execution_does_not_cover_review')
                    permitted=effective_permissions(batch,{proof['confirmed_by']:grant['roles'] if grant else []})
                    if role not in permitted.get(proof['confirmed_by'],[]):errors.append('D08_not_authorized')
                    if not valid_review(d,domain):errors.append('review_payload_changed')
                    if stamp(proof['confirmed_at'])>stamp(d['recorded_at']) and origin is not e:
                        errors.append('review_time_after_decision')
                except (KeyError,TypeError,ValueError,StopIteration,Rejected):errors.append('invalid_review_evidence')
            checks[domain]={'valid':not errors,'reasons':sorted(set(errors)),
                'public_grant':{k:copy.deepcopy(grant[k]) for k in ('principal','roles','mode','credential_ref','expires_at')} if grant else None,
                'verified_config_hash':config_hash}
        result[e['event_id']]=checks
    return result

def capture(store_root,batch_id,*,source_kind):
    if source_kind not in ('business','synthetic','authorized_test_fixture'):raise Rejected('未知来源隔离区')
    store=Store(store_root);batch=store.load(batch_id);check_sources(batch)
    events=list(decision_event_stream(batch));validate_events(events)
    rows={r['id']:r for r in batch['rows']};selected={rid for e in events for rid in e['row_ids']}
    public_rows={}
    for rid in selected:
        r=rows[rid];dec=r['declaration']
        public_rows[rid]={'context':context(r),'identity_review':copy.deepcopy(r['reviews']['identity']),
            'disputes':copy.deepcopy(r['disputes']),'layers':{k:copy.deepcopy(dec.get(k,[])) for k in LAYERS},
            'versions':copy.deepcopy(dec['versions']),'source':copy.deepcopy(r['source'])}
    try:config=json.loads((store.root/'security/trusted_sessions.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):config=None
    # A test fixture remains in the TEST realm even if a caller requests business enrollment.
    marker=batch.get('execution_mode','business')
    if marker=='authorized_test_fixture' and source_kind!='authorized_test_fixture':raise Rejected('授权测试夹具不能作为业务来源')
    if source_kind=='authorized_test_fixture' and (marker!='authorized_test_fixture' or
        not batch.get('test_fixture_id') or (config or {}).get('purpose')!='authorized_test_fixture'):
        raise Rejected('测试学习集须有显式夹具及独立测试权限标记')
    return {'schema':'japan-arrival/knowledge-source-1','store_root':str(store.root),'batch_id':batch_id,
        'snapshot_hash':digest(batch),'revision':batch['revision'],'source_kind':source_kind,
        'batch_execution_mode':marker,'test_fixture_id':batch.get('test_fixture_id'),
        'input_contract':copy.deepcopy(batch.get('input_contract')),'events':events,'rows':public_rows,
        'authorization':authorization(batch,events,config)}

def validate_bundle(bundle):
    if bundle['schema']!='japan-arrival/knowledge-source-1':raise Rejected('来源版本不支持')
    latest=validate_events(bundle['events']);by_row={}
    for e in bundle['events']:
        if e['batch_id']!=bundle['batch_id']:raise Rejected('事件跨批次')
        r=bundle['rows'][e['row_ids'][0]];d=e['decision']
        if d not in r['versions'] or e['source_refs']!=r['source']:raise Rejected('快照版本或来源与事件不一致')
        by_row.setdefault(d['row_id'],[]).append(d)
    for rid,versions in by_row.items():
        if bundle['rows'][rid]['versions']!=versions:raise Rejected('快照存在无事件的版本或顺序不一致')
    for r in bundle['rows'].values():
        for kind in LAYERS:
            refs=r['layers'][kind];seen={}
            for ref in refs:
                if not isinstance(ref.get('id'),str) or ref['id'] in seen:raise Rejected('参考层ID重复/缺失')
                seen[ref['id']]=True
    return latest

def eligible(e,bundle,as_of):
    """Recompute eligibility; never trust a client's learning_eligible boolean."""
    from datetime import date
    date.fromisoformat(as_of);d=e['decision'];r=bundle['rows'][d['row_id']];f=d['human_final'];reasons=[]
    mode=bundle['batch_execution_mode'];kind=bundle['source_kind'];execution=e['execution']
    realm='test' if kind=='authorized_test_fixture' and mode=='authorized_test_fixture' else 'formal'
    if mode=='synthetic_technical_test' or kind=='synthetic' or execution.get('mode')=='synthetic_technical_test':reasons.append('synthetic_authority')
    if realm=='formal' and (mode!='business' or kind!='business'):reasons.append('not_business_source')
    if execution.get('mode')!='business':reasons.append('not_human_business_mode')
    if e['type'] in ('automatic_rule_applied','rule_executed') or d.get('automatic_rule_ref') or d.get('origin')=='automatic_rule':reasons.append('automatic_execution')
    if d.get('returned') or d['state']=='returned':reasons.append('returned')
    if d.get('revoked') or d['state']=='revoked':reasons.append('revoked')
    if d['state']!='effective':reasons.append('not_effective')
    if d.get('pending') or d.get('unparsed_note'):reasons.append('unresolved_review')
    for k in FACT_FIELDS:
        if not d['facts'].get(k):reasons.append('missing_fact:'+k)
    for k in FINAL_FIELDS:
        if not f.get(k) and f.get(k)!='0':reasons.append('missing_final:'+k)
    if not d.get('reason'):reasons.append('missing_reason')
    if not r['identity_review'] or not all(d['context'].values()) or d['context']!=r['context']:reasons.append('identity_not_current')
    if d['facts'].get('version')!=d['context']['version'] or d['facts'].get('specification')!=d['context']['specification']:reasons.append('scope_mismatch')
    if any(x.get('domain') in ('identity','material','tax') for x in r['disputes']):reasons.append('unresolved_dispute')
    for domain in ('material','classification'):
        attestation=bundle['authorization'][e['event_id']][domain];grant=attestation.get('public_grant');proof=d['reviews'].get(domain)
        role='material' if domain=='material' else 'customs'
        if (not valid_review(d,domain) or not attestation['valid'] or not grant or not proof
            or role not in grant.get('roles',[]) or grant.get('mode')!='business'
            or grant.get('principal')!=proof.get('confirmed_by') or grant.get('credential_ref')!=proof.get('credential_ref')):
            reasons.append('invalid_'+domain+'_authority')
    try:
        for k in ('valid_from','valid_through','applicability_date'):date.fromisoformat(f[k])
        if not f['valid_from']<=f['applicability_date']<=f['valid_through']:reasons.append('invalid_applicability_date')
        if not f['valid_from']<=as_of<=f['valid_through']:reasons.append('not_effective_on_query_date')
    except (KeyError,ValueError,TypeError):reasons.append('missing_validity')
    return {'realm':realm,'eligible':not reasons,'reasons':sorted(set(reasons))}
