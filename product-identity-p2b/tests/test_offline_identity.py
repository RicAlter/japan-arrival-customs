"""Isolated fixtures only. No private databases, live sites or declaration engine."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from offline_identity.common import Rejected,digest,key,clone,canonical
from offline_identity.analyze import analyze,link_reason,nonconflicting,specification_usable
from offline_identity.maintenance import register_plan,apply,confirmed_events
from offline_identity.review import model,preview
from offline_identity.lookup import batch_query

ROOT=Path(__file__).resolve().parents[1]
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def fact(code='001',ja='商品A',spec='赤',version=None,**extra):
    vals={'code_raw':code,'code_type':'source_identifier','japanese_name':ja,'specification':spec,'version':version,**extra}
    return {'fact_id':key(vals),'values':vals,'evidence':{f:{'cell':'C2','raw':v} for f,v in vals.items()},
            'source':{'path':'fixture.xlsx','sha256':'fixture','sheet':'資料','row':2,'role':'orders','batch_id':'OLD'},
            'review_status':'reference_only','approval':False}


def p1row(code='001',ja='商品A',rid='2'):
    return {'row_id':rid,'query':{'code_raw':code,'code_type':'source_identifier','japanese_name':ja,'version':None,'specification':None},
            'status':'incomplete_identity','candidates':[],'rejected_candidates':[],'material_reference_available':False}


def make_db(path):
    with closing(sqlite3.connect(path)) as c,c:
        c.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            INSERT INTO metadata VALUES ('schema_version','3'),('source_bundle_schema_version','1');
            CREATE TABLE source_ingest_observations(observation_sha256 TEXT,identity_json TEXT,fields_json TEXT,record_json TEXT,status TEXT);
            CREATE TABLE source_ingest_files(bundle_sha256 TEXT,relative_path TEXT,content BLOB,sha256 TEXT);
            CREATE TABLE source_ingest_bundle_records(bundle_sha256 TEXT,observation_sha256 TEXT);
            CREATE TABLE source_ingest_bundles(sha256 TEXT,manifest_json TEXT,record_count INTEGER);
            CREATE TABLE source_ingest_corrections(identity_key TEXT,field_name TEXT,value_json TEXT,reference TEXT);
        ''')


def tamper_book(source,target,*,sheet='sheet1.xml',cell='K6',value='修改',formula=False,remove_row=False,reverse=False):
    # Adversarial ZIP/XML fault injection, not spreadsheet authoring.
    with zipfile.ZipFile(source) as src,zipfile.ZipFile(target,'w') as dst:
        for name in src.namelist():
            data=src.read(name)
            if name=='xl/worksheets/'+sheet:
                tree=ET.fromstring(data);sd=tree.find('{'+NS+'}sheetData')
                if remove_row:
                    sd.remove(next(r for r in sd if r.attrib['r']=='6'))
                elif reverse:
                    body=[r for r in sd if int(r.attrib['r'])>=6]
                    for r in body:sd.remove(r)
                    for i,r in enumerate(reversed(body),6):
                        r.attrib['r']=str(i)
                        for c in r:c.attrib['r']=''.join(ch for ch in c.attrib['r'] if ch.isalpha())+str(i)
                        sd.append(r)
                else:
                    row=next(r for r in sd if r.attrib['r']==''.join(ch for ch in cell if ch.isdigit()))
                    old=next((c for c in row if c.attrib['r']==cell),None)
                    if old is not None:row.remove(old)
                    c=ET.SubElement(row,'{'+NS+'}c',{'r':cell,'t':'inlineStr' if not formula else 'n'})
                    if formula:ET.SubElement(c,'{'+NS+'}f').text=value
                    else:ET.SubElement(ET.SubElement(c,'{'+NS+'}is'),'{'+NS+'}t').text=value
                    ordered=sorted(list(row),key=lambda c:(len(''.join(ch for ch in c.attrib['r'] if ch.isalpha())),''.join(ch for ch in c.attrib['r'] if ch.isalpha())))
                    row[:]=ordered
                data=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
            dst.writestr(name,data)


class MatchingTests(unittest.TestCase):
    def test_code_alone_not_linked(self):
        self.assertIsNone(link_reason(p1row()['query'],{},fact(ja=None)))

    def test_code_and_japanese_linked(self):
        self.assertEqual(link_reason(p1row()['query'],{},fact()),'code_and_japanese_name')

    def test_namespace_conflict(self):
        f=fact();f['values']['code_type']='JAN';self.assertIsNone(link_reason(p1row()['query'],{},f))

    def test_japanese_mismatch_not_material_association(self):
        f=fact(ja='別商品',material_original='ABS');q=p1row()['query']
        self.assertIsNone(link_reason(q,{'yd':'X'},f));self.assertFalse(nonconflicting(q,f))

    def test_yd_zero_not_identity_anchor(self):
        self.assertIsNone(link_reason(p1row()['query'],{'yd':'0'},fact(ja=None,yd='0')))

    def test_spec_digits_not_stripped(self):
        self.assertTrue(specification_usable('第2弾 12種'));self.assertFalse(specification_usable('预计2026年到货'))

    def test_unique_spec_not_version_invented(self):
        result=analyze({'rows':[p1row()]},[fact()],{},target_batch_id='NEW')
        self.assertEqual(result['rows'][0]['identity_after']['specification'],'赤')
        self.assertIsNone(result['rows'][0]['identity_after']['version']);self.assertEqual(result['metrics']['after_complete_identity'],0)

    def test_same_batch_not_cross_batch_coverage(self):
        f=fact();f['source']['batch_id']='NEW'
        r=analyze({'rows':[p1row()]},[f],{},target_batch_id='NEW')['metrics']
        self.assertEqual(r['all_scope_basic_reference_rows'],1);self.assertEqual(r['cross_batch_basic_reference_rows'],0)

    def test_conflicting_specs_retained(self):
        r=analyze({'rows':[p1row()]},[fact(),fact(spec='青')],{},target_batch_id='NEW')['rows'][0]
        self.assertIn('specification',r['field_conflicts']);self.assertIsNone(r['identity_after']['specification'])

    def test_duplicate_work_group_keeps_original_rows(self):
        r=analyze({'rows':[p1row(rid='2'),p1row(rid='3')]},[fact()],{},target_batch_id='NEW')
        self.assertEqual(len(r['cases']),1);self.assertEqual(r['cases'][0]['row_ids'],['2','3'])

    def test_distinct_context_not_grouped(self):
        r=analyze({'rows':[p1row(rid='2'),p1row(rid='3')]},[fact()],{'2':{'yd':'A'},'3':{'yd':'B'}},target_batch_id='NEW')
        self.assertEqual(len(r['cases']),2)

    def test_no_code_stays_no_code(self):
        r=analyze({'rows':[p1row(code=None)]},[],{},target_batch_id='NEW')
        self.assertIsNone(r['rows'][0]['identity_after']['code_raw']);self.assertEqual(r['metrics']['before_causes']['no_code'],1)


class ReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.original=cls.root/'original.sqlite3';make_db(cls.original);cls.original_hash=digest(cls.original)
        cls.plan=analyze({'rows':[p1row(),p1row(code='002',ja='商品B',rid='3')]},[fact(),fact(code='002',ja='商品B')],{},target_batch_id='NEW')
        cls.plan['source_reports']=[];cls.plan['plan_id']=key(cls.plan)
        cls.pid=cls.plan['plan_id'];cls.model=cls.root/'model.json';cls.model.write_text(canonical(model(cls.plan)),encoding='utf-8')
        cls.base=cls.root/'base.sqlite3';clone(cls.original,cls.base);register_plan(cls.base,cls.plan,'TEST:isolated')
        node=os.environ.get('P2B_NODE') or shutil.which('node')
        if not node:raise RuntimeError('Set P2B_NODE to bundled Node')
        edits=[{'sheet':'人工补充','cell':'F6','value':'S00001'}, {'sheet':'人工补充','cell':'H6','value':'初版'},
               {'sheet':'人工补充','cell':'K6','value':'合成隔离测试：明确版本及来源'}, {'sheet':'人工补充','cell':'L6','value':'确认'}]
        for name,payload in [('blank',[]),('filled',edits),('unconfirmed',edits[:-1])]:
            ep=cls.root/(name+'.json');ep.write_text(canonical(payload),encoding='utf-8')
            subprocess.run([node,str(ROOT/'build_review.mjs'),'--model',str(cls.model),'--output',str(cls.root/(name+'.xlsx')),
                            '--edits',str(ep),'--previews',str(cls.root/(name+'-previews'))],check=True,stdout=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.task=Path(tempfile.mkdtemp(dir=self.root));self.db=self.task/'working.sqlite3';clone(self.base,self.db)

    def p(self,file='filled.xlsx'):return preview(self.db,self.pid,self.root/file)
    def apply(self,p):return apply(self.db,p,confirmation={'kind':'explicit_basic_product_maintenance_confirmation','preview_hash':p['preview_hash'],'operator_reference':'TEST:maintainer'})
    def mutated(self,**kwargs):
        target=self.task/'tampered.xlsx';tamper_book(self.root/'filled.xlsx',target,**kwargs);return target

    def test_blank_returns_zero_edits_no_write(self):
        h=digest(self.db);p=self.p('blank.xlsx');self.assertEqual(p['edits'],[])
        with self.assertRaises(Rejected):self.apply(p)
        self.assertEqual(h,digest(self.db))

    def test_filled_without_confirmation_no_write(self):
        p=self.p('unconfirmed.xlsx');self.assertEqual(p['edits'],[]);self.assertEqual(len(p['filled_not_confirmed']),1)

    def test_positive_write_reference_only_and_original_intact(self):
        p=self.p();self.assertEqual(p['edits'][0]['values']['code_raw'],'001')
        self.assertEqual(self.apply(p)['events'],1);events=confirmed_events(self.db,self.pid)
        self.assertEqual(events[0]['values']['version'],'初版');self.assertFalse(events[0]['material_approval'])
        self.assertEqual(digest(self.original),self.original_hash)

    def test_return_is_reusable_in_new_batch_without_declaration_approval(self):
        self.apply(self.p());r=batch_query(self.db,[{'row_id':'new-1','query':p1row()['query']}],batch_id='FUTURE')
        self.assertEqual(r['maintenance_events'],1);self.assertEqual(r['metrics']['after_complete_identity'],1)
        self.assertFalse(r['material_approval']);self.assertFalse(r['formal_output'])

    def test_idempotent_repeat(self):
        p=self.p();self.apply(p);self.assertEqual(self.apply(p)['status'],'unchanged_duplicate')
        self.assertEqual(len(confirmed_events(self.db,self.pid)),1)

    def test_maintenance_identity_not_excel_self_report(self):
        p=self.p()
        with self.assertRaises(Rejected):apply(self.db,p,confirmation={'kind':'excel_confirmed','preview_hash':p['preview_hash'],'operator_reference':'Excel'})

    def test_stale_database_rejects(self):
        p=self.p()
        with closing(sqlite3.connect(self.db)) as c,c:c.execute("INSERT INTO metadata VALUES ('changed','1')")
        with self.assertRaises(Rejected):self.apply(p)

    def test_preview_json_tamper_rejects_even_rehashed(self):
        p=self.p();p['edits'][0]['values']['version']='伪造';p.pop('preview_hash');p['preview_hash']=key(p)
        with self.assertRaises(Rejected):self.apply(p)

    def test_source_sheet_tamper_rejects(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(sheet='sheet2.xml',cell='E6'))

    def test_original_code_tamper_rejects(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(cell='B6',value='999'))

    def test_unknown_source_rejects(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(cell='F6',value='S99999'))

    def test_wrong_product_source_rejects(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(cell='F6',value='S00002'))

    def test_formula_input_rejects(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(cell='H6',value='1+1',formula=True))

    def test_missing_basis_rejects(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(cell='K6',value=''))

    def test_unknown_placeholder_not_confirmed_version(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(cell='H6',value='待确认'))

    def test_partial_confirmation_leaves_version_missing(self):
        p=preview(self.db,self.pid,self.mutated(cell='H6',value=''))
        self.assertIsNone(p['edits'][0]['values']['version']);self.assertIn('version',p['edits'][0]['missing_after'])
        self.apply(p);q=batch_query(self.db,[{'row_id':'later','query':p1row()['query']}],batch_id='LATER')
        self.assertEqual(q['metrics']['after_complete_identity'],0)

    def test_query_same_code_different_name_not_complete(self):
        self.apply(self.p());q=p1row(ja='別の商品')['query']
        r=batch_query(self.db,[{'row_id':'later','query':q}],batch_id='LATER')
        self.assertEqual(r['metrics']['after_complete_identity'],0);self.assertFalse(r['rows'][0]['linked_sources'])

    def test_query_duplicate_row_id_rejected(self):
        item={'row_id':'same','query':p1row()['query']}
        with self.assertRaises(Rejected):batch_query(self.db,[item,item],batch_id='LATER')

    def test_deleted_case_rejects(self):
        with self.assertRaises(Rejected):preview(self.db,self.pid,self.mutated(remove_row=True))

    def test_row_reorder_uses_stable_id(self):
        p=preview(self.db,self.pid,self.mutated(reverse=True));self.assertEqual(len(p['edits']),1)

    def test_original_database_without_marker_rejects(self):
        with self.assertRaises(Rejected):register_plan(self.original,self.plan,'TEST')

    def test_plan_hash_tamper_rejects(self):
        p=copy.deepcopy(self.plan);p['target_batch_id']='fake'
        with self.assertRaises(Rejected):register_plan(self.db,p,'TEST')

    def test_no_overwrite_clone(self):
        with self.assertRaises(Rejected):clone(self.original,self.db)

    def test_material_remains_reference_after_write(self):
        target=self.mutated(cell='J6',value='ABS（合成参考）');p=preview(self.db,self.pid,target);self.apply(p)
        e=confirmed_events(self.db,self.pid)[0];self.assertEqual(e['material_review_status'],'reference_only');self.assertFalse(e['approval'])


if __name__=='__main__':unittest.main()
