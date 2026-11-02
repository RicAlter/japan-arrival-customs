"""Conservative evidence enrichment; partial references do not become full identity."""
import re
from collections import Counter,defaultdict

from .common import IDENTITY,BASIC,comparable,good_anchor,identity_key,key


def link_reason(query,context,fact):
    v=fact['values']
    if v.get('code_raw')!=query.get('code_raw') or v.get('code_type')!=query.get('code_type'):return None
    for f in ('japanese_name','version','specification'):
        if query.get(f) and v.get(f) and comparable(query[f])!=comparable(v[f]):return None
    if query.get('japanese_name') and v.get('japanese_name') and comparable(query['japanese_name'])==comparable(v['japanese_name']):return 'code_and_japanese_name'
    if good_anchor(context.get('yd')) and good_anchor(v.get('yd')) and context['yd']==v['yd']:return 'code_and_yd'
    if context.get('internal_name') and v.get('internal_name') and comparable(context['internal_name'])==comparable(v['internal_name']):return 'code_and_internal_name'
    return None


def nonconflicting(query,fact):
    v=fact['values']
    return (v.get('code_raw')==query.get('code_raw') and v.get('code_type')==query.get('code_type')
            and all(not query.get(f) or not v.get(f) or comparable(query[f])==comparable(v[f])
                    for f in ('japanese_name','version','specification')))


def specification_usable(value):
    # Reject price/date/order annotations; never delete digits to invent a SKU.
    return bool(value) and not re.search(r'定金|尾款|总价|预计|日元|到货|出荷|截单|[¥￥]|\d{4}年|\d+[元]',value)


def causes(row):
    reason=[]
    if any(not row['query'].get(f) for f in IDENTITY):reason.append('identity_missing')
    if not row['query'].get('version'):reason.append('version_unknown')
    if row['status'] in ('ambiguous','matched_with_conflict','identity_conflict'):reason.append('candidate_conflict')
    if not row['query'].get('code_raw'):reason.append('no_code')
    if not row.get('material_reference_available'):reason.append('material_missing')
    return reason


def analyze(p1,facts,contexts,*,target_batch_id):
    by_code=defaultdict(list)
    for fact in facts:by_code[fact['values'].get('code_raw')].append(fact)
    rows=[];case_map={};order=[];source_index={f['fact_id']:f for f in facts}
    for old in p1['rows']:
        q={f:old['query'].get(f) for f in IDENTITY};rid=old['row_id'];context=contexts.get(rid,{})
        candidates=by_code[q['code_raw']];linked=[];cross=[];original=[]
        for fact in candidates:
            why=link_reason(q,context,fact)
            if why:
                record={'fact_id':fact['fact_id'],'reason':why};linked.append(record)
                if fact['source']['batch_id']!=target_batch_id:cross.append(record)
                if fact['source']['role']=='original_b4':original.append(record)
        def resolve(records):
            fields={};conflicts={}
            for field in ('japanese_name','version','specification')+BASIC:
                values=defaultdict(list)
                for record in records:
                    fact=source_index[record['fact_id']];value=fact['values'].get(field)
                    if value is None or field=='specification' and not specification_usable(value):continue
                    values[comparable(value)].append({'value':value,'fact_id':fact['fact_id'],'evidence':fact['evidence'].get(field)})
                if len(values)==1:
                    records_for_value=next(iter(values.values()));fields[field]={'value':records_for_value[0]['value'],'sources':records_for_value}
                elif len(values)>1:conflicts[field]=[{'value':records[0]['value'],'sources':records} for records in values.values()]
            return fields,conflicts
        resolved,conflicts=resolve(linked);cross_fields,cross_conflicts=resolve(cross)
        final={f:q[f] or resolved.get(f,{}).get('value') for f in IDENTITY}
        independent={f:q[f] or cross_fields.get(f,{}).get('value') for f in IDENTITY}
        missing=[f for f in IDENTITY if not final[f]]
        verified=bool(linked) and not missing and not any(f in conflicts for f in IDENTITY)
        verified_cross=bool(cross) and all(independent.values()) and not any(f in cross_conflicts for f in IDENTITY)
        material=[f['fact_id'] for f in candidates if nonconflicting(q,f) and any(f['values'].get(k) not in (None,'','未找到','未知') for k in ('material_original','material_translation'))]
        material_cross=[fid for fid in material if source_index[fid]['source']['batch_id']!=target_batch_id]
        unresolved=set(missing)
        unresolved.update(f for f in conflicts if f in IDENTITY or f in BASIC and not context.get(f))
        if not material and not old.get('material_reference_available'):unresolved.add('material_reference')
        if old['status'] in ('ambiguous','matched_with_conflict','identity_conflict') and not verified:unresolved.add('candidate_selection')
        result={'row_id':rid,'query':old['query'],'before_status':old['status'],'causes':causes(old),'context':context,
                'candidate_fact_ids':[f['fact_id'] for f in candidates],'linked_sources':linked,'cross_batch_linked_sources':cross,
                'resolved_fields':resolved,'field_conflicts':conflicts,'identity_after':final,'missing_after':missing,
                'complete_identity_verified':verified,'cross_batch_complete_identity_verified':verified_cross,
                'basic_reference_linked':bool(linked),'cross_batch_basic_reference_linked':bool(cross),
                'before_original_basic_reference_linked':bool(original),
                'material_fact_ids':material,'cross_batch_material_fact_ids':material_cross,
                'material_reference_available_after':bool(material) or old.get('material_reference_available',False),
                'cross_batch_material_reference_available_after':bool(material_cross) or old.get('material_reference_available',False),
                'unresolved_fields':sorted(unresolved),'automatic_approval':False}
        rows.append(result)
        if unresolved:
            ckey=key({'identity':q,'context':{f:context.get(f) for f in ('yd','internal_name','material_original')}})
            if ckey not in case_map:
                case_map[ckey]={'case_id':'P'+ckey[:16],'row_ids':[],'representative_row_id':rid,'query':q,
                               'context':context,'unresolved_fields':sorted(unresolved),'candidate_fact_ids':result['candidate_fact_ids'],
                               'resolved_fields':resolved,'field_conflicts':conflicts,'original_candidates':old['candidates'],
                               'original_rejected_candidates':old['rejected_candidates']};order.append(ckey)
            case_map[ckey]['row_ids'].append(rid)
    cases=[case_map[k] for k in order]
    metrics={'rows':len(rows),'before_complete_identity':sum(any(c['match']=='exact_observed_identity' and all(c['identity'].values()) for c in r['candidates']) for r in p1['rows']),
        'after_complete_identity':sum(r['complete_identity_verified'] for r in rows),
        'after_cross_batch_complete_identity':sum(r['cross_batch_complete_identity_verified'] for r in rows),
        'cross_batch_basic_reference_rows':sum(r['cross_batch_basic_reference_linked'] for r in rows),
        'before_original_basic_reference_rows':sum(r['before_original_basic_reference_linked'] for r in rows),
        'all_scope_basic_reference_rows':sum(r['basic_reference_linked'] for r in rows),
        'before_conflict_rows':sum(r['status'] in ('ambiguous','matched_with_conflict','identity_conflict') for r in p1['rows']),
        'after_offline_field_conflict_rows':sum(bool(r['field_conflicts']) for r in rows),
        'after_identity_field_conflict_rows':sum(any(f in r['field_conflicts'] for f in IDENTITY) for r in rows),
        'unresolved_original_candidate_conflict_rows':sum(r['before_status'] in ('ambiguous','matched_with_conflict','identity_conflict') and 'candidate_selection' in r['unresolved_fields'] for r in rows),
        'before_material_reference_rows':sum(bool(r.get('material_reference_available')) for r in p1['rows']),
        'before_context_material_rows':sum(c.get('material_original') not in (None,'','未找到','未知') for c in contexts.values()),
        'before_query_missing_japanese_name':sum(not r['query'].get('japanese_name') for r in p1['rows']),
        'before_candidate_missing_japanese_name_rows':sum(bool(r['candidates']) and all(not c['identity'].get('japanese_name') for c in r['candidates']) for r in p1['rows']),
        'after_cross_batch_material_reference_rows':sum(r['cross_batch_material_reference_available_after'] for r in rows),
        'after_all_scope_material_reference_rows':sum(r['material_reference_available_after'] for r in rows),
        'manual_pending_rows':sum(bool(r['unresolved_fields']) for r in rows),'manual_unique_cases':len(cases),
        'before_causes':dict(Counter(c for row in rows for c in row['causes'])),
        'after_missing_identity':dict(Counter(f for row in rows for f in row['missing_after']))}
    return {'schema':'offline-identity-plan/1','rows':rows,'cases':cases,'facts':facts,'metrics':metrics,
            'target_batch_id':target_batch_id,'material_approval':False,'d1_accessed':False,'formal_output':False}
