"""Only observed header contracts; batch names do not select templates."""
from pathlib import Path
from .support import Rejected, digest, key

HEADERS16 = ['CartonNo.', 'Origin', 'ProductCode(JANCode)', 'JC', '商品名称', '规格',
             '采购单价', '盒规', 'DescriptionofGoods', 'Qty', 'UnitPrice(日本JPY)',
             'Subtotal', '品类', '材质', '渠道', 'YD']
LABELS = {'商品名称': 'internal_name', '中文名': 'internal_name', '规格': 'specification',
          '品类': 'category', '材质': 'material_reference', '渠道': 'channel',
          'YD': 'yd', 'yd': 'yd', '盒规': 'pieces_per_box', '采购单价': 'purchase_unit_price'}


def inspect_source(path):
    from arrival_core import _p0_frozen as p0
    from arrival_core.importer import raw_invoice_layout, import_raw_invoice, import_stage3
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() != '.xlsx':
        raise Rejected('本阶段仅支持已验证的xlsx格式')
    data = path.read_bytes()
    book = p0.Book(data, str(path))
    raw = raw_invoice_layout(book)
    if raw:
        sheet, layout = raw
        profile = layout['id']; header_row = 17
        protected = set(layout['columns'].values())
        batch = import_raw_invoice(path)
        targets = {}
        for address, cell in sheet.cells.items():
            col = address.rstrip('0123456789')
            if address == col + '17' and p0.text(cell['v']) in LABELS and col not in protected:
                field = LABELS[p0.text(cell['v'])]
                if field in targets:
                    raise Rejected('重复业务表头，不能猜补填列')
                targets[field] = col
        if profile == 'kmt-raw-invoice-v2':
            # Frozen P0 CONFIG[1] has these anchored business slots. No new columns.
            for field, col in [('internal_name', 'F'), ('specification', 'G')]:
                if sheet.v(17, col) not in (None, ''):
                    raise Rejected('原表F/G锚点表头与已验证映射不兼容')
                targets[field] = col
    else:
        sheet = book.sheets[0]
        observed = [p0.text(sheet.v(1, chr(65 + n))) for n in range(16)]
        exact = observed == HEADERS16
        legacy = all(p0.clean(sheet.v(1, col)) == label for col, label in {
            'A': 'CartonNo.', 'B': 'Origin', 'C': 'ProductCode(JANCode)',
            'I': 'DescriptionofGoods', 'J': 'Qty', 'K': 'UnitPrice(日本JPY)',
            'L': 'Subtotal', 'M': '品类', 'N': '材质', 'O': '渠道'}.items())
        legacy = legacy and p0.text(sheet.v(1, 'P')) in ('YD', 'yd')
        legacy = legacy and all(sheet.v(1, c) in (None, '') for c in ('D', 'E', 'F', 'G', 'H'))
        if not (exact or legacy):
            raise Rejected('不匹配已验证的KMT原表/16列业务底稿格式；不自动猜列')
        if any(p0.present(c['v']) for a, c in sheet.cells.items()
               if a.endswith('1') and a.rstrip('0123456789') not in [chr(65 + n) for n in range(16)]
               and a == a.rstrip('0123456789') + '1'):
            raise Rejected('16列表头外有未知字段，不静默兼容其他成品布局')
        profile = 'kmt-native-16-v1' if exact else 'kmt-stage3-native-v1'
        header_row = 1
        targets = {'internal_name': 'E', 'specification': 'F', 'category': 'M',
                   'material_reference': 'N', 'channel': 'O', 'yd': 'P'}
        if exact:
            targets.update(pieces_per_box='H', purchase_unit_price='G')
        batch = import_stage3(path, currency='JPY', quantity_unit='')
        # This task certifies neither pure warehouse origin nor earlier approvals.
        for row in batch['rows']:
            # Stage 3 is the observed column mapping, not an approval. A supplied
            # business Subtotal must not be relabelled a Japanese retail amount.
            row['authority'].update(status='a01_unconfirmed_source_observation', amount_basis='provided_workbook_subtotal')
        batch['source_qualification'] = 'provided_workbook_with_existing_business_fields_not_certified_pure_raw'
    if not batch['rows']:
        raise Rejected('未发现可登记的商品行')
    weights = [s.name for s in book.sheets if s.name in ('重さとサイズ', '重さとサイズ (2)')]
    if not weights:
        raise Rejected('缺少已验证的内嵌箱重工作表；本阶段不猜外部附件关系')
    batch['input_mode'] = 'a01_native_copy'
    batch['execution_mode'] = 'preliminary_untrusted'
    batch['product_data_policy'] = 'single-person-v1'
    for row in batch['rows']:
        row['arrival']['quantity_meaning'] = 'unconfirmed_source_observation'
        row['arrival']['unit_raw'] = ''
        row['arrival']['unit_status'] = 'pending_product_or_purchase_lookup'
        row['reviews'] = {k: None for k in row['reviews']}
    if digest(path) != book.sha256:
        raise Rejected('原件在读取期间变化')
    return {'path': str(path), 'bytes': data, 'book': book, 'sheet': sheet,
            'profile_id': profile, 'header_row': header_row, 'targets': targets,
            'batch': batch, 'weights': weights,
            'rows': [{'row_id': row['id'], 'source_row': row['source']['row'],
                      'code': row['identity']['code'], 'japanese_name': row['identity']['japanese_name'],
                      'source': row['source']} for row in batch['rows']],
            'row_map_hash': key([{'id': r['id'], 'source': r['source']} for r in batch['rows']])}
