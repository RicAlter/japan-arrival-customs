"""Policy regressions. Engine invariants are tested by native real-file replay."""
import unittest,tempfile,sys,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction.submission import Service,Legacy
from interaction import save,Rejected

class SubmissionPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.file=self.folder/'return.xlsx';self.file.write_bytes(b'unit fixture, never business data')
        self.s=Service.__new__(Service);self.s.background=self.folder;self.s.root=self.folder;self.s.public=self.folder
        self.s.config={'batch_label':'UNIT'};self.head='h1';self.stage='basics'
        self.s.status=lambda:{'head':self.head,'stage':self.stage,'formal_output':False}
        self.s.deliver=lambda:{'business_files':[],'head':self.head,'formal_output':False}
        self.commit=Mock(side_effect=self.committed)
        self.fields={}
        self.s.engine=SimpleNamespace(bid='a'*24,basics=SimpleNamespace(commit=self.commit,
            read_current=lambda bid:{'fields':self.fields},prepare_confirmation=Mock(return_value={'plan_id':'new-plan'})))
        self.legacy=patch.object(Legacy,'upload');self.upload=self.legacy.start();self.addCleanup(self.legacy.stop)
        self.lookup=patch('interaction.get');self.get=self.lookup.start();self.addCleanup(self.lookup.stop)
        self.get.side_effect=lambda root,token:{'plan_id':'plan','preview_id':'preview'} if token=='plan' else {'proposals':{}}
        self.body={'kind':'basics','confirmation_required':True,'plan_id':'plan','proposed_changes':1,'purchase_prices_deferred':1,
            'selection':{'save_changes':['N2'],'confirm_fields':['N2'],'adopt_candidates':[],'evidence':{}},
            'change_details':[{'target':'N2','field':'category','needs_further_confirmation':False}]}
        self.upload.return_value=self.body
    def committed(self,*a,**k):self.head='h2';return {'replayed':False}
    def test_valid_return_auto_saves_without_second_user_confirmation(self):
        r=self.s.upload(self.file,kind='basics',reference='operator submission')
        self.assertTrue(r['saved']);self.assertFalse(r['confirmation_required']);self.assertEqual(r['accepted_cells'],1)
        self.commit.assert_called_once();self.assertIn('operator submission',self.commit.call_args.kwargs['reference'])
        self.assertTrue(self.upload.call_args.kwargs['confirm_material'])
    def test_invalid_cell_is_exception_not_blanket_rejection(self):
        self.body['change_details'].append({'target':'O2','field':'material_reference','needs_further_confirmation':True})
        r=self.s.upload(self.file,reference='submitted')
        self.assertEqual(r['accepted_cells'],1);self.assertEqual(r['exceptions'][0]['target'],'O2');self.assertTrue(r['saved'])
    def test_missing_purchase_evidence_does_not_confirm_price(self):
        r=self.s.upload(self.file,reference='submitted')
        self.assertEqual(r['purchase_prices_deferred'],1)
        self.assertNotIn('H2',self.body['selection']['confirm_fields'])
    def test_identical_return_is_idempotent(self):
        self.s.upload(self.file,reference='first')
        r=self.s.upload(self.file,reference='second')
        self.assertTrue(r['receipt_replayed']);self.assertEqual(self.commit.call_count,1)
    def test_new_price_evidence_not_hidden_by_identical_workbook(self):
        self.s.upload(self.file,reference='first')
        self.s.upload(self.file,reference='new evidence',purchase_evidence={'H2':{'unit':'盒','source_ref':'order'}})
        self.assertEqual(self.commit.call_count,2)
    def test_validation_failure_does_not_save_or_add_receipt(self):
        self.upload.side_effect=Rejected('original quantity changed')
        with self.assertRaisesRegex(ValueError,'original quantity'):self.s.upload(self.file,reference='submitted')
        self.commit.assert_not_called();self.assertFalse((self.folder/'last-stage-submission.json').exists())
    def test_missing_submit_reference_rejected(self):
        with self.assertRaises(ValueError):self.s.upload(self.file,reference='')
        self.upload.assert_not_called()
    def test_valid_changed_spec_is_not_blocked_by_old_price_context_flag(self):
        self.fields={'G2':{'target':'G2','row_id':'row','field':'specification','confirmed':False,'value':{'type':'text','value':'old'}}}
        self.get.side_effect=lambda root,t:{'preview_id':'preview'} if t=='plan' else {'proposals':{'G2':{'field':'specification','after':{'type':'text','value':'new'},'reasons':[]}}}
        self.s.upload(self.file,reference='operator changed specification')
        selection=self.s.engine.basics.prepare_confirmation.call_args.args[1]
        self.assertIn('G2',selection['confirm_fields'])
    def test_duplicate_readonly_identity_does_not_auto_confirm_spec(self):
        self.fields={'G2':{'target':'G2','row_id':'row','field':'specification','confirmed':False,'value':{'type':'text','value':'old'}}}
        self.get.side_effect=lambda root,t:{'preview_id':'preview'} if t=='plan' else {'proposals':{'G2':{'field':'specification','after':{'type':'text','value':'new'},'reasons':['只读内容重复，需明确原行范围']}}}
        self.s.upload(self.file,reference='ambiguous specification')
        self.s.engine.basics.prepare_confirmation.assert_not_called()
    def test_valid_changed_price_with_explicit_source_unit_can_be_accepted(self):
        self.fields={'H2':{'target':'H2','row_id':'row','field':'purchase_unit_price','confirmed':False,'value':{'type':'number','value':'10'}}}
        self.get.side_effect=lambda root,t:{'preview_id':'preview'} if t=='plan' else {'proposals':{'H2':{'field':'purchase_unit_price','after':{'type':'number','value':'12'},'reasons':['采购价格币种、计价单位及来源须另行明确']}}}
        self.s.upload(self.file,reference='order backed price',purchase_evidence={'H2':{'source_ref':'order JPY quote','unit':'盒'}})
        selection=self.s.engine.basics.prepare_confirmation.call_args.args[1]
        self.assertIn('H2',selection['confirm_fields']);self.assertEqual(selection['evidence']['H2']['unit'],'盒')
    def test_actual_entry_binds_submission_service(self):
        source=(Path(__file__).resolve().parents[1]/'run.py').read_text('utf8')
        self.assertIn('from interaction.submission import Service',source)
    def calculation(self,blocked=False):
        self.stage='calculation'
        self.body={'kind':'calculation','confirmation_required':True,'preview_id':'p','blocked_rows':int(blocked)}
        self.upload.return_value=self.body
        preview={'upload':str(self.file),'facts':[{'parent_id':'row1','errors':['unit missing'] if blocked else []}],
            'blocked_rows':int(blocked),'price_comparability_pending':False,'new_identity_rows_pending':[],
            'weights_unchanged':True,'source_totals_consistent':True}
        self.get.side_effect=lambda *a:preview
        self.s._publish=lambda source,name:str(self.file)
    def test_calculation_partial_submission_saved_and_exceptions_retained(self):
        self.calculation(True)
        with patch('interaction.submission.rt.cli.confirm_review') as final:
            r=self.s.upload(self.file,kind='calculation',reference='return')
        final.assert_not_called();self.assertTrue(r['saved']);self.assertFalse(r['confirmation_required'])
        self.assertTrue((self.folder/'current-review-submission.json').exists());self.assertEqual(r['blocked_rows'],1)
    def test_calculation_passing_submission_continues_controlled_drafts(self):
        self.calculation(False)
        with patch('interaction.submission.rt.cli.confirm_review',return_value={'controlled_drafts':True}) as final:
            self.s.upload(self.file,kind='calculation',reference='return')
        final.assert_called_once();self.assertTrue(final.call_args.kwargs['explicit_confirmation'])
    def test_passing_returned_explicit_basis_needs_no_extra_global_click(self):
        self.calculation(False)
        preview=self.get.side_effect(None,None);preview['price_comparability_pending']=True
        preview['facts'][0]['values']={'conversion_reference':'operator supplied applicable purchase and actual price unit proof'}
        self.get.side_effect=lambda *a:preview
        save(self.folder/'current-review-export.json',{'export_id':'export'})
        validated={**preview,'price_comparability_pending':False,'preview_id':'accepted-basis-preview'}
        with patch('interaction.submission.rt.review.preview_return',return_value=validated) as redo,patch('interaction.submission.rt.cli.confirm_review',return_value={}) as final:
            r=self.s.upload(self.file,kind='calculation',reference='returned complete workbook')
        self.assertIn('operator',redo.call_args.kwargs['price_basis_reference']);self.assertFalse(r['confirmation_required'])
        self.assertEqual(final.call_args.args[1],'accepted-basis-preview')

if __name__=='__main__':unittest.main()
