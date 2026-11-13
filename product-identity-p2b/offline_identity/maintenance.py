"""The maintenance writer only appends basic-reference events to a P1 clone."""
import json
import sqlite3
from contextlib import closing

from .common import working_copy,digest,key,canonical,Rejected,now,FIELDS,IDENTITY,BASIC


def register_plan(database,plan,reference):
    path,marker=working_copy(database)
    if not reference:raise Rejected('缺少本次离线资料维护授权引用')
    payload=dict(plan);claimed=payload.pop('plan_id')
    if key(payload)!=claimed:raise Rejected('补充计划哈希不一致')
    for report in plan.get('source_reports',[]):
        if digest(report['source'])!=report['sha256']:raise Rejected('离线原始资料已变化，计划失效')
    facts={f['fact_id']:f for f in plan['facts']}
    if len(facts)!=len(plan['facts']):raise Rejected('来源观察ID重复')
    for fact in facts.values():
        if set(fact['values'])-FIELDS or fact.get('approval') is not False:raise Rejected('来源含未知或批准字段')
    with closing(sqlite3.connect(path)) as conn,conn:
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS p2b_facts (fact_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS p2b_plans (plan_id TEXT PRIMARY KEY,payload TEXT NOT NULL,reference TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS p2b_basic_events (event_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,
            case_id TEXT NOT NULL,preview_hash TEXT NOT NULL,payload TEXT NOT NULL,recorded_at TEXT NOT NULL);
        ''')
        old=conn.execute('SELECT payload FROM p2b_plans WHERE plan_id=?',(claimed,)).fetchone()
        if old and old[0]!=canonical(plan):raise Rejected('计划ID已绑定不同数据')
        for fid,fact in facts.items():
            previous=conn.execute('SELECT payload FROM p2b_facts WHERE fact_id=?',(fid,)).fetchone()
            if previous and previous[0]!=canonical(fact):raise Rejected('同一来源ID已绑定不同证据')
            conn.execute('INSERT OR IGNORE INTO p2b_facts VALUES (?,?)',(fid,canonical(fact)))
        conn.execute('INSERT OR IGNORE INTO p2b_plans VALUES (?,?,?)',(claimed,canonical(plan),reference))
    return {'plan_id':claimed,'source_facts':len(facts),'original_database_unchanged':digest(marker['source'])==marker['source_sha256'],
            'declaration_approval':False,'formal_output':False}


def load_plan(database,plan_id):
    path,_=working_copy(database)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        row=conn.execute('SELECT payload FROM p2b_plans WHERE plan_id=?',(plan_id,)).fetchone()
    if not row:raise Rejected('补充计划未登记到本工作副本')
    return json.loads(row[0])


def apply(database,preview,*,confirmation):
    path,marker=working_copy(database)
    required={'kind','preview_hash','operator_reference'}
    if (not isinstance(confirmation,dict) or set(confirmation)!=required
            or confirmation['kind']!='explicit_basic_product_maintenance_confirmation'
            or not confirmation['operator_reference']):raise Rejected('需维护操作侧明确确认，不能用Excel自报身份')
    payload=dict(preview);claimed=payload.pop('preview_hash')
    if key(payload)!=claimed or confirmation['preview_hash']!=claimed:raise Rejected('确认范围与预览不一致')
    if not preview.get('edits'):raise Rejected('没有已明确确认的补充行，数据库保持不变')
    plan=load_plan(path,preview['plan_id']);valid_cases={c['case_id']:c for c in plan['cases']}
    content_key=key({'preview':preview,'operator_reference':confirmation['operator_reference']})
    with closing(sqlite3.connect(path)) as conn:
        previous=conn.execute('SELECT COUNT(*) FROM p2b_basic_events WHERE preview_hash=?',(claimed,)).fetchone()[0]
        if previous:
            return {'status':'unchanged_duplicate','events':previous,'material_approval':False,'formal_output':False}
    if digest(path)!=preview['database_sha256']:raise Rejected('工作库已变化，旧预览失效')
    from .review import preview as rebuild_preview
    if rebuild_preview(path,preview['plan_id'],preview['workbook'])!=preview:raise Rejected('回传文件或来源已变化，必须重新预览')
    for report in plan.get('source_reports',[]):
        if digest(report['source'])!=report['sha256']:raise Rejected('离线原始资料已变化，回写拒绝')
    with closing(sqlite3.connect(path)) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            if digest(path)!=preview['database_sha256']:raise Rejected('取得写锁前工作库变化，预览失效')
            for edit in preview['edits']:
                if edit['case_id'] not in valid_cases or set(edit['values'])-FIELDS:raise Rejected('回写含未知商品或字段')
                if edit['values'].get('code_raw')!=valid_cases[edit['case_id']]['query'].get('code_raw'):raise Rejected('不得补造或改写原编码')
                event={'case_id':edit['case_id'],'row_ids':valid_cases[edit['case_id']]['row_ids'],
                       'values':edit['values'],'selected_fact_ids':edit['selected_fact_ids'],
                       'source_kind':'explicit_user_basic_confirmation','source_workbook_sha256':preview['workbook_sha256'],
                       'basis':edit['basis'],'operator_reference':confirmation['operator_reference'],
                       'value_origins':edit['value_origins'],
                       'cell_evidence':edit['cell_evidence'],'unconfirmed_fields':edit['missing_after'],
                       'material_review_status':'reference_only','material_approval':False,'approval':False}
                eid=key([content_key,edit['case_id']])
                conn.execute('INSERT INTO p2b_basic_events VALUES (?,?,?,?,?,?)',(eid,preview['plan_id'],edit['case_id'],claimed,canonical(event),now()))
            conn.commit()
        except Exception:conn.rollback();raise
    if digest(marker['source'])!=marker['source_sha256']:raise Rejected('原库发生变化，本次验收失效')
    return {'status':'basic_references_appended','events':len(preview['edits']),
            'original_database_unchanged':True,'material_approval':False,'d1_accessed':False,'formal_output':False}


def confirmed_events(database,plan_id):
    path,_=working_copy(database)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        rows=conn.execute('SELECT payload FROM p2b_basic_events WHERE plan_id=? ORDER BY rowid',(plan_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]
