"""R3-01 mode on the existing MVP prepare/current/resume interface."""
from pathlib import Path
from collections import Counter
import copy
import csv
import json
import sqlite3
import re

from .service import MvpError, code_version, digest, load_json, save_json, writer
from .storage import identity, canonical
from .quantity_math import POLICY, calculate
from .quantity_sources import Evidence, read_upstream, extract_reviewed
from .quantity_export import edits, export

SCHEMA = 'arrival-quantity/1'


def portable(value):
    if isinstance(value,dict):
        return {k:portable(v) for k,v in value.items() if k not in {'path','task_root','initial_path'}}
    if isinstance(value,list):
        return [portable(v) for v in value]
    return value


def semantic_digest(rows, policy, upstream_sha):
    return identity(portable({'rows':rows,'policy':policy,'upstream_sha256':upstream_sha}))


def validate(job):
    if job['code'] != code_version():
        raise MvpError('SOURCE_CHANGED','数量任务程序绑定变化；请另建版本')
    upstream = read_upstream(job['config']['review_task_root'],job['config']['reviewed_source'])
    if upstream != job['upstream']:
        raise MvpError('SOURCE_CHANGED','R2保存版本或回执变化')
    for source in job['sources']:
        if not Path(source['path']).is_file() or digest(source['path']) != source['sha256']:
            raise MvpError('SOURCE_CHANGED','数量依据或来源发生变化')


def current(job):
    validate(job)
    result = {'schema':SCHEMA,'mode':'quantity_conversion','task_id':job['task_id'],
              'status':job['status'],'step':job['step'],'summary':job.get('summary',{}),
              'completed_rows':job.get('completed_rows',0),'error':job.get('error'),
              'business_files':job.get('business_files',[]),'quantity_source':job.get('quantity_source'),
              'next_action':'current' if job['step']=='exported' else 'resume',
              'acceptance':{'operator_approved':False,'formally_installed':False,'R3_complete':False}}
    for artifact in job.get('artifacts',[]):
        if not Path(artifact['path']).is_file() or digest(artifact['path']) != artifact['sha256']:
            raise MvpError('SOURCE_CHANGED','数量交付物有外部修改，保留现文件')
    return result


def handle(req):
    action = req.get('action')
    if action not in {'prepare','current','resume'}:
        raise MvpError('INPUT_INVALID','数量换算只支持prepare/current/resume')
    if action == 'prepare' and set(req) - {'action','mode','workflow','batch_id','review_task_root','reviewed_source','quantity_binding','output'}:
        raise MvpError('CONFIG_INVALID','数量换算配置含不支持的字段')
    rawroot = req.get('output') if action == 'prepare' else req.get('task_root')
    if not rawroot:
        raise MvpError('INPUT_INVALID','缺少数量任务目录')
    root = Path(rawroot).resolve()
    if action == 'current':
        return current(load_json(root/'job.json'))
    root.mkdir(parents=True,exist_ok=True)
    with writer(root):
        jf = root/'job.json'
        if jf.exists():
            job = load_json(jf)
            if job.get('mode') != 'quantity_conversion':
                raise MvpError('TASK_CONFLICT','任务目录已绑定其他业务模式')
            if action == 'prepare':
                config = {k:copy.deepcopy(req[k]) for k in ('batch_id','review_task_root','reviewed_source','quantity_binding')}
                if config != job['config']:
                    raise MvpError('TASK_CONFLICT','数量任务已绑定其他输入')
            validate(job)
            if job['step'] == 'exported':
                return current(job)
            evidence = Evidence(job['config']['quantity_binding'])
        else:
            if action != 'prepare' or any(p.name != '.writer.lock' for p in root.iterdir()):
                raise MvpError('TASK_CONFLICT','新数量任务要求未占用目录')
            required = ('batch_id','review_task_root','reviewed_source','quantity_binding')
            if any(not req.get(k) for k in required):
                raise MvpError('CONFIG_INVALID','缺少R2保存引用或数量依据')
            config = {k:copy.deepcopy(req[k]) for k in required}
            for p in [config['quantity_binding'],config['reviewed_source']['path'],config['review_task_root']]:
                if Path(p).resolve().is_relative_to(root):
                    raise MvpError('CONFIG_INVALID','输出目录不能包含来源或上游任务')
            upstream = read_upstream(config['review_task_root'],config['reviewed_source'])
            if config['batch_id'] != upstream['batch_id'] or not re.fullmatch(r'[\w.-]{1,100}',str(config['batch_id'])):
                raise MvpError('INPUT_INVALID','数量阶段批次编号须与R2保存批次相同')
            evidence = Evidence(config['quantity_binding'])
            job = {'schema':SCHEMA,'mode':'quantity_conversion','config':config,'upstream':upstream,
                   'sources':evidence.versions,'code':code_version(),'policy':POLICY,
                   'status':'running','step':'bound'}
            job['task_id'] = identity(job)
            save_json(jf,job)
        rows = extract_reviewed(job['upstream'])
        row_binding = identity(rows)
        if job.get('bound_rows_sha256') and job['bound_rows_sha256'] != row_binding:
            raise MvpError('SOURCE_CHANGED','R1原行关联或继承信息变化')
        job.update(bound_rows_sha256=row_binding,status='running',error=None)
        save_json(jf,job)
        db = sqlite3.connect(root/'candidate.sqlite3')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS quantity_rows(row_id TEXT PRIMARY KEY,input_sha TEXT NOT NULL,payload_sha TEXT NOT NULL,payload TEXT NOT NULL)')
            for index,row in enumerate(rows):
                fingerprint = identity([row,evidence.data])
                saved = db.execute('SELECT input_sha,payload_sha,payload FROM quantity_rows WHERE row_id=?',(row['row_id'],)).fetchone()
                if saved:
                    if saved[0] != fingerprint or identity(json.loads(saved[2])) != saved[1]:
                        raise MvpError('TASK_CONFLICT','数量检查点漂移')
                    rows[index] = json.loads(saved[2])
                    continue
                facts, issues, candidates = evidence.facts(row)
                row['quantity'] = calculate(row['scope']['qty'],facts,row['existing'])
                row['quantity']['issues'] += issues
                row['quantity']['rejected_candidates'] += candidates
                if issues:
                    row['quantity']['status'] = 'partial'
                row['quantity']['input_facts'] = facts
                with db:
                    db.execute('INSERT INTO quantity_rows VALUES(?,?,?,?)',
                               (row['row_id'],fingerprint,identity(row),canonical(row)))
                job.update(step='calculating',completed_rows=index+1)
                save_json(jf,job)
            job.update(step='calculated',completed_rows=len(rows))
            save_json(jf,job)
            validate(job)
            semantic = semantic_digest(rows,POLICY,job['upstream']['sha256'])
            contract = {'schema':SCHEMA,'result_id':semantic,'semantic_sha256':semantic,
                        'policy':POLICY,'code_sha256':job['code']['sha256'],
                        'upstream':job['upstream'],'sources':job['sources'],'rows':rows,
                        'R3_complete':False,'operator_approved':False}
            resultfile = root/'quantity-results.json'
            if resultfile.exists() and load_json(resultfile) != contract:
                raise MvpError('TASK_CONFLICT','既有数量契约不同，禁止覆盖')
            if not resultfile.exists():
                save_json(resultfile,contract)
            changes = edits(rows)
            outfile = root/'数量与包装换算.xlsx'
            exported = export(job['upstream']['path'],outfile,job['upstream']['sheet'],changes)
            pending = root/'数量待核.csv'
            with pending.open('w',encoding='utf-8-sig',newline='') as f:
                out = csv.writer(f)
                out.writerow(['原行','商品编码','字段','原因'])
                for row in rows:
                    for issue in row['quantity']['issues']:
                        out.writerow([row['row'],row['scope']['code'],issue.get('field'),issue['code']])
            validate(job)
            counts = Counter(i['code'] for row in rows for i in row['quantity']['issues'])
            job.update(step='exported',status='partial' if counts else 'completed',
                       quantity_source={'path':str(resultfile),'sha256':digest(resultfile),
                                        'schema':SCHEMA,'semantic_sha256':semantic,'result_id':semantic},
                       summary={'rows':len(rows),'rows_with_issues':sum(bool(r['quantity']['issues']) for r in rows),
                                'issue_counts':dict(sorted(counts.items())),'filled_cells':len(changes),
                                'pending_reason_file':str(pending)},
                       business_files=[str(outfile)],export=exported,
                       artifacts=[{'path':str(p),'sha256':digest(p)} for p in (resultfile,outfile,pending)])
            save_json(jf,job)
            return current(job)
        except Exception as exc:
            code = getattr(exc,'code','RUNTIME_FAILURE')
            job.update(status='failed',error={'code':code,'message':str(exc),'retryable':code=='RUNTIME_FAILURE'})
            save_json(jf,job)
            raise
        finally:
            db.close()


def read_quantity_source(reference):
    """R3-02 read-only boundary; no price/tax computation is implemented here."""
    if reference.get('schema') != SCHEMA or digest(reference['path']) != reference['sha256']:
        raise MvpError('SOURCE_CHANGED','数量契约摘要不符')
    result = load_json(reference['path'])
    if result.get('schema') != SCHEMA or result.get('semantic_sha256') != reference['semantic_sha256']:
        raise MvpError('INPUT_INVALID','数量契约版本或语义摘要不符')
    if semantic_digest(result['rows'],result['policy'],result['upstream']['sha256']) != result['semantic_sha256']:
        raise MvpError('SOURCE_CHANGED','数量契约内容语义摘要不符')
    upstream = result['upstream']
    actual = read_upstream(upstream['task_root'],{'path':upstream['path'],'sha256':upstream['sha256'],
                                                'role':'reviewed_basics','version':'operator-return-'+str(upstream['revision'])})
    if actual != upstream:
        raise MvpError('SOURCE_CHANGED','数量契约的R2上游已更新')
    for source in result['sources']:
        if digest(source['path']) != source['sha256']:
            raise MvpError('SOURCE_CHANGED','数量契约来源已更新')
    return result


def usable_quantity(row, unit):
    """Return only a typed, non-conflicting quantity for downstream arithmetic."""
    quantity = row['quantity']
    if quantity['field_states'].get(unit) not in {'inherited','derived'}:
        return None
    return quantity['results'].get(unit)
