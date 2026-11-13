"""Immutable preview artifacts only. No Store.save, HEAD update or commit API."""
from pathlib import Path

from . import __version__
from .support import ROOT, Rejected, bootstrap, digest, key, load, save, check_hashes
from .compare import (InvalidReturn, read, compare, packaging_audit, cache_differences,
                      positive_integer, shown, passive_links)


def context_snapshot(path):
    from native_copy.service import registered_copy
    path = Path(path).resolve(strict=True); snapshot = {str(path): digest(path)}
    context = load(path)
    required = {'schema', 'current_output', 'business_batch_id', 'export_id', 'a_version', 'known_outputs'}
    if set(context) != required or context['schema'] != 'a02-trusted-context/1':
        raise InvalidReturn('当前批次会话配置无效')
    paths = context['known_outputs']
    if not isinstance(paths, list) or not paths or len(paths) > 64 or len(set(paths)) != len(paths):
        raise InvalidReturn('已登记副本范围无效')
    resolved = [Path(p).resolve(strict=True) for p in paths]
    if len(set(resolved)) != len(resolved) or Path(context['current_output']).resolve(strict=True) not in resolved:
        raise InvalidReturn('当前副本不在可信登记范围内')
    registries = []
    for output in resolved:
        for name in ('result.json', 'technical/export-registration.json', 'technical/reference-candidates.json'):
            item = output / name; snapshot[str(item)] = digest(item)
        reg = registered_copy(output)
        snapshot[reg['file']] = digest(reg['file'])
        snapshot.update({s['path']: s['sha256'] for s in reg['source_manifest']})
        registries.append(reg)
    current = registries[resolved.index(Path(context['current_output']).resolve(strict=True))]
    for name in ('business_batch_id', 'export_id', 'a_version'):
        if current[name] != context[name]:
            raise InvalidReturn('当前批次或A版本与宿主登记不一致')
    check_hashes(snapshot)
    return context, registries, current, snapshot


def version_identity(reg):
    return (reg['business_batch_id'], reg['a_version'], reg['copy_sha256'], reg['row_map_hash'])


def corrections(requests, reg, wb):
    if not isinstance(requests, list) or len(requests) > 10000:
        raise InvalidReturn('盒规对话提案格式无效')
    fields = {(f['sheet'], f['cell']): f for f in reg['fields'] if f['field'] == 'pieces_per_box'}
    proposals = []; seen = set()
    for req in requests:
        if not isinstance(req, dict) or set(req) != {'sheet', 'cell', 'pieces_per_box', 'message_ref'}:
            raise InvalidReturn('盒规提案须有原格、每盒件数和对话引用；不接收批准参数')
        target = (req['sheet'], req['cell'])
        if target in seen or target not in fields:
            raise InvalidReturn('盒规提案原行未登记或重复')
        value = positive_integer(req['pieces_per_box'])
        if value is None or not isinstance(req['message_ref'], str) or not req['message_ref'].strip():
            raise InvalidReturn('盒规提案须为正整数且有对话出处')
        seen.add(target); f = fields[target]; cell = wb[target[0]][target[1]]
        proposals.append({'row_id': f['row_id'], 'sheet': target[0], 'cell': target[1],
                          'original': shown(cell), 'proposed_pieces_per_box': value,
                          'message_ref': req['message_ref'], 'export_id': reg['export_id'],
                          'a_version': reg['a_version'], 'status': 'proposed_only',
                          'workbook_written': False, 'confirmed': False, 'qty_unit_confirmed': False})
    return proposals


def preview(output, request):
    if not isinstance(request, dict) or set(request) - {'context_file', 'uploaded_file', 'box_corrections'} or not {'context_file', 'uploaded_file'} <= set(request):
        raise Rejected('仅接受可信上下文、回传文件和可选盒规对话提案；不接收确认保存或计算参数')
    output = Path(output).resolve()
    if output.exists():
        raise Rejected('预览目录已存在，拒绝覆盖')
    upload = Path(request['uploaded_file']).resolve(strict=True)
    context_path = Path(request['context_file']).resolve(strict=True)
    if output == upload.parent or upload.is_relative_to(output) or context_path.is_relative_to(output):
        raise Rejected('预览输出必须与输入隔离')
    output.mkdir(parents=True)
    result = {'schema': 'a02-native-return-preview-result/1', 'implementation': __version__,
              'status': 'rejected', 'modified_cells': None, 'needs_further_confirmation_cells': None,
              'confirmed': False, 'confirmed_fields': [], 'can_enter_b': False, 'formal_output': False,
              'a_version_saved': False, 'business_files': [], 'business_exception_total': None,
              'actual_human_actions': None, 'time_saved': None}
    wb = None; opened = []
    try:
        lock = bootstrap()
        from arrival_core.excel_return import _archive, sha
        context, registries, current, snapshot = context_snapshot(context_path)
        if upload.suffix.lower() != '.xlsx':
            raise InvalidReturn('只接受xlsx回传')
        data = upload.read_bytes(); upload_sha = sha(data)
        snapshot[str(upload)] = upload_sha
        # Existing B2's exclusive hash archive, with no business state transaction.
        archive = output / 'technical' / 'uploads' / (upload_sha + '.xlsx')
        _archive(archive, data)
        snapshot[str(archive)] = upload_sha
        if any(upload_sha == r['copy_sha256'] and version_identity(r) != version_identity(current) for r in registries):
            raise InvalidReturn('回传文件属于旧版本或其他批次，拒绝覆盖当前结果')
        trusted_links = passive_links(Path(current['file']).read_bytes())
        wb, returned_xml = read(data, trusted_external=trusted_links); opened.append(wb)
        current_base = None; current_xml = None; current_edits = None; current_error = None
        matches = []; exact_old = []
        for reg in registries:
            base_data = Path(reg['file']).read_bytes()
            base, parsed = read(base_data, trusted_external=passive_links(base_data)); opened.append(base)
            if reg['export_id'] == current['export_id']:
                current_base, current_xml = base, parsed
            if upload_sha == reg['copy_sha256'] and version_identity(reg) != version_identity(current):
                exact_old.append(reg['export_id'])
            try:
                edits = compare(base, wb, reg)
                matches.append(reg)
                if reg['export_id'] == current['export_id']:
                    current_edits = edits
            except InvalidReturn as exc:
                if reg['export_id'] == current['export_id']:
                    current_error = exc
        if exact_old:
            raise InvalidReturn('回传文件属于旧版本或其他批次，拒绝覆盖当前结果')
        identities = {version_identity(r) for r in matches}
        if len(identities) > 1:
            raise InvalidReturn('只读内容同时匹配多个批次/版本，不能确定来源；请取当前副本重新修改')
        if current_edits is None:
            if matches:
                raise InvalidReturn('回传文件匹配其他批次或旧版本，拒绝覆盖当前结果')
            raise current_error or InvalidReturn('无法匹配已发出的工作副本')
        if identities != {version_identity(current)}:
            raise InvalidReturn('无法唯一定位当前版本')
        proposed = corrections(request.get('box_corrections', []), current, current_base)
        direct_h = {(e['sheet'], e['cell']) for e in current_edits if e['field'] == 'pieces_per_box'}
        if any((p['sheet'], p['cell']) in direct_h for p in proposed):
            raise InvalidReturn('同一H格同时有Excel修改和对话提案，须先消除冲突')
        audit = packaging_audit(current, current_base)
        cache = cache_differences(current_xml, returned_xml)
        unchanged_candidates = [{'row_id': f['row_id'], 'sheet': f['sheet'], 'cell': f['cell'],
                                 'field': f['field'], 'status': 'candidate', 'confirmed': False}
                                for f in current['fields'] if f['status'] == 'candidate'
                                and not any(e['sheet'] == f['sheet'] and e['cell'] == f['cell'] for e in current_edits)]
        details = {'schema': 'a-original-return-preview/1', 'implementation': __version__,
                   'business_batch_id': current['business_batch_id'], 'export_id': current['export_id'],
                   'a_version': current['a_version'], 'source_manifest_hash': current['source_manifest_hash'],
                   'row_map_hash': current['row_map_hash'], 'upload_sha256': upload_sha,
                   'context_sha256': snapshot[str(context_path)], 'known_export_ids': [r['export_id'] for r in registries],
                   'binding_method': 'unique_registered_readonly_content_match',
                   'binding_scope': 'host_supplied_complete_known_export_set; no embedded Excel version identifier',
                   'edits': current_edits, 'box_proposals': proposed, 'packaging_audit': audit,
                   'unchanged_candidates': unchanged_candidates, 'formula_cache_differences': cache,
                   'returned_formula_cache_adopted': False, 'approval_events': [],
                   'confirmed': False, 'can_enter_b': False, 'formal_output': False,
                   'proposed_invalidation_only': ['B_confirmation', 'C_delivery', 'calculation_input_fingerprint'] if current_edits or proposed else [],
                   'original_files_and_a_head_unchanged': True, 'dependency_files_checked': len(lock['files'])}
        preview_id = key(details); details['preview_id'] = preview_id
        check_hashes(snapshot); bootstrap()
        save(output / 'technical' / 'preview.json', details)
        check_hashes(snapshot); bootstrap()
        needed = sum(e['needs_further_confirmation'] for e in current_edits)
        result.update(status='preview_ready', preview_id=preview_id,
                      modified_cells=len(current_edits), needs_further_confirmation_cells=needed,
                      box_proposal_count=len(proposed), unchanged_candidate_cells=len(unchanged_candidates),
                      formula_cache_difference_count=len(cache), business_batch_id=current['business_batch_id'],
                      export_id=current['export_id'], a_version=current['a_version'],
                      message=f'修改了{len(current_edits)}格，{needed}格需要进一步确认' +
                              (f'；另有{len(proposed)}条盒规对话提案' if proposed else '') + '；仅预览，尚未确认保存')
        save(output / 'result.json', result)
        return result
    except Exception as exc:
        # A preview is usable only with a successful final result bound to its hash.
        pending = output / 'technical' / 'preview.json'
        if pending.exists():
            pending.rename(output / 'technical' / 'ineligible-preview.json')
        for field in ('preview_id', 'box_proposal_count', 'unchanged_candidate_cells', 'formula_cache_difference_count'):
            result.pop(field, None)
        result.update(status='rejected', modified_cells=None, needs_further_confirmation_cells=None,
                      reason=str(exc), positions=getattr(exc, 'positions', []), message='回传未通过核验，未应用任何修改')
        save(output / 'technical' / 'rejection.json', {'type': type(exc).__name__, 'reason': str(exc),
                                                      'positions': getattr(exc, 'positions', [])})
        save(output / 'result.json', result)
        return result
    finally:
        for book in opened:
            book.close()


def read_preview(output):
    """Verify an eligible artifact for display, without exposing a commit path."""
    output = Path(output)
    result = load(output / 'result.json')
    if result.get('status') != 'preview_ready':
        raise Rejected('拒绝或不完整的运行没有可用预览')
    detail = load(output / 'technical' / 'preview.json')
    preview_id = detail.pop('preview_id')
    if key(detail) != preview_id or result['preview_id'] != preview_id:
        raise Rejected('预览内容与摘要不一致')
    archive = output / 'technical' / 'uploads' / (detail['upload_sha256'] + '.xlsx')
    if digest(archive) != detail['upload_sha256']:
        raise Rejected('回传归档被修改')
    return dict(detail, preview_id=preview_id)
