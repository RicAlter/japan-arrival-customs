"""A-01: original-format reference copy and immutable export registration only."""
from collections import Counter
from decimal import Decimal
from pathlib import Path
import re

from . import __version__
from .support import ROOT, Rejected, bootstrap, check_hashes, digest, key, save, snapshot_root
from .profiles import inspect_source
from .references import query, positive_integer, scalar
from .ooxml import build, verify


def _value(v):
    return format(v, 'f') if isinstance(v, Decimal) else v


def _merged_non_anchor(sheet, address):
    from openpyxl.utils.cell import range_boundaries, coordinate_to_tuple
    row, col = coordinate_to_tuple(address)
    for area in sheet.merges:
        a, b, c, d = range_boundaries(area)
        if a <= col <= c and b <= row <= d:
            return (row, col) != (b, a)
    return False


def prepare_fields(source, references):
    sheet = source['sheet']; proposals = []; fields = []; counts = Counter()
    for row in source['rows']:
        candidates = references['field_candidates'][row['row_id']]
        for field, col in source['targets'].items():
            addr = col + str(row['source_row']); old = sheet.cells.get(addr, {})
            value = old.get('v'); formula = old.get('f')
            record = {'row_id': row['row_id'], 'sheet': sheet.name, 'cell': addr, 'field': field,
                      'original_value': _value(value), 'original_type': old.get('type'), 'original_formula': formula,
                      'working_value': _value(value), 'status': 'preserved_unverified', 'confirmed': False,
                      'sources': [], 'material_approval': False}
            blank = value in (None, '') and not formula
            proposed = None
            if formula:
                record['status'] = 'original_formula_preserved'
                if field == 'pieces_per_box':
                    record['pieces_per_box_observed'] = positive_integer(value)
                    if record['pieces_per_box_observed'] is None:
                        record['status'] = 'original_packaging_formula_needs_confirmation'
                        proposed = {'cell': addr, 'field': field, 'write_value': None, 'color': 'red'}
            elif _merged_non_anchor(sheet, addr):
                record['status'] = 'merged_non_anchor_preserved'
            elif not blank:
                if field == 'pieces_per_box':
                    record['pieces_per_box_observed'] = positive_integer(value)
                    if record['pieces_per_box_observed'] is None:
                        record['status'] = 'existing_packaging_value_needs_confirmation'
                        proposed = {'cell': addr, 'field': field, 'write_value': None, 'color': 'red'}
                elif field in ('internal_name', 'category', 'material_reference') and scalar(_value(value)) is None:
                    record['status'] = 'existing_unknown_value_preserved'
                    proposed = {'cell': addr, 'field': field, 'write_value': None, 'color': 'red'}
            else:
                c = candidates.get(field)
                if c and c['status'] == 'candidate':
                    v = c['value']
                    if field == 'pieces_per_box' and positive_integer(v) is None:
                        raise Rejected('资料盒规不是有效每盒件数')
                    record.update(working_value=v, status='candidate', sources=c['sources'])
                    proposed = {'cell': addr, 'field': field, 'write_value': v, 'color': 'yellow',
                                'value_type': 'number' if field in ('pieces_per_box', 'purchase_unit_price') else 'text'}
                    counts['prefilled_cells'] += 1
                else:
                    record['status'] = 'conflict' if c and c['status'] == 'conflict' else 'unknown'
                    if c:
                        record['conflicts'] = c.get('variants', [])
                    if field in ('internal_name', 'category', 'material_reference') or record['status'] == 'conflict':
                        proposed = {'cell': addr, 'field': field, 'write_value': None, 'color': 'red'}
            if proposed:
                proposed['row_id'] = row['row_id']; proposals.append(proposed)
            fields.append(record)
    if len({p['cell'] for p in proposals}) != len(proposals):
        raise Rejected('补填字段映射到重复单元格')
    return fields, proposals, dict(counts)


def execute(output, request):
    if (not isinstance(request, dict) or set(request) - {'batch_id', 'input_file', 'library_config'}
            or not isinstance(request.get('batch_id'), str) or not request['batch_id'].strip()
            or not isinstance(request.get('input_file'), str)):
        raise Rejected('仅接受batch_id、input_file和可选只读library_config；不接收确认或答案参数')
    if len(request['batch_id']) > 128 or any(ord(c) < 32 for c in request['batch_id']):
        raise Rejected('批次标识无效')
    source_path = Path(request['input_file']).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists():
        raise Rejected('输出目录已存在，拒绝覆盖旧副本或登记')
    if output.is_relative_to(source_path.parent) or source_path.is_relative_to(output):
        raise Rejected('工作输出须与原附件目录隔离')
    lock = bootstrap()
    source = inspect_source(source_path)
    code_snapshot = {str(p): digest(p) for p in (ROOT / 'native_copy').glob('*.py')}
    snapshot = {str(source_path): source['book'].sha256, **code_snapshot}
    output.mkdir(parents=True)
    technical = output / 'technical'; technical.mkdir()
    staged = technical / 'staged-copy.xlsx'; published = None; stage = 'read_only_reference_query'
    result = {'schema': 'a01-native-copy-result/1', 'status': 'validation_incomplete', 'business_files': [],
              'formal_output': False, 'confirmed': False, 'can_enter_b': False,
              'business_exception_total': None, 'actual_human_actions': None, 'time_saved_seconds': None}
    try:
        references = query(request.get('library_config'), source, request['batch_id'])
        if references['database']:
            info = references['database']
            if Path(info['path']).is_relative_to(output):
                raise Rejected('资料库不能位于输出目录')
            snapshot[info['path']] = info['sha256']
        save(technical / 'reference-candidates.json', references)
        stage = 'blank_cell_fill_plan'
        fields, proposals, counts = prepare_fields(source, references)
        save(technical / 'field-state.json', {'fields': fields, 'confirmed': False})
        stage = 'copy_and_preservation_check'
        copy_bytes, changes = build(source['bytes'], source['sheet'].name, proposals)
        staged.write_bytes(copy_bytes)
        preservation = verify(source['bytes'], staged.read_bytes(), source['sheet'].name, changes)
        save(technical / 'preservation.json', preservation)
        save(technical / 'changes.json', {'cells': changes, 'original_nonempty_values_overwritten': 0})
        stage = 'export_registration'
        from arrival_core.storage import Store
        batch = source['batch']
        batch['business_batch_id'] = request['batch_id']
        a_body = {'source_sha256': source['book'].sha256, 'profile_id': source['profile_id'],
                  'row_map_hash': source['row_map_hash'], 'fields': fields,
                  'reference_snapshot_hash': key(references), 'confirmed': False}
        a_version = key(a_body)
        file_name = source_path.stem + '_工作副本.xlsx'
        copy_rel = 'delivery/' + file_name
        registration = {'schema': 'a01-native-copy-registration/1', 'implementation_version': __version__,
            'business_batch_id': request['batch_id'], 'source_manifest': batch['sources'],
            'source_manifest_hash': key(batch['sources']),
            'implementation_files_sha256': code_snapshot, 'dependency_lock_sha256': digest(ROOT / 'dependency-lock.json'),
            'profile_id': source['profile_id'], 'source_header_row': source['header_row'],
            'source_qualification': batch.get('source_qualification', 'existing_supported_raw_layout_not_certified_unannotated'),
            'source_sha256': source['book'].sha256, 'copy_sha256': digest(staged), 'copy_relative_path': copy_rel,
            'batch_id': batch['id'], 'batch_revision': 0, 'a_version': a_version,
            'row_map_hash': source['row_map_hash'], 'row_map': source['rows'],
            'fields': fields, 'copy_changes': changes, 'reference_snapshot_hash': key(references),
            'library_snapshot': references['database'], 'protected_weight_sheets': source['weights'],
            'preservation': preservation, 'confirmed_fields': [], 'qty_unit_confirmed': False,
            'material_approval': False, 'formal_output': False, 'can_enter_b': False,
            'supported_operations': ['register_copy'], 'unimplemented_operations': ['preview_return', 'commit_a', 'read_for_b', 'split', 'merge'],
            'activation_requires_result_status': 'prepared_reference_copy'}
        export_id = key(registration); registration['export_id'] = export_id
        batch['a01_preparation'] = {'a_version': a_version, 'export_id': export_id, 'confirmed': False,
                                    'reference_copy_only': True}
        Store(snapshot_root(technical / 'batch-store')).save(batch)
        save(technical / 'export-registration.json', registration)
        stage = 'publication'
        check_hashes(snapshot); bootstrap()
        if digest(staged) != registration['copy_sha256']:
            raise Rejected('副本核验后发生变化')
        delivery = output / 'delivery'; delivery.mkdir()
        published = delivery / file_name
        staged.rename(published)
        check_hashes(snapshot); bootstrap()
        if digest(published) != registration['copy_sha256']:
            raise Rejected('发布后副本与登记不一致')
        result.update(status='prepared_reference_copy', stage='registered', business_files=[str(published)],
            registration=str(technical / 'export-registration.json'), export_id=export_id, a_version=a_version,
            profile_id=source['profile_id'], rows=len(source['rows']),
            prefilled_cells=counts.get('prefilled_cells', 0),
            yellow_cells=sum(c['color'] == 'yellow' and c['fill_applied'] for c in changes),
            red_cells=sum(c['color'] == 'red' and c['fill_applied'] for c in changes),
            preserved_original_fill_cells=sum(not c['fill_applied'] for c in changes),
            unmapped_fields=sorted({'internal_name', 'specification', 'category', 'material_reference',
                                    'yd', 'channel', 'pieces_per_box', 'purchase_unit_price'} - set(source['targets'])),
            preservation=preservation, dependency_files_checked=len(lock['files']),
            input_and_database_unchanged=True,
            message='原表工作副本已准备，黄色仅参考，红格/空格待处理，尚未确认或计算')
        save(output / 'result.json', result)
        return result
    except Exception as exc:
        # A late failure removes public eligibility, preserving diagnostics in this run.
        if published is not None and published.exists():
            published.rename(technical / 'rejected-copy.xlsx')
        result.update(status='validation_incomplete', stage=stage, reason=str(exc), business_files=[])
        save(technical / 'failure.json', {'stage': stage, 'type': type(exc).__name__, 'reason': str(exc)})
        save(output / 'result.json', result)
        return result


def registered_copy(output):
    """Read a completed registration without implementing a return/approval API."""
    from .support import load
    output = Path(output).resolve(strict=True)
    result = load(output / 'result.json')
    if result.get('status') != 'prepared_reference_copy':
        raise Rejected('未完成发布的登记不可用')
    registry_path = output / 'technical/export-registration.json'
    registration = load(registry_path)
    export_id = registration.pop('export_id')
    if key(registration) != export_id or result.get('export_id') != export_id:
        raise Rejected('副本登记被修改或不属于当前结果')
    references = load(output / 'technical/reference-candidates.json')
    if key(references) != registration['reference_snapshot_hash']:
        raise Rejected('登记的来源候选快照被修改')
    path = (output / registration['copy_relative_path']).resolve(strict=True)
    if not path.is_relative_to(output / 'delivery') or digest(path) != registration['copy_sha256']:
        raise Rejected('副本丢失、被修改或路径越界')
    check_hashes({s['path']: s['sha256'] for s in registration['source_manifest']})
    return dict(registration, export_id=export_id, file=str(path))
