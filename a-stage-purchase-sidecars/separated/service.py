"""Execute frozen A03 methods with this layout's basic-only model seam."""
from pathlib import Path
from copy import deepcopy
import importlib.util,sys,types,xml.etree.ElementTree as ET
from . import __version__,REPO,model
from .support import bootstrap,code_snapshot,load,save,check_hashes,Rejected
bootstrap()
from a_confirm import support as frozen_support,locking as frozen_locking
NAME='separated._frozen_a03'
if NAME+'.service' not in sys.modules:
    package=types.ModuleType(NAME);package.__path__=[];package.__version__=__version__
    sys.modules[NAME]=package;sys.modules[NAME+'.support']=frozen_support
    sys.modules[NAME+'.locking']=frozen_locking;sys.modules[NAME+'.model']=model
    spec=importlib.util.spec_from_file_location(NAME+'.service',REPO/'a03-confirmation/a_confirm/service.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
Base=sys.modules[NAME+'.service'].Service
class Service(Base):
    def __init__(self,root):
        bootstrap();super().__init__(root);lock=self.root/'separated-code-lock.json'
        if lock.exists():check_hashes(load(lock))
        else:save(lock,code_snapshot())
    def _code(self):return {**super()._code(),**code_snapshot()}
    def register(self,context_file):
        from native_copy.service import registered_copy
        reg=registered_copy(load(context_file)['current_output'])
        if reg.get('stage1_policy',{}).get('purchase_columns_location')!='separate_query':raise Rejected('不是采购分表候选')
        return super().register(context_file)
    def read_current(self,batch_id):
        view=super().read_current(batch_id);contexts=[]
        for f in view['fields'].values():
            if f['field']!='purchase_unit_price':continue
            proof=f.get('evidence',{});valid=f['confirmed'] and model.price_proof(proof)
            contexts.append({'row_id':f['row_id'],'unit':proof.get('unit'),'original_unit_confirmed':bool(valid),
                'minimum_unit_price_confirmed':bool(valid and model.old.minimum_unit(proof['unit'])),
                'minimum_unit_price':f['value']['value'] if valid and model.old.minimum_unit(proof['unit']) else None,
                'source_metadata':deepcopy(f.get('stage1_source_metadata',{}))})
        view.update(stage='basic_only',purchase_columns_location='separate_query',pricing_deferred=True,
            box_confirmation_required=False,box_inference_executed=False,price_difference_executed=False,
            purchase_unit_contexts=contexts)
        return view
    def preview_return(self,batch_id,uploaded,**kwargs):
        if kwargs.get('box_corrections'):raise Rejected('第一阶段不处理盒规')
        from native_copy.ooxml import parts
        from a_confirm.support import get
        batch=self.store.load(batch_id);base=get(self.root,batch['a03']['baseline_ref']);reg=get(self.root,base['registration_ref'])
        package=parts(Path(uploaded).read_bytes());root=ET.fromstring(package.get('docProps/custom.xml',b'<empty/>'))
        matches=[e for e in root if e.get('name')==reg['stage1_version']['property']]
        actual=list(matches[0])[0].text if len(matches)==1 and len(matches[0])==1 else None
        if actual!=reg['stage1_version']['value']:raise Rejected('不是本次分表后的发出底稿，拒绝旧版本/查询表回传')
        result=super().preview_return(batch_id,uploaded,**kwargs)
        if any(p['field'] not in model.ALLOWED for p in result['proposals'].values()):raise Rejected('不是主表可编辑基础字段')
        return result
    def prepare_confirmation(self,preview_id,selection):
        if not isinstance(selection,dict) or set(selection)!={'save_changes','confirm_fields','adopt_candidates','evidence'} or not isinstance(selection['evidence'],dict):raise Rejected('须明确保存、确认和采用范围')
        selection=deepcopy(selection);p=self._preview(preview_id);fields=self._state(p['batch_id'])[4]
        for target in set(selection['confirm_fields'])|set(selection['adopt_candidates']):
            if target not in fields or fields[target]['field'] not in model.ALLOWED:raise Rejected('不在主表确认范围')
            if fields[target]['field']!='purchase_unit_price':continue
            proof=selection['evidence'].get(target,{})
            if not isinstance(proof,dict) or set(proof)!={'source_ref','unit'}:raise Rejected('采购单位移至独立查询，确认采购价时仍须提供明确来源及计价单位；否则先保存待核')
            selection['evidence'][target]={**proof,'currency':'JPY','kind':'stage1_explicit_business_confirmation'}
        return super().prepare_confirmation(preview_id,selection)
