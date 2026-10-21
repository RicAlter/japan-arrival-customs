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
    for name in ("contract", "actor", "evidence", "permissions"):
        sign.add_argument("--"+name, required=True)
    incoming = sub.add_parser("import-batch"); incoming.add_argument("--contract", required=True)
    for name in ("review-package", "status", "apply", "customs-preview", "calculation-preview", "check-amounts",
                 "professional-queue", "group-review-package", "identity-checklist", "export-intermediate", "export-compact", "reconcile-logistics", "reconcile-quantities", "render-drafts", "formal-export",
                 "return-export", "return-preview", "return-commit", "return-status", "return-events", "return-lock"):
        cmd = sub.add_parser(name); cmd.add_argument("--batch", required=True)
        if name == "apply":
            cmd.add_argument("--request", required=True)
            cmd.add_argument("--permissions", required=True, help="本机可信管理员维护的审核人角色配置")
        if name == "check-amounts":
            cmd.add_argument("--proposed", required=True, help="完整的技术行ID到待核对金额的JSON映射")
        if name == "render-drafts":
            cmd.add_argument("--runtime", help="可选：显式选择旧Node引擎；默认Python/openpyxl")
            cmd.add_argument("--previews", action="store_true")
        if name == 'group-review-package':
            cmd.add_argument('--domain',required=True,choices=['identity','material','packaging','tax'])
        if name == 'export-compact':
            cmd.add_argument('--material-history',required=True,help='只读第2步材质查询记录；不进行在线查询')
        if name=='return-export':
            cmd.add_argument('--material-history',required=True)
            cmd.add_argument('--file',required=True)
            cmd.add_argument('--recommendations',help='Skill生成的推荐JSON；仅候选，不是审核')
            cmd.add_argument('--official-materials',help='独立官方参考JSON；不能冒充最终申报选择')
            cmd.add_argument('--reopen-rows',help='业务明确要求纠错的稳定行ID列表JSON；不默认重审已批商品')
        if name=='return-preview':
            cmd.add_argument('--file',required=True)
            cmd.add_argument('--operations',help='明确操作及范围JSON，不含操作者身份')
        if name=='return-commit':
            for field in ('preview-id','confirmed-hash','reference','session-token-env'):cmd.add_argument('--'+field,required=True)
            cmd.add_argument('--confirm',action='store_true',help='业务明确确认已展示的预览和操作范围后才能传入')
        if name=='return-events':cmd.add_argument('--file',required=True)
        if name=='return-lock':
            cmd.add_argument('--reference',required=True);cmd.add_argument('--session-token-env',required=True)
    args = parser.parse_args(argv)
    store = Store(args.output)
    try:
        if args.command.startswith('knowledge-'):
            from .decision_library import DecisionLibrary
            if args.command=='knowledge-init':
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
            from .contracts import create_contract, sign_contract
            if args.command == "init-contract":
                value = create_contract(args.invoice,args.authority,args.weights,args.weight_sheet,
                                        customs_reference=args.customs_reference,internal_reference=args.internal_reference)
            else:
                value = sign_contract(read(args.contract),actor=args.actor,evidence=args.evidence,permissions=read(args.permissions))
            # Reuse the same source/output path guard, without creating a business state.
            from .core import new_batch, new_row
            src = next(iter(value["sources"].values()))
            guard_row = new_row(dict(src,sheet="contract-path-guard",row=0,stage=3),{},currency="JPY",quantity_unit="")
            store.guard(new_batch([guard_row],list(value["sources"].values())))
            store.root.mkdir(parents=True,exist_ok=True)
            target = store.root/("contract-"+digest(value)[:24]+".json")
            if target.exists(): raise Rejected("合同输出已存在，拒绝覆盖")
            atomic_json(target,value)
            print(json.dumps({"file":str(target),"contract_hash":digest(value)},ensure_ascii=False))
            return 0
        if args.command == "import-batch":
            from .batchflow import import_batch
            batch = import_batch(read(args.contract)); folder=store.save(batch)
            print(json.dumps({"batch":batch["id"],"rows":len(batch["rows"]),"folder":str(folder)},ensure_ascii=False))
            return 0
        if args.command == "import-stage3":
            batch = import_stage3(args.source, currency=args.currency, quantity_unit=args.quantity_unit)
            if args.p0_evidence:
                batch = attach_p0_findings(batch, args.p0_evidence)
            folder = store.save(batch)
            print(json.dumps({"batch": batch["id"], "rows": len(batch["rows"]), "folder": str(folder)}, ensure_ascii=False))
            return 0
        batch = store.load(args.batch)
        check_sources(batch)
        folder = store.folder(args.batch)
        if args.command.startswith('return-'):
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
                preview=service.preview(args.file,operations=read(args.operations) if args.operations else None)
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
            if req["state_hash"] != digest(batch):
                raise Rejected("请求版本已过期")
            from .contracts import effective_permissions
            common = {"actor": req["actor"], "evidence": req["evidence"], "permissions": effective_permissions(batch,read(args.permissions))}
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
                from .drafts import render_pair
                target = folder/"drafts"/("r"+str(batch["revision"])+"-"+digest(batch)[:12])
                value = render_pair(batch,target,read(args.runtime) if args.runtime else None,previews=args.previews)
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
