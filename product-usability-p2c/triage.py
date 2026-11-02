"""Read-only candidate classification. No library or declaration decision writer."""
from collections import Counter
import hashlib
import json

UNKNOWN={'','未知','不明','待确认','待补','未找到','无资料','无数据','unknown','n/a','-','no data','not found'}
VERSION_STATES={'unknown','known','confirmed_no_independent_version','known_version_conflict'}
CORE_BASIC=('japanese_name','internal_name','customs_name','category','material')


class Rejected(ValueError):pass


def normalized(value):return ' '.join(str(value).split()).casefold()
def populated(value):return value is not None and normalized(value) not in UNKNOWN
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def version_state(current,history_versions,proof=None):
    """Unknown never becomes 'no version'. Explicit evidence changes only this state."""
    known={normalized(v) for v in history_versions if populated(v)}
    if populated(current):known.add(normalized(current))
    if len(known)>1:return 'known_version_conflict'
    if proof is not None:
        if (not isinstance(proof,dict) or set(proof)!={'kind','source_sha256','reference','explicit_confirmation'}
            or proof['kind']!='no_independent_version' or proof['explicit_confirmation'] is not True
            or not isinstance(proof['source_sha256'],str) or len(proof['source_sha256'])!=64
            or any(c not in '0123456789abcdef' for c in proof['source_sha256'])
            or not populated(proof['reference'])):raise Rejected('无独立版本必须有明确证据及确认，不接受默认值')
        if known:raise Rejected('无独立版本证据与已知版本不一致，须保留冲突')
        return 'confirmed_no_independent_version'
    # A single historical version is a candidate; it does not confirm this row.
    return 'known' if populated(current) else 'unknown'


def classify(item):
    current=item['current'];required=item['required_fields']
    if len(required)!=len(set(required)) or set(required)-set(current):raise Rejected('当前必要字段合同不完整')
    tasks=[];kept=[]
    for field in required:
        cell=current[field]
        if not populated(cell.get('value')):
            tasks.append({'field':field,'reason':'missing_current_value','action':'补充本批明确值及依据','evidence':cell.get('evidence')})
        elif field in CORE_BASIC and not isinstance(cell.get('value'),str):
            tasks.append({'field':field,'reason':'current_value_invalid_type','action':'核对本批名称/材质原值类型','evidence':cell.get('evidence')})
        elif cell.get('confirmed') is not True or not cell.get('evidence'):
            tasks.append({'field':field,'reason':'current_value_not_confirmed','action':'核对本批现有值及确认依据','evidence':cell.get('evidence')})
        else:kept.append(field)
    # Only contradictions between current values are business tasks. Historical
    # conflicts stay visible in the technical layer and cannot override them.
    for conflict in item.get('current_conflicts',[]):
        tasks.append({'field':conflict['field'],'reason':'current_confirmed_sources_conflict',
                      'action':'核实本批两个来源的差异，不选择历史值覆盖','evidence':conflict.get('evidence')})
    state=version_state(item.get('current_version'),item.get('history_versions',[]),item.get('version_proof'))
    issues=list(item.get('library_issues',[]))
    if state!='unknown':issues=[f for f in issues if f!='version']
    if state=='unknown' and 'version' not in issues:issues.append('version')
    if state=='known_version_conflict' and 'known_version_conflict' not in issues:issues.append('known_version_conflict')
    reference_conflict=bool(item.get('history_identity_conflicts')) or state=='known_version_conflict'
    return {'row_id':item['row_id'],'case_id':item.get('case_id'),'code':item.get('code'),
            'current_tasks':tasks,'current_required_fields':[t['field'] for t in tasks],
            'current_disposition':'影响当前报单' if tasks else '已有确认值不需重复处理',
            'kept_confirmed_fields':kept,'version_state':state,'version_value':item.get('current_version'),
            'library_issues':issues,'library_disposition':'仅资料库长期完善' if issues else None,
            'reference_use':'conflict_reference_only' if reference_conflict else 'reference_only',
            'history_identity_conflicts':item.get('history_identity_conflicts',[]),
            'effective_values':{f:cell.get('value') for f,cell in current.items()},
            'historical_values_applied':0,'automatic_identity_confirmation':False,
            'material_approval':False,'formal_output':False}


def summarize(items,results,old_plan):
    if [i['row_id'] for i in items]!=[r['row_id'] for r in results]:raise Rejected('分类改变原行顺序')
    counts=Counter(r['version_state'] for r in results)
    return {'rows':len(results),'before_technical_manual_cases':len(old_plan['cases']),
            'before_technical_manual_rows':old_plan['metrics']['manual_pending_rows'],
            'before_case_field_prompts':sum(len(c['unresolved_fields']) for c in old_plan['cases']),
            'before_prompt_fields':dict(Counter(f for c in old_plan['cases'] for f in c['unresolved_fields'])),
            'current_business_task_rows':sum(bool(r['current_tasks']) for r in results),
            'current_business_unique_tasks':len({r['case_id'] or r['row_id'] for r in results if r['current_tasks']}),
            'current_required_input_cells':sum(len(set(r['current_required_fields'])) for r in results),
            'current_required_fields_checked':sum(len(item['required_fields']) for item in items),
            'confirmed_rows_no_repeat':sum(not r['current_tasks'] for r in results),
            'current_confirmed_basic_values_reused':sum(f in r['kept_confirmed_fields'] for r in results for f in CORE_BASIC),
            'version_states':{k:counts[k] for k in sorted(VERSION_STATES)},
            'long_term_unique_cases_retained':len(old_plan['cases']),
            'strict_identity_before':old_plan['metrics']['before_complete_identity'],
            'strict_identity_after_unchanged':old_plan['metrics']['after_complete_identity'],
            'original_candidate_conflict_rows_unchanged':old_plan['metrics']['unresolved_original_candidate_conflict_rows'],
            'identity_field_conflict_rows_unchanged':old_plan['metrics']['after_identity_field_conflict_rows'],
            'cross_batch_material_reference_rows_unchanged':old_plan['metrics']['after_cross_batch_material_reference_rows'],
            'source_bound_spec_reference_rows':len(results)-old_plan['metrics']['after_missing_identity'].get('specification',0),
            'cross_batch_basic_reference_rows_unchanged':old_plan['metrics']['cross_batch_basic_reference_rows'],
            'historical_values_applied':sum(r['historical_values_applied'] for r in results),
            'formal_output':False,'material_approval':False,'library_write':False}
