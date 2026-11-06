"""B00 transaction/A04 preflight adapters, no replacement calculation engine."""
from pathlib import Path
from copy import deepcopy
from fractions import Fraction
import sys,importlib.util
from .support import bootstrap,REPO,load,save,key,digest,put,get,path,Rejected
bootstrap();sys.path.insert(0,str(REPO/'b00-business-basis'));sys.path.insert(0,str(REPO/'a04-calculation-input'))
from . import calc_model as model
from .updates import Service as Updates
from . import review
from arrival_core.core import new_row,new_batch,context,validate
from arrival_core.storage import Store
from arrival_core.operations_adapter import finite
from a_input.bridge import project as a04_project,dependencies,confirmed

NAME='loop._frozen_basis'
if NAME not in sys.modules:
    spec=importlib.util.spec_from_file_location(NAME,REPO/'b00-business-basis/basis/service.py')
    frozen=importlib.util.module_from_spec(spec);sys.modules[NAME]=frozen;spec.loader.exec_module(frozen)
    frozen.model=model  # Private module copy; the original basis.service globals stay intact.
else:frozen=sys.modules[NAME]
Base=frozen.Service

class Service(Base):
    def __init__(self,root):
        bootstrap();dependencies();self.root=Path(root).resolve(strict=True);self.owner=load(self.root/'compute-owner.json')
        if self.owner.get('schema')!='loop-compute-owner/1':raise Rejected('不是独立计算确认目录')
        parent=Updates(self.owner['loop_root'])
        if parent.owner['mode']!=self.owner['mode'] or get(parent.root,self.owner['review_preview'])['mode']!=self.owner['mode']:raise Rejected('计算目录与上游业务/合成模式不一致')
        self.store=Store(path(self.root/'batches'));self.bid=self.owner['batch_id']
    @classmethod
    def create(cls,loop_root,preview_id,destination):
        parent=Updates(loop_root);p=get(parent.root,preview_id)
        if p.get('schema')!='loop-calculation-preview/1' or p['mode']!=parent.owner['mode']:raise Rejected('计算审核来源/模式不符')
        if p['blocked_rows'] or p['new_identity_rows_pending'] or not p['weights_unchanged'] or not p['actual_price_qualified'] or not p.get('source_totals_consistent',True) or not p.get('price_basis_reference'):raise Rejected('计算审核仍有缺项/非整数/价格口径可比依据/来源总计或箱重待核，不生成不完整双表')
        if key(parent.store.load(parent.bid))!=p['base_hash']:raise Rejected('计算审核预览已过期')
        destination=Path(destination).resolve()
        if destination.exists():raise Rejected('计算确认须使用新目录，旧版本不覆盖')
        export=get(parent.root,p['export_id']);plan=export['plan'];destination.mkdir(parents=True)
        byparent={r['parent_id']:r for r in plan['rows']};fields={};rows=[];mapping={}
        source_ref=get(parent.root,p['update_ref'])['source'];raw_source=source_ref['path']
        for i,fact in enumerate(p['facts'],5):
            source=deepcopy(fact['raw']['source']);raw=fact['raw'];base=byparent[fact['parent_id']]
            values={'code':raw['code'],'ja':raw['ja'],'carton':raw['carton'],'origin':raw['origin'],'qty':raw['quantity'],'price':raw['price'],'amount':raw['amount']}
            row=new_row(source,values,currency='JPY',quantity_unit='',authority_stage=1,authority_status='preliminary_from_raw_invoice',amount_basis='raw_invoice_subtotal')
            rows.append(row);rid=row['id'];mapping[fact['parent_id']]={'row_id':rid,'review_row':i}
            for name,col in [('product_code','C'),('internal_name','D'),('specification','E'),('purchase_unit_price','F'),('category','U'),('channel','_channel'),('yd','_yd')]:
                original=deepcopy(base['basic_fields'].get(name))
                if original is None:continue
                target=review.SHEET+'!'+col+str(i);original.update(row_id=rid,target=target,sheet=review.SHEET,cell=col+str(i))
                original['inherited_from']={'parent_target':base['basic_fields'][name]['target'],'confirmation':deepcopy(base['basic_fields'][name].get('confirmation'))}
                fields[target]=original
            target=review.SHEET+'!AH'+str(i)
            fields[target]={'row_id':rid,'target':target,'sheet':review.SHEET,'cell':'AH'+str(i),'field':'pieces_per_box',
                'value':model.value('blank',None),'status':'candidate','confirmed':False,'sources':[],
                'working_formula':review.FORMULAS['AH'](i),'professional_approval':False}
        basis={'status':'loop_explicit_actual_price_and_unit_basis','source':source_ref,'review':p['upload_sha256'],'price_comparability_reference':p['price_basis_reference']}
        for f in fields.values():
            if f.get('confirmed'):
                f['identity_context_hash']=model.identity_context(fields,f['row_id'])
                if f['field']=='purchase_unit_price':
                    f['original_purchase_evidence']=deepcopy(f.get('evidence',{}));f['evidence']={**f.get('evidence',{}),'price_basis_hash':key(basis),'currency':'JPY','source_kind':'explicit_purchase_price_confirmation'}
        baseline={'schema':'loop-compute-baseline/1','fields':fields,'price_basis':basis,'mapping':mapping,'review_preview':preview_id,
            'plan':plan,'source_file':raw_source,'batch_id':None}
        sources=[{'path':raw_source,'sha256':source_ref['sha256']},{'path':p['upload'],'sha256':p['upload_sha256'],'kind':'explicit_calculation_review'}]
        batch=new_batch(rows,sources);baseline['batch_id']=batch['id'];ref=put(destination,baseline)
        batch['execution_mode']='synthetic_technical_test' if p['mode']=='synthetic' else 'preflight_only'
        batch['a03']={'schema':'a-original-state/1','baseline_ref':ref,'overrides':{},'receipts':{},'version_id':key({'review':preview_id}),
            'parent_hash':None,'can_enter_b':False,'formal_output':False,'downstream':{'recompute_required':True}}
        source={'profile_id':'loop-calculation-view-v1'};_,pricing=model.recheck(source,None,baseline,batch['a03']);batch['a03']['pricing_ref']=put(destination,pricing)
        Store(path(destination/'batches')).save(batch)
        save(destination/'compute-owner.json',{'schema':'loop-compute-owner/1','loop_root':str(parent.root),'review_preview':preview_id,'mode':p['mode'],
            'export_id':p['export_id'],'review_reference':p['reference'],'price_basis_reference':p['price_basis_reference'],'loop_parent_hash':p['base_hash'],'batch_id':batch['id']})
        return cls(destination)
    def _baseline(self,batch):
        b=get(self.root,batch['a03']['baseline_ref']);return b,{'profile_id':'loop-calculation-view-v1'},None
    def _state(self,batch_id):
        b=self.store.load(batch_id);baseline,source,sheet=self._baseline(b);fields,pricing=model.recheck(source,sheet,baseline,b['a03'])
        if key(pricing)!=b['a03']['pricing_ref']:raise Rejected('当前计算确认视图与保存版本不一致')
        return b,baseline,source,sheet,fields,pricing
    def read_current(self,batch_id):
        batch,baseline,_,_,fields,pricing=self._state(batch_id)
        for f in fields.values():
            if f['field'] in {'pieces_per_box','purchase_unit_price'}:f['adopted_basis_current']=bool(f['confirmed'] and f.get('identity_context_hash')==model.identity_context(fields,f['row_id']))
        return {'batch_id':batch_id,'fields':fields,'calculated_cells':pricing['rows'],'pricing_counts':pricing['counts'],
            'current_hash':key(batch),'a_version':batch['a03']['version_id'],'price_basis_hash':key(baseline['price_basis']),'formal_output':False}
    def preview_basis(self,batch_id,*,business_file,groups):
        parent=Updates(self.owner['loop_root']);parent_batch=parent.store.load(parent.bid)
        if key(parent_batch)!=self.owner['loop_parent_hash']:raise Rejected('基础资料/日方版本已变化，计算审核失效')
        fresh=review.preview_return(parent.root,self.owner['export_id'],business_file,reference=self.owner['review_reference'],price_basis_reference=self.owner['price_basis_reference'])
        if fresh['preview_id']!=self.owner['review_preview']:raise Rejected('回传计算审核或重新计算结果变化')
        batch,baseline,_,_,fields,_=self._state(batch_id);facts={baseline['mapping'][f['parent_id']]['row_id']:f for f in fresh['facts']}
        selected=set();items={};excluded={};rowmap={r['id']:r for r in batch['rows']}
        for group in groups:
            if set(group)!={'row_ids','business_unit','declaration_unit','declaration_factor','reference','exceptions'}:raise Rejected('计算确认组不完整')
            ids=group['row_ids']
            if not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(rowmap) or selected&set(ids):raise Rejected('计算确认范围重复/越界')
            if group['business_unit']!='Qty（原表计价口径）' or group['declaration_unit']!='单个' or not group['reference']:raise Rejected('必须明确本批原Qty口径、最小申报单位及依据')
            selected.update(ids)
            for rid in ids:
                f=facts[rid]
                if rid in group['exceptions']:excluded[rid]=group['exceptions'][rid];continue
                if f['errors'] or Fraction(group['declaration_factor'])!=Fraction(f['factor']):excluded[rid]='重新计算未通过或换算系数不符';continue
                n=baseline['mapping'][f['parent_id']]['review_row'];proof={'path':str(business_file),'sha256':digest(Path(business_file)),'sheet':review.SHEET}
                basis={'quantity':f['quantity'],'amount':f['amount'],'boxes':f['boxes'],'row':n,'sheet':review.SHEET,
                    'fields':{name:{'value':v,'proof':{**proof,'cell':c+str(n)}} for name,c,v in [('业务确认数量','J',f['quantity']),('业务确认金额JPY','L',f['amount'])]}}
                ht=review.SHEET+'!AH'+str(n)
                items[rid]={'basis':basis,'h':f['physical_pieces_per_box'],'h_target':ht,'internal_ratio':str(Fraction(f['quantity'])/Fraction(f['boxes'])),
                    'declaration_factor':f['factor'],'business_unit':group['business_unit'],'declaration_unit':group['declaration_unit'],'reference':f['conversion_reference']+'；'+group['reference'],
                    'same_single_quantity':Fraction(f['factor'])==1,'single_quantity_source':{'derived':'明确确认的原Qty × 换算倍数','independent_observation':False,'review':proof},
                    'a_identity_hash':model.identity_context(fields,rid)}
        body={'schema':'b00-scoped-basis-plan/1','batch_id':batch_id,'base_hash':key(batch),'base_a_version':batch['a03']['version_id'],
            'source':{'path':str(business_file),'sha256':digest(Path(business_file)),'role':'explicit_new_workflow_calculation_review'},'groups':deepcopy(groups),
            'items':items,'excluded':excluded,'unselected_rows':sorted(set(rowmap)-selected),'formal_output':False,'professional_approval':False}
        pid=put(self.root,body);return {**body,'plan_id':pid,'confirmation_hash':pid}
    def default_groups(self):
        b,baseline,_,_,_,_=self._state(self.bid);parent=Updates(self.owner['loop_root']);p=get(parent.root,self.owner['review_preview']);groups={}
        for f in p['facts']:
            rid=baseline['mapping'][f['parent_id']]['row_id'];groups.setdefault(f['factor'],[]).append(rid)
        return [{'row_ids':ids,'business_unit':'Qty（原表计价口径）','declaration_unit':'单个','declaration_factor':factor,
            'reference':self.owner['review_reference'],'exceptions':{}} for factor,ids in groups.items()]
    def commit_basis(self,plan_id,**kwargs):
        p=get(self.root,plan_id)
        if p['excluded'] or p['unselected_rows']:raise Rejected('整批计算确认不能遗漏例外或未选行')
        return super().commit_basis(plan_id,**kwargs)

class Bridge:
    def __init__(self,root):self.service=Service(root)
    def prepare(self,batch_id):
        svc=self.service;view=svc.read_current(batch_id);batch=svc.store.load(batch_id)
        parent=Updates(svc.owner['loop_root'])
        if key(parent.store.load(parent.bid))!=svc.owner['loop_parent_hash']:raise Rejected('上游确认或日方版本已变化')
        parent.active()
        result=a04_project(view,batch)
        for item in result['row_checks']:
            item['legacy_100jpy_role_not_applied']=True
            item['price_reference_pending']=item['price_check']['status']!='new_roles_and_conversion_confirmed'
        result['input_fingerprint']=key(result);return result
    def current_input(self,prepared):
        body={k:v for k,v in prepared.items() if k!='input_fingerprint'}
        if key(body)!=prepared.get('input_fingerprint'):raise Rejected('A04计算输入摘要不一致')
        fresh=self.prepare(prepared['batch_id'])
        if fresh!=prepared:raise Rejected('计算审核或基础版本已变化')
        parent=Updates(self.service.owner['loop_root']);pointer=parent.root/'current-computation.json'
        if pointer.exists():
            current=load(pointer)
            if current['review_preview']!=self.service.owner['review_preview'] or Path(current['compute_root']).resolve()!=self.service.root:raise Rejected('该计算确认已被新版本取代，旧输入不得再次交付')
        if not fresh['can_calculate_entire_batch']:raise Rejected('整批依据未确认，禁止生成半份/部分双表')
        return deepcopy(fresh['rc5_input'])
frozen.Bridge=Bridge
