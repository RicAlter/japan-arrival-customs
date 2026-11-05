"""Execute frozen A03 transaction methods in an isolated module namespace.

The original a_confirm.model/service globals are never replaced. Only this
candidate supplies a basic-only model seam; CAS/receipts/compare remain A02/A03.
"""
from pathlib import Path
from copy import deepcopy
import importlib.util,sys,types
from . import __version__,model
from .support import ROOT,REPO,Rejected,bootstrap,code_snapshot,load,save,key,put,digest,check_hashes
bootstrap()
from a_confirm import support as frozen_support,locking as frozen_locking

NAME='stage1._frozen_a03'
if NAME+'.service' not in sys.modules:
    package=types.ModuleType(NAME);package.__path__=[];package.__version__=__version__
    sys.modules[NAME]=package
    sys.modules[NAME+'.support']=frozen_support;sys.modules[NAME+'.locking']=frozen_locking;sys.modules[NAME+'.model']=model
    spec=importlib.util.spec_from_file_location(NAME+'.service',REPO/'a03-confirmation/a_confirm/service.py')
    frozen=importlib.util.module_from_spec(spec);sys.modules[spec.name]=frozen;spec.loader.exec_module(frozen)
Base=sys.modules[NAME+'.service'].Service

class Service(Base):
    def __init__(self,root):
        bootstrap();super().__init__(root)
        lock=self.root/'stage1-code-lock.json'
        if lock.is_file():check_hashes(load(lock)['files'])
        else:save(lock,{'schema':'stage1-candidate-code/1','files':code_snapshot()})
    def _code(self):return {**super()._code(),**code_snapshot()}
    def register(self,context_file):
        from native_copy.service import registered_copy
        context=load(context_file);reg=registered_copy(context['current_output'])
        if reg.get('stage1_policy',{}).get('phase')!='basic_only':raise Rejected('仅登记第一阶段候选，不能接管旧业务版本')
        return super().register(context_file)
    def read_current(self,batch_id):
        view=super().read_current(batch_id);byrow={}
        for f in view['fields'].values():byrow.setdefault(f['row_id'],{})[f['field']]=f
        price_units=[]
        for rid,fields in byrow.items():
            price=fields.get('purchase_unit_price');unit=fields.get('purchase_price_unit');qty=fields.get('purchase_quantity')
            proof=price.get('evidence',{}) if price else {}
            valid=bool(price and unit and price['confirmed'] and unit['confirmed'] and model.unit_resolved(unit['value']['value'])
                and price.get('identity_context_hash')==model.identity_context(view['fields'],rid)
                and proof.get('unit')==unit['value']['value'] and proof.get('unit_target')==unit['target'])
            price_units.append({'row_id':rid,'original_price':price['value']['value'] if price else None,
                'unit':unit['value']['value'] if unit else None,'original_unit_confirmed':valid,
                'minimum_unit_price':price['value']['value'] if valid and model.minimum_unit(unit['value']['value']) else None,
                'minimum_unit_price_confirmed':bool(valid and model.minimum_unit(unit['value']['value'])),
                'source_metadata':deepcopy(price.get('stage1_source_metadata',{})) if price else {},
                'purchase_quantity':qty['value']['value'] if qty else None,'arrival_qty_substituted':False})
        view.update(stage='basic_only',pricing_deferred=True,box_confirmation_required=False,
            price_difference_executed=False,box_inference_executed=False,purchase_unit_contexts=price_units,
            phase2_implemented=False,phase3_implemented=False,formal_output=False,can_enter_b=False)
        return view
    def preview_return(self,batch_id,uploaded,**kwargs):
        if kwargs.get('box_corrections'):raise Rejected('第一阶段不收盒规更正或计算确认')
        base,_,_,_,_,_=self._state(batch_id)
        from a_confirm.support import get
        reg=get(self.root,get(self.root,base['a03']['baseline_ref'])['registration_ref'])
        from native_copy.ooxml import parts
        if 'stage1_version' not in reg:raise Rejected('缺少第一阶段发出版本标记')
        package=parts(Path(uploaded).read_bytes())
        token=reg['stage1_version']['value']
        import xml.etree.ElementTree as ET
        try:
            props=ET.fromstring(package['docProps/custom.xml'])
            matches=[e for e in props if e.get('name')==reg['stage1_version']['property']]
            actual=list(matches[0])[0].text if len(matches)==1 and len(matches[0])==1 else None
        except (KeyError,ET.ParseError):actual=None
        if actual!=token:raise Rejected('不是当前第一阶段发出副本，拒绝旧版覆盖')
        result=super().preview_return(batch_id,uploaded,**kwargs)
        pending=False
        for proposal in result['proposals'].values():
            name=proposal['field'];raw=proposal['after']['value']
            if name not in model.ALLOWED:raise Rejected('第一阶段不允许改原始事实或盒规：'+proposal['target'])
            reason=None
            if name=='purchase_quantity' and (model.number(raw) is None or model.number(raw)<0):reason='采购数量无效，需核对来源/单位，不能用到货Qty兜底'
            if name in {'purchase_price_unit','purchase_quantity_unit'} and not model.unit_resolved(raw):reason='采购单位仍未明确'
            if reason:
                proposal['needs_further_confirmation']=True;proposal['reasons'].append(reason);pending=True
        if pending:
            body={k:v for k,v in result.items() if k not in {'preview_id','message'}}
            body['needs_further_confirmation_cells']=sum(p['needs_further_confirmation'] for p in body['proposals'].values())
            result={**body,'preview_id':put(self.root,body),'message':f'修改{body["modified_cells"]}格，仅预览，未确认保存'}
        return result
    def prepare_confirmation(self,preview_id,selection):
        if not isinstance(selection,dict) or set(selection)!={'save_changes','confirm_fields','adopt_candidates','evidence'} or not isinstance(selection['evidence'],dict):
            raise Rejected('须明确保存、确认和候选采用范围')
        selection=deepcopy(selection);preview=self._preview(preview_id)
        _,baseline,_,_,fields,_=self._state(preview['batch_id'])
        confirming=set(selection.get('confirm_fields',[]))|set(selection.get('adopt_candidates',[]))
        for target in confirming:
            f=fields.get(target)
            if not f or f['field'] not in model.ALLOWED:raise Rejected('不在第一阶段可确认字段范围')
            if f['field'] not in model.UNIT_FIELDS:continue
            unit=next(x for x in fields.values() if x['row_id']==f['row_id'] and x['field']==model.UNIT_FIELDS[f['field']])
            proposed=preview['proposals'].get(unit['target'])
            unit_value=proposed['after']['value'] if proposed and unit['target'] in selection['save_changes'] else unit['value']['value']
            if not unit['confirmed'] and unit['target'] not in confirming:raise Rejected('采购值须连同明确单位确认；未知单位可以先保存待核')
            old=selection['evidence'].get(target,{})
            if old and set(old)!={'source_ref'}:raise Rejected('第一阶段采购确认只接收真实来源说明，由宿主绑定范围和单位')
            source_ref=old.get('source_ref') or f'本次明确确认范围；回传SHA:{preview["upload_sha256"]}；{target}；原始来源保留'
            selection['evidence'][target]={'source_ref':source_ref,'currency':'JPY','unit':unit_value,'unit_target':unit['target'],
                'unit_confirmed_with_scope':True,'kind':'stage1_explicit_business_confirmation'}
        return super().prepare_confirmation(preview_id,selection)
