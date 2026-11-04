"""Generalized approved example patcher. Preserve original ZIP parts and caches."""
import copy
import io
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile
from .support import Rejected


def render(source_bytes, sheet_name, formulas, format_cells, marks):
    from native_copy import ooxml as x
    from native_return.compare import read, passive_links
    package = x.parts(source_bytes); member = x.sheet_member(package, sheet_name)
    raw = package[member]; original = ET.fromstring(raw)
    original_cells = {c.get('r'): c for c in original.findall('s:sheetData/s:row/s:c', x.NS)}
    colors = {m['cell']: 'FFF4CCCC' for m in marks}
    targets = set(formulas) | set(format_cells) | set(colors)
    if not targets:
        return source_bytes, {'verified': True, 'formula_changes': [], 'edited_cells': [],
                              'protected_formulas_and_caches_unchanged': True,
                              'byte_identical_parts': len(package), 'zip_parts': len(package),
                              'weight_parts_byte_identical': True}
    prefix = re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b', raw)[1] or b''
    # Reject downstream dependencies, rather than publish stale original caches.
    altered_helpers = {a for a in formulas if a.startswith(('H', 'U'))}
    if altered_helpers:
        wb, _ = read(source_bytes, trusted_external=passive_links(source_bytes))
        try:
            for ws in wb:
                for cell in ws._cells.values():
                    if cell.data_type != 'f' or (ws.title == sheet_name and cell.coordinate in formulas): continue
                    f = cell.value.replace('$', '')
                    if ws.title != sheet_name:
                        if not re.search(r"(?:'"+re.escape(sheet_name)+r"'|"+re.escape(sheet_name)+r")![HU]", f, re.I): continue
                    refs = set(re.findall(r'(?<![A-Za-z0-9_])[HU]\d+', f, re.I))
                    if refs & altered_helpers or re.search(r'(?<!\w)(?:H:H|U:U)', f, re.I):
                        raise Rejected('盒规/验算重算存在未支持的下游依赖：'+ws.title+'!'+cell.coordinate)
        finally: wb.close()
    styles = x.Styles(package['xl/styles.xml']); style_cache = {}; fill_cache = {}; touched = set()
    def style_for(base, *, two_decimals=False, color=None):
        token = (base, two_decimals, color)
        if token in style_cache: return style_cache[token]
        xf = (styles.fragments+styles.extra_xfs)[base]
        if two_decimals: xf = x.set_attr(x.set_attr(xf, 'numFmtId', '2'), 'applyNumberFormat', '1')
        if color:
            if color not in fill_cache:
                fill_cache[color] = len(styles.fills)+len(styles.extra_fills); p = styles.p
                styles.extra_fills.append(b'<'+p+b'fill><'+p+b'patternFill patternType="solid"><'+p+b'fgColor rgb="'+color.encode()+b'"/><'+p+b'bgColor indexed="64"/></'+p+b'patternFill></'+p+b'fill>')
            xf = x.set_attr(x.set_attr(xf, 'fillId', fill_cache[color]), 'applyFill', '1')
        index = len(styles.xfs)+len(styles.extra_xfs); styles.extra_xfs.append(xf); style_cache[token] = index
        return index
    columns = original.findall('s:cols/s:col', x.NS)
    def change_cell(fragment, address):
        rawcell = fragment or b'<'+prefix+b'c r="'+address.encode()+b'"/>'
        touched.add(address)
        base = int(x.attr(rawcell, 's') or '0')
        if not x.attr(rawcell, 's'):
            for c in columns:
                if int(c.get('min')) <= x.col_number(address) <= int(c.get('max')): base = int(c.get('style', '0'))
        if address in format_cells or address in colors:
            rawcell = x.set_attr(rawcell, 's', style_for(base, two_decimals=address in format_cells, color=colors.get(address)))
        if address in formulas:
            item = formulas[address]; at = rawcell.index(b'>')+1; head, body = rawcell[:at], rawcell[at:]
            head = re.sub(rb'\s+t="[^"]*"', b'', head)
            if head.endswith(b'/>'): head = head[:-2]+b'>'; body = b'</'+prefix+b'c>'
            if item['value'] is None: head = x.set_attr(head, 't', 'str')
            body = re.sub(rb'<'+x.PREFIX+rb'(?:f|v|is)\b[^>]*?(?:/>|>.*?</'+x.PREFIX+rb'(?:f|v|is)>)', b'', body, flags=re.S)
            f = b'<'+prefix+b'f>'+escape(item['formula'][1:]).encode()+b'</'+prefix+b'f>'
            v = b'<'+prefix+b'v>'+(format(item['value'], 'f').encode() if item['value'] is not None else b'')+b'</'+prefix+b'v>'
            rawcell = head+f+v+body
        return rawcell
    row_targets = {}
    for a in targets: row_targets.setdefault(int(re.search(r'\d+$', a)[0]), set()).add(a)
    def change_row(match):
        fragment = match[0]; ri = int(x.attr(fragment, 'r')); selected = row_targets.get(ri, set()); seen = set()
        if not selected: return fragment
        def replace(c):
            address = x.attr(c[0], 'r')
            if address not in selected: return c[0]
            seen.add(address); return change_cell(c[0], address)
        fragment = x.CELL.sub(replace, fragment)
        for address in sorted(selected-seen, key=x.col_number):
            cell = change_cell(None, address)
            following = next((m.start() for m in x.CELL.finditer(fragment) if x.col_number(x.attr(m[0], 'r')) > x.col_number(address)), None)
            if following is None:
                end = re.search(rb'</'+x.PREFIX+rb'row>$', fragment)
                if end is None: raise Rejected('无法识别的原行结构')
                following = end.start()
            fragment = fragment[:following]+cell+fragment[following:]
        return fragment
    new_raw = x.ROW.sub(change_row, raw)
    if touched != targets: raise Rejected('计算/标色目标不属于已存在原行')
    dest = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source_bytes)) as src, zipfile.ZipFile(dest, 'w') as out:
        out.comment = src.comment
        for info in src.infolist():
            out.writestr(info, new_raw if info.filename == member else styles.export() if info.filename == 'xl/styles.xml' else package[info.filename])
    result = dest.getvalue(); final = x.parts(result)
    if list(package) != list(final): raise Rejected('包结构变化')
    if any(package[n] != final[n] for n in package if n not in (member, 'xl/styles.xml')): raise Rejected('非目标页或箱重发生变化')
    tree = ET.fromstring(final[member]); restored = set()
    for row in tree.findall('s:sheetData/s:row', x.NS):
        for cell in list(row):
            address = cell.get('r')
            if address in targets:
                i = list(row).index(cell)
                row.remove(cell)
                if address in original_cells: row.insert(i, copy.deepcopy(original_cells[address]))
                restored.add(address)
    if restored != targets or x.signature(original) != x.signature(tree): raise Rejected('原行序、非目标值、公式或布局变化')
    oldstyles = ET.fromstring(package['xl/styles.xml']); newstyles = ET.fromstring(final['xl/styles.xml'])
    for name in ('fills', 'cellXfs'):
        a, b = oldstyles.find(x.Q+name), newstyles.find(x.Q+name)
        for child in list(b)[len(a):]: b.remove(child)
        b.attrib.clear(); b.attrib.update(a.attrib)
    if x.signature(oldstyles) != x.signature(newstyles): raise Rejected('原样式定义被覆盖')
    wb, parsed = read(result, trusted_external=passive_links(source_bytes))
    try:
        sheet = next(s for s in parsed.sheets if s.name == sheet_name)
        for address, expected in formulas.items():
            cell = sheet.cells[address]
            if cell.get('f') != expected['formula'] or not (cell.get('v') == expected['value'] or expected['value'] is None and cell.get('v') in (None, '')):
                raise Rejected('计算公式或受控缓存不一致：'+address)
        for address in format_cells:
            if wb[sheet_name][address].number_format != '0.00': raise Rejected('价格显示精度不一致')
        for address in colors:
            if wb[sheet_name][address].fill.fgColor.rgb != colors[address]: raise Rejected('警示标色不一致')
    finally: wb.close()
    return result, {'verified': True, 'formula_changes': [{'cell': a, 'original_formula': original_cells[a].find(x.Q+'f').text if a in original_cells and original_cells[a].find(x.Q+'f') is not None else None,
                                                         'working_formula': f['formula'], 'working_cache': str(f['value'])} for a, f in formulas.items()],
                    'edited_cells': sorted(targets), 'protected_formulas_and_caches_unchanged': True,
                    'byte_identical_parts': sum(package[n] == final[n] for n in package), 'zip_parts': len(package),
                    'weight_parts_byte_identical': True, 'original_styles_append_only': True,
                    'row_order_preserved': True, 'reopened': True}
