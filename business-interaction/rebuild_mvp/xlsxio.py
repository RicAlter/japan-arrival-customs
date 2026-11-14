"""Lossless input reader and artifact-tool authored, fixed-layout matching view.

The native ZIP merge deliberately preserves weight XML and cached original
formula results. Artifact Tool has no API for byte-exact ZIP-part preservation.
No workbook is saved through openpyxl or through the legacy business runtime.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

Q = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PKG = '{http://schemas.openxmlformats.org/package/2006/relationships}'
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
ET.register_namespace('', Q[1:-1])
ET.register_namespace('r', R[1:-1])
HEADERS = ['CartonNo.', 'Origin', 'ProductCode(JANCode)', 'JC', '商品图片',
           '商品名称', '规格', '采购单价（原计价单位）', '倍数（采购价÷批发价）',
           'DescriptionofGoods', 'Qty', '卸价（日本JPY）', '批发金额（日本JPY）',
           '品类', '材质', '渠道', 'YD', '网站查找材质', '材质参考',
           '盒规原文参考（人工判断）', '盒装数', '盒规', '是否盲盒', '总单个数（数量依据）']
ALIASES = {
    'carton': ['CartonNo.', 'Carton No.', '箱号', '箱番'],
    'origin': ['Origin', '产地'],
    'code': ['ProductCode(JANCode)', 'ProductCode', 'JANCode', 'JAN', '商品编码', '条形码'],
    'ja': ['DescriptionofGoods', 'Description of Goods', '日文名称', '日文名'],
    'qty': ['Qty', 'Quantity', '数量'],
    'jpy_price': ['UnitPrice(日本JPY)', 'Unit Price(日本JPY)', 'UnitPrice', '卸价（日本JPY）'],
    'amount': ['Subtotal', 'Amount', '批发金额（日本JPY）'],
}


class WorkbookError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def _norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).lower()


def col_number(col):
    n = 0
    for c in col:
        n = n * 26 + ord(c.upper()) - 64
    return n


def col_letter(n):
    out = ''
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(r + 65) + out
    return out


def _safe_package(z):
    names = z.namelist()
    if len(names) != len(set(names)) or any(n.startswith('/') or '..' in PurePosixPath(n).parts for n in names):
        raise WorkbookError('INPUT_INVALID', '工作簿ZIP成员不安全或重复')
    if any('vbaProject' in n for n in names):
        raise WorkbookError('INPUT_INVALID', 'MVP不接收宏工作簿')
    # Actual warehouse file contains passive external-link cache metadata.
    # Reading and preserving it is permitted; no links/formulas are executed.


def sheet_info(path):
    with zipfile.ZipFile(path) as z:
        _safe_package(z)
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets = {x.get('Id'): x.get('Target') for x in rels}
        root = ET.fromstring(z.read('xl/workbook.xml'))
        result = []
        for x in root.find(Q + 'sheets'):
            target = targets[x.get(R + 'id')]
            member = target.lstrip('/') if target.startswith('/') else str(PurePosixPath('xl') / target)
            result.append({'name': x.get('name'), 'path': member, 'state': x.get('state', 'visible')})
        return result


def _strings(z):
    if 'xl/sharedStrings.xml' not in z.namelist():
        return []
    values = []
    with z.open('xl/sharedStrings.xml') as f:
        for _, e in ET.iterparse(f, events=('end',)):
            if e.tag == Q + 'si':
                values.append(''.join(t.text or '' for t in e.iter(Q + 't')))
                e.clear()
    return values


_REF = re.compile(r'(?<![A-Za-z0-9_\.])(?P<colabs>\$?)(?P<col>[A-Z]{1,3})(?P<rowabs>\$?)(?P<row>[1-9][0-9]*)(?![A-Za-z0-9_\(])')


def _outside_strings(formula, transform):
    # Excel double-quoted string literals (including escaped quotes) are inert.
    parts = re.split(r'("(?:[^"]|"")*")', formula)
    return ''.join(p if i % 2 else transform(p) for i, p in enumerate(parts))


def translate_formula(formula, dc=0, dr=0):
    def change(m):
        col = col_number(m['col']) + (0 if m['colabs'] else dc)
        row = int(m['row']) + (0 if m['rowabs'] else dr)
        if col < 1 or row < 1:
            raise WorkbookError('INPUT_INVALID', '共享公式引用越界')
        return m['colabs'] + col_letter(col) + m['rowabs'] + str(row)
    return _outside_strings(formula, lambda p: _REF.sub(change, p))


def _iter_member(z, member, strings):
    shared = {}
    with z.open(member) as f:
        for _, e in ET.iterparse(f, events=('end',)):
            if e.tag != Q + 'row':
                continue
            n = int(e.get('r'))
            values, types, formulas = {}, {}, {}
            for c in e.findall(Q + 'c'):
                address = c.get('r', '')
                match = re.fullmatch(r'([A-Z]+)([0-9]+)', address)
                if not match:
                    continue
                col = match[1]
                typ = c.get('t', 'n')
                v = c.find(Q + 'v')
                raw = v.text or '' if v is not None else ''
                if typ == 's':
                    try:
                        value = strings[int(raw)] if raw else ''
                    except (ValueError, IndexError) as ex:
                        raise WorkbookError('INPUT_INVALID', '共享文本索引错误') from ex
                elif typ == 'inlineStr':
                    value = ''.join(t.text or '' for t in c.iter(Q + 't'))
                else:
                    value = raw
                if value != '':
                    values[col] = value
                types[col] = typ
                formula = c.find(Q + 'f')
                if formula is not None:
                    text = formula.text or ''
                    if formula.get('t') == 'shared':
                        si = formula.get('si')
                        if text:
                            shared[si] = (col_number(col), n, text)
                        elif si in shared:
                            bc, br, base = shared[si]
                            text = translate_formula(base, col_number(col) - bc, n - br)
                        else:
                            raise WorkbookError('INPUT_INVALID', '共享公式缺少主公式：' + address)
                    formulas[col] = text
            yield {'row': n, 'values': values, 'types': types, 'formulas': formulas}
            e.clear()


def iter_rows(path, sheet_name=None):
    infos = sheet_info(path)
    info = next((x for x in infos if x['name'] == sheet_name), None) if sheet_name else infos[0]
    if info is None:
        raise WorkbookError('INPUT_INVALID', '工作表不存在：' + str(sheet_name))
    with zipfile.ZipFile(path) as z:
        yield from _iter_member(z, info['path'], _strings(z))


def read_book(path):
    path = Path(path).resolve(strict=True)
    infos = sheet_info(path)
    sheets = []
    with zipfile.ZipFile(path) as z:
        strings = _strings(z)
        for info in infos:
            root = ET.fromstring(z.read(info['path']))
            sheets.append({**info, 'rows': list(_iter_member(z, info['path'], strings)),
                           'merges': [x.get('ref') for x in root.findall(Q + 'mergeCells/' + Q + 'mergeCell')]})
    return {'path': str(path), 'sha256': digest(path), 'sheets': sheets}


def detect_header(rows, aliases, required):
    normalized = {k: {_norm(x) for x in v} for k, v in aliases.items()}
    candidates = []
    for row in rows:
        found = {k: [c for c, v in row['values'].items() if _norm(v) in labels]
                 for k, labels in normalized.items()}
        if all(found.get(k) for k in required):
            if any(len(cols) > 1 for cols in found.values()):
                raise WorkbookError('FIELD_MAPPING_AMBIGUOUS', '重复表头需明确字段映射：行' + str(row['row']))
            candidates.append((row['row'], {k: cols[0] for k, cols in found.items() if cols}))
    if len(candidates) != 1:
        raise WorkbookError('FIELD_MAPPING_AMBIGUOUS', '无法唯一识别业务表头')
    return candidates[0]


def extract_batch(path):
    book = read_book(path)
    candidates = []
    for s in book['sheets']:
        try:
            n, mapping = detect_header(s['rows'][:100], ALIASES, {'code', 'ja', 'qty'})
            candidates.append((s, n, mapping))
        except WorkbookError:
            continue
    if len(candidates) != 1:
        raise WorkbookError('FIELD_MAPPING_AMBIGUOUS', '无法唯一识别到货商品工作表')
    sheet, header, mapping = candidates[0]
    if not all(k in mapping for k in ['carton', 'origin', 'jpy_price', 'amount']):
        raise WorkbookError('FIELD_MAPPING_AMBIGUOUS', '到货表缺少箱号、产地、价格或金额的明确表头')
    by_row = {x['row']: x for x in sheet['rows']}
    carton_ranges = {}
    for ref in sheet['merges']:
        m = re.fullmatch(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', ref)
        if m and m[1] == m[3] == mapping['carton'] and int(m[2]) > header:
            anchor = by_row.get(int(m[2]), {}).get('values', {}).get(m[1], '')
            for n in range(int(m[2]), int(m[4]) + 1):
                carton_ranges[n] = anchor
    result = []
    for r in sheet['rows']:
        if r['row'] <= header:
            continue
        vals = r['values']
        # At least a product identity and quantity. Totals/format-only rows
        # remain in metadata and are preserved by the output row map.
        code, ja, qty = (vals.get(mapping[k], '') for k in ['code', 'ja', 'qty'])
        if not (code or ja):
            continue
        raw = {k: vals.get(c, '') for k, c in mapping.items()}
        raw['carton'] = raw.get('carton') or carton_ranges.get(r['row'], '')
        cells = {k: {'column': c, 'value': vals.get(c, ''), 'type': r['types'].get(c, 'n'),
                     **({'formula': r['formulas'][c]} if c in r['formulas'] else {})}
                 for k, c in mapping.items()}
        rid = hashlib.sha256((book['sha256'] + '\0' + sheet['name'] + '\0' + str(r['row'])).encode()).hexdigest()
        issues = [] if raw['carton'] else [{'code': 'CARTON_MISSING', 'field': 'carton', 'message': '原表该行无箱号或适用合并范围'}]
        if qty == '':
            issues.append({'code': 'QUANTITY_MISSING', 'field': 'qty', 'message': '商品行原数量为空；保留原行，不推算'})
        result.append({'row_id': rid, 'source_row': r['row'], 'sheet': sheet['name'],
                       'raw': raw, 'raw_cells': cells, 'values': {}, 'evidence': {}, 'issues': issues})
        result[-1]['original_row'] = copy.deepcopy(r)
    weight = next((s for s in book['sheets'] if s['name'] != sheet['name'] and ('重' in s['name'] or 'weight' in s['name'].lower())), None)
    if weight is None or len(book['sheets']) != 2:
        raise WorkbookError('INPUT_INVALID', '本MVP需要明确的商品表和箱重表两张工作表')
    return {'source': {'path': book['path'], 'sha256': book['sha256'], 'role': 'japanese_batch'},
            'sheet': sheet['name'], 'weight_sheet': weight['name'], 'rows': result,
            'metadata': {'header_row': header, 'mapping': mapping, 'source_body_last_row': max(by_row),
                         'product_rows': len(result), 'carton_merge_ranges': len(carton_ranges),
                         'other_raw_rows': [r for r in sheet['rows'] if r['row'] > header and r['row'] not in {x['source_row'] for x in result}]}}


def _tree(info):
    e = ET.Element(info['tag'], info.get('attributes', {}))
    e.text = info.get('text')
    for child in info.get('children', []):
        e.append(_tree(child))
    return e


def _merge_styles(source, authored):
    """Append authored style tables without modifying source style semantics."""
    dest, new = ET.fromstring(source), ET.fromstring(authored)
    maps = {}
    num_map = {}
    dn = dest.find(Q + 'numFmts')
    if dn is None:
        dn = ET.Element(Q + 'numFmts', {'count': '0'})
        dest.insert(0, dn)
    used = {int(x.get('numFmtId')) for x in dn}
    for x in new.findall(Q + 'numFmts/' + Q + 'numFmt'):
        old = int(x.get('numFmtId'))
        nxt = max(used | {163}) + 1
        clone = copy.deepcopy(x)
        clone.set('numFmtId', str(nxt))
        dn.append(clone); used.add(nxt); num_map[old] = nxt
    dn.set('count', str(len(dn)))
    for name in ['fonts', 'fills', 'borders', 'cellStyleXfs', 'cellXfs', 'dxfs']:
        de, ne = dest.find(Q + name), new.find(Q + name)
        if ne is None:
            continue
        if de is None:
            de = ET.SubElement(dest, Q + name, {'count': '0'})
        offset = len(de)
        maps[name] = offset
        for x in ne:
            clone = copy.deepcopy(x)
            if name in ['cellStyleXfs', 'cellXfs']:
                for attr, table in [('fontId', 'fonts'), ('fillId', 'fills'), ('borderId', 'borders')]:
                    if clone.get(attr) is not None:
                        clone.set(attr, str(int(clone.get(attr)) + maps.get(table, 0)))
                if clone.get('numFmtId') is not None and int(clone.get('numFmtId')) in num_map:
                    clone.set('numFmtId', str(num_map[int(clone.get('numFmtId'))]))
                if name == 'cellXfs' and clone.get('xfId') is not None:
                    clone.set('xfId', str(int(clone.get('xfId')) + maps.get('cellStyleXfs', 0)))
            de.append(clone)
        de.set('count', str(len(de)))
    return ET.tostring(dest, encoding='utf-8', xml_declaration=True), maps.get('cellXfs', 0), maps.get('dxfs', 0)


def remap_formula(formula, colmap, row_offset, source_sheet, weight_sheet):
    """Map main-sheet references, leave explicitly qualified weight refs intact."""
    # Token pattern includes optional quoted/unquoted sheet; strings inert.
    token = re.compile(r"(?<![A-Za-z0-9_\.])(?:(?P<sheet>'(?:[^']|'')+'|[\w\u0080-\uffff]+)!)?(?P<ca>\$?)(?P<c>[A-Z]{1,3})(?P<ra>\$?)(?P<r>[1-9][0-9]*)(?![A-Za-z0-9_\(])")
    def change(m):
        sn = (m['sheet'] or '').strip("'").replace("''", "'")
        if sn and sn != source_sheet:
            if sn != weight_sheet:
                raise WorkbookError('INPUT_INVALID', '公式引用未知工作表：' + sn)
            return m[0]
        c = colmap.get(m['c'])
        if c is None:
            raise WorkbookError('INPUT_INVALID', '需保留公式引用了未展示原列：' + m['c'])
        r = int(m['r']) + row_offset
        if r < 1:
            raise WorkbookError('INPUT_INVALID', '公式引用原表头区域，不能自动转移')
        prefix = m['sheet'] + '!' if m['sheet'] else ''
        return prefix + m['ca'] + c + m['ra'] + str(r)
    return _outside_strings(formula, lambda p: token.sub(change, p))


def _patch_cell(cell, value, typ='n', formula=None):
    for child in list(cell):
        if child.tag in {Q + 'f', Q + 'v', Q + 'is'}:
            cell.remove(child)
    cell.attrib.pop('t', None)
    if formula is not None:
        ET.SubElement(cell, Q + 'f').text = formula
        if typ in {'str', 'e', 'b'}:
            cell.set('t', typ)
        ET.SubElement(cell, Q + 'v').text = str(value)
    elif value != '' and value is not None:
        if typ in {'s', 'inlineStr', 'str'}:
            cell.set('t', 'inlineStr')
            ET.SubElement(ET.SubElement(cell, Q + 'is'), Q + 't').text = str(value)
        else:
            if typ != 'n':
                cell.set('t', typ)
            ET.SubElement(cell, Q + 'v').text = str(value)


def _cell(row, address):
    found = next((c for c in row if c.get('r') == address), None)
    if found is None:
        found = ET.SubElement(row, Q + 'c', {'r': address})
    return found


def write_book(raw_source, output, rows, layout_contract, manifest):
    raw_source, output = Path(raw_source).resolve(strict=True), Path(output).resolve()
    if output.exists() or raw_source == output:
        raise WorkbookError('TASK_CONFLICT', '输出必须是新文件，禁止覆盖原文件或已有结果')
    layout = json.loads(Path(layout_contract).read_text(encoding='utf-8-sig')) if not isinstance(layout_contract, dict) else layout_contract
    batch = extract_batch(raw_source)
    expected = [(r['row_id'], r['source_row'], r['raw'], r['raw_cells']) for r in batch['rows']]
    actual = [(r['row_id'], r['source_row'], r['raw'], r['raw_cells']) for r in rows]
    if actual != expected:
        raise WorkbookError('TASK_CONFLICT', '匹配结果改变了原行身份、行序或原始数据')
    ls = next(s for s in layout['sheets'] if s['name'] == batch['sheet'])
    if list(ls['headers'].values()) != HEADERS:
        raise WorkbookError('CONFIG_INVALID', '固定24列表头合同不符')
    output.parent.mkdir(parents=True, exist_ok=True)
    offset = 1 - batch['metadata']['header_row']
    last = batch['metadata']['source_body_last_row'] + offset
    matrix = [[None] * 24 for _ in range(last)]
    matrix[0] = HEADERS
    value_cols = {'jc': 'D', 'name': 'F', 'specification': 'G', 'purchase_price': 'H',
                  'category': 'N', 'material': 'O', 'channel': 'P', 'yd': 'Q',
                  'website_material': 'R', 'material_reference': 'S', 'pack_reference': 'T',
                  'box_count': 'U', 'box_size': 'V', 'blind': 'W', 'total_pieces': 'X'}
    rawcols = {'carton': 'A', 'origin': 'B', 'code': 'C', 'ja': 'J', 'qty': 'K', 'jpy_price': 'L', 'amount': 'M'}
    for r in rows:
        target = matrix[r['source_row'] + offset - 1]
        for field, col in rawcols.items():
            value = r['raw'].get(field, '')
            # Input cached number used for authored preview, native value patched below.
            if field in {'qty', 'jpy_price', 'amount'} and value != '':
                try:
                    value = float(value)
                except ValueError:
                    pass
            target[col_number(col) - 1] = value or None
        for field, col in value_cols.items():
            value = r.get('values', {}).get(field, '')
            target[col_number(col) - 1] = value if value != '' else None
    payload = {'sheet': batch['sheet'], 'weight_sheet': batch['weight_sheet'], 'matrix': matrix,
               'cols': ls['layout'].get('cols', []), 'output': '', 'preview': '',
               'issues': [{'row': r['source_row'] + offset, 'field': i.get('field'), 'code': i.get('code')}
                          for r in rows for i in r.get('issues', [])], 'value_columns': value_cols}
    node = os.environ.get('ARRIVAL_NODE') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
    dependencies = os.environ.get('ARRIVAL_NODE_MODULES') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
    if not Path(node).is_file() or not Path(dependencies).is_dir():
        raise WorkbookError('CONFIG_INVALID', '缺少已配置Node/artifact-tool运行环境')
    with tempfile.TemporaryDirectory(prefix='arrival-author-', dir=output.parent) as tmp:
        tmp = Path(tmp)
        payload['output'], payload['preview'] = str(tmp / 'authored.xlsx'), str(tmp / 'preview.png')
        (tmp / 'payload.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf8')
        # ESM resolution starts at the copied builder. Junction lives only in this run directory.
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(tmp / 'node_modules'), dependencies], check=True, capture_output=True)
        builder = tmp / 'author.mjs'
        builder.write_bytes((Path(__file__).with_name('author.mjs')).read_bytes())
        run = subprocess.run([node, str(builder), str(tmp / 'payload.json')], capture_output=True, text=True, encoding='utf8')
        if run.returncode:
            raise WorkbookError('RUNTIME_FAILURE', 'Excel生成失败：' + (run.stderr or run.stdout)[-2000:])
        with zipfile.ZipFile(raw_source) as src, zipfile.ZipFile(tmp / 'authored.xlsx') as authored:
            parts = {n: src.read(n) for n in src.namelist()}
            source_infos = sheet_info(raw_source)
            main_member = next(s['path'] for s in source_infos if s['name'] == batch['sheet'])
            weight_member = next(s['path'] for s in source_infos if s['name'] == batch['weight_sheet'])
            main = ET.fromstring(authored.read('xl/worksheets/sheet1.xml'))
            # Fixed sample styles are business-selected. Artifact supplies the
            # new sheet content; source styles remain unchanged for weight.
            sample_styles = _tree(layout['formatting_parts']['xl/styles.xml']['structure'])
            merged_sample, sample_offset, _ = _merge_styles(parts['xl/styles.xml'], ET.tostring(sample_styles, encoding='utf-8'))
            merged, style_offset, dxf_offset = _merge_styles(merged_sample, authored.read('xl/styles.xml'))
            strings = _strings(authored)
            header_styles = ls['row_style_profiles'][0]['cell_styles']
            body_styles = next(p['cell_styles'] for p in ls['row_style_profiles'] if p['row'] == 2)
            issue_addresses = {value_cols[i.get('field')] + str(r['source_row'] + offset)
                               for r in rows for i in r.get('issues', []) if i.get('field') in value_cols}
            for c in main.iter(Q + 'c'):
                address = c.get('r')
                col = re.match('[A-Z]+', address)[0]
                if address in issue_addresses:
                    c.set('s', str(int(c.get('s', '0')) + style_offset))
                else:
                    profiles = header_styles if re.fullmatch(r'[A-Z]+1', address) else body_styles
                    c.set('s', str(int(profiles.get(col, '0')) + sample_offset))
                if c.get('t') == 's':
                    v = c.find(Q + 'v')
                    value = strings[int(v.text)]
                    _patch_cell(c, value, 's')
            for e in main.iter(Q + 'cfRule'):
                if e.get('dxfId') is not None:
                    e.set('dxfId', str(int(e.get('dxfId')) + dxf_offset))
            sd = main.find(Q + 'sheetData')
            by_target = {int(r.get('r')): r for r in sd}
            mapping = batch['metadata']['mapping']
            colmap = {mapping[f]: c for f, c in rawcols.items()}
            for r in rows:
                nr = r['source_row'] + offset
                er = by_target.get(nr)
                if er is None:
                    er = ET.SubElement(sd, Q + 'row', {'r': str(nr)})
                    by_target[nr] = er
                for field, col in rawcols.items():
                    info = r['raw_cells'][field]
                    value = r['raw'][field] if field == 'carton' else info['value']
                    typ = 's' if field == 'carton' and info['value'] == '' and value else info.get('type', 'n')
                    formula = info.get('formula')
                    if formula is not None:
                        formula = remap_formula(formula, colmap, offset, batch['sheet'], batch['weight_sheet'])
                    _patch_cell(_cell(er, col + str(nr)), value, typ, formula)
                # Identifiers are text. Artifact import/export may otherwise
                # coerce an all-digit JC into a number/scientific notation.
                for field, col in [('jc', 'D'), ('yd', 'Q')]:
                    value = r.get('values', {}).get(field)
                    if value not in ('', None):
                        _patch_cell(_cell(er, col + str(nr)), str(value), 's')
            # Preserve source non-product rows (notably quantity/amount totals),
            # but never map source auxiliary carton-count/weight columns into a
            # different business meaning. Their original cells are in manifest.
            for source_row in batch['metadata']['other_raw_rows']:
                nr = source_row['row'] + offset
                if nr < 2:
                    continue
                er = by_target.get(nr)
                if er is None:
                    er = ET.SubElement(sd, Q + 'row', {'r': str(nr)})
                    by_target[nr] = er
                for field in ['qty', 'jpy_price', 'amount']:
                    old, newcol = mapping[field], rawcols[field]
                    if old not in source_row['values'] and old not in source_row['formulas']:
                        continue
                    formula = source_row['formulas'].get(old)
                    if formula is not None:
                        formula = remap_formula(formula, colmap, offset, batch['sheet'], batch['weight_sheet'])
                    _patch_cell(_cell(er, newcol + str(nr)), source_row['values'].get(old, ''),
                                source_row['types'].get(old, 'n'), formula)
                # Explicit textual TOTAL label, if present, stays descriptive.
                labels = [v for c, v in source_row['values'].items() if c not in colmap and re.search('total|合計|合计', v, re.I)]
                if labels:
                    _patch_cell(_cell(er, 'J' + str(nr)), labels[0], 's')
            # Restore fixed layout properties without drawing/image references.
            dimension = main.find(Q + 'dimension')
            if dimension is None:
                dimension = ET.SubElement(main, Q + 'dimension')
            dimension.set('ref', 'A1:X' + str(last))
            auto_filter = main.find(Q + 'autoFilter')
            if auto_filter is None:
                auto_filter = ET.SubElement(main, Q + 'autoFilter')
            auto_filter.set('ref', 'B1:X' + str(max(r['source_row'] for r in rows) + offset))
            for key in ['sheetPr', 'sheetViews', 'sheetFormatPr', 'cols', 'pageMargins', 'pageSetup', 'headerFooter']:
                for e in list(main.findall(Q + key)):
                    main.remove(e)
                for info in ls['layout'].get(key, []):
                    e = _tree(info)
                    if key == 'sheetViews':
                        for pane in e.iter(Q + 'pane'):
                            pane.set('topLeftCell', 'A2')
                        for selection in e.iter(Q + 'selection'):
                            selection.set('activeCell', 'A2'); selection.set('sqref', 'A2')
                    main.append(e)
            # OOXML worksheet child order is significant.
            order = ['sheetPr', 'dimension', 'sheetViews', 'sheetFormatPr', 'cols', 'sheetData', 'sheetCalcPr', 'sheetProtection', 'protectedRanges', 'scenarios', 'autoFilter', 'sortState', 'dataConsolidate', 'customSheetViews', 'mergeCells', 'phoneticPr', 'conditionalFormatting', 'dataValidations', 'hyperlinks', 'printOptions', 'pageMargins', 'pageSetup', 'headerFooter', 'rowBreaks', 'colBreaks', 'customProperties', 'cellWatches', 'ignoredErrors', 'smartTags', 'drawing', 'legacyDrawing', 'legacyDrawingHF', 'picture', 'oleObjects', 'controls', 'webPublishItems', 'tableParts', 'extLst']
            main[:] = sorted(main, key=lambda e: order.index(e.tag.split('}')[-1]) if e.tag.split('}')[-1] in order else len(order))
            sd[:] = sorted(sd, key=lambda e: int(e.get('r')))
            for er in sd:
                er[:] = sorted(er, key=lambda c: col_number(re.match('[A-Z]+', c.get('r'))[0]))
            # The chosen sample was image-heavy (156pt rows) and some source
            # styles disabled wrapping. Keep its fonts/formats/widths, with
            # wrap-only clones so the image-free draft remains readable.
            style_root = ET.fromstring(merged)
            xfs = style_root.find(Q + 'cellXfs')
            display_styles = {}
            widths = {}
            for group in ls['layout'].get('cols', []):
                for info in group.get('children', []):
                    a = info['attributes']
                    for cn in range(int(a['min']), int(a['max']) + 1):
                        widths[col_letter(cn)] = float(a['width'])
            for er in sd:
                nr = int(er.get('r'))
                lines = 1
                for c in er:
                    address = c.get('r')
                    col = re.match('[A-Z]+', address)[0]
                    if nr != 1 and col not in {'D', 'F', 'G', 'J', 'N', 'O', 'P', 'Q', 'R', 'S', 'T'}:
                        continue
                    old = int(c.get('s', '0'))
                    key = (old, nr == 1, col == 'D' and nr > 1)
                    if key not in display_styles:
                        clone = copy.deepcopy(xfs[old])
                        if col == 'D' and nr > 1:
                            # Text identity stays inlineStr. Explicit whole
                            # identifier format also prevents renderers from
                            # displaying numeric-looking text as E+12.
                            clone.set('numFmtId', '1')
                            clone.set('applyNumberFormat', '1')
                        alignment = clone.find(Q + 'alignment')
                        if alignment is None:
                            alignment = ET.SubElement(clone, Q + 'alignment')
                        alignment.set('wrapText', '1')
                        alignment.set('vertical', 'center')
                        if nr == 1:
                            alignment.set('horizontal', 'center')
                        clone.set('applyAlignment', '1')
                        display_styles[key] = len(xfs)
                        xfs.append(clone)
                    c.set('s', str(display_styles[key]))
                    text = ''.join(t.text or '' for t in c.iter(Q + 't'))
                    if not text and c.get('t') == 'str':
                        v = c.find(Q + 'v'); text = v.text or '' if v is not None else ''
                    if text:
                        count = sum(2 if unicodedata.east_asian_width(ch) in {'W', 'F'} else 1 for ch in text)
                        safety = 1 if nr == 1 else 1.4
                        lines = max(lines, math.ceil(safety * count / max(8, widths.get(col, 16) - 2)), text.count('\n') + 1)
                er.set('ht', str(min(409.5, max(42 if nr == 1 else 48, lines * 16 + 8))))
                er.set('customHeight', '1')
            xfs.set('count', str(len(xfs)))
            merged = ET.tostring(style_root, encoding='utf-8', xml_declaration=True)
            parts[main_member] = ET.tostring(main, encoding='utf-8', xml_declaration=True)
            parts['xl/styles.xml'] = merged
            # No references to stale input drawings or calculation chain.
            main_rel = str(PurePosixPath(main_member).parent / '_rels' / (PurePosixPath(main_member).name + '.rels'))
            parts.pop(main_rel, None)
            parts.pop('xl/calcChain.xml', None)
            for n in list(parts):
                if n.startswith('xl/media/') or n.startswith('xl/drawings/'):
                    parts.pop(n)
            rels = ET.fromstring(parts['xl/_rels/workbook.xml.rels'])
            for x in list(rels):
                if x.get('Type', '').endswith('/calcChain'):
                    rels.remove(x)
            ET.register_namespace('', PKG[1:-1])
            parts['xl/_rels/workbook.xml.rels'] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
            ET.register_namespace('', Q[1:-1])
            # Source print defined names refer to old rows/columns. Keep other
            # names but replace main print area/filter with current fixed view.
            wb = ET.fromstring(parts['xl/workbook.xml'])
            defined = wb.find(Q + 'definedNames')
            if defined is not None:
                for x in list(defined):
                    if x.get('localSheetId') == '0' and x.get('name') in {'_xlnm.Print_Area', '_xlnm._FilterDatabase', '_xlnm.Print_Titles'}:
                        defined.remove(x)
                ET.SubElement(defined, Q + 'definedName', {'name': '_xlnm.Print_Area', 'localSheetId': '0'}).text = "'" + batch['sheet'].replace("'", "''") + "'!$A$1:$X$" + str(last)
            parts['xl/workbook.xml'] = ET.tostring(wb, encoding='utf-8', xml_declaration=True)
            content = ET.fromstring(parts['[Content_Types].xml'])
            for x in list(content):
                partname = x.get('PartName', '').lstrip('/')
                if partname and partname not in parts:
                    content.remove(x)
            backend = {**manifest, 'layout': {'columns': HEADERS, 'row_offset': offset,
                       'source_sha256': batch['source']['sha256'], 'weight_xml_sha256': hashlib.sha256(parts[weight_member]).hexdigest()},
                       'original_auxiliary_rows': batch['metadata']['other_raw_rows']}
            parts['customXml/arrival-mvp-manifest.json'] = json.dumps(backend, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')
            ET.SubElement(content, CT + 'Override', {'PartName': '/customXml/arrival-mvp-manifest.json', 'ContentType': 'application/json'})
            ET.register_namespace('', CT[1:-1])
            parts['[Content_Types].xml'] = ET.tostring(content, encoding='utf-8', xml_declaration=True)
            ET.register_namespace('', Q[1:-1])
            ready = tmp / 'ready.xlsx'
            ET.fromstring(parts[main_member])  # Reject malformed final XML before publishing.
            with zipfile.ZipFile(ready, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
                for name in sorted(parts):
                    out.writestr(name, parts[name])
            if parts[weight_member] != src.read(weight_member):
                raise WorkbookError('RUNTIME_FAILURE', '箱重XML保全失败')
            verify = subprocess.run([node, str(builder), '--verify', str(ready), batch['sheet'], batch['weight_sheet'], str(tmp)],
                                    capture_output=True, text=True, encoding='utf8')
            if verify.returncode:
                raise WorkbookError('RUNTIME_FAILURE', '最终Excel回读失败：' + (verify.stderr or verify.stdout)[-2000:])
            # Windows rename fails if output exists. Never replace another process's published file.
            ready.rename(output)
        preview = Path(payload['preview'])
        if preview.is_file():
            output.with_suffix('.preview.png').write_bytes(preview.read_bytes())
        for suffix in ['main', 'detail', 'weight']:
            preview = tmp / (suffix + '.png')
            if preview.is_file():
                output.with_suffix('.' + suffix + '.png').write_bytes(preview.read_bytes())
    return {'file': str(output), 'sha256': digest(output), 'rows': len(rows), 'columns': 24,
            'sheets': [batch['sheet'], batch['weight_sheet']], 'images': 0,
            'weight_xml_preserved': True, 'source_row_offset': offset,
            'weight_xml_sha256': hashlib.sha256(parts[weight_member]).hexdigest(),
            'final_artifact_readback': True}
