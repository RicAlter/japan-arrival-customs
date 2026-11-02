"""Repeat the held-out replay without uploading private rows or approving materials."""
import argparse
import csv
import json
from pathlib import Path
from collections import Counter
from contextlib import closing

from offline_identity.common import digest,key,save,read_only,Rejected,IDENTITY
from offline_identity.analyze import analyze
from offline_identity.review import preview
from offline_identity.maintenance import apply,confirmed_events
from offline_identity.lookup import batch_query


def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def run(cfg):
    out=Path(cfg['output']);out.mkdir(parents=True,exist_ok=False)
    plan=load(cfg['plan']);payload=dict(plan);claimed=payload.pop('plan_id')
    if key(payload)!=claimed:raise Rejected('计划哈希无效')
    p1=load(cfg['p1_results'])
    if digest(cfg['p1_results'])!=plan['p1_result_sha256']:raise Rejected('基线结果变化')
    protected={str(Path(p).resolve()):h for p,h in cfg['protected_files'].items()}
    for s in plan['source_reports']:protected[s['source']]=s['sha256']
    protected[cfg['p1_database']]=p1['database_sha256']
    for p,h in protected.items():
        if digest(p)!=h:raise Rejected('受保护文件变化：'+Path(p).name)
    replay=analyze(p1,plan['facts'],{r['row_id']:r['context'] for r in plan['rows']},target_batch_id=plan['target_batch_id'])
    if replay['metrics']!=plan['metrics']:raise Rejected('同一原行回放统计不一致')
    queries=[{'row_id':r['row_id'],'query':{f:r['query'].get(f) for f in IDENTITY},'context':r['context']} for r in plan['rows']]
    before=digest(cfg['database'])
    query=batch_query(cfg['database'],queries,batch_id=plan['target_batch_id'])
    if [r['row_id'] for r in query['rows']]!=[r['row_id'] for r in plan['rows']]:raise Rejected('查询改变原行顺序')
    for a,b in zip(query['rows'],plan['rows']):
        if (a['identity_after']!=b['identity_after'] or a['cross_batch_material_fact_ids']!=b['cross_batch_material_fact_ids']):
            # Fact storage order is intentionally independent of result ordering.
            if a['identity_after']!=b['identity_after'] or set(a['cross_batch_material_fact_ids'])!=set(b['cross_batch_material_fact_ids']):raise Rejected('回放身份/材质参考不一致')
    returned=preview(cfg['database'],claimed,cfg['workbook'])
    if returned['edits']:raise Rejected('真实验收只允许尚未填写的人工表')
    try:
        apply(cfg['database'],returned,confirmation={'kind':'explicit_basic_product_maintenance_confirmation',
              'preview_hash':returned['preview_hash'],'operator_reference':'VALIDATION:blank-must-not-write'})
    except Rejected as e:
        if '没有已明确确认' not in str(e):raise
    else:raise Rejected('空白表未阻断写入')
    if digest(cfg['database'])!=before:raise Rejected('只读回放或空白表修改了副本')
    events=confirmed_events(cfg['database'],claimed)
    if events:raise Rejected('未人工确认的真实验收不应产生维护事件')
    with closing(read_only(cfg['database'])) as c:
        dbcheck=c.execute('PRAGMA integrity_check').fetchone()[0]
        source_count=c.execute('SELECT COUNT(*) FROM source_ingest_observations').fetchone()[0]
        no_code=c.execute("SELECT COUNT(*) FROM source_ingest_observations WHERE json_extract(identity_json,'$.code_raw') IS NULL").fetchone()[0]
    for p,h in protected.items():
        if digest(p)!=h:raise Rejected('验收期间受保护文件变化：'+Path(p).name)
    before_causes={f:plan['metrics']['before_causes'].get(f,0) for f in ['identity_missing','version_unknown','candidate_conflict','no_code','material_missing']}
    with (out/'missing-causes.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        w=csv.writer(stream);w.writerow(['reason','rows','categories_overlap']);w.writerows([k,v,True] for k,v in before_causes.items())
    result={'schema':'offline-identity-real-acceptance/1','rows_replayed':len(query['rows']),
            'metrics':plan['metrics'],'missing_causes':before_causes,'database_integrity':dbcheck,
            'unchanged_original_observations_in_copy':source_count,'no_code_observations_retained':no_code,
            'real_human_confirmation_events':len(events),'blank_return_edits':len(returned['edits']),
            'working_copy_unchanged_by_replay':True,'protected_files_unchanged':len(protected),
            'lookup_same_batch_complete_identity':query['metrics']['after_complete_identity'],
            'lookup_cross_batch_complete_identity':query['metrics']['after_cross_batch_complete_identity'],
            'source_reports':plan['source_reports'],'plan_id':claimed,
            'material_approval':False,'d1_accessed':False,'formal_output':False,'workbuddy_tested':False}
    save(out/'acceptance.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_reports','metrics')},ensure_ascii=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);run(load(p.parse_args().config))
