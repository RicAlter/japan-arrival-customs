"""Canonical confirmed-basis adapter; run unchanged rc.5 ROUND0/tax/templates."""
from pathlib import Path
from copy import deepcopy
from fractions import Fraction
from .support import bootstrap,load,save,digest,key,get,Rejected
from .updates import Service as Updates
from .compute import Service,Bridge
from arrival_core.business_amount import effective_basis
from arrival_core.core import new_row,new_batch,context,validate
from arrival_core.operations_adapter import finite
from arrival_core.logistics import read_weights,reconcile_logistics
def render(root,destination):
    bootstrap();svc=Service(root);preflight=Bridge(root).prepare(svc.bid);input_batch=Bridge(root).current_input(preflight)
    parent=Updates(svc.owner['loop_root']);review=get(parent.root,svc.owner['review_preview']);baseline=svc._baseline(svc.store.load(svc.bid))[0]
    facts={baseline['mapping'][f['parent_id']]['row_id']:f for f in review['facts']}
    canonical=[]
    for row in input_batch['rows']:
        b=effective_basis(row);f=facts[row['id']]
        canonical.append({'parent_row_id':row['id'],'business_basis':deepcopy(b),'review':deepcopy(f),'identity':deepcopy(row['identity'])})
    source_file=Path(root)/('confirmed-calculation-'+key(canonical)+'.json')
    if not source_file.exists():save(source_file,{'schema':'explicit-confirmed-calculation-basis/1','mode':svc.owner['mode'],'records':canonical,'professional_approval':False,'formal_output':False})
    source_sha=digest(source_file);rows=[]
    for index,old in enumerate(input_batch['rows'],2):
        f=facts[old['id']];v=f['values'];b=effective_basis(old)
        # New canonical input records are distinct from Japanese observations.
        # Never change old.raw/authority/source or their immutable amount ledger.
        source={'path':str(source_file.resolve()),'sha256':source_sha,'sheet':'confirmed-calculation-records','row':index,'stage':3,'kind':'explicit_confirmed_canonical_basis',
            'cells':{'qty':{'cell':'quantity','value':b['quantity']},'amount':{'cell':'amount','value':b['amount']}}}
        raw={'code':old['identity']['code'],'ja':old['identity']['japanese_name'],'carton':old['logistics']['carton_raw'],'origin':old['logistics']['origin'],
            'qty':b['quantity'],'amount':b['amount'],'price':finite(Fraction(b['amount'])/Fraction(b['quantity']))}
        row=new_row(source,raw,currency='JPY',quantity_unit=b['quantity_unit'],authority_stage=3,authority_status='business_confirmed_stage3',amount_basis='explicit_calculation_review')
        for name in ['identity','product','packaging','business_amount','reviews']:row[name]=deepcopy(old[name])
        row['product']['customs_name']=v.get('public_name') or ''
        row['material']['candidate']=v.get('material_reference') or ''
        row['original_pairing']={'business':baseline['mapping'][f['parent_id']]['review_row'],'declaration':baseline['mapping'][f['parent_id']]['review_row']}
        row['operations_preserved']={name:{'literal_value':value} for name,value in {'specification':row['identity']['specification'],
            'yd':row['product']['yd'] or None,'remarks':None,'brand':v.get('brand'),'blind':None,'label':None,'size':None,'spec':None}.items()}
        row['operational_execution']={'price':None,'amount':None,'fields':{}}
        row['operational_tax_input']={'rate':v.get('duty_rate'),'vat_rate':v.get('vat_rate'),'reference':True,'allocation':False,
            'basis':v.get('tax_reference') or '未提供税费来源；留空不默认税率'}
        row['operations_provenance']={'业务确认金额JPY':{'path':review['upload'],'sheet':'计算审核','row':row['original_pairing']['business'],'cell':'L'+str(row['original_pairing']['business'])}}
        row['loop_lineage']={'parent_row_id':old['id'],'raw_japanese_source':deepcopy(old['source']),'raw_japanese_observation':deepcopy(old['arrival']),
            'calculation_confirmation':review['preview_id'] if 'preview_id' in review else svc.owner['review_preview'],'mode':svc.owner['mode'],'professional_approval':False}
        row['confirmed_input']={'formal_missing':['专业申报归类/材质/税率及正式放行仍需独立审核']}
        rate=v.get('duty_rate');vat=v.get('vat_rate')
        if rate not in (None,'') and vat not in (None,''):
            row['tax']={'context':context(row),'duty_rate':str(rate),'vat_rate':str(vat),'tax_unit_price':raw['price'],'tax_unit':b['quantity_unit'],
                'formula_version':'historical-box-v1','source':v['tax_reference'],'classification':'controlled_reference_only','effective_date':'unverified'}
            row['reviews']['tax']={'confirmed_by':'controlled_calculation_reference_unverified','confirmed_at':'in_scoped_calculation_receipt','reference':v['tax_reference'],'professional_approval':False}
        else:row['tax']=None;row['reviews']['tax']=None
        rows.append(row)
    batch=new_batch(rows,[*input_batch['sources'],{'path':str(source_file.resolve()),'sha256':source_sha,'kind':'confirmed_canonical_basis'}])
    batch['execution_mode']='synthetic_technical_test' if svc.owner['mode']=='synthetic' else 'controlled_draft_only'
    batch['input_mode']='explicit_calculation_review';batch['product_data_policy']='single-person-v1'
    update=get(parent.root,review['update_ref']);weightfile=update['source']['path'];weights=read_weights(weightfile,'重さとサイズ')
    batch['weight_data']=weights;batch['logistics_check']=reconcile_logistics(rows,weights)
    from arrival_core import _p0_frozen as p0
    from arrival_core.operations_adapter import original_literal
    wb=p0.Book(Path(weightfile).read_bytes(),'actual-update-weights.xlsx');ws=next(s for s in wb.sheets if s.name=='重さとサイズ')
    snapshot={'sheet':ws.name,'rows':[[original_literal(ws.v(n,c)) for c in 'ABCDEFGH'] for n in range(1,max(ws.rows)+1)]}
    batch['operations_delivery_policy']={'version':'rounded-colored-v1','preserve_business_amount':True,'formal_output':False,'weight_snapshot':snapshot}
    batch['controlled_calculation_mode']=svc.owner['mode'];validate(batch)
    from arrival_core import colored_tables
    if svc.owner['mode']=='synthetic':
        import importlib.util,sys
        name='arrival_core._loop_synthetic_colored'
        if name not in sys.modules:
            spec=importlib.util.spec_from_file_location(name,colored_tables.__file__);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
            module.WARNING='SYNTHETIC 隔离技术测试，非真实业务结果；受控草稿，不得外发或用于申报'
        renderer=sys.modules[name]
    else:renderer=colored_tables
    destination=Path(destination)
    if destination.exists():
        comparison=renderer.verify(batch,destination);result={'directory':str(destination),'comparison':comparison,'files':[str(destination/f) for f in renderer.FILES.values()],'replayed':True}
    else:result=renderer.render(batch,destination)
    save(Path(root)/('render-batch-'+key(batch)+'.json'),batch)
    return {**result,'mode':svc.owner['mode'],'rows':len(rows),'business_confirmations_verified':svc.owner['mode']=='business',
        'synthetic_confirmation_only':svc.owner['mode']=='synthetic','professional_approvals_created':0,'formal_output':False}
