"""Synthetic A-01 behavior tests; not human or independent new-batch acceptance."""
from contextlib import closing
import copy
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from native_copy.support import REPO, Rejected, bootstrap, digest, load
bootstrap()
from native_copy.service import execute, registered_copy
from native_copy.ooxml import parts, sheet_member, verify, NS
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.workbook.defined_name import DefinedName
from product_reference.b4_store import SourceBundleStore
from source_adapters.common import write_bundle
from native_copy.profiles import HEADERS16


def fixture_module():
    spec = importlib.util.spec_from_file_location('a01_p1_fixture', REPO / 'product-library-p1/tests/test_product_reference.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


F = fixture_module()


def rewrite(path, transform):
    before = path.read_bytes(); out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(before)) as z, zipfile.ZipFile(out, 'w') as d:
        for info in z.infolist():
            d.writestr(info, transform(info.filename, z.read(info.filename)))
    path.write_bytes(out.getvalue())


def make_native(path, *, code='00123', name='Japanese A', extra=False):
    w = Workbook(); s = w.active; s.title = 'Sheet1'; s.append(HEADERS16)
    s.append(['HA001', 'JP', code, None, None, None, None, None, name, 2, 100, '=J2*K2', None, None, None, None])
    s['C2'].number_format = '@'; s['E2'].font = Font(name='Arial', size=12, bold=True)
    s['E2'].border = Border(bottom=Side(style='thin', color='223344'))
    s['E2'].alignment = Alignment(wrap_text=True, horizontal='center')
    s.row_dimensions[2].height = 35; s.column_dimensions['E'].width = 42
    s['I2'].comment = Comment('Existing original comment', 'Source')
    s.freeze_panes = 'E2'; s.auto_filter.ref = 'A1:P2'
    s.merge_cells('A5:C5'); s['A5'] = 'Original footer'; s.row_dimensions[4].hidden = True
    w.defined_names.add(DefinedName('OriginalName', attr_text="'Sheet1'!$J$2"))
    weights = w.create_sheet('重さとサイズ (2)')
    weights.append(['箱番', '重さ', 'カートン個数', '合計重量（KGS)'])
    weights.append(['HA001', 2.5, 1, '=B2*C2']); weights.sheet_view.showGridLines = False
    auxiliary = w.create_sheet('原辅助'); auxiliary['A1'] = '=1+2'; auxiliary.sheet_state = 'hidden'
    w.save(path); w.close()
    def cache(n, data):
        if n == 'xl/worksheets/sheet1.xml':
            return data.replace(b'<f>J2*K2</f><v></v>', b'<f>J2*K2</f><v>200</v>')
        if n == 'xl/worksheets/sheet2.xml':
            return data.replace(b'<f>B2*C2</f><v></v>', b'<f>B2*C2</f><v>2.5</v>')
        return data
    rewrite(path, cache)


def make_raw(path, version=1):
    w = Workbook(); s = w.active; s.title = 'invoice (計算)'
    if version == 1:
        headers = {'C':'ProductCode(JANCode)','D':'DescriptionofGoods','G':'Origin','H':'UnitPrice(日本JPY)','I':'Qty','K':'Subtotal'}
        values = {'A':'HA001','C':'00123','D':'Japanese A','G':'JP','H':100,'I':2,'K':200}
    else:
        headers = {'D':'ProductCode(JANCode)','H':'DescriptionofGoods','K':'Origin','L':'UnitPrice(日本JPY)','M':'Qty','O':'Subtotal','AB':'品类','AC':'材质'}
        values = {'A':'HA001','D':'00123','H':'Japanese A','K':'JP','L':100,'M':2,'O':200}
    for col, value in headers.items():s[col+'17']=value
    for col, value in values.items():s[col+'18']=value
    t = w.create_sheet('重さとサイズ');t.append(['箱番','重さ','カートン個数','合計重量（KGS)']);t.append(['HA001',2.5,1,2.5])
    w.save(path);w.close()


class NativeCopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.source_dir = self.root/'input'; self.source_dir.mkdir()
        self.source = self.source_dir/'source.xlsx'; make_native(self.source)
        self.db = self.root/'reference.sqlite3'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
            c.execute("INSERT INTO metadata VALUES ('schema_version','3')")
        self.store = SourceBundleStore.initialize(self.db, new_database=True)
        self.seq = 0
        self.add_records([self.record()])

    def tearDown(self):
        from native_copy.support import snapshot_root
        temp_root=Path(tempfile.gettempdir()).resolve();target=self.root.resolve()
        if not target.is_relative_to(temp_root) or target==temp_root:
            raise RuntimeError('测试清理路径越界')
        if target.exists():shutil.rmtree(snapshot_root(target))
        self.tmp.cleanup()

    def record(self, rid='a', name='Candidate Chinese', **identity):
        ident = F.identity(code='00123', version=None, spec=None, name='Japanese A')
        ident.update(identity)
        r = F.record(rid, ident, internal=name, material='紙、スチール等')
        for field, value in {'specification':'A款','category':'文具','channel':'参考渠道','yd':'001YD',
                             'unit_price':'90','currency':'JPY','purchase_unit':'个',
                             'packaging_relations':[{'from_unit':'盒','to_unit':'件','factor':'8'}]}.items():
            r['fields'][field] = {'value':value,'raw_value':value,'reference_type':'historical_reference',
                'translation_status':'not_applicable','evidence':r['fields']['internal_name']['evidence']}
        return r

    def add_records(self, rows, source_id='independent'):
        incoming_dir = self.root/'incoming'; incoming_dir.mkdir(exist_ok=True)
        incoming = incoming_dir/('seed'+str(len(list(incoming_dir.glob('seed*'))))+'.json');incoming.write_text('[]')
        folder = self.root/('bundle'+str(len(list(self.root.glob('bundle*')))))
        request = {'schema_version':'product-source-request/1','source_id':source_id,'source_version':'v1',
                   'mapping_version':'TEST','authorization_reference':'TEST:fixture','files':[{'path':str(incoming)}]}
        for r in rows:r['provenance']['source_id']=source_id
        write_bundle(request,rows,folder,'order')
        self.store.import_bundle(folder,authorization_reference='TEST:fixture',backup_directory=self.root/'backups')

    def request(self, library=True):
        d = {'batch_id':'KMT20261199-new','input_file':str(self.source)}
        if library:d['library_config']={'database':str(self.db),'allowed_source_ids':['independent']}
        return d

    def run_copy(self, request=None):
        self.seq += 1; self.output = self.root/('output'+str(self.seq))
        return execute(self.output, self.request() if request is None else request)

    def result(self, request=None):
        r = self.run_copy(request)
        self.assertEqual(r['status'],'prepared_reference_copy',r)
        return r, Path(r['business_files'][0])

    def edit_source(self, edit):
        w=load_workbook(self.source);edit(w);w.save(self.source);w.close()

    def test_new_batch_uses_original_layout_and_candidate_cells(self):
        before=digest(self.source);db_before=digest(self.db);r,p=self.result()
        w=load_workbook(p);s=w['Sheet1']
        self.assertEqual(s['E2'].value,'Candidate Chinese');self.assertEqual(s['F2'].value,'A款')
        self.assertEqual(s['G2'].value,90);self.assertEqual(s['H2'].value,8)
        self.assertEqual(s['N2'].value,'紙、スチール等');self.assertEqual(s['P2'].value,'001YD')
        self.assertEqual(s['J2'].value,2);self.assertEqual(s['C2'].value,'00123')
        self.assertEqual(s['E2'].fill.fgColor.rgb,'FFFFF2CC');w.close()
        self.assertEqual(digest(self.source),before);self.assertEqual(digest(self.db),db_before)
        self.assertFalse(r['confirmed']);self.assertFalse(r['can_enter_b'])
        self.assertIsNone(r['business_exception_total'])

    def test_no_database_still_prepares_copy_and_leaves_yd_legal(self):
        r,p=self.result(self.request(False));w=load_workbook(p)
        self.assertIsNone(w['Sheet1']['P2'].value);self.assertEqual(w['Sheet1']['P2'].fill.patternType,None)
        self.assertIsNone(w['Sheet1']['H2'].value);self.assertEqual(w['Sheet1']['E2'].fill.fgColor.rgb,'FFF4CCCC');w.close()
        self.assertEqual(r['prefilled_cells'],0)

    def test_nonempty_business_values_and_zero_are_never_overwritten(self):
        def edit(w):
            for a,v in {'E2':'Current Chinese','F2':'Current spec 123','G2':0,'M2':'Current category','N2':'Current material','O2':'Current channel','P2':'CURRENT'}.items():w['Sheet1'][a]=v
        self.edit_source(edit);r,p=self.result();w=load_workbook(p)
        self.assertEqual(w['Sheet1']['E2'].value,'Current Chinese');self.assertEqual(w['Sheet1']['G2'].value,0)
        self.assertEqual(w['Sheet1']['F2'].value,'Current spec 123');self.assertEqual(w['Sheet1']['P2'].value,'CURRENT');w.close()

    def test_whitespace_is_preserved_as_existing_content(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['E2'],'value','  '))
        r,p=self.result();w=load_workbook(p);self.assertEqual(w['Sheet1']['E2'].value,'  ');w.close()

    def test_existing_formula_inside_business_column_is_not_replaced(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['E2'],'value','=I2'))
        r,p=self.result();w=load_workbook(p);self.assertEqual(w['Sheet1']['E2'].value,'=I2');w.close()

    def test_all_zip_parts_formulas_caches_weights_comments_and_layout_preserved(self):
        original=self.source.read_bytes();r,p=self.result();a,b=parts(original),parts(p.read_bytes())
        self.assertEqual(list(a),list(b))
        for n in a:
            if n not in ('xl/worksheets/sheet1.xml','xl/styles.xml'):self.assertEqual(a[n],b[n],n)
        self.assertIn(b'<f>J2*K2</f><v>200</v>',b['xl/worksheets/sheet1.xml'])
        self.assertEqual(a['xl/worksheets/sheet2.xml'],b['xl/worksheets/sheet2.xml'])
        w=load_workbook(p);s=w['Sheet1'];self.assertEqual(s.freeze_panes,'E2');self.assertEqual(s.max_column,16)
        self.assertEqual(s.row_dimensions[2].height,35);self.assertEqual(s['E2'].font.name,'Arial')
        self.assertEqual(s['E2'].font.sz,12);self.assertEqual(s['E2'].alignment.horizontal,'center')
        self.assertEqual(s['I2'].comment.text,'Existing original comment');self.assertEqual(w['原辅助'].sheet_state,'hidden');w.close()

    def test_invalid_existing_h_is_colored_without_rounding_or_qty_conversion(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['H2'],'value',1.25))
        r,p=self.result();w=load_workbook(p)
        self.assertEqual(w['Sheet1']['H2'].value,1.25);self.assertEqual(w['Sheet1']['H2'].fill.fgColor.rgb,'FFF4CCCC')
        self.assertEqual(w['Sheet1']['J2'].value,2);w.close()
        reg=registered_copy(self.output);self.assertFalse(reg['qty_unit_confirmed'])

    def test_existing_h_positive_integer_keeps_no_inferred_unit(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['H2'],'value',8))
        r,p=self.result();reg=registered_copy(self.output)
        f=next(f for f in reg['fields'] if f['field']=='pieces_per_box')
        self.assertEqual(f['pieces_per_box_observed'],8);self.assertFalse(f['confirmed']);self.assertFalse(reg['qty_unit_confirmed'])

    def test_h_formula_with_fractional_cache_is_preserved_and_marked_red(self):
        def h_formula(n,data):
            if n=='xl/worksheets/sheet1.xml':
                return data.replace(b'<c r="I2"',b'<c r="H2"><f>90/100</f><v>0.9</v></c><c r="I2"')
            return data
        rewrite(self.source,h_formula)
        r,p=self.result();w=load_workbook(p);self.assertEqual(w['Sheet1']['H2'].value,'=90/100')
        self.assertEqual(w['Sheet1']['H2'].fill.fgColor.rgb,'FFF4CCCC');w.close()
        self.assertIn(b'<f>90/100</f><v>0.9</v>',parts(p.read_bytes())['xl/worksheets/sheet1.xml'])

    def test_existing_human_fill_is_not_erased(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['E2'],'fill',PatternFill('solid',fgColor='00AAFF')))
        r,p=self.result();w=load_workbook(p);self.assertEqual(w['Sheet1']['E2'].fill.fgColor.rgb,'0000AAFF');w.close()
        self.assertGreater(r['preserved_original_fill_cells'],0)

    def test_candidate_that_begins_with_equals_is_literal_text(self):
        self.add_records([self.record('new',name='=SUM(1,2)',code_raw='00099')],source_id='literal')
        self.edit_source(lambda w:setattr(w['Sheet1']['C2'],'value','00099'))
        q=self.request();q['library_config']['allowed_source_ids']=['literal'];r,p=self.result(q)
        w=load_workbook(p);self.assertEqual(w['Sheet1']['E2'].value,'=SUM(1,2)');self.assertEqual(w['Sheet1']['E2'].data_type,'s');w.close()

    def test_conflicting_field_remains_blank_and_red(self):
        self.add_records([self.record('conflict',name='Other Chinese')])
        r,p=self.result();w=load_workbook(p);self.assertIsNone(w['Sheet1']['E2'].value)
        self.assertEqual(w['Sheet1']['E2'].fill.fgColor.rgb,'FFF4CCCC');w.close()

    def test_multiple_versions_do_not_select_one_by_code(self):
        self.add_records([self.record('version2',name='Other Chinese',version='v2')])
        r,p=self.result();w=load_workbook(p);self.assertIsNone(w['Sheet1']['E2'].value);w.close()

    def test_japanese_name_conflict_does_not_fill(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['I2'],'value','Different name'))
        r,p=self.result();w=load_workbook(p);self.assertIsNone(w['Sheet1']['E2'].value);w.close()

    def test_same_input_sha_is_excluded_even_if_source_renamed(self):
        other=self.record('heldout',name='POLLUTED');other['provenance']['file_sha256']=digest(self.source)
        self.add_records([other],source_id='same-input')
        q=self.request();q['library_config']['allowed_source_ids']=['same-input']
        r,p=self.result(q);w=load_workbook(p);self.assertIsNone(w['Sheet1']['E2'].value);w.close()

    def test_target_batch_lineage_and_answer_file_are_excluded(self):
        for name in ['KMT20261199-new.xlsx','historical-final-answer.xlsx']:
            row=self.record(name,name='POLLUTED');row['provenance']['file_name']=name
            self.add_records([row],source_id='lineage-'+str(len(name)))
        q=self.request();q['library_config']['allowed_source_ids']=['lineage-21','lineage-28']
        # Use actual manifest source IDs so the test does not depend on filename lengths.
        with closing(sqlite3.connect(self.db)) as c:
            q['library_config']['allowed_source_ids']=[json.loads(x[0])['source_id'] for x in c.execute('select manifest_json from source_ingest_bundles') if json.loads(x[0])['source_id'].startswith('lineage-')]
        r,p=self.result(q);w=load_workbook(p);self.assertIsNone(w['Sheet1']['E2'].value);w.close()

    def test_answer_named_bundle_cannot_be_whitelisted(self):
        self.add_records([self.record('answer')],source_id='final-answer')
        q=self.request();q['library_config']['allowed_source_ids']=['final-answer']
        r=self.run_copy(q);self.assertEqual(r['business_files'],[]);self.assertEqual(r['status'],'validation_incomplete')

    def test_unselected_sources_never_supply_values(self):
        q=self.request();q['library_config']['allowed_source_ids']=['not-present']
        r=self.run_copy(q);self.assertEqual(r['status'],'validation_incomplete');self.assertFalse((self.output/'delivery').exists())

    def test_raw_v1_accepts_new_batch_and_no_business_columns_are_added(self):
        make_raw(self.source,1);r,p=self.result(self.request(False))
        self.assertEqual(r['profile_id'],'kmt-raw-invoice-v1');self.assertEqual(self.source.read_bytes(),p.read_bytes())

    def test_raw_v2_uses_existing_anchored_slots(self):
        make_raw(self.source,2);r,p=self.result();w=load_workbook(p);s=w['invoice (計算)']
        self.assertEqual(s['F18'].value,'Candidate Chinese');self.assertEqual(s['G18'].value,'A款')
        self.assertEqual(s['AB18'].value,'文具');self.assertEqual(s['AC18'].value,'紙、スチール等')
        self.assertIsNone(s['F17'].value);self.assertEqual(s['M18'].value,2);w.close()

    def test_legacy_stage3_layout_reuses_reader_but_not_unknown_h_meaning(self):
        def edit(w):
            for col in ['D','E','F','G','H']:w['Sheet1'][col+'1']=None
            w['Sheet1']['P1']='yd';w['Sheet1']['H2']=1.25
        self.edit_source(edit);r,p=self.result();self.assertEqual(r['profile_id'],'kmt-stage3-native-v1')
        w=load_workbook(p);self.assertEqual(w['Sheet1']['H2'].value,1.25);self.assertEqual(w['Sheet1']['H2'].fill.patternType,None);w.close()

    def test_unknown_missing_header_is_rejected_without_guessing(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['M1'],'value',None))
        with self.assertRaises(Rejected):self.run_copy()

    def test_unknown_completed_output_layout_is_rejected(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['Q1'],'value','税率'))
        with self.assertRaises(Rejected):self.run_copy()

    def test_no_code_named_purchase_row_is_retained(self):
        self.edit_source(lambda w:setattr(w['Sheet1']['C2'],'value',None))
        r,p=self.result();self.assertEqual(r['rows'],1)
        w=load_workbook(p);self.assertIsNone(w['Sheet1']['C2'].value);self.assertIsNone(w['Sheet1']['P2'].value);w.close()

    def test_duplicate_codes_keep_two_source_rows_in_order(self):
        def edit(w):
            s=w['Sheet1']
            for col in ['B','C','I','J','K']:s[col+'3']=s[col+'2'].value
            s['A3']='HA002';s['L3']=200
        self.edit_source(edit);r,p=self.result();reg=registered_copy(self.output)
        self.assertEqual(r['rows'],2);self.assertEqual([x['source_row'] for x in reg['row_map']],[2,3])
        self.assertNotEqual(reg['row_map'][0]['row_id'],reg['row_map'][1]['row_id'])

    def test_missing_weight_sheet_rejected(self):
        self.edit_source(lambda w:w.remove(w['重さとサイズ (2)']))
        with self.assertRaises(Rejected):self.run_copy()

    def test_existing_output_cannot_be_overwritten(self):
        r,p=self.result();before=digest(p)
        with self.assertRaises(Rejected):execute(self.output,self.request())
        self.assertEqual(digest(p),before)

    def test_old_schema_database_is_not_migrated(self):
        with closing(sqlite3.connect(self.db)) as c,c:c.execute("update metadata set value='2' where key='schema_version'")
        before=digest(self.db);r=self.run_copy();self.assertEqual(r['business_files'],[]);self.assertEqual(digest(self.db),before)

    def test_database_with_activity_log_is_not_opened_as_static(self):
        Path(str(self.db)+'-wal').write_bytes(b'not-a-live-fixture')
        r=self.run_copy();self.assertEqual(r['status'],'validation_incomplete')

    def test_unknown_confirmation_answer_or_calculation_parameters_rejected(self):
        for field in ['confirm','answer_file','units_confirmation','tax_allocations']:
            q=self.request();q[field]=True
            with self.assertRaises(Rejected):self.run_copy(q)

    def test_registration_is_bound_to_copy_and_never_approved(self):
        r,p=self.result();reg=registered_copy(self.output)
        self.assertEqual(reg['export_id'],r['export_id']);self.assertEqual(reg['copy_sha256'],digest(p))
        self.assertEqual(reg['confirmed_fields'],[]);self.assertFalse(reg['can_enter_b']);self.assertFalse(reg['formal_output'])
        self.assertTrue(all(not f['confirmed'] for f in reg['fields']))

    def test_tampered_copy_and_tampered_registry_are_rejected(self):
        r,p=self.result();p.write_bytes(p.read_bytes()+b'tampered')
        with self.assertRaises(Rejected):registered_copy(self.output)
        r,p=self.result();regpath=self.output/'technical/export-registration.json'
        reg=load(regpath);reg['confirmed']=True;regpath.write_text(json.dumps(reg))
        with self.assertRaises(Rejected):registered_copy(self.output)

    def test_late_integrity_failure_publishes_no_eligible_copy(self):
        from native_copy import service
        real=service.check_hashes;calls=0
        def fail(snapshot):
            nonlocal calls
            calls+=1
            if calls==2:raise Rejected('injected late failure')
            return real(snapshot)
        with patch.object(service,'check_hashes',side_effect=fail):r=self.run_copy()
        self.assertEqual(r['business_files'],[]);self.assertEqual(r['status'],'validation_incomplete')
        self.assertFalse(list((self.output/'delivery').glob('*.xlsx')))
        with self.assertRaises(Rejected):registered_copy(self.output)

    def test_independent_verifier_detects_protected_value_and_weight_damage(self):
        r,p=self.result();original=self.source.read_bytes();changes=load(self.output/'technical/changes.json')['cells']
        copied=p.read_bytes()
        def corrupt(member,replace):
            out=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(copied)) as z,zipfile.ZipFile(out,'w') as d:
                for info in z.infolist():d.writestr(info,replace(z.read(info.filename)) if info.filename==member else z.read(info.filename))
            return out.getvalue()
        damaged=corrupt('xl/worksheets/sheet1.xml',lambda data:data.replace(b'<v>2</v>',b'<v>999</v>',1))
        with self.assertRaises(Rejected):verify(original,damaged,'Sheet1',changes)
        damaged=corrupt('xl/worksheets/sheet2.xml',lambda data:data.replace(b'2.5',b'9.5'))
        with self.assertRaises(Rejected):verify(original,damaged,'Sheet1',changes)

    def test_price_without_explicit_currency_or_unit_remains_blank(self):
        row=self.record('no-currency',code_raw='00222');row['fields'].pop('currency')
        self.add_records([row],source_id='no-currency')
        self.edit_source(lambda w:setattr(w['Sheet1']['C2'],'value','00222'))
        q=self.request();q['library_config']['allowed_source_ids']=['no-currency'];r,p=self.result(q)
        w=load_workbook(p);self.assertIsNone(w['Sheet1']['G2'].value);w.close()

    def test_box_label_never_becomes_numeric_box_relation(self):
        row=self.record('no-relation',code_raw='00223');row['fields'].pop('packaging_relations')
        row['fields']['packaging_label']=copy.deepcopy(row['fields']['internal_name'])
        row['fields']['packaging_label'].update(value='BOX 全8種',raw_value='BOX 全8種')
        self.add_records([row],source_id='no-relation')
        self.edit_source(lambda w:setattr(w['Sheet1']['C2'],'value','00223'))
        q=self.request();q['library_config']['allowed_source_ids']=['no-relation'];r,p=self.result(q)
        w=load_workbook(p);self.assertIsNone(w['Sheet1']['H2'].value);self.assertEqual(w['Sheet1']['J2'].value,2);w.close()

    def test_merged_non_anchor_business_slot_is_not_filled(self):
        self.edit_source(lambda w:w['Sheet1'].merge_cells('E2:F2'))
        r,p=self.result();w=load_workbook(p);self.assertEqual(w['Sheet1']['E2'].value,'Candidate Chinese')
        self.assertIsNone(w['Sheet1']['F2'].value);self.assertIn('E2:F2',str(w['Sheet1'].merged_cells));w.close()

    def test_namespace_prefix_on_source_sheet_remains_supported(self):
        def prefixed(n,data):
            if n!='xl/worksheets/sheet1.xml':return data
            tree=ET.fromstring(data);ET.register_namespace('a01x',NS['s'])
            return ET.tostring(tree,encoding='utf-8',xml_declaration=True)
        rewrite(self.source,prefixed);r,p=self.result()
        self.assertIn(b'<a01x:worksheet',parts(p.read_bytes())['xl/worksheets/sheet1.xml'])

    def test_source_changed_after_query_invalidates_entire_copy(self):
        from native_copy import service
        original=service.prepare_fields
        def mutate(*args):
            result=original(*args);self.source.write_bytes(self.source.read_bytes()+b'changed');return result
        with patch.object(service,'prepare_fields',side_effect=mutate):r=self.run_copy()
        self.assertEqual(r['status'],'validation_incomplete');self.assertEqual(r['business_files'],[])

    def test_same_namespace_does_not_guess_jan(self):
        row=self.record('jan',code_raw='00224',code_type='JAN')
        self.add_records([row],source_id='jan-only')
        self.edit_source(lambda w:setattr(w['Sheet1']['C2'],'value','00224'))
        q=self.request();q['library_config']['allowed_source_ids']=['jan-only'];r,p=self.result(q)
        w=load_workbook(p);self.assertIsNone(w['Sheet1']['E2'].value);w.close()

    def test_registration_rejects_source_modified_after_preparation(self):
        r,p=self.result();self.source.write_bytes(self.source.read_bytes()+b'source changed')
        with self.assertRaises(Rejected):registered_copy(self.output)

    def test_registration_rejects_tampered_reference_snapshot(self):
        r,p=self.result();f=self.output/'technical/reference-candidates.json'
        data=load(f);data['automatic_approval']=True;f.write_text(json.dumps(data))
        with self.assertRaises(Rejected):registered_copy(self.output)

    def test_verifier_checks_actual_planned_fill_color(self):
        r,p=self.result();original=self.source.read_bytes();changes=load(self.output/'technical/changes.json')['cells']
        rewrite(p,lambda n,data:data.replace(b'FFFFF2CC',b'FF00FF00') if n=='xl/styles.xml' else data)
        with self.assertRaises(Rejected):verify(original,p.read_bytes(),'Sheet1',changes)

    def test_empty_shared_string_cell_is_blank_not_an_existing_value(self):
        import re
        old=parts(self.source.read_bytes());data=old['xl/worksheets/sheet1.xml']
        data,n=re.subn(rb'<c r="E2"[^>]*>.*?</c>',b'<c r="E2" s="2" t="s"><v>0</v></c>',data)
        self.assertEqual(n,1);old['xl/worksheets/sheet1.xml']=data
        old['xl/sharedStrings.xml']=b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1"><si><t></t></si></sst>'
        old['[Content_Types].xml']=old['[Content_Types].xml'].replace(b'</Types>',b'<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        old['xl/_rels/workbook.xml.rels']=old['xl/_rels/workbook.xml.rels'].replace(b'</Relationships>',b'<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml" Id="rIdShared"/></Relationships>')
        with zipfile.ZipFile(self.source,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in old.items():z.writestr(name,data)
        r,p=self.result();w=load_workbook(p);self.assertEqual(w['Sheet1']['E2'].value,'Candidate Chinese');w.close()

    def test_deep_workspace_does_not_break_frozen_snapshot_temp_path(self):
        self.output=self.root/('x'*80)/'registered'
        r=execute(self.output,self.request())
        self.assertEqual(r['status'],'prepared_reference_copy',r)
        reg=registered_copy(self.output);self.assertFalse(reg['can_enter_b'])

    def test_supplied_business_amount_is_not_relabelled_retail(self):
        r,p=self.result()
        from arrival_core.storage import Store
        from native_copy.support import snapshot_root
        reg=registered_copy(self.output)
        batch=Store(snapshot_root(self.output/'technical/batch-store')).load(reg['batch_id'])
        self.assertEqual(batch['rows'][0]['authority']['amount_basis'],'provided_workbook_subtotal')
        self.assertEqual(batch['rows'][0]['authority']['status'],'a01_unconfirmed_source_observation')
        self.assertFalse(batch['rows'][0]['reviews']['price'])


if __name__ == '__main__':
    unittest.main()
