import sys,unittest,os,tempfile,json
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from packloop import runtime
from packloop.catalogue import layers
from packloop.support import load,get,key,digest,Rejected
from loop.prices import candidate

class UnitLayers(unittest.TestCase):
    def fact(self,*,quantity='1',price='700',purchase='100',purchase_unit='包',maximum='盒',factor='14',amount='700',packs='7',inner='2',internal='包',boxes=None,scope='SYNTHETIC explicit packaging'):
        row={'parent_id':'test','raw':{'quantity':quantity,'price':price},'basic_fields':{k:{'confirmed':True} for k in ['internal_name','specification','category','channel','yd']},
            'values':[None]*6+[purchase_unit],'price_check':candidate(purchase,price,purchase_confirmed=True,minimum_unit_confirmed=True,actual_price=True,comparable=True)}
        values={'max_unit':maximum,'qty_unit':maximum,'factor':factor,'amount':amount,'packs_per_box':packs,'units_per_pack':inner,'internal_unit':internal,'boxes':boxes,'declaration_unit':'张','packaging_reference':scope}
        return runtime.review.recalculate(row,values,'SYNTHETIC')
    def test_box_seven_packs_two_sheets(self):
        f=self.fact();self.assertFalse(f['errors']);self.assertEqual((f['quantity'],f['factor'],f['declaration_quantity'],f['boxes'],f['internal_unit_price']),('7','2','14','1','100'))
    def test_packet_quantity_ten_is_not_ten_boxes(self):
        f=self.fact(quantity='10',price='100',maximum='包',factor='2',amount='1000',packs='10');self.assertFalse(f['errors']);self.assertEqual((f['quantity'],f['declaration_quantity'],f['boxes']),('10','20','1'))
    def test_sheet_procurement_and_pack_internal_can_coexist(self):
        f=self.fact(purchase='50',purchase_unit='张');self.assertFalse(f['errors']);self.assertEqual(f['internal_unit_price'],'100')
    def test_internal_sheet_unit_stays_per_sheet(self):self.assertEqual(self.fact(internal='张')['internal_unit_price'],'50')
    def test_wrong_cost_divisor_detected(self):self.assertEqual(self.fact()['quantity'],'7')
    def test_missing_layer_not_inferred_from_single_s_value(self):self.assertTrue(self.fact(inner=None)['errors'])
    def test_fractional_layer_is_not_rounded(self):self.assertTrue(self.fact(inner='2.1')['errors'])
    def test_missing_scope_never_auto_adopts_reference(self):self.assertIn('packaging_scope_reference_required',self.fact(scope=None)['errors'])
    def test_conflicting_box_count(self):self.assertIn('box_count_conflicts_with_explicit_source_unit',self.fact(boxes='2')['errors'])
    def test_price_ratio_and_geometry_must_agree(self):self.assertIn('price_ratio_conflicts_with_explicit_packaging_units',self.fact(purchase='50')['errors'])
    def test_noninteger_price_ratio_remains_manual(self):self.assertIn('noninteger_price_ratio_no_rounding',self.fact(price='701',amount='701')['errors'])
    def test_no_forced_whole_box_for_loose_packets(self):
        f=self.fact(quantity='3',price='100',maximum='包',factor='2',amount='300');self.assertIn('exact_quantity_or_price_not_representable_in_existing_excel_engine',f['errors'])
    def test_terminating_partial_box_retained(self):
        f=self.fact(quantity='3',price='100',maximum='包',factor='2',amount='300',packs='10');self.assertFalse(f['errors']);self.assertEqual(f['boxes'],'0.3')
    def test_round0_uses_sheet_quantity(self):self.assertEqual(self.fact()['execution_round0'],50)
    def test_seven_by_two_parse(self):self.assertEqual(layers('明信片1包2枚、1盒7包','明信片整盒1','')[0]['declaration_units_per_box'],14)
    def test_do_not_copy_other_type_under_same_yd(self):self.assertEqual(layers('贴纸1包2枚，1盒10包；明信片10枚套组','明信片整盒1',''),[])
    def test_variety_or_set_not_pack_layer(self):
        for raw in ['全14种','20枚入','本体','2枚套组','1盒7包']:self.assertEqual(layers(raw,'明信片整盒1',''),[])
    def test_conflicting_layers_are_retained(self):self.assertEqual(len(layers('明信片1包2枚、1盒7包；明信片1包3枚、1盒7包','明信片','')),2)
    def test_readonly_catalogue_keeps_conflicts_and_exact_spec_scope(self):
        import sqlite3
        from packloop.catalogue import snapshot
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'library.sqlite3';db=sqlite3.connect(file)
            db.executescript('CREATE TABLE catalogue_entries(entry_id,descriptor_json,grouping_method); CREATE TABLE field_variants(entry_id,field_name,value_json,sample_observation_sha256); CREATE TABLE record_links(entry_id,observation_sha256,position_id,provenance_json,raw_record_sha256,fields_sha256); CREATE TABLE yd_material_rows(x); CREATE TABLE yd_material_imports(import_sha256,columns_json); CREATE TABLE yd_material_lookup(import_sha256,source_row,yd_key,accessories_original,archive_path,sheet);')
            for eid,spec in [('a','明信片整盒1'),('b','吧唧单个')]:db.execute('INSERT INTO catalogue_entries VALUES(?,?,?)',(eid,json.dumps({'code_raw':'123','yd':'YD1','specification':spec}), 'exact_descriptor'))
            db.execute('INSERT INTO yd_material_imports VALUES(?,?)',('sha',json.dumps(['产品配件'])))
            for n,raw in enumerate(['明信片1包2枚、1盒7包','明信片1包3枚、1盒7包'],1):db.execute('INSERT INTO yd_material_lookup VALUES(?,?,?,?,?,?)',('sha',n,'YD1',raw,'file.xlsx','Sheet1'))
            db.commit();db.close();before=digest(file)
            p=snapshot(file,[{'row':1,'code':'123','yd':'YD1','specification':'明信片整盒1','japanese_name':''}]);r=p['rows']['1']
            self.assertIsNone(r['pack_reference']);self.assertTrue(r['pack_conflict']);self.assertEqual(len(r['catalogue_exact_spec']),1);self.assertEqual(len(r['material_link_sources']),2);self.assertEqual(before,digest(file))

@unittest.skipUnless(os.environ.get('PACK_REPLAY_DIR'),'full isolated replay path required')
class Full(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=Path(os.environ['PACK_REPLAY_DIR']);cls.wf=load(cls.out/'19列受控基础资料/workflow-manifest.json');cls.real=runtime.updates.Service(cls.out/'真实业务/state');cls.root=cls.out/'SYNTHETIC_隔离演示/state';cls.syn=runtime.updates.Service(cls.root)
        cls.before=key(cls.syn.store.load(cls.syn.bid));cls.realbefore=key(cls.real.store.load(cls.real.bid));cls.c=runtime.compute.Service(load(cls.out/'SYNTHETIC_隔离演示/compute-context.json')['compute_root'])
        cls.p=get(cls.root,cls.c.owner['review_preview']);cls.e=get(cls.root,cls.c.owner['export_id'])
        import importlib.util
        file=Path(__file__).resolve().parents[3]/'reports/business-loop-20261105/run.py'
        # Locate workspace helper outside actual Git repository.
        file=Path(__file__).resolve().parents[3]/'reports/business-loop-20261105/run.py'
        spec=importlib.util.spec_from_file_location('pack_edit',file);cls.fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.fx)
    def test_19_baseline_full_content_preservation(self):
        from native_copy.ooxml import parts
        original=load(self.wf['catalogue_snapshot']);self.assertEqual(original['counts']['record_links'],167072)
        evidence=load(Path(self.wf['issued_file']).parents[2]/'technical/preservation.json');self.assertTrue(evidence['all_workbook_parts_except_version_identical'])
    def test_actual_sources_668_and_885_have_separate_layers(self):
        rows=load(self.wf['catalogue_snapshot'])['rows'];a=rows['668']['pack_reference'];b=rows['885']['pack_reference']
        self.assertEqual((a['packs_per_box'],a['units_per_pack'],a['declaration_units_per_box']),(7,2,14));self.assertEqual((b['packs_per_box'],b['units_per_pack'],b['declaration_units_per_box']),(10,2,20));self.assertEqual(a['source']['cell'],'I96')
    def test_no_real_confirmation_or_actual_update(self):
        self.assertEqual(self.real.basics.read_current(self.real.bid)['confirmed_field_count'],0);self.assertIsNone(self.real.store.load(self.real.bid)['loop']['active_update'])
    def test_basic_inheritance_and_pack_review_ready(self):
        _,u,v=self.syn.active();self.assertEqual(len(u['inherited_targets']),7650);self.assertEqual(self.c.preflight(self.c.bid)['ready_row_count'],1275)
    def test_repeated_prepare_has_stable_columns_and_fixed_snapshot(self):
        a=runtime.review.prepare(self.root);b=runtime.review.prepare(self.root);self.assertEqual(len(a['headers']),41);self.assertEqual(a['plan_id'],b['plan_id']);self.assertEqual(len(a['rows'][0]['values']),41)
    def test_old18_and_unregistered19_rejected(self):
        s=self.real.basics;v=s.read_current(self.real.bid)
        for file in [self.wf['prior_workflow'],None]:
            f=load(file)['issued_file'] if file else load(self.fx.W/'outputs/KMT20261101_补充核对版_当前.json')['file']
            with self.assertRaises(ValueError):s.preview_return(self.real.bid,f,expected_hash=v['current_hash'])
    def test_S_H_Q_R_and_original_amount_protected(self):
        for cell in ['S668','H668','Q668','R668','L668']:
            with tempfile.TemporaryDirectory() as d:
                f=self.fx.edited(self.wf['issued_file'],Path(d)/'bad.xlsx',{'invoice (計算)':[(cell,'number','999')]})
                with self.assertRaises(ValueError):self.real.basics.preview_return(self.real.bid,f,expected_hash=self.realbefore)
    def test_M_N_actual_work_values_retained_and_editable(self):
        from openpyxl import load_workbook
        w=load_workbook(self.wf['issued_file']);s=w['invoice (計算)'];self.assertFalse(s['N885'].protection.locked);self.assertEqual(s['N885'].value,'纸');self.assertEqual(s['F2'].value,'拍立得整盒89');w.close()
    def test_scoped_A03_save_CAS_and_idempotency_in_temporary_clone(self):
        import shutil
        from packloop.support import path
        with tempfile.TemporaryDirectory(prefix='pack-save-') as d:
            clone=Path(d)/'clone';shutil.copytree(path(self.real.root),path(clone),copy_function=os.link);s=runtime.updates.Service(clone);v=s.basics.read_current(s.bid)
            file=self.fx.edited(self.wf['issued_file'],Path(d)/'changed.xlsx',{'invoice (計算)':[('N2','text','SYNTHETIC 待核材质')]})
            p=s.basics.preview_return(s.bid,file,expected_hash=v['current_hash']);selection={'save_changes':list(p['proposals']),'confirm_fields':[],'adopt_candidates':[],'evidence':{}}
            plan=s.basics.prepare_confirmation(p['preview_id'],selection);s.basics.commit(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference='SYNTHETIC temporary clone save only')
            again=s.basics.commit(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference='SYNTHETIC retry');self.assertTrue(again['replayed']);self.assertEqual(s.basics.read_current(s.bid)['confirmed_field_count'],0)
            with self.assertRaises(ValueError):s.basics.preview_return(s.bid,file,expected_hash=v['current_hash'])
    def test_history_layers_rechecked_from_original_workbooks(self):
        report=load(self.fx.W/'reports/catalogue-pack-loop-20261106/historical-recheck.json');self.assertEqual(report['rows'],9);self.assertTrue(report['source_hashes_unchanged']);self.assertTrue(all(r['billing_per_box']!=r['declaration_per_box'] for r in report['facts']))
    def test_new_packaging_formula_and_readonly_targets_protected(self):
        with tempfile.TemporaryDirectory() as d:
            f=self.fx.edited(self.p['upload'],Path(d)/'bad.xlsx',{'计算审核':[('AK5','number','999')]})
            with self.assertRaises(ValueError):runtime.review.preview_return(self.root,self.c.owner['export_id'],f,reference='SYNTHETIC')
    def test_missing_pack_scope_blocks_and_no_partial_pair(self):
        with tempfile.TemporaryDirectory() as d:
            f=self.fx.edited(self.p['upload'],Path(d)/'missing.xlsx',{'计算审核':[('AM5','text','')]})
            p=runtime.review.preview_return(self.root,self.c.owner['export_id'],f,reference='SYNTHETIC',price_basis_reference='SYNTHETIC');self.assertEqual(p['blocked_rows'],1)
            with self.assertRaises(ValueError):runtime.compute.Service.create(self.root,p['preview_id'],Path(d)/'no-pair')
    def test_confirm_retries_are_idempotent(self):
        before=key(self.c.store.load(self.c.bid));r=runtime.cli.confirm_review(self.root,self.c.owner['review_preview'],confirmed_hash=self.c.owner['review_preview'],explicit_confirmation=True,reference='SYNTHETIC repeat');self.assertTrue(r['receipt']['replayed']);self.assertEqual(before,key(self.c.store.load(self.c.bid)))
    def test_b00_transaction_and_engine_code_unchanged(self):
        from basis.service import Service as Original
        self.assertEqual(runtime.compute.Base.commit_basis.__code__,Original.commit_basis.__code__)
        from a_confirm import model
        self.assertIs(Original.commit_basis.__globals__['model'],model)
    def test_internal_pricing_and_declaration_quantities_are_distinct(self):
        from openpyxl import load_workbook
        d=self.out/'SYNTHETIC_隔离演示/双表草稿';i=load_workbook(d/'内部到货单_受控测试草稿.xlsx',data_only=True);c=load_workbook(d/'海关报关单_受控测试草稿.xlsx',data_only=True)
        s=i.worksheets[0];t=c.worksheets[0]
        self.assertEqual((s['H2'].value,s['I2'].value,s['J2'].value,s['N2'].value),(80,560,100,7));self.assertEqual((t['F2'].value,t['G2'].value),(1120,50));self.assertAlmostEqual(s['R2'].value,130.55);i.close();c.close()
    def test_verification_privacy_and_round0_difference_retained(self):
        v=load(self.out/'SYNTHETIC_隔离演示/双表草稿/_verification.json');self.assertEqual(v['rows'],1275);self.assertTrue(v['formal_rejected']);self.assertEqual(v['privacy_scan'],'passed');self.assertNotEqual(v['batch_difference_jpy'],'0')
    @classmethod
    def tearDownClass(cls):
        assert key(cls.syn.store.load(cls.syn.bid))==cls.before;assert key(cls.real.store.load(cls.real.bid))==cls.realbefore

if __name__=='__main__':unittest.main()
