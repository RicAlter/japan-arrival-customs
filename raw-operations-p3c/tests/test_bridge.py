"""Synthetic protection tests; not new-batch or human business acceptance."""
import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from raw_operations.bridge import bootstrap,execute,align,conversion_groups,ROOT,REPO,digest,load,Rejected
bootstrap()
from arrival_core.importer import import_raw_invoice
from arrival_core.operations_adapter import prepare
from product_reference.b4_store import SourceBundleStore
from source_adapters.common import write_bundle
from openpyxl import Workbook,load_workbook


def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


adapter_fixture=module('p3c_adapter_fixture',REPO/'rc8-operations-colored-v1/tests/test_operations_adapter.py')
p1_fixture=module('p3c_reference_fixture',REPO/'product-library-p1/tests/test_product_reference.py')


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.src=self.root/'source';self.src.mkdir()
        self.files=adapter_fixture.fixtures(self.src,formula=True)
        self.raw=self.src/'raw.xlsx';w=Workbook();s=w.active;s.title='invoice (計算)'
        for col,label in {'C':'ProductCode(JANCode)','D':'DescriptionofGoods','G':'Origin','H':'UnitPrice(日本JPY)','I':'Qty','K':'Subtotal'}.items():s[col+'17']=label
        for col,v in {'A':'HA001','C':'0010001','D':'Synthetic Japanese','G':'JP','H':100,'I':2,'K':200}.items():s[col+'18']=v
        s=w.create_sheet('重さとサイズ');s.append(['箱番','重さ','カートン個数','合計重量（KGS)']);s.append(['HA001',2,1,2])
        w.save(self.raw);w.close()
        self.db=self.root/'reference.sqlite3'
        with closing(sqlite3.connect(self.db)) as c,c:c.execute('create table metadata(key text primary key,value text)');c.execute("insert into metadata values ('schema_version','3')")
        self.store=SourceBundleStore.initialize(self.db,new_database=True)
        self.n=0;self.add_reference()

    def tearDown(self):self.temp.cleanup()
    def dest(self):self.n+=1;return self.root/('output'+str(self.n))
    def req(self,context=True):
        r={'batch_id':'KMT20261002','raw_file':str(self.raw),'library_config':{'database':str(self.db)}}
        if context:r.update(business_file=self.files[0],declaration_file=self.files[1])
        return r
    def add_reference(self,source_id='independent',provenance_hash='a'*64):
        r=p1_fixture.record('r'+source_id,p1_fixture.identity(code='0010001',name='Synthetic Japanese',version=None,spec=None),internal='NEVER APPLY',material='UNAPPROVED MATERIAL')
        r['provenance'].update(source_id=source_id,file_sha256=provenance_hash)
        incoming_dir=self.root/'incoming';incoming_dir.mkdir(exist_ok=True)
        incoming=incoming_dir/('seed-'+source_id+'.json');incoming.write_text('[]')
        req={'schema_version':'product-source-request/1','source_id':source_id,'source_version':'v1','mapping_version':'TEST',
          'authorization_reference':'TEST:fixture','files':[{'path':str(incoming)}]}
        bundle=self.root/('bundle-'+source_id);write_bundle(req,[r],bundle,'order')
        self.store.import_bundle(bundle,authorization_reference='TEST:fixture',backup_directory=self.root/('backup-'+source_id))
    def run_bridge(self,r=None):
        self.last=self.dest();return execute(self.last,self.req() if r is None else r)
    def no_pair(self,r):
        self.assertFalse(r['can_enter_pair_calculation']);self.assertEqual(r['business_files'],[])
        self.assertIsNone(r['business_exception_total']);self.assertIsNone(r['manual_input_cells']);self.assertFalse(r['formal_output'])
        self.assertFalse((self.last/'delivery').exists());self.assertFalse(list(self.last.rglob('confirmed-arrival-v1.xlsx')))

    def test_real_parsers_keep_retail_and_business_amounts_separate(self):
        r=self.run_bridge();self.assertEqual(r['status'],'needs_confirmation',r);self.no_pair(r)
        self.assertEqual(r['facts']['raw_retail_subtotal_jpy'],'200');self.assertEqual(r['facts']['business_source_amount_jpy'],'100')
        self.assertEqual(r['facts']['exact_source_links'],1);self.assertFalse(r['facts']['units_confirmed'])

    def test_raw_only_preliminary_keeps_unknown_units_and_names(self):
        r=self.run_bridge(self.req(False));self.assertEqual(r['status'],'needs_input',r);self.no_pair(r)
        p=load(self.last/'technical/raw-observations.json');self.assertEqual(p['rows'][0]['product']['internal_name'],'')
        self.assertEqual(p['rows'][0]['arrival']['unit_raw'],'');self.assertEqual(p['arrival_summary']['subtotal_jpy'],'200')
        self.assertTrue(Path(r['preparation_files'][0]).is_file())

    def test_preliminary_is_reopened_and_formulas_are_not_executable(self):
        r=self.run_bridge();w=load_workbook(r['preparation_files'][0],data_only=False)
        try:self.assertEqual(w['初步整理']['C7'].value,18);self.assertFalse(any(c.data_type=='f' for row in w['初步整理'] for c in row))
        finally:w.close()

    def test_candidates_do_not_replace_current_values(self):
        r=self.run_bridge();p=load(self.last/'technical/operations-input-candidate.json')['plan']
        self.assertEqual(p['details'][0]['values']['内部中文名'],'PRIVATE-INTERNAL')
        self.assertEqual(p['details'][0]['values']['最终申报材质'],'PVC')
        self.assertEqual(r['facts']['historical_candidates_applied'],0)

    def test_same_batch_source_id_is_excluded(self):
        self.add_reference('KMT20261002-final')
        r=self.run_bridge();p=load(self.last/'technical/reference-candidates.json')
        self.assertIn('KMT20261002-final',p['excluded_source_ids']);self.no_pair(r)
        self.assertTrue(all(s['source_id']!='KMT20261002-final' for row in p['p1']['rows'] for c in row['candidates'] for s in c['sources']))

    def test_same_file_hash_excludes_renamed_source(self):
        self.add_reference('opaque-renamed',digest(self.files[0]));self.run_bridge()
        p=load(self.last/'technical/reference-candidates.json');self.assertIn('opaque-renamed',p['excluded_source_ids'])

    def test_p2b_same_batch_facts_are_removed_before_final_analysis(self):
        facts=[]
        for fid,batch,material in [('heldout','KMT20261002','HELD_OUT_MATERIAL'),('independent','OTHER-BATCH','REFERENCE_ONLY')]:
            facts.append({'fact_id':fid,'values':{'code_raw':'0010001','code_type':'source_identifier',
              'japanese_name':'Synthetic Japanese','version':None,'specification':None,'material_original':material},
              'source':{'path':'synthetic.xlsx','sha256':'b'*64,'batch_id':batch,'role':'historical_arrival','sheet':'Sheet1','row':2},
              'evidence':{},'approval':False,'review_status':'reference_only'})
        with closing(sqlite3.connect(self.db)) as c,c:
            c.executescript('''CREATE TABLE p2b_facts(fact_id TEXT PRIMARY KEY,payload TEXT);
                CREATE TABLE p2b_plans(plan_id TEXT PRIMARY KEY,payload TEXT,reference TEXT);
                CREATE TABLE p2b_basic_events(event_id TEXT PRIMARY KEY,plan_id TEXT,case_id TEXT,preview_hash TEXT,payload TEXT,recorded_at TEXT);''')
            c.executemany('insert into p2b_facts values (?,?)',[(f['fact_id'],json.dumps(f)) for f in facts])
        r=self.run_bridge();self.assertEqual(r['status'],'needs_confirmation',r)
        result=load(self.last/'technical/reference-candidates.json')
        self.assertEqual(result['excluded_p2b_fact_ids'],['heldout'])
        self.assertNotIn('HELD_OUT_MATERIAL',json.dumps(result['p2b']))
        self.assertEqual([f['fact_id'] for f in result['p2b']['facts']],['independent'])

    def test_current_quantity_conflict_is_not_hidden_by_matching_code(self):
        raw=import_raw_invoice(self.raw);plan=prepare(self.files);raw['rows'][0]['authority']['quantity']='3'
        m=align(raw,plan);self.assertEqual(len(m['linked']),1)
        self.assertEqual(m['current_source_conflicts'][0]['current_source_differences'],['quantity'])

    def test_recode_and_split_are_not_inferred(self):
        raw=import_raw_invoice(self.raw);plan=prepare(self.files);plan['details'][0]['values']['商品编码']='changed'
        m=align(raw,plan);self.assertEqual(len(m['linked']),0);self.assertEqual(len(m['unmatched_raw']),1)
        self.assertEqual(len(m['unmatched_operations']),1);self.assertEqual(m['recodes_inferred'],0);self.assertEqual(m['splits_inferred'],0)

    def test_duplicate_carton_code_is_not_collapsed(self):
        raw=import_raw_invoice(self.raw);plan=prepare(self.files);raw['rows'].append(copy.deepcopy(raw['rows'][0]))
        m=align(raw,plan);self.assertEqual(len(m['linked']),0);self.assertEqual(len(m['unmatched_raw']),2)

    def test_same_code_different_name_is_a_separate_source_conflict(self):
        raw=import_raw_invoice(self.raw);plan=prepare(self.files);plan['details'][0]['values']['日文品名']='different'
        m=align(raw,plan);self.assertEqual(len(m['linked']),1);self.assertEqual(len(m['current_source_conflicts']),1)
        self.assertFalse(m['linked'][0]['identity_confirmed'])

    def test_outer_whitespace_is_evidence_not_a_business_conflict(self):
        raw=import_raw_invoice(self.raw);plan=prepare(self.files)
        raw['rows'][0]['identity']['japanese_name']+='\t　'
        m=align(raw,plan);self.assertEqual(m['current_source_conflicts'],[])
        self.assertEqual(len(m['source_formatting_differences']),1)
        self.assertTrue(m['source_formatting_differences'][0]['original_values_preserved'])

    def test_groups_bind_cells_rows_and_separate_box_relations(self):
        raw=import_raw_invoice(self.raw);p=prepare(self.files);m=align(raw,p);g=conversion_groups(p,m)
        self.assertEqual(len(g),1);self.assertEqual(g[0]['relation']['declaration_factor'],'3/2')
        self.assertFalse(g[0]['approved']);self.assertEqual(g[0]['rows'][0]['evidence']['business_quantity']['cell'],'J2')
        changed=copy.deepcopy(p);new=copy.deepcopy(p['details'][0]);new['values']['稳定行号']='another';new['values']['内部盒数']='2'
        changed['details'].append(new);changed['special_conversions'].append({'row_id':'another'})
        self.assertEqual(len(conversion_groups(changed,m)),2)

    def test_group_scope_changes_when_source_range_changes(self):
        p=prepare(self.files);m=align(import_raw_invoice(self.raw),p);a=conversion_groups(p,m)[0]['scope_hash']
        p['source_bundle_hash']='changed';self.assertNotEqual(a,conversion_groups(p,m)[0]['scope_hash'])

    def test_answer_and_fabricated_confirmation_parameters_are_rejected(self):
        for field in ('answer_file','units_confirmation','confirm','formal_output'):
            r=self.req();r[field]=True
            with self.assertRaises(Rejected):execute(self.dest(),r)

    def test_wrong_batch_and_partial_context_are_rejected(self):
        r=self.req();r['batch_id']='KMT20260802'
        with self.assertRaises(Rejected):execute(self.dest(),r)
        r=self.req();r.pop('declaration_file')
        with self.assertRaises(Rejected):execute(self.dest(),r)

    def test_unavailable_library_is_failure_not_zero_or_success(self):
        r=self.req();r['library_config']['database']=str(self.root/'missing.sqlite3')
        out=self.run_bridge(r);self.assertEqual(out['status'],'validation_incomplete');self.no_pair(out)
        self.assertEqual(out['preparation_files'],[]);self.assertFalse((self.root/'missing.sqlite3').exists())

    def test_missing_weights_reports_a_specific_failure(self):
        w=load_workbook(self.raw);w.remove(w['重さとサイズ']);w.save(self.raw);w.close()
        r=self.run_bridge();self.assertEqual(r['status'],'validation_incomplete');self.no_pair(r)
        self.assertIn('箱重工作表不存在',r['reason']);self.assertEqual(r['preparation_files'],[])

    def test_source_change_during_query_invalidates_preparation(self):
        from raw_operations.bridge import references
        def changed(*args):
            value=references(*args);self.raw.write_bytes(self.raw.read_bytes()+b'changed');return value
        with patch('raw_operations.bridge.references',side_effect=changed):r=self.run_bridge()
        self.assertEqual(r['status'],'validation_incomplete');self.no_pair(r);self.assertEqual(r['preparation_files'],[])

    def test_dependencies_originals_and_database_stay_unchanged(self):
        files=[self.raw,Path(self.files[0]),Path(self.files[1]),self.db];before={str(p):digest(p) for p in files}
        self.run_bridge();self.assertEqual(before,{str(p):digest(p) for p in files});bootstrap()
        with self.assertRaises(Rejected):execute(self.last,self.req())


if __name__=='__main__':unittest.main()
