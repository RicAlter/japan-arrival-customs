"""Synthetic reference retrieval, clone-only imports and evidence regression."""
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from openpyxl import Workbook

from product_reference.b4_store import SourceBundleStore
from product_reference.core import Rejected
from product_reference.database import digest, inspect, clone, import_bundle
from product_reference.query import BatchQuery, evidence
from product_reference.sites import requests_for, validate_response
from product_reference.workbooks import extract, collect_bundle
from source_adapters.common import write_bundle


def identity(code='00123', version='v1', spec='red', name='Japanese A', kind='source_identifier'):
    return dict(code_raw=code, code_type=kind if code else None, japanese_name=name, version=version, specification=spec)


def record(rid, ident, material='紙、スチール等', internal='Synthetic A'):
    evidence_file = 'evidence/' + rid + '.json'
    fields = {field: {'value': value, 'raw_value': value, 'reference_type': 'historical_reference',
              'translation_status': 'not_applicable', 'evidence': [{'file': evidence_file, 'sheet': 'Sheet1', 'row': 2, 'cell': 'B2', 'quote': value}]}
              for field, value in {'internal_name': internal, 'material_original': material}.items()}
    return {'source_record_id': rid, 'identity': ident,
            'provenance': {'source_id': 'synthetic', 'source_version': 'v1', 'file_sha256': 'a'*64,
                           'file_name': 'synthetic.xlsx', 'sheet': 'Sheet1', 'row': 2},
            'fields': fields, 'status': 'succeeded', 'review_status': 'reference_only', 'approval': False,
            '_evidence': {evidence_file: {'synthetic': True, 'original': material}}}


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.db = self.root/'original.sqlite3'
        # New synthetic fixture only: production CLI intentionally has no init.
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
            conn.execute("INSERT INTO metadata VALUES ('schema_version','3')")
        self.store = SourceBundleStore.initialize(self.db, new_database=True)
        rows = [record('r1', identity()), record('r2', identity(version='v2', spec='blue'), internal='Synthetic B'),
                record('r3', identity(code=None, spec='red'), internal='No code'),
                record('r4', identity(code='00999', kind='JAN')),
                record('r5', identity(code='incomplete', name=None, version=None, spec=None))]
        self.bundle = self.make_bundle(rows, 'initial')
        self.store.import_bundle(self.bundle, authorization_reference='TEST:fixture', backup_directory=self.root/'backups')
        self.before = digest(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def make_bundle(self, rows, name, reference='TEST:fixture'):
        inputs = self.root/'incoming'; inputs.mkdir(exist_ok=True); source = inputs/'synthetic.json'; source.write_text('[]')
        request = dict(schema_version='product-source-request/1', source_id='synthetic', source_version='v1',
                       authorization_reference=reference, mapping_version='synthetic-v1', files=[{'path': str(source)}])
        folder = self.root/name; write_bundle(request, rows, folder, 'order'); return folder

    def test_duplicate_code_queries_keep_order_and_versions(self):
        queries = [identity(version='v2', spec='blue'), identity(), identity()]
        result = BatchQuery(self.db).run(queries)
        self.assertEqual([r['index'] for r in result['rows']], [0,1,2])
        self.assertEqual([r['candidates'][0]['fields']['internal_name']['value'] for r in result['rows']], ['Synthetic B','Synthetic A','Synthetic A'])
        self.assertTrue(all(r['status']=='exact_reference' for r in result['rows']))
        self.assertEqual(digest(self.db), self.before)

    def test_missing_identity_is_not_wildcard(self):
        r = BatchQuery(self.db).run([{'code_raw':'00123'}])['rows'][0]
        self.assertEqual(r['status'],'ambiguous')
        self.assertTrue(all(c['match']=='candidate_only' for c in r['candidates']))
        r = BatchQuery(self.db).run([identity(code='incomplete')])['rows'][0]
        self.assertEqual(r['status'],'candidates_incomplete_identity')
        self.assertIn('version',r['candidates'][0]['unknown_comparisons'])

    def test_mismatched_name_or_spec_rejects_even_single_code(self):
        r = BatchQuery(self.db).run([identity(name='Other A', spec='red')])['rows'][0]
        self.assertEqual(r['status'],'identity_conflict')
        self.assertFalse(r['candidates']); self.assertEqual(len(r['rejected_candidates']),2)

    def test_jan_namespace_and_leading_zero_not_inferred(self):
        rows = BatchQuery(self.db).run([{'jan':'00999'}, {'code_raw':'00999'}, {'jan':'999'}])['rows']
        self.assertTrue(rows[0]['candidates']); self.assertEqual(rows[1]['status'],'no_match'); self.assertEqual(rows[2]['status'],'no_match')
        r = BatchQuery(self.db).run([{'code_raw':'00999'}], namespace_aliases=[{'from':'source_identifier','to':'JAN','reference':'TEST explicit alias'}])
        self.assertTrue(r['rows'][0]['candidates'])
        with self.assertRaises(Rejected): BatchQuery(self.db).run([],namespace_aliases=[{'from':'JAN','to':'source_identifier'}])

    def test_no_code_preserved_and_not_merged(self):
        r = BatchQuery(self.db).run([identity(code=None)])['rows'][0]
        self.assertEqual(r['status'],'no_code_candidates'); self.assertEqual(len(r['candidates']),1)
        self.assertEqual(inspect(self.db)['tables']['source_ingest_observations']['rows'],5)

    def test_material_full_text_and_source_evidence(self):
        r = BatchQuery(self.db).run([identity()])['rows'][0]['candidates'][0]
        m = r['material_references'][0]
        self.assertEqual(m['value'],'紙、スチール等'); self.assertEqual(m['reference_type'],'historical_reference')
        blob = evidence(self.db, m['source']['observation_sha256'], m['evidence'][0]['file'])
        self.assertEqual(blob['original'],'紙、スチール等')
        with self.assertRaises(Rejected): evidence(self.db,m['source']['observation_sha256'],'evidence/not-for-this-row.json')

    def test_same_identity_conflicts_and_no_d1_approval(self):
        bundle = self.make_bundle([record('conflict', identity(),internal='Conflicting A')], 'conflict')
        self.store.import_bundle(bundle,authorization_reference='TEST:fixture',backup_directory=self.root/'backups')
        r = BatchQuery(self.db).run([identity()])['rows'][0]
        self.assertEqual(r['status'],'matched_with_conflict'); self.assertFalse(r['automatic_approval']); self.assertFalse(r['final_material_selected'])
        self.assertIn('internal_name',r['candidates'][0]['conflicts'])

    def test_exclude_same_source_or_file_for_holdout(self):
        self.assertEqual(BatchQuery(self.db).run([identity()],exclude_source_ids=['synthetic'])['rows'][0]['status'],'no_match')
        self.assertEqual(BatchQuery(self.db).run([identity()],exclude_file_sha256=['a'*64])['rows'][0]['status'],'no_match')

    def test_clone_only_import_idempotent_and_original_unchanged(self):
        target = self.root/'working.sqlite3'; clone(self.db,target)
        auth = {'kind':'explicit_user_source_import_authorization','reference':'USER:synthetic-fixture',
                'source_ids':['synthetic'],'adapter_ids':['order'],'confirmed_by':'TEST USER','confirmed_at':'2026-11-02'}
        bundle = self.make_bundle([record('new',identity(code='NEW'))], 'new',auth['reference'])
        with self.assertRaises(Rejected): import_bundle(self.db,bundle,auth)
        self.assertEqual(import_bundle(target,bundle,auth)['new_observations'],1)
        self.assertEqual(import_bundle(target,bundle,auth)['status'],'unchanged_duplicate')
        self.assertEqual(digest(self.db),self.before)
        with self.assertRaises(Rejected): clone(self.db,target)

    def test_unsupported_schema_and_d1_do_not_migrate(self):
        p = self.root/'d1.sqlite3'
        with closing(sqlite3.connect(p)) as c, c: c.execute('CREATE TABLE decisions(id TEXT)')
        before = digest(p)
        with self.assertRaises(Rejected): BatchQuery(p).run([identity()])
        with self.assertRaises(Rejected): clone(p,self.root/'badcopy.sqlite3')
        self.assertEqual(digest(p),before)

    def test_readonly_connection_blocks_sql_writes(self):
        from product_reference.database import read_only
        c = read_only(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError): c.execute('DELETE FROM source_ingest_observations')
        finally:c.close()

    def test_evidence_hash_tampering_is_detected(self):
        r = BatchQuery(self.db).run([identity()])['rows'][0]['candidates'][0]['material_references'][0]
        with closing(sqlite3.connect(self.db)) as c, c:c.execute("UPDATE source_ingest_files SET content=X'7B7D' WHERE relative_path=?",(r['evidence'][0]['file'],))
        with self.assertRaises(Rejected):evidence(self.db,r['source']['observation_sha256'],r['evidence'][0]['file'])

    def test_excel_mapping_formula_no_code_and_full_source(self):
        path = self.root/'incoming'/'source.xlsx'; w=Workbook();s=w.active;s.title='Sheet1'
        s.append(['code','name','spec','material','unmapped formula']);s.append(['00123','Japanese A','red','紙、スチール等','=1+1']);s.append([None,'Unnamed','blue','PVC',None]);w.save(path);w.close()
        mapping={'id':'synthetic','sheet':'Sheet1','header_row':1,'headers':{'A':'code','B':'name'},
                 'columns':{'code_raw':'A','japanese_name':'B','specification':'C','material_original':'D'},'item_column':'B'}
        rows=extract(path,mapping,source_id='synthetic',source_version='v1',authorization_reference='TEST:fixture')
        self.assertEqual(len(rows),2);self.assertIsNone(rows[1]['identity']['code_raw'])
        self.assertEqual(next(iter(rows[0]['_evidence'].values()))['cells']['E2']['formula'],'=1+1')
        # A mapped formula remains explicit missing data with raw evidence.
        mapping['columns']['internal_name']='E'
        rows=extract(path,mapping,source_id='synthetic',source_version='v1',authorization_reference='TEST:fixture')
        self.assertIsNone(rows[0]['fields']['internal_name']['value']);self.assertEqual(rows[0]['fields']['internal_name']['raw_value'],'=1+1')

    def test_five_site_interface_keeps_errors_separate_and_no_network(self):
        self.assertEqual(len(requests_for([identity()])),5)
        r={'site_id':'animate','query_id':'1','identity':identity(),'status':'rate_limited','references':[],'approval':False}
        self.assertEqual(validate_response(r)['status'],'rate_limited')
        r['status']='succeeded'
        with self.assertRaises(Rejected):validate_response(r)

    def test_site_success_requires_correct_domain_and_preserves_original(self):
        ref={'url':'https://www.amiami.jp/item','retrieved_at':'2026-11-02T00:00:00Z','content_sha256':'a'*64,
             'identity_quote':'Synthetic item','material_original':'紙、スチール等','material_translation':'纸、钢等','evidence_file':'offline-snapshot.json'}
        r={'site_id':'amiami','query_id':'1','identity':identity(),'status':'succeeded','references':[ref],'approval':False}
        self.assertEqual(validate_response(r)['references'][0]['material_original'],'紙、スチール等')
        ref['url']='https://amiami.jp.invalid.example/item'
        with self.assertRaises(Rejected):validate_response(r)

    def test_explicit_zero_and_invalid_identity_scalar(self):
        result=BatchQuery(self.db).run([{'code_raw':0}])
        self.assertEqual(result['rows'][0]['missing_identity'],['japanese_name','version','specification'])
        with self.assertRaises(Rejected):BatchQuery(self.db).run([{'code_raw':True}])

    def test_unknown_material_label_is_not_material_coverage(self):
        from product_reference.query import has_material
        self.assertFalse(has_material({'material_references':[{'field':'material_url','value':'https://invalid.example'}]}))
        self.assertFalse(has_material({'material_references':[{'field':'material_original','value':'未找到'}]}))
        self.assertTrue(has_material({'material_references':[{'field':'material_original','value':'紙、スチール等'}]}))

    def test_batch_f_labels_do_not_become_stable_spec_or_master_conflict(self):
        rows=[]
        for rid,label in [('label1','red整盒26'),('label2','red整盒30')]:
            row=record(rid,identity());body=copy.deepcopy(row['fields']['internal_name']);body.update(value=label,raw_value=label)
            row['fields']['packaging_label']=body;rows.append(row)
        bundle=self.make_bundle(rows,'labels');self.store.import_bundle(bundle,authorization_reference='TEST:fixture',backup_directory=self.root/'backups')
        r=BatchQuery(self.db).run([identity()])['rows'][0]
        self.assertEqual(r['status'],'exact_reference');self.assertNotIn('packaging_label',r['candidates'][0]['conflicts'])
        self.assertEqual({x['value'] for x in r['candidates'][0]['contextual_references']},{'red整盒26','red整盒30'})

    def test_bad_bundle_cannot_write_even_authorization_to_copy(self):
        target=self.root/'working.sqlite3';clone(self.db,target);before=digest(target)
        auth={'kind':'explicit_user_source_import_authorization','reference':'USER:synthetic-fixture',
              'source_ids':['synthetic'],'adapter_ids':['order'],'confirmed_by':'TEST USER','confirmed_at':'2026-11-02'}
        bundle=self.make_bundle([record('new',identity(code='NEW'))],'bad-bundle',auth['reference'])
        wrong_scope=copy.deepcopy(auth);wrong_scope['source_ids']=['not-synthetic']
        with self.assertRaises(Rejected):import_bundle(target,bundle,wrong_scope)
        self.assertEqual(digest(target),before)
        (bundle/'records.jsonl').write_text('{}',encoding='utf-8')
        with self.assertRaises(Rejected):import_bundle(target,bundle,auth)
        self.assertEqual(digest(target),before)

    def test_cli_batch_query_and_no_init_command(self):
        request=self.root/'request.json';request.write_text(json.dumps({'items':[identity()]}))
        out=self.root/'query.json'
        result=subprocess.run([sys.executable,'-B','-m','product_reference','query','--database',str(self.db),'--request',str(request),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr+result.stdout);self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['rows'][0]['status'],'exact_reference')
        self.assertNotEqual(subprocess.run([sys.executable,'-B','-m','product_reference','init'],capture_output=True).returncode,0)


if __name__=='__main__':unittest.main()
