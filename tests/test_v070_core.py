"""Portable synthetic technical tests. No fixture is a formal business sample."""
import copy, hashlib, json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'workbuddy/japan-arrival-customs/scripts'))
from arrival_core.core import Rejected, digest, new_batch, new_row, context
from arrival_core.storage import Store, atomic_json
from arrival_core.classification_contract import contract
from arrival_core.d2_candidates import discover, replay, snapshot, cutoff_for, analyze_library
from arrival_core.decision_library import DecisionLibrary
from arrival_core.rule_registry import RuleRegistry
from arrival_core.return_auth import load_session
from arrival_core.contracts import create_contract, sign_contract, ROLES
from arrival_core.declaration_decisions import revise
from arrival_core.source_adapters import status, read_feishu, read_official, quote_composition, normalize_records

def version(identifier,group=None,day='01',code=None):
    facts={'product_type':'TEST ornament','purpose':'TEST display','complete_composition':'PVC、铁、纸等',
           'key_material_features':'plastic body','construction':'no electronics','version':'v1','specification':'s1',
           'inclusion_conditions':'explicit ornament','exclusion_conditions':'exclude electronics'}
    final={'declaration_material':'TEST plastic','classification_code':'TEST-HS', 'classification_basis':'TEST evidence',
           'duty_rate':'0','vat_rate':'0.13','tariff_schedule_version':'TEST-2026','valid_from':'2026-01-01',
           'valid_through':'2026-12-31','applicability_date':'2026-10-'+day,'jurisdiction':'TEST',
           'origin_conditions':'JP','trade_conditions':'TEST normal trade'}
    return {'batch_id':'batch-'+identifier,'decision_id':identifier,'event_id':'event-'+identifier,'version':1,
            'source_bundle':'bundle-'+identifier,'event_time':'2026-10-'+day+'T00:00:00Z',
            'available_at':'2026-10-'+day+'T00:00:01Z','technical_fixture':True,
            'independent_approval_group':group or 'group-'+identifier,
            'decision':{'row_id':'row-'+identifier,'context':{'code':code or identifier,'version':'v1','specification':'s1'},
                        'facts':facts,'human_final':final,'state':'effective'}}

def report(records):
    return {'discovery':discover(snapshot(records,cutoff_for('2026-10-21')),as_of='2026-10-21',realm='test'),
            'validation':replay(records,as_of='2026-10-21',realm='test')}

class D2Tests(unittest.TestCase):
    def setUp(self): self.records=[version('a',day='01'),version('b',day='02'),version('c',day='03')]
    def test_empty_formal_has_no_fabricated_accuracy(self):
        r=discover([],as_of='2026-10-21');v=replay([],as_of='2026-10-21')
        self.assertEqual(r['formal_current_decisions'],0);self.assertEqual(v['metrics']['joint_accuracy']['denominator'],0)
        self.assertIsNone(v['metrics']['joint_accuracy']['value'])
    def test_test_fixtures_cannot_become_formal(self):
        r=discover(snapshot(self.records,cutoff_for('2026-10-21')),as_of='2026-10-21')
        self.assertEqual(r['candidates'],[])
    def test_bulk_approval_counts_once(self):
        self.records[1]['independent_approval_group']=self.records[0]['independent_approval_group']
        r=report(self.records[:2])['discovery']['candidates'][0]
        self.assertEqual(r['independent_support_count'],1);self.assertEqual(r['status'],'case_reference_only')
    def test_same_jan_reapprovals_not_independent_support(self):
        self.records[1]['decision']['context']['code']='a'
        self.assertEqual(report(self.records[:2])['discovery']['candidates'][0]['independent_support_count'],1)
    def test_cross_jan_candidate_has_traceable_support(self):
        r=report(self.records)['discovery']['candidates'][0]
        self.assertEqual(r['identity_count'],3);self.assertEqual(len(r['support']),3);self.assertFalse(r['automatic_adoption'])
    def test_unknown_condition_is_not_wildcard(self):
        self.records[0]['decision']['facts']['construction']=''
        self.assertEqual(report(self.records[:1])['discovery']['candidates'],[])
    def test_conflicting_targets_are_quarantined(self):
        self.records[1]['decision']['human_final']['classification_code']='TEST-DIFFERENT'
        r=report(self.records)['discovery'];self.assertEqual(len(r['conflicts']),1)
        self.assertTrue(all(c['conflicted'] for c in r['candidates']))
    def test_chronological_holdout_has_explicit_denominators(self):
        r=report(self.records)['validation'];self.assertEqual(r['metrics']['coverage']['numerator'],1)
        self.assertEqual(r['metrics']['coverage']['denominator'],3);self.assertEqual(r['metrics']['joint_accuracy']['denominator'],1)
    def test_future_import_not_available_to_past_decision(self):
        self.records[0]['available_at']='2026-10-20T00:00:00Z'
        self.assertEqual(report(self.records)['validation']['metrics']['coverage']['numerator'],0)
    def test_future_revocation_not_visible_before_cutoff(self):
        revoked=copy.deepcopy(self.records[0]);revoked.update(version=2,event_id='revoked',event_time='2026-10-22T00:00:00Z',available_at='2026-10-22T00:00:01Z')
        revoked['decision']['state']='revoked';self.records.append(revoked)
        self.assertEqual(len(report(self.records)['discovery']['candidates'][0]['support']),3)
        newer=discover(snapshot(self.records,cutoff_for('2026-10-23')),as_of='2026-10-23',realm='test')
        self.assertEqual(len(newer['candidates'][0]['support']),2)
    def test_same_approval_cannot_leak_across_holdout(self):
        self.records[2]['independent_approval_group']=self.records[0]['independent_approval_group']
        r=report(self.records)['validation'];self.assertEqual(r['metrics']['coverage']['numerator'],0)
    def test_counterexample_records_joint_mismatch(self):
        self.records[2]['decision']['human_final']['declaration_material']='TEST metal'
        r=report(self.records)['validation'];self.assertEqual(len(r['counterexamples']),1)
        self.assertEqual(r['metrics']['joint_accuracy']['numerator'],0)
    def test_d1_adapter_empty_and_late_fixture_eligibility(self):
        with tempfile.TemporaryDirectory() as d:
            lib=DecisionLibrary.create(Path(d)/'library',source_root=Path(d)/'store',source_kind='synthetic')
            self.assertEqual(analyze_library(lib,as_of='2026-10-21')['discovery']['formal_current_decisions'],0)

class D3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        src=self.root/'inputs'/'source.txt';src.parent.mkdir();src.touch()
        source={'path':str(src),'sha256':hashlib.sha256(b'').hexdigest(),'sheet':'TEST','row':2}
        row=new_row(source,{'amount':'10','qty':'1','code':'new','variant':'v1','ja':'TEST','carton':'1'},currency='JPY',quantity_unit='piece')
        row['identity']['specification']='s1';row['reviews']['identity']={'confirmed_by':'TECH','confirmed_at':'2026-10-21','reference':'TEST identity'}
        self.batch=new_batch([row],[source]);self.batch['execution_mode']='synthetic_technical_test'
        ctr=create_contract(src,src,src,'TEST');ctr['responsibilities']={r:['TECH'] for r in ROLES}
        ctr.update(authority_quantity_unit='piece',invoice_quantity_unit='piece')
        self.batch['input_contract']=sign_contract(ctr,actor='TECH',evidence='TEST ONLY D08',permissions={'TECH':['contract']})
        self.store=Store(self.root/'store');self.store.save(self.batch)
        security=self.store.root/'security';security.mkdir()
        self.token='TEST-ONLY-NOT-A-BUSINESS-CREDENTIAL'
        roles=['customs','material','rule_publisher','rule_executor']
        atomic_json(security/'trusted_sessions.json',{'purpose':'synthetic_technical_test','sessions':[{
            'principal':'TECH','roles':roles,'mode':'synthetic_technical_test','credential_ref':'TECH-ONLY',
            'token_sha256':hashlib.sha256(self.token.encode()).hexdigest(),
            'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}]})
        self.session=load_session(self.store.root,self.token)
        self.policy={'realm':'test','quality_approved':True,'approval_reference':'TECH policy','approved_by':'TECH',
                     'credential_ref':'TECH-ONLY','publishers':['TECH'],'executors':['TECH'],
                     'valid_from':'2026-01-01','valid_through':'2026-12-31','production_automatic_enabled':False,
                     'thresholds':{'min_independent_support':2,'min_validation_decisions':3,'min_covered_decisions':1,'min_joint_accuracy':'1'}}
        atomic_json(security/'rule_policy.json',self.policy)
        self.library=DecisionLibrary.create(self.root/'knowledge',source_root=self.store.root,source_kind='synthetic')
        self.registry=RuleRegistry(self.library.root/'rule_registry.json',library=self.library)
        self.analysis=report([version('a',day='01'),version('b',day='02'),version('c',day='03')])
        self.mock=patch.object(self.registry,'_analysis',side_effect=lambda *args:self.analysis);self.mock.start()
        self.candidate=self.analysis['discovery']['candidates'][0];self.facts=self.candidate['conditions']
        self.rule=self.registry.draft(self.candidate['candidate_id'],as_of='2026-10-21',realm='test')
    def tearDown(self): self.mock.stop();self.tmp.cleanup()
    def publish(self):
        return self.registry.publish(self.rule['id'],session=self.session,batch=self.batch,reference='TECH publish',as_of='2026-10-21',expected_version=self.rule['version'])
    def match(self,**kw):
        params={'as_of':'2026-10-21','allow_automatic':True,'session':self.session,'batch':self.batch,'realm':'test'};params.update(kw)
        return self.registry.match(self.facts,**params)
    def test_unapproved_rule_cannot_apply(self): self.assertEqual(self.match()['route'],'manual_review')
    def test_published_technical_rule_not_production_authority(self):
        self.publish();r=self.match();self.assertTrue(r['technical_application_allowed']);self.assertFalse(r['automatic_adoption'])
    def test_expired_rule_manual(self): self.publish();self.assertEqual(self.match(as_of='2027-01-01')['route'],'manual_review')
    def test_wrong_structure_use_composition_manual(self):
        self.publish()
        for field in ('construction','purpose','complete_composition'):
            facts=dict(self.facts);facts[field]='DIFFERENT'
            self.assertEqual(self.registry.match(facts,as_of='2026-10-21',realm='test')['route'],'manual_review')
    def test_revoked_old_version_cannot_apply(self):
        r=self.publish();self.registry.transition(r['id'],'revoked',session=self.session,batch=self.batch,reference='TECH revoke',as_of='2026-10-21',expected_version=r['version'])
        self.assertEqual(self.match()['route'],'manual_review');self.assertEqual(len(self.registry._load()['rules'][r['id']]),3)
    def test_synthetic_publisher_cannot_enter_formal_registry(self):
        with self.assertRaises(Rejected):self.registry._policy(self.session,self.batch,'rule_publisher','formal','2026-10-21')
    def test_spoofed_session_and_missing_D08_denied(self):
        with self.assertRaises(Rejected):self.registry.publish(self.rule['id'],session={'principal':'TECH'},batch=self.batch,reference='x',as_of='2026-10-21',expected_version=1)
        b=copy.deepcopy(self.batch);del b['input_contract']
        with self.assertRaises(Rejected):self.registry.publish(self.rule['id'],session=self.session,batch=b,reference='x',as_of='2026-10-21',expected_version=1)
    def test_quality_gate_has_no_default(self):
        del self.policy['thresholds'];atomic_json(self.store.root/'security/rule_policy.json',self.policy)
        with self.assertRaises(Rejected):self.publish()
    def test_correction_invalidates_support(self):
        self.publish();self.analysis['discovery']['candidates'][0]['candidate_version']='changed'
        self.assertEqual(self.match()['route'],'manual_review');self.assertEqual(len(self.registry.impact_report(as_of='2026-10-21')['affected_rules']),1)
    def test_two_matching_rules_do_not_choose_one(self):
        r=self.publish();value=self.registry._load();another=copy.deepcopy(r);another['id']='another'
        value['rules']['another']=[another];self.registry._record(value,'TEST conflicting fixture',another,{})
        self.assertIn('conflict',self.match()['reasons'])
    def test_stale_publish_and_tampered_state_denied(self):
        with self.assertRaises(Rejected):self.registry.publish(self.rule['id'],session=self.session,batch=self.batch,reference='x',as_of='2026-10-21',expected_version=0)
        value=self.registry._load();value['rules'][self.rule['id']][-1]['status']='published';atomic_json(self.registry.path,value)
        with self.assertRaises(Rejected):self.registry._load()
    def test_rule_application_uses_B2_outbox_and_is_not_human_learning(self):
        self.publish();batch=self.store.load(self.batch['id']);row=batch['rows'][0]
        values={**version('new')['decision']['facts'],**version('new')['decision']['human_final'],'reason':'TEST'}
        revise(batch,row,{},'edit_decision',values,self.session,'TEST facts')
        # Save through normal immutable revision/CAS, never edit a stored snapshot.
        from arrival_core.core import changed
        before=self.store.load(batch['id']);batch=changed(before,batch,'TECH','TEST seed',[row['id']],{})
        self.store.save(batch,expected_hash=digest(before));expected=digest(batch)
        result=self.registry.apply(self.store,batch['id'],row['id'],facts=self.facts,as_of='2026-10-21',session=self.session,reference='TEST execute',expected_hash=expected,realm='test')
        updated=self.store.load(batch['id']);self.assertEqual(updated['decision_events'][-1]['type'],'automatic_rule_applied')
        from arrival_core.excel_return import decision_event_stream
        self.assertEqual(len(list(decision_event_stream(updated))),2)
        self.assertFalse(updated['rows'][0]['declaration']['versions'][-1]['learning_eligible'])
        self.library.import_batch(batch['id']);self.assertEqual(self.library.statistics(as_of='2026-10-21')['formal_learning_samples'],0)
        retry=self.registry.apply(self.store,batch['id'],row['id'],facts=self.facts,as_of='2026-10-21',session=self.session,reference='TEST execute',expected_hash=expected,realm='test')
        self.assertTrue(retry['replayed']);self.assertEqual(result['event_id'],retry['event_id'])

class SourceTests(unittest.TestCase):
    def test_unconfigured_is_not_connected(self): self.assertEqual(status()['feishu_product']['state'],'not_configured')
    def test_unauthorized_source_never_calls_network(self):
        with self.assertRaises(Rejected):read_feishu('feishu_product',{},transport=lambda *a:self.fail('network called'))
    def test_real_metadata_mapping_and_all_pages_preserve_composition(self):
        config={'read_authorized':True,'authorization_reference':'TEST','app_token':'TEST','table_id':'TEST','token_env':'TEST_FEISHU_TOKEN',
                'mapping':{'identity':'f1','version':'f2','specification':'f3','complete_composition':'f4'},
                'mapping_reference':'TEST actual metadata','identity_binding':{'source_field_id':'f1','reference':'TEST JAN meaning'}}
        fields=[{'field_id':'f'+str(i),'field_name':'name'+str(i)} for i in range(1,5)]
        calls=[]
        def transport(url,headers):
            calls.append(url)
            if '/fields?' in url:data={'items':fields,'has_more':False}
            elif 'page_token=' not in url:data={'items':[{'record_id':'r1','fields':{'name1':'TEST-JAN','name2':'v1','name3':'s1','name4':[{'text':'PVC、铁、纸等'}]}}],'has_more':True,'page_token':'next'}
            else:data={'items':[{'record_id':'r2','fields':{'name1':'TEST-JAN2','name2':'v1','name3':'s1','name4':'PVC'}}],'has_more':False}
            return json.dumps({'code':0,'data':data},ensure_ascii=False).encode()
        with patch.dict(os.environ,{'TEST_FEISHU_TOKEN':'TEST-ONLY'}):result=read_feishu('feishu_product',config,transport=transport)
        self.assertEqual(len(calls),3);self.assertEqual(result['rows'][0]['values']['complete_composition'],'PVC、铁、纸等')
        self.assertFalse(result['real_connection_verified']);self.assertNotIn('TEST-ONLY',json.dumps(result))
    def test_unknown_field_mapping_rejected(self):
        with self.assertRaises(Rejected):normalize_records('feishu_product',[],[],{'identity':'missing','version':'f2','specification':'f3'},mapping_reference='x',source={},identity_binding={},collected_at='x')
    def test_official_source_preserves_original_and_identity(self):
        cfg={'read_authorized':True,'authorization_reference':'TEST','official_hosts':['official.example']}
        ev=read_official('https://official.example/product',cfg,identity_evidence={'code':'TEST','version':'v1','specification':'s1','reference':'TEST match'},transport=lambda *a:'<p>PVC、鉄、紙等</p>'.encode())
        quoted=quote_composition(ev,'PVC、鉄、紙等','PVC、铁、纸等');self.assertFalse(quoted['approval']);self.assertEqual(quoted['complete_composition']['original'],'PVC、鉄、紙等')
        with self.assertRaises(Rejected):read_official('https://unapproved.example',cfg,identity_evidence={})

class D1LifecycleIntegration(unittest.TestCase):
    """Actual D1 bundles/commits feed D2 then D3; authority stays TEST-only."""
    def setUp(self):
        D3Tests.setUp(self);self.mock.stop()
        config=json.loads((self.store.root/'security/trusted_sessions.json').read_text(encoding='utf-8'))
        config['purpose']='authorized_test_fixture';config['sessions'][0]['mode']='business'
        atomic_json(self.store.root/'security/trusted_sessions.json',config)
        self.session=load_session(self.store.root,self.token)
        self.library=DecisionLibrary.create(self.root/'real-D1-test',source_root=self.store.root,source_kind='authorized_test_fixture')
        self.template=copy.deepcopy(self.batch)
        for i in range(3):
            b=self.fixture(str(i));self.store.save(b);before=copy.deepcopy(b)
            row=b['rows'][0];params={**version(str(i))['decision']['facts'],**version(str(i))['decision']['human_final'],'reason':'AUTHORIZED TEST ONLY'}
            for action,values in (('edit_decision',params),('approve_material',{}),('approve_classification',{})):
                revise(b,row,{},action,values,self.session,'TEST independent approval '+str(i))
            from arrival_core.core import changed
            b=changed(before,b,'TECH','TEST independent approval',[row['id']],{})
            self.store.save(b,expected_hash=digest(before));self.library.import_batch(b['id'])
        self.registry=RuleRegistry(self.library.root/'rule_registry.json',library=self.library)
        analysis=analyze_library(self.library,as_of=datetime.now(timezone.utc).date().isoformat(),realm='test')
        self.candidate=analysis['discovery']['candidates'][0];self.facts=self.candidate['conditions']
        self.batch=b;self.analysis=analysis
        self.rule=self.registry.draft(self.candidate['candidate_id'],as_of='2026-10-21',realm='test')
    tearDown=D3Tests.tearDown
    publish=D3Tests.publish
    match=D3Tests.match
    def fixture(self,name):
        b=copy.deepcopy(self.template);b['id']=digest(['AUTHORIZED-TEST',name])[:24]
        b['execution_mode']='authorized_test_fixture';b['test_fixture_id']='EXPLICIT-NOT-BUSINESS-'+name
        b['rows'][0]['id']=digest(['TEST-row',name])[:24];b['rows'][0]['identity']['code']='TEST-'+name
        return b
    def test_real_D1_D2_D3_technical_lifecycle(self):
        self.assertEqual(self.library.statistics(as_of='2026-10-21')['formal_learning_samples'],0)
        self.assertEqual(self.candidate['independent_support_count'],3)
        self.assertEqual(self.analysis['validation']['metrics']['coverage']['numerator'],1)
        self.publish()
        b=self.fixture('next');self.store.save(b);before=copy.deepcopy(b)
        row=b['rows'][0];params={**version('next')['decision']['facts'],**version('next')['decision']['human_final'],'reason':'TEST new facts'}
        revise(b,row,{},'edit_decision',params,self.session,'TEST facts only')
        from arrival_core.core import changed
        b=changed(before,b,'TECH','TEST new facts',[row['id']],{});self.store.save(b,expected_hash=digest(before))
        from arrival_core.workflow import execute
        with patch.dict(os.environ,{'TECH_RULE_SESSION':self.token}):
            response=execute(self.store.root,{'message':'应用已授权归类规则','batch':b['id'],'row':row['id'],
                'facts':self.facts,'as_of':'2026-10-21','reference':'TEST rule execution','expected_hash':digest(b),
                'session_token_env':'TECH_RULE_SESSION','library':str(self.library.root),'registry':str(self.registry.path),'realm':'test'})
        result=response['result']
        self.library.import_batch(b['id']);stats=self.library.statistics(as_of='2026-10-21')
        self.assertEqual(stats['formal_learning_samples'],0);self.assertEqual(stats['test_learning_samples'],3)
        self.assertFalse(result['human_training_sample'])
    def test_real_D1_revocation_blocks_reuse_and_reports_impact(self):
        self.publish();before=self.store.load(self.batch['id']);b=copy.deepcopy(before)
        revise(b,b['rows'][0],{},'revoke_decision',{'reason':'TEST revoke evidence'},self.session,'TEST revoke')
        from arrival_core.core import changed
        b=changed(before,b,'TECH','TEST revoke',[b['rows'][0]['id']],{});self.store.save(b,expected_hash=digest(before));self.library.import_batch(b['id'])
        self.assertEqual(self.match()['route'],'manual_review')
        self.assertEqual(len(self.registry.impact_report(as_of='2026-10-21')['affected_rules']),1)
    def test_unrelated_batch_revision_does_not_change_independent_support(self):
        self.publish();before=self.store.load(self.batch['id']);b=copy.deepcopy(before)
        from arrival_core.core import changed
        b=changed(before,b,'TECH','TEST unrelated audit',[],{})
        self.store.save(b,expected_hash=digest(before));self.library.import_batch(b['id'])
        self.assertTrue(self.match()['technical_application_allowed'])
    def test_saved_B2_revocation_blocks_rule_even_before_D1_retry(self):
        self.publish();before=self.store.load(self.batch['id']);b=copy.deepcopy(before)
        revise(b,b['rows'][0],{},'revoke_decision',{'reason':'TEST saved revocation'},self.session,'TEST unsynced revoke')
        from arrival_core.core import changed
        b=changed(before,b,'TECH','TEST unsynced revoke',[b['rows'][0]['id']],{})
        self.store.save(b,expected_hash=digest(before))
        self.assertEqual(self.match()['route'],'manual_review')


if __name__=='__main__':unittest.main()
