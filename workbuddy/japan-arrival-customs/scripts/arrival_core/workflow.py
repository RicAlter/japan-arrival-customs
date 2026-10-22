"""Single WorkBuddy facade over existing B2/P1 CLI steps; stage is derived only."""
import contextlib, hashlib, io, json
from pathlib import Path
from .core import Rejected, digest, review_package, readiness
from .storage import Store, check_sources
from .workbuddy_router import route, inspect_workbooks, sync_d1, historical_references


def _initial_raw_artifacts(root,batch_id):
    """Idempotently create the preliminary result and its registered B2 review."""
    from openpyxl import load_workbook
    from .preliminary import export_preliminary,FILENAME as PRELIMINARY_FILE
    from .compact_review import export_compact,FILENAME as REVIEW_FILE
    from .excel_return import ReturnService
    store=Store(root);batch=store.load(batch_id);key='r'+str(batch['revision'])+'-'+digest(batch)[:12]
    folder=store.folder(batch_id)/'initial'/key;folder.mkdir(parents=True,exist_ok=True)
    preliminary=folder/PRELIMINARY_FILE
    if preliminary.exists():
        preliminary_result={'file':str(preliminary),'sha256':hashlib.sha256(preliminary.read_bytes()).hexdigest(),
                            'replayed':True,'formal_output':False}
    else:preliminary_result=export_preliminary(batch,preliminary)
    review=folder/REVIEW_FILE;service=ReturnService(root)
    if review.exists():
        wb=load_workbook(review,read_only=True,data_only=False)
        try:export_id=(wb.properties.identifier or '').removeprefix('arrival-return:')
        finally:wb.close()
        registration=json.loads((store.root/'exports'/(export_id+'.json')).read_text(encoding='utf-8'))
        review_result={'export_id':export_id,'file':str(review),'workbook_sha256':registration['workbook_sha256'],
                       'base_hash':registration['base_hash'],'replayed':True,'formal_output':False}
    else:
        seed=folder/'review_seed';export_compact(batch,None,seed)
        review_result=service.register_b1(batch_id,seed,review)
    return {'preliminary':preliminary_result,'review':review_result,
            'notice':'初步整理与审核表均未形成批准；提交仍需可信合同、D08身份、差异预览和明确确认。'}

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
    row_status=status.get('rows',{})
    missing=sum(bool(v) for v in row_status.values())
    reason_counts={}
    for reasons in row_status.values():
        for reason in set(reasons):reason_counts[reason]=reason_counts.get(reason,0)+1
    quantity=status.get('quantities',{'passed':False,'pending_rows':len(batch['rows']),'automatic_coefficients_inferred':0})
    quantity_reason_counts={}
    for row in quantity.get('rows',[]):
        for reason in set(row.get('pending',[])):quantity_reason_counts[reason]=quantity_reason_counts.get(reason,0)+1
    quantity_summary={'passed':quantity.get('passed',False),'pending_rows':quantity.get('pending_rows',len(batch['rows'])),
                      'automatic_coefficients_inferred':quantity.get('automatic_coefficients_inferred',0),
                      'pending_reason_counts':quantity_reason_counts}
    contract=status.get('contract',{})
    contract_missing_counts={}
    for item in contract.get('missing',[]):
        group=item.split(':row',1)[0]+':rows' if ':row' in item else item
        contract_missing_counts[group]=contract_missing_counts.get(group,0)+1
    contract_summary={k:v for k,v in contract.items() if k!='missing'}
    contract_summary.update({'missing_count':len(contract.get('missing',[])),
                             'missing_reason_counts':contract_missing_counts})
    blocker_summary={'formal_ready':status.get('formal_ready',False),'draft_allowed':status.get('draft_allowed',True),
                     'pending_rows':missing,'pending_reason_counts':reason_counts,
                     'contract':contract_summary,'logistics':status.get('logistics',{})}
    stage='modified_pending_confirmation' if pending else 'review_complete' if batch.get('active_review_lock') else 'waiting_review'
    if not pending and receipts and missing: stage='blocked'
    raw=batch.get('input_mode')=='raw_invoice_preliminary'
    return {'batch_id':batch_id,'revision':batch['revision'],'state_hash':digest(batch),'stage':stage,
            'products':len(batch['rows']),'batch_confirmable_products':len(package['ordinary_ids']),
            'individual_review_rows':len(package['individual_ids']),
            'product_confirmed':sum(bool(r['reviews']['product']) for r in batch['rows']),
            'pending_rows':missing,'pending_previews':pending,
            'checks':{'logistics':status.get('logistics',{'passed':False,'reason':'箱重资料未接齐'}),
                      'quantity':quantity_summary,
                      'amount':('日方原表Subtotal合计仅作初步到货总价；最终申报金额待业务确定，逐行不得抵消'
                                if raw else '保留第3步逐行业务金额；不得以合计抵消商品差异')},
            'available_files':['精简业务审核Excel','海关受控草稿','内部到货受控草稿'],
            'formal_output':False,'blockers':blocker_summary,
            'next_step':'查看差异并明确确认；由可信身份提交' if pending else '处理问题页例外并按明确范围确认普通商品'}

def execute(root,request):
    allowed={'message','files','batch','currency','quantity_unit','contract','material_history','file',
             'operations','recommendations','official_materials','preview_id','confirmed_hash','confirm',
             'reference','session_token_env','library','criteria','as_of','registry','source_config','source_evidence',
             'facts','row','expected_hash','realm','settings','conversion'}
    if not isinstance(request,dict) or set(request)-allowed: raise Rejected('请求字段未知')
    intent=route(request.get('message','')); command=intent['command']; files=request.get('files',[])
    store=Store(root); batch_id=request.get('batch'); value={}
    if command in ('prepare-contract','fill-contract','sign-contract','preflight'):
        from .business_setup import save_contract,fill_contract,sign_filled_contract,preflight
        contract=json.loads(Path(request['contract']).read_text(encoding='utf-8-sig')) if request.get('contract') else None
        if command=='prepare-contract':
            from .contracts import create_contract
            inspection=inspect_workbooks(files)
            roles={k:[f for f in inspection['files'] if k in f['roles']] for k in ('raw_invoice','invoice','stage3_authority','weight')}
            required=('raw_invoice','weight') if inspection['input_mode']=='raw_invoice_preliminary' else ('invoice','stage3_authority','weight')
            missing=[k for k in required if not roles[k]]
            if missing or not inspection['ready']:
                return {'status':'needs_input','missing':missing,'preflight':inspection,'formal_output':False}
            weight=roles['weight'][0]
            if len(weight['weight_sheets'])!=1: raise Rejected('存在多个箱重页，请提供唯一明确的箱重资料')
            if inspection['input_mode']=='raw_invoice_preliminary':
                from .contracts import create_raw_contract
                value=save_contract(root,create_raw_contract(roles['raw_invoice'][0]['path'],weight['weight_sheets'][0]))
            else:value=save_contract(root,create_contract(roles['invoice'][0]['path'],roles['stage3_authority'][0]['path'],weight['path'],weight['weight_sheets'][0]))
        elif command=='fill-contract':
            if not contract: raise Rejected('先准备本批业务合同，填写操作引用程序返回的合同文件，不编辑JSON')
            value=fill_contract(root,contract,request.get('settings'))
        else:
            import os
            from .return_auth import load_session
            if command=='preflight':
                try:session=load_session(root,os.environ.get(request['session_token_env'],'')) if request.get('session_token_env') else None
                except Rejected:session=None
            else:session=load_session(root,os.environ.get(request['session_token_env'],'')) if request.get('session_token_env') else None
            if command=='sign-contract':
                if not contract: raise Rejected('先准备并填写本批合同')
                value=sign_filled_contract(root,contract,session=session,reference=request.get('reference'),confirmed_hash=request.get('confirmed_hash'),confirm=request.get('confirm'))
            else:
                batch=store.load(batch_id) if batch_id else None
                value=preflight(root,files=files,contract=contract,batch=batch,library=request.get('library'),session=session)
        return {'status':'ok','controlled_command':command,'result':value,'formal_output':False}
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
                contract=json.loads(Path(request['contract']).read_text(encoding='utf-8-sig'))
            else:
                preflight=inspect_workbooks(files)
                if not preflight['ready']: return {'status':'needs_input','preflight':preflight,'formal_output':False}
                roles={kind:[f for f in preflight['files'] if kind in f.get('roles',[])] for kind in ('raw_invoice','stage3_authority','invoice','weight')}
                if preflight['input_mode']=='raw_invoice_preliminary':
                    from .contracts import create_raw_contract
                    weight=roles['weight'][0]
                    if len(weight['weight_sheets'])!=1: raise Rejected('存在多个箱重工作表，须明确选择')
                    contract=create_raw_contract(roles['raw_invoice'][0]['path'],weight['weight_sheets'][0])
                    from .business_setup import save_contract
                    contract_file=save_contract(root,contract)['file']
                elif roles['invoice'] and roles['weight']:
                    from .contracts import create_contract
                    weight=roles['weight'][0]
                    if len(weight['weight_sheets'])!=1: raise Rejected('存在多个箱重工作表，须明确选择')
                    contract=create_contract(roles['invoice'][0]['path'],roles['stage3_authority'][0]['path'],weight['path'],weight['weight_sheets'][0])
                else:
                    return {'status':'needs_input','missing':[k for k in ('invoice','weight') if not roles[k]],
                            'notice':'真实业务主入口须完整合同。单独第3步文件仅支持CLI预导入，不可替代业务导入。','formal_output':False}
            if contract.get('input_mode')=='raw_invoice_preliminary' and not contract.get('approval'):
                from .business_setup import preliminary_import
                value=preliminary_import(root,contract);batch_id=value['batch']
                value['artifacts']=_initial_raw_artifacts(root,batch_id)
                if 'contract_file' in locals():value['contract_file']=contract_file
            else:
                from .business_setup import managed_import
                value=managed_import(root,contract);batch_id=value['batch']
    else:
        if not batch_id:
            batches=[p.parent.name for p in store.root.glob('*/head.json') if len(p.parent.name)==24]
            if len(batches)!=1: raise Rejected('无法唯一恢复批次，请明确本批记录')
            batch_id=batches[0]
        if command=='status': value=describe(root,batch_id)
        elif command in ('preview-conversion','confirm-conversion'):
            from .business_setup import conversion_preview,conversion_commit
            if command=='preview-conversion':value=conversion_preview(root,batch_id,request.get('row'),request.get('conversion'))
            else:
                import os
                from .return_auth import load_session
                session=load_session(root,os.environ.get(request.get('session_token_env',''),''))
                value=conversion_commit(root,batch_id,request.get('preview_id'),confirmed_hash=request.get('confirmed_hash'),confirm=request.get('confirm'),session=session,reference=request.get('reference'))
        elif command=='return-export':
            current=store.load(batch_id)
            if not current.get('input_contract'):
                raise Rejected('生成精简审核表还需要日方原表和明确箱重工作表；补齐文件后按完整来源重新建批')
            if current.get('input_mode')=='raw_invoice_preliminary' and not request.get('file'):
                value=_initial_raw_artifacts(root,batch_id)['review']
                response={'status':'ok','controlled_command':command,'result':value,'batch':describe(root,batch_id),'formal_output':False}
                return response
            arguments=['--batch',batch_id]
            if not request.get('file'): raise Rejected('请指定新的审核表输出位置')
            if request.get('material_history'):arguments+=['--material-history',request['material_history']]
            arguments+=['--file',request['file']]
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
