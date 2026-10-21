"""Single WorkBuddy facade over existing B2/P1 CLI steps; stage is derived only."""
import contextlib, hashlib, io, json
from pathlib import Path
from .core import Rejected, digest, review_package, readiness
from .storage import Store, check_sources
from .workbuddy_router import route, inspect_workbooks, sync_d1, historical_references

def invoke(root,command,*arguments):
    from .cli import main
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream): code=main(['--output',str(root),command,*map(str,arguments)])
    value=json.loads(stream.getvalue())
    if code: raise Rejected(value.get('error','受控程序拒绝操作'))
    return value

def describe(root,batch_id):
    store=Store(root); batch=store.load(batch_id); check_sources(batch)
    package=review_package(batch); status=readiness(batch)
    from .excel_return import ReturnService
    receipts=batch.get('return_receipts',{}); committed={r['preview_id'] for r in receipts.values()}
    pending=[]
    for path in (store.root/'previews').glob('*.json'):
        preview=json.loads(path.read_text(encoding='utf-8'))
        if preview.get('batch_id')==batch_id and preview.get('base_hash')==digest(batch) and path.stem not in committed:
            pending.append(path.stem)
    missing=sum(bool(v) for v in status.get('rows',{}).values())
    stage='modified_pending_confirmation' if pending else 'review_complete' if batch.get('active_review_lock') else 'waiting_review'
    if not pending and receipts and missing: stage='blocked'
    return {'batch_id':batch_id,'revision':batch['revision'],'state_hash':digest(batch),'stage':stage,
            'products':len(batch['rows']),'batch_confirmable_products':len(package['ordinary_ids']),
            'individual_review_rows':len(package['individual_ids']),
            'product_confirmed':sum(bool(r['reviews']['product']) for r in batch['rows']),
            'pending_rows':missing,'pending_previews':pending,
            'checks':{'logistics':status.get('logistics',{'passed':False,'reason':'箱重资料未接齐'}),
                      'quantity':status.get('quantities',{'passed':False,'reason':'单位及数量待核验'}),
                      'amount':'保留第3步逐行权威金额；不得以合计抵消商品差异'},
            'available_files':['精简业务审核Excel','海关受控草稿','内部到货受控草稿'],
            'formal_output':False,'blockers':status,
            'next_step':'查看差异并明确确认；由可信身份提交' if pending else '处理问题页例外并按明确范围确认普通商品'}

def execute(root,request):
    allowed={'message','files','batch','currency','quantity_unit','contract','material_history','file',
             'operations','recommendations','official_materials','preview_id','confirmed_hash','confirm',
             'reference','session_token_env','library','criteria','as_of','registry','source_config','source_evidence',
             'facts','row','expected_hash','realm'}
    if not isinstance(request,dict) or set(request)-allowed: raise Rejected('请求字段未知')
    intent=route(request.get('message','')); command=intent['command']; files=request.get('files',[])
    store=Store(root); batch_id=request.get('batch'); value={}
    if command=='return-preview':
        file=request.get('file') or (files[0] if len(files)==1 else None)
        if not file: raise Rejected('请提供一份修改后的审核Excel')
        from .excel_return import ReturnService
        operations=request.get('operations')
        if isinstance(operations,str): operations=json.loads(Path(operations).read_text(encoding='utf-8-sig'))
        preview=ReturnService(root).preview(file,operations=operations)
        if batch_id and preview['batch_id']!=batch_id: raise Rejected('审核表不属于指定批次')
        batch_id=preview['batch_id']
        value={'preview_id':preview['preview_id'],'confirmation_hash':preview['confirmation_hash'],
               'changes':preview['proposals'],'operations':preview['operations'],'issue_notes':preview['issue_notes'],
               'base_is_current':preview['base_is_current'],'commit_executed':False}
    elif command=='return-commit':
        if not batch_id or request.get('confirm') is not True: raise Rejected('须明确确认已展示的差异及范围')
        arguments=['--batch',batch_id,'--confirm']
        for key,flag in (('preview_id','preview-id'),('confirmed_hash','confirmed-hash'),('reference','reference'),('session_token_env','session-token-env')):
            if not request.get(key): raise Rejected('缺少确认凭据：'+key)
            arguments+=['--'+flag,request[key]]
        if request.get('library'): arguments+=['--library',request['library']]
        value=invoke(root,'return-commit',*arguments)
    elif command=='import-stage3':
        if batch_id:
            if files:
                current=store.load(batch_id)
                known={s['sha256'] for s in current['sources']}
                if any(hashlib.sha256(Path(f).read_bytes()).hexdigest() not in known for f in files):
                    raise Rejected('附件不是该批原始来源；新文件须新建批次')
            value={'batch':batch_id,'resumed':True}
        else:
            if request.get('contract'):
                from .batchflow import import_batch
                contract=json.loads(Path(request['contract']).read_text(encoding='utf-8-sig'))
                batch=import_batch(contract)
            else:
                preflight=inspect_workbooks(files)
                if not preflight['ready']: return {'status':'needs_input','preflight':preflight,'formal_output':False}
                roles={kind:[f for f in preflight['files'] if kind in f.get('roles',[])] for kind in ('stage3_authority','invoice','weight')}
                if roles['invoice'] and roles['weight']:
                    from .contracts import create_contract
                    from .batchflow import import_batch
                    weight=roles['weight'][0]
                    if len(weight['weight_sheets'])!=1: raise Rejected('存在多个箱重工作表，须明确选择')
                    contract=create_contract(roles['invoice'][0]['path'],roles['stage3_authority'][0]['path'],weight['path'],weight['weight_sheets'][0])
                    batch=import_batch(contract)  # unsigned by design; draft only
                else:
                    from .importer import import_stage3
                    if request.get('currency')!='JPY': raise Rejected('请明确本票币种JPY；未知单位保留空值')
                    batch=import_stage3(roles['stage3_authority'][0]['path'],currency='JPY',quantity_unit=request.get('quantity_unit',''))
            batch_id=batch['id']
            if (store.folder(batch_id)/'head.json').exists():
                current=store.load(batch_id);check_sources(current);value={'batch':batch_id,'resumed':True}
            else:
                store.save(batch);value={'batch':batch_id,'resumed':False}
    else:
        if not batch_id:
            batches=[p.parent.name for p in store.root.glob('*/head.json') if len(p.parent.name)==24]
            if len(batches)!=1: raise Rejected('无法唯一恢复批次，请明确本批记录')
            batch_id=batches[0]
        if command=='status': value=describe(root,batch_id)
        elif command=='return-export':
            if not store.load(batch_id).get('input_contract'):
                raise Rejected('生成精简审核表还需要日方原表和明确箱重工作表；补齐文件后按完整来源重新建批')
            arguments=['--batch',batch_id]
            for key,flag in (('material_history','material-history'),('file','file')):
                if not request.get(key): raise Rejected('缺少审核表输入：'+key)
                arguments+=['--'+flag,request[key]]
            for key,flag in (('recommendations','recommendations'),('official_materials','official-materials')):
                if request.get(key): arguments+=['--'+flag,request[key]]
            from .storage import atomic_json
            if request.get('source_evidence'):
                if request.get('official_materials'): raise Rejected('官方参考入口重复，请使用一个明确来源清单')
                from .source_adapters import official_payload
                payload=official_payload(store.load(batch_id),[json.loads(Path(p).read_text(encoding='utf-8')) for p in request['source_evidence']])
                destination=store.folder(batch_id)/'reference_payloads';destination.mkdir(exist_ok=True)
                evidence_file=destination/(digest(payload)+'.json')
                if not evidence_file.exists():atomic_json(evidence_file,payload['official_materials'])
                arguments+=['--official-materials',str(evidence_file)]
            file=Path(request['file'])
            request_key=digest({k:v for k,v in request.items() if k!='message'})
            if file.exists():
                file_sha=hashlib.sha256(file.read_bytes()).hexdigest()
                for p in (store.root/'exports').glob('*.json'):
                    registration=json.loads(p.read_text(encoding='utf-8'))
                    if registration.get('workflow_request_hash')==request_key and registration['workbook_sha256']==file_sha and registration['base_hash']==digest(store.load(batch_id)):
                        value={'export_id':registration['export_id'],'file':str(file),'replayed':True};break
                else: raise Rejected('已有文件不是同版本已登记导出；请选择新文件位置')
            else:
                value=invoke(root,'return-export',*arguments)
                p=store.root/'exports'/(value['export_id']+'.json')
                registration=json.loads(p.read_text(encoding='utf-8'));registration['workflow_request_hash']=request_key
                atomic_json(p,registration)
        elif command=='rule-apply':
            required=('library','registry','facts','row','as_of','session_token_env','reference','expected_hash')
            if any(not request.get(k) for k in required): raise Rejected('规则应用缺少明确范围、事实版本或可信授权参数')
            from .storage import atomic_json
            destination=store.folder(batch_id)/'rule_requests';destination.mkdir(exist_ok=True)
            facts_file=destination/(digest(request['facts'])+'.json')
            if not facts_file.exists():atomic_json(facts_file,request['facts'])
            arguments=['--batch',batch_id,'--facts',str(facts_file),'--realm',request.get('realm','formal')]
            for key,flag in (('library','library'),('registry','registry'),('row','row'),('as_of','as-of'),
                             ('session_token_env','session-token-env'),('reference','reference'),('expected_hash','expected-hash')):
                arguments+=['--'+flag,request[key]]
            value=invoke(root,'rule-apply',*arguments)
            if request.get('library'):value['knowledge_sync']=sync_d1(root,request['library'],batch_id)
        elif command=='render-drafts':
            batch=store.load(batch_id);check_sources(batch)
            folder=store.folder(batch_id)/'drafts'/('r'+str(batch['revision'])+'-'+digest(batch)[:12])
            if folder.exists():
                from .drafts import draft_payload,verify_pair
                payload=draft_payload(batch);comparison=verify_pair(batch,folder,payload)
                comparison['excel_engine']='python'
                value={'directory':str(folder),'comparison':comparison,'summary':payload['summary']}
            else:value=invoke(root,'render-drafts','--batch',batch_id)
    response={'status':'ok','controlled_command':command,'result':value,'batch':describe(root,batch_id),'formal_output':False}
    if request.get('library') and request.get('criteria') and request.get('as_of'):
        response['historical_references']=historical_references(request['library'],request['criteria'],request['as_of'])
        try:
            from .d2_candidates import analyze_library
            from .decision_library import DecisionLibrary
            response['rule_candidates']=analyze_library(DecisionLibrary(request['library']),as_of=request['as_of'])['discovery']
        except (OSError,Rejected,KeyError,ValueError) as exc:
            response['rule_candidates']={'status':'unavailable','error_type':type(exc).__name__,'automatic_adoption':False}
    if request.get('registry') and request.get('library') and request.get('as_of'):
        from .rule_registry import RuleRegistry
        from .declaration_decisions import head
        from .classification_contract import contract
        registry=RuleRegistry(request['registry'],library=request['library']);matches={}
        for row in store.load(batch_id)['rows']:
            if head(row):
                try:matches[row['id']]=registry.match(contract(head(row))[0],as_of=request['as_of'])
                except Rejected:matches[row['id']]={'route':'manual_review','reasons':['incomplete_condition_contract']}
        response['released_rules']=matches
    if request.get('source_config'):
        from .source_adapters import status
        response['sources']=status(json.loads(Path(request['source_config']).read_text(encoding='utf-8-sig')))
    return response
