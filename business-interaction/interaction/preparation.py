"""Fresh-batch enrichment; existing state, calculation engines and installed skills untouched."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from collections import Counter
from decimal import Decimal,InvalidOperation
import json,re,shutil,subprocess,sqlite3
from . import load,save,digest,key,Rejected,rt,ROOT
from .preparation_sources import Index,code,snapshot,database_records,workbook_records,unique
from .preparation_rules import material,packaging
from .preparation_workbook import native_project,graft_images,update_cells,reviewed_copy

def resolve(jan,index,cards,history):
    hit=index.lookup(jan);direct=hit['records'];linked=hit['related']
    allrecords=direct+linked
    ydrecords=[r for r in allrecords if r.get('yd')]
    if ydrecords:
        priority=min(r.get('priority',100) for r in ydrecords)
        ydrecords=[r for r in ydrecords if r.get('priority',100)==priority]
    yd=unique(ydrecords,'yd')
    if not yd and any(r.get('yd') for r in allrecords):return {'jan':jan,'status':'identity_conflict','sources':allrecords,'values':{}}
    compatible=[r for r in allrecords if not r.get('yd') or r.get('yd')==yd]
    registry=[r for r in compatible if r.get('source',{}).get('kind')=='registry']
    fields={k:unique(registry,k) or unique(compatible,k) for k in ['name','spec','channel']}
    fields['yd']=yd
    # Only a source whose primary/SKU code is the arrival code can supply its price.
    prices=[r for r in direct if (not r.get('yd') or r.get('yd')==yd) and jan in {code(r.get('jan')),code(r.get('sku'))} and r.get('price_scope')!='order_total' and r.get('price') not in (None,'')]
    canonical=[r for r in prices if r.get('source',{}).get('kind')=='catalogue' and r.get('currency') in {'JPY','CNY','日元','人民币','円','RMB'}]
    # Database observations retain original precision. Keep other source quotes in evidence.
    if canonical:prices=canonical
    currency_codes={'人民币':'CNY','RMB':'CNY','日元':'JPY','円':'JPY'}
    pairs={(str(r['price']),currency_codes.get(str(r.get('currency')),str(r.get('currency')))) for r in prices};price=None
    if len(pairs)==1:
        v,currency=next(iter(pairs))
        if currency in {'CNY','人民币','RMB'}:price=v+'元'
        elif currency in {'JPY','日元','円'}:
            try:
                number=Decimal(v)
                if number.is_finite():price=number
            except InvalidOperation:pass
    fields['price']=price
    refs=cards.get(yd,[]) if str(yd or '').strip() else [];raw=unique(compatible,'material')
    if not raw:
        vals={r['material_original'] for r in refs if r.get('material_original')}
        raw=next(iter(vals)) if len(vals)==1 else '\n'.join(sorted(vals)) or None
    packs={r['accessories_original'] for r in refs if r.get('accessories_original')}
    packraw='\n'.join(sorted(packs)) or unique(compatible,'packaging') or None
    m=material(str(fields['spec'] or ''),raw,history);p=packaging(str(fields['spec'] or ''),packraw)
    images={r['image'] for r in compatible if r.get('image')}
    image=next(iter(images)) if len(images)==1 and hit['status']!='box_code_conflict' else None
    related_image=bool(image and not any(r.get('image')==image and jan in {code(r.get('jan')),code(r.get('sku'))} for r in direct))
    image_scope='box_reference' if related_image and any(code(r.get('pcs'))==jan for r in hit['links']) else 'piece_reference' if related_image else 'exact'
    if hit['status']=='box_code_conflict':
        fields={k:unique([r for r in direct if code(r.get('jan'))==jan],k) for k in ['name','spec','channel','yd']};fields['price']=None
        image=None
    return {'jan':jan,'status':hit['status'],'values':fields,'material':m,'packaging':p,'image':image,'box_image':image_scope=='box_reference','image_scope':image_scope,
            'sources':compatible,'lookup_matches':[{'source':r['source'],'query_code':jan,'fields':[f for f in ['jan','sku','pcs'] if code(r.get(f))==jan]} for r in direct],
            'excluded_yd_records':[r for r in allrecords if r not in compatible],'yd_priority_records':ydrecords,'code_links':hit['links'],'related_procurement':linked,'material_link_sources':refs,
            'purchase_observations_shared_not_allocated':True,'confirmed':False}

_legacy_resolve=resolve
def resolve(jan,index,cards,history,context=None):
    from .matching_repair import resolve_repaired
    if context is None and not any(r.get('source',{}).get('kind')=='effective_purchase_order' for r in index.lookup(jan)['records']):return _legacy_resolve(jan,index,cards,history)
    return resolve_repaired(jan,index,cards,history,_legacy_resolve,context)

def prepare(request):
    from native_copy.profiles import inspect_source
    sourcefile=Path(request['input_file']).resolve(strict=True);output=Path(request['output']).resolve();batch=request['batch_id']
    if not re.fullmatch(r'[\w.-]{1,100}',batch):raise Rejected('批次标识只能包含字母数字中文及._-')
    identity={'source':digest(sourcefile),'batch':batch}
    if (output/'session.json').exists():
        config=load(output/'session.json')
        if config.get('preparation_identity')!=identity:raise Rejected('输出目录已有不同批次或原件版本')
        if 'quantity_review' in request and (config.get('quantity_review_request_hash')!=key(request['quantity_review'])
                or config.get('quantity_review',{}).get('code_sha256')!=digest(Path(__file__).parent/'quantity_review.py')):
            # Updating read-only quantity sources must not re-register the batch
            # or recreate the workbook/human saves.
            from .quantity_review import refresh_quantity_review
            config['quantity_review']=refresh_quantity_review(config,request['quantity_review'])
            config['quantity_review_request_hash']=key(request['quantity_review'])
        if 'material_review_settings' not in config:
            settings=deepcopy(request.get('material_review',{}))
            if not isinstance(settings,dict):raise Rejected('material_review须为查询配置对象')
            captured=[]
            for filename in settings.get('evidence_manifests',[]):
                original=Path(filename).resolve(strict=True);sha=digest(original)
                target=Path(config['background'])/'fixed-inputs'/('website-'+sha[:12]+'-'+original.name)
                if target.exists() and digest(target)!=sha:raise Rejected('固定网站清单摘要变化')
                if not target.exists():shutil.copyfile(original,target)
                if digest(target)!=sha:raise Rejected('网站证据清单在捕获期间变化')
                captured.append(str(target))
            config['material_review_settings']={**settings,'evidence_manifests':captured}
        return complete_preparation(config,request.get('material_review',{}),output/'session.json')
    if output.exists():raise Rejected('准备目录已存在且未完成，保留诊断；使用新目录')
    source=inspect_source(sourcefile)
    if source['profile_id'] not in {'kmt-raw-invoice-v1','kmt-raw-invoice-v2','kmt-native-16-v1'}:raise Rejected('当前只接既有读取器已验证的日方原表布局kmt-raw-invoice-v1/v2')
    if [r['source_row'] for r in source['rows']]!=list(range(source['header_row']+1,source['header_row']+1+len(source['rows']))):raise Rejected('原表存在数据行间隙，后续原引擎行关联尚不支持；不猜映射')
    output.mkdir(parents=True);back=output/'后台';fixed=back/'fixed-inputs';fixed.mkdir(parents=True)
    raw=fixed/'original.xlsx';shutil.copyfile(sourcefile,raw)
    if digest(raw)!=identity['source']:raise Rejected('原件在捕获期间变化，保留诊断并停止准备')
    # Original bytes are retained; all reads below use that frozen attachment.
    source=inspect_source(raw);dbinfo=snapshot(request['database'],fixed/'product-library.sqlite3')
    settings=deepcopy(request.get('material_review',{}))
    if not isinstance(settings,dict):raise Rejected('material_review须为查询配置对象')
    captured_manifests=[]
    for filename in settings.get('evidence_manifests',[]):
        original=Path(filename).resolve(strict=True);sha=digest(original)
        destination=fixed/('website-'+sha[:12]+'-'+original.name)
        shutil.copyfile(original,destination)
        if digest(destination)!=sha:raise Rejected('网站证据清单在捕获期间变化')
        captured_manifests.append(str(destination))
    settings['evidence_manifests']=captured_manifests
    for field in ['access_review','stop_state_files']:
        files=settings.get(field,[]) if field=='stop_state_files' else ([settings[field]] if settings.get(field) else [])
        captured=[]
        for filename in files:
            original=Path(filename).resolve(strict=True);sha=digest(original)
            target=fixed/('website-setting-'+sha[:12]+'-'+original.name)
            shutil.copyfile(original,target)
            if digest(target)!=sha:raise Rejected('网站访问范围在捕获期间变化')
            captured.append(str(target))
        if captured:settings[field]=captured if field=='stop_state_files' else captured[0]
    records=[];assets=[]
    for config in request.get('sources',[]):
        original=Path(config['path']).resolve(strict=True);sha=digest(original);frozen=fixed/(sha[:12]+'-'+original.name)
        shutil.copyfile(original,frozen);captured={**config,'path':str(frozen),'sha256':sha}
        records+=workbook_records(captured);assets.append({**captured,'original':str(original)})
    wanted={r['code'] for r in source['rows']}
    ix=Index(records)
    for jan in list(wanted):
        h=ix.lookup(jan)
        wanted.update(code(r.get('jan')) for r in h['links'] if r.get('jan'))
    from .dg_enrichment import dg_alias
    wanted.update(alias for jan in list(wanted) if (alias:=dg_alias(jan)))
    dbrecords,cards=database_records(dbinfo['path'],wanted);records+=dbrecords;ix=Index(records)
    history=request.get('history_rules',[]);evidence={};values={};queue=[];images=[]
    caches={}
    for manifest in request.get('image_caches',[]):
        for url,item in load(manifest).items():
            if item.get('status')=='downloaded' and Path(item['file']).is_file() and digest(item['file'])==item.get('sha256'):caches[url]=item
    stopped_image_hosts={};download_attempts=0
    image_limit=request.get('image_max_downloads')
    if image_limit is not None and (type(image_limit) is not int or image_limit<0):
        raise Rejected('image_max_downloads须为非负整数，未配置时不限制下载次数')
    for n,r in enumerate(source['rows'],2):
        context={'name_ja':r['japanese_name']}
        for field in ['internal_name','specification','channel','yd','purchase_unit_price']:
            col=source.get('targets',{}).get(field)
            if col:context['source_'+field]=source['sheet'].v(r['source_row'],col)
        item=resolve(r['code'],ix,cards,history,context);item.update(row=n,row_id=r['row_id'],name_ja=r['japanese_name'],source=r['source'])
        fields=item['values'];values[n]={'F':fields.get('name'),'G':fields.get('spec'),'H':fields.get('price'),'P':fields.get('channel'),'Q':fields.get('yd'),
            'S':item.get('material',{}).get('value'),'T':item.get('packaging',{}).get('value')}
        # The existing v2 reader exposes historical working name/spec/category/
        # material slots. Preserve their nonempty contents; do not clear them or
        # treat importing the old sheet as a new business confirmation.
        for field,col in [('internal_name','F'),('specification','G'),('category','N'),('material_reference','O'),('channel','P'),('yd','Q'),('purchase_unit_price','H')]:
            original_col=source.get('targets',{}).get(field)
            original_value=source['sheet'].v(r['source_row'],original_col) if original_col else None
            if original_value not in (None,''):
                values[n][col]=original_value
                item.setdefault('preserved_source_fields',{})[field]={**r['source'],'cell':original_col+str(r['source_row'])}
        if isinstance(fields.get('price'),Decimal):fields['price']=str(fields['price'])
        item['lookup_execution']={'executed':True,'database_snapshot_sha256':dbinfo['sha256'],
                                  'source_workbooks':len(assets)}
        image=caches.get(item.get('image'))
        if image:
            item['image_execution']={'status':'cache_verified','reason':'cache_file_sha256_verified','file':image['file'],'sha256':image['sha256']}
        elif not item.get('image'):
            urls={r.get('image') for r in item.get('sources',[]) if r.get('image')}
            item['image_execution']={'status':'data_missing' if not urls else 'conflict',
                                     'reason':'no_image_source' if not urls else 'no_unique_compatible_image_source'}
        elif not request.get('download_images',True):
            item['image_execution']={'status':'not_executed','reason':'download_images_disabled'}
        elif image_limit is not None and download_attempts>=image_limit:
            item['image_execution']={'status':'not_executed','reason':'download_budget_exhausted'}
        else:
            from .preparation_images import fetch
            from urllib.parse import urlparse
            host=urlparse(item['image']).hostname;hosts=request.get('image_hosts',['img.alicdn.com'])
            if host in stopped_image_hosts:
                item['image_execution']={'status':'external_access_blocked','reason':stopped_image_hosts[host]}
            elif urlparse(item['image']).scheme!='https' or host not in hosts:
                item['image_execution']={'status':'not_executed','reason':'image_host_not_allowed'}
            else:
                download_attempts+=1;downloaded=fetch(item['image'],back/'image-cache',hosts)
                if downloaded['status']=='downloaded':image=downloaded;caches[item['image']]=downloaded
                elif any(code in downloaded.get('reason','') for code in ['403','429']):stopped_image_hosts[host]=downloaded['reason']
                item['image_download']=downloaded
                item['image_execution']={'status':'downloaded' if image else 'external_failure',
                                         'reason':'download_succeeded' if image else downloaded.get('reason') or downloaded['status'],
                                         'transport_attempted':True}
        if image:
            scale=min(220/image['width'],194/image['height']);images.append({'row':n,'file':image['file'],'width':image['width']*scale,'height':image['height']*scale})
            values[n]['E']='整盒参考图' if item['box_image'] else '单品参考图' if item.get('image_scope')=='piece_reference' else None
        item['image_status']='cached' if image else 'missing_or_uncached';evidence[str(n)]=item
        # Latest user instruction: every product is queued, regardless of local material/manual values.
        queue.append({'row':n,'jan':r['code'],'name_ja':r['japanese_name'],'spec':values[n].get('G'),'yd':fields.get('yd'),
                      'channel':fields.get('channel'),'database_hit_does_not_skip_website':True,
                      'row_id':r['row_id'],'code_links':item.get('code_links',[]),'reason':'full_product_website_review'})
    save(back/'sources.json',{'database':dbinfo,'workbooks':assets});save(back/'evidence.json',{'rows':evidence});save(back/'image-cache-index.json',caches)
    save(back/'website-queue.json',{'schema':'all-products-material-query/1','scope':'all','rows':queue,'automatic_approval':False})
    projected=fixed/'projected16.xlsx';projected.write_bytes(native_project(source,16))
    data=native_project(source,20,values)
    from native_copy.ooxml import build,verify
    if images:
        canvas=back/'images.xlsx';plan={'sheet':source['sheet'].name,'output':str(canvas),'images':images};save(back/'images-plan.json',plan)
        subprocess.run([request.get('node','node'),str(ROOT/'prepare-images.mjs'),str(back/'images-plan.json')],check=True,capture_output=True,timeout=90)
        data=graft_images(data,canvas.read_bytes(),source['sheet'].name,images)
    review_info=None
    if request.get('review_file'):
        reviewed=Path(request['review_file']).resolve(strict=True)
        data=reviewed_copy(source,reviewed,request.get('review_file_sha256'))
        frozen=fixed/'reviewed-input.xlsx';frozen.write_bytes(data)
        review_info={'path':str(frozen),'original':str(reviewed),'sha256':digest(frozen),
                     'raw_facts_verified':True,'automatic_confirmation':False}
        save(back/'reviewed-input.json',review_info)
        # The legacy query action and registration must describe the retained
        # worksheet, rather than the resolver's earlier draft values.
        from .material_review import read_rows
        _,display_rows=read_rows(frozen,source['sheet'].name)
        for row,q in zip(display_rows,queue):
            q.update({k:row[k] for k in ('jan','name_ja','spec','yd','channel')})
        save(back/'website-queue.json',{'schema':'all-products-material-query/1','scope':'all','rows':queue,'automatic_approval':False})
    public=output/'业务当前文件';public.mkdir();file=public/(batch+'_基础资料.xlsx');file.write_bytes(data)
    config={'schema':'prepared-basics-session/1','preparation_identity':identity,'batch_label':batch,'business_directory':str(public),
            'background':str(back),'prepared_file':str(file),'source':str(raw),'source_sha256':digest(raw),'database':dbinfo,
            'node':request.get('node','node'),'mode':request.get('mode','business'),'sheet':source['sheet'].name,'prepared_sha256':digest(file),
            'reviewed_input':review_info,'preparation_status':'material_review_pending','material_review_settings':settings,
            'delivery_review_required':True,'preparation_policy':{'download_images':request.get('download_images',True),
                'image_max_downloads':image_limit,'image_download_attempts':download_attempts,
                'image_hosts':request.get('image_hosts',['img.alicdn.com']),
                'sop':{'path':str(ROOT/'workbuddy/japan-arrival-customs-trial/references/business-preparation-sop.md'),
                       'sha256':digest(ROOT/'workbuddy/japan-arrival-customs-trial/references/business-preparation-sop.md')}}}
    config['attention_display']='sparse-business-v1'
    from .attention_display import apply_attention
    apply_attention(file,config)
    from .quantity_review import build_quantity_review
    config['quantity_review']=build_quantity_review(source,records,request.get('quantity_review',{}),back,batch)
    config['quantity_review_request_hash']=key(request.get('quantity_review',{}))
    from .preparation_registration import register
    config.update(register(projected,file,source,config,evidence))
    save(output/'session.json',config)
    summary={'rows':len(evidence),'fields':{k:sum(bool(v.get(k)) for v in values.values()) for k in ['F','G','H','P','Q','S','T']},
             'images':len(images),'website_queued_rows':len(queue),'material_rules':dict(Counter(x.get('material',{}).get('status','missing') for x in evidence.values())),
             'box_link_rows':sum(bool(x.get('code_links')) for x in evidence.values()),'confirmed':0,'formal_output':False,'real_human_actions':None,'time_saved_seconds':None}
    if review_info:
        from openpyxl import load_workbook
        from .photo_layout import XDR
        import xml.etree.ElementTree as ET
        workbook=load_workbook(file,read_only=True,data_only=True)
        try:
            observed=list(workbook[config['sheet']].values)[1:len(evidence)+1]
            summary['fields']={k:sum(row[ord(k)-65] not in (None,'') for row in observed) for k in ['F','G','H','N','O','P','Q','R','S','T']}
        finally:workbook.close()
        from .photo_layout import parts
        summary['images']=sum(len(ET.fromstring(v)) for k,v in parts(file.read_bytes()).items() if re.fullmatch(r'xl/drawings/drawing\d+\.xml',k))
        summary['reviewed_input']=review_info
        summary['draft_resolver_material_rules']=summary.pop('material_rules')
    save(back/'summary.json',summary)
    result=complete_preparation(config,{},output/'session.json')
    return {**result,'summary':summary}


def complete_preparation(config,settings,session_file):
    """An interrupted review is resumed before a prepared file is published."""
    from .material_review import review_materials, apply_material_reference_overlay
    if not isinstance(settings,dict):raise Rejected('material_review须为查询配置对象')
    # A replay uses the captured evidence manifests, including on retry.
    settings=config.get('material_review_settings',settings)
    if digest(config['database']['path'])!=config['database']['sha256']:
        raise Rejected('准备阶段固定资料库快照摘要变化')
    back=Path(config['background']);file=Path(config['prepared_file'])
    review_output=back/'dual-source-material-review'
    # Later human edits retain their bytes and get a separate evidence version.
    if (review_output/'run.json').exists() and load(review_output/'run.json')['identity']['source_sha256']!=digest(file):
        review_output=back/('dual-source-material-review-'+digest(file)[:16])
    config['preparation_status']='material_review_pending';save(session_file,config)
    dual=review_materials(None,{**settings,'input_file':str(file),'database':config['database']['path'],
                               'output':str(review_output)})
    save(back/'material-review-complete.json',dual)
    if config.get('schema')=='prepared-basics-session/1':
        apply_material_reference_overlay(config,dual)
        from .website_query import apply_review_overlay
        apply_review_overlay(config,dual)
    config['preparation_status']='complete';save(session_file,config)
    return {**prepared_current(config),'session':str(session_file),'material_review':dual}

def prepared_current(config):
    from .service import Service
    return Service(config).deliver()
