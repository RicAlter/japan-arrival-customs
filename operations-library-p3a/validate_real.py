"""Private held-out replay. No business paths/data are stored in this source."""
import argparse
from pathlib import Path
import copy

from integrated_arrival.support import load,save,digest,key,check_hashes,dependencies,ROOT
from integrated_arrival.flow import execute
from integrated_arrival.library import inspect_database,query
from integrated_arrival.comparison import compare


def validate(cfg):
    dependencies()
    from arrival_core.operations_adapter import prepare
    report=Path(cfg['report_output']);report.mkdir(parents=True,exist_ok=False)
    protected=cfg['protected_files'];check_hashes(protected)
    source_code={str(p):digest(p) for p in ROOT.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and '__pycache__' not in p.parts}
    request=load(cfg['request']);old=load(cfg['old_provenance']);plan=prepare(request['files'])
    # The prior explicit user confirmation persists for the identical original
    # bytes, identical mappings and identical special/pairing scope. Only the
    # isolated checkout's mapping paths alter the bundle hash. Never silently
    # confirm different business data in the runtime.
    def source_values(sources):return {(s['kind'],Path(s['path']).name,s['sha256']) for s in sources}
    if source_values(plan['sources'])!=source_values(old['sources']):raise ValueError('同批源文件/映射不一致，不得复用确认')
    units=request['units_confirmation']
    if units['special_conversion_hash']!=plan['special_conversion_hash'] or units.get('pairing_hash')!=plan['pairing_hash']:
        raise ValueError('换算或配对范围不一致，须重新确认')
    original_bundle=units['source_bundle_hash'];bound=copy.deepcopy(request)
    bound['units_confirmation']['source_bundle_hash']=plan['source_bundle_hash']
    save(report/'confirmation-scope-proof.json',{'same_original_bytes_and_mapping_bytes':True,
         'same_special_and_pairing_hashes':True,'old_bundle_hash':original_bundle,'isolated_bundle_hash':plan['source_bundle_hash'],
         'basis':'沿用用户对同批同原件同范围的明确确认，仅隔离映射路径变化；非正式审批'})
    save(report/'request-bound.json',bound)
    library={'database':cfg['database'],'current_batch_id':cfg['current_batch_id']};save(report/'library-config.json',library)
    result=execute(cfg['run_output'],bound,library)
    save(report/'integration-result.json',result)
    if result['status'] not in ('ok','ok_with_business_exceptions'):raise ValueError('真实集成未通过：'+str(result))
    diffs={}
    for kind,original in cfg['baseline'].items():
        generated=next(p for p in result['business_files'] if ('海关' if kind=='customs' else '内部') in Path(p).name)
        diffs[kind]=compare(original,generated)
        if not diffs[kind]['equal']:raise ValueError('真实样本语义差异：'+kind)
    # Real original B4 is also exercised through the same P1 read interface;
    # it need not have any P2-B tables and is never initialized or migrated.
    original_info=inspect_database({'database':cfg['original_b4'],'current_batch_id':cfg['current_batch_id']})
    original_query=query(original_info,load(result['engine_batch_file']))
    save(report/'original-b4-query.json',original_query)
    check_hashes(protected);check_hashes(source_code)
    acceptance={'status':'passed','summary':result['summary'],'differences':diffs,
        'protected_files_unchanged':len(protected),'integration_source_files_unchanged':len(source_code),
        'original_b4_supported':original_info,'original_b4_query_rows':len(original_query['p1']['rows']),
        'original_b4_overlay_optional':original_query['p2b'] is None,
        'engine_math_and_gates_unchanged':True,'no_legacy_migration':True,
        'output_copy_hashes':result['delivery_hashes'],'original_output_hashes_unchanged':{p:digest(p) for p in cfg['baseline'].values()},
        'input_confirmation_reused_only_for_identical_scope':True,
        'verification':result['delivery_verification'],'business_files':result['business_files'],
        'database_write':False,'d1_accessed':False,'web_requests':0,'workbuddy_tested':False,'formal_output':False}
    save(report/'acceptance.json',acceptance)
    print({'status':'passed','rows':result['summary']['rows'],'business_exceptions':result['business_exception_total'],
           'semantic_equal':all(v['equal'] for v in diffs.values()),'protected':len(protected)})
    return acceptance


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);validate(load(parser.parse_args().config))
