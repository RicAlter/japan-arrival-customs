"""Reuse A-02's full return comparison, then add bound, cache-independent checks."""
from pathlib import Path
from . import __version__
from .support import Rejected, bootstrap, code_snapshot, check_hashes, digest, key, load, save
from .prepare import registered_copy
from .profiles import inspect_source
from .pricing import analyze


def preview(output, request):
    if not isinstance(request, dict) or set(request)-{'context_file', 'uploaded_file', 'box_corrections'} or not {'context_file', 'uploaded_file'} <= set(request):
        raise Rejected('只支持回传预览，不接收确认、保存、拆分或计算参数')
    bootstrap()
    from native_return import service as old
    context, registries, current, snapshot = old.context_snapshot(request['context_file'])
    for folder in context['known_outputs']:
        reg = registered_copy(folder)
        if reg.get('schema') == 'a02-native22-registration/1':
            path = Path(folder)/'technical/pricing.json'; snapshot[str(path)] = digest(path)
    if current.get('schema') != 'a02-native22-registration/1': return old.preview(output, request)
    snapshot.update(code_snapshot())
    output = Path(output).resolve(); upload = Path(request['uploaded_file']).resolve(strict=True)
    if output.exists(): raise Rejected('不覆盖已有预览')
    if upload.is_relative_to(output) or Path(request['context_file']).resolve().is_relative_to(output):
        raise Rejected('预览与输入须隔离')
    output.mkdir(parents=True); tech = output/'technical'; tech.mkdir()
    result = {'schema': 'a22-return-result/1', 'implementation': __version__, 'status': 'rejected',
              'modified_cells': None, 'needs_further_confirmation_cells': None, 'confirmed': False,
              'a_version_saved': False, 'can_enter_b': False, 'formal_output': False, 'business_files': [],
              'business_exception_total': None, 'actual_human_actions': None, 'time_saved': None}
    try:
        from native_copy.support import snapshot_root
        base_root = snapshot_root(tech/'base-compare')
        base_result = old.preview(base_root, request)
        if base_result['status'] != 'preview_ready':
            from native_return.compare import InvalidReturn
            raise InvalidReturn(base_result.get('reason', '原表保护核验失败'), base_result.get('positions', []))
        detail = old.read_preview(base_root)
        source = inspect_source(current['source_file'])
        from arrival_core import _p0_frozen as p0
        book = p0.Book(Path(current['file']).read_bytes(), 'issued-registered-copy.xlsx')
        sheet = next(s for s in book.sheets if s.name == source['sheet'].name)
        changes = {}
        for edit in detail['edits']:
            changes.setdefault(edit['row_id'], {})[edit['field']] = edit['after']['value']
        box = {p['row_id']: p['proposed_pieces_per_box'] for p in detail['box_proposals']}
        pricing = analyze(source, sheet, current['fields'], current['price_basis'], manual=changes, box_proposals=box)
        pending_rows = {r['row_id'] for r in pricing['rows'] if r.get('hypothetical_only')}
        extra = {'product_code', 'specification', 'purchase_unit_price', 'pieces_per_box'}
        for edit in detail['edits']:
            if edit['row_id'] in pending_rows and edit['field'] in extra:
                edit['needs_further_confirmation'] = True
                edit['reasons'] = sorted(set(edit['reasons']+['价格/盒规或身份依据改变，仅展示待确认提案']))
        detail.update(schema='a22-return-preview/1', implementation=__version__,
                      base_preview_id=detail.pop('preview_id'), price_check_snapshot_hash=key(pricing),
                      packaging_audit={'groups': pricing['groups'], 'program_groups': pricing['program_groups'],
                                       'actual_human_actions': None, 'confirmed': False},
                      pricing_counts=pricing['counts'], returned_formula_cache_adopted=False,
                      price_recheck_method='registered_observations_plus_explicit_manual_proposals_not_uploaded_formula_caches')
        preview_id = key(detail); detail['preview_id'] = preview_id
        check_hashes(snapshot); bootstrap()
        save(tech/'pricing-preview.json', pricing); save(tech/'preview.json', detail)
        archive = base_root/'technical/uploads'/(detail['upload_sha256']+'.xlsx')
        if digest(archive) != detail['upload_sha256']: raise Rejected('上传归档变化')
        check_hashes(snapshot); bootstrap()
        needed = sum(e['needs_further_confirmation'] for e in detail['edits'])
        result.update(status='preview_ready', preview_id=preview_id, export_id=current['export_id'], a_version=current['a_version'],
                      modified_cells=len(detail['edits']), needs_further_confirmation_cells=needed,
                      box_proposal_count=len(detail['box_proposals']), pricing_counts=pricing['counts'],
                      price_issue_groups=len(pricing['groups']), red_price_rows=pricing.get('affected_price_rows'),
                      unchanged_candidate_cells=base_result['unchanged_candidate_cells'],
                      formula_cache_difference_count=base_result['formula_cache_difference_count'],
                      message=f'修改了{len(detail["edits"])}格，{needed}格需要进一步确认；'+
                              ('盒规价格已重新核验' if current['price_basis']['status']=='bound_to_dialogue_basis' else '价格口径待核，未执行验算')+
                              '，仅预览，未确认保存')
        save(output/'result.json', result); return result
    except Exception as exc:
        if (tech/'preview.json').exists(): (tech/'preview.json').rename(tech/'ineligible-preview.json')
        result.pop('preview_id', None)
        result.update(status='rejected', modified_cells=None, needs_further_confirmation_cells=None,
                      reason=str(exc), positions=getattr(exc, 'positions', []), business_files=[])
        save(tech/'rejection.json', {'type': type(exc).__name__, 'reason': str(exc), 'positions': result['positions']})
        save(output/'result.json', result); return result


def read_preview(output):
    from native_return.service import read_preview as old_read
    output = Path(output); result = load(output/'result.json')
    if result.get('schema') != 'a22-return-result/1': return old_read(output)
    if result.get('status') != 'preview_ready': raise Rejected('没有可用的新格式预览')
    detail = load(output/'technical/preview.json'); preview_id = detail.pop('preview_id')
    if key(detail) != preview_id or result['preview_id'] != preview_id: raise Rejected('预览被修改')
    pricing = load(output/'technical/pricing-preview.json')
    if key(pricing) != detail['price_check_snapshot_hash']: raise Rejected('价格核验预览被修改')
    from native_copy.support import snapshot_root
    base = old_read(snapshot_root(output/'technical/base-compare'))
    if base['preview_id'] != detail['base_preview_id']: raise Rejected('基础预览绑定不一致')
    return dict(detail, preview_id=preview_id, pricing=pricing)
