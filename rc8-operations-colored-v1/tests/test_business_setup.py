"""Focused public-entry regressions; administrator fixtures are synthetic only."""
import copy, json, os
from pathlib import Path
from unittest.mock import patch
from test_v070_workflow import WorkflowTests
from arrival_core.core import Rejected,digest,context
from arrival_core.workflow import execute,invoke
from arrival_core.storage import Store,atomic_json
from arrival_core.business_setup import preflight,verify_contract
from arrival_core.decision_library import DecisionLibrary


class BusinessSetupTests(WorkflowTests):
    # Reuse the input builder, not its tests (load_tests below filters inherited tests).
    def prepare(self):
        return execute(self.output,{'message':'准备这批业务合同','files':[str(self.stage),str(self.invoice)]})['result']

    def test_setup_missing_files_contract_and_wrong_units(self):
        for files in ([],[str(self.stage)],[str(self.invoice)]):
            reply=execute(self.output,{'message':'处理这批日本到货','files':files})
            self.assertEqual(reply['status'],'needs_input')
        initial=invoke(self.output,'import-stage3','--source',self.stage,'--currency','JPY','--quantity-unit','')
        self.assertFalse(initial['business_review_allowed'])
        before=digest(Store(self.output).load(initial['batch']))
        with self.assertRaisesRegex(Rejected,'缺少批次合同'):
            invoke(self.output,'return-export','--batch',initial['batch'],'--material-history',self.history,'--file',self.delivery/'bad.xlsx')
        self.assertEqual(before,digest(Store(self.output).load(initial['batch'])))
        prepared=self.prepare()
        for settings in ({'authority_quantity_unit':'JPY'}, {'authority_quantity_unit':'公斤'},
                         {'execution_mode':'business'},{'row_quantity_units':{'99999':'件'}}):
            with self.assertRaises(Rejected):execute(self.output,{'message':'填写这批业务合同','contract':prepared['file'],'settings':settings})
        missing=json.loads(Path(prepared['file']).read_text(encoding='utf-8'));missing['sources']['invoice']['path']=str(self.root/'absent.xlsx')
        with self.assertRaises(OSError):
            from arrival_core.business_setup import managed_import
            managed_import(self.output,missing)

    def test_setup_controlled_sign_import_cli_and_immutability(self):
        original=Store(self.output).load(self.batch_id);before=digest(original)
        self.configure_synthetic()
        batch=Store(self.output).load(self.batch_id)
        self.assertEqual(before,digest(Store(self.output).load(original['id'])))
        verify_contract(self.output,batch['input_contract'])
        from arrival_core.business_setup import save_contract
        signed=save_contract(self.output,batch['input_contract'])
        rerun=invoke(self.output,'import-batch','--contract',signed['file'])
        self.assertTrue(rerun['resumed']);self.assertEqual(rerun['batch'],self.batch_id)
        with self.assertRaises(Rejected):execute(self.output,{'message':'填写这批业务合同','contract':signed['file'],'settings':{'invoice_quantity_unit':'盒'}})
        with self.assertRaises(Rejected):execute(self.output,{'message':'处理这批日本到货','execution_mode':'business'})
        forged=copy.deepcopy(batch['input_contract']);forged['approval']['reference']='forged'
        with self.assertRaises(Rejected):verify_contract(self.output,forged)
        cfg=json.loads((self.output/'security/runtime.json').read_text(encoding='utf-8'));cfg['execution_mode']='business'
        atomic_json(self.output/'security/runtime.json',cfg)
        with self.assertRaises(Rejected):verify_contract(self.output,batch['input_contract'])

    def test_setup_preflight_collects_business_todos_and_ready_draft(self):
        # Aggregate missing configuration, rather than first-error-only startup.
        (self.output/'security/runtime.json').unlink()
        missing=preflight(self.output,files=[str(self.stage)])
        self.assertGreaterEqual(len(missing['todos']),4);self.assertFalse(missing['ready_for_review_submission'])
        self.assertFalse(missing['formal_output_allowed'])
        from arrival_core.contracts import ROLES
        atomic_json(self.output/'security/runtime.json',{'execution_mode':'synthetic_technical_test','quantity_units':['件','盒','套'],
                    'responsibilities':{r:['TECH'] for r in ROLES},'signing_key_env':'TECH_SIGNING_KEY'})
        self.configure_synthetic()
        lib=DecisionLibrary.create(self.root/'knowledge',source_root=self.output,source_kind='synthetic')
        with patch.dict(os.environ,{'TECH_SESSION':'TECH-ONLY'}):
            result=execute(self.output,{'message':'检查这批能否开始','batch':self.batch_id,'library':str(lib.root),'session_token_env':'TECH_SESSION'})['result']
        self.assertEqual(result['todos'],[]);self.assertTrue(result['ready_for_review_submission'])
        self.assertTrue(result['drafts_allowed']);self.assertFalse(result['formal_output_allowed'])

    def test_setup_unsigned_contract_and_untrusted_legacy_approval_rejected(self):
        prepared=self.prepare()
        with self.assertRaises(Rejected):execute(self.output,{'message':'签核这批业务合同','contract':prepared['file'],'confirm':True,
            'confirmed_hash':prepared['contract_hash'],'reference':'NOT APPROVAL','session_token_env':'ABSENT'})
        preview=self.modified_preview()['result'];before=digest(Store(self.output).load(self.batch_id))
        self.configure_synthetic();signed_id=self.batch_id
        # A valid synthetic session still cannot approve the unsigned old batch.
        with patch.dict(os.environ,{'TECH_SESSION':'TECH-ONLY'}), self.assertRaises(Rejected):
            execute(self.output,{'message':'确认提交这批审核','batch':self.imported['batch']['batch_id'],'confirm':True,
                    'preview_id':preview['preview_id'],'confirmed_hash':preview['confirmation_hash'],
                    'reference':'TEST','session_token_env':'TECH_SESSION'})
        self.assertEqual(before,digest(Store(self.output).load(self.imported['batch']['batch_id'])))
        request=self.root/'actor-request.json';batch=Store(self.output).load(signed_id)
        atomic_json(request,{'action':'confirm-products','actor':'fake','roles':['business'],'state_hash':digest(batch),'evidence':'fake'})
        with patch.dict(os.environ,{'TECH_SESSION':'TECH-ONLY'}),self.assertRaisesRegex(Rejected,'自报'):
            invoke(self.output,'apply','--batch',signed_id,'--request',request,'--session-token-env','TECH_SESSION')

    def test_setup_conversion_uses_existing_domain_preview_and_CAS(self):
        self.configure_synthetic();batch=Store(self.output).load(self.batch_id);row=batch['rows'][0]
        req=self.root/'identity-request.json'
        atomic_json(req,{'action':'approve-domain','state_hash':digest(batch),'evidence':'TEST identity confirmation',
                        'row_id':row['id'],'domain':'identity','payload':{'version':'v1','specification':'TEST single'}})
        with patch.dict(os.environ,{'TECH_SESSION':'TECH-ONLY'}):
            invoke(self.output,'apply','--batch',self.batch_id,'--request',req,'--session-token-env','TECH_SESSION')
        batch=Store(self.output).load(self.batch_id);before=digest(batch)
        payload={'source_unit':'件','declaration_unit':'件','internal_unit':'件','source':'TEST unit evidence',
                 'declaration_factor':'1','pieces_per_box':'2','internal_quantity':'2','internal_boxes':'1'}
        preview=execute(self.output,{'message':'预览这批单位换算','batch':self.batch_id,'row':row['id'],'conversion':payload})['result']
        self.assertEqual(before,digest(Store(self.output).load(self.batch_id)))
        req={'message':'确认这批单位换算','batch':self.batch_id,'preview_id':preview['preview_id'],
             'confirmed_hash':preview['confirmation_hash'],'confirm':True,'reference':'TEST reviewed conversion','session_token_env':'TECH_SESSION'}
        with patch.dict(os.environ,{'TECH_SESSION':'TECH-ONLY'}):
            committed=execute(self.output,req);again=execute(self.output,req)
        self.assertTrue(again['result']['replayed'])
        saved=Store(self.output).load(self.batch_id);self.assertEqual(saved['revision'],batch['revision']+1)
        self.assertEqual(saved['rows'][0]['authority'],batch['rows'][0]['authority'])
        self.assertEqual(saved['rows'][0]['reviews']['packaging']['confirmed_by'],'TECH')


def load_tests(loader,tests,pattern):
    import unittest
    return unittest.TestSuite(BusinessSetupTests(name) for name in dir(BusinessSetupTests) if name.startswith('test_setup_'))
