"""Synthetic xlsx tests of the extension, using the frozen A-01 library fixtures."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from decimal import Decimal

from native22.support import REPO, bootstrap, digest, load, Rejected
bootstrap()
from native22.prepare import prepare, registered_copy
from native22.returns import preview, read_preview
from native22 import prepare as preparation_module
from native22.pricing import calculate, price
from native_copy.ooxml import parts, sheet_member, NS
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.comments import Comment

spec = importlib.util.spec_from_file_location('native22_a01_test_fixtures', REPO/'a01-native-copy/tests/test_native_copy.py')
fx = importlib.util.module_from_spec(spec); spec.loader.exec_module(fx)


def native22(path):
    w = Workbook(); s = w.active; s.title = 'Sheet1'
    headers = {'A':'CartonNo.', 'B':'Origin', 'C':'ProductCode(JANCode)', 'I':'DescriptionofGoods',
               'J':'单个价', 'K':'倍数', 'L':'单个数', 'M':'Qty', 'N':'UnitPrice(日本JPY)',
               'O':'Subtotal', 'Q':'材质', 'R':'渠道', 'S':'YD', 'T':'备注'}
    for c, v in headers.items(): s[c+'1'] = v
    values = {'A':'HA001', 'B':'JP', 'C':'00123', 'D':'=TEXT(C2,0)', 'G':800.004, 'H':'=G2/N2',
              'I':'Japanese A', 'J':'=N2/K2', 'K':'=L2/M2', 'L':2, 'M':2, 'N':100,
              'O':'=M2*N2', 'T':'Original note', 'U':'=G2-N2*H2', 'V':'=ROUND(J2,0)'}
    for c, v in values.items(): s[c+'2'] = v
    s['C2'].number_format = '@'; s['I2'].comment = Comment('Original source', 'Fixture')
    s.column_dimensions['E'].width = 40; s.row_dimensions[2].height = 30
    s.merge_cells('A5:C5'); s['A5'] = 'Original footer'
    t = w.create_sheet('重さとサイズ (2)'); t.append(['箱番','重さ','カートン個数','合計重量（KGS)']); t.append(['HA001',2.5,1,'=B2*C2'])
    aux = w.create_sheet('原辅助'); aux['A1'] = '=1+2'; aux.sheet_state = 'hidden'
    w.save(path); w.close()
    def cache(n, data):
        if n == 'xl/worksheets/sheet1.xml':
            for f, v in [('M2*N2','200'), ('G2/N2','8.00004'), ('G2-N2*H2','0'), ('N2/K2','100'), ('L2/M2','1')]:
                data = data.replace(('<f>'+f+'</f><v></v>').encode(), ('<f>'+f+'</f><v>'+v+'</v>').encode())
        return data
    fx.rewrite(path, cache)


class Native22Tests(unittest.TestCase):
    def setUp(self):
        self.f = fx.NativeCopyTests('test_no_database_still_prepares_copy_and_leaves_yd_legal'); self.f.setUp()
        self.root = self.f.root; self.source = self.f.source_dir/'native22.xlsx'; native22(self.source)
        self.seq = 0; self.batch = 'NEW-SYNTHETIC-BATCH'

    def tearDown(self): self.f.tearDown()

    def edit_source(self, changes=None, action=None):
        w = load_workbook(self.source)
        for a, v in (changes or {}).items(): w['Sheet1'][a] = v
        if action: action(w)
        w.save(self.source); w.close()

    def request(self, basis=True, library=True):
        r = {'batch_id': self.batch, 'input_file': str(self.source)}
        if library: r['library_config'] = {'database': str(self.f.db), 'allowed_source_ids': ['independent']}
        if basis:
            r['price_basis'] = {'schema':'a-price-basis/1', 'source_sha256':digest(self.source), 'currency':'JPY',
                                'purchase_column':'G', 'comparison_column':'N', 'purchase_role':'purchase_price_reference',
                                'comparison_role':'source_business_unit_price', 'evidence_ref':'TEST:explicit dialogue role binding'}
        return r

    def prepared(self, request=None):
        self.seq += 1; self.output = self.root/('prepare'+str(self.seq))
        before = digest(self.source); db_before = digest(self.f.db)
        r = prepare(self.output, request or self.request())
        self.assertEqual(r['status'], 'prepared_reference_copy', r)
        self.assertEqual(digest(self.source), before); self.assertEqual(digest(self.f.db), db_before)
        self.r = r; self.reg = registered_copy(self.output); self.base = Path(self.reg['file'])
        self.pricing = load(self.output/'technical/pricing.json') if (self.output/'technical/pricing.json').exists() else None
        self.assertFalse(r['confirmed']); self.assertFalse(r['can_enter_b'])
        return r

    def edited(self, changes=None, action=None):
        self.seq += 1; path = self.root/('return'+str(self.seq)+'.xlsx'); w = load_workbook(self.base)
        for a, v in (changes or {}).items(): w['Sheet1'][a] = v
        if action: action(w)
        w.save(path); w.close(); return path

    def context(self, known=None):
        p = self.root/('context'+str(self.seq)+'.json')
        p.write_text(json.dumps({'schema':'a02-trusted-context/1', 'current_output':str(self.output),
                                'business_batch_id':self.batch, 'export_id':self.r['export_id'], 'a_version':self.r['a_version'],
                                'known_outputs':[str(x) for x in (known or [self.output])]}), encoding='utf-8')
        return p

    def returned(self, path=None, box=None, context=None):
        self.seq += 1; self.preview_output = self.root/('preview'+str(self.seq))
        request = {'uploaded_file':str(path or self.base), 'context_file':str(context or self.context())}
        if box is not None: request['box_corrections'] = box
        r = preview(self.preview_output, request)
        self.assertFalse(r['confirmed']); self.assertFalse(r['can_enter_b']); self.assertFalse(r['a_version_saved'])
        if r['status'] == 'preview_ready': self.detail = read_preview(self.preview_output)
        return r

    def test_22_named_mapping_fill_and_no_extra_sheets(self):
        r = self.prepared(); w = load_workbook(self.base); s = w['Sheet1']
        self.assertEqual(r['profile_id'], 'kmt-native-22-v1'); self.assertEqual(r['prefilled_cells'], 6)
        self.assertEqual(s['E2'].value, 'Candidate Chinese'); self.assertEqual(s['P2'].value, '文具')
        self.assertEqual(s['Q2'].value, '紙、スチール等'); self.assertEqual(s['S2'].value, '001YD')
        self.assertEqual(s['M2'].value, 2); self.assertEqual(s['N2'].value, 100); self.assertEqual(s['T2'].value, 'Original note')
        self.assertEqual(s['O2'].value, '=M2*N2'); self.assertEqual(s['D2'].value, '=TEXT(C2,0)')
        self.assertEqual(w.sheetnames, ['Sheet1', '重さとサイズ (2)', '原辅助']); self.assertEqual(s.max_column, 22)
        self.assertTrue(all(not f['confirmed'] and not f['material_approval'] for f in self.reg['fields'])); w.close()

    def test_normal_rounding_not_red_and_price_raw_retained(self):
        r = self.prepared(); w = load_workbook(self.base); s = w['Sheet1']
        self.assertEqual(r['pricing_counts'], {'within_100_jpy':1})
        self.assertEqual(s['G2'].value, 800.004); self.assertEqual(s['G2'].number_format, '0.00')
        self.assertEqual(s['N2'].number_format, '0.00'); self.assertNotEqual(s['H2'].fill.fgColor.rgb, 'FFF4CCCC')
        self.assertEqual(self.pricing['rows'][0]['pieces_per_box'], '8'); self.assertEqual(self.pricing['rows'][0]['difference_jpy'], '0.00')
        w.close(); w = load_workbook(self.base, data_only=True)
        self.assertEqual(w['Sheet1']['H2'].value, 8); self.assertEqual(w['Sheet1']['U2'].value, 0); w.close()

    def test_literal_box_count_preserved_even_when_ratio_differs(self):
        self.edit_source({'H2':7}); self.prepared()
        w = load_workbook(self.base); self.assertEqual(w['Sheet1']['H2'].value, 7); w.close()
        self.assertEqual(self.pricing['rows'][0]['difference_jpy'], '100.00')

    def test_over_100_overrides_old_u_fill_only(self):
        self.edit_source({'G2':200.005,'H2':1}, lambda w: setattr(w['Sheet1']['U2'], 'fill', PatternFill('solid', fgColor='FFFF00')))
        self.prepared(); self.assertEqual(self.pricing['counts'], {'exceeds_100_jpy':1})
        w = load_workbook(self.base); self.assertEqual(w['Sheet1']['U2'].fill.fgColor.rgb, 'FFF4CCCC')
        self.assertNotEqual(w['Sheet1']['H2'].fill.fgColor.rgb, 'FFF4CCCC'); w.close()

    def test_zero_inferred_never_becomes_one_or_pass(self):
        self.edit_source({'G2':0}); self.prepared()
        self.assertEqual(self.pricing['counts'], {'rounded_packaging_not_positive_integer':1})
        w = load_workbook(self.base, data_only=True); self.assertEqual(w['Sheet1']['H2'].value, 0)
        self.assertIsNone(w['Sheet1']['U2'].value); w.close()

    def test_missing_purchase_price_not_filled_from_japanese_price(self):
        self.edit_source({'G2':'#N/A'}); r = self.prepared(self.request(library=False))
        self.assertEqual(r['pricing_counts'], {'price_input_unavailable':1})
        w = load_workbook(self.base); self.assertEqual(w['Sheet1']['G2'].value, '#N/A'); w.close()
        w = load_workbook(self.base, data_only=True); self.assertIsNone(w['Sheet1']['H2'].value); self.assertIsNone(w['Sheet1']['U2'].value); w.close()

    def test_zero_comparison_price_is_unavailable_not_zero_difference(self):
        self.edit_source({'N2':0}); self.prepared(); self.assertEqual(self.pricing['counts'], {'price_input_unavailable':1})

    def test_blank_or_text_purchase_price_is_not_coerced_to_zero(self):
        for value in (None, '800.00', ''):
            self.edit_source({'G2':value}); self.prepared(self.request(library=False))
            self.assertEqual(self.pricing['counts'], {'price_input_unavailable':1})
            w=load_workbook(self.base,data_only=True);self.assertIsNone(w['Sheet1']['H2'].value);self.assertIsNone(w['Sheet1']['U2'].value);w.close()

    def test_negative_or_rounded_zero_comparison_price_is_not_used(self):
        for value in (-1,0.004):
            self.edit_source({'N2':value});self.prepared()
            self.assertEqual(self.pricing['counts'],{'price_input_unavailable':1})

    def test_positive_integer_text_box_count_is_accepted_as_observation(self):
        self.edit_source({'H2':'8'});self.prepared()
        self.assertEqual(self.pricing['counts'],{'within_100_jpy':1})

    def test_price_basis_missing_is_one_batch_group_not_thousands_red(self):
        r = self.prepared(self.request(basis=False)); self.assertEqual(r['pricing_counts'], {})
        self.assertEqual(self.pricing['groups'][0]['kind'], 'batch_price_basis_missing')
        self.assertEqual(len(self.pricing['groups']), 1); self.assertEqual(self.pricing['display_marks'], [])
        w = load_workbook(self.base); self.assertEqual(w['Sheet1']['H2'].value, '=G2/N2'); w.close()

    def test_retail_or_final_role_and_wrong_sha_refused(self):
        for key, value in [('purchase_role','retail_price'), ('comparison_role','final_declared_price'), ('source_sha256','0'*64), ('currency','CNY')]:
            req = self.request(); req['price_basis'][key] = value
            with self.assertRaises(Rejected): prepare(self.root/('bad-'+key), req)

    def test_candidate_purchase_price_never_becomes_approved_calculation(self):
        self.edit_source({'G2':None}); self.prepared()
        self.assertEqual(self.pricing['counts'], {'purchase_price_candidate_not_adopted':1})
        self.assertTrue(self.pricing['rows'][0]['hypothetical_only'])
        self.assertTrue(any(f['field']=='purchase_unit_price' and f['status']=='candidate' and not f['confirmed'] for f in self.reg['fields']))

    def test_candidate_box_fill_not_discarded_or_adopted(self):
        self.edit_source({'H2':None}); self.prepared()
        self.assertEqual(self.pricing['counts'], {'packaging_candidate_not_adopted':1})
        w = load_workbook(self.base); self.assertEqual(w['Sheet1']['H2'].value, 8); w.close()

    def test_unknown_h_formula_group_preserved_not_executed(self):
        self.edit_source({'H2':'=SUM(G2:N2)'}); self.prepared()
        self.assertEqual(self.pricing['counts'], {'unsupported_original_packaging_formula':1})
        w = load_workbook(self.base); self.assertEqual(w['Sheet1']['H2'].value, '=SUM(G2:N2)'); w.close()

    def test_unknown_u_formula_preserved(self):
        self.edit_source({'U2':'=G2-N2+5'}); self.prepared()
        self.assertEqual(self.pricing['counts'], {'unsupported_original_difference_formula':1})
        w = load_workbook(self.base); self.assertEqual(w['Sheet1']['U2'].value, '=G2-N2+5'); w.close()

    def test_blank_u_cell_gets_formula_without_new_column(self):
        self.edit_source({'U2':None}); self.prepared(); w = load_workbook(self.base)
        self.assertEqual(w['Sheet1']['U2'].data_type, 'f'); self.assertEqual(w['Sheet1'].max_column, 22); w.close()

    def test_unhandled_h_dependency_refuses_copy(self):
        self.edit_source({'J2':'=H2*100'}); self.seq += 1
        r = prepare(self.root/'dependency-failure', self.request())
        self.assertEqual(r['status'], 'validation_incomplete', r); self.assertEqual(r['business_files'], [])
        self.assertIn('下游依赖', r['reason'])

    def test_unhandled_u_dependency_cannot_leave_a_stale_original_cache(self):
        self.edit_source({'V2':'=ROUND(U2,0)'})
        r=prepare(self.root/'u-dependency-failure',self.request())
        self.assertEqual(r['status'],'validation_incomplete',r)
        self.assertEqual(r['business_files'],[]);self.assertIn('下游依赖',r['reason'])

    def test_header_swap_duplicate_or_unknown_is_rejected(self):
        for case in ('swap', 'duplicate', 'extra'):
            native22(self.source)
            def edit(w):
                s=w['Sheet1']
                if case=='swap': s['N1'],s['Q1']='材质','UnitPrice(日本JPY)'
                elif case=='duplicate': s['E1']='Qty'
                else: s['W1']='unknown'
            self.edit_source(action=edit)
            with self.assertRaises(Rejected): prepare(self.root/('bad-'+case), self.request())

    def test_legal_return_and_untouched_yellow_not_confirmed(self):
        self.prepared(); r = self.returned(self.edited({'E2':'人工中文名','Q2':'纸参考','S2':None}))
        self.assertEqual(r['status'],'preview_ready',r); self.assertEqual(r['modified_cells'],3)
        self.assertGreater(r['unchanged_candidate_cells'],0); self.assertFalse(self.detail['confirmed'])
        self.assertEqual(self.detail['approval_events'],[]); self.assertEqual(r['pricing_counts'],{'within_100_jpy':1})

    def test_original_quantities_prices_amounts_and_helper_formulas_protected(self):
        self.prepared()
        for address in ('M2','N2','O2','L2','J2','K2','H2','U2','V2','D2','T2'):
            r = self.returned(self.edited({address:999}))
            self.assertEqual(r['status'],'rejected', (address,r)); self.assertIn(address,json.dumps(r))

    def test_weight_protected(self):
        self.prepared(); r=self.returned(self.edited(action=lambda w: setattr(w['重さとサイズ (2)']['B2'],'value',999)))
        self.assertEqual(r['status'],'rejected',r); self.assertIn('B2',json.dumps(r))

    def test_manual_purchase_price_is_fresh_pending_proposal(self):
        self.prepared(); r=self.returned(self.edited({'G2':400}))
        self.assertEqual(r['status'],'preview_ready',r); self.assertEqual(r['needs_further_confirmation_cells'],1)
        self.assertEqual(r['pricing_counts'],{'manual_purchase_price_pending_source':1})
        self.assertEqual(self.detail['pricing']['rows'][0]['g_calculation_price'],'400.00')
        self.assertFalse(self.detail['returned_formula_cache_adopted'])

    def test_code_or_spec_change_invalidates_price_association(self):
        self.prepared()
        for address in ('C2','F2'):
            r=self.returned(self.edited({address:'new identity'}))
            self.assertEqual(r['pricing_counts'],{'identity_context_changed_pending_basis':1})
            self.assertEqual(r['needs_further_confirmation_cells'],1)
            self.assertEqual(self.detail['edits'][0]['row_id'],self.reg['row_map'][0]['row_id'])

    def test_h_literal_edit_pending_and_recomputed(self):
        self.edit_source({'H2':8}); self.prepared(); r=self.returned(self.edited({'H2':4}))
        self.assertEqual(r['pricing_counts'],{'manual_packaging_pending_confirmation':1})
        self.assertEqual(self.detail['pricing']['rows'][0]['difference_jpy'],'400.00')

    def test_chat_box_correction_keeps_excel_formula(self):
        self.prepared(); before=digest(self.base)
        r=self.returned(box=[{'sheet':'Sheet1','cell':'H2','pieces_per_box':4,'message_ref':'TEST:dialogue only'}])
        self.assertEqual(r['status'],'preview_ready',r); self.assertEqual(r['modified_cells'],0)
        self.assertEqual(self.detail['pricing']['rows'][0]['difference_jpy'],'400.00'); self.assertEqual(digest(self.base),before)

    def test_upload_cache_change_cannot_change_price_check(self):
        self.edit_source({'G2':'=1+799'})
        fx.rewrite(self.source, lambda n,d: d.replace(b'<f>1+799</f><v></v>',b'<f>1+799</f><v>800</v>') if n.endswith('sheet1.xml') else d)
        self.prepared(); p=self.root/'cache-tampered.xlsx';p.write_bytes(self.base.read_bytes())
        fx.rewrite(p,lambda n,d: d.replace(b'<f>1+799</f><v>800</v>',b'<f>1+799</f><v>1</v>') if n.endswith('sheet1.xml') else d)
        r=self.returned(p); self.assertEqual(r['status'],'preview_ready',r)
        self.assertEqual(r['pricing_counts'],{'within_100_jpy':1}); self.assertEqual(self.detail['pricing']['rows'][0]['g_calculation_price'],'800.00')

    def test_old_version_exact_and_modified_ambiguous_rejected(self):
        self.prepared(); old=self.output; oldfile=self.base; modified=self.edited({'E2':'旧版修改'})
        self.prepared(self.request(library=False)); ctx=self.context([old,self.output])
        for p in (oldfile,modified):
            r=self.returned(p,context=ctx);self.assertEqual(r['status'],'rejected',r)

    def test_pricing_snapshot_tamper_rejected(self):
        self.prepared(); p=self.output/'technical/pricing.json';v=load(p);v['confirmed']=True;p.write_text(json.dumps(v))
        with self.assertRaises(Rejected): registered_copy(self.output)

    def test_preview_snapshot_tamper_rejected(self):
        self.prepared();self.returned();p=self.preview_output/'technical/pricing-preview.json';v=load(p);v['confirmed']=True;p.write_text(json.dumps(v))
        with self.assertRaises(Rejected):read_preview(self.preview_output)

    def test_context_changes_during_extended_recheck_rejects_whole_preview(self):
        self.prepared();ctx=self.context()
        import native22.returns as module
        original=module.analyze
        def changed(*args,**kwargs):
            ctx.write_text('{}');return original(*args,**kwargs)
        with patch.object(module,'analyze',side_effect=changed):r=self.returned(context=ctx)
        self.assertEqual(r['status'],'rejected',r);self.assertIsNone(r['modified_cells'])
        with self.assertRaises(Rejected):read_preview(self.preview_output)

    def test_late_prepare_failure_does_not_publish_eligible_excel(self):
        import native22.prepare as module
        actual=module.save
        def failed(path,value):
            if Path(path).name=='result.json' and value.get('status')=='prepared_reference_copy':raise OSError('TEST late publication')
            return actual(path,value)
        out=self.root/'late-preparation'
        with patch.object(module,'save',side_effect=failed):r=prepare(out,self.request())
        self.assertEqual(r['status'],'validation_incomplete',r);self.assertEqual(r['business_files'],[])
        self.assertTrue((out/'technical/rejected-copy.xlsx').exists())

    def test_late_preview_failure_quarantines_extended_preview(self):
        self.prepared()
        import native22.returns as module
        actual=module.save
        def failed(path,value):
            if Path(path).name=='result.json' and value.get('schema')=='a22-return-result/1' and value.get('status')=='preview_ready':raise OSError('TEST late preview')
            return actual(path,value)
        with patch.object(module,'save',side_effect=failed):r=self.returned()
        self.assertEqual(r['status'],'rejected',r);self.assertTrue((self.preview_output/'technical/ineligible-preview.json').exists())
        with self.assertRaises(Rejected):read_preview(self.preview_output)

    def test_return_does_not_call_business_save(self):
        self.prepared()
        from arrival_core.storage import Store
        with patch.object(Store,'save',side_effect=AssertionError('forbidden business save')):
            r=self.returned(self.edited({'E2':'仍为提案'}))
        self.assertEqual(r['status'],'preview_ready',r)

    def test_windows_long_archive_path_uses_existing_extended_path_helper(self):
        self.prepared();ctx=self.context()
        out=self.root/('a'*55)/('b'*45)/'preview'
        r=preview(out,{'context_file':str(ctx),'uploaded_file':str(self.base)})
        self.assertEqual(r['status'],'preview_ready',r)
        self.assertEqual(read_preview(out)['pricing_counts'],{'within_100_jpy':1})

    def test_legacy_16_preparation_and_return_delegate_unchanged(self):
        req=self.f.request();r=self.prepared(req)
        self.assertEqual(r['profile_id'],'kmt-native-16-v1');self.assertIsNone(self.pricing)
        self.batch=req['batch_id'];r=self.returned(self.edited({'E2':'旧格式仍支持'}))
        self.assertEqual(r['status'],'preview_ready',r);self.assertEqual(r['modified_cells'],1)

    def test_16_explicit_basis_uses_k_not_n_and_adds_no_u(self):
        req=self.f.request();req['price_basis']=self.request()['price_basis'];req['price_basis'].update(source_sha256=digest(self.f.source),comparison_column='K')
        self.prepared(req);self.assertEqual(self.reg['price_columns']['comparison'],'K')
        w=load_workbook(self.base);self.assertLess(w['Sheet1'].max_column,21);w.close()

    def test_raw_v2_and_stage3_delegate_without_new_price_mapping(self):
        for version in (1,2):
            p=self.f.source_dir/('raw'+str(version)+'.xlsx');fx.make_raw(p,version)
            r=self.prepared({'batch_id':self.batch,'input_file':str(p)})
            self.assertEqual(r['profile_id'],'kmt-raw-invoice-v'+str(version))

    def test_rounding_and_threshold_boundaries(self):
        self.assertEqual(price(Decimal('1.005')),Decimal('1.01'));self.assertEqual(price(Decimal('-1.005')),Decimal('-1.01'))
        for g,n,h,expected in [('200','100','1','within_100_jpy'),('200.004','100','1','within_100_jpy'),
                               ('200.005','100','1','exceeds_100_jpy'),('0','100','1','within_100_jpy'),
                               ('0','100.01','1','exceeds_100_jpy')]:
            self.assertEqual(calculate(Decimal(g),Decimal(n),Decimal(h),False)[2],expected)
        self.assertEqual(calculate(Decimal('150'),Decimal(100),None,True)[0],Decimal(2))
        self.assertEqual(calculate(Decimal('40'),Decimal(100),None,True)[2],'rounded_packaging_not_positive_integer')


if __name__=='__main__':unittest.main()
