"""Pure deterministic, field-local matching with per-value source evidence."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

from .sources import norm, code, known, _identity_keys, PROCUREMENT, SourceError


def _ref(record, field):
    ref = {k: record[k] for k in ('source_id', 'source_sha256', 'role', 'sheet', 'row')}
    ref.update(column=record['columns'].get(field, ''), value=record['fields'].get(field, ''))
    ref['source_field'] = field
    ref['scope'] = deepcopy(record.get('scope', {}))
    return ref


def _issue(row, code_, field, message, candidates=None):
    item = {'code': code_, 'field': field, 'message': message}
    if candidates:
        item['candidates'] = candidates
    if item not in row['issues']:
        row['issues'].append(item)


def _rank(record):
    return int(record.get('scope', {}).get('priority', 100))


def _record_order(record):
    return (_rank(record), record['source_sha256'], record['sheet'], record['row'])


class _IdentityIndex:
    """Compute exact identity keys once, preserving original candidate order.

    Indices are row positions rather than record IDs: duplicate observations
    remain duplicate evidence just as in a linear scan. Unioning query paths
    returns each input occurrence once, without changing matching semantics.
    """
    def __init__(self, records):
        self.rows = list(records)
        self.codes, self.names = defaultdict(set), defaultdict(set)
        self.summary_codes, self.summary_pcs, self.summary_names = defaultdict(set), defaultdict(set), defaultdict(set)
        self.prior, self.yd = defaultdict(set), defaultdict(set)
        for position, record in enumerate(self.rows):
            fields = record['fields']
            keys, names = _identity_keys(fields)
            for key in keys:
                self.codes[key].add(position)
            for name in names:
                self.names[name].add(position)
            main = code(fields.get('code'))
            if main and not fields.get('lookup_text'):
                self.summary_codes[main].add(position)
            for key in _identity_keys({'pcs': fields.get('pcs')})[0]:
                self.summary_pcs[key].add(position)
            for field in ('lookup_text', 'ja'):
                name = norm(fields.get(field))
                if name:
                    self.summary_names[name].add(position)
            japanese = norm(fields.get('ja'))
            if main and japanese:
                self.prior[(main, japanese)].add(position)
            if fields.get('yd'):
                self.yd[fields['yd']].add(position)

    def select(self, positions):
        return [self.rows[position] for position in sorted(positions)]

    def linked(self, row, related_codes):
        positions = set(self.codes.get(code(row['raw'].get('code')), ()))
        positions.update(self.names.get(norm(row['raw'].get('ja')), ()))
        for related in related_codes:
            positions.update(self.codes.get(related, ()))
        return self.select(positions)


def _choose(row, target, records, source_field=None, *, prefer_source_priority=True, label=None):
    """Adopt a unique value only, not the first item in an arbitrary sequence."""
    if row['values'].get(target) not in (None, ''):
        return True
    source_field = source_field or target
    candidates = [r for r in records if known(r['fields'].get(source_field))]
    if not candidates:
        return False
    if prefer_source_priority:
        rank = min(_rank(r) for r in candidates)
        candidates = [r for r in candidates if _rank(r) == rank]
    groups = defaultdict(list)
    for record in sorted(candidates, key=_record_order):
        groups[norm(record['fields'][source_field])].append(record)
    if len(groups) != 1:
        _issue(row, 'FIELD_CONFLICT', target, (label or target) + '存在多个有据候选，未自动采用',
               [{'value': key, 'sources': [_ref(r, source_field) for r in group]} for key, group in sorted(groups.items())])
        return False
    group = next(iter(groups.values()))
    row['values'][target] = group[0]['fields'][source_field]
    row['evidence'][target] = [_ref(r, source_field) for r in group]
    return True


def _is_active(record):
    fields = record['fields']
    if record.get('scope', {}).get('order_header_blocked'):
        return False
    if re.search(r'取消|作废|已关闭|已砍单|cancel', norm(fields.get('status')), re.I):
        return False
    return True


def _order_scope(records, headers):
    """Actual order IDs only; never equate IDs with SKU or quote IDs."""
    by_id = defaultdict(list)
    for header in headers:
        if known(header['fields'].get('order_id')):
            by_id[header['fields']['order_id']].append(header)
    scoped, linked_headers = [], []
    for record in records:
        order_id = record['fields'].get('order_id')
        matches = by_id.get(order_id, [])
        if matches:
            rank = min(_rank(r) for r in matches)
            matches = [r for r in matches if _rank(r) == rank]
            record = deepcopy(record)
            scope = record.setdefault('scope', {})
            scope['order_header_evidence'] = [_ref(r, 'status') for r in matches if known(r['fields'].get('status'))]
            statuses = {norm(r['fields'].get('status')) for r in matches if known(r['fields'].get('status'))}
            scope['order_header_conflict'] = len(statuses) > 1
            scope['order_header_blocked'] = any(not _is_active(r) for r in matches)
            linked_headers.extend(matches)
        scoped.append(record)
    return scoped, list({(r['source_id'], r['sheet'], r['row']): r for r in linked_headers}.values())


def _price_eligible(record):
    if not _is_active(record):
        return False
    if record.get('scope', {}).get('order_header_conflict'):
        return False
    fields = record['fields']
    if norm(fields.get('cancelled')).lower() in {'是', 'true', '1', 'yes'}:
        try:
            ordered = Decimal(str(fields.get('purchase_qty', '')))
            cancelled = Decimal(str(fields.get('cancelled_qty', '')))
            if ordered <= 0 or cancelled >= ordered:
                return False
        except InvalidOperation:
            return False
    return bool(fields.get('unit') and _currency(fields.get('currency')))


def _currency(value):
    value = norm(value).upper()
    return {'日元': 'JPY', '人民币': 'CNY', '日币': 'JPY', 'RMB': 'CNY', 'JPY': 'JPY', 'CNY': 'CNY', 'USD': 'USD', '美元': 'USD'}.get(value)


def _latest_same_record(records):
    """Version precedence applies only to the same procurement fact identity."""
    groups = defaultdict(list)
    for record in records:
        f = record['fields']
        identity = f.get('quote_id') if record['role'] == 'purchase_list' else f.get('order_id')
        if identity:
            key = (record['role'], identity, f.get('sku'), f.get('code'), f.get('yd'), f.get('channel'), _currency(f.get('currency')))
        else:
            key = ('unversioned', record['source_id'], record['sheet'], record['row'])
        groups[key].append(record)
    result = []
    for group in groups.values():
        rank = min(_rank(r) for r in group)
        result.extend(r for r in group if _rank(r) == rank)
    return result


def _price(row, records, name_branch):
    original = _latest_same_record(records)
    records = [r for r in original if _price_eligible(r)]
    if name_branch:
        records = [r for r in records if _currency(r['fields'].get('currency')) == 'CNY']
    # Valid actual order quotation outranks an unbound purchase-list quote.
    actual_orders = [r for r in records if r['role'] == 'order_detail' and r['fields'].get('order_id') and known(r['fields'].get('price'))]
    if actual_orders:
        records = actual_orders
    groups = defaultdict(list)
    for record in records:
        field = 'actual_price' if known(record['fields'].get('actual_price')) else 'price'
        value = record['fields'].get(field)
        if not known(value):
            continue
        try:
            decimal = Decimal(str(value))
            if not decimal.is_finite() or decimal < 0:
                continue
        except InvalidOperation:
            continue
        fields = record['fields']
        key = (str(decimal.normalize()), _currency(fields.get('currency')), fields.get('unit'), fields.get('sku'), fields.get('channel'))
        groups[key].append((record, field))
    if not groups:
        if any(known(r['fields'].get('price')) or known(r['fields'].get('actual_price')) for r in original):
            _issue(row, 'PRICE_BASIS_MISSING', 'purchase_price', '采购报价缺明确币种或原计价依据')
        return
    # Distinct SKU aliases alone may coexist, but never hide price/channel/unit differences.
    values = defaultdict(list)
    for (value, currency, unit, sku, channel), pairs in groups.items():
        values[(value, currency, unit, channel)].extend(pairs)
    if len(values) != 1:
        _issue(row, 'PROCUREMENT_CONFLICT', 'purchase_price', '存在不同采购报价、币种、单位或渠道，未自动选价',
               [{'value': key[0], 'currency': key[1], 'unit': key[2], 'channel': key[3], 'sources': [_ref(r, f) for r, f in pairs]} for key, pairs in sorted(values.items())])
        return
    key, pairs = next(iter(values.items()))
    record, field = sorted(pairs, key=lambda pair: _record_order(pair[0]))[0]
    currency = key[1]
    row['values']['purchase_price'] = record['fields'][field] + ('元' if currency == 'CNY' else ('日元' if currency == 'JPY' else currency))
    row['evidence']['purchase_price'] = []
    for r, f in sorted(pairs, key=lambda pair: _record_order(pair[0])):
        ref = _ref(r, f)
        ref.update(currency=_currency(r['fields'].get('currency')), unit=r['fields'].get('unit'),
                   unit_kind=r.get('scope', {}).get('unit_kind', 'explicit'), packaging_unit=r.get('scope', {}).get('packaging_unit'))
        row['evidence']['purchase_price'].append(ref)


def _summary_matches(row, records):
    incoming = code(row['raw'].get('code'))
    japanese = norm(row['raw'].get('ja'))
    if isinstance(records, _IdentityIndex):
        for index, value, path in ((records.summary_codes, incoming, 'business_code'),
                                   (records.summary_pcs, incoming, 'business_pcs'),
                                   (records.summary_names, japanese, 'business_japanese_name')):
            if value and index.get(value):
                return records.select(index[value]), path
        return [], None
    direct = [r for r in records if incoming and code(r['fields'].get('code')) == incoming and not r['fields'].get('lookup_text')]
    if direct:
        return direct, 'business_code'
    pcs = [r for r in records if incoming and incoming in _identity_keys({'pcs': r['fields'].get('pcs')})[0]]
    if pcs:
        return pcs, 'business_pcs'
    names = [r for r in records if japanese and japanese in {norm(r['fields'].get('lookup_text')), norm(r['fields'].get('ja'))}]
    if names:
        return names, 'business_japanese_name'
    return [], None


def _linked(row, records, related_codes):
    if isinstance(records, _IdentityIndex):
        return records.linked(row, related_codes)
    incoming = code(row['raw'].get('code'))
    japanese = norm(row['raw'].get('ja'))
    exact = []
    for record in records:
        keys, names = _identity_keys(record['fields'])
        if (incoming and incoming in keys) or (japanese and japanese in names) or bool(keys & related_codes):
            exact.append(record)
    return exact


def _prior_material(row, records):
    incoming, japanese = code(row['raw'].get('code')), norm(row['raw'].get('ja'))
    if isinstance(records, _IdentityIndex):
        candidates = records.select(records.prior.get((incoming, japanese), ())) if incoming and japanese else []
    else:
        candidates = [r for r in records if incoming and code(r['fields'].get('code')) == incoming and japanese and norm(r['fields'].get('ja')) == japanese]
    # A blank/missing JP name is insufficient to transfer old declarations.
    for field in ('material', 'website_material', 'material_reference'):
        if _choose(row, field, candidates, prefer_source_priority=False, label='此前' + field):
            for ref in row['evidence'][field]:
                ref['scope']['adoption_kind'] = 'inherited_user_authorized_material'
                ref['scope']['authority'] = '2026-11-14 user: supplied partial material workbook; carry reliably matched material only'


def match_batch(batch, collected, policy=None):
    """Return copies in original order, with no model or side effects."""
    default_policy = json.loads(Path(__file__).with_name('policy.json').read_text(encoding='utf-8'))
    if policy is not None and policy != default_policy:
        raise SourceError('CONFIG_INVALID', '本MVP只接受已版本化的固定匹配规则，不接受调用方临时覆盖')
    records = sorted(collected['records'], key=_record_order)
    forbidden = [r for r in records if r['role'] not in {'business_summary', 'purchase_list', 'order_detail', 'purchase_order', 'product_catalog', 'daily_material', 'product_card', 'prior_material'}]
    if forbidden:
        raise SourceError('SOURCE_FORBIDDEN', '匹配候选含未许可来源')
    by_role = defaultdict(list)
    for record in records:
        by_role[record['role']].append(record)
    summary_index = _IdentityIndex(by_role['business_summary'])
    procurement_index = _IdentityIndex(sorted(by_role['purchase_list'] + by_role['order_detail'], key=_record_order))
    catalogue_index = _IdentityIndex(by_role['product_catalog'])
    daily_index = _IdentityIndex(by_role['daily_material'])
    prior_index = _IdentityIndex(by_role['prior_material'])
    card_index = _IdentityIndex(by_role['product_card'])
    result = []
    for source_row in batch['rows']:
        row = deepcopy(source_row)
        # Always rematch nonmaterial fields. Do not accidentally preserve stale
        # automatic outputs if a caller passes already matched rows to resume.
        extraction_issues = [deepcopy(issue) for issue in source_row.get('issues', [])
                             if issue.get('code') in {'CARTON_MISSING', 'QUANTITY_MISSING'}]
        row['values'], row['evidence'], row['issues'] = {}, {}, extraction_issues
        incoming = code(row['raw'].get('code'))
        if incoming and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.\-/]*', incoming):
            row['values']['jc'] = incoming
            raw_source = batch.get('source', {})
            row['evidence']['jc'] = [{'source_id': raw_source.get('source_id', 'batch'), 'source_sha256': raw_source.get('sha256'), 'role': 'japanese_batch', 'sheet': row.get('sheet', batch.get('sheet')), 'row': row['source_row'], 'column': row.get('raw_cells', {}).get('code', {}).get('column', ''), 'value': incoming}]
        summary, path = _summary_matches(row, summary_index)
        # Latest maintained summary may fill an older missing field. Priority
        # is explicitly configured, never inferred from filesystem timestamps.
        if summary:
            for target in ('name', 'specification', 'category', 'yd'):
                _choose(row, target, summary)
        related_codes = set()
        for record in summary:
            related_codes.update(_identity_keys(record['fields'])[0])
        procurement = _linked(row, procurement_index, related_codes)
        # A direct barcode purchase-list establishes an explicit SKU link to
        # order details; do not bootstrap arbitrary sibling SKU from YD alone.
        for record in procurement:
            related_codes.update(_identity_keys(record['fields'])[0])
        procurement = _latest_same_record(_linked(row, procurement_index, related_codes))
        procurement, order_headers = _order_scope(procurement, by_role['purchase_order'])
        active = [r for r in procurement if _is_active(r)]
        if not path and active:
            path = 'procurement_identity'
        if active:
            if not row['values'].get('name') and not any(i['field'] == 'name' for i in row['issues']):
                _choose(row, 'name', active, prefer_source_priority=False)
            _choose(row, 'yd', active, prefer_source_priority=False)
            active_orders = {r['fields'].get('order_id') for r in active if r['fields'].get('order_id')}
            matching_headers = [r for r in order_headers if r['fields'].get('order_id') in active_orders and _is_active(r)]
            _choose(row, 'channel', active + matching_headers, prefer_source_priority=False)
            _price(row, active, path == 'business_japanese_name')
            if any(r.get('scope', {}).get('order_header_conflict') for r in active):
                _issue(row, 'ORDER_STATUS_CONFLICT', 'purchase_price', '同一订单存在状态冲突，相关报价未自动采用')
        # Catalogues supply SKU specification only via exact aliases, never
        # every variant belonging to a product-group YD.
        catalogues = _linked(row, catalogue_index, related_codes)
        if not row['values'].get('name') and not any(i['field'] == 'name' for i in row['issues']):
            _choose(row, 'name', catalogues)
        if not row['values'].get('specification') and not any(i['field'] == 'specification' for i in row['issues']):
            if not _choose(row, 'specification', catalogues):
                # 单品名称 is only a potential specification when it is not an
                # order label; retain exact original wording, no tail parsing.
                explicit = [r for r in active if known(r['fields'].get('specification'))]
                _choose(row, 'specification', explicit, prefer_source_priority=False)
        _prior_material(row, prior_index)
        if not row['values'].get('material_reference') and not any(i['field'] == 'material_reference' for i in row['issues']):
            if not _choose(row, 'material_reference', summary, 'material'):
                daily = _linked(row, daily_index, related_codes)
                _choose(row, 'material_reference', daily, 'material', prefer_source_priority=False)
        yd = row['values'].get('yd')
        cards = card_index.select(card_index.yd.get(yd, ())) if yd else []
        if not row['values'].get('material_reference') and not any(i['field'] == 'material_reference' for i in row['issues']):
            # Group-level product-card material is reference only, full text;
            # no split/classification into the declaration material column O.
            if _choose(row, 'material_reference', cards, 'material', prefer_source_priority=False):
                for ref in row['evidence']['material_reference']:
                    ref['scope']['adoption_scope'] = 'yd_collection_reference'
        if not path:
            _issue(row, 'PRODUCT_UNMATCHED', 'identity', '主编码、PCS及日文名未取得可靠商品对应；保留人工判断')
        for field, message in (('name', '商品名称'), ('specification', '完整规格'), ('yd', 'YD'), ('channel', '实际采购渠道')):
            if not row['values'].get(field) and not any(i['field'] == field for i in row['issues']):
                _issue(row, 'FIELD_MISSING', field, message + '未取得可靠来源，其他字段继续处理')
        matching_field = 'pcs' if path == 'business_pcs' else ('lookup_text' if path == 'business_japanese_name' else 'code')
        row['matching'] = {'path': path or 'unresolved', 'model_inference': False, 'policy_version': default_policy['version'],
                           'basis': [_ref(r, matching_field) for r in summary]}
        result.append(row)
    return result
