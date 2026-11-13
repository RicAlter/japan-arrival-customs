"""Re-register the exact 19-column supplied workbook using existing A02/A03."""
from pathlib import Path
from copy import deepcopy
import shutil,xml.etree.ElementTree as ET,sqlite3,hashlib
from .support import bootstrap,load,save,key,digest,Rejected,code_snapshot
from .catalogue import snapshot
SHEET='invoice (計算)'

def register(reference_workbook,parent_workflow,database,output):
    bootstrap()
    from separated.service import Service
    from native_copy.service import registered_copy
    from native_copy.ooxml import parts
    from stage1.workbook import packed
    from arrival_core.storage import Store
    from native_copy.support import snapshot_root
    from openpyxl import load_workbook
    parent_workflow=Path(parent_workflow).resolve();parent=parent_workflow.parent;m=load(parent_workflow);prior=Service(m['a03_root']);current=prior.read_current(m['batch_id'])
    if current['revision'] or current['confirmed_field_count']:raise Rejected('已有人工保存/确认；禁止新底稿初始化覆盖，请先做显式版本迁移')
    output=Path(output).resolve()
    if output.exists():raise Rejected('登记目录必须为全新目录')
    output.mkdir(parents=True);fixed=output/'fixed-inputs';fixed.mkdir()
    source_reference=Path(reference_workbook).resolve();captured=source_reference.read_bytes();sha=hashlib.sha256(captured).hexdigest()
    original=fixed/'19列核对版_固定输入.xlsx';original.write_bytes(captured)
    source_database=Path(database).resolve();observed_database_sha=digest(source_database);frozen_database=fixed/'product-library.sqlite3'
    source_connection=sqlite3.connect(source_database.as_uri()+'?mode=ro',uri=True);source_connection.execute('PRAGMA query_only=ON')
    destination_connection=sqlite3.connect(frozen_database);source_connection.backup(destination_connection);destination_connection.close();source_connection.close()
    save(fixed/'snapshot-origin.json',{'source_reference':str(source_reference),'reference_sha256':sha,'source_database':str(source_database),'source_database_observed_sha256':observed_database_sha,
        'database_capture':'SQLite read-only backup including committed WAL; frozen SHA is authoritative','frozen_database_sha256':digest(frozen_database),'source_database_written':False})
    w=load_workbook(original);s=w[SHEET];old=load_workbook(m['issued_file']);a=old[SHEET]
    reg=registered_copy(parent/'native-copy');reg.pop('file');reg.pop('export_id')
    rows=[]
    for r in reg['row_map']:
        n=r['source_row']
        for c in [3,9,10,11,12]:
            if (s.cell(n,c).value,s.cell(n,c).data_type)!=(a.cell(n,c).value,a.cell(n,c).data_type):raise Rejected('原商品身份/数量金额公式变化：'+str(n))
        if s.cell(n,8).value is not None:raise Rejected('H必须保留空白')
        for c in [8,17,18,19]:
            if not s.cell(n,c).protection.locked:raise Rejected('H/Q/R/S参考保护缺失，不登记')
        rows.append({'row':n,'code':str(s.cell(n,3).value),'yd':s.cell(n,16).value,'specification':s.cell(n,6).value,'japanese_name':s.cell(n,9).value})
    if len(rows)!=1275 or s.max_column!=19 or s.auto_filter.ref!='B1:S1313':raise Rejected('仅登记已核验本批19列布局/筛选')
    catalog=snapshot(frozen_database,rows);tech=output/'technical';tech.mkdir();save(tech/'catalogue-snapshot.json',catalog)
    prior_history={'state':m['a03_root'],'hash':current['current_hash'],'revision':current['revision'],'confirmed':current['confirmed_field_count'],'previous_workflow':str(parent_workflow)};save(tech/'parent-history.json',prior_history)
    snapshot_sha=digest(tech/'catalogue-snapshot.json')
    for f in reg['fields']:
        n=int(''.join(x for x in f['cell'] if x.isdigit()));cell=s[f['cell']]
        f['working_value']=cell.value;f['status']='candidate' if cell.value not in (None,'') else 'missing';f['confirmed']=False
        f['prior_sources']=deepcopy(f['sources']);f['sources']=[{'kind':'source_derived_working_value_no_human_approval','path':str(original),'sha256':sha,'sheet':SHEET,'cell':f['cell'],'value':cell.value,
            'catalogue_snapshot':str(tech/'catalogue-snapshot.json'),'snapshot_sha256':snapshot_sha,'lookup_row':n,'original_sources_retained':f['prior_sources']}]
        f['stage1_source_metadata']={**f.get('stage1_source_metadata',{}),'value_origin':'source-derived or assistant-derived; not human-confirmed','original_working_value_preserved':True}
    reg['fields']=[f for f in reg['fields'] if f['field']!='pieces_per_box']
    w.close();old.close();data=original.read_bytes();p=parts(data);prop=ET.fromstring(p['docProps/custom.xml']);hits=[e for e in prop if e.get('name')=='CustomsAStageExportVersion']
    if len(hits)!=1 or len(hits[0])!=1:raise Rejected('原核对版版本属性不唯一')
    oldtoken=list(hits[0])[0].text;token=key({'reference_sha256':sha,'database_snapshot':key(catalog),'prior_hash':current['current_hash'],'code':code_snapshot()})
    if p['docProps/custom.xml'].count(oldtoken.encode())!=1:raise Rejected('版本标记不能唯一替换')
    p['docProps/custom.xml']=p['docProps/custom.xml'].replace(oldtoken.encode(),token.encode());data=packed(data,p)
    before=parts(original.read_bytes());after=parts(data)
    if any(before[k]!=after[k] for k in before if k!='docProps/custom.xml'):raise Rejected('新登记改变了工作簿内容')
    native=output/'native-copy';nt=native/'technical';nt.mkdir(parents=True);(native/'delivery').mkdir();issued=native/'delivery/issued-baseline.xlsx';issued.write_bytes(data)
    references=load(parent/'native-copy/technical/reference-candidates.json');references['catalogue_attachment']={'file':str(tech/'catalogue-snapshot.json'),'sha256':digest(tech/'catalogue-snapshot.json'),'whole_database_sha256':catalog['sha256'],'automatic_confirmation':False}
    save(nt/'reference-candidates.json',references)
    reg.update(copy_sha256=digest(issued),reference_snapshot_hash=key(references),stage1_version={'property':'CustomsAStageExportVersion','value':token},version_marker={'property':'CustomsAStageExportVersion','value':token},
        a_version=key({'parent':reg['a_version'],'reference':sha,'snapshot':key(catalog)}),layout_parent_export=m['export_id'],implementation_files_sha256={**reg['implementation_files_sha256'],**code_snapshot()})
    reg['stage1_policy'].update(registered_output_columns=19,reference_columns={'category':'Q','material':'R','pack_reference':'S'},box_reference_automatic_confirmation=False)
    reg['export_id']=key(reg);save(nt/'export-registration.json',reg)
    Store(snapshot_root(nt/'batch-store')).save(Store(snapshot_root(parent/'native-copy/technical/batch-store')).load(reg['batch_id']))
    save(native/'result.json',{'schema':'a01-native-copy-result/1','status':'prepared_reference_copy','export_id':reg['export_id'],'a_version':reg['a_version'],'confirmed':False,'formal_output':False})
    save(tech/'trusted-context.json',{'schema':'a02-trusted-context/1','current_output':str(native),'business_batch_id':reg['business_batch_id'],'export_id':reg['export_id'],'a_version':reg['a_version'],'known_outputs':[str(native)]})
    svc=Service(output/'state');receipt=svc.register(tech/'trusted-context.json');view=svc.read_current(reg['batch_id']);save(tech/'registration.json',receipt)
    business=output/'KMT20261101_19列受控基础资料.xlsx';shutil.copyfile(issued,business)
    for keyname in ['purchase_query_file','quantity_check_file']:
        source=Path(m[keyname]);shutil.copyfile(source,output/source.name)
    shutil.copyfile(parent/'technical/authoring-plan.json',tech/'authoring-plan.json')
    manifest={**m,'schema':'catalogue-19-workflow/1','business_file':str(business),'issued_file':str(issued),'issued_sha256':digest(issued),'a03_root':str(svc.root),'current_hash':view['current_hash'],
        'export_id':reg['export_id'],'prior_workflow':str(parent_workflow),'catalogue_snapshot':str(tech/'catalogue-snapshot.json'),'catalogue_snapshot_sha256':digest(tech/'catalogue-snapshot.json'),
        'parent_history':prior_history,'registered_columns':19,'human_return_received':False,'actual_business_confirmations':0}
    for keyname in ['purchase_query_file','quantity_check_file']:manifest[keyname]=str(output/Path(m[keyname]).name)
    save(output/'workflow-manifest.json',manifest);save(tech/'preservation.json',{'all_workbook_parts_except_version_identical':True,'rows':1275,'columns':19,'H_blank':True,'Q_R_S_locked':True,'original_reference_sha256':sha,'confirmation_count':0,'registered_as_baseline_not_business_approval':True})
    return manifest
