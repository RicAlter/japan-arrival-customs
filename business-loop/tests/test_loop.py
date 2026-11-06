import os,sys,tempfile,unittest,importlib.util
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from loop.support import bootstrap,load,save,get,key,digest,Rejected
bootstrap()
from loop.prices import candidate
from loop import review
class Prices(unittest.TestCase):
    def p(self,lo,hi,**k):return candidate(lo,hi,**{'purchase_confirmed':True,'minimum_unit_confirmed':True,'actual_price':True,'comparable':True,**k})
    def test_roles_are_maximum_divided_by_minimum(self):self.assertEqual(self.p('100','600')['pieces_per_box'],'6')
    def test_noninteger_is_never_rounded_into_box_size(self):self.assertEqual(self.p('200','1050')['reason'],'noninteger_price_ratio_no_rounding')
    def test_source_precision_not_two_decimal_display(self):self.assertEqual(self.p('100.004','500')['status'],'manual')
    def test_exact_subcent_ratio_survives_legacy_display_unavailable(self):self.assertEqual(self.p('.0005','.003')['pieces_per_box'],'6')
    def test_unconfirmed_purchase_not_used(self):self.assertEqual(self.p('100','600',purchase_confirmed=False)['pieces_per_box'],None)
    def test_unknown_minimum_unit_not_used(self):self.assertEqual(self.p('100','600',minimum_unit_confirmed=False)['status'],'manual')
    def test_official_or_observed_price_not_actual(self):self.assertEqual(self.p('100','600',actual_price=False)['reason'],'actual_japanese_price_unconfirmed')
    def test_different_price_roles_or_currency_not_comparable(self):self.assertEqual(self.p('100','600',comparable=False)['status'],'manual')
    def test_zero_negative_and_missing_prices(self):
        for lo,hi in [('0','600'),('-1','600'),('1','0'),(None,'600'),('100','NaN')]:self.assertEqual(self.p(lo,hi)['status'],'manual')
    def test_existing_round0_preserved(self):
        from arrival_core.colored_operations import round0
        self.assertEqual(round0('346.5'),347)
    def test_manual_basis_does_not_force_noninteger_candidate_to_integer(self):
        row={'parent_id':'id','raw':{'quantity':'2','price':'1050'},'basic_fields':{},'values':[None]*7,
            'price_check':self.p('200','1050')}
        r=review.recalculate(row,{'amount':'2100','factor':'5','max_unit':'盒','qty_unit':'盒','declaration_unit':'个','conversion_reference':'manual guess'},'TEST')
        self.assertIn('noninteger_price_ratio_no_rounding',r['errors'])
    def nonbox(self,qty,boxes):
        row={'parent_id':'SYNTHETIC','raw':{'quantity':str(qty),'price':'600'},'basic_fields':{n:{'confirmed':True} for n in ['internal_name','specification','category','channel','yd']},'values':[None]*6+['个'],'price_check':self.p('100','600')}
        return review.recalculate(row,{'amount':str(qty*600),'factor':'6','max_unit':'套','qty_unit':'套','declaration_unit':'个','boxes':boxes},'SYNTHETIC scope')
    def test_nonbox_maximum_unit_needs_independent_box_count(self):self.assertIn('internal_box_count_or_box_unit_confirmation_missing',self.nonbox(2,None)['errors'])
    def test_nonbox_price_factor_and_physical_box_size_are_separate(self):self.assertEqual(self.nonbox(2,1)['physical_pieces_per_box'],'12')
    def test_nonexact_legacy_internal_ratio_is_manual(self):self.assertIn('internal_box_ratio_not_exact_legacy_contract',self.nonbox(1,3)['errors'])
    def test_missing_actual_price_is_row_error_not_exception(self):
        row={'parent_id':'missing','raw':{'quantity':'2','price':None},'basic_fields':{},'values':[None]*6+['个'],'price_check':self.p('100',None)}
        result=review.recalculate(row,{'amount':'1200','factor':'6','max_unit':'盒','qty_unit':'盒','declaration_unit':'个'},'SYNTHETIC')
        self.assertIn('actual_price_input_invalid',result['errors'])
    def test_same_physical_unit_cannot_mean_six_of_itself(self):
        row={'parent_id':'units','raw':{'quantity':'2','price':'600'},'basic_fields':{},'values':[None]*6+['个'],'price_check':self.p('100','600')}
        result=review.recalculate(row,{'amount':'1200','factor':'6','max_unit':'个','qty_unit':'个','declaration_unit':'个','boxes':'1'},'SYNTHETIC')
        self.assertIn('same_unit_cannot_have_nonunit_factor',result['errors'])

@unittest.skipUnless(os.environ.get('LOOP_REPLAY_DIR'),'provide isolated replay evidence')
class FullReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=Path(os.environ['LOOP_REPLAY_DIR']);cls.root=cls.out/'SYNTHETIC_隔离演示/state'
        from loop.updates import Service
        cls.s=Service(cls.root);cls.before=key(cls.s.store.load(cls.s.bid));cls.batch,cls.active,cls.view=cls.s.active()
        context=cls.out/'SYNTHETIC_隔离演示/compute-context.json'
        cls.compute=Path(load(context)['compute_root']) if context.exists() else cls.out/'SYNTHETIC_隔离演示/calculation-state'
        helper=Path(__file__).resolve().parents[2]/'a-stage-first-phase/tests/test_roundtrip.py'
        spec=importlib.util.spec_from_file_location('loop_test_edit',helper);cls.fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.fx)
    def update(self,file,**kwargs):return self.s.preview_update(file,role='synthetic_actual_price_update',reference='SYNTHETIC update regression',**kwargs)
    def test_confirmed_fields_unchanged_after_update(self):
        self.assertEqual(len(self.active['inherited_targets']),7650)
        self.assertEqual(self.view['confirmed_field_count'],7650)
        self.assertEqual(len(self.active['matches']),1275)
    def test_same_actual_values_create_no_spurious_changed_ranges(self):
        p=self.update(self.active['source']['path']);self.assertEqual(p['changed_price_quantity_rows'],[])
    def test_one_price_change_limits_delta_but_keeps_basic_confirmations(self):
        first=next(iter(self.active['matches'].values()))['new'];n=first['row'];q=first['quantity']
        with tempfile.TemporaryDirectory() as d:
            file=self.fx.edit(self.active['source']['path'],[(first['source']['sheet'],'H'+str(n),'number','700'),(first['source']['sheet'],'K'+str(n),'number',str(int(q)*700))],Path(d)/'SYNTHETIC changed.xlsx')
            p=self.update(file);self.assertEqual(len(p['changed_price_quantity_rows']),1);self.assertEqual(len(p['inherited_targets']),7650)
            self.assertFalse(p['source_totals_consistent'])
    def test_same_jan_alone_does_not_inherit_changed_identity(self):
        first=next(iter(self.active['matches'].values()))['new'];n=first['row'];rid=next(iter(self.active['matches']))
        with tempfile.TemporaryDirectory() as d:
            file=self.fx.edit(self.active['source']['path'],[(first['source']['sheet'],'D'+str(n),'text','SYNTHETIC different product version')],Path(d)/'changed.xlsx')
            p=self.update(file);self.assertIn(rid,p['issues']);self.assertNotIn(rid,p['matches']);self.assertTrue(p['new_unlinked_rows'])
    def test_full_identity_reordering_preserves_correct_relationship(self):
        rows=sorted([v['new'] for v in self.active['matches'].values()],key=lambda r:r['row'])[:2];a,b=rows;sheet=a['source']['sheet'];changes=[]
        from arrival_core import _p0_frozen as p0
        book=p0.Book(Path(self.active['source']['path']).read_bytes(),'source.xlsx');s=next(s for s in book.sheets if s.name==sheet)
        for target,source in [(a,b),(b,a)]:
            for col in 'ABCDEFGHIJ':
                v=s.v(source['row'],col);kind='number' if col in 'HIJ' and v is not None else 'text'
                changes.append((sheet,col+str(target['row']),kind,str(v) if v is not None else ''))
            changes.append((sheet,'K'+str(target['row']),'number',str(int(source['quantity'])*600)))
        with tempfile.TemporaryDirectory() as d:
            file=self.fx.edit(self.active['source']['path'],changes,Path(d)/'reordered.xlsx');p=self.update(file)
            rid=next(rid for rid,m in self.active['matches'].items() if m['new']['row']==a['row'])
            self.assertEqual(p['matches'][rid]['new']['row'],b['row']);self.assertEqual(len(p['inherited_targets']),7650)
    def test_duplicate_full_identity_stays_manual(self):
        rows=sorted([v['new'] for v in self.active['matches'].values()],key=lambda r:r['row'])[:2];a,b=rows;sheet=a['source']['sheet'];changes=[]
        from arrival_core import _p0_frozen as p0
        source=next(s for s in p0.Book(Path(self.active['source']['path']).read_bytes(),'source.xlsx').sheets if s.name==sheet)
        for c in 'ABCDEFG':changes.append((sheet,c+str(b['row']),'text',str(source.v(a['row'],c) or '')))
        with tempfile.TemporaryDirectory() as d:
            file=self.fx.edit(self.active['source']['path'],changes,Path(d)/'duplicate.xlsx');p=self.update(file);self.assertGreaterEqual(len(p['issues']),2)
    def test_observation_role_is_not_upgraded(self):
        p=self.s.preview_update(self.active['source']['path'],role='synthetic_initial_price_observation',reference='SYNTHETIC official observation')
        self.assertFalse(p['actual_price_qualified'])
    def test_synthetic_file_and_state_cannot_enter_business(self):
        from loop.updates import Service
        real=Service(self.out/'真实业务/state');before=key(real.store.load(real.bid));objects=set((real.root/'objects').iterdir())
        with self.assertRaises(Rejected):real.preview_update(self.active['source']['path'],role='actual_price_update',reference='attempt')
        self.assertEqual(objects,set((real.root/'objects').iterdir()));self.assertEqual(before,key(real.store.load(real.bid)))
        with self.assertRaises(Rejected):real.active()
    def test_no_implicit_update_confirmation_or_old_hash(self):
        p=self.update(self.active['source']['path'])
        for h,flag in [(p['preview_id'],False),('0'*64,True)]:
            with self.assertRaises(Rejected):self.s.commit_update(p['preview_id'],confirmed_hash=h,explicit_confirmation=flag,reference='SYNTHETIC')
    def test_update_receipt_is_idempotent_and_not_real_business_approval(self):
        pid=self.batch['loop']['active_update'];r=self.s.commit_update(pid,confirmed_hash=pid,explicit_confirmation=True,reference='SYNTHETIC duplicate')
        self.assertTrue(r['replayed']);self.assertFalse(r['actual_business_confirmation'])
    def test_stale_update_and_old_review_cannot_overwrite_a_new_version(self):
        import shutil
        from loop.updates import Service
        from loop.compute import Service as Compute
        c=Compute(self.compute);old_review=get(self.root,c.owner['review_preview'])
        with tempfile.TemporaryDirectory(prefix='loop-version-') as d:
            clone=Path(d)/'clone';shutil.copytree(self.root,clone,copy_function=os.link);s=Service(clone)
            p=s.preview_update(self.active['source']['path'],role='synthetic_actual_price_update',reference='SYNTHETIC next version')
            stale=s.preview_update(self.active['source']['path'],role='synthetic_actual_price_update',reference='SYNTHETIC stale second choice')
            before=deepcopy(s.store.load(s.bid)['a03']['overrides'])
            s.commit_update(p['preview_id'],confirmed_hash=p['preview_id'],explicit_confirmation=True,reference='SYNTHETIC explicit next version')
            self.assertEqual(before,s.store.load(s.bid)['a03']['overrides'])
            with self.assertRaises(Rejected):s.commit_update(stale['preview_id'],confirmed_hash=stale['preview_id'],explicit_confirmation=True,reference='SYNTHETIC stale')
            with self.assertRaises(Rejected):review.preview_return(s.root,c.owner['export_id'],old_review['upload'],reference='SYNTHETIC old review')
    def test_review_snapshot_and_formula_recalculation(self):
        from openpyxl import load_workbook
        reviewfile=self.out/'SYNTHETIC_隔离演示/SYNTHETIC_计算审核表.xlsx';w=load_workbook(reviewfile)
        self.assertIn('SYNTHETIC',w['计算审核']['A2'].value);self.assertTrue(w['计算审核']['H5'].protection.locked);self.assertFalse(w['计算审核']['I5'].protection.locked);w.close()
        from loop.compute import Service
        c=Service(self.compute);baseline=c._baseline(c.store.load(c.bid))[0];p=get(self.root,c.owner['review_preview'])
        self.assertEqual(p['blocked_rows'],0);self.assertFalse(p['formula_caches_trusted']);self.assertTrue(all(not f['purchase_quantity_consumed'] for f in p['facts']))
    def test_readonly_jan_source_price_and_formula_edits_rejected(self):
        from loop.compute import Service
        c=Service(self.compute);p=get(self.root,c.owner['review_preview'])
        for cell,kind,value in [('C5','text','fake'),('H5','number','999'),('R5','formula','J5*N5+1')]:
            with tempfile.TemporaryDirectory() as d:
                f=self.fx.edit(p['upload'],[('计算审核',cell,kind,value)],Path(d)/'bad.xlsx')
                with self.assertRaises(ValueError):review.preview_return(self.root,c.owner['export_id'],f,reference='SYNTHETIC bad input')
    def test_client_formula_cache_is_not_used(self):
        from loop.compute import Service
        from openpyxl import load_workbook
        c=Service(self.compute);p=get(self.root,c.owner['review_preview']);w=load_workbook(p['upload']);formula=w['计算审核']['R5'].value;w.close()
        with tempfile.TemporaryDirectory() as d:
            file=self.fx.edit(p['upload'],[('计算审核','R5','formula',formula[1:])],Path(d)/'cache.xlsx')
            r=review.preview_return(self.root,c.owner['export_id'],file,reference='SYNTHETIC cache tamper')
            self.assertEqual(r['facts'][0]['declaration_quantity'],'480');self.assertFalse(r['formula_caches_trusted'])
    def test_missing_unit_blocks_both_drafts_instead_of_partial_delivery(self):
        from loop.compute import Service
        c=Service(self.compute);p=get(self.root,c.owner['review_preview'])
        with tempfile.TemporaryDirectory() as d:
            file=self.fx.edit(p['upload'],[('计算审核','K5','text','')],Path(d)/'missing-unit.xlsx')
            r=review.preview_return(self.root,c.owner['export_id'],file,reference='SYNTHETIC missing Qty unit');self.assertEqual(r['blocked_rows'],1)
            with self.assertRaises(Rejected):Service.create(self.root,r['preview_id'],Path(d)/'must-not-exist')
            self.assertFalse((Path(d)/'must-not-exist').exists())
    def test_integer_ratio_does_not_itself_confirm_price_comparability(self):
        from loop.compute import Service
        c=Service(self.compute);p=get(self.root,c.owner['review_preview'])
        result=review.preview_return(self.root,c.owner['export_id'],p['upload'],reference='SYNTHETIC no price-comparability assertion')
        self.assertTrue(result['price_comparability_pending']);self.assertEqual(result['blocked_rows'],0)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Rejected):Service.create(self.root,result['preview_id'],Path(d)/'forbidden')
    def test_confirmation_retry_does_not_duplicate_amount_versions(self):
        from loop.compute import Service
        from loop.cli import confirm_review
        c=Service(self.compute);before=key(c.store.load(c.bid))
        r=confirm_review(self.root,c.owner['review_preview'],confirmed_hash=c.owner['review_preview'],explicit_confirmation=True,reference='SYNTHETIC same confirmed preview retry')
        self.assertTrue(r['receipt']['replayed']);self.assertEqual(before,key(c.store.load(c.bid)))
    def test_old_calculation_selection_cannot_be_delivered(self):
        from loop.compute import Service,Bridge
        import loop.compute as module
        c=Service(self.compute);bridge=Bridge(c.root);p=bridge.prepare(c.bid);original=module.load
        def changed(file):
            if Path(file).name=='current-computation.json':return {'review_preview':'f'*64,'compute_root':'different'}
            return original(file)
        with patch.object(module,'load',changed):
            with self.assertRaises(Rejected):bridge.current_input(p)
    def test_editing_the_same_business_filename_is_supported(self):
        # Trust the archived issued baseline, never the editable delivery path.
        from loop.compute import Service
        c=Service(self.compute);e=get(self.root,c.owner['export_id']);file=Path(e['file']);before=file.read_bytes()
        try:
            p=get(self.root,c.owner['review_preview']);file.write_bytes(Path(p['upload']).read_bytes())
            result=review.preview_return(self.root,c.owner['export_id'],file,reference='SYNTHETIC same-filename return');self.assertEqual(result['blocked_rows'],0)
        finally:file.write_bytes(before)
    def test_b00_a04_and_legacy_transaction_code_are_reused(self):
        from loop.compute import Base,Service
        from basis.service import Service as Original
        self.assertEqual(Base.commit_basis.__code__,Original.commit_basis.__code__)
        from a_confirm import model as original_model
        self.assertIs(Original.commit_basis.__globals__['model'],original_model)
        c=Service(self.compute);p=c.preflight(c.bid);self.assertEqual(p['ready_row_count'],1275);self.assertEqual(p['blocked_row_count'],0)
    def test_controlled_pair_is_verified_and_round0_difference_not_hidden(self):
        from openpyxl import load_workbook
        pair=self.out/'SYNTHETIC_隔离演示/双表草稿';v=load(pair/'_verification.json')
        self.assertEqual(v['rows'],1275);self.assertEqual(v['batch_difference_jpy'],'-1');self.assertEqual(v['rounding_rows'],1)
        self.assertTrue(v['formal_rejected']);self.assertEqual(v['privacy_scan'],'passed');self.assertEqual(len(list(pair.glob('*.xlsx'))),2)
        for f in pair.glob('*.xlsx'):
            w=load_workbook(f);self.assertIn('SYNTHETIC',w.properties.title);self.assertFalse(w.defined_names);self.assertFalse(w._external_links);w.close()
    @classmethod
    def tearDownClass(cls):
        assert key(cls.s.store.load(cls.s.bid))==cls.before,'Read-only regression must not change synthetic HEAD'

if __name__=='__main__':unittest.main()
