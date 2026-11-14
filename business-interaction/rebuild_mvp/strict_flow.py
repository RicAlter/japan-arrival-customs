"""User-prescribed source flow; no cross-source substitution of main fields.

Source field names are assigned by audited business semantics, including the
business-maintained order summary's misleading legacy header labels.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from .sources import code, norm, known, _identity_keys, SourceError
from .matching import (_IdentityIndex, _summary_matches, _linked, _choose, _price,
                       _ref, _issue, _record_order, _latest_same_record,
                       _order_scope, _is_active, _prior_material, _sku_specification)
from .reviewed import enrich_reviewed, reviewed_index, _same_row

MAIN_FIELDS = {'name': 'name', 'specification': 'specification',
               'purchase_price': 'price', 'channel': 'channel'}
DEPARTMENTS = {'手办部', '万代部'}
PERMITTED = {'business_summary', 'purchase_list', 'order_detail', 'purchase_order',
             'product_catalog', 'daily_material', 'product_card', 'prior_material',
             'reviewed_basics', 'completed_reference'}


def _priority(record):
    return int(record.get('scope', {}).get('priority', 100))


def _best_main_group(row, records, reviewed):
    """Use an explicit source version, then an exact reviewed SKU descriptor.

    No quantity or price ratio selects a source record. Reviewed values apply
    only when their own code/JP identity and same shipment scope were verified.
    """
    if not records:
        return [], None
    confirmed_specs = {norm(record['fields'].get('specification')) for record in reviewed
                       if record['role'] == 'reviewed_basics' and _same_row(row, record)
                       and known(record['fields'].get('specification'))}
    if len(confirmed_specs) == 1:
        exact = [record for record in records if norm(record['fields'].get('specification')) in confirmed_specs]
        if exact:
            best = min(_priority(record) for record in exact)
            return [record for record in exact if _priority(record) == best], {
                'kind': 'exact_reviewed_specification', 'value': next(iter(confirmed_specs)),
                'source_priority': best}
    best = min(_priority(record) for record in records)
    group = [record for record in records if _priority(record) == best]
    if len(confirmed_specs) == 1:
        if any(known(record['fields'].get('specification')) for record in group):
            _issue(row, 'MAIN_REVIEWED_SPEC_CONFLICT', 'specification',
                   '主表候选规格与本出荷行已有确认规格不同；保留人工值，不按数量或价格猜行',
                   [{'value': record['fields'].get('specification'), 'source': _ref(record, 'specification')} for record in group])
    return group, None


def _common_main_field(row, target, records, field=None):
    """Only values present and equal on every selected main-row candidate.

    Missing cells are not filled from other source rows to form a tuple which
    does not exist in any source record. Each adopted common value has source
    coordinates for all selected records.
    """
    field = field or MAIN_FIELDS[target]
    if row['values'].get(target) not in (None, ''):
        row.setdefault('main_candidates_for_confirmed_fields', {})[target] = {
            'preserved_value': row['values'][target],
            'preserved_evidence': deepcopy(row['evidence'].get(target, [])),
            'candidates': [_ref(record, field) for record in records],
            'automatic_override': False}
        return
    if any(issue.get('field') == target and issue.get('code') == 'REVIEWED_FIELD_CONFLICT' for issue in row['issues']):
        return
    supplied = [record for record in records if known(record['fields'].get(field)) or
                (target == 'purchase_price' and str(record['fields'].get(field, '')).strip() in {'0', '0.0', '0.00'})]
    if not supplied:
        _issue(row, 'FIELD_MISSING', target, '已命中主表，但该字段缺失；不换来源覆盖此匹配路径')
        return
    distinct = {norm(record['fields'][field]) for record in supplied}
    if len(distinct) != 1 or len(supplied) != len(records):
        _issue(row, 'FIELD_CONFLICT' if len(distinct) > 1 else 'MAIN_RECORD_PARTIAL', target,
               '同优先版本主表存在不同值或缺项，仅保留共同一致字段，未跨记录拼接',
               [{'value': record['fields'].get(field, ''), 'source': _ref(record, field)} for record in records])
        return
    if target == 'purchase_price':
        try:
            if any(not Decimal(str(record['fields'][field])).is_finite() or Decimal(str(record['fields'][field])) < 0 for record in records):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            _issue(row, 'PRICE_BASIS_MISSING', target, '主表日元采购价不是有效数值，原文保留后台')
            return
        if any(norm(record['fields'].get('currency')).upper() not in {'JPY', '日元', '日币'} for record in records):
            _issue(row, 'PRICE_BASIS_MISSING', target, '主表采购价未登记为日元，不采用其他采购报价替换')
            return
        row['values'][target] = str(records[0]['fields'][field]) + '日元'
    else:
        row['values'][target] = records[0]['fields'][field]
    row['evidence'][target] = [_ref(record, field) for record in records]
    for ref, record in zip(row['evidence'][target], records):
        ref['scope']['adoption_kind'] = 'business_summary_same_record_group'
        if target == 'purchase_price':
            ref.update(currency='JPY', unit=record['fields'].get('unit'),
                       unit_kind='business_summary_original_sku_quote', packaging_unit=None)


def _department(record, policy):
    fields, scope = record['fields'], record.get('scope', {})
    aliases = policy.get('department_aliases', {})
    def canonical(label):
        label = norm(label)
        return aliases.get(label, label)
    direct = norm(fields.get('department'))
    if direct:
        mapped = canonical(direct)
        return mapped if mapped in DEPARTMENTS else None
    evidence = scope.get('department_evidence') or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    labels = {canonical(ref.get('value', ref.get('department', ''))) for ref in evidence if isinstance(ref, dict)}
    labels.discard('')
    return next(iter(labels)) if len(labels) == 1 and labels <= DEPARTMENTS else None


def _department_candidates(records, policy):
    return [record for record in records
            if record['role'] in {'purchase_list', 'order_detail'} and _department(record, policy) in DEPARTMENTS]


def _candidate_note(record, reason):
    return {'role': record['role'], 'source_id': record['source_id'],
            'source_sha256': record['source_sha256'], 'sheet': record['sheet'], 'row': record['row'],
            'reason': reason, 'fields': deepcopy(record['fields']), 'scope': deepcopy(record.get('scope', {}))}


def _procurement_fields(row, records, headers):
    """Only explicitly identified hand-figure/Bandai department fallback."""
    _choose(row, 'name', records, prefer_source_priority=False)
    _choose(row, 'channel', records, prefer_source_priority=False)
    if not row['values'].get('channel') and not any(issue.get('field') == 'channel' for issue in row['issues']):
        order_ids = {record['fields']['order_id'] for record in records if known(record['fields'].get('order_id'))}
        matching_headers = [header for header in headers if header['fields'].get('order_id') in order_ids and _is_active(header)]
        _choose(row, 'channel', matching_headers, prefer_source_priority=False)
    if not _choose(row, 'specification', records, prefer_source_priority=False):
        if not any(issue.get('field') == 'specification' for issue in row['issues']):
            descriptors = [record for record in records if _sku_specification(record)]
            if _choose(row, 'specification', descriptors, 'sku_name', prefer_source_priority=False):
                for ref in row['evidence']['specification']:
                    ref['scope']['adoption_kind'] = 'department_procurement_sku_name_original_specification'
                    ref['scope']['quantity_conversion_performed'] = False
    if not row['values'].get('purchase_price'):
        _price(row, records, False)


def run_strict(batch, collected, policy):
    """Match in the prescribed order; preserve authorized reviewed values."""
    records = sorted(collected['records'], key=_record_order)
    if any(record['role'] not in PERMITTED for record in records):
        raise SourceError('SOURCE_FORBIDDEN', '严格匹配候选含未许可来源')
    by_role = defaultdict(list)
    for record in records:
        by_role[record['role']].append(record)
    summary_index = _IdentityIndex(by_role['business_summary'])
    # The business main lookup field contains both codes and Japanese/English
    # product titles. Third-step exact-name search must include ASCII titles.
    for position, record in enumerate(summary_index.rows):
        lookup = norm(record['fields'].get('code'))
        if lookup:
            summary_index.summary_names[lookup].add(position)
        if lookup and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.\-/]*', lookup):
            summary_index.summary_codes[code(lookup)].discard(position)
    procurement_index = _IdentityIndex(sorted(by_role['purchase_list'] + by_role['order_detail'], key=_record_order))
    catalog_index = _IdentityIndex(by_role['product_catalog'])
    daily_index = _IdentityIndex(by_role['daily_material'])
    prior_index = _IdentityIndex(by_role['prior_material'])
    cards_index = _IdentityIndex(by_role['product_card'])
    reviewed = reviewed_index(by_role['reviewed_basics'] + by_role['completed_reference'])
    result = []
    for original in batch['rows']:
        row = deepcopy(original)
        row['values'], row['evidence'] = {}, {}
        row['issues'] = [deepcopy(issue) for issue in original.get('issues', [])
                         if issue.get('code') in {'CARTON_MISSING', 'QUANTITY_MISSING'}]
        raw = row['raw']; incoming = code(raw.get('code')); japanese = norm(raw.get('ja'))
        if incoming and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.\-/]*', incoming):
            row['values']['jc'] = incoming
            source = batch.get('source', {})
            row['evidence']['jc'] = [{'source_id': source.get('source_id', 'batch'), 'source_sha256': source.get('sha256'),
                                    'role': 'japanese_batch', 'sheet': row.get('sheet', batch.get('sheet')),
                                    'row': row['source_row'], 'column': row.get('raw_cells', {}).get('code', {}).get('column', ''), 'value': incoming}]
        existing = reviewed.get((incoming, japanese), [])
        enrich_reviewed(row, existing, preserve_confirmed=True)
        matches, path = _summary_matches(row, summary_index)
        main, selection = _best_main_group(row, matches, existing)
        if matches:
            selected = {(record['source_id'], record['sheet'], record['row']) for record in main}
            row['master_candidates'] = [
                {'source_id': record['source_id'], 'source_sha256': record['source_sha256'],
                 'sheet': record['sheet'], 'row': record['row'],
                 'selected': (record['source_id'], record['sheet'], record['row']) in selected,
                 'scope': deepcopy(record.get('scope', {})),
                 'fields': {field: record['fields'].get(field, '') for field in MAIN_FIELDS.values()},
                 'evidence': {target: _ref(record, field) for target, field in MAIN_FIELDS.items()}}
                for record in matches]
        # Only the selected main source rows may create cross-code linkage.
        related_codes = set()
        for record in main:
            related_codes.update(_identity_keys(record['fields'])[0])
        procurement = _linked(row, procurement_index, related_codes)
        for record in procurement:
            related_codes.update(_identity_keys(record['fields'])[0])
        procurement = _latest_same_record(_linked(row, procurement_index, related_codes))
        procurement, headers = _order_scope(procurement, by_role['purchase_order'])
        active = [record for record in procurement if _is_active(record)]
        # YD is auxiliary and cannot change the selected four-field main tuple.
        _choose(row, 'yd', active, prefer_source_priority=False)
        if main:
            for field in ('name', 'specification', 'channel'):
                _common_main_field(row, field, main)
            if path == 'business_japanese_name':
                if not row['values'].get('purchase_price'):
                    lists = [record for record in active if record['role'] == 'purchase_list']
                    _price(row, lists, True)
                    if not row['values'].get('purchase_price') and not any(issue.get('field') == 'purchase_price' for issue in row['issues']):
                        _issue(row, 'FIELD_MISSING', 'purchase_price', '日文名路径仅取采购清单对应人民币报价，当前缺明确可用记录')
                else:
                    row.setdefault('main_candidates_for_confirmed_fields', {})['purchase_price'] = {
                        'preserved_value': row['values']['purchase_price'],
                        'preserved_evidence': deepcopy(row['evidence'].get('purchase_price', [])),
                        'candidates': [_ref(record, 'actual_price' if known(record['fields'].get('actual_price')) else 'price')
                                       for record in active if record['role'] == 'purchase_list'
                                       and norm(record['fields'].get('currency')).upper() in {'CNY', '人民币', 'RMB'}],
                        'automatic_override': False}
            else:
                _common_main_field(row, 'purchase_price', main)
        else:
            eligible = _department_candidates(active, policy)
            if eligible:
                _procurement_fields(row, eligible, headers)
                path = 'department_procurement'
            elif any(ref.get('role') == 'reviewed_basics' for ref in row['evidence'].get('name', [])):
                path = 'reviewed_identity'
            else:
                path = 'unresolved'
                _issue(row, 'PRODUCT_UNMATCHED', 'identity',
                       '主表主码、PCS、日文名及明确手办部/万代部采购均无确定对应，交用户判断')
            if active and not eligible:
                _issue(row, 'DEPARTMENT_SCOPE_MISSING', 'identity',
                       '采购候选仅见其他部门或部门依据不足，不能当手办部/万代部自动采用')
        # Other sources are visible as evidence candidates, never substituted
        # into main four-field matches or an unapproved department branch.
        catalogues = _linked(row, catalog_index, related_codes)
        if catalogues or (not main and active):
            row['unadopted_candidates'] = [_candidate_note(record, 'catalogue_reference_not_prescribed_identity_path') for record in catalogues]
            if not main:
                row['unadopted_candidates'].extend(_candidate_note(record, 'department_not_confirmed_or_not_authorized') for record in active if record not in _department_candidates(active, policy))
        _prior_material(row, prior_index)
        if not row['values'].get('material_reference') and not any(issue.get('field') == 'material_reference' for issue in row['issues']):
            if not _choose(row, 'material_reference', main, 'material', prefer_source_priority=False):
                daily = _linked(row, daily_index, related_codes)
                _choose(row, 'material_reference', daily, 'material', prefer_source_priority=False)
        yd = row['values'].get('yd')
        cards = cards_index.select(cards_index.yd.get(yd, ())) if yd else []
        if not row['values'].get('material_reference') and not any(issue.get('field') == 'material_reference' for issue in row['issues']):
            if _choose(row, 'material_reference', cards, 'material', prefer_source_priority=False):
                for ref in row['evidence']['material_reference']:
                    ref['scope']['adoption_scope'] = 'yd_collection_reference'
        for target, label in (('name', '商品名称'), ('specification', '规格'), ('purchase_price', '采购价'), ('channel', '渠道'), ('yd', 'YD')):
            if not row['values'].get(target) and not any(issue.get('field') == target for issue in row['issues']):
                _issue(row, 'FIELD_MISSING', target, label + '缺失或待用户判断；其他可靠字段继续处理')
        matching_field = 'pcs' if path == 'business_pcs' else 'code'
        basis = []
        for record in main:
            field = matching_field
            if path == 'business_japanese_name':
                field = 'lookup_text' if known(record['fields'].get('lookup_text')) else (
                    'ja' if norm(record['fields'].get('ja')) == japanese else 'code')
            basis.append(_ref(record, field))
        if path == 'department_procurement':
            basis = [_ref(record, 'department') for record in _department_candidates(active, policy)]
            for ref, record in zip(basis, _department_candidates(active, policy)):
                canonical = _department(record, policy)
                ref['scope']['canonical_department'] = canonical
                if norm(record['fields'].get('department')) == '模型部' and canonical == '万代部':
                    ref['scope']['department_alias_authority'] = '2026-11-14 user explicitly confirmed: 万代就是模型部'
        if path == 'reviewed_identity':
            basis = deepcopy(row['evidence'].get('name', []))
        row['matching'] = {'path': path or 'unresolved', 'basis': basis,
                           'record_selection': selection, 'policy_version': policy['version'], 'model_inference': False}
        result.append(row)
    return result
