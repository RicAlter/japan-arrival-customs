"""D3 lifecycle artifacts under the existing D1 library; no second approval system.

    Human identity comes exclusively from B2 Session + signed D08. A host-admin
    policy authorizes publishers and supplies business-approved quality thresholds.
    Production is off unless all those independently configured gates are valid.
"""
import copy, json
from pathlib import Path
from .core import Rejected, digest, now, decimal, changed, context
from .storage import Store, atomic_json, check_sources
from .classification_contract import CONDITIONS, TARGET, contract, day, timestamp
from .decision_library import DecisionLibrary
from .d2_candidates import analyze_library
from .return_auth import authorize


class RuleRegistry:
    def __init__(self, path, *, library):
        self.library = library if isinstance(library,DecisionLibrary) else DecisionLibrary(library)
        self.path = Path(path).resolve()
        if self.path.parent != self.library.root or self.path.name != 'rule_registry.json':
            raise Rejected('规则版本必须保存在原D1库的rule_registry.json，不允许另建知识库')
        self.source_root = Path(self.library._metadata()['source_root'])

    def _load(self):
        if not self.path.exists():
            return {'schema':'japan-arrival/rule-registry-2','revision':0,'events':[],'rules':{}}
        value = json.loads(self.path.read_text(encoding='utf-8'))
        if value.get('schema') != 'japan-arrival/rule-registry-2':
            raise Rejected('规则库格式未知，须开发期显式迁移，运行时不迁移')
        previous = None
        for i,event in enumerate(value['events'],1):
            if event['sequence'] != i or event['previous'] != previous or event['hash'] != digest({k:v for k,v in event.items() if k!='hash'}):
                raise Rejected('规则审计链损坏')
            previous = event['hash']
        if value['revision'] != len(value['events']): raise Rejected('规则修订号不一致')
        if value['events'] and value['events'][-1]['rules_hash'] != digest(value['rules']): raise Rejected('规则状态与审计不一致')
        return value

    def _record(self,value,action,rule,proof):
        event={'sequence':value['revision']+1,'previous':value['events'][-1]['hash'] if value['events'] else None,
               'at':now(),'action':action,'rule_id':rule['id'],'version':rule['version'],
               'proof':proof,'rules_hash':digest(value['rules'])}
        event['hash']=digest(event); value['events'].append(event); value['revision']+=1
        atomic_json(self.path,value)

    def _analysis(self,as_of,realm): return analyze_library(self.library,as_of=as_of,realm=realm)

    def _candidate(self,candidate_id,as_of,realm):
        analysis=self._analysis(as_of,realm)
        candidate=next((c for c in analysis['discovery']['candidates'] if c['candidate_id']==candidate_id),None)
        if not candidate: raise Rejected('候选不在当前有效D1证据中')
        return candidate,analysis

    def _live_support(self,candidate):
        # An approval can already be revoked in B2 while D1 delivery is pending.
        # Such a saved human change must block new automation immediately. If the
        # authoritative source cannot be read, reuse falls back to manual review.
        if candidate['realm']=='test' and self.library._metadata()['source_kind']=='synthetic':return
        from .declaration_decisions import head
        for proof in candidate['support']:
            batch=Store(self.source_root).load(proof['batch_id']);check_sources(batch)
            record=next((head(r) for r in batch['rows'] if head(r) and head(r)['decision_id']==proof['decision_id']),None)
            if not record or record['version']!=proof['version'] or record['state']!='effective':
                raise Rejected('支持决定已在B2变更或撤销，须先同步D1并复核规则')

    def draft(self,candidate_id,*,as_of,realm='formal',expected_version=None):
        candidate,analysis=self._candidate(candidate_id,as_of,realm)
        identifier=digest([realm,candidate_id])
        with Store(self.library.root).lock(self.library.root/'rule_writes'):
            value=self._load(); versions=value['rules'].setdefault(identifier,[])
            if versions and versions[-1]['status']=='revoked': raise Rejected('已撤销规则不可复活；须新证据和新候选')
            if expected_version is not None and expected_version!=len(versions): raise Rejected('规则版本过期')
            if versions and versions[-1]['candidate_version']==candidate['candidate_version'] and versions[-1]['status'] in ('pending_approval','published'):
                return dict(versions[-1],replayed=True)
            rule={'id':identifier,'version':len(versions)+1,'status':'pending_approval','realm':realm,
                  'candidate_id':candidate_id,'candidate_version':candidate['candidate_version'],
                  'candidate':candidate,'discovery_hash':analysis['discovery']['report_hash'],
                  'validation_hash':analysis['validation']['report_hash'],'created_at':now()}
            versions.append(rule);self._record(value,'draft',rule,{'approval':False})
            return copy.deepcopy(rule)

    def _policy(self,session,batch,role,realm,as_of):
        from .contracts import contract_status
        if not batch or not batch.get('input_contract') or not contract_status(batch['input_contract'],batch['rows'])['approved_for_business_review']:
            raise Rejected('规则授权必须有本票已签核D08')
        # Reuse D08's existing customs responsibility; rule-specific delegation is
        # an additional trusted-session role, not a new Excel/D08 field.
        authorize(self.source_root,session,batch,'customs')
        if role not in session.roles: raise Rejected('可信会话未获得规则发布/执行专用角色')
        if realm=='formal' and (session.mode!='business' or self.library._metadata()['source_kind']!='business'):
            raise Rejected('合成/测试身份或测试D1库不能发布或执行正式规则')
        if realm=='test':
            synthetic=session.mode=='synthetic_technical_test' and batch.get('execution_mode')=='synthetic_technical_test'
            config=json.loads((self.source_root/'security/trusted_sessions.json').read_text(encoding='utf-8'))
            fixture=(session.mode=='business' and batch.get('execution_mode')=='authorized_test_fixture' and
                     batch.get('test_fixture_id') and config.get('purpose')=='authorized_test_fixture' and
                     self.library._metadata()['source_kind']=='authorized_test_fixture')
            if not synthetic and not fixture: raise Rejected('技术规则只能用于显式隔离测试批次')
        path=self.source_root/'security/rule_policy.json'
        try: policy=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc: raise Rejected('未配置经批准的可信规则发布策略') from exc
        if (policy.get('realm')!=realm or policy.get('quality_approved') is not True or
            not policy.get('approval_reference') or not policy.get('approved_by') or not policy.get('credential_ref') or
            session.principal not in policy.get('publishers' if role=='rule_publisher' else 'executors',[]) or
            not policy.get('valid_from','')<=as_of<=policy.get('valid_through','') or
            not policy.get('valid_from','')<=timestamp(now()).date().isoformat()<=policy.get('valid_through','')):
            raise Rejected('发布/执行角色、质量批准或有效期缺失')
        return policy

    @staticmethod
    def _quality(candidate,analysis,policy):
        thresholds=policy.get('thresholds',{})
        required={'min_independent_support','min_validation_decisions','min_covered_decisions','min_joint_accuracy'}
        if set(thresholds)!=required: raise Rejected('质量门槛尚未完整批准')
        for k in required-{'min_joint_accuracy'}:
            if type(thresholds[k]) is not int or thresholds[k]<0: raise Rejected('质量分母门槛须为明确非负整数')
        accuracy=decimal(thresholds['min_joint_accuracy'])
        if not 0<=accuracy<=1: raise Rejected('联合正确率门槛无效')
        rows=[r for r in analysis['validation']['rows'] if r['conditions']==candidate['conditions']]
        covered=[r for r in rows if r['prediction']]
        correct=sum(r['prediction']==r['human_final'] for r in covered)
        if candidate['status']!='candidate_rule' or candidate['conflicted']:
            raise Rejected('单案例或冲突候选不可发布')
        if (candidate['independent_support_count']<thresholds['min_independent_support'] or
            len(rows)<thresholds['min_validation_decisions'] or len(covered)<thresholds['min_covered_decisions'] or
            not covered or decimal(str(correct))/decimal(str(len(covered)))<accuracy):
            raise Rejected('候选未满足获批验证门槛或没有可验证分母')
        return {'evaluated':len(rows),'covered':len(covered),'joint_correct':correct,'thresholds':thresholds}

    def publish(self,rule_id,*,session,batch,reference,as_of,expected_version):
        if not isinstance(reference,str) or not reference.strip(): raise Rejected('须提供规则批准依据')
        with Store(self.library.root).lock(self.library.root/'rule_writes'):
            value=self._load(); rule=copy.deepcopy(value['rules'][rule_id][-1])
            if rule['version']!=expected_version or rule['status']!='pending_approval': raise Rejected('规则不是当前待批准版本')
            policy=self._policy(session,batch,'rule_publisher',rule['realm'],day(as_of))
            candidate,analysis=self._candidate(rule['candidate_id'],as_of,rule['realm'])
            if candidate['candidate_version']!=rule['candidate_version']: raise Rejected('支持证据已变化，须生成新候选版本')
            self._live_support(candidate)
            quality=self._quality(candidate,analysis,policy)
            intervals=candidate['validity_evidence']
            start=max(x['valid_from'] for x in intervals); end=min(x['valid_through'] for x in intervals)
            if not start<=as_of<=end or not start<=timestamp(now()).date().isoformat()<=end: raise Rejected('全部支持证据没有当前共同有效期')
            rule.update(status='published',valid_from=start,valid_through=end,published_at=now(),
                        approval={'execution':session.evidence(),'reference':reference,'policy_hash':digest(policy),
                                  'batch_id':batch['id'],'batch_hash':digest(batch),'quality':quality})
            # Lifecycle transitions always append versions; old approvals are never rewritten.
            rule['version']+=1;value['rules'][rule_id].append(rule)
            self._record(value,'publish',rule,rule['approval']);return rule

    def transition(self,rule_id,status,*,session,batch,reference,as_of,expected_version):
        if status not in ('suspended','revoked') or not reference: raise Rejected('仅允许有依据的暂停或撤销')
        with Store(self.library.root).lock(self.library.root/'rule_writes'):
            value=self._load();rule=copy.deepcopy(value['rules'][rule_id][-1])
            self._policy(session,batch,'rule_publisher',rule['realm'],as_of)
            if rule['version']!=expected_version or rule['status']=='revoked': raise Rejected('规则已撤销或版本过期')
            rule.update(version=rule['version']+1,status=status,changed_at=now(),change_reference=reference)
            value['rules'][rule_id].append(rule);self._record(value,status,rule,session.evidence());return rule

    def match(self,facts,*,as_of,allow_automatic=False,session=None,batch=None,realm='formal'):
        day(as_of)
        result={'as_of':as_of,'matches':[],'automatic_adoption':False,'technical_application_allowed':False,
                'route':'manual_review','reasons':[]}
        if set(facts)!=set(CONDITIONS) or any(not isinstance(v,str) or not v.strip() for v in facts.values()):
            result['reasons']=['incomplete_conditions'];return result
        value=self._load()
        for versions in value['rules'].values():
            rule=versions[-1]
            if rule['realm']==realm and rule['status']=='published' and rule['candidate']['conditions']==facts:
                if rule['valid_from']<=as_of<=rule['valid_through'] and rule['valid_from']<=timestamp(now()).date().isoformat()<=rule['valid_through']: result['matches'].append(rule)
                else: result['reasons'].append('rule_expired')
        if len(result['matches'])!=1:
            result['reasons'].append('conflict' if len(result['matches'])>1 else 'no_published_match');return result
        rule=result['matches'][0]
        try:
            candidate,analysis=self._candidate(rule['candidate_id'],as_of,realm)
            if candidate['candidate_version']!=rule['candidate_version'] or candidate['conflicted']:
                raise Rejected('人工纠正/撤销/冲突影响原规则，须复核')
            self._live_support(candidate)
            if not allow_automatic: result['reasons'].append('explicit_automatic_request_missing');return result
            policy=self._policy(session,batch,'rule_executor',realm,as_of)
            if digest(policy)!=rule['approval']['policy_hash']: raise Rejected('发布策略已改变，须重新批准')
            config=json.loads((self.source_root/'security/trusted_sessions.json').read_text(encoding='utf-8'))
            if digest(config)!=rule['approval']['execution']['config_hash']: raise Rejected('发布凭据配置已改变，须重新批准')
            grant=next((g for g in config['sessions'] if g['principal']==rule['approval']['execution']['principal'] and g['credential_ref']==rule['approval']['execution']['credential_ref']),None)
            if not grant or 'rule_publisher' not in grant['roles'] or timestamp(grant['expires_at'])<=timestamp(now()):
                raise Rejected('原规则发布凭据已失效')
            if policy.get('production_automatic_enabled') is not True and realm=='formal': raise Rejected('生产自动采用未启用')
            self._quality(candidate,analysis,policy)
            result.update(automatic_adoption=realm=='formal',technical_application_allowed=realm=='test',
                          route='authorized_rule_application',rule_id=rule['id'],rule_version=rule['version'])
        except (Rejected,OSError,ValueError,KeyError,TypeError) as exc:
            result['reasons'].append(str(exc))
        return result

    def apply(self,store,batch_id,row_id,*,facts,as_of,session,reference,expected_hash,realm='formal'):
        """Reuse B2 decision versions/outbox. Automated events never claim human review.

        This applies a final-choice proposal from a released rule. Per-ticket tax
        basis, price, packing and final-release gates still require their own proof.
        """
        if store.root!=self.source_root.resolve(): raise Rejected('规则执行必须使用D1绑定的原B2存储')
        batch=store.load(batch_id);check_sources(batch)
        if batch.get('active_review_lock'): raise Rejected('已锁定批次须先按B2流程明确重开审核')
        request_id=digest([batch_id,row_id,facts,as_of,reference,expected_hash,realm])
        previous=next((r for r in batch.get('rule_application_receipts',{}).values() if r.get('request_id')==request_id),None)
        if previous:
            self._policy(session,batch,'rule_executor',realm,as_of)
            return dict(previous,replayed=True)
        if digest(batch)!=expected_hash: raise Rejected('批次版本已变化')
        row=next(r for r in batch['rows'] if r['id']==row_id)
        if not row['reviews']['identity'] or row['disputes'] or not reference: raise Rejected('商品身份未审、存在争议或缺执行依据')
        # Facts are bound to the current version already captured through B2, not
        # arbitrary request facts invented to force a match.
        from .declaration_decisions import head, revise
        current=head(row)
        if not current or contract(current)[0]!=facts or current['context']!=context(row): raise Rejected('条件不属于当前商品版本')
        with Store(self.library.root).lock(self.library.root/'rule_writes'):
            match=self.match(facts,as_of=as_of,allow_automatic=True,session=session,batch=batch,realm=realm)
            if match['route']!='authorized_rule_application': raise Rejected('规则须转人工：'+','.join(match['reasons']))
            rule=match['matches'][0]; key=digest([batch_id,row_id,rule['id'],rule['version'],facts,as_of])
            if key in batch.get('rule_application_receipts',{}): return dict(batch['rule_application_receipts'][key],replayed=True)
            out=copy.deepcopy(batch);target=next(r for r in out['rows'] if r['id']==row_id)
            values={**facts,**rule['candidate']['target'],'valid_from':rule['valid_from'],
                    'valid_through':rule['valid_through'],'applicability_date':as_of,
                    'classification_basis':reference,'reason':'authorized rule '+rule['id']}
            event=revise(out,target,{},'edit_decision',values,session,reference)
            decision=target['declaration']['versions'][-1]
            decision.update(origin='automatic_rule',automatic_rule_ref={'id':rule['id'],'version':rule['version']},
                            reviews={'material':None,'classification':None},learning_eligible=False,
                            technical_approval_complete=False,state='automatic_rule_applied')
            from .declaration_decisions import pending,review_payload
            for domain in ('material','classification'):
                decision['reviews'][domain]={'confirmed_by':session.principal,'confirmed_at':now(),
                    'reference':reference,'credential_ref':session.credential_ref,'execution_mode':'authorized_rule_automation',
                    'approval_kind':'authorized_rule','rule_id':rule['id'],'rule_version':rule['version'],
                    'payload_hash':digest(review_payload(decision,domain)),'decision_version':decision['version']}
            target['reviews']['material']=dict(decision['reviews']['material'],kind='authorized_rule')
            target['reviews']['tax']=None;target['tax']=None  # per-ticket tax basis is outside a classification rule
            decision['pending']=pending(decision,target)
            decision['technical_approval_complete']=not decision['pending']
            event.update(type='automatic_rule_applied',decision=copy.deepcopy(decision))
            event['event_id']=digest({k:v for k,v in event.items() if k not in ('event_id','transaction_id')})
            receipt={'application_id':key,'request_id':request_id,'rule_id':rule['id'],'rule_version':rule['version'],
                     'knowledge_head':json.loads((self.library.root/'head.json').read_text(encoding='utf-8')),
                     'source_state_hash':expected_hash,'rule_approval_hash':digest(rule['approval']),
                     'event_id':event['event_id'],'realm':realm,'human_training_sample':False,'formal_output':False}
            out.setdefault('rule_application_receipts',{})[key]=receipt
            out=changed(batch,out,session.principal,'authorized_rule_application',[row_id],receipt)
            store.save(out,expected_hash=expected_hash);return receipt

    def impact_report(self,*,as_of):
        rows=[]
        for versions in self._load()['rules'].values():
            rule=versions[-1]
            if rule['status']!='published': continue
            try:
                candidate,_=self._candidate(rule['candidate_id'],as_of,rule['realm'])
                self._live_support(candidate)
                affected=candidate['candidate_version']!=rule['candidate_version'] or candidate['conflicted']
            except (Rejected,OSError,KeyError,ValueError): affected=True
            if affected: rows.append({'rule_id':rule['id'],'version':rule['version'],'action':'manual_revalidation_required'})
        affected={r['rule_id'] for r in rows};applications=[]
        for path in self.source_root.glob('*/head.json'):
            if len(path.parent.name)!=24: continue
            batch=Store(self.source_root).load(path.parent.name)
            for receipt in batch.get('rule_application_receipts',{}).values():
                if receipt['rule_id'] in affected:
                    applications.append({'batch_id':batch['id'],'application_id':receipt['application_id'],
                                         'action':'locked_history_trace_only' if batch.get('active_review_lock') else 'manual_revalidation_required'})
        return {'as_of':as_of,'affected_rules':rows,'affected_applications':applications,
                'new_application_blocked':True,'history_preserved':True}
