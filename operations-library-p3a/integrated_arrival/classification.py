"""Build P2-C inputs from the NEW verified batch, never from the old holdout plan."""
from collections import Counter

from .support import Rejected,key


def classify_batch(batch,data,library):
    from triage import classify,CORE_BASIC,populated
    p1=library['p1']['rows'];overlay=library['p2b']
    overlay_rows=overlay['rows'] if overlay else [None]*len(p1)
    facts={f['fact_id']:f for f in overlay['facts']} if overlay else {}
    results=[];long_term=set();versions=Counter();formal=Counter()
    units=batch['operations_adapter']['units'];reference=units.get('reference')
    if units.get('confirm') is not True or not populated(reference):raise Rejected('本批确认依据不足')
    for index,(row,base,extra) in enumerate(zip(batch['rows'],p1,overlay_rows)):
        c=data['customs']['rows'][index];i=data['internal']['rows'][index];rid=row['id']
        if base['row_id']!=rid or extra and extra['row_id']!=rid:raise Rejected('分类来源行不一致')
        evidence=row.get('operations_provenance')
        if not evidence:raise Rejected('当前字段缺少来源证据，不能计算异常总数')
        values={'carton':row['raw']['carton'],'origin':row['raw']['origin'],
                'japanese_name':row['identity']['japanese_name'],'internal_name':row['product']['internal_name'],
                'customs_name':row['product']['customs_name'],'category':row['product']['category'],
                'material':row['material']['selected']['translation'],
                'business_quantity':row['authority']['quantity'],'business_price':i[9],
                'business_amount':row['authority']['amount'],'internal_boxes':row['packaging']['internal_boxes'],
                'internal_quantity':row['packaging']['internal_quantity'],'pieces_per_box':row['packaging']['pieces_per_box'],
                'declaration_quantity':c[5],'declaration_price':c[6],
                'declaration_amount':data['caches']['customs']['P'+str(index+2)],
                'duty_rate':(row.get('operational_tax_input') or {}).get('rate'),
                'vat_rate':(row.get('operational_tax_input') or {}).get('vat_rate'),
                'box_tax':data['caches']['internal'].get('R'+str(index+2)),
                'business_unit':units['business_unit'],'internal_unit':units['internal_unit'],
                'declaration_unit':units['declaration_unit'],'declaration_factor':row['packaging']['declaration_factor']}
        # Reference comes from the engine-validated current request, not library
        # candidates. No operation here writes back values to row or payload.
        current={f:{'value':v,'confirmed':True,'evidence':{'source_row':row['original_pairing'],
                 'source_fields':evidence,'reference':reference}} for f,v in values.items()}
        candidates=base['candidates'];rejected=base['rejected_candidates']
        history_versions=[a['identity'].get('version') for a in candidates+rejected]
        identity_conflicts=[]
        if rejected:identity_conflicts.append('rejected_identity_candidates')
        if base['status']=='ambiguous':identity_conflicts.append('ambiguous_candidates')
        issues=set(base['missing_identity'])
        if base['status'] in ('ambiguous','matched_with_conflict','identity_conflict'):issues.add('candidate_selection')
        if not base['material_reference_available']:issues.add('material_reference_missing')
        if extra:
            issues.update(extra['unresolved_fields'])
            identity_conflicts.extend(f for f in ('japanese_name','version','specification') if f in extra['field_conflicts'])
            history_versions.extend(facts[f]['values'].get('version') for f in extra['candidate_fact_ids'])
        # A code is optional when the existing adapter can validate a legitimate
        # no-code case. It never becomes a required new library repair task.
        issues.discard('code_raw');issues.discard('code_type')
        item={'row_id':rid,'code':row['identity']['code'],'current':current,'required_fields':list(values),
              'current_version':row['identity'].get('version') or None,'history_versions':history_versions,
              'history_identity_conflicts':sorted(set(identity_conflicts)),'library_issues':sorted(issues)}
        result=classify(item)
        if result['effective_values']!=values or result['historical_values_applied']!=0:raise Rejected('候选覆盖了当前确认值')
        # Missing box-tax output is dependent on missing tax inputs; it is a
        # visible pending calculation, not another manual tax amount to invent.
        result['manual_input_fields']=sorted({t['field'] for t in result['current_tasks']} - ({'box_tax'} if values['duty_rate'] is None or values['vat_rate'] is None else set()))
        result['source_rows']=row['original_pairing'];result['formal_missing_unchanged']=row['confirmed_input']['formal_missing']
        results.append(result);versions[result['version_state']]+=1;formal.update(result['formal_missing_unchanged'])
        if result['library_issues']:
            long_term.add(key({'query':{f:base['query'].get(f) for f in ('code_raw','code_type','japanese_name','version','specification')},'context':{f:row['product'].get(f) for f in ('internal_name','yd')},
                              'material':values['material']}))
    if len(results)!=len(batch['rows']):raise Rejected('分类未覆盖完整新批次')
    batch_issues=[]
    if data['batch_difference']!='0':batch_issues.append({'reason':'current_confirmed_batch_amount_conflict','difference_jpy':data['batch_difference']})
    summary={'rows':len(results),'business_exception_rows':sum(bool(r['current_tasks']) for r in results),
             'business_exception_batches':len(batch_issues),
             'business_exception_total':sum(bool(r['current_tasks']) for r in results)+len(batch_issues),
             'manual_input_cells':sum(len(r['manual_input_fields']) for r in results),
             'confirmed_rows_no_repeat':sum(not r['current_tasks'] for r in results),
             'confirmed_basic_values_reused':sum(f in r['kept_confirmed_fields'] for r in results for f in CORE_BASIC),
             'long_term_cases':len(long_term),'version_states':dict(versions),
             'p1_candidate_statuses':library['p1']['summary'],
             'strict_identity_references':sum(any(a['match']=='exact_observed_identity' and all(a['identity'].values()) and not a['conflicts'] for a in r['candidates']) for r in p1),
             'p2b_available':overlay is not None,'p2b_complete_identity_references':overlay['metrics']['after_complete_identity'] if overlay else None,
             'same_input_facts_excluded':len(overlay['excluded_same_input_fact_ids']) if overlay else 0,
             'formal_missing_counts_unchanged':dict(formal),'historical_values_applied':0,
             'automatic_identity_confirmation':False,'material_approval':False,'formal_output':False}
    return {'rows':results,'batch_issues':batch_issues,'summary':summary}
