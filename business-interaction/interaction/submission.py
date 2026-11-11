"""Returned workbook is a stage submission, never an external-release approval.

Reuse the existing preview, eligibility, immutable receipts and CAS commits.
The legacy service remains available for replaying old confirmation sessions.
"""
from pathlib import Path
from copy import deepcopy
from .service import Service as Legacy
from . import rt,load,save,put,key,digest,Rejected
from . import calculation_context  # Add immutable original facts and sourced tax inputs.

POLICY='stage-return-is-submission/20261111'

class Service(Legacy):
    def deliver(self):
        pointer=self.background/'current-review-submission.json'
        if pointer.exists():
            r=load(pointer)
            if r['after_head']==self.status()['head'] and self.status()['stage']=='calculation':
                if digest(r['file'])!=r['sha256']:raise Rejected('已提交计算审核文件摘要变化')
                return {**self.status(),'business_files':[r['file']],'saved':True,'confirmation_required':False,
                        'submission_policy':POLICY,'exceptions':r['exceptions'],
                        'message':'已保存本阶段提交。仅列出的依据缺失/校验异常待处理；正式外发关闭。'}
        r=super().deliver()
        r['submission_policy']=POLICY
        if r['stage']=='calculation':r['message']='修改这一份计算审核表并回传即提交；系统校验后保存，异常集中报告。正式外发关闭。'
        return r

    def upload(self,file,*,kind=None,reference,**kwargs):
        if not str(reference or '').strip():raise Rejected('回传必须保留提交来源')
        source=Path(file).resolve(strict=True);sha=digest(source)
        context=key({k:v for k,v in kwargs.items() if k in {'purchase_evidence','selection','price_basis_reference'}})
        latest=self.background/'last-stage-submission.json'
        before=self.status()['head']
        if latest.exists():
            r=load(latest)
            if r['input_sha256']==sha and r.get('context_hash')==context and r['after_head']==before and kind in (None,r['kind']):
                return {**r['result'],'receipt_replayed':True}
        # O is supplied by the operator. R/S are never promoted into O here.
        kwargs['confirm_material']=True
        p=super().upload(file,kind=kind,reference=reference,**kwargs)
        if not p.get('confirmation_required'):return p
        kind=p['kind']
        if kind=='update':return p  # Price role still requires an evidenced adoption.
        exceptions=[]
        if kind=='basics':
            selection=deepcopy(p['selection'])
            # The old preview's generic further-confirmation flag can describe a
            # valid changed specification whose old price context was invalidated.
            # Accept the submitted text after eligibility; keep the price pending.
            from . import get
            from separated import model
            plan=get(self.root,p['plan_id']);preview=get(self.root,plan['preview_id'])
            special=any(c['field'] in {'specification','purchase_unit_price'} for c in preview['proposals'].values())
            fields=self.engine.basics.read_current(self.engine.bid)['fields'] if special else {}
            projected=deepcopy(fields)
            for t,c in preview['proposals'].items():projected[t]['value']=c['after']
            added=False
            for t,c in preview['proposals'].items():
                if c['field'] not in {'specification','purchase_unit_price'} or t in selection['confirm_fields']:continue
                if any('只读内容重复' in r or '类型待核' in r for r in c.get('reasons',[])):continue
                proof={}
                if c['field']=='purchase_unit_price':
                    raw=(kwargs.get('purchase_evidence') or {}).get(t)
                    if not isinstance(raw,dict) or set(raw)!={'source_ref','unit'}:continue
                    proof={**raw,'currency':'JPY','kind':'stage1_explicit_business_confirmation'}
                try:model.eligibility(projected[t],proof, {},projected)
                except ValueError:continue
                if projected[t]['value']['value'] in (None,''):continue
                if proof:selection['evidence'][t]=raw
                selection['confirm_fields'].append(t);added=True
            if added:
                plan=self.engine.basics.prepare_confirmation(plan['preview_id'],selection);p['plan_id']=plan['plan_id']
            accepted=set(selection['confirm_fields'])|set(selection['adopt_candidates'])
            # Invalid or substantive-conflict cells may be retained pending; valid
            # submitted cells get the existing business/reference-confirmed state.
            for change in p['change_details']:
                if change['target'] not in accepted:
                    exceptions.append({'target':change['target'],'field':change['field'],
                        'reason':'identity_or_value_validation_pending' if change['needs_further_confirmation'] else 'critical_evidence_or_value_missing'})
            receipt=self.engine.basics.commit(p['plan_id'],confirmed_hash=p['plan_id'],explicit_confirmation=True,
                reference=POLICY+'; submitted workbook '+sha+'; '+reference)
            result=self.deliver()
            result.update(saved=True,accepted_cells=len(accepted),changed_cells=p['proposed_changes'],
                purchase_prices_deferred=(sum(f['field']=='purchase_unit_price' and not f['confirmed'] and t not in accepted and projected[t]['value']['value'] not in (None,'') for t,f in fields.items()) if special else p['purchase_prices_deferred']))
        else:
            from . import get
            preview=get(self.root,p['preview_id'])
            if (preview['price_comparability_pending'] and preview['facts']
                and all(not f['errors'] and str(f.get('values',{}).get('conversion_reference') or '').strip() for f in preview['facts'])):
                # A valid returned workbook with explicit per-row basis is the
                # operator's submission of that scope, not a request to click again.
                export=load(self.background/'current-review-export.json')
                preview=rt.review.preview_return(self.root,export['export_id'],file,reference=reference,
                    price_basis_reference=POLICY+'; returned workbook '+sha+'; explicit per-row conversion sources submitted by operator')
                p['preview_id']=preview['preview_id']
            exceptions=[{'row_id':f['parent_id'],'reasons':f['errors']} for f in preview['facts'] if f['errors']]
            global_errors=[]
            for name,bad in [('price_basis_reference_missing',preview['price_comparability_pending']),
                ('unlinked_source_rows',bool(preview['new_identity_rows_pending'])),
                ('weight_version_requires_review',not preview['weights_unchanged']),
                ('source_totals_inconsistent',not preview['source_totals_consistent'])]:
                if bad:global_errors.append(name)
            if global_errors:exceptions.append({'scope':'batch','reasons':global_errors})
            receipt={'preview_id':p['preview_id'],'accepted_row_ids':[f['parent_id'] for f in preview['facts'] if not f['errors']],
                     'blocked_rows':p['blocked_rows'],'global_exceptions':global_errors,'formal_output':False}
            # The underlying engine permits controlled drafts only if every gate
            # passes. A partial submission is still archived/readable for editing.
            if not exceptions:
                receipt=rt.cli.confirm_review(self.root,p['preview_id'],confirmed_hash=p['preview_id'],
                    explicit_confirmation=True,reference=POLICY+'; '+reference)
            from a_confirm.locking import writer
            with writer(self.root,self.engine.bid):
                if self.status()['head']!=before:raise Rejected('提交期间上游版本变化，未保存当前指针')
                target=self._publish(preview['upload'],self.config.get('batch_label','batch')+'_计算审核.xlsx')
                save(self.background/'current-review-submission.json',{'file':target,'sha256':digest(target),
                    'after_head':before,'preview_id':p['preview_id'],'exceptions':exceptions,'receipt':receipt})
            result=self.deliver();result.update(saved=True,accepted_rows=len([f for f in preview['facts'] if not f['errors']]),blocked_rows=p['blocked_rows'])
        record={'schema':POLICY,'kind':kind,'input':str(source),'input_sha256':sha,'context_hash':context,'before_head':before,
                'after_head':self.status()['head'],'reference':reference,'receipt':receipt,'exceptions':exceptions,
                'professional_approval':False,'formal_output':False}
        record_id=put(self.background,record)
        result.update(confirmation_required=False,submission_policy=POLICY,submission_id=record_id,exceptions=exceptions)
        save(latest,{**record,'result':result})
        return result
