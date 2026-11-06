import sys,unittest,tempfile,os,shutil,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;W=REPO.parent
sys.path.insert(0,str(ROOT))
from interaction import rt,load,save,key,digest,path,Rejected
from interaction.service import Service
R=W/'reports/business-interaction-20261106'
OUT=W/'outputs/KMT20261101_单表分阶段试用_20261106'
def daily_config():return load(W/'outputs/KMT20261101_日常业务入口_当前.json')['session']
def registered_workflow():return Service(daily_config()).engine.owner['workflow']
def basic_cell(backend,field):return next(f['cell'] for f in backend.basics.read_current(backend.bid)['fields'].values() if f['field']==field and f['cell'].rstrip('0123456789')+'2'==f['cell'])
spec=importlib.util.spec_from_file_location('fixture_edit',W/'reports/business-loop-20261105/run.py');fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)

class RealDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.s=Service(daily_config());cls.before=key(cls.s.engine.store.load(cls.s.engine.bid))
    def test_first_stage_exposes_only_one_real_workbook(self):
        result=self.s.deliver();self.assertEqual(result['stage'],'basics');self.assertEqual(len(result['business_files']),1)
        self.assertEqual(Path(result['business_files'][0]).parent,self.s.public);self.assertNotIn('SYNTHETIC',result['business_files'][0]);self.assertFalse(result['formal_output'])
    def test_presentation_is_legal_zero_change_return(self):
        s=self.s.engine;v=s.basics.read_current(s.bid);p=s.basics.preview_return(s.bid,self.s.deliver()['business_files'][0],expected_hash=v['current_hash']);self.assertEqual(p['modified_cells'],0);self.assertEqual(v['confirmed_field_count'],0)
    def test_missing_and_reference_colors_keep_optional_fields_and_protection(self):
        from openpyxl import load_workbook
        w=load_workbook(self.s.deliver()['business_files'][0]);s=w['invoice (計算)'];view=self.s.engine.basics.read_current(self.s.engine.bid)
        for f in view['fields'].values():
            if f['field'] in {'internal_name','category'} and f['value']['value'] in (None,''):
                if f['field']=='category' and load(self.s.engine.owner['workflow']).get('manual_category_input_only'):
                    self.assertIsNone(s[f['cell']].fill.patternType)
                else:self.assertEqual(s[f['cell']].fill.fgColor.rgb,'FFF4CCCC')
                self.assertFalse(s[f['cell']].protection.locked)
        layout=load(self.s.engine.owner['workflow']);cols=layout.get('registered_columns',19);pack=layout.get('reference_columns',{}).get('pack_reference','S')
        self.assertEqual(s[basic_cell(self.s.engine,'specification')].value,'拍立得整盒89')
        if layout.get('manual_packaging_original_text_only'):
            self.assertEqual(s[pack+'2'].value,'亚克力卡吧唧贴纸整盒11个入，相卡拍立得整盒17个入')
            self.assertTrue(all(f['value']['value'] is None for f in view['fields'].values() if f['field']=='category'))
        else:self.assertEqual(s[pack+'2'].value,17)
        self.assertTrue(s[pack+'2'].protection.locked);self.assertIsNone(s['I2' if cols==20 else 'H2'].value);self.assertEqual(s.max_column,cols);self.assertEqual(s.auto_filter.ref,'B1:T1313' if cols==20 else 'B1:S1313')
        if layout.get('excel_ui_unprotected'):self.assertTrue(all(not ws.protection.sheet for ws in w))
        w.close()
    def test_no_calculation_upload_before_actual_price_update(self):
        file=W/'outputs/KMT20261101_资料库包装闭环候选_20261106_v3/SYNTHETIC_隔离演示/SYNTHETIC_一次修改回传.xlsx'
        with self.assertRaises(ValueError):self.s.upload(file,kind='calculation',reference='isolated refusal test')
    def test_no_implicit_confirmation(self):
        with self.assertRaises(ValueError):self.s.confirm('not-approved',explicit_confirmation=False,reference='not approved')
    @classmethod
    def tearDownClass(cls):assert key(cls.s.engine.store.load(cls.s.engine.bid))==cls.before

class ScopedReturn(unittest.TestCase):
    def test_default_preview_exposes_scope_and_defers_unit_unknown_prices(self):
        current={'workflow':registered_workflow()}
        with tempfile.TemporaryDirectory(prefix='daily-default-') as d:
            root=Path(d);backend=rt.updates.Service.fork(current['workflow'],root/'state',mode='synthetic');s=Service({'root':str(backend.root),'mode':'synthetic','background':str(root/'private'),'business_directory':str(root/'visible'),'node':load(OUT/'后台/session.json')['node']})
            file=Path(s.deliver()['business_files'][0]);before=key(backend.store.load(backend.bid));name=basic_cell(backend,'internal_name');category=basic_cell(backend,'category');fx.edited(file,file,{'invoice (計算)':[(name,'text','SYNTHETIC 明确修改名称'),(category,'text','未知')]})
            deferred=sum(f['field']=='purchase_unit_price' and f['value']['value'] not in (None,'') for f in backend.basics.read_current(backend.bid)['fields'].values())
            p=s.upload(file,reference='SYNTHETIC plain Excel return, no user JSON');self.assertTrue(p['confirmation_required']);self.assertEqual(p['proposed_changes'],2);self.assertGreater(p['field_counts']['internal_name'],0);self.assertEqual(p['field_counts']['purchase_unit_price'],0);self.assertEqual(p['purchase_prices_deferred'],deferred);self.assertGreater(p['summary']['saved_pending_fields'],0);self.assertNotIn('invoice (計算)!'+category,p['selection']['confirm_fields']+p['selection']['adopt_candidates']);self.assertEqual(key(backend.store.load(backend.bid)),before)
    def test_same_file_return_preview_save_only_and_idempotency(self):
        current={'workflow':registered_workflow()}
        with tempfile.TemporaryDirectory(prefix='daily-return-') as d:
            root=Path(d);backend=rt.updates.Service.fork(current['workflow'],root/'state',mode='synthetic')
            cfg={'root':str(backend.root),'mode':'synthetic','background':str(root/'private'),'business_directory':str(root/'visible'),'node':load(OUT/'后台/session.json')['node']};s=Service(cfg);file=Path(s.deliver()['business_files'][0]);before=key(backend.store.load(backend.bid))
            material=basic_cell(backend,'material_reference');target='invoice (計算)!'+material
            fx.edited(file,file,{'invoice (計算)':[(material,'text','SYNTHETIC 待核材质')]})
            scope={'save_changes':[target],'confirm_fields':[],'adopt_candidates':[],'evidence':{}}
            p=s.upload(file,reference='SYNTHETIC same filename returned',selection=scope);self.assertEqual(p['proposed_changes'],1);self.assertEqual(key(backend.store.load(backend.bid)),before)
            with self.assertRaises(ValueError):s.confirm(p['confirmation_id'],explicit_confirmation=False,reference='SYNTHETIC')
            result=s.confirm(p['confirmation_id'],explicit_confirmation=True,reference='SYNTHETIC explicit save N2 only');self.assertEqual(result['stage'],'basics');self.assertEqual(len(result['business_files']),1)
            from openpyxl import load_workbook
            w=load_workbook(result['business_files'][0]);self.assertEqual(w['invoice (計算)'][material].value,'SYNTHETIC 待核材质');w.close()
            view=backend.basics.read_current(backend.bid);self.assertEqual(view['confirmed_field_count'],0);self.assertEqual(view['fields'][target]['status'],'saved_pending')
            repeat=s.confirm(p['confirmation_id'],explicit_confirmation=True,reference='SYNTHETIC exact same scope retry');self.assertTrue(repeat['receipt_replayed']);self.assertTrue(list((root/'private/retained-editable-copies').glob('*.xlsx')))
    def test_stale_scope_cannot_replace_later_save(self):
        current={'workflow':registered_workflow()}
        with tempfile.TemporaryDirectory(prefix='daily-cas-') as d:
            root=Path(d);backend=rt.updates.Service.fork(current['workflow'],root/'state',mode='synthetic');s=Service({'root':str(backend.root),'mode':'synthetic','background':str(root/'private'),'business_directory':str(root/'visible'),'node':load(OUT/'后台/session.json')['node']});base=s.deliver()['business_files'][0]
            material=basic_cell(backend,'material_reference');scope={'save_changes':['invoice (計算)!'+material],'confirm_fields':[],'adopt_candidates':[],'evidence':{}}
            a=fx.edited(base,root/'a.xlsx',{'invoice (計算)':[(material,'text','SYNTHETIC A')]});p=s.upload(a,reference='SYNTHETIC A',selection=scope)
            b=fx.edited(base,root/'b.xlsx',{'invoice (計算)':[(material,'text','SYNTHETIC B')]});q=s.upload(b,reference='SYNTHETIC B',selection=scope)
            s.confirm(p['confirmation_id'],explicit_confirmation=True,reference='SYNTHETIC approve A')
            with self.assertRaises(ValueError):s.confirm(q['confirmation_id'],explicit_confirmation=True,reference='SYNTHETIC stale B')

@unittest.skipUnless((R/'stage-delivery-proof.json').exists(),'complete isolated replay first')
class LaterStages(unittest.TestCase):
    def test_stage_file_counts_are_one_one_two(self):
        p=load(R/'stage-delivery-proof.json');self.assertEqual(p['file_counts'],[1,1,2]);self.assertTrue(p['synthetic_only']);self.assertFalse(p['real_business_confirmation'])
        for name in ['stage1.json','stage2.json','stage3.json']:
            p=load(R/name)
            self.assertTrue(all(Path(f).suffix=='.xlsx' for f in p['business_files']));self.assertFalse(any('report' in Path(f).name.lower() or '清单' in Path(f).name for f in p['business_files']))
        s=Service(R/'synthetic-session.json');delivery=s.deliver();self.assertEqual(len(list(s.public.glob('*.xlsx'))),2);self.assertEqual(len(delivery['business_files']),2);self.assertTrue(list((s.background/'past-stage-files').rglob('*.xlsx')))
    def test_missing_unit_does_not_publish_a_pair(self):
        s=Service(R/'synthetic-session.json');e=load(s.background/'current-review-export.json');c=load(s.root/'current-computation.json');compute=rt.compute.Service(c['compute_root']);review=load(s.root/'objects'/(compute.owner['review_preview']+'.json'))
        with tempfile.TemporaryDirectory() as d:
            file=fx.edited(review['upload'],Path(d)/'missing.xlsx',{'计算审核':[('K5','text','')]});p=s.upload(file,kind='calculation',reference='SYNTHETIC missing unit',price_basis_reference='SYNTHETIC')
            self.assertEqual(p['blocked_rows'],1);self.assertFalse(p['business_files'])
            with self.assertRaises(ValueError):s.confirm(p['confirmation_id'],explicit_confirmation=True,reference='SYNTHETIC blocked scope')
    def test_calculation_rules_and_round0_still_verified(self):
        s=Service(R/'synthetic-session.json');c=load(s.root/'current-computation.json');v=load(s.background/'draft-pairs'/c['review_preview'][:16]/'_verification.json')
        self.assertEqual(v['rows'],1275);self.assertEqual(v['batch_difference_jpy'],'7');self.assertEqual(v['rounding_rows'],1);self.assertTrue(v['formal_rejected']);self.assertEqual(v['privacy_scan'],'passed')

if __name__=='__main__':unittest.main()
