from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

from a_input.bridge import Bridge, project, dependencies, REPO, key, Rejected
dependencies()
from arrival_core.core import new_row, new_batch, context, exact_price, validate
from a_confirm import model


def fixture():
    source = {'sha256': 'a'*64, 'path': 'synthetic.xlsx', 'sheet': 'Sheet1', 'row': 2}
    row = new_row(source, {'qty': '8', 'amount': '200', 'code': '00123', 'ja': 'test',
                          'internal': 'CANDIDATE', 'material': 'CANDIDATE'}, currency='JPY', quantity_unit='')
    rid = row['id']
    fields = {}
    for cell, name, val in [('C2','product_code','00123'), ('F2','specification','spec'),
                            ('H2','pieces_per_box','8'), ('G2','purchase_unit_price','200'),
                            ('E2','internal_name','中文名')]:
        fields[cell] = {'row_id': rid, 'field': name, 'value': {'type':'text','value':val},
                        'status':'candidate', 'confirmed':False}
    fields['H2'].update(confirmed=True, status='adopted_reference', adopted_basis_current=True,
                        confirmation={'reference':'TEST:explicit H'},
                        evidence={'source_ref':'TEST:box document','meaning':'pieces_per_box'})
    fields['H2']['identity_context_hash'] = model.identity_context(fields, rid)
    fields['F2'].update(confirmed=True, status='business_confirmed', confirmation={'reference':'TEST:spec'},
                        identity_context_hash=model.identity_context(fields,rid))
    row['identity']['specification'] = 'spec'
    proof = {'confirmed_by':'TEST','confirmed_at':'TEST','reference':'TEST:scope'}
    values = {'quantity':'8','amount':'200','quantity_unit':'件','currency':'JPY','reason':'TEST'}
    record = {'version':1,'previous_hash':None,'values':values,'fact_hash':key(context(row)),
              'source':source,'status':'business_amount_approved'}
    record['record_hash']=key(record)
    row['business_amount']={'schema':'japan-arrival/business-amount-1','versions':[record],'current_version':1}
    row['reviews']['price']=dict(proof,business_amount_hash=record['record_hash'])
    row['reviews']['identity']=proof
    row['reviews']['packaging']=proof
    row['packaging']={'source_unit':'件','declaration_unit':'件','declaration_factor':'1',
                      'internal_unit':'件','internal_quantity':'8','internal_boxes':'1','pieces_per_box':'8',
                      'source':'TEST:unit document','context':context(row)}
    batch=new_batch([row],[])
    view={'fields':fields,'calculated_cells':[{'row_id':rid,'status':'within_100_jpy'}],
          'batch_id':batch['id'],'a_version':'TEST-V1','current_hash':key(batch),
          'price_basis_hash':'TEST','pricing_counts':{'within_100_jpy':1}}
    return view,batch


class ProjectionTests(unittest.TestCase):
    def test_rc5_accepts_confirmed_basis_and_exact_price_without_rendering(self):
        v,b=fixture(); out=project(v,b)
        self.assertTrue(out['rc5_schema_accepted']); validate(out['rc5_input'])
        self.assertEqual(exact_price(out['rc5_input']['rows'][0])['unit_price_denominator'],'1')
        self.assertFalse(out['calculation_executed']);self.assertFalse(out['formal_output'])

    def test_candidate_not_projected_material_not_approved(self):
        v,b=fixture(); r=project(v,b)['rc5_input']['rows'][0]
        self.assertEqual(r['product']['internal_name'],'');self.assertIsNone(r['material']['selected'])

    def test_no_ledger_does_not_use_qty_or_subtotal_observation(self):
        v,b=fixture(); b['rows'][0].pop('business_amount')
        out=project(v,b);self.assertEqual(out['ready_row_count'],0)
        self.assertIn('qty_actual_unit_unconfirmed',out['row_checks'][0]['blockers'])

    def test_h_alone_does_not_confirm_unit(self):
        v,b=fixture(); b['rows'][0]['reviews']['price']=None
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_h_unconfirmed_blocks_even_with_packaging_review(self):
        v,b=fixture();v['fields']['H2']['confirmed']=False
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_h_zero_rejected(self):
        v,b=fixture();v['fields']['H2']['value']['value']='0'
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_h_mismatch_rejected(self):
        v,b=fixture();v['fields']['H2']['value']['value']='7'
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_actual_unit_not_equal_h_unit_rejected(self):
        v,b=fixture();b['rows'][0]['packaging']['source_unit']='盒'
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_context_change_invalidates_ledger(self):
        v,b=fixture();v['fields']['F2']['value']['value']='new spec'
        v['fields']['F2']['identity_context_hash']=model.identity_context(v['fields'],b['rows'][0]['id'])
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_invalid_packaging_context_rejected(self):
        v,b=fixture(); b['rows'][0]['packaging']['context']={}
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_synthetic_approval_never_production_basis(self):
        v,b=fixture(); rec=b['rows'][0]['business_amount']['versions'][0]
        rec['status']='synthetic_technical_approved';rec.pop('record_hash');rec['record_hash']=key(rec)
        b['rows'][0]['reviews']['price']['business_amount_hash']=rec['record_hash']
        self.assertEqual(project(v,b)['ready_row_count'],0)

    def test_price_reference_pending_does_not_replace_independent_amount(self):
        v,b=fixture();v['calculated_cells'][0]['status']='exceeds_100_jpy'
        out=project(v,b);self.assertEqual(out['ready_row_count'],1)
        self.assertTrue(out['row_checks'][0]['price_reference_pending'])
        self.assertEqual(out['rc5_input']['rows'][0]['business_amount'],b['rows'][0]['business_amount'])

    def test_partial_rows_excluded_without_stopping_ready_rows(self):
        v,b=fixture(); row=deepcopy(b['rows'][0]);row['source']['row']=3;row['id']='second';row.pop('business_amount')
        b['rows'].append(row)
        out=project(v,b);self.assertEqual(out['ready_row_count'],1);self.assertEqual(out['blocked_row_count'],1)

    def test_input_immutable_and_deterministic(self):
        v,b=fixture();before=key([v,b]);self.assertEqual(project(v,b),project(v,b))
        self.assertEqual(before,key([v,b]))

    def test_no_purchase_quantity_substitution(self):
        v,b=fixture();self.assertIsNone(project(v,b)['row_checks'][0]['purchase_quantity'])


spec=importlib.util.spec_from_file_location('a04_a03_fixture',REPO/'a03-confirmation/tests/test_confirmation.py')
fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f=fx.ConfirmationTests('test_partial_confirmation_saves_only_selected_changes');self.f.setUp()
        self.bridge=Bridge(self.f.service.root)
    def tearDown(self): self.f.tearDown()
    def test_real_a03_reader_same_version_identical(self):
        a=self.bridge.prepare(self.f.bid);b=self.bridge.prepare(self.f.bid)
        self.assertEqual(a,b);self.assertIsNone(self.bridge.current_input(a))
    def test_partial_confirmation_and_version_invalidation(self):
        old=self.bridge.prepare(self.f.bid)
        p=self.f.preview({'E2':'人工名'})
        self.f.commit(self.f.plan(p,fx.selection(['Sheet1!E2'],['Sheet1!E2'])))
        new=self.bridge.prepare(self.f.bid)
        self.assertNotEqual(old['input_fingerprint'],new['input_fingerprint'])
        self.assertEqual(new['ready_row_count'],0)
        self.assertIn('internal_name',new['row_checks'][0]['confirmed_fields'])
        with self.assertRaises(Rejected): self.bridge.current_input(old)
    def test_tampered_input_rejected(self):
        a=self.bridge.prepare(self.f.bid);a['ready_row_count']=1
        with self.assertRaises(Rejected): self.bridge.current_input(a)
    def test_unapproved_fields_not_accepted(self):
        a=self.bridge.prepare(self.f.bid)
        self.assertEqual(a['row_checks'][0]['confirmed_fields'],{})


if __name__=='__main__': unittest.main()
