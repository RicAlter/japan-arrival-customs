"""D1-derived candidates and chronological identity/approval holdout; no publication."""
import copy, json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from .core import Rejected, digest
from .classification_contract import contract, day, identity, reference, signature, timestamp, TARGET
from .knowledge_source import eligible

def records_from_library(library):
    """Read D1 commits rather than interpreting _current(as_of) as history.

    Both the human event and its source/authorization bundle must have been
    available at the replay cutoff. Late imports cannot become earlier knowledge.
    """
    with library._lock():
        head, *_ = library._load()
        pointer, commits = head['commit'], []
        while pointer:
            entry = json.loads(library._objects('commits', pointer).read_text(encoding='utf-8'))
            commits.append(entry); pointer = entry['previous']
        output = []
        for entry in reversed(commits):
            bundle = json.loads(library._objects('objects', entry['bundle']).read_text(encoding='utf-8'))
            for event in bundle['events']:
                d = event['decision']; proof = d['reviews'].get('classification')
                origin = next((e for e in bundle['events'] if proof and e['decision_id'] == d['decision_id']
                               and e['decision_version'] == proof['decision_version']), None)
                group = digest([bundle['batch_id'], origin.get('transaction_id') or origin['event_id'],
                                proof['confirmed_by'], proof['credential_ref'], proof['reference'], 'classification']) if origin else None
                output.append({'batch_id': bundle['batch_id'], 'decision_id': d['decision_id'],
                               'event_id': event['event_id'], 'version': d['version'],
                               'event_time': d['recorded_at'], 'available_at': entry['committed_at'],
                               'decision': copy.deepcopy(d), 'source_bundle': entry['bundle'],
                               'source_refs': event['source_refs'], 'independent_approval_group': group,
                               '_bundle': bundle, '_event': event})
        return output

def snapshot(records, cutoff, *, realm='formal', effective_date=None):
    limit = timestamp(cutoff); effective_date = effective_date or limit.date().isoformat(); day(effective_date)
    selected = {}
    for r in records:
        if not r.get('event_time') or not r.get('available_at'): continue
        if timestamp(r['event_time']) > limit or timestamp(r['available_at']) > limit: continue
        key = (r['batch_id'], r['decision_id']); order = (r['version'], timestamp(r['available_at']))
        if key not in selected or order > selected[key][0]: selected[key] = (order, r)
    output = []
    for _, r in selected.values():
        value = copy.copy(r)
        if '_bundle' in value:
            q = eligible(value['_event'], value['_bundle'], effective_date)
        else:
            # Standalone fixtures can exercise algorithms only in the TEST realm.
            q = {'realm':'test', 'eligible':bool(value.get('technical_fixture')),
                 'reasons':[] if value.get('technical_fixture') else ['not_authoritative_D1_record']}
            d = value['decision']; f = d['human_final']
            if d.get('state') != 'effective' or d.get('origin') == 'automatic_rule' or not f.get('valid_from','') <= effective_date <= f.get('valid_through',''):
                q.update(eligible=False, reasons=['inactive_or_automatic_fixture'])
        value['eligibility'] = q; output.append(value)
    return output

def cutoff_for(value):
    return datetime.combine(date.fromisoformat(day(value)), time.max, timezone.utc).isoformat()

def components(records):
    """Keep all versions of a JAN and an entire approval transaction in one fold."""
    parent = list(range(len(records))); seen = {}
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i, r in enumerate(records):
        keys = [('identity', identity(r)), ('decision', r['batch_id'], r['decision_id'])]
        if r.get('independent_approval_group'): keys.append(('approval', r['independent_approval_group']))
        for key in keys:
            if key in seen: parent[find(i)] = find(seen[key])
            seen[key] = i
    result = defaultdict(list)
    for i, r in enumerate(records): result[find(i)].append(r)
    return list(result.values())

def discover(versions, *, as_of, realm='formal'):
    day(as_of)
    if realm not in ('formal','test'): raise Rejected('仅支持formal/test隔离区')
    usable, excluded = [], Counter()
    for v in versions:
        q = v.get('eligibility',{})
        if not q.get('eligible') or q.get('realm') != realm:
            excluded.update(q.get('reasons') or ['outside_requested_realm']); continue
        try: conditions, target = contract(v['decision'])
        except Rejected: excluded['incomplete_condition_contract'] += 1; continue
        if not v.get('independent_approval_group'):
            excluded['missing_independent_approval'] += 1; continue
        usable.append((v, conditions, target))
    grouped = defaultdict(list)
    for v, facts, target in usable: grouped[signature(facts,target)].append((v,facts,target))
    candidates = []
    for key, values in sorted(grouped.items()):
        support = [v for v,_,_ in values]; groups = sorted({v['independent_approval_group'] for v in support})
        independent = components(support)
        intervals = [{'valid_from':v['decision']['human_final']['valid_from'],
                      'valid_through':v['decision']['human_final']['valid_through'], 'source':reference(v)} for v in support]
        # A later bundle may contain an unchanged old decision plus unrelated new
        # rows. Bind support validity to immutable event/version IDs; preserve the
        # bundle references as evidence without treating re-import as a decision.
        candidates.append({'candidate_id':key, 'candidate_version':digest([{k:v[k] for k in ('batch_id','decision_id','event_id','version')} for v in support]),
                           'status':'candidate_rule' if len(independent)>1 else 'case_reference_only',
                           'realm':realm, 'conditions':values[0][1], 'target':values[0][2],
                           'support':[reference(v) for v in support], 'support_decision_ids':[v['decision_id'] for v in support],
                           'independent_approval_groups':groups, 'independent_approval_count':len(groups),
                           'independent_support_count':len(independent), 'identity_count':len({identity(v) for v in support}),
                           'validity_evidence':intervals,
                           'classification_evidence':[v['decision']['human_final']['classification_basis'] for v in support],
                           'automatic_adoption':False})
    conflicts = []
    for i, left in enumerate(candidates):
        for right in candidates[i+1:]:
            if left['conditions'] != right['conditions'] or left['target'] == right['target']: continue
            overlap = any(a['valid_from']<=b['valid_through'] and b['valid_from']<=a['valid_through']
                          for a in left['validity_evidence'] for b in right['validity_evidence'])
            if overlap: conflicts.append({'kind':'overlapping_conditions_different_joint_result',
                                         'candidate_ids':[left['candidate_id'],right['candidate_id']],
                                         'support':left['support']+right['support']})
    for c in candidates: c['conflicted'] = any(c['candidate_id'] in x['candidate_ids'] for x in conflicts)
    report = {'schema':'japan-arrival/d2-report-1', 'as_of':as_of, 'realm':realm,
              'formal_current_decisions':len(usable) if realm=='formal' else 0, 'eligible_decisions':len(usable),
              'approval_groups':len({v['independent_approval_group'] for v,_,_ in usable}),
              'identities':len({identity(v) for v,_,_ in usable}), 'excluded':dict(excluded),
              'candidates':candidates, 'conflicts':conflicts, 'automatic_adoption':False,
              'quality_threshold':'unapproved',
              'notice':'无可用正式样本' if realm=='formal' and not usable else '仅候选，须验证及授权发布'}
    report['report_hash'] = digest(report); return report

def replay(records, *, as_of, realm='formal'):
    """Chronological leave-component-out validation with explicit denominators."""
    end = cutoff_for(as_of); current = snapshot(records,end,realm=realm)
    eligible_rows = [v for v in current if v['eligibility']['eligible'] and v['eligibility']['realm']==realm]
    all_known = [v for v in records if v.get('available_at') and timestamp(v['available_at'])<=timestamp(end)]
    fold_keys = {}
    for group in components(all_known):
        keys = {(v['batch_id'],v['decision_id']) for v in group}
        for key in keys: fold_keys[key] = keys
    rows, counters = [], Counter()
    for test in sorted(eligible_rows,key=lambda x:(x['event_time'],x['event_id'])):
        limit = test['event_time']; held = fold_keys.get((test['batch_id'],test['decision_id']),set())
        training = [v for v in snapshot(records,limit,realm=realm) if
                    (v['batch_id'],v['decision_id']) not in held and timestamp(v['event_time'])<timestamp(limit)]
        report = discover(training,as_of=timestamp(limit).date().isoformat(),realm=realm)
        try: conditions,target = contract(test['decision'])
        except Rejected: continue
        candidates = [c for c in report['candidates'] if c['status']=='candidate_rule' and not c['conflicted']
                      and c['conditions']==conditions and any(x['valid_from']<=timestamp(limit).date().isoformat()<=x['valid_through'] for x in c['validity_evidence'])]
        predicted = candidates[0]['target'] if len(candidates)==1 else None
        compared = {k:predicted[k]==target[k] for k in TARGET} if predicted else {}
        counters['covered'] += bool(predicted)
        if predicted:
            counters['material_correct'] += compared['declaration_material']
            counters['classification_correct'] += compared['classification_code']
            counters['tariff_correct'] += all(compared[k] for k in ('duty_rate','vat_rate','tariff_schedule_version'))
            counters['joint_correct'] += all(compared.values())
        rows.append({'test':reference(test), 'conditions':conditions, 'cutoff':limit, 'held_out_decisions':sorted([list(k) for k in held]),
                     'available_training':len(training), 'prediction':predicted, 'human_final':target,
                     'comparison':compared, 'uncovered_reason':None if predicted else 'no_unambiguous_prior_independent_support'})
    def metric(n,d): return {'numerator':n,'denominator':d,'value':n/d if d else None}
    unique = {v['event_id']:v for v in all_known}
    edits = [v for v in unique.values() if v['version']>1 and v.get('_event',{}).get('type') in ('decision_edited','decision_revoked','decision_rejected')]
    # Raw edits/revocations are evidence, not automatically an approved correction.
    # Count a correction only when two distinct effective human choices exist for
    # one decision, in the requested isolation realm.
    history=defaultdict(list)
    for v in unique.values():
        q=eligible(v['_event'],v['_bundle'],timestamp(v['event_time']).date().isoformat()) if '_bundle' in v else {'eligible':False}
        if q.get('eligible') and q.get('realm')==realm:
            history[(v['batch_id'],v['decision_id'])].append(v)
    corrected=set()
    for key,items in history.items():
        items.sort(key=lambda v:v['version'])
        if any((v['decision']['facts'],v['decision']['human_final']) != (items[0]['decision']['facts'],items[0]['decision']['human_final']) for v in items[1:]):
            corrected.add(key)
    result = {'schema':'japan-arrival/d2-replay-1', 'as_of':as_of, 'realm':realm, 'formal_metrics':realm=='formal',
              'time_cutoff_enforced':True, 'holdout':'chronological_leave_identity_and_approval_component_out', 'rows':rows,
              'metrics':{'evaluated_decisions':len(rows),'replayable':len(rows),'unreviewed_predictions':0,
                         'coverage':metric(counters['covered'],len(rows)),
                         'material_accuracy':metric(counters['material_correct'],counters['covered']),
                         'classification_accuracy':metric(counters['classification_correct'],counters['covered']),
                         'tariff_accuracy':metric(counters['tariff_correct'],counters['covered']),
                         'joint_accuracy':metric(counters['joint_correct'],counters['covered']),
                         'human_correction_rate':metric(len(corrected),len(history))},
              'counterexamples':[r for r in rows if r['prediction'] and not all(r['comparison'].values())],
              'inactive_current_decisions':[reference(v) for v in current if not v['eligibility']['eligible']],
              'correction_events':[reference(v) for v in edits], 'approved_corrected_decisions':[list(k) for k in sorted(corrected)],
              'raw_edits_are_not_approved_corrections':True,'automatic_adoption':False}
    result['report_hash'] = digest(result); return result

def analyze_library(library, *, as_of, realm='formal'):
    records = records_from_library(library)
    discovery = discover(snapshot(records,cutoff_for(as_of),realm=realm),as_of=as_of,realm=realm)
    return {'discovery':discovery,'validation':replay(records,as_of=as_of,realm=realm),'automatic_adoption':False}
