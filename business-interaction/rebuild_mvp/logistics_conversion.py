"""R3-03 unified resumable task. All source Excel cells and parts are retained."""
from pathlib import Path
import copy,csv,json,os,shutil,sqlite3
from .service import MvpError,code_version,digest,load_json,save_json,writer
from .storage import identity,canonical
from .logistics_sources import upstream,WeightEvidence,item_fact
from .logistics_math import POLICY,analyse_group,inventory,associate,reconcile,frac
from .xlsxio import read_book

SCHEMA='arrival-carton-weight/1'


def semantic(data):
    return identity({k:data[k]for k in ['policy','quantity_source','pricing_source','delivery','sources','groups','rows','totals','summary_checks','excluded_rows']})


def validate(job):
    if job['code']!=code_version():raise MvpError('SOURCE_CHANGED','箱重任务程序变化，须另建版本')
    q,p,delivery=upstream(job['config']['quantity_source'],job['config']['pricing_source'])
    if delivery!=job['delivery']:raise MvpError('SOURCE_CHANGED','数量或价税交付发生变化')
    for source in job['sources']:
        if not Path(source['path']).is_file()or digest(source['path'])!=source['sha256']:raise MvpError('SOURCE_CHANGED','箱重依据发生变化')
    return q,p


def current(job):
    validate(job)
    for item in job.get('artifacts',[]):
        if not Path(item['path']).is_file()or digest(item['path'])!=item['sha256']:raise MvpError('SOURCE_CHANGED','既有箱重交付发生变化，禁止覆盖')
    return {'schema':SCHEMA,'mode':'carton_weight','task_id':job['task_id'],'step':job['step'],'status':job['status'],
            'completed_groups':job.get('completed_groups',0),'completed_rows':job.get('completed_rows',0),
            'logistics_source':job.get('logistics_source'),'business_files':job.get('business_files',[]),'summary':job.get('summary',{}),
            'error':job.get('error'),'next_action':'current'if job['step']=='exported'else'resume',
            'acceptance':{'operator_approved':False,'formally_installed':False,'R3_complete':False,'final_paired_outputs':False}}


def checkpoint(db,table,key,facts,fn):
    fingerprint=identity(facts);old=db.execute(f'SELECT input_sha,payload_sha,payload FROM {table} WHERE id=?',(key,)).fetchone()
    if old:
        payload=json.loads(old[2])
        if old[0]!=fingerprint or old[1]!=identity(payload):raise MvpError('TASK_CONFLICT','箱重检查点漂移')
        return payload
    payload=fn()
    with db:db.execute(f'INSERT INTO {table} VALUES(?,?,?,?)',(key,fingerprint,identity(payload),canonical(payload)))
    return payload


def copy_preserved(source,output):
    source,output=Path(source),Path(output);sha=digest(source)
    if source.with_name('~$'+source.name).exists():raise MvpError('TASK_CONFLICT','上游Excel正在编辑')
    if output.exists():
        if digest(output)!=sha:raise MvpError('TASK_CONFLICT','箱重副本已有不同内容，禁止覆盖')
    else:
        temp=output.with_suffix('.copy.tmp');shutil.copyfile(source,temp)
        if digest(temp)!=sha or digest(source)!=sha:raise MvpError('SOURCE_CHANGED','复制期间上游变化')
        os.replace(temp,output)
    return {'source_sha256':sha,'output_sha256':digest(output),'byte_identical':True,'non_target_cell_changes':0,
            'all_zip_parts_formulas_caches_images_and_manual_values_preserved':True}


def handle(req):
    action=req.get('action');required=('batch_id','quantity_source','pricing_source','logistics_binding')
    if action not in {'prepare','current','resume'}:raise MvpError('INPUT_INVALID','箱重只支持prepare/current/resume')
    if action=='prepare'and set(req)-set(required)-{'workflow','action','mode','output'}:raise MvpError('CONFIG_INVALID','箱重配置含未知字段')
    location=req.get('output')if action=='prepare'else req.get('task_root')
    if not location:raise MvpError('INPUT_INVALID','缺箱重任务输出目录')
    root=Path(location).resolve()
    if action=='current':return current(load_json(root/'job.json'))
    root.mkdir(parents=True,exist_ok=True)
    with writer(root):
        jf=root/'job.json'
        if jf.exists():
            job=load_json(jf)
            if job.get('mode')!='carton_weight':raise MvpError('TASK_CONFLICT','目录不是箱重任务')
            if action=='prepare'and {k:req.get(k)for k in required}!=job['config']:raise MvpError('TASK_CONFLICT','同目录不能绑定不同箱重配置')
            q,p=validate(job)
            if job['step']=='exported':return current(job)
            evidence=WeightEvidence(job['config']['logistics_binding'],job['config']['batch_id'],job['config']['quantity_source'],job['config']['pricing_source'])
        else:
            if action!='prepare'or any(x.name!='.writer.lock'for x in root.iterdir()):raise MvpError('TASK_CONFLICT','箱重须用新目录')
            if any(not req.get(k)for k in required):raise MvpError('CONFIG_INVALID','缺数量、价税契约或箱重依据')
            config={k:copy.deepcopy(req[k])for k in required};q,p,delivery=upstream(config['quantity_source'],config['pricing_source'])
            if config['batch_id']!=q['upstream']['batch_id']:raise MvpError('INPUT_INVALID','箱重批次与数量批次不符')
            evidence=WeightEvidence(config['logistics_binding'],config['batch_id'],config['quantity_source'],config['pricing_source'])
            protected=[delivery['path'],delivery['job_path'],config['quantity_source']['path'],config['pricing_source']['path']]+[s['path']for s in evidence.versions]
            if any(Path(x).resolve().is_relative_to(root)for x in protected):raise MvpError('CONFIG_INVALID','输出目录不能包含上游或依据')
            job={'schema':SCHEMA,'mode':'carton_weight','config':config,'delivery':delivery,'sources':evidence.versions,
                 'policy':POLICY,'code':code_version(),'step':'bound','status':'running'}
            job['task_id']=identity(job);save_json(jf,job)
        db=sqlite3.connect(root/'candidate.sqlite3')
        for table in ['logistics_groups','logistics_rows']:db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,input_sha TEXT,payload_sha TEXT,payload TEXT)')
        try:
            job.update(status='running',error=None);save_json(jf,job)
            facts,source_issues,excluded=evidence.group_facts();groups=[]
            for i,fact in enumerate(facts):
                groups.append(checkpoint(db,'logistics_groups',fact['id'],fact,lambda:analyse_group(fact)))
                job.update(step='weights',completed_groups=i+1);save_json(jf,job)
            groups,index,totals=inventory(groups,source_issues)
            checks,summary_issues=evidence.audit_summaries(totals)
            book=read_book(job['delivery']['path']);sheet=next(s for s in book['sheets']if s['name']==q['upstream']['sheet'])
            rows=[]
            for i,(qr,pr)in enumerate(zip(q['rows'],p['rows'])):
                item=item_fact(qr,pr,sheet,job['delivery'])
                rows.append(checkpoint(db,'logistics_rows',item['row_id'],[item,groups,index],lambda:associate(item,groups,index)))
                job.update(step='associating',completed_rows=i+1);save_json(jf,job)
            total=reconcile(rows,groups,index,totals,evidence.data['coverage'],source_issues+summary_issues)
            validate(job)
            contract={'schema':SCHEMA,'policy':POLICY,'code_sha256':job['code']['sha256'],'quantity_source':job['config']['quantity_source'],
                      'pricing_source':job['config']['pricing_source'],'delivery':job['delivery'],'sources':job['sources'],'groups':groups,
                      'rows':rows,'totals':total,'summary_checks':checks,'excluded_rows':excluded,'operator_approved':False,'R3_complete':False}
            key=semantic(contract);contract.update(result_id=key,semantic_sha256=key)
            file=root/'carton-weight-results.json'
            if file.exists()and load_json(file)!=contract:raise MvpError('TASK_CONFLICT','已有箱重结果不同，禁止覆盖')
            if not file.exists():save_json(file,contract)
            output=root/'箱号与重量核对.xlsx';preserved=copy_preserved(job['delivery']['path'],output)
            links=root/'箱货关联.csv';pending=root/'箱重待核.csv';detail=root/'箱重明细.csv'
            with links.open('w',encoding='utf-8-sig',newline='')as f:
                w=csv.writer(f);w.writerow(['原行','商品编码','原箱号','实物箱集合','箱组引用','关联含义','数量已拆分','商品重量已分摊','状态'])
                for r in rows:w.writerow([r['row'],r['scope']['code'],r['carton_raw'],','.join(r['cartons']),','.join(sorted({g for x in r['links']for g in x['group_ids']})),r['association'],False,False,r['status']])
            with detail.open('w',encoding='utf-8-sig',newline='')as f:
                w=csv.writer(f);w.writerow(['箱组ID','原表','原行','原箱号','实物箱集合','原箱数','原单箱重','原箱组重','原重量单位','箱组重KG','重量状态','问题'])
                for g in groups:w.writerow([g['id'],g['sheet'],g['row'],g['carton_raw'],','.join(g['cartons']),g['raw']['count'],g['raw'].get('unit_weight',''),g['raw']['total_weight'],g['weight_unit'],str(frac(g['total_weight_kg']))if g['total_weight_kg']else'',g['field_states'].get('weight'),';'.join(x['code']for x in g['issues'])])
            with pending.open('w',encoding='utf-8-sig',newline='')as f:
                w=csv.writer(f);w.writerow(['范围','原行','字段','问题'])
                for scope,items in [('商品',rows),('重量',groups)]:
                    for row in items:
                        for issue in row['issues']:w.writerow([scope,row['row'],issue['field'],issue['code']])
                for issue in total['issues']:w.writerow(['批次',issue.get('row',''),issue['field'],issue['code']])
            validate(job)
            partial=bool(total['issues']or any(x['issues']for x in groups+rows))
            job.update(step='exported',status='partial'if partial else'completed',error=None,logistics_source={'path':str(file),'sha256':digest(file),'schema':SCHEMA,'result_id':key,'semantic_sha256':key},
                       business_files=[str(output)],artifacts=[{'path':str(x),'sha256':digest(x)}for x in [file,output,links,pending,detail]],
                       summary={'rows':len(rows),'groups':len(groups),'rows_with_issues':sum(bool(r['issues'])for r in rows),'totals':total,
                                'preservation':preserved,'association_file':str(links),'weight_detail_file':str(detail),'pending_reason_file':str(pending)})
            save_json(jf,job);return current(job)
        except Exception as exc:
            code=getattr(exc,'code','RUNTIME_FAILURE');job.update(status='failed',error={'code':code,'message':str(exc),'retryable':code=='RUNTIME_FAILURE'});save_json(jf,job);raise
        finally:db.close()


def read_logistics_source(ref):
    if ref.get('schema')!=SCHEMA or digest(ref['path'])!=ref['sha256']:raise MvpError('SOURCE_CHANGED','箱重契约摘要不符')
    d=load_json(ref['path'])
    if d.get('schema')!=SCHEMA or d.get('policy')!=POLICY or d.get('result_id')!=ref.get('result_id')or d.get('semantic_sha256')!=ref.get('semantic_sha256')or d.get('result_id')!=ref.get('semantic_sha256')or semantic(d)!=ref['semantic_sha256']:
        raise MvpError('SOURCE_CHANGED','箱重契约语义不符')
    _,_,delivery=upstream(d['quantity_source'],d['pricing_source'])
    if delivery!=d['delivery']:raise MvpError('SOURCE_CHANGED','箱重上游交付漂移')
    for s in d['sources']:
        if digest(s['path'])!=s['sha256']:raise MvpError('SOURCE_CHANGED','箱重来源漂移')
    return d
