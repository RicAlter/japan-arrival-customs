"""Explicit positional Excel profiles, including unnamed business columns."""
import io
import json
import zipfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from source_adapters.common import BASE, MATERIAL, canonical, sha, scalar, write_bundle
from .core import Rejected


def extract(path, mapping, *, source_id, source_version, authorization_reference):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes(); file_hash = sha(data)
    allowed = BASE | MATERIAL | {'packaging_label'}
    if (not isinstance(mapping, dict) or set(mapping) != {'id','sheet','header_row','headers','columns','item_column'}
            or not mapping['columns'] or set(mapping['columns']) - allowed):
        raise Rejected('Excel映射不完整或含采购/关务/最终选择字段')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if any('vbaproject' in n.lower() for n in archive.namelist()):
            raise Rejected('来源含宏')
        external_links = [n for n in archive.namelist() if 'externallinks/' in n.lower()]
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    records = []
    try:
        if mapping['sheet'] not in book.sheetnames:
            raise Rejected('映射工作表不存在')
        sheet = book[mapping['sheet']]; header_row = mapping['header_row']
        for cell, expected in mapping['headers'].items():
            if sheet[f'{cell}{header_row}'].value != expected:
                raise Rejected('显式映射表头不匹配：' + cell)
        max_col = sheet.max_column
        if max_col > 512:
            raise Rejected('来源格式尾列过宽，需提供经过核对的窄表导出；不静默丢弃证据列')
        # Capture original cells/formulas through the last declared source column.
        # Never enumerate a formatting-only XFD tail.
        for cells in sheet.iter_rows(min_row=header_row+1, max_col=max_col):
            row_num = cells[0].row if cells[0].value is not None else next((c.row for c in cells if c.value is not None), None)
            if row_num is None:
                continue
            item = cells[column_index_from_string(mapping['item_column'])-1].value
            if item is None or str(item).strip().casefold() in {'total','合计','总计','計'}:
                continue
            rid = sha(canonical([file_hash, sheet.title, row_num]).encode())
            evidence_file = 'evidence/' + rid + '.json'
            fields, raw_cells = {}, {}
            for cell in cells:
                if cell.value is not None:
                    raw_cells[cell.coordinate] = {'raw': cell.value, 'type': cell.data_type,
                                                  'number_format': cell.number_format,
                                                  'formula': cell.value if cell.data_type == 'f' else None}
            for field, col in mapping['columns'].items():
                cell = cells[column_index_from_string(col)-1]
                # Preserve the original formula/error as evidence, leave its
                # semantic field missing. Never resolve external links/caches.
                value = None if cell.data_type in ('f', 'e') else scalar(cell.value, field)
                fields[field] = {'value': value, 'raw_value': cell.value,
                    'evidence': [{'file': evidence_file, 'sheet': sheet.title, 'row': row_num,
                                  'cell': f'{col}{row_num}', 'quote': None if cell.value is None else str(cell.value)}],
                    'reference_type': 'historical_reference', 'translation_status': 'provided_unreviewed' if field == 'material_translation' and value else 'not_applicable'}
            identity = {k: fields.get(k, {}).get('value') for k in ('code_raw','code_type','japanese_name','version','specification')}
            if identity['code_raw'] and not identity['code_type']:
                identity['code_type'] = 'source_identifier'
            records.append({'source_record_id': rid, 'identity': identity,
                'provenance': {'source_id': source_id, 'source_version': source_version,
                               'file_name': path.name, 'file_sha256': file_hash, 'sheet': sheet.title, 'row': row_num},
                'fields': fields, 'status': 'succeeded', 'review_status': 'reference_only', 'approval': False,
                '_evidence': {evidence_file: {'file_sha256': file_hash, 'sheet': sheet.title,
                                            'row': row_num, 'cells': raw_cells,
                                            'external_links_ignored_not_resolved': external_links}}})
    finally:
        book.close()
    if sha(path.read_bytes()) != file_hash:
        raise Rejected('解析期间原件变化')
    return records


def collect_bundle(path, mapping, destination, *, source_id, source_version, authorization_reference):
    rows = extract(path, mapping, source_id=source_id, source_version=source_version,
                   authorization_reference=authorization_reference)
    request = {'schema_version': 'product-source-request/1', 'source_id': source_id,
               'source_version': source_version, 'authorization_reference': authorization_reference,
               'mapping_version': mapping['id'], 'files': [{'path': str(Path(path).resolve())}]}
    return write_bundle(request, rows, destination, 'order')


def queries(path, mapping):
    rows = extract(path, mapping, source_id='query-only', source_version='query-only', authorization_reference='query-only')
    return [{'row_id': r['source_record_id'], **r['identity'], 'source': r['provenance']} for r in rows]
