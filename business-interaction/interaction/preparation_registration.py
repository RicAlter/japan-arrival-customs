"""Register a fresh 20-column baseline through unchanged separated A03 services."""
from pathlib import Path
from . import load,save,key,digest,rt

def register(projected,file,original,config,evidence):
    from native_copy.profiles import inspect_source
    from native_copy.support import snapshot_root
    from arrival_core.storage import Store
    from separated.service import Service
    from stage1.workbook import version_marker
    from openpyxl import load_workbook
    source=inspect_source(projected);back=Path(config['background']);native=back/'controlled-baseline/native-copy';tech=native/'technical';tech.mkdir(parents=True)
    delivery=native/'delivery';delivery.mkdir();issued=delivery/'issued.xlsx'
    token=key({'source':digest(projected),'evidence':evidence,'layout':20})
    data=file.read_bytes()
    if config.get('reviewed_input'):
        # Preserve the reviewed copy's existing export marker. Never remove or
        # reset it, and never migrate its live A03 state into this isolated run.
        import xml.etree.ElementTree as ET
        from .photo_layout import parts
        custom=parts(data).get('docProps/custom.xml')
        markers=[e for e in ET.fromstring(custom) if e.get('name')=='CustomsAStageExportVersion'] if custom else []
        if len(markers)>1:raise ValueError('核对表版本标记不唯一')
        if markers:
            token=next(iter(markers[0])).text
            if not token:raise ValueError('核对表版本标记为空')
        else:data=version_marker(data,token)
    else:data=version_marker(data,token)
    file.write_bytes(data);issued.write_bytes(data)
    sheet=source['sheet'].name;wb=load_workbook(file,read_only=True);observed=list(wb[sheet].values);wb.close()
    fields=[];mapping={'internal_name':'F','specification':'G','purchase_unit_price':'H','category':'N','material_reference':'O','channel':'P','yd':'Q'}
    for row in source['rows']:
        n=row['source_row'];ev=evidence[str(n)]
        for field,col in mapping.items():
            value=observed[n-1][ord(col)-65]
            fields.append({'row_id':row['row_id'],'sheet':sheet,'cell':col+str(n),'field':field,'original_value':None,'original_type':None,
                'original_formula':None,'working_value':value,'status':'candidate' if value not in (None,'') else 'missing','confirmed':False,
                'sources':([{'kind':'reviewed_workbook','path':config['reviewed_input']['path'],'sha256':config['reviewed_input']['sha256'],
                             'sheet':sheet,'cell':col+str(n),'confirmed':False}] if config.get('reviewed_input') else
                           [ev['preserved_source_fields'][field]] if field in ev.get('preserved_source_fields',{}) else ev.get('sources',[])),
                'material_approval':False,'stage1_source_metadata':{'reference_only':True,'evidence_file':str(back/'evidence.json'),'row':n,
                    **({'linked_purchase_price':ev['price_review']} if field=='purchase_unit_price' and ev.get('price_review',{}).get('category')=='safe_linked_box_order_quote' else {})}})
    refs={'schema':'fresh-preparation-reference/1','database':config['database'],'field_candidates':{}}
    save(tech/'reference-candidates.json',refs)
    reg={'schema':'a01-native-copy-registration/1','implementation_version':'fresh20/1','business_batch_id':config['batch_label'],
         'source_manifest':source['batch']['sources'],'source_manifest_hash':key(source['batch']['sources']),'source_sha256':digest(projected),
         'implementation_files_sha256':{},'profile_id':source['profile_id'],'source_header_row':1,
         'copy_sha256':digest(issued),'copy_relative_path':'delivery/issued.xlsx','batch_id':source['batch']['id'],'batch_revision':0,
         'a_version':token,'row_map_hash':source['row_map_hash'],'row_map':source['rows'],'fields':fields,
         'reference_snapshot_hash':key(refs),'library_snapshot':config['database'],'protected_weight_sheets':source['weights'],
         'price_basis':{'status':'stage1_purchase_reference_only'},'confirmed_fields':[],'formal_output':False,
         'stage1_version':{'property':'CustomsAStageExportVersion','value':token},
         'stage1_policy':{'phase':'basic_only','purchase_columns_location':'separate_query','registered_output_columns':20,'manual_category_input_only':True}}
    reg['export_id']=key(reg);save(tech/'export-registration.json',reg)
    Store(snapshot_root(tech/'batch-store')).save(source['batch'])
    save(native/'result.json',{'status':'prepared_reference_copy','export_id':reg['export_id']})
    context={'current_output':str(native),'business_batch_id':config['batch_label'],'export_id':reg['export_id'],'a_version':token,'known_outputs':[str(native)],'schema':'a02-trusted-context/1'}
    save(back/'trusted-context.json',context);svc=Service(back/'a03-state');svc.register(back/'trusted-context.json')
    catalog={'database':config['database']['path'],'sha256':config['database']['sha256'],'rows':{n:{'material_link_sources':r.get('material_link_sources',[])} for n,r in evidence.items()}}
    save(back/'catalogue-snapshot.json',catalog)
    workflow={'schema':'catalogue-19-workflow/1','batch_id':reg['batch_id'],'a03_root':str(svc.root),'business_file':str(file),
        'issued_file':str(issued),'issued_sha256':digest(issued),'export_id':reg['export_id'],'original_source':str(original['path']),
        'catalogue_snapshot':str(back/'catalogue-snapshot.json'),'catalogue_snapshot_sha256':digest(back/'catalogue-snapshot.json'),
        'manual_packaging_original_text_only':True,'registered_columns':20,'reference_columns':{'pack_reference':'T'},
        'display_columns':{'manual_category':'N','manual_material':'O','website_material':'R','material_reference':'S','pack_reference':'T'},
        'source_row_mapping':{r['row_id']:original['rows'][i]['source_row'] for i,r in enumerate(source['rows'])}}
    save(back/'workflow.json',workflow)
    engine=rt.updates.Service.fork(back/'workflow.json',back/'live-state',mode=config['mode'])
    # Cache the prepared display against its exact initial head, preserving all picture bytes.
    save(back/'last-main-display.json',{'head':key(engine.store.load(engine.bid)),'file':str(file),'source_sha256':digest(file)})
    return {'root':str(engine.root),'prepared_sha256':digest(file),'registered_columns':20}
