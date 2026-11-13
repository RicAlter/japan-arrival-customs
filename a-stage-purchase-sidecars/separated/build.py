"""Reissue the verified stage-one sample; no repeated raw import or queries."""
from pathlib import Path
from copy import deepcopy
import shutil
from .support import bootstrap,code_snapshot,load,save,digest,key,check_hashes,Rejected
from .query import build as query
from .workbook import main18
def prepare(workflow,output):
    bootstrap();output=Path(output).resolve();m=load(workflow)
    from stage1.service import Service as Prior
    current=Prior(m['a03_root']).read_current(m['batch_id'])
    if current['revision']!=0 or current['confirmed_field_count']!=0:raise Rejected('原候选已保存，不用空状态覆盖，须保留并衔接实际确认版本')
    if output.exists():raise Rejected('新布局须使用新目录，原版本不覆盖')
    if digest(Path(m['issued_file']))!=m['issued_sha256']:raise Rejected('原发出底稿摘要变化')
    prior=Path(workflow).resolve().parent;refs=load(prior/'technical/reference-snapshot.json');reg=load(prior/'native-copy/technical/export-registration.json')
    output.mkdir(parents=True);tech=output/'technical';tech.mkdir()
    plan={'prior_workflow':str(Path(workflow).resolve()),'input':m['issued_file'],'input_sha256':m['issued_sha256'],'output':str(output),'sheet':reg['row_map'][0]['source']['sheet'],
        'main_authored':str(tech/'main-authored.xlsx'),'main_file':str(output/'KMT20261101_基础资料主表.xlsx'),
        'query_file':str(output/'KMT20261101_采购查询表.xlsx'),'differences_file':str(output/'KMT20261101_采购数量核对表.xlsx'),
        'code_snapshot':code_snapshot(),'query':query(refs,reg['row_map'])}
    save(tech/'authoring-plan.json',plan)
    save(tech/'prior-state.json',{'revision':current['revision'],'current_hash':current['current_hash'],'confirmed':0})
    return plan['query']['counts']
def finalize(output):
    bootstrap();output=Path(output).resolve();tech=output/'technical';p=load(tech/'authoring-plan.json');check_hashes(p['code_snapshot'])
    if (output/'workflow-manifest.json').exists():raise Rejected('已发出登记不覆盖')
    if digest(Path(p['input']))!=p['input_sha256']:raise Rejected('原发出版本变化')
    oldm=load(p['prior_workflow']);prior=Path(p['prior_workflow']).parent;reg=load(prior/'native-copy/technical/export-registration.json')
    policy=deepcopy(reg['stage1_policy']);policy.update(purchase_columns_location='separate_query',manual_columns={k:v for k,v in policy['manual_columns'].items() if k not in {'purchase_quantity','purchase_price_unit','purchase_quantity_unit'}},
        reference_columns={'category':'Q','material':'R'},registered_output_columns=18,unit_auxiliary_fields=[],purchase_query_is_confirmation_input=False)
    token=key({'previous_export':reg['export_id'],'policy':policy,'copy':p['input_sha256']})
    data,preservation=main18(p['input'],p['main_authored'],p['sheet'],token)
    native=output/'native-copy';nt=native/'technical';nt.mkdir(parents=True);(native/'delivery').mkdir();issued=native/'delivery/issued-baseline.xlsx';issued.write_bytes(data)
    shutil.copyfile(prior/'native-copy/technical/reference-candidates.json',nt/'reference-candidates.json')
    from . import __version__
    reg.update(implementation_version=__version__,stage1_policy=policy,copy_sha256=digest(issued),
        a_version=key({'old':reg['a_version'],'layout':policy,'copy':digest(issued)}),fields=[f for f in reg['fields'] if f['field'] not in {'purchase_quantity','purchase_price_unit','purchase_quantity_unit'}],
        stage1_version={'property':'CustomsAStageExportVersion','value':token},layout_preservation=preservation,layout_parent_export=reg['export_id'],
        implementation_files_sha256={**reg['implementation_files_sha256'],**code_snapshot()})
    reg.pop('export_id',None);reg['export_id']=key(reg);save(nt/'export-registration.json',reg)
    from arrival_core.storage import Store
    from native_copy.support import snapshot_root
    Store(snapshot_root(nt/'batch-store')).save(load(prior/'technical/source-batch.json'))
    save(native/'result.json',{'schema':'a01-native-copy-result/1','status':'prepared_reference_copy','export_id':reg['export_id'],'a_version':reg['a_version'],'confirmed':False,'formal_output':False})
    context={'schema':'a02-trusted-context/1','current_output':str(native),'business_batch_id':reg['business_batch_id'],'export_id':reg['export_id'],'a_version':reg['a_version'],'known_outputs':[str(native)]}
    save(tech/'trusted-context.json',context)
    from .service import Service
    svc=Service(output/'state');receipt=svc.register(tech/'trusted-context.json');view=svc.read_current(reg['batch_id'])
    save(tech/'registration.json',receipt);save(tech/'preservation.json',preservation)
    shutil.copyfile(issued,p['main_file'])
    for name in ['query_file','differences_file']:
        if not Path(p[name]).is_file():raise Rejected('独立采购查询或数量核对表尚未生成')
    manifest={'schema':'stage1-separated-workflow/1','stage':'basic_only','business_file':p['main_file'],'issued_file':str(issued),'issued_sha256':reg['copy_sha256'],
        'purchase_query_file':p['query_file'],'quantity_check_file':p['differences_file'],'sidecars_are_query_only':True,
        'a03_root':str(svc.root),'batch_id':reg['batch_id'],'current_hash':view['current_hash'],'export_id':reg['export_id'],
        'prior_workflow':p['prior_workflow'],'human_return_received':False,'actual_business_confirmations':0,'formal_output':False,'counts':p['query']['counts']}
    save(output/'workflow-manifest.json',manifest);return manifest
