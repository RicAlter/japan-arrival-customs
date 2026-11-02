"""Versioned local-file contract helpers. No network, arrival runtime or SQLite."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

VERSION = '1.0.0'
IDENTITY = ('code_raw', 'code_type', 'japanese_name', 'version', 'specification')
BASE = set(IDENTITY) | {'internal_name', 'customs_name', 'brand', 'category', 'channel', 'yd'}
ORDER = {'order_id', 'order_line_id', 'supplier', 'purchase_quantity', 'purchase_unit', 'unit_price', 'currency'}
PACK = {'packaging_original', 'packaging_label', 'packaging_parent_unit', 'packaging_child_unit', 'packaging_child_quantity'}
MATERIAL = {'material_original', 'material_translation', 'complete_composition', 'material_url', 'material_site'}
DECIMALS = {'purchase_quantity', 'unit_price', 'packaging_child_quantity'}

class SourceError(ValueError):
    pass

def sha(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def validate_request(request):
    allowed = {'schema_version', 'source_id', 'source_version', 'authorization_reference', 'mapping_version', 'files', 'identities', 'reference_type'}
    if not isinstance(request, dict) or set(request) - allowed:
        raise SourceError('请求包含未知字段；禁止数据库、Store路径或批准配置')
    if request.get('schema_version') != 'product-source-request/1':
        raise SourceError('不支持的来源请求版本')
    for key in ('source_id', 'source_version', 'authorization_reference', 'mapping_version'):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise SourceError('缺少授权或来源配置：' + key)
    if not isinstance(request.get('files'), list) or not request['files']:
        raise SourceError('缺少只读来源文件')
    return request

def scalar(value, field):
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SourceError('来源字段类型不支持：' + field)
    if field in DECIMALS:
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise SourceError('无效十进制字段：' + field) from exc
        if not number.is_finite() or number < 0:
            raise SourceError('数量/价格须为非负有限数')
        return format(number, 'f')
    # Excel numeric codes are preserved as observed text, never padded.
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)

def read_mapped(request, allowed_fields):
    """Yield source rows with per-field cell evidence and complete raw snapshots.

    Internal `_evidence` is removed by write_bundle after publishing its content.
    Adapter authors may derive explicit relations but must not invent identity.
    """
    validate_request(request)
    seen = set()
    for spec in request['files']:
        if not isinstance(spec, dict) or set(spec) - {'path', 'sheet', 'header_row', 'columns'}:
            raise SourceError('未知文件配置')
        path = Path(spec.get('path', '')).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in {'.xlsx', '.csv', '.json'}:
            raise SourceError('只接受XLSX/CSV/JSON本地文件')
        data = path.read_bytes(); content_hash = sha(data)
        mapping = spec.get('columns')
        if not isinstance(mapping, dict) or not mapping or set(mapping) - set(allowed_fields):
            raise SourceError('未知或缺失的字段映射')
        if any(not isinstance(v, str) or not v for v in mapping.values()):
            raise SourceError('字段映射必须引用实际表头')
        header_row = spec.get('header_row', 1)
        if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
            raise SourceError('表头行无效')
        sheet = spec.get('sheet')
        if path.suffix.lower() == '.xlsx':
            from openpyxl import load_workbook
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if any('vbaproject' in name.lower() or 'externallinks/' in name.lower() for name in archive.namelist()):
                    raise SourceError('来源包含宏或外部连接')
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
            try:
                if sheet not in book.sheetnames:
                    raise SourceError('必须指定实际存在的工作表')
                ws = book[sheet]
                header = [c.value for c in next(ws.iter_rows(min_row=header_row, max_row=header_row))]
                table = [(i, [c.value for c in row]) for i, row in enumerate(ws.iter_rows(min_row=header_row + 1), header_row + 1)]
            finally:
                book.close()
        elif path.suffix.lower() == '.csv':
            table_csv = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
            if not table_csv or header_row != 1:
                raise SourceError('CSV必须使用首行表头')
            header = table_csv[0]; table = list(enumerate(table_csv[1:], 2)); sheet = None
        else:
            rows_json = json.loads(data.decode('utf-8-sig'))
            if not isinstance(rows_json, list) or any(not isinstance(r, dict) for r in rows_json):
                raise SourceError('JSON须为对象数组')
            header = list(dict.fromkeys(k for r in rows_json for k in r))
            table = [(i, [row.get(k) for k in header]) for i, row in enumerate(rows_json, 1)]; sheet = None
        used_headers = [v for v in header if v is not None]
        if len(used_headers) != len(set(used_headers)):
            raise SourceError('来源包含重复表头')
        if set(mapping.values()) - set(used_headers):
            raise SourceError('映射列缺失：' + ','.join(sorted(set(mapping.values()) - set(used_headers))))
        indexes = {field: header.index(label) for field, label in mapping.items()}
        for row_num, values in table:
            if all(v in (None, '') for v in values):
                continue
            rid = sha(canonical([content_hash, sheet, row_num]).encode())
            if rid in seen:
                continue
            seen.add(rid)
            evidence_name = 'evidence/' + rid + '.json'
            fields = {}
            for field, index in indexes.items():
                raw = values[index] if index < len(values) else None
                if isinstance(raw, str) and raw.startswith('='):
                    raise SourceError('映射字段含公式，不能猜测缓存值')
                val = scalar(raw, field)
                fields[field] = {'value': val, 'raw_value': raw,
                    'evidence': [{'file': evidence_name, 'sheet': sheet, 'row': row_num, 'cell': str(header[index]), 'quote': None if raw is None else str(raw)}],
                    'reference_type': request.get('reference_type', 'historical_reference'),
                    'translation_status': 'provided_unreviewed' if field == 'material_translation' and val else 'not_applicable'}
            identity = {field: fields.get(field, {}).get('value') for field in IDENTITY}
            if not identity['code_type'] and identity['code_raw']:
                identity['code_type'] = 'source_identifier'
            yield {'source_record_id': rid, 'identity': identity,
                'provenance': {'source_id': request['source_id'], 'source_version': request['source_version'],
                               'file_sha256': content_hash, 'file_name': path.name, 'sheet': sheet, 'row': row_num},
                'fields': fields, 'status': 'succeeded', 'review_status': 'reference_only', 'approval': False,
                '_evidence': {evidence_name: {'file_sha256': content_hash, 'sheet': sheet, 'row': row_num,
                                           'values': {str(k): v for k, v in zip(header, values) if k is not None}}}}
        if sha(path.read_bytes()) != content_hash:
            raise SourceError('来源在读取期间发生变化')

def write_bundle(request, records, destination, adapter_id):
    validate_request(request)
    out = Path(destination).resolve()
    if out.exists():
        raise SourceError('输出目录已存在，拒绝覆盖')
    for spec in request['files']:
        parent = Path(spec['path']).resolve(strict=True).parent
        if out == parent or out.is_relative_to(parent) or parent.is_relative_to(out):
            raise SourceError('输出目录必须与输入目录分离')
    evidence = {}; clean_records = []
    for item in records:
        row = dict(item)
        for name, content in row.pop('_evidence', {}).items():
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or not name.startswith('evidence/') or '\\' in name:
                raise SourceError('非法证据相对路径')
            if name in evidence and evidence[name] != content:
                raise SourceError('证据文件冲突')
            evidence[name] = content
        clean_records.append(row)
    if len({r['source_record_id'] for r in clean_records}) != len(clean_records):
        raise SourceError('来源记录ID重复')
    payload = {'records.jsonl': ''.join(canonical(r) + '\n' for r in clean_records).encode('utf-8')}
    payload.update({name: (canonical(value) + '\n').encode('utf-8') for name, value in evidence.items()})
    report = {'scanned': len(clean_records), 'succeeded': sum(r['status'] == 'succeeded' for r in clean_records),
              'rejected': 0, 'errors': [], 'mapping_version': request['mapping_version'],
              'real_source_verified': False, 'notice': '解析成功不等于字段含义获批或真实系统已接通'}
    payload['validation_report.json'] = (canonical(report) + '\n').encode('utf-8')
    manifest = {'schema_version': 'product-source-bundle/1', 'adapter_id': adapter_id, 'adapter_version': VERSION,
                'mapping_version': request['mapping_version'], 'source_id': request['source_id'],
                'source_version': request['source_version'], 'authorization_reference': request['authorization_reference'],
                'files': {name: sha(data) for name, data in payload.items()}, 'record_count': len(clean_records),
                'status': 'succeeded' if all(r['status'] == 'succeeded' for r in clean_records) else 'partial_failure'}
    # Publish a new directory only after all in-memory parsing/validation succeeds.
    out.mkdir(parents=True)
    for name, data in payload.items():
        target = out / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
    (out / 'manifest.json').write_text(canonical(manifest) + '\n', encoding='utf-8')
    return manifest

def run(adapter_id, collect, argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument('--request', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        request = json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
        manifest = write_bundle(request, list(collect(request)), args.output, adapter_id)
        print(canonical(manifest)); return 0
    except (SourceError, OSError, ValueError, KeyError) as exc:
        print(canonical({'status': 'unsupported_mapping', 'error': str(exc), 'approval': False})); return 2
