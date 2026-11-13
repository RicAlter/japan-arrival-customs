"""Named headers plus approved blank anchors; never select by batch name."""
from pathlib import Path
from .support import Rejected, digest, key

HEADERS = {'carton': 'CartonNo.', 'origin': 'Origin', 'code': 'ProductCode(JANCode)',
           'ja': 'DescriptionofGoods', 'single_price': '单个价', 'multiple': '倍数',
           'single_qty': '单个数', 'qty': 'Qty', 'price': 'UnitPrice(日本JPY)',
           'amount': 'Subtotal', 'material': '材质', 'channel': '渠道', 'yd': 'YD', 'note': '备注'}
COLUMNS = dict(zip(HEADERS, ('A', 'B', 'C', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'Q', 'R', 'S', 'T')))
ANCHORS = {'D': ('', 'JC'), 'E': ('', '商品名称', '中文名'), 'F': ('', '规格'),
           'G': ('', '采购单价'), 'H': ('', '盒规'), 'P': ('', '品类'),
           'U': ('', '价差', '价格验算'), 'V': ('', '取整单价')}
EXTRA_ROLES = {'jc': 'D', 'internal': 'E', 'variant': 'F', 'lookup_price': 'G',
               'lookup_ratio': 'H', 'category': 'P', 'price_difference': 'U', 'rounded_price': 'V'}


def inspect_source(path):
    from arrival_core import _p0_frozen as p0
    from arrival_core.core import new_row, new_batch
    from arrival_core.operations_adapter import locate
    from native_copy.profiles import inspect_source as old_inspect
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() != '.xlsx': raise Rejected('仅接受已验证xlsx格式')
    data = path.read_bytes(); book = p0.Book(data, str(path)); sheet = book.sheets[0]
    config = {'headers': HEADERS, 'columns': COLUMNS, 'anchored_blank_headers': []}
    named = locate(sheet, config)
    if named is None:
        return old_inspect(path)
    # Unnamed fields are recognized only under these complete, fixed named anchors.
    if named != COLUMNS or any(p0.text(sheet.v(1, c)).strip() not in labels for c, labels in ANCHORS.items()):
        raise Rejected('22列锚点与已验证布局不一致，不能猜未命名列')
    from openpyxl.utils.cell import column_index_from_string
    if any(p0.present(cell.get('v')) for a, cell in sheet.cells.items()
           if a == a.rstrip('0123456789')+'1' and column_index_from_string(a.rstrip('0123456789')) > 22):
        raise Rejected('22列表头外有未知字段')
    columns = dict(named, **EXTRA_ROLES); rows = []; carry = None
    for ri in sorted(sheet.rows):
        if ri < 2: continue
        if p0.present(sheet.v(ri, columns['carton'])): carry = sheet.v(ri, columns['carton'])
        if not any(p0.present(sheet.v(ri, columns[k])) for k in ('code', 'ja')): continue
        if not any(p0.present(sheet.v(ri, columns[k])) for k in ('qty', 'amount')): continue
        cells = {role: {'cell': col+str(ri), 'value': p0.text(sheet.v(ri, col)),
                        'formula': sheet.f(ri, col), 'type': sheet.cells.get(col+str(ri), {}).get('type')}
                 for role, col in columns.items()}
        source = {'path': str(path), 'sha256': book.sha256, 'sheet': sheet.name, 'row': ri,
                  'stage': 3, 'template': 'kmt-native-22-v1', 'cells': cells}
        raw = {role: p0.text(sheet.v(ri, col)) if sheet.v(ri, col) is not None else None
               for role, col in columns.items()}
        raw['carton'] = raw['carton'] or p0.text(carry)
        row = new_row(source, raw, currency='JPY', quantity_unit='',
                      authority_status='a22_unconfirmed_source_observation', amount_basis='provided_workbook_subtotal')
        row['arrival']['quantity_meaning'] = 'unconfirmed_source_observation'
        row['identity']['code_type'] = 'source_identifier' if row['identity']['code'] else 'absent_not_fabricated'
        rows.append(row)
    if not rows: raise Rejected('22列表未发现商品行')
    weights = [s.name for s in book.sheets if s.name in ('重さとサイズ', '重さとサイズ (2)')]
    if not weights: raise Rejected('缺少已验证箱重页')
    manifest = [{'path': str(path), 'sha256': book.sha256, 'stage': 3, 'kind': 'kmt-native-22-v1'}]
    batch = new_batch(rows, manifest)
    batch.update(input_mode='a22_native_copy', execution_mode='preliminary_untrusted',
                 product_data_policy='single-person-v1', source_qualification='provided_business_workbook_not_certified_pure_raw')
    if digest(path) != book.sha256: raise Rejected('读取期间原件变化')
    return {'path': str(path), 'bytes': data, 'book': book, 'sheet': sheet, 'profile_id': 'kmt-native-22-v1',
            'header_row': 1, 'targets': {'internal_name': 'E', 'specification': 'F', 'purchase_unit_price': 'G',
                                      'pieces_per_box': 'H', 'category': named.get('category', 'P'),
                                      'material_reference': named['material'], 'channel': named['channel'], 'yd': named['yd']},
            'columns': columns, 'batch': batch, 'weights': weights,
            'rows': [{'row_id': r['id'], 'source_row': r['source']['row'], 'code': r['identity']['code'],
                      'japanese_name': r['identity']['japanese_name'], 'source': r['source']} for r in rows],
            'row_map_hash': key([{'id': r['id'], 'source': r['source']} for r in rows])}
