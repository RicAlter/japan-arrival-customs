from pathlib import Path
from collections import defaultdict,Counter
from copy import deepcopy
from fractions import Fraction
import shutil
from .support import bootstrap,load,save,key,digest,put,get,archive,path,writer,advance,original_raw,field_fingerprint,Rejected
from separated.service import Service as Basics
from native22.profiles import inspect_source
from arrival_core import _p0_frozen as p0

def invoice(file):
    s=inspect_source(file)
    if s['profile_id']!='kmt-raw-invoice-v1':raise Rejected('日方更新须走已验证11列原始文件入口，不能上传人工业务副本')
    rows=[];carton=''
    for r in s['rows']:
        n=r['source_row'];t=s['sheet'];carton=p0.text(t.v(n,'A')) or carton
        identity=[carton,*[p0.text(t.v(n,c)) for c in ['B','C','D','E','F','G']]]
        rows.append({'row':n,'identity':identity,'carton':carton,'code':r['code'],'ja':r['japanese_name'],'origin':p0.text(t.v(n,'G')),
            'price':p0.text(t.v(n,'H')),'quantity':p0.text(t.v(n,'I')),'amount':p0.text(t.v(n,'K')),'source':r['source'],
            'weight_observation':p0.text(t.v(n,'J'))})
    totals=[]
    for n in s['sheet'].rows:
        if p0.text(s['sheet'].v(n,'G')).upper()=='TOTAL':
            try:
                amount=sum(Fraction(r['amount']) for r in rows);quantity=sum(Fraction(r['quantity']) for r in rows)
                valid=Fraction(p0.text(s['sheet'].v(n,'K')))==amount and Fraction(p0.text(s['sheet'].v(n,'I')))==quantity
            except (ValueError,ZeroDivisionError):valid=False
            totals.append({'row':n,'amount_cell':'K'+str(n),'quantity_cell':'I'+str(n),'consistent':valid})
    s['loop_total_checks']=totals
    return rows,s

class Service:
    def __init__(self,root):
        bootstrap();self.root=Path(root).resolve(strict=True)
        self.owner=load(self.root/'loop-owner.json')
        if self.owner.get('mode') not in {'business','synthetic'}:raise Rejected('闭环运行身份无效')
        self.basics=Basics(self.root);self.store=self.basics.store;self.bid=self.owner['batch_id']
        batch=self.store.load(self.bid)
        if batch.get('loop',{}).get('mode')!=self.owner['mode']:raise Rejected('目录身份与持久化批次模式不一致')
    @classmethod
    def fork(cls,workflow,destination,*,mode):
        bootstrap();m=load(workflow);source=Path(m['a03_root']).resolve();destination=Path(destination).resolve()
        if mode not in {'business','synthetic'}:raise Rejected('须明确隔离测试或实际业务模式')
        if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):raise Rejected('闭环使用新的独立目录，不能覆盖已确认状态')
        parent=Basics(source);before=parent.read_current(m['batch_id']);batch=parent.store.load(m['batch_id'])
        if mode=='business' and (batch.get('execution_mode')=='synthetic_technical_test' or (source/'loop-owner.json').exists() and load(source/'loop-owner.json').get('mode')=='synthetic'):
            raise Rejected('合成状态和确认不得晋升为真实业务目录')
        if mode=='business' and batch.get('loop'):raise Rejected('已有闭环版本请继续原目录，不可重新初始化更新和确认记录')
        shutil.copytree(path(source),path(destination))
        save(destination/'loop-owner.json',{'schema':'business-loop-owner/1','mode':mode,'workflow':str(Path(workflow).resolve()),'batch_id':m['batch_id'],
            'parent_state':str(source),'parent_hash':key(batch),'initial_raw':str(original_raw(workflow))})
        copied=Basics(destination);out=deepcopy(batch);out['execution_mode']='synthetic_technical_test' if mode=='synthetic' else batch.get('execution_mode','preliminary_untrusted')
        out['loop']={'schema':'business-loop/1','mode':mode,'updates':[],'active_update':None,'receipts':{},'origin_basics_hash':field_fingerprint(before)}
        out=advance(batch,out,'loop_isolated_fork','隔离闭环候选；不产生业务确认')
        copied.store.save(out,expected_hash=key(batch));return cls(destination)
    def preview_update(self,file,*,role,reference,links=None):
        if not isinstance(reference,str) or not reference.strip():raise Rejected('日方文件版本须有实际来源及价格角色说明')
        allowed={'business':{'actual_price_update','initial_price_observation'},'synthetic':{'synthetic_actual_price_update','synthetic_initial_price_observation'}}
        if role not in allowed[self.owner['mode']]:raise Rejected('合成更新与真实业务目录不能混用')
        batch=self.store.load(self.bid);view=self.basics.read_current(self.bid);raw=Path(file).resolve(strict=True);sha=digest(raw)
        if raw.suffix.lower()!='.xlsx':raise Rejected('只接受xlsx日方更新')
        if self.owner['mode']=='business':
            observed=inspect_source(raw)
            if 'SYNTHETIC' in p0.text(observed['sheet'].v(1,'A')).upper():raise Rejected('合成文件标记不得进入真实业务更新')
        archived=path(self.root/'objects'/(sha+'.xlsx'));archive(archived,raw.read_bytes())
        oldrows,old=invoice(self.owner['initial_raw']);newrows,new=invoice(archived)
        if self.owner['mode']=='business' and 'SYNTHETIC' in p0.text(new['sheet'].v(1,'A')).upper():raise Rejected('合成文件标记不得进入真实业务更新')
        oldbyrow={r['row']:r for r in oldrows};bykey=defaultdict(list);oldcounts=Counter(tuple(r['identity']) for r in oldrows)
        previous=get(self.root,batch['loop']['active_update']) if batch['loop']['active_update'] else None
        for r in newrows:bykey[tuple(r['identity'])].append(r)
        explicit=links or {};known={r['id'] for r in batch['rows']}
        if not isinstance(explicit,dict) or not set(explicit)<=known:raise Rejected('人工行关联范围无效')
        used=set();matches={};issues={};inherited=[];changed=[]
        for row in batch['rows']:
            rid=row['id'];original=oldbyrow.get(row['source']['row']+16)
            if not original:issues[rid]='旧原始行来源不可定位';continue
            candidates=bykey[tuple(original['identity'])]
            if rid in explicit:
                proof=explicit[rid]
                if set(proof)!={'new_row','reference'} or not isinstance(proof['reference'],str) or not proof['reference'].strip():raise Rejected('人工关联须指定新原行与依据')
                candidates=[r for r in newrows if r['row']==proof['new_row'] and r['identity']==original['identity']]
            elif oldcounts[tuple(original['identity'])]!=1:candidates=[]
            if len(candidates)!=1 or candidates[0]['row'] in used:issues[rid]='新增/冲突/重复身份，须明确关联；不按同JAN猜测';continue
            r=candidates[0];used.add(r['row']);prior=previous['matches'].get(rid,{}).get('new',original) if previous else original
            matches[rid]={'old_raw_row':prior['row'],'old_values':deepcopy(prior),'new':r,'explicit_link':deepcopy(explicit.get(rid)),
                'inheritance_reason':'完整箱号/Ref/JAN/日文名/HS/产地一致；业务基础值未由日方文件改写'}
            if any(prior[k]!=r[k] for k in ['price','quantity','amount','weight_observation']):changed.append(rid)
            inherited.extend(k for k,f in view['fields'].items() if f['row_id']==rid and f['confirmed'])
        new_unlinked=[r['row'] for r in newrows if r['row'] not in used]
        # Weight changes never inherit the old logistics release.
        ob=p0.Book(Path(self.owner['initial_raw']).read_bytes(),'old-raw.xlsx');nb=p0.Book(archived.read_bytes(),'new-raw.xlsx')
        oldweights=next(s for s in ob.sheets if s.name=='重さとサイズ');newweights=next(s for s in nb.sheets if s.name=='重さとサイズ')
        weights_equal=oldweights.cells==newweights.cells
        body={'schema':'loop-price-update-preview/1','batch_id':self.bid,'base_hash':key(batch),'mode':self.owner['mode'],'role':role,'reference':reference,
            'source':{'path':str(archived),'sha256':sha,'original_path':str(raw)},'matches':matches,'issues':issues,'new_unlinked_rows':new_unlinked,
            'inherited_targets':sorted(inherited),'changed_price_quantity_rows':changed,'basics_fingerprint':field_fingerprint(view),'weights_unchanged':weights_equal,
            'actual_price_qualified':role in {'actual_price_update','synthetic_actual_price_update'},'professional_approval':False,'formal_output':False}
        body['source_total_checks']=new['loop_total_checks'];body['source_totals_consistent']=all(t['consistent'] for t in new['loop_total_checks'])
        if digest(raw)!=sha or key(self.store.load(self.bid))!=key(batch):raise Rejected('更新预览期间来源/业务版本变化')
        pid=put(self.root,body);return {**body,'preview_id':pid}
    def commit_update(self,preview_id,*,confirmed_hash,explicit_confirmation,reference):
        if explicit_confirmation is not True or confirmed_hash!=preview_id or not isinstance(reference,str) or not reference.strip():raise Rejected('须明确确认已展示的日方更新版本及范围')
        plan=get(self.root,preview_id);tx=key({'price_update':preview_id})
        if plan.get('schema')!='loop-price-update-preview/1' or plan['mode']!=self.owner['mode']:raise Rejected('不是本目录的价格更新预览')
        with writer(self.root,self.bid):
            batch=self.store.load(self.bid)
            if tx in batch['loop']['receipts']:return {**batch['loop']['receipts'][tx],'replayed':True}
            if key(batch)!=plan['base_hash']:raise Rejected('基础版本变化，旧日方更新预览失效')
            if digest(Path(plan['source']['path']))!=plan['source']['sha256']:raise Rejected('日方更新归档被改变')
            out=deepcopy(batch);out['loop']['updates'].append(preview_id);out['loop']['active_update']=preview_id
            receipt={'transaction_id':tx,'preview_id':preview_id,'revision':batch['revision']+1,'inherited_confirmations':len(plan['inherited_targets']),
                'needs_link_review':len(plan['issues'])+len(plan['new_unlinked_rows']),'reference':reference,'mode':self.owner['mode'],'actual_business_confirmation':self.owner['mode']=='business',
                'professional_approval':False,'formal_output':False}
            out['loop']['receipts'][tx]=receipt;out=advance(batch,out,'japanese_price_version_confirmed',reference,plan['matches'])
            try:self.store.save(out,expected_hash=plan['base_hash'])
            except Exception:
                active=self.store.load(self.bid)
                if tx not in active['loop']['receipts']:raise
                return {**active['loop']['receipts'][tx],'replayed':True,'recovered':True}
            return {**receipt,'replayed':False}
    def active(self):
        batch=self.store.load(self.bid);pid=batch['loop']['active_update']
        if not pid:raise Rejected('尚无已明确承接的日方实际价更新')
        update=get(self.root,pid)
        if digest(Path(update['source']['path']))!=update['source']['sha256']:raise Rejected('实际价格来源变化')
        return batch,update,self.basics.read_current(self.bid)
