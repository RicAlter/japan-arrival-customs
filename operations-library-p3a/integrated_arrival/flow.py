"""Transactional delivery boundary around the unchanged rc.5 operations route."""
from pathlib import Path
import copy
import json
import shutil
import sqlite3
import traceback

from .support import Rejected,dependencies,digest,key,load,save,check_hashes
from .library import inspect_database,query
from .classification import classify_batch
from .colors import mark_current

ENGINE_FIELDS={'message','files','units_confirmation','comparison_files','no_code_reasons','reference_evidence','tax_allocations'}


def validate_request(request):
    if not isinstance(request,dict) or set(request)-ENGINE_FIELDS or request.get('message')!='处理已确认运营表':
        raise Rejected('隔离集成仅接受已确认运营表主入口，不接受旧库维护或正式输出命令')
    if not isinstance(request.get('files'),list) or not request['files'] or any(not isinstance(f,str) for f in request['files']):
        raise Rejected('需提供真实运营输入文件')
    other=request.get('comparison_files',[])
    if not isinstance(other,list) or any(not isinstance(f,str) for f in other):raise Rejected('历史对照输入须为文件数组')
    return [Path(f).resolve(strict=True) for f in request['files']+other]


def execute(output,request,library_config):
    output=Path(output).resolve()
    # An existing result may be in use: never overwrite it or recover in place.
    if output.exists():raise Rejected('集成输出目录必须全新，拒绝覆盖旧结果')
    if isinstance(request,dict):
        for name in request.get('files',[]) if isinstance(request.get('files'),list) else []:
            if isinstance(name,str):
                path=Path(name).resolve()
                if output.is_relative_to(path.parent) or path.is_relative_to(output):raise Rejected('输出目录须与原件目录隔离')
    output.mkdir(parents=True)
    technical=output/'technical';technical.mkdir();stage='dependencies';snapshot={};published=False
    result={'schema':'p3a-operational-integration-result/1','status':'validation_incomplete',
            'business_exception_total':None,'business_exception_rows':None,'manual_input_cells':None,
            'business_files':[],'formal_output':False,'material_approval':False,'automatic_identity_confirmation':False}
    try:
        lock=dependencies()
        stage='input_validation';files=validate_request(request)
        for path in files:
            if output.is_relative_to(path.parent) or path.is_relative_to(output):raise Rejected('输出目录须与原件目录隔离')
        snapshot={str(p):digest(p) for p in files}
        frozen_request=key(request)
        stage='database_validation';info=inspect_database(library_config)
        if Path(info['path']).is_relative_to(output):raise Rejected('只读资料库不能放在本次输出目录中')
        snapshot[info['path']]=info['sha256']
        stage='engine_input_and_calculation'
        from arrival_core.workflow import execute as engine_execute
        from arrival_core.colored_tables import payload,verify
        from arrival_core.storage import check_sources
        # No library fields enter the old engine request, payload or batch.
        engine=engine_execute(technical/'engine',copy.deepcopy(request))
        save(technical/'engine-result.json',engine)
        if engine.get('status')!='ok':
            check_hashes(snapshot);dependencies()
            result.update(status=engine.get('status','validation_incomplete'),stage=stage,
                          reason=engine.get('reason','需先完成本批来源、单位及特殊换算确认'),
                          input_confirmation=engine if engine.get('status')=='needs_confirmation' else None)
            save(output/'result.json',result);return result
        stage='pair_verification'
        folder=Path(engine['provenance']).parent.parent
        batch_path=folder/'batch.json';batch=load(batch_path);batch_hash=digest(batch_path)
        data=payload(batch);data_hash=key(data);state_hash=key(batch)
        pair=Path(engine['result']['directory']);comparison=verify(batch,pair,data)
        if comparison['rows']!=len(batch['rows']) or not comparison['formal_rejected']:raise Rejected('原计算/双表/正式门禁未完成核验')
        if key(batch)!=state_hash or digest(batch_path)!=batch_hash:raise Rejected('原核验改变本批状态')
        save(technical/'pair-verification.json',comparison)
        stage='readonly_library_query';candidates=query(info,batch)
        save(technical/'library-candidates.json',candidates)
        stage='current_vs_long_term_classification';classified=classify_batch(batch,data,candidates)
        if key(batch)!=state_hash or key(data)!=data_hash or digest(batch_path)!=batch_hash:raise Rejected('资料库查询/分类改变了计算输入或结果')
        save(technical/'classification.json',classified)
        delivery_pair=pair
        marked,changes=mark_current(data,classified)
        if changes:
            stage='current_exception_colors'
            from arrival_core.colored_tables import write_pair
            delivery_pair=technical/'classified-pair';delivery_pair.mkdir()
            write_pair(marked,delivery_pair)
            comparison=verify(batch,delivery_pair,marked)
            save(technical/'current-exception-colors.json',changes)
            save(technical/'classified-pair-verification.json',comparison)
        stage='final_integrity'
        check_sources(batch);check_hashes(snapshot);dependencies()
        files_expected={Path(v['path']).name:v['sha256'] for v in comparison['files'].values()}
        if set(files_expected)!={'海关报关单_受控测试草稿.xlsx','内部到货单_受控测试草稿.xlsx'}:raise Rejected('原引擎交付范围不是两张业务表')
        for name,expected in files_expected.items():
            if digest(delivery_pair/name)!=expected:raise Rejected('双表核验后结果变化')
        # Only copy already verified bytes. The integration has no Excel writer
        # and does not edit values, formulas, styles, comments or metadata.
        staged=technical/'staged-delivery';staged.mkdir()
        for name in files_expected:shutil.copyfile(delivery_pair/name,staged/name)
        delivery=output/'delivery'
        hashes={str(delivery/name):digest(staged/name) for name in files_expected}
        if list(hashes.values())!=list(files_expected.values()):raise Rejected('交付复制后的哈希不一致')
        check_hashes(snapshot);check_sources(batch);dependencies()
        staged.rename(delivery);published=True
        check_hashes(snapshot)
        summary=classified['summary']
        result.update(status='ok_with_business_exceptions' if summary['business_exception_total'] else 'ok',
            stage='verified_delivery',business_exception_total=summary['business_exception_total'],
            business_exception_rows=summary['business_exception_rows'],manual_input_cells=summary['manual_input_cells'],
            business_files=list(hashes),summary=summary,delivery_hashes=hashes,
            input_and_database_hashes_unchanged=snapshot,dependency_files_checked=len(lock['files']),
            engine_batch_file=str(batch_path),engine_pair=str(pair),
            verified_delivery_pair=str(delivery_pair),current_red_cells_added=len(changes),
            delivery_verification=comparison,workbuddy_tested=False,
            message='仅交付两张受控表，当前异常看原表内标色；长期资料问题留后台')
        save(output/'result.json',result);return result
    except Exception as exc:
        # No partial success, stale count or deliverable paths escape on errors.
        # Preserve engine files for diagnosis. Published files (if a post-copy
        # check failed) move into this new run's technical quarantine only.
        if published and (output/'delivery').exists():
            (output/'delivery').rename(technical/'rejected-delivery')
        save(technical/'failure.json',{'stage':stage,'type':type(exc).__name__,'reason':str(exc),'traceback':traceback.format_exc()})
        result={'schema':'p3a-operational-integration-result/1','status':'validation_incomplete','stage':stage,'reason':str(exc),
                'business_exception_total':None,'business_exception_rows':None,'manual_input_cells':None,'business_files':[],
                'formal_output':False,'material_approval':False,'automatic_identity_confirmation':False}
        save(output/'result.json',result);return result
