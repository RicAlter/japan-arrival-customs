"""Controlled filling of the existing contract; no second approval/state system.

security/runtime.json and its signing environment are provisioned by a trusted
administrator, never by the Skill. Upload/request writers must not control them.
"""
import copy
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

from .core import Rejected, digest, require_actor
from .contracts import ROLES, validate_contract, contract_status, sign_contract
from .storage import Store, atomic_json


def require_contract(batch):
    if not isinstance(batch.get('input_contract'), dict):
        raise Rejected('缺少批次合同/来源记录：请从日方原始工作簿重新执行“处理这批日本到货”；系统会记录原表和箱重页。提交真实审核前再通过受控单位填写及可信签核，不能编辑旧快照补签。')
    return batch['input_contract']


def runtime(root):
    try:
        config=json.loads((Path(root)/'security/runtime.json').read_text(encoding='utf-8'))
        if not isinstance(config,dict):raise ValueError()
        if config['execution_mode'] not in ('business','synthetic_technical_test'): raise ValueError()
        units=config['quantity_units']
        if not isinstance(units,list) or not units or any(not isinstance(u,str) or not u.strip() or u in ('未知','待确认','JPY','USD','CNY') for u in units): raise ValueError()
        if not isinstance(config['responsibilities'],dict) or set(config['responsibilities'])!=set(ROLES): raise ValueError()
        for people in config['responsibilities'].values():
            if people is not None and (not isinstance(people,list) or not people or any(not isinstance(p,str) or not p.strip() for p in people)): raise ValueError()
        if not isinstance(config['signing_key_env'],str) or not config['signing_key_env']: raise ValueError()
    except (OSError,KeyError,ValueError,TypeError) as exc:
        raise Rejected('宿主运行配置缺失或不完整：请可信管理员配置security/runtime.json中的执行模式、已确认单位、D08职责及签核密钥环境引用；禁止业务编辑快照。') from exc
    return config


def _key(config):
    key=os.environ.get(config['signing_key_env'],'')
    if len(key)<32: raise Rejected('宿主签核密钥环境未就绪：请管理员注入至少32字符随机密钥；不得写入附件、请求或日志。')
    return key.encode()


def _seal(contract,config):
    value=copy.deepcopy(contract);value['approval'].pop('host_seal',None)
    return hmac.new(_key(config),digest(value).encode(),hashlib.sha256).hexdigest()


def _units(contract,config):
    for unit in [contract.get('authority_quantity_unit'),contract.get('invoice_quantity_unit'),*contract.get('row_quantity_units',{}).values()]:
        if unit is not None and unit not in config['quantity_units']:
            raise Rejected('计价/采购单位不在管理员确认的本环境单位清单中；请核实原始Qty口径，不得猜测单位。')


def save_contract(root,contract):
    validate_contract(contract)
    # Apply the original source/output separation guard without a business write.
    from .batchflow import import_batch
    Store(root).guard(import_batch(contract))
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    path=root/('contract-'+digest(contract)[:24]+'.json')
    with Store(root).lock(root/'contract_writes'):
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8'))!=contract: raise Rejected('合同内容冲突')
        else: atomic_json(path,contract)
    return {'file':str(path),'contract_hash':digest(contract),'signed':contract_status(contract)['approved_for_business_review'],
            'summary':{'currency':contract['currency'],'weight_unit':contract['weight_unit'],
                       'authority_quantity_unit':contract.get('authority_quantity_unit'),
                       'invoice_quantity_unit':contract.get('invoice_quantity_unit'),
                       'row_quantity_units':contract.get('row_quantity_units',{}),
                       'responsibilities':contract['responsibilities']},'formal_output':False}


def fill_contract(root,contract,settings):
    if contract.get('approval'): raise Rejected('已签核合同不可修改；请从原始文件重新准备合同，新签核产生新批次。')
    config=runtime(root)
    if not isinstance(settings,dict) or not settings or set(settings)-{'authority_quantity_unit','arrival_quantity_unit','invoice_quantity_unit','row_quantity_units'}:
        raise Rejected('合同填写只接受原始到货/计价单位、采购单位、逐源行单位；身份、执行模式、金额及税率不能由请求声明。')
    out=copy.deepcopy(contract);settings=copy.deepcopy(settings)
    if 'arrival_quantity_unit' in settings:
        if 'authority_quantity_unit' in settings: raise Rejected('原始到货单位参数重复')
        settings['authority_quantity_unit']=settings.pop('arrival_quantity_unit')
    out.update(settings);out['responsibilities']=copy.deepcopy(config['responsibilities'])
    overrides=out.get('row_quantity_units',{})
    if not isinstance(overrides,dict): raise Rejected('逐行单位须按来源原始行号填写')
    from .batchflow import import_batch
    valid={str(r['source']['row']) for r in import_batch(contract)['rows']}
    if set(overrides)-valid: raise Rejected('逐行单位含不存在的来源原始行')
    validate_contract(out);_units(out,config)
    return save_contract(root,out)


def sign_filled_contract(root,contract,*,session,reference,confirmed_hash,confirm):
    config=runtime(root)
    if confirm is not True or confirmed_hash!=digest(contract): raise Rejected('先展示合同单位、源版本及职责，再明确确认合同哈希后签核。')
    if contract.get('approval'):
        verify_contract(root,contract)
        from .return_auth import validate_session
        validate_session(root,session,config['execution_mode'])
        require_actor(session.principal,'contract',{session.principal:list(session.roles)})
        return save_contract(root,contract)
    from .return_auth import validate_session
    validate_session(root,session,config['execution_mode'])
    if contract['responsibilities']!=config['responsibilities']: raise Rejected('D08职责配置已变化，请重新填写并预览合同。')
    _units(contract,config)
    from .batchflow import import_batch
    from .contracts import quantity_unit
    if not contract.get('invoice_quantity_unit') or any(not quantity_unit(contract,r['source']['row']) for r in import_batch(contract)['rows']):
        raise Rejected('请先通过“填写这批业务合同”明确采购与默认计价单位，再由可信合同角色签核。')
    require_actor(session.principal,'contract',{session.principal:list(session.roles)})
    if not isinstance(reference,str) or not reference.strip():raise Rejected('合同签核依据必填')
    # Retries of the same explicit signing transaction reuse its immutable proof.
    # Do not count a repeated upload as a fresh human decision.
    with Store(root).lock(Path(root)/'contract_signing'):
        for path in Path(root).glob('contract-*.json'):
            existing=json.loads(path.read_text(encoding='utf-8'));proof=existing.get('approval') or {}
            if (proof.get('payload_hash')==digest({k:v for k,v in contract.items() if k!='approval'})
                and proof.get('confirmed_by')==session.principal and proof.get('reference')==reference
                and proof.get('runtime_hash')==digest(config)):
                verify_contract(root,existing);return dict(save_contract(root,existing),replayed=True)
        signed=sign_contract(contract,actor=session.principal,evidence=reference,permissions={session.principal:list(session.roles)})
        signed['approval'].update(trusted_session=session.evidence(),execution_mode=config['execution_mode'],runtime_hash=digest(config))
        signed['approval']['host_seal']=_seal(signed,config)
        return save_contract(root,signed)


def verify_contract(root,contract):
    # The product-library hash is an import snapshot.  A later single-person
    # correction may append new candidate evidence to that external library;
    # this must not rewrite or invalidate the already-imported batch.
    config=runtime(root);validate_contract(contract,verify_product_library=False);_units(contract,config)
    proof=contract.get('approval') or {}
    if not contract_status(contract)['approved_for_business_review'] or not proof.get('host_seal'):
        raise Rejected('合同尚未通过本宿主可信签核：请填写单位并用可信合同会话签核，不能提交真实审核。')
    if proof.get('execution_mode')!=config['execution_mode'] or proof.get('runtime_hash')!=digest(config):
        raise Rejected('合同的运行环境/权限配置已变化；技术批次不能升级为真实业务，请重新准备并签核新合同。')
    if not hmac.compare_digest(proof['host_seal'],_seal(contract,config)): raise Rejected('合同可信签核校验失败；禁止手工改写批准证据。')
    return config


def managed_import(root,contract):
    from .batchflow import import_batch
    config=runtime(root);validate_contract(contract);_units(contract,config)
    if contract.get('approval'): verify_contract(root,contract)
    batch=import_batch(contract)
    batch['execution_mode']=config['execution_mode']
    batch['runtime_context']={'mode':config['execution_mode'],'policy_hash':digest(config),'contract_hash':digest(contract)}
    batch['id']=digest({'source_batch':batch['id'],'runtime_context':batch['runtime_context']})[:24]
    store=Store(root)
    if (store.folder(batch['id'])/'head.json').exists():
        from .storage import check_sources
        check_sources(store.load(batch['id']));return {'batch':batch['id'],'resumed':True}
    store.save(batch);return {'batch':batch['id'],'resumed':False}


def preliminary_import(root,contract):
    """Persist an unsigned raw-input draft; no identity or business approval is created."""
    from .batchflow import import_batch
    validate_contract(contract)
    if contract.get('input_mode')!='raw_invoice_preliminary' or contract.get('approval'):
        raise Rejected('初步导入只接受未签核的日方原表合同；已签核合同使用正式受控导入')
    batch=import_batch(contract);batch['execution_mode']='preliminary_untrusted'
    batch['runtime_context']={'mode':'preliminary_untrusted','contract_hash':digest(contract),
                              'approval':False,'review_submission_allowed':False}
    batch['id']=digest({'source_batch':batch['id'],'runtime_context':batch['runtime_context']})[:24]
    store=Store(root)
    if (store.folder(batch['id'])/'head.json').exists():
        from .storage import check_sources
        check_sources(store.load(batch['id']));return {'batch':batch['id'],'resumed':True}
    store.save(batch);return {'batch':batch['id'],'resumed':False}


def confirmed_import(root, contract):
    """Persist a supplied confirmed workbook as an untrusted, controlled-draft batch.

    The adapter records file evidence only.  It intentionally neither manufactures
    a WorkBuddy identity nor treats the workbook as a release authorization.
    """
    from .batchflow import import_batch
    validate_contract(contract)
    if contract.get('input_mode') != 'confirmed_arrival_v1' or contract.get('approval'):
        raise Rejected('已确认Excel导入只接受未签核的confirmed-arrival-v1合同')
    batch=import_batch(contract)
    batch['execution_mode']='confirmed_excel_untrusted'
    batch['runtime_context']={'mode':'confirmed_excel_untrusted','contract_hash':digest(contract),
                              'trusted_identity_verified':False,'formal_release_authorized':False}
    batch['id']=digest({'source_batch':batch['id'],'runtime_context':batch['runtime_context']})[:24]
    store=Store(root)
    if (store.folder(batch['id'])/'head.json').exists():
        from .storage import check_sources
        check_sources(store.load(batch['id']));return {'batch':batch['id'],'resumed':True}
    store.save(batch);return {'batch':batch['id'],'resumed':False}


def require_managed_review(root,batch):
    contract=require_contract(batch);config=verify_contract(root,contract)
    expected={'mode':config['execution_mode'],'policy_hash':digest(config),'contract_hash':digest(contract)}
    if batch.get('runtime_context')!=expected or batch.get('execution_mode')!=config['execution_mode']:
        raise Rejected('本批次不是当前可信业务导入版本；请用已签核合同重新导入，旧批次事实保持只读。')


def conversion_preview(root,batch_id,row_id,payload):
    from .core import _apply_domain_row, context
    batch=Store(root).load(batch_id);require_managed_review(root,batch)
    row=next((r for r in batch['rows'] if r['id']==row_id),None)
    if not row or not isinstance(payload,dict): raise Rejected('请明确本批商品行及单位换算资料')
    allowed={'source_unit','declaration_unit','internal_unit','source','declaration_factor','pieces_per_box','internal_quantity','internal_boxes'}
    if set(payload)!=allowed: raise Rejected('单位换算须包含各层单位、换算系数、内部数量/盒数及来源；不能传身份、税率或金额')
    config=runtime(root)
    if any(payload[k] not in config['quantity_units'] for k in ('source_unit','declaration_unit','internal_unit')):
        raise Rejected('换算单位不在管理员已确认清单内')
    effective=dict(payload,context=context(row))
    _apply_domain_row(copy.deepcopy(row),'packaging',effective,actor='preview_not_approval',evidence='validation_only')
    preview={'batch_id':batch_id,'base_hash':digest(batch),'row_id':row_id,'payload':effective,'domain':'packaging'}
    key=digest(preview);directory=Store(root).folder(batch_id)/'conversion_previews';directory.mkdir(exist_ok=True)
    path=directory/(key+'.json')
    if not path.exists(): atomic_json(path,preview)
    return {'preview_id':key,'confirmation_hash':key,'changes':payload,'row_id':row_id,'submitted':False}


def conversion_commit(root,batch_id,preview_id,*,confirmed_hash,confirm,session,reference):
    if not isinstance(preview_id,str) or len(preview_id)!=64 or any(c not in '0123456789abcdef' for c in preview_id): raise Rejected('无效换算预览')
    if confirm is not True or confirmed_hash!=preview_id or not isinstance(reference,str) or not reference.strip(): raise Rejected('请明确确认换算预览、哈希及依据后提交')
    store=Store(root);batch=store.load(batch_id);require_managed_review(root,batch)
    from .return_auth import authorize
    permissions=authorize(root,session,batch,'packaging')
    preview=json.loads((store.folder(batch_id)/'conversion_previews'/(preview_id+'.json')).read_text(encoding='utf-8'))
    if digest(preview)!=preview_id or preview['batch_id']!=batch_id: raise Rejected('换算预览被修改或不属于本批')
    if any(e.get('conversion_preview_id')==preview_id for e in batch['events']):return {'replayed':True,'revision':batch['revision']}
    if digest(batch)!=preview['base_hash']: raise Rejected('换算预览已过期，请重新预览')
    from .core import approve_domain
    updated=approve_domain(batch,preview['row_id'],'packaging',preview['payload'],actor=session.principal,evidence=reference,permissions=permissions)
    updated['events'][-1].update(conversion_preview_id=preview_id,trusted_session=session.evidence())
    store.save(updated,expected_hash=digest(batch))
    return {'revision':updated['revision'],'state_hash':digest(updated),'replayed':False}


def preflight(root,*,files=(),contract=None,batch=None,library=None,session=None):
    import openpyxl
    tasks=[];checks={}
    def check(name,call,action):
        try: checks[name]={'ok':True,'detail':call()}
        except (Rejected,OSError,KeyError,TypeError,ValueError) as exc:
            checks[name]={'ok':False,'reason':str(exc)};tasks.append(action+'：'+str(exc))
    checks['python']={'ok':sys.version_info>=(3,11),'version':sys.version.split()[0],'executable':sys.executable}
    checks['openpyxl']={'ok':openpyxl.__version__=='3.1.5','version':openpyxl.__version__,'expected':'3.1.5'}
    if not checks['openpyxl']['ok']:tasks.append('请管理员安装requirements.txt固定的openpyxl==3.1.5')
    if not checks['python']['ok']: tasks.append('请管理员使用Python 3.11或更新版本')
    check('runtime',lambda: {'execution_mode':runtime(root)['execution_mode']},'配置可信运行环境')
    if batch:
        contract=batch.get('input_contract')
        if not files: files=list(dict.fromkeys(s['path'] for s in batch['sources']))
    def check_files():
        from .workbuddy_router import inspect_workbooks
        result=inspect_workbooks(files)
        raw=any('raw_invoice' in f['roles'] for f in result['files'])
        required=('raw_invoice','weight') if raw else ('stage3_authority','invoice','weight')
        missing=[k for k in required if not any(k in f['roles'] for f in result['files'])]
        if missing or not result['ready']: raise Rejected('缺少或冲突的Excel资料：'+','.join(missing or result['conflicts'] or result['unknown']))
        return {'required_sources_present':True,'input_mode':'raw_invoice_preliminary' if raw else 'legacy_stage3_authority'}
    check('files',check_files,'提供包含invoice (計算)及重さとサイズ页的日方原工作簿；兼容旧流程时才需独立第3步表')
    def check_contract():
        if not contract: require_contract({})
        verify_contract(root,contract)
        if batch: require_managed_review(root,batch)
        return {'signed':True,'quantity_units_confirmed':True}
    check('contract',check_contract,'填写并可信签核本批合同')
    def check_identity():
        from .return_auth import validate_session
        config=runtime(root);validate_session(root,session,config['execution_mode'])
        if contract:
            from .contracts import effective_permissions
            roles=effective_permissions({'input_contract':contract,'rows':batch['rows'] if batch else []},{session.principal:list(session.roles)})[session.principal]
            if not roles: raise Rejected('当前会话不在本批D08审核职责范围')
        return {'mode':session.mode,'roles':roles if contract else [],'real_D08_required':config['execution_mode']=='business'}
    check('identity',check_identity,'由管理员/宿主提供相应D08审核会话，技术身份不能当真实批准')
    def check_output():
        # Probe with a unique temporary file and remove only that probe.
        import tempfile
        path=Path(root).resolve()
        if contract:
            from .batchflow import import_batch
            Store(root).guard(import_batch(contract))
        elif files:
            for f in files:
                source=Path(f).resolve()
                if source.is_relative_to(path) or path.is_relative_to(source.parent): raise Rejected('输出必须与源文件目录分离')
        path.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe: probe.write(b'probe');probe.flush()
        return {'writable':True}
    check('output',check_output,'选择独立可写输出目录')
    def check_library():
        if not library: raise Rejected('未选择外置D1库；提交后可重试同步，但不能宣称已同步')
        from .decision_library import DecisionLibrary
        lib=DecisionLibrary(library);meta=lib._metadata()
        if Path(meta['source_root']).resolve()!=Path(root).resolve(): raise Rejected('D1来源存储与当前批次不一致')
        if checks['runtime']['ok']:
            expected='synthetic' if runtime(root)['execution_mode']=='synthetic_technical_test' else 'business'
            if meta['source_kind']!=expected: raise Rejected('D1库的真实/技术来源类型不符')
        return {'available':True,'source_kind':meta['source_kind']}
    check('D1',check_library,'选择匹配本运行环境的外置D1库')
    checks['formal_output']={'ok':False,'reason':'D05正式字段白名单及逐票业务门禁未放行；正式输出保持关闭'}
    basic = bool(batch and batch.get('product_data_policy')=='single-person-v1')
    basic_ready = basic and all(checks[k]['ok'] for k in ('files','output','python','openpyxl'))
    professional_ready = all(checks[k]['ok'] for k in ('runtime','files','contract','identity','output','python','openpyxl'))
    from .host_acceptance import capabilities
    return {'checks':checks,'todos':([] if basic_ready else tasks),
            'professional_todos':tasks,'capabilities':{
                'basic_confirmation':{'available':basic_ready,'requires_D08':False},
                'professional_review':{'available':professional_ready,'requires_corresponding_roles':True},
                'formal_output':{'available':False}},'host_acceptance':capabilities(root),
            'ready_for_review_submission':professional_ready,
            'drafts_allowed':bool(contract and checks['files']['ok'] and checks['output']['ok'] and checks['openpyxl']['ok']),
            'formal_output_allowed':False,'notice':'预检不代替逐行金额、数量、箱重及分域审核；技术通过不代表真实关务批准。'}
