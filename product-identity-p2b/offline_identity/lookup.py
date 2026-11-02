"""Independent read-only lookup of offline facts and explicitly maintained references."""
import json
from contextlib import closing

from .common import read_only,require_b4,digest,Rejected,key,IDENTITY,FIELDS
from .analyze import analyze


def batch_query(database,queries,*,batch_id):
    if not batch_id:raise Rejected('需提供本次查询批次，区分同批与跨批来源')
    before=digest(database)
    with closing(read_only(database)) as conn:
        require_b4(conn)
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'p2b_facts','p2b_basic_events'}<=tables:raise Rejected('本副本未登记离线身份资料')
        facts=[json.loads(r[0]) for r in conn.execute('SELECT payload FROM p2b_facts ORDER BY rowid')]
        events=[json.loads(r[0]) for r in conn.execute('SELECT payload FROM p2b_basic_events ORDER BY rowid')]
    for event in events:
        if event.get('material_approval') is not False or event.get('approval') is not False:raise Rejected('非法基础维护事件')
        facts.append({'fact_id':key(event),'values':event['values'],
            'evidence':{f:{'source_workbook_sha256':event['source_workbook_sha256'],
                          'cell':event['cell_evidence'].get(f),'basis':event['basis'],
                          'selected_fact_ids':event['selected_fact_ids'],'value_origin':event.get('value_origins',{}).get(f)}
                        for f in event['values']},
            'source':{'path':'maintenance://'+key(event),'file_name':'已确认基础资料回传',
                      'sheet':'人工补充','row':event['case_id'],'batch_id':'maintenance:'+event['source_workbook_sha256'],
                      'role':'explicit_basic_maintenance'},'review_status':'reference_only','approval':False})
    rows=[];contexts={};ids=set()
    for item in queries:
        if not isinstance(item,dict) or set(item)-{'row_id','query','context'}:raise Rejected('查询记录结构无效')
        rid=item['row_id'];q=item['query']
        if not isinstance(rid,str) or rid in ids:raise Rejected('查询行号必须为唯一文本')
        if set(q)-set(IDENTITY) or any(v is not None and not isinstance(v,str) for v in q.values()):raise Rejected('身份查询须使用原始文本及允许字段')
        if not isinstance(item.get('context',{}),dict) or set(item.get('context',{}))-FIELDS:raise Rejected('查询上下文字段无效')
        ids.add(rid);contexts[rid]=item.get('context',{})
        rows.append({'row_id':rid,'query':{f:q.get(f) for f in IDENTITY},'candidates':[],
                     'rejected_candidates':[],'status':'incomplete_identity','material_reference_available':False})
    result=analyze({'rows':rows},facts,contexts,target_batch_id=batch_id)
    if digest(database)!=before:raise Rejected('查询期间资料副本变化')
    return {'schema':'offline-identity-batch-query/1','database_sha256':before,'rows':result['rows'],
            'metrics':result['metrics'],'facts':facts,'maintenance_events':len(events),
            'material_approval':False,'d1_accessed':False,'formal_output':False}
