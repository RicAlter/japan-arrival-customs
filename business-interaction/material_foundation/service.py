"""Persistent one-code/site-at-a-time material queries, with bounded fetches."""
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import quote,urlparse
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import json,hashlib,copy,re,time
from rebuild_mvp.service import writer,save_json
from rebuild_mvp.xlsxio import iter_rows,sheet_info
from .parsing import parse,translate,objects

HERE=Path(__file__).resolve().parent
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def clock():return time.time()
def code_binding():
    files=list(HERE.glob('*.py'))+[HERE/'policy.json',HERE.parent/'run.py',HERE.parent/'rebuild_mvp/xlsxio.py',HERE.parent/'material_providers/vendor/jp_material_query/jpmaterial/translate.py']
    return hashlib.sha256(json.dumps({str(p.relative_to(HERE.parent)):sha(p) for p in sorted(files)},sort_keys=True).encode()).hexdigest()
def valid_jan(code):return bool(re.fullmatch(r'\d{10,14}',str(code)))
def checksum(code):
    if len(code) not in (12,13,14) or not code.isdigit():return None
    return (sum(int(c)*(3 if i%2==0 else 1) for i,c in enumerate(reversed(code[:-1])))+int(code[-1]))%10==0
def identify(path,sheet=None,columns=None):
    columns=columns or {};names=[s['name'] for s in sheet_info(path)]
    if sheet is None:
        if len(names)>1:raise ValueError('FIELD_MAPPING_AMBIGUOUS: 多工作表须明确sheet')
        sheet=names[0]
    header=None;mapping={}
    aliases={'code':['ProductCode(JANCode)','jan code','JAN','JAN码','商品编码','编码'],
             'material':['网站查找材质','中文材质','材质'], 'url':['材质网址','商品详情页网址','网址'], 'site':['材质站名','站点名','站名']}
    for row in iter_rows(path,sheet):
        if row['row']>40:break
        found={}
        for field,values in aliases.items():
            if field in columns:found[field]=columns[field];continue
            for label in values:
                matches=[c for c,v in row['values'].items() if re.sub(r'\s+','',str(v)).lower()==re.sub(r'\s+','',label).lower()]
                if len(matches)>1:raise ValueError('FIELD_MAPPING_AMBIGUOUS: '+field)
                if matches:found[field]=matches[0];break
        if 'code' in found and 'material' in found:header=row['row'];mapping=found;break
    if header is None:raise ValueError('FIELD_MAPPING_AMBIGUOUS: 需要编码及材质表头或列映射')
    if len(set(mapping.values()))!=len(mapping):raise ValueError('FIELD_MAPPING_AMBIGUOUS: 目标列不能重叠')
    rows=[r for r in iter_rows(path,sheet) if r['row']>header and str(r['values'].get(mapping['code'],'')).strip()]
    return sheet,mapping,rows

def prepare(req,root):
    if (root/'job.json').exists():raise ValueError('TASK_CONFLICT: 任务目录已存在，请current或resume')
    path=Path(req['input_file']).resolve(strict=True);policy=load(HERE/'policy.json')
    sheet,mapping,rows=identify(path,req.get('sheet'),req.get('columns'));jobs={};skipped=[]
    for row in rows:
        code=str(row['values'].get(mapping['code'],'')).strip()
        if not valid_jan(code):skipped.append({'row':row['row'],'code':code,'reason':'非JAN，未查询'});continue
        if row['values'].get(mapping['material']) not in ('',None):continue
        item=jobs.setdefault(code,{'jan':code,'rows':[],'site_index':0,'phase':'start','status':'queued','attempts':[],'checksum_valid':checksum(code)})
        item['rows'].append(row['row'])
    official=req.get('official_records',[])
    for record in official:
        if not record.get('source') or not record.get('original'):raise ValueError('INPUT_INVALID: 官方资料须有原文与来源')
        if record['jan'] in jobs:
            item=jobs[record['jan']];item.update(status='found',result={'site':'官方资料','url':record.get('url',''),'translation':translate(record['original']),'evidence':record['source']})
    job={'schema':'material-foundation-job/1','code_binding':code_binding(),'source':str(path),'source_sha256':sha(path),'sheet':sheet,'columns':mapping,'policy':policy,'policy_sha256':sha(HERE/'policy.json'),'codes':jobs,'skipped':skipped,'host_ready':{},'request':None,'receipts':{},'created_at':datetime.now(timezone.utc).isoformat()}
    job['nonblocking']=bool(req.get('nonblocking',False))
    job['max_site_attempts']=int(req.get('max_site_attempts',2))
    save_json(root/'job.json',job);return current(job)

def current(job):
    counts={}
    for item in job['codes'].values():counts[item['status']]=counts.get(item['status'],0)+1
    return {'status':'completed' if all(i['status'] in ('found','not_found') for i in job['codes'].values()) else 'partial','counts':counts,'unique_codes':len(job['codes']),'skipped_rows':job['skipped'],'pending':job['request'],'business_files':job.get('business_files',[]),'formal_output':False}

def build_request(item,site):
    jan=item['jan'];phase=item['phase'];selected=item.get('selected');headers={}
    if site=='anime_store':url=f'https://anime-store.jp/products/{jan}.json';phase='detail'
    elif site=='colleize':
        phase='detail' if selected else 'search';url=f'https://api.colleize.com/api/goods/{quote(str(selected))}' if selected else f'https://api.colleize.com/api/goods?name={jan}&sortType=RECOMMEND'
    elif site=='amiami':
        phase='detail' if selected else 'search';url=f'https://api.amiami.com/api/v1.0/item?gcode={quote(str(selected))}' if selected else f'https://api.amiami.com/api/v1.0/items?s_keywords={jan}&pagecnt=1&pagemax=20&lang=ja';headers={'X-User-Key':'amiami_dev','User-Agent':'python-amiami_dev'}
    elif site=='jumpcs':url=f'https://jumpcs.shueisha.co.jp/shop/g/g{jan}/';phase='detail'
    elif site=='hobbysearch':url=selected or f'https://www.1999.co.jp/search/?q={jan}';phase='detail' if selected else 'search'
    else:url=selected or f'https://www.suruga-ya.jp/search?category=&search_word={jan}';phase='detail' if selected else 'search'
    rid=hashlib.sha256(json.dumps([jan,site,phase,url,len(item['attempts'])],ensure_ascii=False).encode()).hexdigest()[:24]
    return {'id':rid,'jan':jan,'site':site,'phase':phase,'url':url,'headers':headers,'transport':'external_fetch' if site in ('hobbysearch','surugaya') else 'http','selected':selected}

def next_request(job):
    if job.get('nonblocking'):return next_nonblocking(job)
    if job['request']:return {'status':'request_ready','request':job['request']}
    for item in job['codes'].values():
        if item['status'] in ('found','not_found'):continue
        while item['site_index']<len(job['policy']['sites']):
            site=job['policy']['sites'][item['site_index']]
            if site=='jumpcs' and not item['jan'].startswith(job['policy']['jumpcs_prefix']):
                item['attempts'].append({'site':site,'status':'not_applicable'});item['site_index']+=1;continue
            ready=job['host_ready'].get(site,0)
            if clock()<ready:return {'status':'waiting','retry_after_seconds':round(ready-clock()+0.01,2),'jan':item['jan'],'site':site}
            request=build_request(item,site);job['request']=request;item['status']='pending';return {'status':'request_ready','request':request}
        item['status']='not_found'
    return current(job)

def next_nonblocking(job):
    """Advance other sites/rows while a host cools; errors never mean absent."""
    if job['request']:return {'status':'request_ready','request':job['request']}
    waiting=[];sites=job['policy']['sites']
    for item in job['codes'].values():
        if item['status'] in ('found','not_found','deferred'):continue
        deferred=item.setdefault('deferred_sites',[])
        while True:
            if item['site_index']>=len(sites):
                ready=[i for i in deferred if job['host_ready'].get(sites[i],0)<=clock()]
                if ready:
                    item['site_index']=ready[0];deferred.remove(ready[0]);item.pop('selected',None)
                else:
                    if deferred:
                        waiting.extend(job['host_ready'].get(sites[i],clock()) for i in deferred)
                    else:item['status']='deferred' if item.get('unavailable_sites') else 'not_found'
                    break
            index=item['site_index'];site=sites[index]
            if site in item.get('finished_sites',[]):
                if index in deferred:deferred.remove(index)
                item['site_index']+=1;continue
            if site=='jumpcs' and not item['jan'].startswith(job['policy']['jumpcs_prefix']):
                item['site_index']+=1;continue
            errors=sum(a.get('status')=='error' and a.get('request',{}).get('site')==site for a in item['attempts'])
            if errors>=job['max_site_attempts']:
                if site not in item.setdefault('unavailable_sites',[]):item['unavailable_sites'].append(site)
                if index in deferred:deferred.remove(index)
                advance(item);continue
            if clock()<job['host_ready'].get(site,0):
                if index not in deferred:deferred.append(index)
                advance(item);continue
            if index in deferred:deferred.remove(index)
            request=build_request(item,site);job['request']=request;item['status']='pending'
            return {'status':'request_ready','request':request}
    if waiting:return {'status':'waiting','retry_after_seconds':max(0,round(min(waiting)-clock()+0.01,2))}
    return current(job)

def advance(item):
    if item.get('other_ids'):
        item['selected']=item['other_ids'].pop(0);item['phase']='detail'
    else:
        item['site_index']+=1;item.pop('selected',None);item['phase']='start'
    item['status']='queued'

def submit(job,root,req):
    rid=req['request_id'];payload=json.dumps({k:req.get(k) for k in ('http_status','body','final_url','transport_error')},ensure_ascii=False,sort_keys=True);digest=hashlib.sha256(payload.encode()).hexdigest()
    if rid in job['receipts']:
        if job['receipts'][rid]!=digest:raise ValueError('TASK_CONFLICT: 同一请求回传内容变化')
        return current(job)
    request=job['request']
    if not request or request['id']!=rid:raise ValueError('TASK_CONFLICT: 请求不匹配')
    body=str(req.get('body',''));status=int(req.get('http_status',0));site=request['site'];item=job['codes'][request['jan']]
    if len(body.encode('utf-8'))>job['policy']['max_response_bytes']:raise ValueError('INPUT_INVALID: 响应超过8MB，请按单商品回传')
    final=req.get('final_url') or request['url']
    allowed={urlparse(request['url']).hostname}
    if site=='surugaya':allowed|={'suruga-ya.jp','www.suruga-ya.jp'}
    if site=='hobbysearch':allowed|={'1999.co.jp','www.1999.co.jp'}
    if urlparse(final).hostname not in allowed:raise ValueError('INPUT_INVALID: 返回网址超出站点')
    evidence=root/'evidence';evidence.mkdir(exist_ok=True);snapshot=evidence/(rid+'.txt');snapshot.write_text(body,encoding='utf-8')
    attempt={'request':request,'http_status':status,'snapshot':str(snapshot),'sha256':sha(snapshot),'final_url':final,'transport_error':req.get('transport_error'),'queried_at':datetime.now(timezone.utc).isoformat()}
    if req.get('transport_error') or status in (0,403,429) or status>=500 or not body.strip() and status==200:
        attempt['status']='error';item['status']='retry';job['host_ready'][site]=clock()+job['policy']['retry_seconds'];item['attempts'].append(attempt);job['request']=None;job['receipts'][rid]=digest;return {'status':'retry','error':{'code':'ACCESS_BLOCKED' if status in (403,429) else 'NETWORK_ERROR','retryable':True},'retry_after_seconds':job['policy']['retry_seconds'],'jan':item['jan'],'site':site}
    job['host_ready'][site]=clock()+job['policy']['interval_seconds'][site]
    if status==404:result={'status':'error','error_code':'HTTP_404_UNVERIFIED','reason':'地址或访问结果待核实，404不作为商品不存在依据'}
    elif status!=200:result={'status':'error'}
    elif site in ('hobbysearch','surugaya') and request['phase']=='search':
        result=parse(site,item['jan'],'detail',body,final)
        if result['status']=='identity_mismatch':
            pattern=r'(?:https://(?:www\.)?1999\.co\.jp)?/\d{6,}' if site=='hobbysearch' else r'(?:https://www\.suruga-ya\.jp)?/product/detail/[A-Za-z0-9]+'
            links=list(dict.fromkeys(re.findall(pattern,body)))
            base='https://www.1999.co.jp' if site=='hobbysearch' else 'https://www.suruga-ya.jp'
            result={'status':'detail','ids':[x if x.startswith('https://') else base+x for x in links[:20]]} if links else {'status':'not_found'}
    else:result=parse(site,item['jan'],request['phase'],body,final,item.get('selected'))
    attempt.update(result);item['attempts'].append(attempt);job['request']=None;job['receipts'][rid]=digest
    if result['status']=='detail':item['selected']=result['ids'][0];item['other_ids']=result['ids'][1:];item['phase']='detail';item['status']='queued'
    elif result['status']=='found':
        translated=translate(result['original']);item.update(status='found',result={'site':site,'url':final if site not in ('colleize','anime_store','amiami') else (f'https://colleize.com/lineup/{next((o.get("artist",{}).get("id","") for o in objects(json.loads(body)) if o.get("material")),"")}/{item.get("selected","")}' if site=='colleize' else f'https://anime-store.jp/products/{item["jan"]}' if site=='anime_store' else f'https://www.amiami.jp/top/detail/detail?gcode={item.get("selected","")}'),'translation':translated,'evidence':attempt})
    elif result['status']=='error':item['status']='retry';job['host_ready'][site]=clock()+65
    else:
        old_index=item['site_index'];advance(item)
        if job.get('nonblocking') and item['site_index']!=old_index:
            item.setdefault('finished_sites',[]).append(site)
    return current(job)

def handle(req):
    root=Path(req.get('task_root') or req.get('output','')).resolve()
    try:
        if not req.get('task_root') and not req.get('output'):raise ValueError('INPUT_INVALID: task_root/output必填')
        root.mkdir(parents=True,exist_ok=True)
        with writer(root):
            action=req['action']
            if action=='prepare':return {'schema':'material-foundation/1',**prepare(req,root)}
            job=load(root/'job.json')
            if job['policy_sha256']!=sha(HERE/'policy.json'):raise ValueError('SOURCE_CHANGED: 规则变化，请另建任务')
            if job.get('code_binding')!=code_binding():raise ValueError('SOURCE_CHANGED: 查询程序版本变化，请用原冻结副本继续')
            if action in ('current','resume'):return {'schema':'material-foundation/1',**current(job)}
            if action=='next':result=next_request(job)
            elif action=='submit':result=submit(job,root,req)
            elif action=='fetch':
                result=next_request(job)
                if result['status']=='request_ready':
                    request=result['request']
                    if request['transport']=='external_fetch':result={'status':'needs_external_fetch','request':request}
                    elif not req.get('allow_online'):result={'status':'needs_online_permission','request':request}
                    else:
                        # Persist request before network so interruption can retry the same code/site.
                        save_json(root/'job.json',job)
                        response={'request_id':request['id']}
                        try:
                            with urlopen(Request(request['url'],headers={'User-Agent':'JapanArrivalMaterial/1',**request['headers']}),timeout=25) as r:
                                data=r.read(job['policy']['max_response_bytes']+1)
                                if len(data)>job['policy']['max_response_bytes']:raise ValueError('RESPONSE_TOO_LARGE')
                                response.update(http_status=r.status,body=data.decode('utf-8',errors='replace'),final_url=r.geturl())
                        except HTTPError as exc:response.update(http_status=exc.code,body=exc.read(100000).decode('utf-8',errors='replace'))
                        except Exception as exc:response.update(http_status=0,body='',transport_error=str(exc))
                        result=submit(job,root,response)
            elif action=='writeback':
                from .writeback import apply
                result=apply(job,root,req);job['business_files']=result['business_files']
            else:raise ValueError('INPUT_INVALID: 未知action')
            save_json(root/'job.json',job);return {'schema':'material-foundation/1',**result}
    except Exception as exc:
        code=str(exc).split(':',1)[0]
        if code not in {'SOURCE_CHANGED','INPUT_INVALID','FIELD_MAPPING_AMBIGUOUS','TASK_CONFLICT'}:code='RUNTIME_FAILURE'
        return {'schema':'material-foundation/1','status':'failed','error':{'code':code,'message':str(exc),'retryable':code=='RUNTIME_FAILURE'},'business_files':[]}
