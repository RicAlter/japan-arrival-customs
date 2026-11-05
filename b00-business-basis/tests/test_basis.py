from copy import deepcopy
from pathlib import Path
import importlib.util
import unittest
from unittest.mock import patch

from basis.service import Service, REPO, Rejected, key
from a_input.bridge import Bridge
from openpyxl import Workbook,load_workbook

spec=importlib.util.spec_from_file_location('b00_a03_fixture',REPO/'a03-confirmation/tests/test_confirmation.py')
fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)


def business(path):
    w=Workbook();s=w.active;s.title='Sheet1'
    headers={'A':'CartonNo.','B':'Origin','C':'ProductCode(JANCode)','G':'DescriptionofGoods',
             'H':'盒装数','I':'Qty','J':'UnitPrice(日本JPY)','K':'Subtotal','M':'材质','S':'YD编码','T':'备注'}
    for c,v in headers.items():s[c+'1']=v
    for c,v in {'A':'HA001','B':'JP','C':'00123','G':'Japanese A','H':1,'I':2,'J':100,'K':200,'M':'参考'}.items():s[c+'2']=v
    w.save(path);w.close()


class BasisTests(unittest.TestCase):
    def setUp(self):
        self.f=fx.ConfirmationTests('test_partial_confirmation_saves_only_selected_changes');self.f.setUp()
        self.service=Service.fork(self.f.service.root,self.f.root/'b00')
        self.bid=self.f.bid;self.file=self.f.root/'business.xlsx';business(self.file)
        self.rid=self.service.store.load(self.bid)['rows'][0]['id']
    def tearDown(self):self.f.tearDown()
    def group(self):return {'row_ids':[self.rid],'business_unit':'件','declaration_unit':'件','reference':'TEST:business source & no-conversion rule','exceptions':{}}
    def preview(self,g=None):return self.service.preview_basis(self.bid,business_file=self.file,groups=[g or self.group()])
    def commit(self,p):return self.service.commit_basis(p['plan_id'],confirmed_hash=p['plan_id'],explicit_confirmation=True,reference='TEST:explicit scoped confirmation')
    def edit(self,cell,value):
        w=load_workbook(self.file);w['Sheet1'][cell]=value;w.save(self.file);w.close()
    def test_preview_does_not_confirm(self):
        p=self.preview();self.assertEqual(len(p['items']),1)
        self.assertEqual(self.service.preflight(self.bid)['ready_row_count'],0)
    def test_saved_a_version_reenters_a04_and_rc5(self):
        old=Bridge(self.service.root).prepare(self.bid);r=self.commit(self.preview())
        out=Bridge(self.service.root).prepare(self.bid)
        self.assertEqual(out['ready_row_count'],1);self.assertNotEqual(out['a_version'],old['a_version'])
        self.assertEqual(out['rc5_input']['rows'][0]['authority']['amount'],'200')
        self.assertEqual(out['rc5_input']['rows'][0]['business_amount']['versions'][-1]['values']['amount'],'200')
        self.assertFalse(r['formal_output']);self.assertEqual(r['professional_approvals'],0)
        with self.assertRaises(Rejected):Bridge(self.service.root).current_input(old)
    def test_mixed_qty_scope_supported_with_explicit_single_relation(self):
        g=self.group();g.update(business_unit='Qty（原表计价口径）',declaration_unit='单个')
        self.commit(self.preview(g));out=self.service.preflight(self.bid)
        self.assertEqual(out['ready_row_count'],1)
        self.assertEqual(out['rc5_input']['rows'][0]['business_amount']['versions'][-1]['values']['quantity_unit'],g['business_unit'])
    def test_piece_unit_single_declaration_alias_needs_scoped_evidence(self):
        g=self.group();g['declaration_unit']='单个'
        self.commit(self.preview(g));self.assertEqual(self.service.preflight(self.bid)['ready_row_count'],1)
    def test_price_reference_not_replaced_by_business_amount(self):
        self.commit(self.preview());state=self.service.read_current(self.bid)
        self.assertFalse(state['fields']['Sheet1!G2']['confirmed'])
        self.assertEqual(state['fields']['Sheet1!G2']['value']['value'],'800.004')
    def test_h_from_independent_boxes_not_purchase_price_ratio(self):
        self.commit(self.preview());self.assertEqual(self.service.read_current(self.bid)['fields']['Sheet1!H2']['value']['value'],'2')
    def test_source_raw_authority_and_original_store_unchanged(self):
        old=self.service.store.load(self.bid);original=key(self.f.service.store.load(self.bid))
        self.commit(self.preview());new=self.service.store.load(self.bid)
        for k in ('raw','source','authority','arrival'):self.assertEqual(old['rows'][0][k],new['rows'][0][k])
        self.assertEqual(original,key(self.f.service.store.load(self.bid)))
        read=self.service.read_basis(self.bid)['rows'][0]
        self.assertIsNone(read['purchase_quantity']);self.assertIsNone(read['japanese_retail_amount'])
        self.assertEqual(read['arrival_quantity_observation']['quantity_raw'],'2')
        self.assertEqual(read['business_basis']['amount'],'200')
    def test_repeat_confirmation_no_new_version(self):
        p=self.preview();a=self.commit(p);b=self.commit(p)
        self.assertTrue(b['replayed']);self.assertEqual(a['a_version'],b['a_version'])
        self.assertEqual(self.service.store.load(self.bid)['revision'],1)
    def test_explicit_confirmation_required(self):
        p=self.preview()
        with self.assertRaises(Rejected):self.service.commit_basis(p['plan_id'],confirmed_hash=p['plan_id'],explicit_confirmation=False,reference='TEST')
    def test_conflicting_old_plan_rejected(self):
        p=self.preview();g=self.group();g['reference']='TEST:other';self.commit(self.preview(g))
        with self.assertRaises(Rejected):self.commit(p)
    def test_source_change_after_preview_rejected(self):
        p=self.preview();self.edit('J2',200)
        with self.assertRaises(Rejected):self.commit(p)
    def test_source_change_after_save_invalidates_reading(self):
        self.commit(self.preview());self.edit('J2',200)
        with self.assertRaises(Rejected):self.service.preflight(self.bid)
    def test_unknown_unit_rejected(self):
        g=self.group();g['business_unit']='未知'
        with self.assertRaises(Rejected):self.preview(g)
    def test_zero_box_rejected(self):
        self.edit('H2',0)
        p=self.preview();self.assertFalse(p['items']);self.assertIn(self.rid,p['excluded'])
    def test_fractional_pieces_stay_exception(self):
        self.edit('H2',3);p=self.preview();self.assertFalse(p['items']);self.assertEqual(len(p['excluded']),1)
    def test_explicit_exceptions_remain_unconfirmed(self):
        g=self.group();g['exceptions']={self.rid:'TEST:separate review'}
        p=self.preview(g);self.assertFalse(p['items'])
        with self.assertRaises(Rejected):self.commit(p)
    def test_identity_mismatch_not_guessed(self):
        self.edit('C2','99999');p=self.preview();self.assertFalse(p['items'])
    def test_quantity_difference_retained_not_balanced(self):
        self.edit('I2',4);self.edit('K2',400)
        p=self.preview();self.assertFalse(p['items']);self.assertIn(self.rid,p['excluded'])
    def test_explicit_conversion_keeps_physical_h_separate_from_pricing_layer(self):
        self.edit('I2',1);self.edit('K2',100)
        g=self.group();g.update(business_unit='Qty（原表计价口径）',declaration_unit='单个',declaration_factor='2')
        p=self.preview(g);self.commit(p);out=self.service.preflight(self.bid)
        self.assertEqual(out['ready_row_count'],1)
        r=out['rc5_input']['rows'][0]
        self.assertEqual(r['packaging']['pieces_per_box'],'1')
        self.assertEqual(r['packaging']['declaration_factor'],'2')
        self.assertEqual(self.service.read_current(self.bid)['fields']['Sheet1!H2']['value']['value'],'2')
        self.assertEqual(r['arrival']['quantity_raw'],'2')
        self.assertEqual(r['business_amount']['versions'][-1]['values']['quantity'],'1')
    def test_native16_receives_same_group_without_new_excel_layout(self):
        folder=self.f.root/'source16';folder.mkdir()
        file=folder/'native16.xlsx';fx.fx.fx.make_native(file)
        f=self.f.f;f.source=file;f.prepared(f.request(basis=False))
        from a_confirm.service import Service as A03
        source=A03(self.f.root/'a03-16');bid=source.register(f.context())['batch_id']
        service=Service.fork(source.root,self.f.root/'b00-16');rid=service.store.load(bid)['rows'][0]['id']
        g=self.group();g['row_ids']=[rid]
        p=service.preview_basis(bid,business_file=self.file,groups=[g])
        service.commit_basis(p['plan_id'],confirmed_hash=p['plan_id'],explicit_confirmation=True,reference='TEST:16 columns explicit scope')
        self.assertEqual(service.preflight(bid)['ready_row_count'],1)
    def test_final_customs_input_not_accepted(self):
        w=Workbook();w.save(self.file);w.close()
        with self.assertRaises(Rejected):self.preview()
    def test_batch_scope_duplicates_rejected(self):
        with self.assertRaises(Rejected):self.service.preview_basis(self.bid,business_file=self.file,groups=[self.group(),self.group()])
    def test_unknown_row_id_rejected(self):
        g=self.group();g['row_ids']=['not-this-batch']
        with self.assertRaises(Rejected):self.preview(g)
    def test_prior_a_change_invalidates_approved_basis(self):
        self.commit(self.preview());view=self.service.read_current(self.bid)
        p=self.service.preview_return(self.bid,self.f.f.edited({'E2':'new name'}),expected_hash=view['current_hash'])
        plan=self.service.prepare_confirmation(p['preview_id'],fx.selection(['Sheet1!E2'],['Sheet1!E2']))
        self.service.commit(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference='TEST:later A edit')
        self.assertEqual(self.service.preflight(self.bid)['ready_row_count'],0)
    def test_save_failure_before_head_preserves_old_version(self):
        p=self.preview();original=self.service.store.save
        def stop(*a,**k):raise OSError('TEST:before head')
        with patch.object(self.service.store,'save',side_effect=stop):
            with self.assertRaises(OSError):self.commit(p)
        self.assertEqual(self.service.store.load(self.bid)['revision'],0)
        self.commit(p);self.assertEqual(self.service.preflight(self.bid)['ready_row_count'],1)
    def test_save_failure_after_head_recovers_receipt(self):
        p=self.preview();original=self.service.store.save
        def stop(*a,**k):original(*a,**k);raise OSError('TEST:after head')
        with patch.object(self.service.store,'save',side_effect=stop):r=self.commit(p)
        self.assertTrue(r['recovered']);self.assertEqual(self.service.store.load(self.bid)['revision'],1)


if __name__=='__main__':unittest.main()
