"""Explicit authorized A-01 copies only. Never recursively ingest business sources."""
import argparse
import json
from pathlib import Path

from native_return.support import bootstrap, load, save, digest, check_hashes
bootstrap()
from native_return.service import preview, read_preview
from native_copy.service import registered_copy
from native_return.compare import read, passive_links
from openpyxl import load_workbook


def run(config, output):
    output = Path(output).resolve()
    if output.exists(): raise ValueError('验收目录已存在')
    protected = dict(config['protected_files'])
    for p in config['issued_outputs']:
        for f in Path(p).rglob('*'):
            if f.is_file(): protected[str(f.resolve())] = digest(f)
    check_hashes(protected)
    output.mkdir(parents=True)
    issued = [registered_copy(p) for p in config['issued_outputs']]
    reg = issued[0]
    context = output/'trusted-context.json'
    save(context, {'schema': 'a02-trusted-context/1', 'current_output': config['issued_outputs'][0],
                   'business_batch_id': reg['business_batch_id'], 'export_id': reg['export_id'],
                   'a_version': reg['a_version'], 'known_outputs': config['issued_outputs']})
    uploads = output/'test-uploads'; uploads.mkdir()
    def edit(name, changes, sheet='Sheet1'):
        file = uploads/(name+'.xlsx'); w = load_workbook(reg['file'], keep_links=True)
        for address, value in changes.items(): w[sheet][address] = value
        w.save(file); w.close(); return file
    results = []
    def case(name, upload, expected, extra=None, modified=None, further=None):
        request = {'context_file': str(context), 'uploaded_file': str(upload)}
        if extra: request.update(extra)
        result = preview(output/name, request)
        assert result['status'] == expected, result
        if modified is not None: assert result['modified_cells'] == modified, result
        if further is not None: assert result['needs_further_confirmation_cells'] == further, result
        results.append({'name': name, 'upload': str(upload), 'result': result})
        return result
    # Programmatic edit simulation, explicitly not a business person's decision.
    w = load_workbook(reg['file']); values = {}
    for row in (2, 3):
        for col in ('E', 'F', 'M', 'N', 'O', 'P'):
            address = col+str(row); values[address] = str(w['Sheet1'][address].value or '')+'（回传测试）'
    w.close()
    for address in ('E2', 'M2', 'N2'): values[address] = None
    legal = edit('12格修改_仅程序测试', values)
    case('legal-12-cells', legal, 'preview_ready', modified=12, further=3)
    detail = read_preview(output/'legal-12-cells')
    save(output/'修改前后对比.json', {'test_only': True, 'issued_file': reg['file'],
                                      'returned_test_file': str(legal), 'edits': detail['edits']})
    table = ['# A-02实际Excel修改前后对比', '', '仅程序模拟编辑，不是业务确认；空值记为（空）。', '',
             '| 单元格 | 字段 | 发出值 | 回传值 | 需进一步确认 |', '|---|---|---|---|---|']
    def text(value):
        return ('（空）' if value is None else str(value)).replace('|', '\\|').replace('\n', ' ')
    for e in detail['edits']:
        table.append('| '+' | '.join([e['sheet']+'!'+e['cell'], e['field'], text(e['before']['value']),
                                       text(e['after']['value']), '是' if e['needs_further_confirmation'] else '否'])+' |')
    (output/'修改前后对比.md').write_text('\n'.join(table)+'\n', encoding='utf-8')
    # Each case is a separate real uploaded xlsx; no source or issued copy is edited.
    case('quantity-rejected', edit('数量误改', {'J2': 71}), 'rejected')
    case('amount-rejected', edit('金额公式误改', {'L2': 108291}), 'rejected')
    case('h-formula-rejected', edit('H原公式误改', {'H17': 6}), 'rejected')
    original = load_workbook(reg['file']); weights = reg['protected_weight_sheets'][0]
    assert original[weights]['B2'].value is not None; original.close()
    case('weight-rejected', edit('箱重误改', {'B2': 99999}, weights), 'rejected')
    case('h-chat-proposal', Path(reg['file']), 'preview_ready',
         {'box_corrections': [{'sheet': 'Sheet1', 'cell': 'H17', 'pieces_per_box': 6,
                              'message_ref': 'TEST:模拟对话-原表17行每盒6件；不是业务确认'}]}, modified=0, further=0)
    case('unchanged', Path(reg['file']), 'preview_ready', modified=0, further=0)
    case('other-batch-rejected', Path(issued[1]['file']), 'rejected')
    # Ordinary Excel saves may remove/recalculate caches; compare formulas separately.
    before_bytes = Path(reg['file']).read_bytes(); after_bytes = legal.read_bytes()
    before, _ = read(before_bytes, trusted_external=passive_links(before_bytes))
    after, _ = read(after_bytes, trusted_external=passive_links(before_bytes))
    formulas = [(s.title, c.coordinate, c.value) for s in before for c in s._cells.values() if c.data_type == 'f']
    after_formulas = [(s.title, c.coordinate, c.value) for s in after for c in s._cells.values() if c.data_type == 'f']
    assert formulas == after_formulas
    assert before.sheetnames == after.sheetnames
    assert [[(c.coordinate, c.value) for c in s._cells.values() if c.value is not None] for s in before if s.title in reg['protected_weight_sheets']] == [[(c.coordinate, c.value) for c in s._cells.values() if c.value is not None] for s in after if s.title in reg['protected_weight_sheets']]
    assert all(len(s[1]) == len(t[1]) for s, t in zip([(s.title, list(s.rows)) for s in before], [(s.title, list(s.rows)) for s in after]))
    before.close(); after.close()
    check_hashes(protected)
    result = {'schema': 'a02-authorized-history-acceptance/1', 'test_kind': 'programmatic_edit_on_authorized_historical_workbook',
              'real_human_review': False, 'independent_new_batch_validated': False,
              'source_and_issued_files_unchanged': True, 'protected_files_checked': len(protected),
              'original_formula_count': len(formulas), 'original_formulas_preserved_in_legal_return': True,
              'weight_values_and_formulas_preserved_in_legal_return': True,
              'cache_changes_tracked_not_adopted': detail['formula_cache_differences'],
              'packaging_groups': [{'kind': g['kind'], 'count': g['count']} for g in detail['packaging_audit']['groups']],
              'all_cases_passed': True, 'cases': results, 'confirmed': False, 'a_version_saved': False,
              'b_calculated': False, 'business_exception_total': None, 'actual_human_actions': None, 'time_saved': None}
    save(output/'acceptance.json', result)
    save(output/'protection-check.json', {'files': protected, 'all_unchanged': True})
    return {'all_cases_passed': True, 'cases': len(results), 'protected_files': len(protected),
            'packaging_groups': result['packaging_groups'], 'formula_count': len(formulas)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--config', required=True); p.add_argument('--output', required=True)
    args = p.parse_args(); print(json.dumps(run(load(args.config), args.output), ensure_ascii=False, indent=2))
