"""Only the P1/P2-B read interfaces are imported; no legacy ProductLibrary."""
from collections import Counter
from contextlib import closing
from pathlib import Path

from .support import Rejected,digest,key


def inspect_database(config):
    if not isinstance(config,dict) or 'database' not in config or set(config)-{'database','current_batch_id'} or not isinstance(config['database'],str):
        raise Rejected('资料库配置只接受明确database路径及可选current_batch_id')
    if 'current_batch_id' in config and (not isinstance(config['current_batch_id'],str) or not config['current_batch_id'].strip()):raise Rejected('外部业务批次标识须为明确文本，不从文件名猜测')
    path=Path(config['database']).resolve(strict=True)
    # P1's mode=ro connection must not create/ignore a live WAL or hot journal.
    if any(Path(str(path)+s).exists() for s in ('-wal','-shm','-journal')):
        raise Rejected('资料库有活动日志，需使用业务停止写入后的独立静态快照')
    before=digest(path)
    from product_reference.database import read_only,require_b4
    with closing(read_only(path)) as conn:
        meta=require_b4(conn)
        if meta.get('schema_version')!='3':raise Rejected('仅支持已核对的B4基础v3/来源V1，禁止旧库迁移')
        required_observation={'identity_key','source_id','source_record_id','purchase_candidate_state'}
        if not required_observation<={r['name'] for r in conn.execute('PRAGMA table_info(source_ingest_observations)')}:raise Rejected('B4缺少P1查询必要结构')
        if conn.execute('PRAGMA journal_mode').fetchone()[0].lower()!='delete':raise Rejected('资料库须为静态DELETE日志快照，不切换原库日志模式')
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        overlay={'p2b_facts','p2b_plans','p2b_basic_events'}
        if tables&overlay and not overlay<=tables:raise Rejected('P2-B扩展表不完整，不能静默降级')
        if overlay<=tables:
            required={'p2b_facts':{'fact_id','payload'},'p2b_plans':{'plan_id','payload','reference'},
                      'p2b_basic_events':{'event_id','plan_id','case_id','preview_hash','payload','recorded_at'}}
            for table,cols in required.items():
                if not cols<={r['name'] for r in conn.execute('PRAGMA table_info('+table+')')}:raise Rejected('P2-B扩展结构不兼容')
    if digest(path)!=before:raise Rejected('检查资料库期间内容变化')
    return {'path':str(path),'sha256':before,'base_schema':'3','source_schema':'1','p2b_available':overlay<=tables,
            'current_batch_id':config.get('current_batch_id'),'read_only':True}


def query(info,batch):
    from product_reference.query import BatchQuery
    originals=[s['sha256'] for s in batch['sources'] if s.get('kind')=='operations_original']
    queries=[];contexts={}
    for row in batch['rows']:
        i=row['identity'];rid=row['id']
        # confirmed_source_identifier is the input adapter's namespace label;
        # its raw source code maps to P1's source_identifier, never guessed JAN.
        queries.append({'row_id':rid,'code_raw':i['code'] or None,'code_type':'source_identifier' if i['code'] else None,
                        'japanese_name':i.get('japanese_name') or None,'version':i.get('version') or None,
                        'specification':i.get('specification') or None})
        contexts[rid]={f:row['product'].get(f) for f in ('internal_name','yd','category')}
    p1=BatchQuery(info['path']).run(queries,exclude_file_sha256=originals)
    overlay=None;excluded=[]
    if info['p2b_available']:
        from offline_identity.lookup import batch_query
        from offline_identity.analyze import analyze
        request=[{'row_id':q['row_id'],'query':{k:v for k,v in q.items() if k!='row_id'},'context':contexts[q['row_id']]} for q in queries]
        target=info.get('current_batch_id') or batch['business_batch_id']
        raw=batch_query(info['path'],request,batch_id=target)
        # The existing API is reused unchanged. Same-input observations can be
        # evidence, but are excluded from the independent historical candidate layer.
        facts=[]
        for f in raw['facts']:
            if f.get('approval') is not False or f.get('review_status')!='reference_only':raise Rejected('P2-B来源含非法批准状态')
            if f['source'].get('sha256') in originals or f['source'].get('batch_id')==target:
                excluded.append(f['fact_id']);continue
            facts.append(f)
        overlay=analyze(p1,facts,contexts,target_batch_id=target)
        overlay['maintenance_events']=raw['maintenance_events']
        overlay['excluded_same_input_fact_ids']=excluded
    if digest(info['path'])!=info['sha256']:raise Rejected('查询资料库期间内容变化')
    if [r['row_id'] for r in p1['rows']]!=[r['id'] for r in batch['rows']]:raise Rejected('资料库查询改变原行范围')
    return {'database':info,'p1':p1,'p2b':overlay,'excluded_input_sha256':originals,
            'namespace_mapping':{'from':'confirmed_source_identifier','to':'source_identifier','basis':'同一原始运营商品编码，不推定JAN'},
            'automatic_identity_confirmation':False,'material_approval':False,'formal_output':False}
