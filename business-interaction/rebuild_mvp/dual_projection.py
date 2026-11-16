"""R4-02 unified draft pair projection and immutable save receipt."""
from pathlib import Path
import copy,csv,json,sqlite3
from .service import MvpError,code_version,digest,load_json,save_json,writer,HERE
from .storage import identity
from .xlsxio import read_book
from .purchase_images import image_rows
from .projection_sources import graph,ProjectionEvidence,TEMPLATE
from .projection_math import POLICY,weight_cells,project_row,totals,private_tokens
from .projection_export import export_customs
from .logistics_conversion import checkpoint,copy_preserved

SCHEMA='arrival-dual-projection/1'
REQUIRED=('batch_id','review_task_root','reviewed_source','quantity_source','pricing_source','logistics_source','projection_binding','renderer')


def renderer_files(renderer):
    if set(renderer)!={'node','node_modules'}:raise MvpError('CONFIG_INVALID','renderer只绑定部署Node与bundled node_modules')
    paths=[Path(renderer['node']),Path(renderer['node_modules'])/'@oai/artifact-tool/package.json']
    if not all(p.is_file()for p in paths):raise MvpError('CONFIG_INVALID','缺部署提供的Artifact运行环境')
    return [{'path':str(p.resolve()),'sha256':digest(p)}for p in paths]


def validate(job):
    if code_version()!=job['code']:raise MvpError('SOURCE_CHANGED','双表任务程序变化，须另建版本')
    q,p,l,delivery=graph(job['config'])
    if delivery!=job['delivery']:raise MvpError('SOURCE_CHANGED','双表上游保存版本发生变化')
    for source in job['sources']:
        if not Path(source['path']).is_file()or digest(source['path'])!=source['sha256']:raise MvpError('SOURCE_CHANGED','投影依据/模板/运行环境发生变化')
    return q,p,l


def current(job):
    validate(job)
    for a in job.get('artifacts',[]):
        if not Path(a['path']).is_file()or digest(a['path'])!=a['sha256']:raise MvpError('SOURCE_CHANGED','已保存双表发生变化，禁止覆盖')
    return {'schema':SCHEMA,'mode':'dual_projection','task_id':job['task_id'],'status':job['status'],'step':job['step'],
            'completed_rows':job.get('completed_rows',0),'business_files':job.get('business_files',[]),'pair_source':job.get('pair_source'),
            'summary':job.get('summary',{}),'error':job.get('error'),'next_action':'current'if job['step']=='saved'else'resume',
            'acceptance':{'operator_approved':False,'professional_approved':False,'formal_output':False,'formally_installed':False,'R4_complete':False}}


def internal_audit(book,q,l):
    main=next(s for s in book['sheets']if s['name']==q['upstream']['sheet']);pics=image_rows(book['path'],main['name'])if 'path'in book else set()
    issues=[];raw={r['row']:r for r in main['rows']}
    for row in q['rows']:
        r=raw[row['row']]
        for col in ['F','G','H','N','O','U','V','W','X']:
            value=r['values'].get(col,'')
            if value=='':issues.append({'book':'internal','row':row['row'],'column':col,'field':col,'code':'INTERNAL_FIELD_MISSING_OR_FORMULA_CACHE'})
            elif r['types'].get(col)in {'e','b'}:issues.append({'book':'internal','row':row['row'],'column':col,'field':col,'code':'INTERNAL_CELL_TYPE_REVIEW'})
        if row['row']not in pics:issues.append({'book':'internal','row':row['row'],'column':'E','field':'picture','code':'PICTURE_LINK_AWAITING_EMBED'if r['values'].get('E','')else'PICTURE_MISSING'})
    # Compare the actual saved weight page to the audited R3 source, rather than
    # relabelling a stale/synthetic inherited page as the current physical total.
    source=l['groups'][0]['evidence']['carton']if l['groups']else None
    matching=False
    if source and len(book['sheets'])==2:
        expected=next(s for s in read_book(source['path'])['sheets']if s['name']==source['sheet']);other=next(s for s in book['sheets']if s['name']!=main['name'])
        key=lambda s:[{'row':r['row'],'values':r['values'],'formulas':r['formulas']}for r in s['rows']if r['values']or r['formulas']]
        matching=key(expected)==key(other)
    if not matching:issues.append({'book':'internal','row':1,'column':'A','field':'weight_page','code':'INHERITED_WEIGHT_PAGE_DIFFERS_FROM_R3_SOURCE'})
    return issues,{'existing_picture_rows':sorted(pics),'weight_page_matches_r3_source':matching,'original_page_preserved':True}


def semantic(data):
    return identity({k:data[k]for k in ['policy','config','delivery','sources','rows','totals','internal_issues','internal_audit','upstream_issues','templates','files']})


def handle(req):
    action=req.get('action')
    if action not in {'prepare','current','resume'}:raise MvpError('INPUT_INVALID','双表只支持prepare/current/resume')
    if action=='prepare'and set(req)-set(REQUIRED)-{'workflow','action','mode','output'}:raise MvpError('CONFIG_INVALID','双表配置包含未知字段')
    location=req.get('output')if action=='prepare'else req.get('task_root')
    if not location:raise MvpError('INPUT_INVALID','缺双表输出目录')
    root=Path(location).resolve()
    if action=='current':return current(load_json(root/'job.json'))
    root.mkdir(parents=True,exist_ok=True)
    with writer(root):
        jf=root/'job.json'
        if jf.exists():
            job=load_json(jf)
            if job.get('mode')!='dual_projection':raise MvpError('TASK_CONFLICT','目录不是双表任务')
            if action=='prepare'and {k:req.get(k)for k in REQUIRED}!=job['config']:raise MvpError('TASK_CONFLICT','同目录不能改双表绑定')
            q,p,l=validate(job)
            if job['step']=='saved':return current(job)
            evidence=ProjectionEvidence(job['config']['projection_binding'],job['config'])
        else:
            if action!='prepare'or any(x.name!='.writer.lock'for x in root.iterdir()):raise MvpError('TASK_CONFLICT','双表须使用新目录')
            if any(not req.get(k)for k in REQUIRED):raise MvpError('CONFIG_INVALID','缺R2/R3结果或投影配置')
            config={k:copy.deepcopy(req[k])for k in REQUIRED};q,p,l,delivery=graph(config);evidence=ProjectionEvidence(config['projection_binding'],config)
            versions=evidence.versions+renderer_files(config['renderer'])
            paths=[delivery['path'],delivery['job_path'],config['reviewed_source']['path']]+[config[k]['path']for k in ['quantity_source','pricing_source','logistics_source']]+[x['path']for x in versions]
            roots=[Path(config['review_task_root']).resolve()]+[Path(config[k]['path']).resolve().parent for k in ['quantity_source','pricing_source','logistics_source']]
            if any(Path(x).resolve().is_relative_to(root)for x in paths)or any(root.is_relative_to(parent)for parent in roots):raise MvpError('CONFIG_INVALID','输出不得包含来源或写入旧任务')
            job={'schema':SCHEMA,'mode':'dual_projection','config':config,'delivery':delivery,'sources':versions,'code':code_version(),'policy':POLICY,'step':'bound','status':'running'}
            job['task_id']=identity(job);save_json(jf,job)
        book=read_book(job['delivery']['path']);book['path']=job['delivery']['path'];main=next(s for s in book['sheets']if s['name']==q['upstream']['sheet'])
        tokens=private_tokens(main);weights=weight_cells(l);rows=[]
        db=sqlite3.connect(root/'candidate.sqlite3')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS projection_rows(id TEXT PRIMARY KEY,input_sha TEXT,payload_sha TEXT,payload TEXT)')
            job.update(status='running',error=None);save_json(jf,job)
            for index,(qr,pr,lr)in enumerate(zip(q['rows'],p['rows'],l['rows'])):
                public,issues=evidence.public(qr);facts=[qr,pr,lr,public,issues,weights,tokens,index+2]
                rows.append(checkpoint(db,'projection_rows',qr['row_id'],facts,lambda:project_row(qr,pr,lr,public,issues,weights,tokens,index+2)))
                job.update(step='projecting',completed_rows=index+1);save_json(jf,job)
            total=totals(rows);internal_issues,iaudit=internal_audit(book,q,l);upstream_issues=[]
            for qr,pr,lr in zip(q['rows'],p['rows'],l['rows']):
                for kind,issues in [('quantity',qr['quantity']['issues']),('price',pr['pricing']['issues']),('logistics',lr['issues'])]:
                    for issue in issues:upstream_issues.append({'kind':kind,'row':qr['row'],'field':issue.get('field',''),'code':issue['code']})
            for group in l['groups']:
                for issue in group['issues']:upstream_issues.append({'kind':'weight:'+group['sheet'],'row':group['row'],'field':issue['field'],'code':issue['code']})
            for issue in l['totals']['issues']:upstream_issues.append({'kind':'weight_summary','row':issue.get('row',''),'field':issue['field'],'code':issue['code']})
            validate(job);job['step']='exporting';save_json(jf,job)
            internal=root/'内部到货表_待核.xlsx';customs=root/'海关报单_草稿.xlsx'
            internal_proof=copy_preserved(job['delivery']['path'],internal)
            customs_proof=export_customs(rows,total,customs,job['config']['renderer'],tokens)
            validate(job)
            template=load_json(TEMPLATE)
            contract={'schema':SCHEMA,'policy':POLICY,'code_sha256':job['code']['sha256'],'config':job['config'],'delivery':job['delivery'],'sources':job['sources'],
                      'rows':rows,'totals':total,'internal_issues':internal_issues,'internal_audit':iaudit,'upstream_issues':upstream_issues,
                      'templates':{'internal':template['internal_id'],'customs':template['customs_id'],'sha256':digest(TEMPLATE),'approval_scope':'layout_only'},
                      'files':[{'kind':'internal','path':str(internal),'sha256':digest(internal),'preservation':internal_proof},
                               {'kind':'customs','path':str(customs),'sha256':digest(customs),'verification':customs_proof}],
                      'operator_approved':False,'formal_output':False,'R4_complete':False}
            key=semantic(contract);contract.update(result_id=key,semantic_sha256=key)
            target=root/'pair-results.json'
            if target.exists()and load_json(target)!=contract:raise MvpError('TASK_CONFLICT','已有双表契约不同，禁止覆盖')
            if not target.exists():save_json(target,contract)
            pending=root/'双表待核.csv'
            with pending.open('w',encoding='utf-8-sig',newline='')as f:
                w=csv.writer(f);w.writerow(['表','来源行','输出行','字段/列','原因'])
                for i in internal_issues:w.writerow(['内部',i['row'],i['row'],i['column'],i['code']])
                for i in upstream_issues:w.writerow(['来源-'+i['kind'],i['row'],'',i['field'],i['code']])
                for row in rows:
                    for i in row['issues']:w.writerow(['海关',row['row'],row['output_row'],i.get('column',i['field']),i['code']])
            receipt={'schema':'arrival-pair-save/1','task_id':job['task_id'],'result_id':key,'files':[{k:f[k]for k in ['kind','path','sha256']}for f in contract['files']],'committed':True,'formal_output':False}
            rf=root/'pair-save-receipt.json'
            if rf.exists()and load_json(rf)!=receipt:raise MvpError('TASK_CONFLICT','双表保存回执不同')
            if not rf.exists():save_json(rf,receipt)
            validate(job)
            count=len(internal_issues)+sum(len(r['issues'])for r in rows)+len(upstream_issues)
            job.update(step='saved',status='draft_with_gaps'if count else'draft',error=None,business_files=[str(internal),str(customs)],
                       pair_source={'path':str(target),'sha256':digest(target),'schema':SCHEMA,'result_id':key,'semantic_sha256':key},
                       artifacts=[{'path':str(x),'sha256':digest(x)}for x in [target,internal,customs,pending,rf]],
                       summary={'rows':len(rows),'pending_records':count,'upstream_pending_records':len(upstream_issues),'customs_totals':total,'internal_audit':iaudit,'pending_reason_file':str(pending),'save_receipt':str(rf),
                                'internal_preservation':internal_proof,'customs_columns':33,'internal_columns':24,'tax_values':'Only upstream reference contract retained; no template tax columns added'})
            save_json(jf,job);return current(job)
        except Exception as exc:
            code=getattr(exc,'code','RUNTIME_FAILURE');job.update(status='failed',error={'code':code,'message':str(exc),'retryable':code=='RUNTIME_FAILURE'});save_json(jf,job);raise
        finally:db.close()


def read_pair_source(ref):
    if ref.get('schema')!=SCHEMA or digest(ref['path'])!=ref['sha256']:raise MvpError('SOURCE_CHANGED','双表契约摘要不符')
    d=load_json(ref['path'])
    if d.get('schema')!=SCHEMA or d.get('policy')!=POLICY or d.get('result_id')!=ref.get('result_id')or d.get('semantic_sha256')!=ref.get('semantic_sha256')or semantic(d)!=ref['semantic_sha256']or d['result_id']!=d['semantic_sha256']:raise MvpError('SOURCE_CHANGED','双表契约语义不符')
    root=Path(ref['path']).resolve().parent;job=load_json(root/'job.json');receipt=load_json(root/'pair-save-receipt.json')
    if (job.get('mode')!='dual_projection'or job.get('step')!='saved'or job.get('pair_source')!=ref or job['code']['sha256']!=d['code_sha256']
            or receipt.get('committed')is not True or receipt.get('task_id')!=job['task_id']or receipt.get('result_id')!=d['result_id']
            or receipt.get('files')!=[{k:x[k]for k in ['kind','path','sha256']}for x in d['files']]):
        raise MvpError('SOURCE_CHANGED','双表尚无对应完整保存回执')
    _,_,_,delivery=graph(d['config'])
    if delivery!=d['delivery']:raise MvpError('SOURCE_CHANGED','双表上游保存版本变化')
    for item in d['sources']+d['files']:
        if digest(item['path'])!=item['sha256']:raise MvpError('SOURCE_CHANGED','双表来源或交付变化')
    return d
