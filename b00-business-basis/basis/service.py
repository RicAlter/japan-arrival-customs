from copy import deepcopy
from pathlib import Path
from fractions import Fraction
import sys

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'a04-calculation-input'))
from a_input.bridge import Bridge, dependencies, confirmed
from a_confirm.service import Service as A03
from a_confirm.support import Rejected, key, digest, put, get, load, path
from a_confirm.locking import writer
from a_confirm import model


def text(value):
    from arrival_core import _p0_frozen as p0
    return p0.text(value)


def business_source(file):
    """Only the stage3 business domain; never read declaration/final-price columns."""
    from arrival_core import _p0_frozen as p0
    from arrival_core.operations_adapter import configs, locate, value
    file=Path(file).resolve(strict=True);sha=digest(file)
    book=p0.Book(file.read_bytes(),str(file));sheet=book.sheets[0]
    config=next((c for c in configs() if c['role']=='business' and locate(sheet,c)),None)
    if config:
        cols=locate(sheet,config)
        selected={k:cols[k] for k in ['箱号','商品编码','日文品名','业务确认数量','业务单价','业务确认金额JPY']}
        boxes=cols.get('来源盒数');spec=config.get('preserve_columns',{}).get('specification')
    else:
        from native22.profiles import inspect_source
        data=inspect_source(file);sheet=data['sheet'];cols=data.get('columns')
        if data['profile_id']=='kmt-native-22-v1':
            raise Rejected('22列原表Qty/Subtotal仍为到货观察，须提供独立第3步业务金额依据')
        if data['profile_id'] not in ('kmt-native-16-v1','kmt-stage3-native-v1'):
            raise Rejected('本批依据读取仅支持已验证第3步业务格式')
        # Existing native profiles carry source-cell names, not fixed ordinals.
        cells=data['rows'][0]['source']['cells']
        selected={k:cells[r]['cell'].rstrip('0123456789') for k,r in
                  [('箱号','carton'),('商品编码','code'),('日文品名','ja'),('业务确认数量','qty'),('业务单价','price'),('业务确认金额JPY','amount')]}
        boxes=None;spec=data['targets'].get('specification')
    rows={};carry=''
    for n in sorted(sheet.rows):
        if n<2:continue
        if text(sheet.v(n,selected['箱号'])):carry=text(sheet.v(n,selected['箱号']))
        if not text(sheet.v(n,selected['商品编码'])) and not text(sheet.v(n,selected['日文品名'])):continue
        fields={}
        for name,col in selected.items():
            if name=='箱号' and not text(sheet.v(n,col)):
                v=carry;proof={'path':str(file),'sha256':sha,'sheet':sheet.name,'cell':col+str(n),'inherited':True}
            elif config:
                v,proof=value(book,sheet,n,name,selected,config)
            else:
                v=text(sheet.v(n,col));proof={'path':str(file),'sha256':sha,'sheet':sheet.name,'cell':col+str(n),'formula':sheet.f(n,col)}
                if proof['formula']:
                    qcol,pcol=selected['业务确认数量'],selected['业务单价']
                    if name!='业务确认金额JPY' or proof['formula'].replace('$','').replace(' ','') not in ('='+qcol+str(n)+'*'+pcol+str(n),'='+pcol+str(n)+'*'+qcol+str(n)):
                        raise Rejected('业务来源存在未验证公式')
            fields[name]={'value':v,'proof':proof}
        from arrival_core.core import positive,decimal
        q=positive(fields['业务确认数量']['value']);p=decimal(fields['业务单价']['value']);a=decimal(fields['业务确认金额JPY']['value'])
        if a<0 or p<0 or Fraction(q)*Fraction(p)!=Fraction(a):raise Rejected('第3步业务单价×数量与金额不一致')
        b=text(sheet.v(n,boxes)) if boxes else None
        if boxes and sheet.f(n,boxes):raise Rejected('来源盒数必须为独立数值')
        rows[n]={'carton':carry,'code':fields['商品编码']['value'],'ja':fields['日文品名']['value'],
                 'spec':text(sheet.v(n,spec)) if spec else '', 'quantity':str(q),'amount':str(a),'boxes':b,
                 'fields':fields,'row':n,'sheet':sheet.name}
    if not rows or digest(file)!=sha:raise Rejected('业务来源为空或读取期间变化')
    return {'path':str(file),'sha256':sha,'role':'stage3_business_values_only','rows':rows}


class Service(A03):
    def __init__(self,root):
        dependencies();super().__init__(root)
        if not (self.root/'b00-owner.json').is_file():
            raise Rejected('B-00仅写入显式建立的隔离副本，不能写旧验收目录')

    @staticmethod
    def fork(existing, destination):
        import shutil
        existing=Path(existing).resolve(strict=True);destination=Path(destination).resolve()
        A03(existing)
        if destination.exists() or destination.is_relative_to(existing) or existing.is_relative_to(destination):
            raise Rejected('须使用新的隔离保存副本目录')
        shutil.copytree(existing,destination)
        from arrival_core.storage import atomic_json
        atomic_json(destination/'b00-owner.json',{'schema':'b00-isolated-writer/1','parent':str(existing)})
        return Service(destination)

    def preview_basis(self,batch_id,*,business_file,groups):
        from arrival_core.core import positive
        from arrival_core.operations_adapter import UNITS
        batch,baseline,source,sheet,fields,pricing=self._state(batch_id)
        view=self.read_current(batch_id);business=business_source(business_file)
        rowmap={r['id']:r for r in batch['rows']};items={};excluded={};seen=set()
        byrow={}
        for f in fields.values():byrow.setdefault(f['row_id'],{})[f['field']]=f
        if not isinstance(groups,list) or not groups:raise Rejected('须指定有依据的具体规则范围')
        for group in groups:
            required={'row_ids','business_unit','declaration_unit','reference','exceptions'}
            if set(group) not in (required,required|{'declaration_factor'}):raise Rejected('确认组字段不完整或未知')
            ids=group['row_ids'];exceptions=group['exceptions']
            if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(rowmap):raise Rejected('确认范围必须为本批明确且不重复的行ID')
            if seen & set(ids):raise Rejected('确认组范围重复')
            seen.update(ids)
            if not isinstance(exceptions,dict) or not set(exceptions)<=set(ids) or any(not isinstance(v,str) or not v.strip() for v in exceptions.values()):raise Rejected('例外须有明确行及原因')
            if not isinstance(group['reference'],str) or not group['reference'].strip():raise Rejected('规则依据必填')
            unit=group['business_unit'];du=group['declaration_unit']
            factor=positive(group.get('declaration_factor','1'))
            if unit not in UNITS|{'Qty（原表计价口径）'} or du not in UNITS|{'单个'}:raise Rejected('实际单位未知，不能统一确认')
            for rid in ids:
                if rid in exceptions:excluded[rid]=exceptions[rid];continue
                original=rowmap[rid];n=original['source']['row'];b=business['rows'].get(n)
                if not b:excluded[rid]='业务依据未找到同原行';continue
                # Match the frozen physical row AND complete identity context.
                raw=original['raw'];sf=byrow.get(rid,{}).get('specification')
                spec=(sf['value']['value'] or '') if sf and confirmed(sf,fields) else text(raw.get('variant'))
                if (text(raw.get('code'))!=b['code'] or text(raw.get('ja'))!=b['ja']
                        or text(raw.get('carton'))!=b['carton'] or spec!=b['spec']):
                    excluded[rid]='原行身份/规格/箱号不一致，禁止猜改码关联';continue
                if not b['boxes']:
                    excluded[rid]='业务来源缺少独立盒数';continue
                try:
                    qty=positive(b['quantity']);boxes=positive(b['boxes']);internal_ratio=Fraction(qty)/Fraction(boxes)
                except ValueError:
                    excluded[rid]='数量或盒数非正数，例外待核';continue
                cell=original['source']['cells'].get('single_qty')
                # Current schema can safely reuse no-conversion historical scope.
                # Nontrivial mixed-Qty conversion is retained for separate review.
                if cell is None:
                    if unit!='件' or du not in ('件','个','单个'):
                        excluded[rid]='缺少独立单个数量，不能解释混合Qty';continue
                    single=qty
                else:
                    if cell.get('formula'):
                        excluded[rid]='原单个数量为公式，需独立依据';continue
                    single=positive(cell['value'])
                if Fraction(single)!=Fraction(qty)*Fraction(factor):
                    excluded[rid]='单个数与业务Qty不符合本组明确换算系数，例外需单独依据';continue
                h=Fraction(single)/Fraction(boxes)
                if h.denominator!=1 or h<=0:
                    excluded[rid]='数量/盒数不能确认正整数每盒件数';continue
                hf=byrow.get(rid,{}).get('pieces_per_box')
                if hf is None:excluded[rid]='当前A格式没有H每盒件数登记';continue
                items[rid]={'basis':b,'h':str(h.numerator),'h_target':hf['target'],
                            'internal_ratio':str(internal_ratio),'declaration_factor':str(factor),
                            'business_unit':unit,'declaration_unit':du,'reference':group['reference'],
                            'same_single_quantity':single==qty,'single_quantity_source':deepcopy(cell),
                            'a_identity_hash':model.identity_context(fields,rid)}
        plan={'schema':'b00-scoped-basis-plan/1','batch_id':batch_id,'base_hash':key(batch),'base_a_version':view['a_version'],
              'source':{k:v for k,v in business.items() if k!='rows'},'groups':deepcopy(groups),'items':items,'excluded':excluded,
              'unselected_rows':sorted(set(rowmap)-seen),'formal_output':False,'professional_approval':False,
              'message':f'可确认{len(items)}行，例外{len(excluded)}行，未选{len(set(rowmap)-seen)}行'}
        if key(self.store.load(batch_id))!=key(batch):raise Rejected('预览期间A版本变化')
        pid=put(self.root,plan)
        return dict(plan,plan_id=pid,confirmation_hash=pid)

    def commit_basis(self,plan_id,*,confirmed_hash,explicit_confirmation,reference):
        from arrival_core.core import changed,now,context
        from arrival_core.operations_adapter import finite
        from arrival_core.business_amount import apply_amount
        from arrival_core.single_person import operator_context
        if explicit_confirmation is not True or confirmed_hash!=plan_id or not isinstance(reference,str) or not reference.strip():raise Rejected('须明确确认已展示的业务依据及范围')
        plan=get(self.root,plan_id)
        if plan.get('schema')!='b00-scoped-basis-plan/1' or not plan['items']:raise Rejected('没有有效确认范围')
        tx=key({'b00_plan':plan_id})
        with writer(self.root,plan['batch_id']):
            batch,baseline,source,sheet,fields,pricing=self._state(plan['batch_id'])
            if tx in batch['a03']['receipts']:return dict(batch['a03']['receipts'][tx],replayed=True)
            if key(batch)!=plan['base_hash']:raise Rejected('A版本冲突，旧范围不能覆盖新资料')
            if digest(Path(plan['source']['path']))!=plan['source']['sha256']:raise Rejected('确认依据文件已变化')
            # Rebuild from source on commit, independent of mutable caller preview.
            rebuilt=self.preview_basis(plan['batch_id'],business_file=plan['source']['path'],groups=plan['groups'])
            if rebuilt['plan_id']!=plan_id:raise Rejected('已展示依据发生变化')
            out=deepcopy(batch);state=out['a03'];operator=operator_context();at=now()
            prior=state.get('calculation_basis',{})
            source_refs=prior.get('sources',[]) if prior.get('a_version')==state['version_id'] else []
            source_refs={r['path']:r for r in source_refs};source_refs[plan['source']['path']]=plan['source']
            scoped_rows=deepcopy(prior.get('rows',{})) if prior.get('a_version')==state['version_id'] else {}
            rows={r['id']:r for r in out['rows']}
            class Session:
                mode='business'
                principal=operator.get('principal') or 'local_business_confirmation_unverified'
                def evidence(self):return dict(operator,scope='calculation_basis_only',professional_approval=False)
            for rid,item in plan['items'].items():
                row=rows[rid]
                # Match A04's confirmed basic projection; never promote a candidate.
                accepted={f['field']:f for f in fields.values() if f['row_id']==rid and confirmed(f,fields)}
                row['identity']['specification']=accepted.get('specification',{}).get('value',{}).get('value') or ''
                if 'product_code' in accepted:row['identity']['code']=accepted['product_code']['value']['value']
                proof={'confirmed_by':Session.principal,'confirmed_at':at,'reference':reference,
                       'scope':'calculation_basis_only','professional_approval':False,'plan_id':plan_id}
                values={'amount':item['basis']['amount'],'quantity':item['basis']['quantity'],'currency':'JPY',
                        'quantity_unit':item['business_unit'],'reason':item['reference']}
                apply_amount(row,values,session=Session(),reference=reference,source_revision=batch['revision'],authorization_hash=plan_id)
                row['reviews']['identity']=proof
                row['packaging']={'context':context(row),'source_unit':item['business_unit'],'internal_unit':item['business_unit'],
                                  'declaration_unit':item['declaration_unit'],'declaration_factor':item['declaration_factor'],
                                  'internal_quantity':item['basis']['quantity'],'internal_boxes':item['basis']['boxes'],
                                  'pieces_per_box':finite(item['internal_ratio']),
                                  'source':item['reference']}
                row['reviews']['packaging']=proof;row['reviews']['tax']=None;row['tax']=None
                hf=fields[item['h_target']]
                rec=self._record(hf,model.value('number',item['h']),'adopted_reference',
                                 {'source_ref':item['reference'],'meaning':'pieces_per_box'})
                rec['identity_context_hash']=item['a_identity_hash']
                rec['confirmation']={'plan_id':plan_id,'operator':operator,'reference':reference,'at':at}
                rec['sources']=[plan['source'],item['basis']['fields']['业务确认数量']['proof']]
                state['overrides'][item['h_target']]=rec
                scoped_rows[rid]={'same_single_quantity':item['same_single_quantity'],'plan_id':plan_id,
                                 'business_unit':item['business_unit'],'source_row':item['basis']['row'],
                                 'conversion_confirmed':True,'declaration_factor':item['declaration_factor'],
                                 'physical_pieces_per_box':item['h'],
                                 'legacy_internal_quantity_per_box':row['packaging']['pieces_per_box']}
            state['version_id']=key({'parent':batch['a03']['version_id'],'transaction':tx,'revision':batch['revision']+1})
            state['parent_hash']=key(batch)
            state['calculation_basis']={'schema':'b00-confirmed-basis/1','a_version':state['version_id'],
                                        'sources':list(source_refs.values()),'rows':scoped_rows}
            state['downstream']={'b_confirmation_valid':False,'c_delivery_valid':False,'recompute_required':True,
                                 'input_fingerprint':None,'invalidated_by':tx}
            _,rechecked=model.recheck(source,sheet,baseline,state);state['pricing_ref']=put(self.root,rechecked)
            receipt={'schema':'b00-basis-receipt/1','plan_id':plan_id,'transaction_id':tx,'a_version':state['version_id'],
                     'revision':batch['revision']+1,'confirmed_rows':sorted(plan['items']),'excluded':plan['excluded'],
                     'reference':reference,'operator':operator,'at':at,'formal_output':False,'professional_approvals':0}
            state['receipts'][tx]=receipt
            out=changed(batch,out,Session.principal,'b00_explicit_basis_confirmation',sorted(plan['items']),receipt)
            try:self.store.save(out,expected_hash=plan['base_hash'])
            except Exception:
                current=self.store.load(plan['batch_id'])
                if tx not in current['a03']['receipts']:raise
                return dict(current['a03']['receipts'][tx],replayed=True,recovered=True)
            return dict(receipt,replayed=False)

    def preflight(self,batch_id):return Bridge(self.root).prepare(batch_id)

    def read_basis(self,batch_id):
        """Separate quantity/amount layers, including invalidated saved history."""
        from arrival_core.business_amount import current,approved
        batch=self.store.load(batch_id);self._baseline(batch)
        scope=batch['a03'].get('calculation_basis',{})
        valid=scope.get('a_version')==batch['a03']['version_id']
        if valid:
            for s in scope['sources']:
                if digest(Path(s['path']))!=s['sha256']:raise Rejected('业务依据来源已变化')
        rows=[]
        for row in batch['rows']:
            record=current(row)
            active=bool(valid and record and approved(row))
            rows.append({'row_id':row['id'],'arrival_quantity_observation':deepcopy(row['arrival']),
                         'business_basis':deepcopy(record['values']) if active else None,
                         'saved_basis_history':deepcopy(record),'basis_current':active,
                         'purchase_quantity':None,'purchase_quantity_status':'not_confirmed',
                         'japanese_retail_amount':None,'retail_status':'not_supplied_as_business_basis'})
        if key(self.store.load(batch_id))!=key(batch):raise Rejected('读取期间A版本变化')
        return {'a_version':batch['a03']['version_id'],'current_hash':key(batch),'basis_current':valid,
                'rows':rows,'formal_output':False}
