"""A-03 scope, durable CAS, cache independence and real process-death recovery."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from a_confirm.support import ROOT, REPO, Rejected, bootstrap, get, key, load, path
bootstrap()
from a_confirm.service import Service, InterruptedSave
from a_confirm.locking import writer
from openpyxl import load_workbook

spec=importlib.util.spec_from_file_location('a03_a22_fixtures',REPO/'a02-native-22/tests/test_native22.py')
fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)


def selection(save=(),confirm=(),adopt=(),evidence=None):
    return {'save_changes':list(save),'confirm_fields':list(confirm),'adopt_candidates':list(adopt),'evidence':evidence or {}}


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.f=fx.Native22Tests('test_normal_rounding_not_red_and_price_raw_retained');self.f.setUp();self.f.prepared()
        self.root=self.f.root;self.service=Service(self.root/'a03');self.registration=self.service.register(str(self.f.context()))
        self.bid=self.registration['batch_id'];self.seq=0

    def tearDown(self):self.f.tearDown()

    def read(self):return self.service.read_current(self.bid)

    def preview(self,changes=None,dialogue=None,upload=None,expected=None):
        state=self.read()
        return self.service.preview_return(self.bid,str(upload or self.f.edited(changes)),expected_hash=expected or state['current_hash'],field_proposals=dialogue)

    def plan(self,preview,scope):return self.service.prepare_confirmation(preview['preview_id'],scope)

    def commit(self,plan,service=None,reference='TEST:explicit user confirmation simulation'):
        return (service or self.service).commit(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference=reference)

    def price_proof(self,state=None):
        return {'source_ref':'TEST:independent purchase record, not Japanese-price fallback',
                'source_kind':'purchase_document',
                'price_basis_hash':(state or self.read())['price_basis_hash'],'currency':'JPY'}

    def test_partial_confirmation_saves_only_selected_changes(self):
        p=self.preview({'E2':'人工名','R2':'人工渠道'})
        plan=self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2']));r=self.commit(plan);state=self.read()
        self.assertEqual(r['revision'],1);self.assertEqual(state['fields']['Sheet1!E2']['value']['value'],'人工名')
        self.assertTrue(state['fields']['Sheet1!E2']['confirmed'])
        self.assertEqual(state['fields']['Sheet1!R2']['status'],'candidate')
        self.assertFalse(state['fields']['Sheet1!R2']['confirmed']);self.assertIn('Sheet1!R2',r['unselected_changes'])
        self.assertFalse(state['can_enter_b']);self.assertEqual(state['professional_approvals'],0)

    def test_missing_explicit_confirmation_or_wrong_hash_cannot_save(self):
        plan=self.plan(self.preview({'E2':'修改'}),selection(['Sheet1!E2'],['Sheet1!E2']))
        before=self.read()['current_hash']
        for explicit,confirmed,reference in [(False,plan['plan_id'],'TEST'),(True,'0'*64,'TEST'),(True,plan['plan_id'],'')]:
            with self.assertRaises(Rejected):self.service.commit(plan['plan_id'],confirmed_hash=confirmed,explicit_confirmation=explicit,reference=reference)
        self.assertEqual(self.read()['current_hash'],before)

    def test_untouched_yellow_not_implicitly_confirmed(self):
        plan=self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2']));self.commit(plan)
        state=self.read()
        for target in ('Sheet1!F2','Sheet1!P2','Sheet1!Q2','Sheet1!R2','Sheet1!S2'):
            self.assertEqual(state['fields'][target]['status'],'candidate');self.assertFalse(state['fields'][target]['confirmed'])

    def test_explicit_candidate_adoption_keeps_reference_provenance(self):
        p=self.preview();plan=self.plan(p,selection(adopt=['Sheet1!E2']))
        self.commit(plan);field=self.read()['fields']['Sheet1!E2']
        self.assertTrue(field['confirmed']);self.assertEqual(field['status'],'adopted_reference');self.assertTrue(field['sources'])
        self.assertTrue(all(not s.get('approval',False) for s in field['sources']))

    def test_candidate_cannot_be_cloaked_as_ordinary_unchanged_confirmation(self):
        with self.assertRaises(Rejected):self.plan(self.preview(),selection(confirm=['Sheet1!E2']))

    def test_saved_red_blank_stays_pending_and_can_save_other_fields(self):
        p=self.preview({'E2':'名称','Q2':None});plan=self.plan(p,selection(['Sheet1!E2','Sheet1!Q2'],['Sheet1!E2']))
        self.commit(plan);state=self.read()
        self.assertEqual(state['saved_pending_fields'],['Sheet1!Q2']);self.assertFalse(state['fields']['Sheet1!Q2']['confirmed'])
        self.assertEqual(state['fields']['Sheet1!Q2']['value']['type'],'blank')
        self.assertTrue(state['fields']['Sheet1!E2']['confirmed'])

    def test_invalid_red_content_cannot_be_confirmed(self):
        p=self.preview({'E2':None})
        with self.assertRaises(Rejected):self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2']))
        self.assertEqual(self.read()['revision'],0)

    def test_material_confirmation_never_is_declaration_approval(self):
        p=self.preview({'Q2':'纸参考'});self.commit(self.plan(p,selection(['Sheet1!Q2'],['Sheet1!Q2'])))
        f=self.read()['fields']['Sheet1!Q2'];self.assertEqual(f['status'],'reference_confirmed');self.assertFalse(f['professional_approval'])

    def test_yd_may_be_explicitly_cleared_and_confirmed(self):
        p=self.preview({'S2':None});self.commit(self.plan(p,selection(['Sheet1!S2'],['Sheet1!S2'])))
        f=self.read()['fields']['Sheet1!S2'];self.assertEqual(f['value']['type'],'blank');self.assertTrue(f['confirmed'])

    def test_repeat_confirmation_even_new_reference_replays_original_receipt(self):
        plan=self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2']))
        first=self.commit(plan);again=self.commit(plan,reference='TEST:second click')
        self.assertTrue(again['replayed']);self.assertEqual(first['transaction_id'],again['transaction_id'])
        self.assertEqual(self.read()['revision'],1);self.assertEqual(len(self.service.history(self.bid)),2)

    def test_partial_followup_rebases_same_upload_without_rollback(self):
        upload=self.f.edited({'E2':'新名称','R2':'新渠道'});p=self.preview(upload=upload)
        self.commit(self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2'])))
        p2=self.preview(upload=upload)
        self.assertNotIn('Sheet1!E2',p2['proposals']);self.assertIn('Sheet1!E2',p2['already_saved'])
        self.commit(self.plan(p2,selection(['Sheet1!R2'],['Sheet1!R2'])))
        state=self.read();self.assertEqual(state['revision'],2)
        self.assertTrue(state['fields']['Sheet1!E2']['confirmed']);self.assertTrue(state['fields']['Sheet1!R2']['confirmed'])

    def test_old_file_cannot_overwrite_saved_value(self):
        self.commit(self.plan(self.preview({'E2':'第一版'}),selection(['Sheet1!E2'],['Sheet1!E2'])))
        before=self.read()['current_hash']
        with self.assertRaises(Rejected):self.preview({'E2':'另一旧版'})
        self.assertEqual(self.read()['current_hash'],before)

    def test_disjoint_old_confirmation_plan_still_conflicts_with_new_head(self):
        p=self.preview({'E2':'名称','R2':'渠道'})
        a=self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2']));b=self.plan(p,selection(['Sheet1!R2'],['Sheet1!R2']))
        self.commit(a)
        with self.assertRaises(Rejected):self.commit(b)
        self.assertEqual(self.read()['revision'],1);self.assertFalse(self.read()['fields']['Sheet1!R2']['confirmed'])

    def test_old_successful_receipt_replays_after_later_versions(self):
        upload=self.f.edited({'E2':'名称','R2':'渠道'});p=self.preview(upload=upload)
        plan=self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2']));first=self.commit(plan)
        p=self.preview(upload=upload);self.commit(self.plan(p,selection(['Sheet1!R2'],['Sheet1!R2'])))
        self.assertEqual(self.commit(plan)['transaction_id'],first['transaction_id']);self.assertEqual(self.read()['revision'],2)

    def test_price_requires_bound_scope_evidence(self):
        p=self.preview({'G2':999})
        for evidence in ({},{'source_ref':'TEST','price_basis_hash':'0'*64,'currency':'JPY'},dict(self.price_proof(),currency='CNY')):
            with self.assertRaises(Rejected):self.plan(p,selection(['Sheet1!G2'],['Sheet1!G2'],evidence={'Sheet1!G2':evidence}))

    def test_retail_or_final_amount_cannot_be_purchase_price_basis(self):
        p=self.preview({'G2':999})
        for kind in ('retail_price','historical_final_amount'):
            with self.assertRaises(Rejected):self.plan(p,selection(['Sheet1!G2'],['Sheet1!G2'],evidence={'Sheet1!G2':dict(self.price_proof(),source_kind=kind)}))

    def test_price_can_be_saved_pending_then_explicitly_adopted_later(self):
        p=self.preview({'G2':999});self.commit(self.plan(p,selection(['Sheet1!G2'])))
        state=self.read();self.assertFalse(state['fields']['Sheet1!G2']['confirmed'])
        self.assertEqual(state['pricing_counts'],{'manual_purchase_price_pending_source':1})
        p=self.preview(upload=self.f.base)
        plan=self.plan(p,selection(confirm=['Sheet1!G2'],evidence={'Sheet1!G2':self.price_proof()}));self.commit(plan)
        self.assertEqual(self.read()['pricing_counts'],{'within_100_jpy':1});self.assertFalse(self.read()['can_enter_b'])

    def test_price_red_does_not_pass_just_because_saved(self):
        p=self.preview({'G2':10000})
        self.commit(self.plan(p,selection(['Sheet1!G2'])))
        self.assertEqual(self.read()['pricing_counts'],{'manual_purchase_price_pending_source':1})

    def test_formula_box_override_saved_in_backend_without_editing_formula(self):
        before=self.f.base.read_bytes();p=self.preview(dialogue=[{'sheet':'Sheet1','cell':'H2','value':{'type':'number','value':'7'},'message_ref':'TEST:每盒7件'}])
        plan=self.plan(p,selection(['Sheet1!H2'],['Sheet1!H2'],evidence={'Sheet1!H2':{'source_ref':'TEST:每盒7件依据','meaning':'pieces_per_box'}}))
        self.commit(plan);state=self.read();self.assertEqual(state['fields']['Sheet1!H2']['value']['value'],'7')
        self.assertEqual(state['calculated_cells'][0]['difference_jpy'],'100.00');self.assertEqual(self.f.base.read_bytes(),before)
        self.assertTrue(state['fields']['Sheet1!H2']['working_formula'].startswith('=IFERROR'))

    def test_zero_box_confirmation_rejected_even_with_evidence(self):
        p=self.preview(dialogue=[{'sheet':'Sheet1','cell':'H2','value':{'type':'number','value':'0'},'message_ref':'TEST:无效0'}])
        with self.assertRaises(Rejected):self.plan(p,selection(['Sheet1!H2'],['Sheet1!H2'],evidence={'Sheet1!H2':{'source_ref':'TEST','meaning':'pieces_per_box'}}))

    def test_source_formula_or_quantity_edits_cannot_be_saved(self):
        for a in ('M2','O2','H2','U2','J2','N2'):
            with self.assertRaises(Rejected):self.preview({a:99})
        with self.assertRaises(Rejected):self.preview(dialogue=[{'sheet':'Sheet1','cell':'M2','value':{'type':'number','value':'99'},'message_ref':'TEST'}])
        self.assertEqual(self.read()['revision'],0)

    def test_source_change_after_plan_blocks_save_without_overwriting(self):
        p=self.preview({'E2':'名称'});plan=self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2']))
        raw=self.f.source.read_bytes()
        try:
            self.f.source.write_bytes(raw+b'TEST change')
            with self.assertRaisesRegex(ValueError,'源文件已变更'):self.commit(plan)
        finally:self.f.source.write_bytes(raw)
        self.assertEqual(self.read()['revision'],0)

    def test_upload_archive_tamper_prevents_confirmation(self):
        p=self.preview({'E2':'名称'});file=path(self.service.root/'objects'/(p['upload_sha256']+'.xlsx'));original=file.read_bytes()
        try:
            file.write_bytes(b'TEST corrupted')
            with self.assertRaises(Rejected):self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2']))
        finally:file.write_bytes(original)
        self.assertEqual(self.read()['revision'],0)

    def test_plan_tamper_prevents_save(self):
        plan=self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2']))
        file=path(self.service.root/'objects'/(plan['plan_id']+'.json'));raw=file.read_bytes();file.write_bytes(b'{}')
        try:
            with self.assertRaises(Rejected):self.commit(plan)
        finally:file.write_bytes(raw)
        self.assertEqual(self.read()['revision'],0)

    def test_existing_non_service_directory_is_never_used_for_saves(self):
        with self.assertRaises(Rejected):Service(self.f.output)

    def test_confirmation_scope_cannot_include_protected_or_wildcard_cells(self):
        p=self.preview({'E2':'名称'})
        for target in ('*','Sheet1!M2','Sheet1!U2','Sheet1!E999'):
            with self.assertRaises(Rejected):self.plan(p,selection([target],[target]))

    def test_read_fresh_process_and_history_match_saved_version(self):
        self.commit(self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2'])))
        fresh=Service(self.service.root);self.assertEqual(fresh.read_current(self.bid),self.read())
        self.assertEqual([r['revision'] for r in fresh.history(self.bid)],[0,1])

    def test_registered_export_remains_immutable_and_reimport_does_not_reset(self):
        self.commit(self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2'])))
        r=self.service.register(str(self.f.context()));self.assertEqual(r['status'],'already_registered');self.assertEqual(r['revision'],1)

    def test_partial_confirm_after_newer_head_needs_fresh_preview(self):
        p=self.preview({'E2':'名称','R2':'渠道'});self.commit(self.plan(p,selection(['Sheet1!E2'],['Sheet1!E2'])))
        with self.assertRaises(Rejected):self.plan(p,selection(['Sheet1!R2'],['Sheet1!R2']))

    def test_active_process_lock_is_not_deleted(self):
        plan=self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2']))
        with writer(self.service.root,self.bid):
            with self.assertRaises(Rejected):self.commit(plan)
        self.assertEqual(self.read()['revision'],0)

    def test_exception_before_head_keeps_old_version_and_retry_is_single(self):
        from arrival_core import storage
        plan=self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2']));real=storage.atomic_json
        def failed(p,v):
            if p.name=='head.json':raise OSError('TEST before HEAD')
            return real(p,v)
        with patch.object(storage,'atomic_json',side_effect=failed):
            with self.assertRaises(InterruptedSave):self.commit(plan)
        self.assertEqual(self.read()['revision'],0);self.assertEqual(len(self.service.history(self.bid)),1)
        self.commit(plan);self.assertEqual(self.read()['revision'],1);self.assertEqual(len(self.service.history(self.bid)),2)

    def test_exception_after_head_is_recognized_as_saved(self):
        from arrival_core import storage
        plan=self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2']));real=storage.atomic_json
        def failed(p,v):
            result=real(p,v)
            if p.name=='head.json':raise OSError('TEST after HEAD')
            return result
        with patch.object(storage,'atomic_json',side_effect=failed):receipt=self.commit(plan)
        self.assertEqual(receipt['status'],'saved');self.assertTrue(receipt['recovered_after_exception'])
        self.assertEqual(self.read()['revision'],1);self.assertTrue(self.commit(plan)['replayed'])

    def test_post_head_read_error_reports_uncertain_and_replays_after_restart(self):
        plan=self.plan(self.preview({'E2':'名称'}),selection(['Sheet1!E2'],['Sheet1!E2']));real=self.service.store.load
        def failed(bid):
            value=real(bid)
            if value['revision']==1:raise OSError('TEST read after HEAD')
            return value
        with patch.object(self.service.store,'load',side_effect=failed):
            with self.assertRaisesRegex(InterruptedSave,'暂不能核实'):self.commit(plan)
        fresh=Service(self.service.root);self.assertEqual(fresh.read_current(self.bid)['revision'],1)
        self.assertTrue(self.commit(plan,service=fresh)['replayed'])

    def crash_and_recover(self,mode):
        plan=self.plan(self.preview({'E2':'崩溃恢复后名称'}),selection(['Sheet1!E2'],['Sheet1!E2']))
        script=ROOT/'tests/process_fault.py'
        env=dict(os.environ,PYTHONPATH=str(ROOT));r=subprocess.run([sys.executable,'-X','utf8','-B',str(script),str(self.service.root),plan['plan_id'],mode],env=env,capture_output=True,timeout=60)
        self.assertEqual(r.returncode,71 if mode=='before' else 72,r.stderr.decode())
        fresh=Service(self.service.root);state=fresh.read_current(self.bid)
        self.assertEqual(state['revision'],0 if mode=='before' else 1)
        receipt=self.commit(plan,service=fresh);self.assertTrue(receipt['recovered_stale_lock'])
        self.assertEqual(fresh.read_current(self.bid)['revision'],1);self.assertEqual(len(fresh.history(self.bid)),2)
        self.assertTrue(self.commit(plan,service=fresh)['replayed'])

    def test_real_process_death_before_head_is_recoverable(self):self.crash_and_recover('before')
    def test_real_process_death_after_head_does_not_duplicate_save(self):self.crash_and_recover('after')

    def test_changed_basis_invalidates_old_b_c_confirmation_and_reviews(self):
        base=self.service.store.load(self.bid);out=deepcopy(base);out['revision']+=1
        out['a03']['parent_hash']=key(base);out['a03']['version_id']=key({'TEST':'existing B confirmation'})
        out['a03']['downstream']={'b_confirmation_valid':True,'c_delivery_valid':True,'recompute_required':False,'input_fingerprint':'TEST:old'}
        out['rows'][0]['reviews']['price']={'TEST':'old calculation confirmation'}
        with writer(self.service.root,self.bid):self.service.store.save(out,expected_hash=key(base))
        self.commit(self.plan(self.preview({'E2':'新名称'}),selection(['Sheet1!E2'],['Sheet1!E2'])))
        state=self.read();self.assertFalse(state['downstream']['b_confirmation_valid']);self.assertFalse(state['downstream']['c_delivery_valid'])
        self.assertTrue(state['downstream']['recompute_required']);self.assertIsNone(state['downstream']['input_fingerprint'])
        self.assertIsNone(self.service.store.load(self.bid)['rows'][0]['reviews']['price'])

    def test_16_column_compatibility_uses_same_save_boundary(self):
        req=self.f.f.request();self.f.prepared(req);self.f.batch=req['batch_id']
        service=Service(self.root/'legacy-a03');reg=service.register(str(self.f.context()));bid=reg['batch_id']
        state=service.read_current(bid);p=service.preview_return(bid,str(self.f.edited({'E2':'16列名称'})),expected_hash=state['current_hash'])
        plan=service.prepare_confirmation(p['preview_id'],selection(['Sheet1!E2'],['Sheet1!E2']))
        r=self.commit(plan,service=service);self.assertEqual(r['revision'],1);self.assertEqual(service.read_current(bid)['fields']['Sheet1!E2']['value']['value'],'16列名称')

    def test_uploaded_formula_cache_is_never_the_saved_price_authority(self):
        self.f.edit_source({'G2':'=1+799'})
        fx.fx.rewrite(self.f.source,lambda n,d:d.replace(b'<f>1+799</f><v></v>',b'<f>1+799</f><v>800</v>') if n.endswith('sheet1.xml') else d)
        self.f.prepared();service=Service(self.root/'cache-a03');reg=service.register(str(self.f.context()));bid=reg['batch_id']
        upload=self.root/'cache-changed.xlsx';upload.write_bytes(self.f.base.read_bytes())
        fx.fx.rewrite(upload,lambda n,d:d.replace(b'<f>1+799</f><v>800</v>',b'<f>1+799</f><v>1</v>') if n.endswith('sheet1.xml') else d)
        current=service.read_current(bid);p=service.preview_return(bid,str(upload),expected_hash=current['current_hash'])
        plan=service.prepare_confirmation(p['preview_id'],selection(adopt=['Sheet1!E2']));self.commit(plan,service=service)
        state=service.read_current(bid);self.assertEqual(state['pricing_counts'],{'within_100_jpy':1})
        self.assertEqual(state['calculated_cells'][0]['pieces_per_box'],'8');self.assertFalse(state['returned_formula_cache_used'])


if __name__=='__main__':unittest.main()
