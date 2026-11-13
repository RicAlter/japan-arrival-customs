"""Thin A preparation orchestration around frozen query, patch and storage APIs."""
from pathlib import Path
from . import __version__
from .support import ROOT, Rejected, bootstrap, code_snapshot, check_hashes, digest, key, save, load
from .profiles import inspect_source
from .pricing import bind_basis, mapping, analyze, formula_plan
from .workbook import render


def prepare(output, request):
    if not isinstance(request, dict) or set(request)-{'batch_id', 'input_file', 'library_config', 'price_basis'} or not {'batch_id', 'input_file'} <= set(request):
        raise Rejected('只接受批次、原件、可选只读资料库及价格口径，不接收确认或答案')
    bootstrap()
    if not isinstance(request['batch_id'], str) or not request['batch_id'].strip() or len(request['batch_id']) > 128 or any(ord(c)<32 for c in request['batch_id']):
        raise Rejected('批次标识无效')
    source = inspect_source(request['input_file'])
    if source['profile_id'] != 'kmt-native-22-v1' and request.get('price_basis') is None:
        from native_copy.service import execute
        return execute(output, {k: v for k, v in request.items() if k != 'price_basis'})
    output = Path(output).resolve(); input_path = Path(source['path'])
    if output.exists(): raise Rejected('输出目录已存在，不覆盖')
    if output.is_relative_to(input_path.parent) or input_path.is_relative_to(output): raise Rejected('输出须与原附件目录隔离')
    basis = bind_basis(request.get('price_basis'), source)
    snapshot = {source['path']: source['book'].sha256, **code_snapshot()}
    output.mkdir(parents=True); tech = output/'technical'; tech.mkdir(); published = None
    result = {'schema': 'a22-preparation-result/1', 'implementation': __version__, 'status': 'validation_incomplete',
              'business_files': [], 'confirmed': False, 'can_enter_b': False, 'formal_output': False,
              'business_exception_total': None, 'actual_human_actions': None, 'time_saved': None}
    try:
        from native_copy.references import query
        from native_copy.service import prepare_fields
        from native_copy.ooxml import build, verify
        from native_copy.support import snapshot_root
        from arrival_core import _p0_frozen as p0
        from arrival_core.storage import Store
        references = query(request.get('library_config'), source, request['batch_id'])
        if references['database']: snapshot[references['database']['path']] = references['database']['sha256']
        fields, fills, counts = prepare_fields(source, references)
        # Derived H decimals are routine computation, not thousands of missing-source tasks.
        fills = [p for p in fills if not (p['field'] == 'pieces_per_box' and p['color'] == 'red' and
                 (basis['status'] == 'bound_to_dialogue_basis' or source['sheet'].cells.get(p['cell'], {}).get('f')))]
        filled, fill_changes = build(source['bytes'], source['sheet'].name, fills)
        fill_preservation = verify(source['bytes'], filled, source['sheet'].name, fill_changes)
        filled_book = p0.Book(filled, 'registered-reference-copy.xlsx')
        filled_sheet = next(s for s in filled_book.sheets if s.name == source['sheet'].name)
        pricing = analyze(source, filled_sheet, fields, basis)
        formula_changes = formula_plan(pricing); columns = mapping(source)
        formats = {columns[k]+str(r['source_row']) for r in source['rows'] for k in ('purchase', 'comparison')}
        if basis['status'] != 'bound_to_dialogue_basis': formats = set()
        copy_bytes, preservation = render(filled, source['sheet'].name, formula_changes, formats, pricing['display_marks'])
        final_book = p0.Book(copy_bytes, 'registered-working-copy.xlsx')
        final_sheet = next(s for s in final_book.sheets if s.name == source['sheet'].name)
        price_rows = {r['row_id']: r for r in pricing['rows']}
        for field in fields:
            actual = final_sheet.cells.get(field['cell'], {})
            field['working_value'] = str(actual['v']) if isinstance(actual.get('v'), p0.Decimal) else actual.get('v')
            field['working_formula'] = actual.get('f')
            if field['field'] == 'pieces_per_box' and field['row_id'] in price_rows:
                field['calculation_status'] = price_rows[field['row_id']]['status']
                if field['cell'] in formula_changes: field['status'] = 'derived_reference_not_confirmed'
        save(tech/'reference-candidates.json', references); save(tech/'pricing.json', pricing)
        save(tech/'field-state.json', {'fields': fields, 'confirmed': False})
        save(tech/'preservation.json', {'blank_fill': fill_preservation, 'controlled_calculation': preservation})
        save(tech/'changes.json', {'blank_fills': fill_changes, 'calculation': preservation['formula_changes'],
                                  'display_marks': pricing['display_marks'], 'original_business_prices_overwritten': 0})
        staged = tech/'staged-copy.xlsx'; staged.write_bytes(copy_bytes)
        av = key({'source_sha256': source['book'].sha256, 'profile_id': source['profile_id'],
                  'fields': fields, 'references': key(references), 'pricing': key(pricing), 'confirmed': False})
        filename = input_path.stem+'_工作副本.xlsx'; batch = source['batch']; batch['business_batch_id'] = request['batch_id']
        reg = {'schema': 'a02-native22-registration/1', 'implementation_version': __version__,
               'business_batch_id': request['batch_id'], 'source_manifest': batch['sources'],
               'source_manifest_hash': key(batch['sources']), 'source_sha256': source['book'].sha256,
               'implementation_files_sha256': code_snapshot(), 'dependency_lock_sha256': digest(ROOT/'dependency-lock.json'),
               'profile_id': source['profile_id'], 'source_header_row': source['header_row'],
               'source_qualification': batch.get('source_qualification'), 'copy_sha256': digest(staged),
               'copy_relative_path': 'delivery/'+filename, 'batch_id': batch['id'], 'batch_revision': 0, 'a_version': av,
               'row_map_hash': source['row_map_hash'], 'row_map': source['rows'], 'fields': fields,
               'reference_snapshot_hash': key(references), 'library_snapshot': references['database'],
               'pricing_snapshot_hash': key(pricing), 'price_basis': basis, 'price_columns': columns,
               'source_file': source['path'], 'source_formula_records': [r['source'] for r in source['rows']],
               'copy_changes': fill_changes, 'controlled_formula_changes': preservation['formula_changes'],
               'protected_weight_sheets': source['weights'], 'preservation': preservation,
               'confirmed_fields': [], 'confirmed': False, 'qty_unit_confirmed': False, 'material_approval': False,
               'formal_output': False, 'can_enter_b': False, 'supported_operations': ['register_copy', 'preview_return'],
               'unimplemented_operations': ['commit_a', 'split', 'merge', 'read_for_b']}
        export_id = key(reg); reg['export_id'] = export_id
        batch['a22_preparation'] = {'a_version': av, 'export_id': export_id, 'confirmed': False}
        Store(snapshot_root(tech/'batch-store')).save(batch)
        save(tech/'export-registration.json', reg)
        check_hashes(snapshot); bootstrap()
        delivery = output/'delivery'; delivery.mkdir(); published = delivery/filename; staged.rename(published)
        if digest(published) != reg['copy_sha256']: raise Rejected('发布副本与登记不一致')
        check_hashes(snapshot); bootstrap()
        result.update(status='prepared_reference_copy', business_files=[str(published)], export_id=export_id, a_version=av,
                      registration=str(tech/'export-registration.json'), profile_id=source['profile_id'], rows=len(source['rows']),
                      prefilled_cells=counts.get('prefilled_cells', 0), pricing_counts=pricing['counts'],
                      price_issue_groups=len(pricing['groups']), program_groups=len(pricing['program_groups']),
                      red_price_rows=pricing.get('affected_price_rows'),
                      red_cells=len({m['cell'] for m in pricing['display_marks']} | {c['cell'] for c in fill_changes if c['color']=='red'}),
                      yellow_cells=sum(c['color']=='yellow' and c['fill_applied'] for c in fill_changes),
                      preservation=preservation, message=('同版式工作副本已登记；价格口径待核，尚未执行价格验算' if basis['status'] != 'bound_to_dialogue_basis'
                                                          else '同版式工作副本已登记；计算仅供参考，未确认保存或进入B计算'))
        save(output/'result.json', result); return result
    except Exception as exc:
        if published is not None and published.exists(): published.rename(tech/'rejected-copy.xlsx')
        result.update(status='validation_incomplete', reason=str(exc), business_files=[])
        save(tech/'failure.json', {'type': type(exc).__name__, 'reason': str(exc)})
        save(output/'result.json', result); return result


def registered_copy(output):
    from native_copy.service import registered_copy as old_registered
    reg = old_registered(output)
    if reg.get('schema') == 'a02-native22-registration/1':
        pricing = load(Path(output)/'technical/pricing.json')
        if key(pricing) != reg['pricing_snapshot_hash']: raise Rejected('盒规价格核验快照被修改')
    return reg
