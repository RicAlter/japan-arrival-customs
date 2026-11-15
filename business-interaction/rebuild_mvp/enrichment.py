"""Versioned prepare/current/resume for material and procurement-photo overlays."""
import csv, hashlib, json, re
from pathlib import Path
from .service import writer, save_json, digest, code_version
from .xlsxio import read_book
from .purchase_images import image_rows, observations, match, download
from .enrichment_export import export

HERE=Path(__file__).resolve().parent
ERRORS={'INPUT_INVALID','CONFIG_INVALID','SOURCE_CHANGED','SOURCE_FORBIDDEN','TASK_CONFLICT','FIELD_MAPPING_AMBIGUOUS'}

def binding():
    from material_foundation.service import code_binding
    return {'program':code_version()['sha256'],'material':code_binding(),'policy':digest(HERE/'enrichment_policy.json')}

def material_values(job, material):
    result={};evidence={}
    for code,item in (material or {}).get('codes',{}).items():
        if item['status']!='found':continue
        value=item['result'];zh=value['translation']['zh']
        for n in item['rows']:result[str(n)]=zh;evidence[str(n)]={'code':code,**value}
    return result,evidence

def report(job,root):
    files=job.get('business_files',[])
    return {'schema':'arrival-enrichment/1','task_id':job['task_id'],'batch_id':job['config']['batch_id'],
            'status':job['status'],'step':job['step'],'versions':job['binding'],'business_files':files,
            'summary':job.get('summary',{}),'issues':job.get('issue_sample',[]),'error':None,
            'requests':job.get('external_requests',[]),'retry_after_seconds':job.get('retry_after_seconds',0),
            'next_action':'provide_web_response_or_resume' if job.get('external_requests') else 'resume' if job.get('pending') else 'review_results',
            'semantic_sha256':job.get('semantic_sha256'),'evidence':str(root/'field-evidence.json'),'formal_output':False}

def validate(job):
    if job['binding']!=binding():raise ValueError('SOURCE_CHANGED: 程序或规则改变，请用冻结版本恢复')
    for p,sha in job['input_versions'].items():
        if not Path(p).is_file() or digest(p)!=sha:raise ValueError('SOURCE_CHANGED: 输入或采购来源改变')
    if job.get('business_files'):
        p=job['business_files'][0]
        if not Path(p).is_file() or digest(p)!=job['output_sha256']:raise ValueError('SOURCE_CHANGED: 已生成确认表被修改，请保留并另建任务')

def prepare(req,root):
    keys={'batch_id','input_file','sources','sheet','materials','pictures','allow_online','max_operations'}
    config={k:req[k] for k in keys if k in req}
    if not config.get('batch_id') or not config.get('input_file'):raise ValueError('INPUT_INVALID: batch_id/input_file必填')
    config.setdefault('sources',[]);config.setdefault('materials',True);config.setdefault('pictures',True);config.setdefault('allow_online',False)
    config.setdefault('max_operations',50)
    if any(not isinstance(config[k],bool) for k in ('materials','pictures','allow_online')):raise ValueError('CONFIG_INVALID: 开关必须为JSON布尔值')
    if not isinstance(config['max_operations'],int) or not 1<=config['max_operations']<=100:raise ValueError('CONFIG_INVALID: max_operations为1至100')
    if not config['materials'] and not config['pictures']:raise ValueError('CONFIG_INVALID: 至少选择材质或图片')
    path=Path(config['input_file']).resolve(strict=True);config['input_file']=str(path)
    if path.with_name('~$'+path.name).exists():raise ValueError('TASK_CONFLICT: 输入表正在编辑')
    book=read_book(path);sheet=config.get('sheet','invoice (計算)');data=next((s for s in book['sheets'] if s['name']==sheet),None)
    if data is None:raise ValueError('FIELD_MAPPING_AMBIGUOUS: 未识别业务工作表')
    config['sheet']=sheet
    header=next((r for r in data['rows'] if r['values'].get('E')=='商品图片' and r['values'].get('R')=='网站查找材质'),None)
    if not header:raise ValueError('FIELD_MAPPING_AMBIGUOUS: 本模式要求认可的24列确认表')
    rows=[r for r in data['rows'] if r['row']>header['row'] and r['values'].get('C')]
    occupied=image_rows(path,sheet);policy=json.loads((HERE/'enrichment_policy.json').read_text(encoding='utf8'))
    records,audit=observations(config['sources'],{str(r['values']['C']) for r in rows}) if config['pictures'] else ([],[])
    versions={str(path):book['sha256']}
    for s in config['sources']:versions[str(Path(s['path']).resolve())]=digest(s['path'])
    job={'schema':'arrival-enrichment-job/1','mode':'enrich_review','config':config,'input_versions':versions,'binding':binding(),
         'task_id':hashlib.sha256(json.dumps([config,versions,binding()],ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24],
         'rows':rows,'occupied_picture_rows':sorted(occupied),'pictures':match(rows,records,occupied) if config['pictures'] else {},
         'source_audit':audit,'policy':policy,'status':'running','step':'prepared','business_files':[],'revision':0}
    save_json(root/'job.json',job)
    if config['materials']:
        from material_foundation.service import handle
        value=handle({'action':'prepare','input_file':str(path),'output':str(root/'materials'),'sheet':sheet,
                      'columns':{'code':'C','material':'R'},'nonblocking':True,'max_site_attempts':policy['max_site_attempts']})
        if value['status']=='failed':raise ValueError(value['error']['code']+': '+value['error']['message'])
    save_json(root/'job.json',job);return job

def resume(job,root,req):
    from material_foundation.service import handle as material_handle
    config=job['config'];online=config['allow_online'];budget=config['max_operations'];job['external_requests']=[];job['retry_after_seconds']=0
    # Downloads and material queries receive independent bounded budgets, so a
    # slow/blocked website cannot starve procurement pictures.
    count=0;cache={}
    for n,pic in sorted(job['pictures'].items(),key=lambda x:int(x[0])):
        if pic['status'] not in ('queued','retry') or count>=budget:continue
        if not online:continue
        if pic.get('attempts',0)>=2:pic.update(status='unresolved',reason='采购图片链接访问失败');continue
        count+=1;pic['attempts']=pic.get('attempts',0)+1
        try:
            if pic['url'] not in cache:cache[pic['url']]=download(pic['url'],root,job['policy'])
            pic.update(status='found',download=cache[pic['url']],reason='')
        except Exception as exc:
            pic.update(status='retry' if pic['attempts']<2 else 'unresolved',reason='采购图片链接访问失败',error={'code':str(exc).split(':')[0] if ':' in str(exc) else 'IMAGE_DOWNLOAD_FAILED','message':str(exc)[:250]})
        save_json(root/'job.json',job)
    material=None
    if config['materials']:
        mr=root/'materials';base={'task_root':str(mr)}
        if not (mr/'job.json').exists():
            value=material_handle({'action':'prepare','input_file':config['input_file'],'output':str(mr),'sheet':config['sheet'],
                                  'columns':{'code':'C','material':'R'},'nonblocking':True,'max_site_attempts':job['policy']['max_site_attempts']})
            if value['status']=='failed':raise ValueError(value['error']['code']+': '+value['error']['message'])
        for response in req.get('responses',[]):
            if not isinstance(response,dict) or set(response)-{'request_id','http_status','body','final_url','transport_error'}:raise ValueError('INPUT_INVALID: 外部回传只允许请求ID、状态、网址和原文')
            value=material_handle({**base,**response,'action':'submit'})
            if value['status']=='failed':raise ValueError(value['error']['code']+': '+value['error']['message'])
        for _ in range(budget):
            value=material_handle({**base,'action':'fetch','allow_online':online})
            if value['status']=='failed':raise ValueError(value['error']['code']+': '+value['error']['message'])
            if value['status']=='needs_external_fetch':job['external_requests']=[value['request']];break
            if value['status']=='waiting':job['retry_after_seconds']=value['retry_after_seconds'];break
            if value['status'] in ('completed','needs_online_permission'):break
            # No more eligible work (all records found/absent/deferred).
            child=json.loads((mr/'job.json').read_text(encoding='utf8'))
            if not child.get('request') and all(x['status'] in ('found','not_found','deferred') for x in child['codes'].values()):break
        material=json.loads((mr/'job.json').read_text(encoding='utf8'))
    values,evidence=material_values(job,material);pics={n:x['download'] for n,x in job['pictures'].items() if x['status']=='found'}
    issues=[];pending=any(p['status'] in ('queued','retry') for p in job['pictures'].values());bycode=(material or {}).get('codes',{})
    reason_rows=[];blank_material=0;blank_images=0
    for row in job['rows']:
        n=row['row'];v=row['values'];code=str(v['C']);m='';p=''
        if not v.get('R') and str(n) not in values:
            blank_material+=1;item=bycode.get(code)
            if not config['materials']:m='本任务未查询材质'
            elif not item:m='编码格式或商品身份需核对'
            elif item['status']=='not_found':m='已查站点未找到明确材质'
            elif item['status']=='deferred':m='网站访问受限或失败，未完成核实'
            else:m='待续查';pending=True
        if n not in job['occupied_picture_rows'] and str(n) not in pics:
            blank_images+=1;p=job['pictures'].get(str(n),{}).get('reason') or ('待下载' if config['pictures'] else '本任务未补图片')
        if m or p:reason_rows.append([n,code,v.get('F',''),v.get('J',''),m,p])
    key=hashlib.sha256(json.dumps({'materials':values,'pictures':{n:v['sha256'] for n,v in pics.items()},'reasons':reason_rows},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    validate(job)
    if key!=job.get('semantic_sha256'):
        revision=job['revision']+1;outfile=root/f'运营核对表_{revision:03d}.xlsx'
        result=export(config['input_file'],outfile,config['sheet'],values,pics,job['policy'])
        job.update(revision=revision,business_files=[result['path']],output_sha256=result['sha256'],export=result,semantic_sha256=key)
        save_json(root/'job.json',job)
    csvfile=root/f'待补原因_{job["revision"]:03d}.csv'
    with csvfile.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['表格行号','商品编码','商品名称','日文名','未补材质原因','未补图片原因']);w.writerows(reason_rows)
    save_json(root/'field-evidence.json',{'materials':evidence,'pictures':job['pictures'],'sources':job['input_versions'],'source_audit':job['source_audit'],'semantic_sha256':key})
    job.update(pending=pending,status='partial' if pending else 'completed_with_gaps' if reason_rows else 'completed',step='exported',
               summary={'product_rows':len(job['rows']),'materials_added':len(values),'purchase_picture_rows_added':len(pics),
                        'picture_rows':len(job['occupied_picture_rows'])+len(pics),'blank_website_material_rows':blank_material,'blank_picture_rows':blank_images,
                        'source_sheets_with_issues':len(job['source_audit']),'pending_reason_file':str(csvfile)},issue_sample=reason_rows[:8])
    save_json(root/'job.json',job);return report(job,root)

def handle(req):
    try:
        action=req.get('action')
        if action not in ('prepare','current','resume'):raise ValueError('INPUT_INVALID: 只支持prepare/current/resume')
        raw=req.get('output') if action=='prepare' else req.get('task_root')
        if not raw:raise ValueError('INPUT_INVALID: 缺少output/task_root')
        root=Path(raw).resolve()
        if action=='current':
            job=json.loads((root/'job.json').read_text(encoding='utf8'));validate(job);return report(job,root)
        root.mkdir(parents=True,exist_ok=True)
        with writer(root):
            if (root/'job.json').exists():
                job=json.loads((root/'job.json').read_text(encoding='utf8'))
                if job.get('mode')!='enrich_review':raise ValueError('TASK_CONFLICT: 目录绑定其他任务')
                if action=='prepare':
                    for k,v in job['config'].items():
                        if k in req and req[k]!=v:raise ValueError('TASK_CONFLICT: 输入配置不一致')
                validate(job)
            else:
                if action!='prepare' or any(p.name!='.writer.lock' for p in root.iterdir()):raise ValueError('TASK_CONFLICT: 目录非空或任务未建立')
                job=prepare(req,root)
            return resume(job,root,req)
    except Exception as exc:
        code=getattr(exc,'code',str(exc).split(':',1)[0])
        if code not in ERRORS:code='RUNTIME_FAILURE'
        return {'schema':'arrival-enrichment/1','status':'failed','business_files':[],'error':{'code':code,'message':str(exc),'retryable':code=='RUNTIME_FAILURE'},'next_action':'resume' if code=='RUNTIME_FAILURE' else 'check_input_and_versions'}
