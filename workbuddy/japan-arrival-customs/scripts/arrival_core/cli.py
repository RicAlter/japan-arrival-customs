import argparse
import json
from pathlib import Path

from .core import (Rejected, approve_domain, box_tax, confirm_products, customs_preview,
                   digest, exact_price, readiness, reconcile_amounts, review_package, supplement, supplement_many)
from .importer import attach_p0_findings, import_stage3
from .storage import Store, atomic_json, check_sources


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="日本到货统一明细与审核；仅受控测试草稿，无正式外发")
    parser.add_argument("--output", required=True, help="独立输出目录")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ('knowledge-init','knowledge-import','knowledge-stats','knowledge-search','knowledge-check',
                 'knowledge-rebuild','knowledge-backup','knowledge-restore','knowledge-upgrade','knowledge-history'):
        cmd=sub.add_parser(name);cmd.add_argument('--library',required=True)
        if name=='knowledge-init':
            cmd.add_argument('--source-kind',required=True,choices=['business','synthetic','authorized_test_fixture'])
        if name=='knowledge-import':cmd.add_argument('--batch',required=True)
        if name=='knowledge-history':
            cmd.add_argument('--batch',required=True);cmd.add_argument('--decision',required=True)
        if name in ('knowledge-stats','knowledge-search'):cmd.add_argument('--as-of',required=True)
        if name=='knowledge-search':
            cmd.add_argument('--criteria',required=True,help='商品类型/用途/组成/构造条件JSON；仅检索')
            cmd.add_argument('--realm',choices=['formal','test','quarantine'],default='formal')
        if name in ('knowledge-backup','knowledge-restore'):cmd.add_argument('--backup',required=True)
    for name in ('product-library-stats','product-library-lookup'):
        cmd=sub.add_parser(name,help='只读查询共享商品资料库；维护写入由独立商品维护Skill执行')
        cmd.add_argument('--library',required=True)
        if name=='product-library-lookup':
            cmd.add_argument('--code',required=True);cmd.add_argument('--japanese-name',default='');cmd.add_argument('--version',default='')
    d2=sub.add_parser('d2-report',help='只读发现候选/冲突；不发布规则')
    d2.add_argument('--library',required=True);d2.add_argument('--as-of',required=True)
    d2r=sub.add_parser('d2-replay',help='按事件时间输出回放可用性；不使用未来知识')
    d2r.add_argument('--library',required=True);d2r.add_argument('--as-of',required=True)
    for cmd in (d2,d2r): cmd.add_argument('--realm',choices=['formal','test'],default='formal')
    for name in ('rule-draft','rule-publish','rule-transition','rule-match','rule-apply','rule-impact'):
        cmd=sub.add_parser(name);cmd.add_argument('--registry',required=True);cmd.add_argument('--library',required=True)
        cmd.add_argument('--as-of',required=True);cmd.add_argument('--realm',choices=['formal','test'],default='formal')
        cmd.add_argument('--batch');cmd.add_argument('--session-token-env')
        if name=='rule-draft':
            cmd.add_argument('--candidate-id',required=True)
        elif name in ('rule-publish','rule-transition'):
            cmd.add_argument('--rule-id',required=True);cmd.add_argument('--reference',required=True);cmd.add_argument('--expected-version',required=True,type=int)
            if name=='rule-transition':cmd.add_argument('--status',required=True,choices=['suspended','revoked'])
        elif name in ('rule-match','rule-apply'):
            cmd.add_argument('--facts',required=True);cmd.add_argument('--allow-automatic',action='store_true')
            if name=='rule-apply':
                cmd.add_argument('--row',required=True);cmd.add_argument('--reference',required=True);cmd.add_argument('--expected-hash',required=True)
    sources=sub.add_parser('source-status',help='来源状态；未配置来源不视为已接通')
    sources.add_argument('--config')
    source_read=sub.add_parser('source-read',help='有权限及真实字段映射后只读采集来源证据')
    source_read.add_argument('--config',required=True);source_read.add_argument('--kind',required=True,choices=['feishu_product','feishu_purchase','official_web'])
    source_read.add_argument('--url');source_read.add_argument('--identity-evidence')
    flow=sub.add_parser('workbuddy',help='单一业务入口，复用已有受控命令和B2审核')
    flow.add_argument('--request',required=True)
    intent=sub.add_parser('workbuddy-route',help='自然语言只映射到既有受控步骤')
    intent.add_argument('--message',required=True);intent.add_argument('--files',nargs='*')
    brief=sub.add_parser('batch-brief',help='业务化批次状态摘要');brief.add_argument('--batch',required=True)
    sync=sub.add_parser('d1-sync',help='审核已保存后可重试的D1索引同步');sync.add_argument('--batch',required=True);sync.add_argument('--library',required=True)
    reference=sub.add_parser('historical-references',help='只读展示D1正式案例候选；不是自动归类')
    reference.add_argument('--library',required=True);reference.add_argument('--criteria',required=True);reference.add_argument('--as-of',required=True)
    imp = sub.add_parser("import-stage3")
    imp.add_argument("--source", required=True)
    imp.add_argument("--currency", required=True)
    imp.add_argument("--quantity-unit", required=True, help="未确认时传空字符串，价格审核保持待定")
    imp.add_argument("--p0-evidence", help="可选：本项目冻结的reports/p0目录")
    contract = sub.add_parser("init-contract")
    for name in ("invoice", "authority", "weights", "weight-sheet"):
        contract.add_argument("--"+name, required=True)
    contract.add_argument("--customs-reference")
    contract.add_argument("--internal-reference")
    sign = sub.add_parser("sign-contract")
    for name in ("contract", "evidence", "session-token-env", "confirmed-hash"):
        sign.add_argument("--"+name, required=True)
    sign.add_argument('--confirm',action='store_true')
    fill=sub.add_parser('fill-contract',help='受控填写单位；不直接编辑合同或快照')
    fill.add_argument('--contract',required=True);fill.add_argument('--authority-unit',required=True);fill.add_argument('--invoice-unit',required=True)
    pre=sub.add_parser('preflight',help='真实业务启动检查；不批准审核')
    pre.add_argument('--batch');pre.add_argument('--contract');pre.add_argument('--files',nargs='*',default=[])
    pre.add_argument('--library');pre.add_argument('--session-token-env')
    incoming = sub.add_parser("import-batch"); incoming.add_argument("--contract", required=True)
    for name in ("review-package", "status", "apply", "customs-preview", "calculation-preview", "check-amounts",
                 "professional-queue", "group-review-package", "identity-checklist", "export-intermediate", "export-compact", "reconcile-logistics", "reconcile-quantities", "render-drafts", "formal-export",
                 "return-export", "return-preview", "return-commit", "return-status", "return-events", "return-lock"):
        cmd = sub.add_parser(name); cmd.add_argument("--batch", required=True)
        if name == "apply":
            cmd.add_argument("--request", required=True)
            cmd.add_argument('--session-token-env',required=True,help='只引用宿主会话环境变量；不能用actor/permissions自报身份')
        if name == "check-amounts":
            cmd.add_argument("--proposed", required=True, help="完整的技术行ID到待核对金额的JSON映射")
        if name == "render-drafts":
            cmd.add_argument("--runtime", help="可选：显式选择旧Node引擎；默认Python/openpyxl")
            cmd.add_argument("--previews", action="store_true")
            cmd.add_argument('--preview-id', help='可选：当前已登记B2预览，仅展示候选，绝不提交')
        if name == 'group-review-package':
            cmd.add_argument('--domain',required=True,choices=['identity','material','packaging','tax'])
        if name == 'export-compact':
            cmd.add_argument('--material-history',help='可选只读历史材质查询记录；缺失时正常输出0条候选')
        if name=='return-export':
            cmd.add_argument('--material-history',help='可选；未提供时保持材质候选为空')
            cmd.add_argument('--file',required=True)
            cmd.add_argument('--recommendations',help='Skill生成的推荐JSON；仅候选，不是审核')
            cmd.add_argument('--official-materials',help='独立官方参考JSON；不能冒充最终申报选择')
            cmd.add_argument('--reopen-rows',help='业务明确要求纠错的稳定行ID列表JSON；不默认重审已批商品')
        if name=='return-preview':
            cmd.add_argument('--file',required=True)
            cmd.add_argument('--export-id',help='仅在可信只读匹配存在多个登记时，由宿主选择登记')
            cmd.add_argument('--operations',help='明确操作及范围JSON，不含操作者身份')
        if name=='return-commit':
            for field in ('preview-id','confirmed-hash','reference','session-token-env'):cmd.add_argument('--'+field,required=True)
            cmd.add_argument('--confirm',action='store_true',help='业务明确确认已展示的预览和操作范围后才能传入')
            cmd.add_argument('--library',help='外置D1库；提交成功后同步，失败仅标记可重试，不回滚审核决定')
        if name=='return-events':cmd.add_argument('--file',required=True)
        if name=='return-lock':
            cmd.add_argument('--reference',required=True);cmd.add_argument('--session-token-env',required=True)
    args = parser.parse_args(argv)
    store = Store(args.output)
    try:
        if args.command.startswith('product-library-'):
            from .product_library import ProductLibrary
            library=ProductLibrary(args.library)
            if args.command=='product-library-stats':value=library.statistics()
            else:value=library.lookup(args.code,japanese_name=args.japanese_name,version=args.version)
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.command in ('fill-contract','preflight'):
            from .business_setup import fill_contract,preflight
            if args.command=='fill-contract':value=fill_contract(store.root,read(args.contract),{'authority_quantity_unit':args.authority_unit,'invoice_quantity_unit':args.invoice_unit})
            else:
                import os
                from .return_auth import load_session
                try:session=load_session(store.root,os.environ.get(args.session_token_env,'')) if args.session_token_env else None
                except Rejected:session=None
                value=preflight(store.root,files=args.files,contract=read(args.contract) if args.contract else None,batch=store.load(args.batch) if args.batch else None,library=args.library,session=session)
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.command in ('d2-report','d2-replay'):
            from .decision_library import DecisionLibrary
            from .d2_candidates import analyze_library
            analysis=analyze_library(DecisionLibrary(args.library),as_of=args.as_of,realm=args.realm)
            value=analysis['discovery' if args.command=='d2-report' else 'validation']
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.command.startswith('rule-'):
            import os
            from .return_auth import load_session
            from .rule_registry import RuleRegistry
            registry=RuleRegistry(args.registry,library=args.library)
            batch=store.load(args.batch) if args.batch else None
            session=load_session(store.root,os.environ.get(args.session_token_env,'')) if args.session_token_env else None
            if args.command=='rule-draft':value=registry.draft(args.candidate_id,as_of=args.as_of,realm=args.realm)
            elif args.command=='rule-publish':value=registry.publish(args.rule_id,session=session,batch=batch,reference=args.reference,as_of=args.as_of,expected_version=args.expected_version)
            elif args.command=='rule-transition':value=registry.transition(args.rule_id,args.status,session=session,batch=batch,reference=args.reference,as_of=args.as_of,expected_version=args.expected_version)
            elif args.command=='rule-impact':value=registry.impact_report(as_of=args.as_of)
            elif args.command=='rule-apply':value=registry.apply(store,args.batch,args.row,facts=read(args.facts),as_of=args.as_of,session=session,reference=args.reference,expected_hash=args.expected_hash,realm=args.realm)
            else:value=registry.match(read(args.facts),as_of=args.as_of,allow_automatic=args.allow_automatic,session=session,batch=batch,realm=args.realm)
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.command=='workbuddy':
            from .workflow import execute
            print(json.dumps(execute(args.output,read(args.request)),ensure_ascii=False));return 0
        if args.command=='source-read':
            from .source_adapters import read_feishu,read_official,archive_evidence
            if Path(args.config).resolve()!=store.root/'security/source_config.json':
                raise Rejected('读取权限和字段映射只能来自宿主管理员保护的security/source_config.json')
            config=read(args.config)[args.kind]
            if args.kind=='official_web':value=read_official(args.url,config,identity_evidence=read(args.identity_evidence))
            else:value=read_feishu(args.kind,config)
            print(json.dumps(archive_evidence(store.root/'source_evidence',value),ensure_ascii=False));return 0
        if args.command=='source-status':
            from .source_adapters import status
            print(json.dumps(status(read(args.config) if args.config else None),ensure_ascii=False));return 0
        if args.command=='workbuddy-route':
            from .workbuddy_router import route,inspect_workbooks
            value=route(args.message);value['preflight']=inspect_workbooks(args.files) if args.files else None
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.command=='batch-brief':
            from .workbuddy_router import batch_brief
            print(json.dumps(batch_brief(args.output,args.batch),ensure_ascii=False));return 0
        if args.command=='d1-sync':
            from .workbuddy_router import sync_d1
            print(json.dumps(sync_d1(args.output,args.library,args.batch),ensure_ascii=False));return 0
        if args.command=='historical-references':
            from .workbuddy_router import historical_references
            print(json.dumps(historical_references(args.library,read(args.criteria),args.as_of),ensure_ascii=False));return 0
        if args.command.startswith('knowledge-'):
            from .decision_library import DecisionLibrary
            if args.command=='knowledge-init':
                from .business_setup import runtime
                mode=runtime(store.root)['execution_mode']
                expected='business' if mode=='business' else 'synthetic'
                if args.source_kind!=expected:raise Rejected('D1来源类型必须与可信运行环境一致；不能将技术库标为真实业务库')
                library=DecisionLibrary.create(args.library,source_root=args.output,source_kind=args.source_kind)
                value={'library':str(library.root),'created':True,'source_kind':args.source_kind}
            elif args.command=='knowledge-restore':
                library=DecisionLibrary.restore(args.backup,args.library);value=library.integrity()
            else:
                library=DecisionLibrary(args.library)
                if args.command=='knowledge-import':value=library.import_batch(args.batch)
                elif args.command=='knowledge-history':value=library.history(args.batch,args.decision)
                elif args.command=='knowledge-stats':value=library.statistics(as_of=args.as_of)
                elif args.command=='knowledge-search':value=library.search(read(args.criteria),as_of=args.as_of,realm=args.realm)
                elif args.command=='knowledge-check':value=library.integrity()
                elif args.command=='knowledge-rebuild':value=library.rebuild()
                elif args.command=='knowledge-backup':value=library.backup(args.backup)
                else:value=library.upgrade()
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.command in ("init-contract", "sign-contract"):
            from .contracts import create_contract
            from .business_setup import save_contract,sign_filled_contract
            if args.command == "init-contract":
                value = create_contract(args.invoice,args.authority,args.weights,args.weight_sheet,
                                        customs_reference=args.customs_reference,internal_reference=args.internal_reference)
            else:
                import os
                from .return_auth import load_session
                value=sign_filled_contract(store.root,read(args.contract),session=load_session(store.root,os.environ.get(args.session_token_env,'')),reference=args.evidence,confirmed_hash=args.confirmed_hash,confirm=args.confirm)
                print(json.dumps(value,ensure_ascii=False));return 0
            print(json.dumps(save_contract(store.root,value),ensure_ascii=False))
            return 0
        if args.command == "import-batch":
            from .business_setup import managed_import
            print(json.dumps(managed_import(store.root,read(args.contract)),ensure_ascii=False))
            return 0
        if args.command == "import-stage3":
            batch = import_stage3(args.source, currency=args.currency, quantity_unit=args.quantity_unit)
            if args.p0_evidence:
                batch = attach_p0_findings(batch, args.p0_evidence)
            folder = store.save(batch)
            print(json.dumps({"batch": batch["id"], "rows": len(batch["rows"]), "folder": str(folder),
                              'purpose':'pre_import_only','business_review_allowed':False,
                              'next_step':'补齐原始表/箱重表后init-contract → fill-contract → sign-contract → import-batch；不可在快照补造input_contract'}, ensure_ascii=False))
            return 0
        batch = store.load(args.batch)
        check_sources(batch)
        folder = store.folder(args.batch)
        if args.command.startswith('return-'):
            from .business_setup import require_contract,require_managed_review
            if args.command in ('return-export','return-preview','return-commit','return-lock'):require_contract(batch)
            if args.command in ('return-commit','return-lock'):require_managed_review(store.root,batch)
            from .excel_return import ReturnService,decision_event_stream
            service=ReturnService(store.root)
            if args.command=='return-export':
                from .compact_review import export_compact
                seed=folder/'return_seeds'/('r'+str(batch['revision'])+'-'+digest(batch)[:12])
                if not seed.exists():export_compact(batch,args.material_history,seed)
                value=service.register_b1(args.batch,seed,args.file,
                    recommendations=read(args.recommendations) if args.recommendations else None,
                    official_materials=read(args.official_materials) if args.official_materials else None,
                    reopen_ids=read(args.reopen_rows) if args.reopen_rows else None)
            elif args.command=='return-preview':
                preview=service.preview(args.file,batch_id=args.batch,export_id=args.export_id,operations=read(args.operations) if args.operations else None)
                if preview['batch_id']!=args.batch:raise Rejected('上传不属于指定批次')
                value={'preview_id':preview['preview_id'],'confirmation_hash':preview['confirmation_hash'],
                    'file':str(service._path('previews',preview['preview_id'])),'base_is_current':preview['base_is_current'],
                    'edited_questions':len(preview['edits']),'explicit_operations':len(preview['operations'])}
            elif args.command=='return-commit':
                import os
                from .return_auth import load_session
                preview=read(service._path('previews',args.preview_id))
                if preview['batch_id']!=args.batch:raise Rejected('预览不属于指定批次')
                session=load_session(store.root,os.environ.get(args.session_token_env,''))
                value=service.commit(args.preview_id,confirmed_hash=args.confirmed_hash,explicit_confirmation=args.confirm,
                    reference=args.reference,session=session)
                if args.library:
                    from .workbuddy_router import sync_d1
                    value['knowledge_sync']=sync_d1(store.root,args.library,args.batch)
                else:
                    value['knowledge_sync']={'status':'not_requested','automatic_adoption':False}
            elif args.command=='return-events':
                target=Path(args.file).resolve();Store(target.parent).guard(batch)
                if target.exists() or target.suffix!='.json':raise Rejected('事件导出须为新的JSON文件')
                target.parent.mkdir(parents=True,exist_ok=True)
                events=list(decision_event_stream(batch));atomic_json(target,{'events':events,'automatic_rules':False})
                value={'file':str(target),'events':len(events),'formal_output':False}
            elif args.command=='return-lock':
                import os
                from .return_auth import load_session
                value=service.lock_review(args.batch,session=load_session(store.root,os.environ.get(args.session_token_env,'')),reference=args.reference)
            else:value=service.status(args.batch)
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.command == "apply":
            req = read(args.request)
            from .business_setup import require_managed_review
            require_managed_review(store.root,batch)
            if any(k in req for k in ('actor','permissions','execution_mode','roles')):raise Rejected('身份/权限/模式只能来自可信宿主，不接受请求自报')
            if req["state_hash"] != digest(batch):
                raise Rejected("请求版本已过期")
            import os
            from .return_auth import load_session,authorize
            session=load_session(store.root,os.environ.get(args.session_token_env,''))
            roles={'identity':'identity','price':'amount','material':'material','packaging':'packaging','tax':'customs'}
            role=roles.get(req.get('domain') or req.get('package',{}).get('domain'),'business')
            common = {"actor": session.principal, "evidence": req["evidence"], "permissions": authorize(store.root,session,batch,role)}
            if req["action"] == "supplement":
                updated = supplement(batch, req["row_id"], req["values"], **common)
            elif req["action"] == "supplement-group":
                updated = supplement_many(batch, req["items"], **common)
            elif req["action"] == "confirm-products":
                updated = confirm_products(batch, req["package"], req["row_ids"], mode=req["mode"],
                                           resolutions=req.get("resolutions"), **common)
            elif req["action"] == "approve-domain":
                updated = approve_domain(batch, req["row_id"], req["domain"], req["payload"], **common)
            elif req['action'] == 'approve-group':
                from .group_review import approve_group
                updated=approve_group(batch,req['package'],req['group_id'],req['row_ids'],req['common'],req.get('per_row',{}),
                                      scope_confirmed=req.get('scope_confirmed',False),**common)
            elif req['action'] == 'record-exception':
                from .group_review import record_exception
                updated=record_exception(batch,req['row_ids'],req['domain'],status=req.get('status','pending'),**common)
            else:
                raise Rejected("未知操作")
            store.save(updated, expected_hash=digest(batch))
            print(json.dumps({"revision": updated["revision"], "state_hash": digest(updated)}))
        else:
            if args.command == "formal-export":
                from .batchflow import require_formal_release
                require_formal_release(batch)
            if args.command=='export-compact':
                from .compact_review import export_compact
                target=folder/'compact'/('r'+str(batch['revision'])+'-'+digest(batch)[:12])
                print(json.dumps(export_compact(batch,args.material_history,target),ensure_ascii=False))
                return 0
            if args.command=='export-intermediate':
                from .intermediate import export_intermediate
                target=folder/'intermediate'/('r'+str(batch['revision'])+'-'+digest(batch)[:12])
                print(json.dumps(export_intermediate(batch,target),ensure_ascii=False))
                return 0
            if args.command == "render-drafts":
                from .drafts import render_pair,draft_payload,verify_pair
                from .report_templates import target_name,load_preview
                candidate=load_preview(args.output,batch,args.preview_id) if args.preview_id else None
                name=target_name(batch,args.preview_id) if batch.get('input_mode')=='raw_invoice_preliminary' else 'r'+str(batch['revision'])+'-'+digest(batch)[:12]
                target = folder/'drafts'/name
                if target.exists():
                    payload=draft_payload(batch,candidate_preview=candidate)
                    value={'directory':str(target),'comparison':verify_pair(batch,target,payload),'summary':payload['summary'],'replayed':True}
                else:
                    value = render_pair(batch,target,read(args.runtime) if args.runtime else None,previews=args.previews,candidate_preview=candidate)
                print(json.dumps(value,ensure_ascii=False))
                return 0
            if args.command == "review-package":
                value = review_package(batch)
            elif args.command == 'group-review-package':
                from .group_review import group_package
                value=group_package(batch,args.domain)
            elif args.command == 'identity-checklist':
                from .business_review import identity_checklist
                value=identity_checklist(batch)
            elif args.command == "status":
                value = readiness(batch)
            elif args.command == "check-amounts":
                value = reconcile_amounts(batch["rows"], read(args.proposed))
            elif args.command == "calculation-preview":
                value = [{"id": r["id"], "price": exact_price(r), "box_tax": box_tax(r)} for r in batch["rows"]]
            elif args.command == "professional-queue":
                from .batchflow import professional_queue
                value=professional_queue(batch)
            elif args.command == "reconcile-logistics":
                from .logistics import reconcile_logistics
                value=reconcile_logistics(batch["rows"],batch["weight_data"])
            elif args.command == "reconcile-quantities":
                from .batchflow import reconcile_quantities
                value=reconcile_quantities(batch)
            else:
                value = [customs_preview(r) for r in batch["rows"]]
            # Revision-named files are review aids, never formal deliverables.
            suffix='-'+args.domain if args.command=='group-review-package' else ''
            target = folder / f"{args.command}{suffix}-r{batch['revision']:06d}.json"
            atomic_json(target, value)
            print(json.dumps({"file": str(target), "state_hash": digest(batch)}, ensure_ascii=False))
        return 0
    except (Rejected, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2
