"""Real xlsx round trips using synthetic A-01 registrations. No human approval."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

from native_return.support import REPO, bootstrap, digest, key, load, Rejected
bootstrap()
from native_return import service
from native_return.compare import read, compare, passive_links
from openpyxl import load_workbook

spec = importlib.util.spec_from_file_location('a02_a01_fixtures', REPO / 'a01-native-copy/tests/test_native_copy.py')
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.NativeCopyTests('test_no_database_still_prepares_copy_and_leaves_yd_legal')
        self.f.setUp(); self.root = self.f.root
        self.seq = 0
        self.r, self.base = self.f.result()
        self.current = self.f.output
        self.context = self.root / 'context.json'
        self.write_context([self.current])

    def tearDown(self):
        self.f.tearDown()

    def write_context(self, known):
        c = {'schema': 'a02-trusted-context/1', 'current_output': str(self.current),
             'business_batch_id': self.r['business_batch_id'] if 'business_batch_id' in self.r else 'KMT20261199-new',
             'export_id': self.r['export_id'], 'a_version': self.r['a_version'],
             'known_outputs': [str(p) for p in known]}
        self.context.write_text(json.dumps(c), encoding='utf-8')

    def edited(self, changes=None, action=None):
        self.seq += 1; path = self.root / ('edited'+str(self.seq)+'.xlsx')
        w = load_workbook(self.base)
        for address, value in (changes or {}).items():
            w['Sheet1'][address] = value
        if action: action(w)
        w.save(path); w.close()
        return path

    def preview(self, path=None, corrections=None):
        self.seq += 1; self.out = self.root / ('preview'+str(self.seq))
        req = {'uploaded_file': str(path or self.base), 'context_file': str(self.context)}
        if corrections is not None: req['box_corrections'] = corrections
        r = service.preview(self.out, req)
        self.assertFalse(r['confirmed']); self.assertFalse(r['can_enter_b']); self.assertFalse(r['a_version_saved'])
        if r['status'] == 'preview_ready':
            self.details = service.read_preview(self.out)
        return r

    def rejected(self, path, text=None):
        r = self.preview(path)
        self.assertEqual(r['status'], 'rejected', r)
        self.assertIsNone(r['modified_cells']); self.assertFalse((self.out/'technical/preview.json').exists())
        if text: self.assertIn(text, json.dumps(r, ensure_ascii=False))
        with self.assertRaises(Rejected): service.read_preview(self.out)
        return r

    def test_unchanged_yellow_not_approved(self):
        r = self.preview(); self.assertEqual(r['status'], 'preview_ready', r)
        self.assertEqual(r['modified_cells'], 0); self.assertGreater(r['unchanged_candidate_cells'], 0)
        self.assertEqual(self.details['approval_events'], [])
        self.assertTrue(all(not f['confirmed'] for f in self.details['unchanged_candidates']))

    def test_legal_edits_and_optional_yd(self):
        r = self.preview(self.edited({'E2': '人工名称', 'F2': 'vol.3 123', 'M2': '卡片', 'N2': '纸参考', 'O2': '采购渠道', 'P2': None}))
        self.assertEqual(r['status'], 'preview_ready', r); self.assertEqual(r['modified_cells'], 6)
        self.assertEqual(r['needs_further_confirmation_cells'], 0)
        self.assertEqual(self.details['edits'][1]['row_id'], self.details['edits'][0]['row_id'])
        self.assertTrue(all(e['manual_change'] and not e['confirmed'] for e in self.details['edits']))
        self.assertTrue(all(not e['material_approval'] for e in self.details['edits']))

    def test_clear_required_three_cells(self):
        r = self.preview(self.edited({'E2': None, 'M2': None, 'N2': None}))
        self.assertEqual(r['modified_cells'], 3); self.assertEqual(r['needs_further_confirmation_cells'], 3)

    def test_protected_quantity(self): self.rejected(self.edited({'J2': 3}), 'Sheet1!J2')
    def test_protected_price(self): self.rejected(self.edited({'K2': 101}), 'Sheet1!K2')
    def test_protected_amount_formula(self): self.rejected(self.edited({'L2': 200}), 'Sheet1!L2')
    def test_protected_carton(self): self.rejected(self.edited({'A2': 'HA002'}), 'Sheet1!A2')
    def test_protected_jc(self): self.rejected(self.edited({'D2': 'JC'}), 'Sheet1!D2')
    def test_protected_origin(self): self.rejected(self.edited({'B2': 'CN'}), 'Sheet1!B2')
    def test_protected_japanese_name(self): self.rejected(self.edited({'I2': 'Japanese B'}), 'Sheet1!I2')
    def test_protected_header(self): self.rejected(self.edited({'E1': 'name'}), 'Sheet1!E1')
    def test_protected_weight(self): self.rejected(self.edited(action=lambda w: setattr(w['重さとサイズ (2)']['B2'], 'value', 4)), '重さとサイズ (2)!B2')
    def test_protected_auxiliary(self): self.rejected(self.edited(action=lambda w: setattr(w['原辅助']['A1'], 'value', 3)), '原辅助!A1')
    def test_added_formula_in_editable_cell(self): self.rejected(self.edited({'E2': '=1+2'}), 'Sheet1!E2')
    def test_appended_row(self): self.rejected(self.edited({'E3': 'extra'}), 'Sheet1!E3')
    def test_inserted_row(self): self.rejected(self.edited(action=lambda w: w['Sheet1'].insert_rows(2)))
    def test_deleted_row(self): self.rejected(self.edited(action=lambda w: w['Sheet1'].delete_rows(2)))
    def test_added_sheet(self): self.rejected(self.edited(action=lambda w: w.create_sheet('审核页')), '工作表')
    def test_changed_merge(self): self.rejected(self.edited(action=lambda w: w['Sheet1'].unmerge_cells('A5:C5')), '合并')
    def test_changed_comment(self): self.rejected(self.edited(action=lambda w: setattr(w['Sheet1']['I2'].comment, 'text', 'change')), '批注')
    def test_changed_named_range(self): self.rejected(self.edited(action=lambda w: setattr(w.defined_names['OriginalName'], 'attr_text', "'Sheet1'!$J$3")), '命名区域')

    def test_style_change_is_not_confirmation(self):
        from openpyxl.styles import PatternFill
        def action(w):
            w['Sheet1']['E2'].fill = PatternFill('solid', fgColor='FFFFFF')
            w['Sheet1'].column_dimensions['E'].width = 50
        r = self.preview(self.edited(action=action)); self.assertEqual(r['modified_cells'], 0)
        self.assertGreater(r['unchanged_candidate_cells'], 0)

    def test_ordinary_save_cache_loss_not_adopted(self):
        r = self.preview(self.edited({'E2': '人工名称'}))
        self.assertEqual(r['status'], 'preview_ready', r)
        self.assertGreater(r['formula_cache_difference_count'], 0)
        self.assertFalse(self.details['returned_formula_cache_adopted'])

    def test_purchase_price_only_proposal_needs_basis(self):
        r = self.preview(self.edited({'G2': 80}))
        self.assertEqual(r['modified_cells'], 1); self.assertEqual(r['needs_further_confirmation_cells'], 1)

    def test_h_literal_positive_integer(self):
        r = self.preview(self.edited({'H2': '12.0'}))
        self.assertEqual(r['modified_cells'], 1); self.assertEqual(r['needs_further_confirmation_cells'], 0)
        self.assertFalse(self.details['packaging_audit']['qty_unit_inferred'])

    def test_h_invalid_no_implicit_one(self):
        for value in (None, 0, -1, 1.5, 'BOX', True):
            r = self.preview(self.edited({'H2': value}))
            self.assertEqual(r['needs_further_confirmation_cells'], 1, r)

    def test_code_change_preserves_original_id(self):
        r = self.preview(self.edited({'C2': '000123'}))
        self.assertEqual(r['needs_further_confirmation_cells'], 1)
        e = self.details['edits'][0]; self.assertEqual(e['before']['value'], '00123')
        self.assertEqual(e['after']['value'], '000123')

    def test_missing_current_batch_context(self):
        c = load(self.context); c['business_batch_id'] = 'WRONG'; self.context.write_text(json.dumps(c))
        self.rejected(self.base, '当前批次')

    def test_exact_old_export_rejected(self):
        old, oldbase = self.r, self.base; olddir = self.current
        self.r, self.base = self.f.result(self.f.request(False)); self.current = self.f.output
        self.write_context([olddir, self.current])
        self.rejected(oldbase, '旧版本')

    def test_modified_old_with_identical_readonly_skeleton_ambiguous(self):
        olddir = self.current; edited = self.edited({'E2': '旧版人工改字'})
        self.r, self.base = self.f.result(self.f.request(False)); self.current = self.f.output
        self.write_context([olddir, self.current])
        self.rejected(edited, '多个批次/版本')

    def test_other_batch_rejected(self):
        olddir = self.current
        source = self.f.source_dir / 'different.xlsx'; fixtures.make_native(source, code='00999', name='Other')
        self.r, self.base = self.f.result({'batch_id': 'NEW-BATCH', 'input_file': str(source)})
        self.current = self.f.output
        c = {'schema': 'a02-trusted-context/1', 'current_output': str(self.current), 'business_batch_id': 'NEW-BATCH',
             'export_id': self.r['export_id'], 'a_version': self.r['a_version'], 'known_outputs': [str(olddir), str(self.current)]}
        self.context.write_text(json.dumps(c))
        oldbase = Path(load(olddir/'result.json')['business_files'][0]); self.rejected(oldbase, '其他批次')

    def test_h_formula_direct_edit_rejected_and_chat_safe(self):
        self.f.edit_source(lambda w: setattr(w['Sheet1']['H2'], 'value', '=G2/K2'))
        self.r, self.base = self.f.result(); self.current = self.f.output; self.write_context([self.current])
        self.rejected(self.edited({'H2': 6}), 'H盒规更正请在对话说明')
        proposal = [{'sheet': 'Sheet1', 'cell': 'H2', 'pieces_per_box': 6, 'message_ref': 'TEST:chat:每盒6件'}]
        before = digest(self.base); r = self.preview(self.base, proposal)
        self.assertEqual(r['modified_cells'], 0); self.assertEqual(r['box_proposal_count'], 1)
        self.assertEqual(digest(self.base), before)
        self.assertEqual(self.details['packaging_audit']['groups'][0]['kind'], 'legacy_price_ratio_formula')
        self.assertFalse(self.details['box_proposals'][0]['workbook_written'])

    def test_reject_approval_parameters(self):
        with self.assertRaises(Rejected):
            service.preview(self.root/'bad', {'context_file': str(self.context), 'uploaded_file': str(self.base), 'approved': True})

    def test_h_proposal_validation_and_conflict(self):
        proposal = {'sheet': 'Sheet1', 'cell': 'H2', 'pieces_per_box': 6, 'message_ref': 'TEST:chat'}
        for items in ([dict(proposal, approved=True)], [proposal, proposal], [dict(proposal, pieces_per_box=0)], [dict(proposal, cell='H999')]):
            r = self.preview(corrections=items); self.assertEqual(r['status'], 'rejected', r)
        r = self.preview(self.edited({'H2': 7}), [proposal]); self.assertEqual(r['status'], 'rejected', r)

    def test_archive_tampering_rejected(self):
        r = self.preview(); self.assertEqual(r['status'], 'preview_ready', r)
        p = next((self.out/'technical/uploads').glob('*.xlsx')); p.write_bytes(b'corrupt')
        with self.assertRaises(Rejected): service.read_preview(self.out)

    def test_preview_tampering_rejected(self):
        self.preview(); path = self.out/'technical/preview.json'; v = load(path); v['confirmed'] = True
        path.write_text(json.dumps(v));
        with self.assertRaises(Rejected): service.read_preview(self.out)

    def test_context_changed_mid_preview_no_eligible_result(self):
        actual = service.corrections
        def changed(*args):
            self.context.write_text('{}'); return actual(*args)
        with patch.object(service, 'corrections', side_effect=changed):
            self.rejected(self.base, '发生变化')

    def test_late_failure_quarantines_preview(self):
        actual = service.save
        def failed(path, value):
            if Path(path).name == 'result.json' and value.get('status') == 'preview_ready':
                raise OSError('TEST publication failure')
            return actual(path, value)
        with patch.object(service, 'save', side_effect=failed):
            self.rejected(self.base, 'publication failure')
        self.assertTrue((self.out/'technical/ineligible-preview.json').exists())

    def test_duplicate_zip_entries_rejected(self):
        p = self.root/'duplicate.xlsx'; p.write_bytes(self.base.read_bytes())
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(p, 'a') as z: z.writestr('xl/workbook.xml', b'<bad/>')
        self.rejected(p, '重复部件')

    def test_numeric_equal_blank_not_zero(self):
        r = self.preview(self.edited({'J2': 2.0})); self.assertEqual(r['modified_cells'], 0)
        self.rejected(self.edited({'J2': None}), 'Sheet1!J2')

    def test_rename_file_allowed_and_repeated_previews_no_business_versions(self):
        p = self.root/'rename.xlsx'; p.write_bytes(self.base.read_bytes())
        r1 = self.preview(p); r2 = self.preview(p)
        self.assertEqual(r1['preview_id'], r2['preview_id'])
        self.assertEqual(load(self.current/'result.json')['a_version'], self.r['a_version'])

    def test_duplicate_readonly_rows_need_scope_even_relative_formulas(self):
        def duplicate(w):
            s = w['Sheet1']
            for col in range(1, 17):
                s.cell(3, col).value = s.cell(2, col).value
            s['L3'] = '=J3*K3'
        self.f.edit_source(duplicate)
        self.r, self.base = self.f.result(); self.current = self.f.output; self.write_context([self.current])
        r = self.preview(self.edited({'E2': '范围待核'}))
        self.assertEqual(r['status'], 'preview_ready', r)
        self.assertEqual(r['needs_further_confirmation_cells'], 1)
        self.assertIn('只读内容重复', str(self.details['edits'][0]['reasons']))

    def test_local_named_range_change_rejected(self):
        from openpyxl.workbook.defined_name import DefinedName
        self.f.edit_source(lambda w: w['Sheet1'].defined_names.add(DefinedName('LocalQty', attr_text="'Sheet1'!$J$2")))
        self.r, self.base = self.f.result(); self.current = self.f.output; self.write_context([self.current])
        self.rejected(self.edited(action=lambda w: setattr(w['Sheet1'].defined_names['LocalQty'], 'attr_text', "'Sheet1'!$J$3")), '命名区域')

    def test_preview_does_not_call_existing_business_commit_or_store(self):
        from arrival_core.storage import Store
        from arrival_core.excel_return import ReturnService
        with patch.object(Store, 'save', side_effect=AssertionError('must not save')):
            with patch.object(ReturnService, 'commit', side_effect=AssertionError('must not commit')):
                r = self.preview(self.edited({'E2': '仍为提案'}))
        self.assertEqual(r['status'], 'preview_ready', r)

    def test_validated_raw_v2_mapping_not_native_letters(self):
        source = self.f.source_dir/'raw.xlsx'; fixtures.make_raw(source, version=2)
        self.r, self.base = self.f.result({'batch_id': 'KMT20261199-new', 'input_file': str(source)})
        self.current = self.f.output; self.write_context([self.current])
        def raw_edit(w): w['invoice (計算)']['F18'] = '新中文名'
        r = self.preview(self.edited(action=raw_edit))
        self.assertEqual(r['status'], 'preview_ready', r); self.assertEqual(r['modified_cells'], 1)
        self.assertEqual(self.details['edits'][0]['field'], 'internal_name')
        self.rejected(self.edited(action=lambda w: setattr(w['invoice (計算)']['M18'], 'value', 3)), 'M18')

    def test_new_external_link_and_macros_rejected(self):
        p = self.root/'active.xlsx'; p.write_bytes(self.base.read_bytes())
        with zipfile.ZipFile(p, 'a') as z: z.writestr('xl/vbaProject.bin', b'test')
        self.rejected(p, '宏')
        p = self.root/'external.xlsx'; p.write_bytes(self.base.read_bytes())
        with zipfile.ZipFile(p, 'a') as z:
            z.writestr('xl/externalLinks/externalLink1.xml', '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
        self.rejected(p, '外部链接')


if __name__ == '__main__': unittest.main()
