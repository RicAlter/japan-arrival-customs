"""Stage-one preparation orchestrates existing projection/query/A02/A03 only."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import shutil
from .support import ROOT,Rejected,bootstrap,digest,key,load,save,code_snapshot,check_hashes
from .projection import project
from .references import collect

COLUMNS={'internal_name':'E','specification':'F','purchase_unit_price':'G','category':'M','material_reference':'N','channel':'O','yd':'P',
         'purchase_quantity':'Q','purchase_price_unit':'R','purchase_quantity_unit':'S'}
HEADERS={'G':'采购单价（原计价单位）','H':'盒规（后续阶段）','Q':'采购数量（独立）','R':'采购计价单位','S':'采购数量单位','T':'AI参考品类','U':'AI参考材质'}

def prepare(request,output):
    bootstrap();output=Path(output).resolve()
    if output.exists():raise Rejected('第一阶段须使用新候选目录，不覆盖旧资料或确认记录')
    if request.get('phase')!='basic_only':raise Rejected('本轮仅支持第一阶段，不提供价格更新或盒规计算')
    from a_confirm.service import Service as Prior
    # Inspect the prior immutable snapshot directly. Calling legacy read_current
    # would run its price recheck, which is explicitly outside stage one.
    prior=Prior(request['prior_a03_root']).store.load(request['prior_batch_id'])
    if key(prior)!=request['prior_current_hash'] or any(r.get('confirmed') for r in prior.get('a03',{}).get('overrides',{}).values()) or prior['revision']!=0:
        raise Rejected('历史A资料已有保存或变化，不能用零版样本覆盖；历史记录保持原样')
    output.mkdir(parents=True);tech=output/'technical';tech.mkdir()
    raw=Path(request['projection']['source'])
    if digest(raw)!=request['projection']['source_sha256']:raise Rejected('日方原始附件版本已变化')
    shutil.copyfile(raw,tech/'original-japanese-attachment.xlsx')
    if digest(tech/'original-japanese-attachment.xlsx')!=request['projection']['source_sha256']:raise Rejected('原始附件保全失败')
    before=code_snapshot();projection_file,projection_check=project(request['projection'],tech/'projection')
    from native22.profiles import inspect_source
    source=inspect_source(projection_file)
    if source['profile_id']!='kmt-native-16-v1' or any(source['sheet'].f(r['source_row'],'H') for r in source['rows']):
        raise Rejected('既有基础投影不应有新盒规公式，不在此重写计算')
    refs=collect(source,request['references'])
    save(tech/'reference-snapshot.json',refs);save(tech/'request.json',request)
    records=[];fields=[];rows=deepcopy(source['rows']);priorreg=load(request['references']['prior_registration'])
    byold={(f['cell'],f['field']):f for f in priorreg['fields']}
    for rec in refs['rows']:
        n=rec['row']
        for name,col in COLUMNS.items():
            value=rec['values'].get(name);meta=deepcopy(rec['metadata'].get(name,{}))
            sources=meta.get('sources',[])
            if value not in (None,''):
                records.append({'cell':col+str(n),'value':str(value),'kind':'number' if name in {'purchase_unit_price','purchase_quantity'} else 'text','color':'yellow','editable':True})
            fields.append({'row_id':rec['row_id'],'sheet':source['sheet'].name,'cell':col+str(n),'field':name,
                'original_value':None,'original_type':None,'original_formula':None,'working_value':str(value) if value is not None else None,
                'status':rec['statuses'].get(name,'unknown'),'confirmed':False,'sources':sources,'material_approval':False,
                'stage1_source_metadata':meta})
        for col,name in [('T','ai_category'),('U','ai_material')]:
            if rec[name] not in (None,''):records.append({'cell':col+str(n),'value':str(rec[name]),'kind':'text','color':rec['ai_material_color'] if col=='U' else 'yellow','editable':False})
    policy={'schema':'stage1-basic-fields/1','phase':'basic_only','seven_fields':['internal_name','specification','purchase_unit_price','purchase_quantity','yd','channel','category'],
        'unit_auxiliary_fields':['purchase_price_unit','purchase_quantity_unit'],'material_optional':True,'source_mapping_reused':True,
        'purchase_quantity_independent_of_arrival':True,'box_inference_executed':False,'price_difference_executed':False,
        'manual_columns':COLUMNS,'reference_columns':{'category':'T','material':'U'},'original_source_columns':16,'registered_output_columns':21,
        'input_21_column_importer_implemented':False,'phase2_implemented':False,'phase3_implemented':False,'formal_output':False}
    plan={'schema':'stage1-authoring-plan/1','input':str(projection_file),'sheet':source['sheet'].name,'rows':len(rows),'row_map':rows,
        'source_manifest':source['batch']['sources'],'source_profile':source['profile_id'],'source_row_map_hash':source['row_map_hash'],
        'fields':fields,'records':records,'headers':HEADERS,'filter_range':'B1:U1313','artifact_output':str(tech/'artifact-authored.xlsx'),
        'policy':policy,'code_snapshot':before,'source_original':request['projection']['source'],'source_original_sha256':request['projection']['source_sha256']}
    save(tech/'authoring-plan.json',plan);save(tech/'source-batch.json',source['batch']);save(tech/'policy.json',policy)
    check_hashes(before)
    summary={'rows':len(rows),'references':refs['counts'],'field_nonempty':{name:sum(f['field']==name and f['working_value'] not in (None,'') for f in fields) for name in COLUMNS},
        'purchase_quantity_from_arrival':0,'pricing_deferred':True,'original_source_sha256':plan['source_original_sha256'],'confirmed_fields':0,
        'minimum_unit_prices_automatically_confirmed':0,'procurement_total':None,'business_loop_passed':False}
    save(tech/'preparation-summary.json',summary)
    return summary

def finalize(output):
    from .workbook import patch_from_authored
    from .service import Service
    from native_copy.support import snapshot_root
    from arrival_core.storage import Store
    from native_copy.service import registered_copy
    from native_copy.ooxml import parts
    from . import __version__
    output=Path(output).resolve(strict=True);tech=output/'technical';p=load(tech/'authoring-plan.json');check_hashes(p['code_snapshot'])
    if (output/'result.json').exists():raise Rejected('候选已发布，不覆盖发出基准')
    data,preservation=patch_from_authored(p)
    # Keep a separate invisible per-issue marker, using existing return concept.
    from .workbook import version_marker
    token=key({'policy':p['policy'],'source':p['source_original_sha256'],'fields':p['fields'],'reference':digest(tech/'reference-snapshot.json')})
    data=version_marker(data,token)
    native=output/'native-copy';nt=native/'technical';nt.mkdir(parents=True);delivery=native/'delivery';delivery.mkdir()
    issued=delivery/'issued-baseline.xlsx';issued.write_bytes(data)
    refs=load(tech/'reference-snapshot.json')
    save(nt/'reference-candidates.json',{'schema':'stage1-reference-candidates/1','database':refs['fresh_query']['database'],
        'field_candidates':{r['row_id']:{k:{'value':v,'status':r['statuses'].get(k,'unknown'),'sources':r['metadata'].get(k,{}).get('sources',[]),'confirmed':False} for k,v in r['values'].items()} for r in refs['rows']},
        'assistant_references':[{'row':r['row'],'category':r['ai_category'],'material':r['ai_material'],'confirmed':False} for r in refs['rows']]})
    references=load(nt/'reference-candidates.json');source_batch=load(tech/'source-batch.json')
    reg={'schema':'a01-native-copy-registration/1','implementation_version':__version__,'business_batch_id':load(tech/'request.json')['references']['batch_label'],
        'source_manifest':p['source_manifest'],'source_manifest_hash':key(p['source_manifest']),'source_sha256':digest(Path(p['input'])),
        'profile_id':p['source_profile'],'source_header_row':1,'source_qualification':'provided_11_column_invoice_projected_without_business_approval',
        'implementation_files_sha256':p['code_snapshot'],'copy_sha256':digest(issued),'copy_relative_path':'delivery/issued-baseline.xlsx',
        'batch_id':source_batch['id'],'batch_revision':0,'a_version':key({'fields':p['fields'],'references':key(references),'phase':'basic_only'}),
        'row_map_hash':p['source_row_map_hash'],'row_map':p['row_map'],'fields':p['fields'],'copy_changes':[],
        'reference_snapshot_hash':key(references),'library_snapshot':references['database'],'protected_weight_sheets':['重さとサイズ'],
        'preservation':preservation,'price_basis':{'status':'stage1_purchase_reference_only','source':p['source_original_sha256'],'pricing_deferred':True},
        'stage1_policy':p['policy'],'stage1_version':{'property':'CustomsAStageExportVersion','value':token},
        'confirmed_fields':[],'qty_unit_confirmed':False,'material_approval':False,'can_enter_b':False,'formal_output':False}
    reg['export_id']=key(reg);save(nt/'export-registration.json',reg);save(nt/'preservation.json',preservation)
    Store(snapshot_root(nt/'batch-store')).save(source_batch)
    save(native/'result.json',{'schema':'a01-native-copy-result/1','status':'prepared_reference_copy','export_id':reg['export_id'],'a_version':reg['a_version'],'confirmed':False,'formal_output':False})
    registered_copy(native)
    context={'schema':'a02-trusted-context/1','current_output':str(native),'business_batch_id':reg['business_batch_id'],
        'export_id':reg['export_id'],'a_version':reg['a_version'],'known_outputs':[str(native)]}
    save(tech/'trusted-context.json',context);svc=Service(output/'state');receipt=svc.register(tech/'trusted-context.json');view=svc.read_current(reg['batch_id'])
    save(tech/'registration.json',receipt);save(tech/'current.json',view)
    business=output/'KMT20261101_第一阶段基础资料整理_候选.xlsx';shutil.copyfile(issued,business)
    save(output/'workflow-manifest.json',{'schema':'stage1-workflow/1','stage':'basic_only','business_file':str(business),'issued_file':str(issued),'issued_sha256':reg['copy_sha256'],
        'a03_root':str(svc.root),'batch_id':reg['batch_id'],'current_hash':view['current_hash'],'export_id':reg['export_id'],'policy':str(tech/'policy.json'),
        'original_source':p['source_original'],'original_source_sha256':p['source_original_sha256'],'human_return_received':False,'actual_business_confirmations':0,'formal_output':False})
    result={**load(tech/'preparation-summary.json'),'business_file':str(business),'stage1_service':str(svc.root),'issued_sha256':reg['copy_sha256'],'export_id':reg['export_id'],
        'status':'first_stage_candidate','phase2_implemented':False,'phase3_implemented':False,'formal_output':False,'installed_as_skill':False}
    save(output/'result.json',result);return result
