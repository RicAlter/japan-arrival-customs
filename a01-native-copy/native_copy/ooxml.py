"""Surgical OOXML patching: all other ZIP parts stay byte-for-byte identical."""
import copy
import io
import posixpath
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

from .support import Rejected

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
URI = NS['s']
Q = '{' + URI + '}'
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
PREFIX = rb'(?:[A-Za-z_][\w.-]*:)?'
CELL = re.compile(rb'<' + PREFIX + rb'c\b[^>]*?(?:/>|>.*?</' + PREFIX + rb'c>)', re.S)
ROW = re.compile(rb'<' + PREFIX + rb'row\b[^>]*?(?:/>|>.*?</' + PREFIX + rb'row>)', re.S)
COLORS = {'yellow': 'FFFFF2CC', 'red': 'FFF4CCCC'}


def attr(data, name):
    head = data[:data.index(b'>') + 1]
    m = re.search(rb'(?<![\w:.-])' + name.encode() + rb'="([^"]*)"', head)
    return m[1].decode() if m else None


def set_attr(data, name, value):
    i = data.index(b'>') + 1
    head, rest = data[:i], data[i:]
    pattern = rb'(?<![\w:.-])' + name.encode() + rb'="[^"]*"'
    replacement = name.encode() + b'="' + str(value).encode() + b'"'
    if re.search(pattern, head):
        head = re.sub(pattern, lambda m: replacement, head, count=1)
    else:
        j = len(head) - (2 if head.endswith(b'/>') else 1)
        head = head[:j] + b' ' + replacement + head[j:]
    return head + rest


def col_number(address):
    n = 0
    for c in address.rstrip('0123456789'):
        n = n * 26 + ord(c) - 64
    return n


def signature(e):
    return (e.tag, tuple(sorted(e.attrib.items())), e.text, e.tail, tuple(signature(c) for c in e))


def parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if len(z.namelist()) != len(set(z.namelist())) or z.testzip():
            raise Rejected('Excel包有重复成员或CRC错误')
        if any(n.lower().endswith('vbaproject.bin') for n in z.namelist()):
            raise Rejected('本阶段不接收宏文件')
        return {n: z.read(n) for n in z.namelist()}


def sheet_member(package, name):
    workbook = ET.fromstring(package['xl/workbook.xml'])
    rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(package['xl/_rels/workbook.xml.rels'])}
    for s in workbook.findall('s:sheets/s:sheet', NS):
        if s.get('name') == name:
            target = rels[s.get(RID)]
            member = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
            if member not in package or '..' in member.split('/'):
                raise Rejected('工作表关系无效')
            return member
    raise Rejected('缺工作表：' + name)


class Styles:
    def __init__(self, raw):
        self.raw = raw
        self.tree = ET.fromstring(raw)
        self.fills = list(self.tree.find(Q + 'fills'))
        self.xfs = list(self.tree.find(Q + 'cellXfs'))
        self.extra_fills = []; self.extra_xfs = []; self.cache = {}
        self.xf_raw = self.section('cellXfs')[0]
        self.fragments = re.findall(rb'<' + PREFIX + rb'xf\b[^>]*?(?:/>|>.*?</' + PREFIX + rb'xf>)', self.xf_raw, re.S)
        if len(self.fragments) != len(self.xfs):
            raise Rejected('不支持的样式XML结构')
        root = re.search(rb'<([A-Za-z_][\w.-]*:)?styleSheet\b', raw)
        self.p = root[1] or b''

    def section(self, name):
        m = re.search(rb'<' + PREFIX + name.encode() + rb'\b[^>]*>.*?</' + PREFIX + name.encode() + rb'>', self.raw, re.S)
        if not m:
            raise Rejected('样式表缺少：' + name)
        return m[0], m.start(), m.end()

    def colored(self, base, color):
        if base >= len(self.xfs):
            raise Rejected('源样式ID越界')
        old_fill = self.fills[int(self.xfs[base].get('fillId', '0'))]
        pattern = old_fill.find(Q + 'patternFill')
        # An existing colored cell may be a human annotation; never erase it.
        if pattern is not None and pattern.get('patternType') not in (None, 'none', 'gray125'):
            return base, False
        if (base, color) in self.cache:
            return self.cache[base, color], True
        fill_id = len(self.fills) + len(self.extra_fills)
        p = self.p
        self.extra_fills.append(b'<' + p + b'fill><' + p + b'patternFill patternType="solid"><' + p + b'fgColor rgb="' + color.encode() + b'"/><' + p + b'bgColor indexed="64"/></' + p + b'patternFill></' + p + b'fill>')
        xf = set_attr(set_attr(self.fragments[base], 'fillId', fill_id), 'applyFill', '1')
        index = len(self.xfs) + len(self.extra_xfs)
        self.extra_xfs.append(xf); self.cache[base, color] = index
        return index, True

    def export(self):
        result = self.raw
        for name, extra, count in [('fills', self.extra_fills, len(self.fills)), ('cellXfs', self.extra_xfs, len(self.xfs))]:
            if not extra:
                continue
            old, _, _ = self.section(name)
            closing = re.search(rb'</' + PREFIX + name.encode() + rb'>$' , old)
            new = set_attr(old[:closing.start()] + b''.join(extra) + old[closing.start():], 'count', count + len(extra))
            result = result.replace(old, new, 1)
        return result


def patch_cell(original, change, prefix=b''):
    addr = change['cell']
    raw = original or b'<' + prefix + b'c r="' + addr.encode() + b'"/>'
    raw = set_attr(raw, 's', change['style_id'])
    if change.get('write_value') is None:
        return raw
    head_end = raw.index(b'>') + 1
    head, body = raw[:head_end], raw[head_end:]
    head = re.sub(rb'\s+t="[^"]*"', b'', head)
    if head.endswith(b'/>'):
        head = head[:-2] + b'>'
        body = b'</' + prefix + b'c>'
    body = re.sub(rb'<' + PREFIX + rb'(?:v|is)\b[^>]*?(?:/>|>.*?</' + PREFIX + rb'(?:v|is)>)', b'', body, flags=re.S)
    if change['value_type'] == 'number':
        value = b'<' + prefix + b'v>' + str(change['write_value']).encode() + b'</' + prefix + b'v>'
    else:
        head = set_attr(head, 't', 'inlineStr')
        value = (b'<' + prefix + b'is><' + prefix + b't xml:space="preserve">' +
                 escape(str(change['write_value'])).encode('utf-8') + b'</' + prefix + b't></' + prefix + b'is>')
    return head + value + body


def build(source_bytes, sheet_name, proposed):
    package = parts(source_bytes)
    member = sheet_member(package, sheet_name)
    raw = package[member]
    tree = ET.fromstring(raw)
    root_match = re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b', raw)
    prefix = root_match[1] or b''
    styles = Styles(package['xl/styles.xml'])
    elements = {c.get('r'): c for c in tree.findall('s:sheetData/s:row/s:c', NS)}
    physical_rows = tree.findall('s:sheetData/s:row', NS)
    physical_cells = tree.findall('s:sheetData/s:row/s:c', NS)
    if len(elements) != len(physical_cells) or len({r.get('r') for r in physical_rows}) != len(physical_rows):
        raise Rejected('源表包含重复行/单元格身份')
    strings = []
    if 'xl/sharedStrings.xml' in package:
        strings = [''.join(t.text or '' for t in e.findall('.//' + Q + 't'))
                   for e in ET.fromstring(package['xl/sharedStrings.xml']).findall(Q + 'si')]
    row_styles = {int(r.get('r')): int(r.get('s', '0')) for r in tree.findall('s:sheetData/s:row', NS)}
    columns = tree.findall('s:cols/s:col', NS)
    changes = []
    for item in proposed:
        d = dict(item); addr = d['cell']; old = elements.get(addr)
        if old is not None and old.find(Q + 'f') is not None and d.get('write_value') is not None:
            raise Rejected('计划试图修改已有公式：' + addr)
        base = int(old.get('s', '0')) if old is not None else row_styles.get(int(re.search(r'\d+$', addr)[0]), 0)
        if old is None and not base:
            for col in columns:
                if int(col.get('min')) <= col_number(addr) <= int(col.get('max')):
                    base = int(col.get('style', '0'))
        d['base_style_id'] = base
        d['style_id'], d['fill_applied'] = styles.colored(base, COLORS[d['color']])
        d['original_cell_exists'] = old is not None
        if d.get('write_value') is not None and old is not None:
            value = old.find(Q + 'v'); texts = old.findall('.//' + Q + 't')
            observed = value.text if value is not None else None
            if old.get('t') == 's' and observed is not None:
                observed = strings[int(observed)]
            if observed not in (None, '') or any(t.text not in (None, '') for t in texts):
                raise Rejected('不能覆盖已有非空值：' + addr)
        changes.append(d)
    by_row = {}
    for d in changes:
        by_row.setdefault(int(re.search(r'\d+$', d['cell'])[0]), {})[d['cell']] = d
    touched = set()
    def patch_row(match):
        fragment = match[0]; ri = int(attr(fragment, 'r'))
        edits = by_row.get(ri)
        if not edits:
            return fragment
        seen = set(); touched.add(ri)
        def replace_cell(m):
            address = attr(m[0], 'r')
            if address not in edits:
                return m[0]
            seen.add(address)
            return patch_cell(m[0], edits[address], prefix)
        fragment = CELL.sub(replace_cell, fragment)
        for addr in sorted(set(edits) - seen, key=col_number):
            cell = patch_cell(None, edits[addr], prefix)
            following = next((m.start() for m in CELL.finditer(fragment) if col_number(attr(m[0], 'r')) > col_number(addr)), None)
            if following is None:
                end = re.search(rb'</' + PREFIX + rb'row>$', fragment)
                if not end:
                    raise Rejected('不能向未知行结构写入')
                following = end.start()
            fragment = fragment[:following] + cell + fragment[following:]
        return fragment
    new_sheet = ROW.sub(patch_row, raw)
    if touched != set(by_row):
        raise Rejected('补填计划引用不存在的行')
    changed = {}
    if new_sheet != raw:
        changed[member] = new_sheet
    new_styles = styles.export()
    if new_styles != package['xl/styles.xml']:
        changed['xl/styles.xml'] = new_styles
    if not changed:
        return source_bytes, changes
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source_bytes)) as z, zipfile.ZipFile(output, 'w') as dest:
        dest.comment = z.comment
        for info in z.infolist():
            dest.writestr(info, changed.get(info.filename, package[info.filename]))
    return output.getvalue(), changes


def verify(source_bytes, result_bytes, sheet_name, changes):
    before, after = parts(source_bytes), parts(result_bytes)
    if list(before) != list(after):
        raise Rejected('副本增加、删除或重排了包成员')
    member = sheet_member(before, sheet_name)
    allowed = {member, 'xl/styles.xml'}
    unchanged = [n for n in before if before[n] == after[n]]
    if any(before[n] != after[n] for n in before if n not in allowed):
        raise Rejected('副本改变了非补填工作表、箱重或其他部件')
    a, b = ET.fromstring(before[member]), ET.fromstring(after[member])
    old_cells = {c.get('r'): c for c in a.findall('s:sheetData/s:row/s:c', NS)}
    new_cells = {c.get('r'): c for c in b.findall('s:sheetData/s:row/s:c', NS)}
    rows = {int(r.get('r')): r for r in b.findall('s:sheetData/s:row', NS)}
    old_styles = ET.fromstring(before['xl/styles.xml']); new_styles = ET.fromstring(after['xl/styles.xml'])
    xfs_a = list(old_styles.find(Q + 'cellXfs')); xfs_b = list(new_styles.find(Q + 'cellXfs'))
    for d in changes:
        addr = d['cell']; old = old_cells.get(addr); new = new_cells.get(addr)
        if new is None:
            raise Rejected('计划单元格缺失')
        if d.get('write_value') is not None and new.find(Q + 'f') is not None:
            raise Rejected('补填值变成公式')
        if d.get('write_value') is not None:
            if d['value_type'] == 'text':
                value = ''.join(t.text or '' for t in new.findall('.//' + Q + 't'))
                if new.get('t') != 'inlineStr' or value != str(d['write_value']):
                    raise Rejected('补填文本/编码内容不一致')
            elif new.find(Q + 'v').text != str(d['write_value']):
                raise Rejected('补填数值不一致')
        else:
            ref = copy.deepcopy(new); ref.attrib.pop('s', None)
            if old is not None:
                src = copy.deepcopy(old); src.attrib.pop('s', None)
                if signature(ref) != signature(src):
                    raise Rejected('标色改变了原值/公式缓存')
            elif list(ref):
                raise Rejected('空格标色不应写入业务值')
        xf_a = copy.deepcopy(xfs_a[d['base_style_id']]); xf_b = copy.deepcopy(xfs_b[int(new.get('s', '0'))])
        if d['fill_applied']:
            fill = list(new_styles.find(Q + 'fills'))[int(xf_b.get('fillId', '0'))]
            pattern = fill.find(Q + 'patternFill')
            fg = pattern.find(Q + 'fgColor') if pattern is not None else None
            if pattern is None or pattern.get('patternType') != 'solid' or fg is None or fg.get('rgb') != COLORS[d['color']]:
                raise Rejected('单元格颜色与补填/待确认计划不一致')
        elif int(new.get('s', '0')) != d['base_style_id']:
            raise Rejected('原有人工标色样式被替换')
        for xf in (xf_a, xf_b):
            for k in ('fillId', 'applyFill'):
                xf.attrib.pop(k, None)
            xf.tail = None
        if signature(xf_a) != signature(xf_b):
            raise Rejected('标色改变了字体、边框、数字格式或对齐')
        row = rows[int(re.search(r'\d+$', addr)[0])]; index = list(row).index(new)
        row.remove(new)
        if old is not None:
            row.insert(index, copy.deepcopy(old))
    if signature(a) != signature(b):
        raise Rejected('副本改变了保护格、行序、公式、布局或行列属性')
    # Original style definitions must remain intact; only append fills and cloned XFs.
    for name in ('fills', 'cellXfs'):
        old, new = old_styles.find(Q + name), new_styles.find(Q + name)
        for item in list(new)[len(old):]:
            new.remove(item)
        new.attrib.clear(); new.attrib.update(old.attrib)
    if signature(old_styles) != signature(new_styles):
        raise Rejected('副本改写了原样式定义')
    from openpyxl import load_workbook
    workbook = load_workbook(io.BytesIO(result_bytes), read_only=True, data_only=False, keep_links=True)
    try:
        sheet_names = workbook.sheetnames
    finally:
        workbook.close()
    return {'verified': True, 'sheet_names': sheet_names, 'zip_parts': len(before),
            'byte_identical_parts': len(unchanged), 'edited_cells': len(changes),
            'all_other_cells_unchanged': True, 'row_order_preserved': True,
            'formula_and_cache_preserved': True, 'weight_parts_byte_identical': True,
            'original_styles_preserved_except_planned_fills': True, 'reopened': True}
