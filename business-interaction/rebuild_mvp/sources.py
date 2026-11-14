"""Explicit, field-restricted sources; stream only the batch-relevant subset.

No SQLite release, network service or model is called here. Opening and known
derived-opening sources are rejected before opening their files.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import file_digest, sha256
import itertools
import json
from pathlib import Path
import re
import unicodedata

ROLES = {'business_summary', 'purchase_list', 'order_detail', 'purchase_order',
         'product_catalog', 'daily_material', 'product_card', 'prior_material',
         'reviewed_basics', 'completed_reference'}
PROCUREMENT = {'purchase_list', 'order_detail', 'purchase_order'}
EMPTY = {'', '0', '无', '未知', '待补', '待核', '未查到', '未找到', 'nan', 'none', 'null'}
FORBIDDEN_SOURCE_HASHES = frozenset({
    '68ba852202cd0ea21c30ae6e545f3da87030584bdbe3c5c598cb62e7a0c0db04',
    'bc27855f38ab97ed4b52d820a99a73b6812bfd00e8a026ea3d237ba55de98326',
    'eb3e31b28d01232f330a6601896db289efa7d789bf70eb8f313a703bf162f3b9',
    '44db76716140ac8aed7e79dd932db67315923b7f7bdce16ab823be7b1f2aabd8',
})


class SourceError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def norm(value):
    """Only Unicode/space normalization; no prefix stripping or fuzzy match."""
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or ''))).strip()


def code(value):
    text = norm(value)
    if text.lower() in EMPTY:
        return ''
    return re.sub(r'\.0$', '', text) if re.fullmatch(r'\d+\.0', text) else text


def known(value):
    return norm(value).lower() not in EMPTY and norm(value).upper() not in {
        '#N/A', '#VALUE!', '#REF!', '#DIV/0!', '#NAME?', '#NUM!', '#NULL!', '#SPILL!', '#CALC!'}


def header_key(value):
    return re.sub(r'[\s_（）()\-]+', '', norm(value)).lower()


ALIASES = {
    'code': ['jan code', 'jancode', 'JAN', 'JC', '商品编码', '条形码', 'ProductCode(JANCode)'],
    'pcs': ['pcs jan code', 'pcs jancode', 'pcs编码', 'PCS JAN', 'pcs jan'],
    'name': ['商品名称', '产品', '产品名称', '中文名称'],
    'ja': ['日文名称', '日文名', 'DescriptionofGoods'],
    'specification': ['规格', '颜色及规格', '商品规格'],
    'yd': ['YD编码', 'YD', 'yd code'],
    'sku': ['SKU关联编码', 'SKU编码', 'SKU'],
    'style_code': ['款式编码'],
    'sku_name': ['单品名称'],
    'category': ['品类'],
    'department': ['商品分类', '部门'],
    'material': ['材质', '产品材质', '补充材质'],
    'website_material': ['网站查找材质'],
    'material_reference': ['材质参考'],
    'channel': ['渠道商名称', '采购渠道', '渠道'],
    'price': ['单品报价', '采购单价', '采购单价日元', '采购单价（日元）'],
    'actual_price': ['实际单品报价'],
    'currency': ['货币类型', '币种'],
    'unit': ['计价单位', '报价单位', '采购单位'],
    'order_id': ['线上采购订单号', '采购订单号', '订单号'],
    'quote_id': ['单品渠道商报价id(不可修改)', '报价id'],
    'date': ['订单生成时间', '邮件日期'],
    'status': ['采购状态', '订单状态', '状态'],
    'cancelled': ['是否有砍单', '是否砍单'],
    'cancelled_qty': ['砍单数量', '砍单数'],
    'purchase_qty': ['渠道商本次采购数量', '本次采购数量'],
    'carton': ['CartonNo.', '箱号'],
    'origin': ['Origin'],
    'qty': ['Qty'],
    'accessories': ['产品配件', '配件', '配件数量'],
    'size': ['产品尺寸'],
    'material_scope': ['适用范围', '范围'],
    'pack_reference': ['盒规原文参考（人工判断）', '盒规原文参考'],
    'box_count': ['盒装数'],
    'box_size': ['盒规'],
    'blind': ['是否盲盒', '是否盲抽'],
    'total_pieces': ['总单个数（数量依据）'],
}

ALLOWED = {
    'business_summary': {'code', 'pcs', 'name', 'ja', 'specification', 'yd', 'category', 'material'},
    'purchase_list': {'code', 'pcs', 'name', 'ja', 'specification', 'yd', 'sku', 'sku_name', 'channel', 'price', 'actual_price', 'currency', 'unit', 'order_id', 'quote_id', 'date', 'status', 'department', 'purchase_qty'},
    'order_detail': {'code', 'pcs', 'name', 'ja', 'specification', 'yd', 'sku', 'sku_name', 'channel', 'price', 'currency', 'unit', 'order_id', 'date', 'status', 'department', 'cancelled', 'cancelled_qty', 'purchase_qty'},
    'purchase_order': {'channel', 'currency', 'order_id', 'date', 'status', 'cancelled'},
    'product_catalog': {'code', 'name', 'specification', 'style_code', 'sku', 'yd'},
    'daily_material': {'code', 'material'},
    'product_card': {'name', 'yd', 'material', 'material_scope', 'size', 'accessories'},
    'prior_material': {'code', 'ja', 'material', 'website_material', 'material_reference', 'carton', 'origin', 'qty'},
    # Explicit user-reviewed business source. Never inherit old price/channel.
    'reviewed_basics': {'code', 'ja', 'name', 'specification', 'material', 'website_material', 'material_reference', 'carton', 'origin', 'qty', 'category', 'pack_reference', 'box_size', 'blind', 'yd'},
    # User supplied completed material/reference workbook; its computed prices,
    # group-derived YD and channels do not become procurement facts.
    'completed_reference': {'code', 'ja', 'material', 'website_material', 'material_reference', 'carton', 'origin', 'qty', 'category', 'pack_reference', 'box_count', 'box_size', 'blind', 'total_pieces'},
}


def validate_source(config):
    role = config.get('role')
    label = ' '.join(str(config.get(k, '')) for k in ('path', 'role', 'lineage', 'derived_from', 'source_type'))
    if re.search(r'开[订定]|opening|preorder', label, re.I) or config.get('opening_derived'):
        raise SourceError('SOURCE_FORBIDDEN', '开订或明确由开订派生的来源禁止进入候选：' + str(config.get('path', '')))
    if role not in ROLES:
        raise SourceError('CONFIG_INVALID', '未许可的来源角色：' + str(role))
    if not Path(config.get('path', '')).is_file():
        raise SourceError('INPUT_INVALID', '来源文件不存在：' + str(config.get('path', '')))
    if config.get('sha256') in FORBIDDEN_SOURCE_HASHES:
        raise SourceError('SOURCE_FORBIDDEN', '来源为已登记排除的开订文件，改名也不允许采用')
    with Path(config['path']).open('rb') as handle:
        actual_hash = file_digest(handle, 'sha256').hexdigest()
    if actual_hash in FORBIDDEN_SOURCE_HASHES:
        raise SourceError('SOURCE_FORBIDDEN', '文件内容属于已登记排除的开订来源')
    if config.get('sha256') and actual_hash != config['sha256']:
        raise SourceError('SOURCE_CHANGED', '来源内容不符合已固定哈希：' + str(config['path']))


def _mapping(header, role, configured=None):
    result = {}
    for field in ALLOWED[role]:
        aliases = {header_key(v) for v in ALIASES.get(field, [])}
        columns = [c for c, value in header.items() if header_key(value) in aliases]
        if configured and field in configured:
            wanted = configured[field]
            wanted = wanted if isinstance(wanted, list) else [wanted]
            columns = []
            for name in wanted:
                if re.fullmatch('[A-Z]+', str(name)):
                    columns.append(str(name))
                else:
                    matches = [c for c, value in header.items() if str(value) == str(name)]
                    if len(matches) != 1:
                        raise SourceError('FIELD_MAPPING_AMBIGUOUS', f'字段{field}表头不唯一：{name}')
                    columns.extend(matches)
        if columns:
            result[field] = columns
    # Color-and-spec is explicitly more complete than a split spec field, and
    # remains the source's own field (never concatenate unverified identifiers).
    if role == 'product_catalog' and not (configured or {}).get('specification'):
        complete = [c for c, value in header.items() if header_key(value) == header_key('颜色及规格')]
        if len(complete) == 1:
            result['specification'] = complete
    return result


def _iter_sheet_rows(path, sheet_name, role):
    if Path(path).suffix.lower() == '.json':
        if role != 'product_card':
            raise SourceError('CONFIG_INVALID', 'JSON仅允许已登记产品卡快照')
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        for sheet in data['sheets']:
            if str(sheet.get('name', sheet.get('title', ''))) != sheet_name:
                continue
            for index, values in enumerate(sheet['data'], 1):
                yield {'row': index, 'values': {_col(i + 1): '' if v is None else str(v) for i, v in enumerate(values)}, 'types': {}, 'formulas': {}}
    else:
        from .xlsxio import iter_rows
        yield from iter_rows(path, sheet_name)


def _col(index):
    result = ''
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _sheet_names(path, role):
    if Path(path).suffix.lower() == '.json':
        d = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return [str(s.get('name', s.get('title', 'sheet' + str(i)))) for i, s in enumerate(d['sheets'])]
    from .xlsxio import sheet_info
    return [s['name'] for s in sheet_info(path)]


def _iter_records(config, meta, audit):
    role, path = config['role'], config['path']
    for sheet in _sheet_names(path, role):
        if config.get('sheets') and sheet not in config['sheets']:
            continue
        iterator = iter(_iter_sheet_rows(path, sheet, role))
        head = list(itertools.islice(iterator, 30))
        mapping, header_row = {}, None
        if role == 'daily_material':
            # Explicit audited headerless source mapping; not guessed elsewhere.
            mapping = {k: [v] if isinstance(v, str) else v for k, v in config.get('field_map', {'code': 'A', 'material': 'B'}).items() if k in ALLOWED[role]}
            header_row = int(config.get('header_row', 0))
        else:
            best = (-1, None, {})
            for row in head:
                candidate = _mapping(row['values'], role, config.get('field_map'))
                score = len(candidate)
                if score > best[0]:
                    best = (score, row['row'], candidate)
            if best[0] >= (2 if role != 'product_card' else 2):
                _, header_row, mapping = best
        if not mapping or header_row is None:
            audit['skipped_sheets'].append({'source_id': meta['source_id'], 'sheet': sheet, 'reason': 'header_not_identified'})
            continue
        audit['field_maps'].append({'source_id': meta['source_id'], 'sheet': sheet, 'header_row': header_row, 'fields': mapping})
        for row in itertools.chain(head, iterator):
            if row['row'] <= header_row:
                continue
            fields, columns, conflicts = {}, {}, {}
            for field, candidates in mapping.items():
                values = [(c, str(row['values'].get(c, '')).strip()) for c in candidates]
                values = [(c, v) for c, v in values if known(v)]
                if not values:
                    continue
                distinct = {}
                for c, value in values:
                    distinct.setdefault(norm(value), (c, value))
                if field == 'pcs':
                    fields[field] = [v for c, v in distinct.values()]
                    columns[field] = values[0][0]
                    continue
                if len(distinct) > 1:
                    conflicts[field] = [{'column': c, 'value': v} for c, v in values]
                    # Don't hide ambiguous duplicate headers in a single value.
                    continue
                columns[field], fields[field] = next(iter(distinct.values()))
            if not fields:
                continue
            if role == 'product_catalog' and fields.get('code'):
                # 商品编码 is retained as the export identifier, not asserted JAN.
                fields.setdefault('sku', fields['code'])
                columns.setdefault('sku', columns['code'])
            if role in {'purchase_list', 'order_detail'} and fields.get('sku') and (fields.get('actual_price') or fields.get('price')) and not fields.get('unit'):
                fields['unit'] = '采购SKU原计价单位'
                columns['unit'] = columns.get('actual_price', columns.get('price', ''))
            if role == 'business_summary' and fields.get('code') and re.search('[ぁ-ヿ一-龯]', fields['code']):
                fields['lookup_text'] = fields['code']
                columns['lookup_text'] = columns['code']
            yield {'source_id': meta['source_id'], 'source_sha256': meta['sha256'], 'role': role,
                   'sheet': sheet, 'row': row['row'], 'fields': fields, 'columns': columns,
                   'scope': {'source_version': meta.get('version'), 'priority': config.get('priority', 100),
                             'family': config.get('family', role), 'duplicate_field_conflicts': conflicts,
                             'pcs_source_cells': [{'column': c, 'value': str(row['values'].get(c, '')).strip()} for c in mapping.get('pcs', []) if known(row['values'].get(c))],
                             'unit_kind': 'source_sku_quote' if fields.get('unit') == '采购SKU原计价单位' else ('explicit' if fields.get('unit') else 'unknown'),
                             'packaging_unit': None,
                             'scope_evidence': {'field': 'actual_price' if fields.get('actual_price') else 'price', 'column': columns.get('actual_price', columns.get('price')), 'header': '实际单品报价' if fields.get('actual_price') else '单品报价'} if fields.get('unit') == '采购SKU原计价单位' else None}}


def _identity_keys(fields):
    codes = {code(fields.get(k)) for k in ('code', 'sku') if code(fields.get(k))}
    pcs = fields.get('pcs') or []
    if isinstance(pcs, str):
        pcs = [pcs]
    # Each explicit PCS cell can itself contain a delimited list. Do not split
    # arbitrary whitespace or extract digits from unrelated prose.
    pcs = [part for cell in pcs for part in re.split(r'[\n,，;；、]+', str(cell))]
    codes.update(code(v) for v in pcs if code(v))
    names = {norm(fields.get(k)) for k in ('ja', 'lookup_text') if known(fields.get(k))}
    return codes, names


def collect_sources(config, batch, progress=None):
    """Return restricted source metadata and only records linked to this batch.

    Two passes connect the initial code/name matches to exact SKU/YD/order IDs.
    A YD connection permits collecting candidates, not automatically adopting
    all its SKU values. match_batch separately enforces SKU identity.
    """
    if not isinstance(config, list):
        raise SourceError('CONFIG_INVALID', 'sources必须是列表')
    for item in config:
        validate_source(item)
    audit = {'skipped_sheets': [], 'field_maps': [], 'source_counts': [], 'duplicates': [],
             'excluded_fields': {'business_summary': ['channel', 'amount', 'qty'], 'product_card': ['channel', 'official_price']}}
    sources, by_role, seen = [], defaultdict(list), set()
    for item in config:
        path = Path(item['path'])
        with path.open('rb') as handle:
            digest = file_digest(handle, 'sha256').hexdigest()
        if digest in FORBIDDEN_SOURCE_HASHES:
            raise SourceError('SOURCE_FORBIDDEN', '文件内容属于已登记排除的开订来源')
        if item.get('sha256') and digest != item['sha256']:
            raise SourceError('SOURCE_CHANGED', '来源哈希变化：' + str(path))
        identity = (digest, item['role'])
        if identity in seen:
            audit['duplicates'].append({'path': str(path), 'sha256': digest, 'role': item['role']})
            continue
        seen.add(identity)
        meta = {'source_id': 'SRC-' + digest[:24] + '-' + item['role'], 'path': str(path.resolve()),
                'sha256': digest, 'role': item['role'], 'version': item.get('version', 'sha256:' + digest),
                'bytes': path.stat().st_size, 'allowed_fields': sorted(ALLOWED[item['role']])}
        sources.append(meta)
        by_role[item['role']].append((item, meta))
    seed_codes = {code(r['raw'].get('code')) for r in batch['rows'] if code(r['raw'].get('code'))}
    seed_names = {norm(r['raw'].get('ja')) for r in batch['rows'] if known(r['raw'].get('ja'))}
    connected_codes, yds, orders = set(seed_codes), set(), set()
    records, collected_ids = [], set()

    def scan(item, meta, include_related):
        scanned = kept = 0
        for record in _iter_records(item, meta, audit):
            scanned += 1
            fields = record['fields']; codes, names = _identity_keys(fields)
            relevant = bool(codes & connected_codes or names & seed_names)
            if include_related:
                relevant = relevant or bool(fields.get('yd') in yds or fields.get('order_id') in orders)
            if not relevant:
                continue
            record_id = (record['source_id'], record['sheet'], record['row'])
            if record_id not in collected_ids:
                record['record_id'] = sha256(json.dumps(record_id, ensure_ascii=False).encode()).hexdigest()[:32]
                records.append(record); collected_ids.add(record_id); kept += 1
            # Do not allow a YD-only hit to bootstrap arbitrary other SKU codes.
            if codes & connected_codes or names & seed_names:
                connected_codes.update(codes)
                if fields.get('yd'):
                    yds.add(fields['yd'])
                if fields.get('order_id'):
                    orders.add(fields['order_id'])
        audit['source_counts'].append({'source_id': meta['source_id'], 'scanned': scanned, 'new_kept': kept, 'pass': 2 if include_related else 1})
        if progress:
            progress({'source_id': meta['source_id'], 'role': meta['role'], 'scanned': scanned, 'kept': kept})

    # Purchase rows establish exact SKU links before large catalogue scans.
    order = ['business_summary', 'purchase_list', 'order_detail', 'product_catalog', 'daily_material', 'prior_material', 'reviewed_basics', 'completed_reference', 'product_card', 'purchase_order']
    for role in order:
        for item, meta in by_role[role]:
            scan(item, meta, role in {'product_catalog', 'product_card', 'purchase_order'})
    # Revisit small procurement sources for sibling candidate facts only. No
    # second 900k-row catalogue pass, and no entire-history DB migration.
    for role in ('purchase_list', 'order_detail', 'product_card', 'purchase_order'):
        for item, meta in by_role[role]:
            scan(item, meta, True)
    audit['field_maps'] = list({json.dumps(v, sort_keys=True): v for v in audit['field_maps']}.values())
    audit['connected'] = {'codes': len(connected_codes), 'yds': len(yds), 'orders': len(orders)}
    departments = sorted({r['fields']['department'] for r in records if r['role'] in PROCUREMENT and r['fields'].get('department')})
    audit['department_coverage'] = {'observed_labels': departments, 'requested_labels': ['手办部', '万代部'],
                                    'labels_not_observed_not_proof_of_no_product': [d for d in ('手办部', '万代部') if d not in departments],
                                    'model_department_is_not_bandai_department': True}
    return {'sources': sources, 'records': records, 'audit': audit}
