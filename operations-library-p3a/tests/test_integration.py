import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from integrated_arrival.support import dependencies,REPO,digest,load,key
dependencies()
from integrated_arrival.flow import execute
from integrated_arrival.library import query as actual_query
from integrated_arrival.classification import classify_batch as actual_classify
from integrated_arrival.comparison import compare
from product_reference.b4_store import SourceBundleStore
from source_adapters.common import write_bundle
from arrival_core.operations_adapter import prepare
from arrival_core.report_templates import cache_formulas
from openpyxl import load_workbook


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

rc_fixture=module('p3a_rc5_synthetic_fixture',REPO/'rc8-operations-colored-v1/tests/test_colored_operations.py')
p1_fixture=module('p3a_p1_synthetic_fixture',REPO/'product-library-p1/tests/test_product_reference.py')


def edit(file,sheet,cell,value):
    wb=load_workbook(file);cached=load_workbook(file,data_only=True)
    caches={idx:{c.coordinate:cached[s.title][c.coordinate].value for row in s for c in row if c.data_type=='f'} for idx,s in enumerate(wb,1)}
    cached.close();wb[sheet][cell]=value;wb.save(file);wb.close();cache_formulas(file,caches)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=self.root/'source';self.src.mkdir();self.files=rc_fixture.fixtures(self.src)
        wb=load_workbook(self.files[1]);s=wb.worksheets[0];s['F2']=4;s['G2']=25;wb.save(self.files[1]);wb.close()
        cache_formulas(self.files[1],{1:{'P2':100}})
        self.db=self.root/'library.sqlite3'
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)');c.execute("INSERT INTO metadata VALUES ('schema_version','3')")
        store=SourceBundleStore.initialize(self.db,new_database=True)
        rows=[p1_fixture.record('a',p1_fixture.identity(code='0010001',name='Japanese'),material='CANDIDATE ONLY MATERIAL',internal='CANDIDATE ONLY INTERNAL'),
              p1_fixture.record('b',p1_fixture.identity(code='0010001',name='Other Japanese',version='v2'),material='WRONG IDENTITY MATERIAL')]
        incoming_dir=self.root/'incoming';incoming_dir.mkdir();incoming=incoming_dir/'seed.json';incoming.write_text('[]');bundle=self.root/'bundle'
        req={'schema_version':'product-source-request/1','source_id':'synthetic','source_version':'v1','mapping_version':'TEST',
             'authorization_reference':'TEST:fixture','files':[{'path':str(incoming)}]}
        write_bundle(req,rows,bundle,'order');store.import_bundle(bundle,authorization_reference='TEST:fixture',backup_directory=self.root/'backup')
        self.original_hash=digest(self.db);self.config={'database':str(self.db)};self.n=0

    def tearDown(self):self.temp.cleanup()
    def dest(self):self.n+=1;return self.root/('run'+str(self.n))
    def request(self,confirm=True):
        req={'message':'处理已确认运营表','files':self.files}
        if confirm:req['units_confirmation']=rc_fixture.confirmation(prepare(self.files))
        return req
    def run_flow(self,request=None,config=None):
        self.last=self.dest();return execute(self.last,request if request is not None else self.request(),config if config is not None else self.config)
    def assert_incomplete(self,r):
        self.assertNotIn(r['status'],('ok','ok_with_business_exceptions'))
        self.assertIsNone(r['business_exception_total']);self.assertIsNone(r['business_exception_rows']);self.assertIsNone(r['manual_input_cells'])
        self.assertEqual(r['business_files'],[]);self.assertNotIn('summary',r);self.assertFalse((self.last/'delivery').exists())

    def test_new_input_real_calculation_query_and_two_verified_tables(self):
        r=self.run_flow();self.assertEqual(r['status'],'ok',r);self.assertEqual(r['business_exception_total'],0)
        self.assertEqual(len(r['business_files']),2);self.assertEqual(len(list((self.last/'delivery').glob('*'))),2)
        self.assertEqual(digest(self.db),self.original_hash);self.assertTrue(r['summary']['long_term_cases'])
        self.assertFalse(r['formal_output']);self.assertFalse(r['material_approval'])

    def test_candidates_never_cover_current_material_names_F_notes_or_YD(self):
        r=self.run_flow();p=next(f for f in r['business_files'] if '内部' in f);wb=load_workbook(p,data_only=True);s=wb.worksheets[0]
        try:
            self.assertEqual([s[c].value for c in ['E2','F2','M2','S2','T2']],['PRIVATE INTERNAL','PRIVATE SPEC','PVC,纸',0,'原备注'])
        finally:wb.close()
        candidates=load(self.last/'technical/library-candidates.json');self.assertTrue(candidates['p1']['rows'][0]['candidates'])
        self.assertTrue(candidates['p1']['rows'][0]['rejected_candidates']);self.assertEqual(r['summary']['historical_values_applied'],0)

    def test_preview_never_reports_zero_before_confirmation(self):
        r=self.run_flow(self.request(False));self.assertEqual(r['status'],'needs_confirmation');self.assert_incomplete(r)

    def test_missing_current_material_is_input_failure_not_zero(self):
        edit(self.files[0],'Sheet1','M2',None);r=self.run_flow(self.request(False));self.assert_incomplete(r)

    def test_missing_quantity_is_input_failure_not_library_fill(self):
        edit(self.files[0],'Sheet1','I2',None);r=self.run_flow(self.request(False));self.assert_incomplete(r)

    def test_current_source_conflict_rejected(self):
        edit(self.files[1],'图片处理','M2','Metal');r=self.run_flow(self.request(False));self.assert_incomplete(r);self.assertIn('冲突',r['reason'])

    def test_missing_confirmation_basis_cannot_publish(self):
        req=self.request();req['units_confirmation']['reference']='';self.assert_incomplete(self.run_flow(req))

    def test_changed_confirmation_hash_cannot_publish(self):
        req=self.request();req['units_confirmation']['special_conversion_hash']='0'*64;self.assert_incomplete(self.run_flow(req))

    def test_missing_database_is_not_created(self):
        missing=self.root/'missing.sqlite3';r=self.run_flow(config={'database':str(missing)});self.assert_incomplete(r);self.assertFalse(missing.exists())

    def test_schema_v2_rejected_without_migration(self):
        with closing(sqlite3.connect(self.db)) as c,c:c.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
        before=digest(self.db);self.assert_incomplete(self.run_flow());self.assertEqual(digest(self.db),before)

    def test_unknown_source_schema_rejected(self):
        with closing(sqlite3.connect(self.db)) as c,c:c.execute("UPDATE metadata SET value='99' WHERE key='source_bundle_schema_version'")
        before=digest(self.db);self.assert_incomplete(self.run_flow());self.assertEqual(digest(self.db),before)

    def test_partial_p2b_extension_rejected(self):
        with closing(sqlite3.connect(self.db)) as c,c:c.execute('CREATE TABLE p2b_facts(fact_id TEXT,payload TEXT)')
        self.assert_incomplete(self.run_flow())

    def test_active_database_log_rejected_without_touch(self):
        journal=Path(str(self.db)+'-wal');journal.write_bytes(b'fixture');self.assert_incomplete(self.run_flow());self.assertEqual(journal.read_bytes(),b'fixture')

    def test_readonly_P1_and_P2B_enriched_database_queried(self):
        from offline_identity.analyze import analyze
        from offline_identity.maintenance import register_plan
        from product_reference.database import clone
        source=self.db;copydb=self.root/'p2b.sqlite3';clone(source,copydb)
        raw={'row_id':'SYNTHETIC','query':p1_fixture.identity(code='0010001',name='Japanese',version=None,spec=None),
             'status':'incomplete_identity','candidates':[],'rejected_candidates':[],'material_reference_available':False}
        fact={'fact_id':'x','values':p1_fixture.identity(code='0010001',name='Japanese',version=None,spec='red'),
              'evidence':{'specification':{'cell':'C2'}},'source':{'path':'fixture','sheet':'Sheet1','row':2,'batch_id':'OLD','role':'orders'},
              'review_status':'reference_only','approval':False}
        plan=analyze({'rows':[raw]},[fact],{},target_batch_id='NEW');plan['source_reports']=[];plan['plan_id']=key(plan)
        register_plan(copydb,plan,'TEST:p2b');before=digest(copydb)
        r=self.run_flow(config={'database':str(copydb)});self.assertEqual(r['status'],'ok',r)
        self.assertTrue(r['summary']['p2b_available']);self.assertEqual(digest(copydb),before)

    def test_library_query_failure_never_becomes_no_match_zero(self):
        with patch('integrated_arrival.flow.query',side_effect=sqlite3.DatabaseError('TEST query failure')):r=self.run_flow()
        self.assert_incomplete(r);self.assertTrue((self.last/'technical/failure.json').is_file())

    def test_original_source_change_during_query_invalidates_delivery(self):
        def changed(info,batch):
            value=actual_query(info,batch);Path(self.files[0]).write_bytes(Path(self.files[0]).read_bytes()+b'changed');return value
        with patch('integrated_arrival.flow.query',side_effect=changed):r=self.run_flow()
        self.assert_incomplete(r)

    def test_database_change_during_query_invalidates_delivery(self):
        def changed(info,batch):
            value=actual_query(info,batch)
            with closing(sqlite3.connect(self.db)) as c,c:c.execute("INSERT INTO metadata VALUES ('changed','TEST')")
            return value
        with patch('integrated_arrival.flow.query',side_effect=changed):r=self.run_flow()
        self.assert_incomplete(r)

    def test_pair_tampering_after_verification_invalidates_delivery(self):
        def changed(batch,data,candidates):
            value=actual_classify(batch,data,candidates);standard=Path(batch['source']['path']) if 'source' in batch else Path(batch['rows'][0]['source']['path'])
            target=standard.parent.parent/'pair/海关报关单_受控测试草稿.xlsx';target.write_bytes(target.read_bytes()+b'changed');return value
        with patch('integrated_arrival.flow.classify_batch',side_effect=changed):r=self.run_flow()
        self.assert_incomplete(r)

    def test_frozen_dependency_failure_not_zero(self):
        with patch('integrated_arrival.flow.dependencies',side_effect=ValueError('TEST pin mismatch')):r=self.run_flow()
        self.assert_incomplete(r)

    def test_copy_failure_never_publishes_one_file(self):
        original=shutil.copyfile;calls=[]
        def copy_one(src,dst):
            calls.append(src)
            if len(calls)==2:raise OSError('TEST disk failure')
            return original(src,dst)
        with patch('integrated_arrival.flow.shutil.copyfile',side_effect=copy_one):r=self.run_flow()
        self.assert_incomplete(r);self.assertEqual(r['stage'],'final_integrity')

    def test_no_legacy_library_constructor_is_used(self):
        with patch('arrival_core.product_library.ProductLibrary.__init__',side_effect=AssertionError('OLD MIGRATION MUST NEVER RUN')):
            r=self.run_flow()
        self.assertEqual(r['status'],'ok',r)

    def test_missing_tax_input_remains_pending_red_and_counted_after_verification(self):
        self.files=rc_fixture.fixtures(self.src,rate=None)
        edit(self.files[1],'图片处理','F2',4);edit(self.files[1],'图片处理','G2',25);cache_formulas(self.files[1],{1:{'P2':100}})
        r=self.run_flow();self.assertEqual(r['status'],'ok_with_business_exceptions',r)
        self.assertEqual(r['business_exception_rows'],1);self.assertEqual(r['manual_input_cells'],1)
        file=next(f for f in r['business_files'] if '内部' in f);w=load_workbook(file,data_only=True)
        try:
            self.assertIsNone(w.worksheets[0]['O2'].value);self.assertIsNone(w.worksheets[0]['R2'].value)
            self.assertEqual(w.worksheets[0]['R2'].fill.fgColor.rgb,'FFFFC7CE')
        finally:w.close()

    def test_no_history_for_new_code_does_not_make_version_a_business_task(self):
        edit(self.files[0],'Sheet1','C2','SYNTHETIC-NEW');edit(self.files[1],'图片处理','B2','SYNTHETIC-NEW')
        r=self.run_flow();self.assertEqual(r['status'],'ok',r)
        self.assertEqual(r['summary']['p1_candidate_statuses'],{'no_match':1})
        self.assertEqual(r['summary']['version_states'],{'unknown':1});self.assertEqual(r['business_exception_total'],0)

    def test_unknown_current_material_is_red_without_candidate_substitution(self):
        edit(self.files[0],'Sheet1','M2','未知');edit(self.files[1],'图片处理','M2','未知')
        r=self.run_flow();self.assertEqual(r['status'],'ok_with_business_exceptions',r)
        self.assertEqual(r['business_exception_rows'],1);self.assertEqual(r['current_red_cells_added'],2)
        for file in r['business_files']:
            w=load_workbook(file,data_only=True)
            try:
                self.assertEqual(w.worksheets[0]['M2'].value,'未知');self.assertEqual(w.worksheets[0]['M2'].fill.fgColor.rgb,'FFFFC7CE')
            finally:w.close()

    def test_placeholder_confirmation_basis_is_not_real_confirmation(self):
        req=self.request();req['units_confirmation']['reference']='待确认';r=self.run_flow(req);self.assert_incomplete(r)
        self.assertIn('确认依据不足',r['reason'])

    def test_batch_amount_difference_is_a_current_conflict_not_zero(self):
        edit(self.files[1],'图片处理','G2',26);cache_formulas(self.files[1],{1:{'P2':104}})
        r=self.run_flow();self.assertEqual(r['status'],'ok_with_business_exceptions',r)
        self.assertEqual(r['summary']['business_exception_batches'],1);self.assertEqual(r['business_exception_total'],1)
        self.assertEqual(r['delivery_verification']['batch_difference_jpy'],'4')

    def test_late_failure_quarantines_both_files_and_removes_counts(self):
        from integrated_arrival.flow import check_hashes as original
        calls=[]
        def fail_late(snapshot):
            calls.append(1)
            if len(calls)==3:raise ValueError('TEST late integrity failure')
            return original(snapshot)
        with patch('integrated_arrival.flow.check_hashes',side_effect=fail_late):r=self.run_flow()
        self.assert_incomplete(r);self.assertEqual(len(list((self.last/'technical/rejected-delivery').glob('*.xlsx'))),2)

    def test_new_outputs_equal_engine_bytes_and_immutable_rerun(self):
        r=self.run_flow();before={f:digest(f) for f in r['business_files']}
        for f in r['business_files']:
            original=Path(r['engine_pair'])/Path(f).name
            self.assertEqual(digest(f),digest(original));self.assertTrue(compare(f,original)['equal'])
        from integrated_arrival.support import Rejected
        with self.assertRaises(Rejected):execute(self.last,self.request(),self.config)
        self.assertEqual(before,{f:digest(f) for f in before})


if __name__=='__main__':unittest.main()
