"""A-only explicit scoped confirmation. Reuses frozen B2 CAS/HEAD/receipts model."""
from copy import deepcopy
from pathlib import Path
import json
from . import __version__
from .support import ROOT, Rejected, archive, bootstrap, check_hashes, digest, get, key, load, path, put
from .locking import writer
from . import model


class InterruptedSave(Rejected):
    """No receipt at HEAD: retry the same confirmed plan, without guessing success."""


class Service:
    def __init__(self,root):
        bootstrap()
        from arrival_core.storage import Store
        self.root=Path(root).resolve();marker=self.root/'a03-service.json'
        identity={'schema':'isolated-a03-service/1','implementation':__version__,'exclusive_store_writer':'a_confirm'}
        if self.root.exists():
            if not marker.is_file() or load(marker)!=identity:raise Rejected('候选保存目录不是本A-03专用目录，不能写入旧成果')
        else:
            self.root.mkdir(parents=True);archive(marker,json.dumps(identity,sort_keys=True).encode())
        self.store=Store(path(self.root/'batches'));self._cache={}

    def _code(self):
        return {str(p):digest(p) for p in (ROOT/'a_confirm').glob('*.py')}

    def _baseline(self,batch):
        from arrival_core.storage import check_sources
        from native22.profiles import inspect_source
        from arrival_core import _p0_frozen as p0
        check_sources(batch)
        state=batch.get('a03',{})
        if state.get('schema')!='a-original-state/1' or state.get('can_enter_b') is not False or state.get('formal_output') is not False:
            raise Rejected('不是有效的A阶段专用版本')
        ref=state['baseline_ref'];file=path(self.root/'objects'/(ref+'.json'))
        if ref in self._cache:
            baseline,expected,source,sheet=self._cache[ref]
            if digest(file)!=expected:raise Rejected('A原始登记对象被修改')
        else:
            baseline=get(self.root,ref);reg=get(self.root,baseline['registration_ref'])
            source=inspect_source(baseline['source_file'])
            data=path(self.root/'objects'/(baseline['copy_sha256']+'.xlsx')).read_bytes()
            if key(reg['source_manifest'])!=baseline['source_manifest_hash']:raise Rejected('原行来源清单不一致')
            book=p0.Book(data,'a03-registered-original-copy.xlsx');sheet=next(s for s in book.sheets if s.name==source['sheet'].name)
            self._cache[ref]=(baseline,digest(file),source,sheet)
        if digest(path(self.root/'objects'/(baseline['copy_sha256']+'.xlsx')))!=baseline['copy_sha256']:
            raise Rejected('登记的原工作副本被修改')
        if batch['id']!=baseline['batch_id'] or batch['sources']!=baseline['source_manifest']:
            raise Rejected('A基础版本脱离原批次')
        return baseline,source,sheet

    def register(self,context_file):
        from native_return.service import context_snapshot
        from native22.prepare import registered_copy
        from native22.pricing import bind_basis
        from arrival_core.storage import Store
        from arrival_core import _p0_frozen as p0
        context,regs,current,snapshot=context_snapshot(context_file)
        current=registered_copy(context['current_output']);known=[]
        for s in current['source_manifest']:
            source=Path(s['path']).resolve()
            if self.root.is_relative_to(source.parent) or source.is_relative_to(self.root):raise Rejected('A保存目录必须与原件目录隔离')
        for folder in context['known_outputs']:
            reg=registered_copy(folder)
            data=Path(reg['file']).read_bytes();archive(self.root/'objects'/(reg['copy_sha256']+'.xlsx'),data)
            known.append({'registration_ref':put(self.root,reg),'copy_sha256':reg['copy_sha256']})
        original=Store(path(Path(context['current_output'])/'technical/batch-store')).load(current['batch_id'])
        for s in original['sources']:
            source=Path(s['path']).resolve()
            if self.root.is_relative_to(source.parent) or source.is_relative_to(self.root):raise Rejected('A保存目录必须与原件目录隔离')
        if original['sources']!=current['source_manifest']:raise Rejected('原快照与副本登记不一致')
        book=p0.Book(Path(current['file']).read_bytes(),'a03-imported-copy.xlsx')
        main=current['row_map'][0]['source']['sheet'];sheet=next(s for s in book.sheets if s.name==main)
        baseline={'schema':'a03-baseline/1','registration_ref':put(self.root,current),'batch_id':current['batch_id'],
                  'business_batch_id':current['business_batch_id'],'source_file':current['source_manifest'][0]['path'],
                  'source_manifest':current['source_manifest'],'source_manifest_hash':current['source_manifest_hash'],
                  'copy_sha256':current['copy_sha256'],'export_id':current['export_id'],'known':known,
                  'fields':model.fields_from_baseline(current,sheet),
                  'price_basis':current.get('price_basis',{'status':'not_bound','reason':'旧副本未绑定价格口径'})}
        baseline_ref=put(self.root,baseline);bid=original['id']
        with writer(self.root,bid):
            if (self.store.folder(bid)/'head.json').exists():
                active=self.store.load(bid)
                if active.get('a03',{}).get('baseline_ref')!=baseline_ref:raise Rejected('本批已有A保存版本，不能重新初始化覆盖')
                return {'status':'already_registered','batch_id':bid,'revision':active['revision'],'current_hash':key(active),'a_version':active['a03']['version_id']}
            out=deepcopy(original);out['revision']=0;out['formal_output_enabled']=False
            out['a03']={'schema':'a-original-state/1','baseline_ref':baseline_ref,'overrides':{},'receipts':{},
                        'version_id':key({'baseline':baseline_ref,'revision':0}),'parent_hash':None,
                        'downstream':{'b_confirmation_valid':False,'c_delivery_valid':False,'recompute_required':True,'input_fingerprint':None},
                        'can_enter_b':False,'formal_output':False}
            from native22.profiles import inspect_source
            source=inspect_source(baseline['source_file'])
            _,pricing=model.recheck(source,sheet,baseline,out['a03'])
            out['a03']['pricing_ref']=put(self.root,pricing)
            check_hashes(snapshot);bootstrap();self.store.save(out)
        return {'status':'registered','batch_id':bid,'revision':0,'current_hash':key(out),'a_version':out['a03']['version_id']}

    def _state(self,batch_id):
        batch=self.store.load(batch_id);baseline,source,sheet=self._baseline(batch)
        fields,pricing=model.recheck(source,sheet,baseline,batch['a03'])
        saved=get(self.root,batch['a03']['pricing_ref'])
        if key(pricing)!=key(saved):raise Rejected('当前A资料与保存的受控价格核验不一致')
        by_row={f['row_id']:f for f in fields.values() if f['field']=='pieces_per_box'}
        for row in pricing['rows']:
            field=by_row.get(row['row_id'])
            if field and row['mode']=='inferred' and field['target'] not in batch['a03']['overrides']:
                field['value']=model.value('number' if row['pieces_per_box'] is not None else 'blank',row['pieces_per_box'])
        return batch,baseline,source,sheet,fields,pricing

    def read_current(self,batch_id):
        batch,baseline,source,sheet,fields,pricing=self._state(batch_id)
        calculated=[]
        by_row={f['row_id']:f for f in fields.values() if f['field']=='pieces_per_box'}
        for r in pricing['rows']:
            if r['mode']=='inferred' and r['row_id'] in by_row and by_row[r['row_id']]['target'] not in batch['a03']['overrides']:
                by_row[r['row_id']]['value']=model.value('number' if r['pieces_per_box'] is not None else 'blank',r['pieces_per_box'])
            calculated.append({'row_id':r['row_id'],'h_cell':r['h_cell'],'u_cell':r['u_cell'],
                               'pieces_per_box':r['pieces_per_box'],'difference_jpy':r['difference_jpy'],'status':r['status']})
        for f in fields.values():
            rec=batch['a03']['overrides'].get(f['target'])
            f['registered_observation']=baseline['fields'][f['target']]['value']
            if f['field'] in ('purchase_unit_price','pieces_per_box'):
                f['adopted_basis_current']=bool(rec and rec['confirmed'] and rec.get('identity_context_hash')==model.identity_context(fields,f['row_id']))
        return {'schema':'a03-current-basic-data/1','batch_id':batch_id,'business_batch_id':baseline['business_batch_id'],
                'revision':batch['revision'],'a_version':batch['a03']['version_id'],'current_hash':key(batch),
                'price_basis_hash':key(baseline['price_basis']),'price_basis_status':baseline['price_basis']['status'],
                'fields':fields,'pricing_counts':pricing['counts'],'pricing_groups':pricing['groups'],
                'calculated_cells':calculated,'downstream':deepcopy(batch['a03']['downstream']),
                'confirmed_field_count':sum(f['confirmed'] for f in fields.values()),
                'candidate_field_count':sum(f['status']=='candidate' for f in fields.values()),
                'saved_pending_fields':sorted(k for k,f in fields.items() if f['status']=='saved_pending'),
                'workbook_snapshot_role':'immutable_source_reference_not_current_saved_values',
                'formulas_preserved':True,'returned_formula_cache_used':False,
                'can_enter_b':False,'formal_output':False,'professional_approvals':0}

    def preview_return(self,batch_id,uploaded,*,expected_hash,field_proposals=None,box_corrections=None):
        from native_return.compare import read,compare,passive_links,InvalidReturn
        from native_return.service import version_identity,corrections
        from arrival_core import _p0_frozen as p0
        batch,baseline,source,sheet,fields,pricing=self._state(batch_id)
        if key(batch)!=expected_hash:raise Rejected('当前版本已变化，请重新读取后预览')
        snapshot=self._code();uploaded=Path(uploaded).resolve(strict=True);data=uploaded.read_bytes();sha=digest(uploaded)
        if uploaded.suffix.lower()!='.xlsx':raise Rejected('只接受xlsx回传')
        archive(self.root/'objects'/(sha+'.xlsx'),data)
        main_reg=get(self.root,baseline['registration_ref']);issued=path(self.root/'objects'/(baseline['copy_sha256']+'.xlsx')).read_bytes()
        regs=[get(self.root,k['registration_ref']) for k in baseline['known']]
        if any(sha==r['copy_sha256'] and version_identity(r)!=version_identity(main_reg) for r in regs):raise Rejected('旧版本或其他批次文件不能覆盖当前A资料')
        wb,_=read(data,trusted_external=passive_links(issued));opened=[wb];matches=[];edits=None;current_error=None
        try:
            for reg in regs:
                raw=path(self.root/'objects'/(reg['copy_sha256']+'.xlsx')).read_bytes()
                if digest(path(self.root/'objects'/(reg['copy_sha256']+'.xlsx')))!=reg['copy_sha256']:raise Rejected('已知副本归档被修改')
                base,_=read(raw,trusted_external=passive_links(raw));opened.append(base)
                try:
                    found=compare(base,wb,reg);matches.append(reg)
                    if reg['export_id']==main_reg['export_id']:edits=found
                except InvalidReturn as exc:
                    if reg['export_id']==main_reg['export_id']:current_error=exc
            if len({version_identity(r) for r in matches})>1:raise Rejected('多个导出版本无法唯一定位，不能猜测归属')
            if edits is None:raise current_error or Rejected('回传不属于本批工作副本')
            main_wb,_=read(issued,trusted_external=passive_links(issued));opened.append(main_wb)
            box=corrections(box_corrections or [],main_reg,main_wb)
        finally:
            for w in opened:w.close()
        proposed={};already=[]
        for e in edits:
            target=e['sheet']+'!'+e['cell'];after=model.value(e['after']['type'],e['after']['value'])
            before=fields[target]['value'];original=model.value(e['before']['type'],e['before']['value'])
            if after==before:already.append(target);continue
            if before!=original:raise Rejected('旧文件修改与已保存值冲突，拒绝覆盖：'+target)
            proposed[target]={'target':target,'row_id':e['row_id'],'field':e['field'],'before':before,'after':after,
                              'needs_further_confirmation':e['needs_further_confirmation'],'reasons':e['reasons'],'origin':'excel_edit'}
        dialogues=list(field_proposals or [])+[{'sheet':b['sheet'],'cell':b['cell'],
                    'value':{'type':'number','value':str(b['proposed_pieces_per_box'])},'message_ref':b['message_ref']} for b in box]
        dialogue_targets=set()
        for d in dialogues:
            if not isinstance(d,dict) or set(d)!={'sheet','cell','value','message_ref'} or not isinstance(d['message_ref'],str) or not d['message_ref'].strip():
                raise Rejected('对话提案须明确原格、值及真实对话出处')
            target=d['sheet']+'!'+d['cell']
            if target not in fields or target in proposed or target in dialogue_targets:raise Rejected('对话字段不在基础白名单或与Excel重复')
            dialogue_targets.add(target)
            if not isinstance(d['value'],dict) or set(d['value'])!={'type','value'}:raise Rejected('提案值须明确类型')
            after=model.value(d['value']['type'],d['value']['value'])
            if after==fields[target]['value']:already.append(target);continue
            proposed[target]={'target':target,'row_id':fields[target]['row_id'],'field':fields[target]['field'],
                              'before':fields[target]['value'],'after':after,'needs_further_confirmation':True,
                              'reasons':['对话提案尚未采用'],'origin':'dialogue_proposal','message_ref':d['message_ref']}
        draft=deepcopy(batch['a03'])
        for target,e in proposed.items():draft['overrides'][target]=self._record(fields[target],e['after'],'saved_pending',{})
        _,preview_pricing=model.recheck(source,sheet,baseline,draft)
        pending_rows={r['row_id'] for r in preview_pricing['rows'] if r.get('hypothetical_only')}
        for e in proposed.values():
            if e['row_id'] in pending_rows and e['field'] in ('product_code','specification','purchase_unit_price','pieces_per_box'):e['needs_further_confirmation']=True
        preview={'schema':'a03-return-preview/1','batch_id':batch_id,'base_hash':key(batch),'base_version':batch['a03']['version_id'],
                 'baseline_ref':batch['a03']['baseline_ref'],'upload_sha256':sha,'proposals':proposed,'already_saved':sorted(set(already)),
                 'pricing_ref':put(self.root,preview_pricing),'confirmed':False,'can_enter_b':False,
                 'modified_cells':len(proposed),'needs_further_confirmation_cells':sum(e['needs_further_confirmation'] for e in proposed.values())}
        if digest(uploaded)!=sha:raise Rejected('上传在预览中发生变化')
        if key(self.store.load(batch_id))!=key(batch):raise Rejected('预览期间当前版本发生变化')
        check_hashes(snapshot);bootstrap();identity=put(self.root,preview)
        return dict(preview,preview_id=identity,message=f'修改了{len(proposed)}格，{preview["needs_further_confirmation_cells"]}格需要进一步确认；尚未保存')

    @staticmethod
    def _record(field,v,status,evidence):
        return {'row_id':field['row_id'],'field':field['field'],'value':deepcopy(v),'status':status,
                'confirmed':status in model.CONFIRMED,'professional_approval':False,'evidence':deepcopy(evidence),
                'identity_context_hash':None,'value_origin':'explicit_business_selection','sources':[],
                'prior_sources':deepcopy(field.get('sources',[]))}

    def _preview(self,preview_id):
        preview=get(self.root,preview_id)
        if preview.get('schema')!='a03-return-preview/1':raise Rejected('不是A-03回传预览')
        if digest(path(self.root/'objects'/(preview['upload_sha256']+'.xlsx')))!=preview['upload_sha256']:raise Rejected('回传归档被修改')
        get(self.root,preview['pricing_ref'])
        return preview

    def prepare_confirmation(self,preview_id,selection):
        preview=self._preview(preview_id)
        batch,baseline,source,sheet,fields,pricing=self._state(preview['batch_id'])
        if key(batch)!=preview['base_hash']:raise Rejected('该预览已过期，请基于当前A版本重新展示')
        required={'save_changes','confirm_fields','adopt_candidates','evidence'}
        if not isinstance(selection,dict) or set(selection)!=required or not isinstance(selection['evidence'],dict):raise Rejected('须明确保存、确认和候选采用范围')
        scope={}
        for name in ('save_changes','confirm_fields','adopt_candidates'):
            items=selection[name]
            if not isinstance(items,list) or any(not isinstance(x,str) or x not in fields for x in items) or len(items)!=len(set(items)):
                raise Rejected('范围须为具体且不重复的已登记单元格，不支持整批通配批准')
            scope[name]=sorted(items)
        if set(selection['evidence'])-set(scope['confirm_fields'])-set(scope['adopt_candidates']):raise Rejected('依据不能夹带未选确认范围')
        if set(scope['confirm_fields'])&set(scope['adopt_candidates']):raise Rejected('普通确认与候选采用不能重复')
        projected=deepcopy(fields);updates={}
        for target in scope['save_changes']:
            e=preview['proposals'].get(target)
            if not e:raise Rejected('保存范围不在本次修改预览中')
            updates[target]=self._record(fields[target],e['after'],'saved_pending',{})
            projected[target].update(updates[target])
        for target in scope['confirm_fields']+scope['adopt_candidates']:
            f=projected[target];adopt=target in scope['adopt_candidates']
            if adopt and (fields[target]['status']!='candidate' or target in preview['proposals']):raise Rejected('候选采用只适用于明确选中的未改候选')
            if not adopt and fields[target]['status']=='candidate' and target not in scope['save_changes']:raise Rejected('未改黄色候选须明确采用，不能夹带确认')
            if fields[target]['confirmed'] and target not in updates:continue
            proof=model.eligibility(f,selection['evidence'].get(target,{}),baseline['price_basis'],projected)
            status='reference_confirmed' if f['field']=='material_reference' else 'adopted_reference' if adopt or f['field'] in ('purchase_unit_price','pieces_per_box') else 'business_confirmed'
            rec=self._record(f,f['value'],status,proof['evidence'])
            if target not in scope['save_changes']:rec['sources']=deepcopy(f.get('sources',[]))
            rec['identity_context_hash']=proof['identity_context_hash'];updates[target]=rec;projected[target].update(rec)
        if not updates:raise Rejected('没有新增修改或明确采用范围，不新增A版本')
        draft=deepcopy(batch['a03']);draft['overrides'].update(updates)
        _,remaining=model.recheck(source,sheet,baseline,draft)
        plan={'schema':'a03-confirmation-plan/1','batch_id':batch['id'],'preview_id':preview_id,'base_hash':key(batch),
              'base_version':batch['a03']['version_id'],'baseline_ref':batch['a03']['baseline_ref'],'updates':updates,
              'selection':scope,'evidence':deepcopy(selection['evidence']),'pricing_ref':put(self.root,remaining),
              'unselected_changes':sorted(set(preview['proposals'])-set(scope['save_changes'])),
              'summary':{'saved_fields':len(updates),'confirmed_fields':sum(r['confirmed'] for r in updates.values()),
                         'saved_pending_fields':sum(not r['confirmed'] for r in updates.values()),
                         'adopted_candidates':len(scope['adopt_candidates']),'remaining_price_rows':remaining.get('affected_price_rows'),
                         'pricing_counts':remaining['counts']},'requires_explicit_confirmation':True,'professional_approvals':0}
        if key(self.store.load(batch['id']))!=key(batch):raise Rejected('选择范围期间版本已变化')
        identity=put(self.root,plan)
        return dict(plan,plan_id=identity,confirmation_hash=identity,
                    message=f'本次保存{len(updates)}格，其中{plan["summary"]["confirmed_fields"]}格明确确认；其余问题保持待核，等待明确确认')

    def _build(self,batch,plan,plan_id,operator,reference,at):
        from arrival_core.core import changed
        out=deepcopy(batch);state=out['a03'];tx=key({'kind':'a03-confirmation','plan_id':plan_id})
        state['overrides'].update(deepcopy(plan['updates']))
        for target in plan['updates']:
            state['overrides'][target]['confirmation']={'plan_id':plan_id,'operator':operator,'reference':reference,'at':at}
        state['version_id']=key({'parent':batch['a03']['version_id'],'transaction':tx,'revision':batch['revision']+1})
        state['parent_hash']=key(batch);state['pricing_ref']=plan['pricing_ref']
        state['downstream']={'b_confirmation_valid':False,'c_delivery_valid':False,'recompute_required':True,
                             'input_fingerprint':None,'invalidated_by':tx,'previous_a_version':batch['a03']['version_id']}
        out['formal_output_enabled']=False;out['active_review_lock']=None
        for row in out['rows']:
            for domain in ('price','packaging','tax'):row['reviews'][domain]=None
        receipt={'schema':'a03-commit-receipt/1','transaction_id':tx,'plan_id':plan_id,'preview_id':plan['preview_id'],
                 'revision':batch['revision']+1,'a_version':state['version_id'],'operator':operator,'reference':reference,'saved_at':at,
                 'saved_fields':sorted(plan['updates']),'confirmed_fields':sorted(k for k,r in plan['updates'].items() if r['confirmed']),
                 'saved_pending_fields':sorted(k for k,r in plan['updates'].items() if not r['confirmed']),
                 'adopted_candidates':plan['selection']['adopt_candidates'],'unselected_changes':plan['unselected_changes'],
                 'pricing_summary':plan['summary'],'professional_approvals':0,'d1_events':0,'can_enter_b':False,'formal_output':False}
        state['receipts'][tx]=receipt
        out=changed(batch,out,operator.get('principal') or 'single_person_unverified','a03_scoped_confirmation',
                    sorted({r['row_id'] for r in plan['updates'].values()}),receipt)
        out['events'][-1]['at']=at
        return out

    def commit(self,plan_id,*,confirmed_hash,explicit_confirmation,reference):
        from arrival_core.single_person import operator_context
        from arrival_core.core import now
        if explicit_confirmation is not True or confirmed_hash!=plan_id or not isinstance(reference,str) or not reference.strip():
            raise Rejected('须明确确认已经展示的范围与版本，不能从Excel推定批准')
        bootstrap();snapshot=self._code();plan=get(self.root,plan_id)
        if plan.get('schema')!='a03-confirmation-plan/1':raise Rejected('不是已展示的确认范围预览')
        preview=self._preview(plan['preview_id']);get(self.root,plan['pricing_ref'])
        if preview['base_hash']!=plan['base_hash'] or preview['baseline_ref']!=plan['baseline_ref']:raise Rejected('确认范围脱离原预览')
        bid=plan['batch_id'];tx=key({'kind':'a03-confirmation','plan_id':plan_id})
        with writer(self.root,bid) as stale:
            batch,baseline,source,sheet,fields,pricing=self._state(bid)
            if tx in batch['a03']['receipts']:
                return dict(batch['a03']['receipts'][tx],status='saved',replayed=True,current_hash=key(batch),recovered_stale_lock=stale)
            if key(batch)!=plan['base_hash'] or batch['a03']['baseline_ref']!=plan['baseline_ref']:raise Rejected('版本冲突，不能用旧确认覆盖当前A版本')
            file=path(self.root/'transactions'/(tx+'.json'))
            if not file.exists():
                operator=operator_context();at=now();out=self._build(batch,plan,plan_id,operator,reference,at)
                intent={'schema':'a03-save-intent/1','plan_id':plan_id,'operator':operator,'reference':reference,'at':at,'out':out,'out_hash':key(out)}
                try:archive(file,json.dumps(intent,ensure_ascii=False,sort_keys=True,allow_nan=False).encode())
                except Rejected:
                    if not file.exists():raise
            intent=load(file)
            if intent.get('schema')!='a03-save-intent/1' or intent.get('plan_id')!=plan_id or key(intent['out'])!=intent['out_hash']:
                raise Rejected('保存事务草稿被修改')
            out=self._build(batch,plan,plan_id,intent['operator'],intent['reference'],intent['at'])
            if out!=intent['out']:raise Rejected('事务草稿超出已明确确认的范围')
            _,checked=model.recheck(source,sheet,baseline,out['a03'])
            if key(checked)!=plan['pricing_ref']:raise Rejected('保存前重新核验与已展示范围不一致')
            check_hashes(snapshot);bootstrap()
            try:self.store.save(out,expected_hash=plan['base_hash'])
            except Exception as exc:
                try:active=self.store.load(bid)
                except Exception as read_error:
                    raise InterruptedSave('保存结果暂不能核实，请对同一确认范围恢复查询，勿另建重复提交：'+str(read_error)) from exc
                if tx in active.get('a03',{}).get('receipts',{}):
                    return dict(active['a03']['receipts'][tx],status='saved',replayed=True,current_hash=key(active),recovered_after_exception=True,recovered_stale_lock=stale)
                raise InterruptedSave('保存尚未提交；当前版本保持，可对同一确认范围重试：'+str(exc)) from exc
            return dict(out['a03']['receipts'][tx],status='saved',replayed=False,current_hash=key(out),recovered_stale_lock=stale)

    def history(self,batch_id):
        batch=self.store.load(batch_id);result=[]
        while True:
            self._baseline(batch)
            result.append({'revision':batch['revision'],'a_version':batch['a03']['version_id'],'snapshot_hash':key(batch),
                           'transaction_count':len(batch['a03']['receipts'])})
            parent=batch['a03']['parent_hash']
            if parent is None:break
            previous=self.store.folder(batch_id)/f'r{batch["revision"]-1:06d}-{parent}.json'
            batch=load(previous)
            if key(batch)!=parent:raise Rejected('已提交版本链摘要不一致')
        return list(reversed(result))
