"""Numeric, blank-only U/V/W/X overlay; all other ZIP parts stay byte-exact."""
from pathlib import Path
import copy
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from .service import MvpError, digest
from .xlsxio import sheet_info, read_book, col_number, Q


def edits(rows):
    changes = {}
    def integer(value):
        return value is not None and value['denominator'] == '1'
    for row in rows:
        quantity = row['quantity']
        proposed = {}
        if integer(quantity['results'].get('piece')):
            proposed['X'] = quantity['results']['piece']['numerator']
        if integer(quantity['results'].get('box')) and (not quantity['remainder'] or quantity['remainder']['remaining_pieces']['numerator'] == '0'):
            proposed['U'] = quantity['results']['box']['numerator']
        if integer(quantity.get('v_size')):
            proposed['V'] = quantity['v_size']['numerator']
        blind = quantity.get('blind')
        if blind:
            proposed['W'] = '是' if blind['value'] else '否'
        for col, value in proposed.items():
            if row['existing'].get(col, '') == '' and col not in row['formulas']:
                changes[col + str(row['row'])] = value
    return changes


def compare(source, output, sheet, changes):
    a, b = read_book(source), read_book(output)
    if len(a['sheets']) != len(b['sheets']):
        raise MvpError('TASK_CONFLICT', '输出工作表变化')
    for old, new in zip(a['sheets'], b['sheets']):
        if old['name'] != new['name'] or old['merges'] != new['merges'] or len(old['rows']) != len(new['rows']):
            raise MvpError('TASK_CONFLICT', '输出结构变化')
        for r, s in zip(old['rows'], new['rows']):
            r, s = copy.deepcopy(r), copy.deepcopy(s)
            if r['row'] != s['row']:
                raise MvpError('TASK_CONFLICT', '输出行序变化')
            for col in set(r['values']) | set(s['values']):
                address = col + str(r['row'])
                if old['name'] == sheet and address in changes:
                    if s['values'].get(col) != changes[address] or col in r['formulas'] or r['values'].get(col, '') != '':
                        raise MvpError('TASK_CONFLICT', '输出不是合法空格补充：'+address)
                    for item in (r,s):
                        item['values'].pop(col,None)
                        item['types'].pop(col,None)
            if r != s:
                raise MvpError('TASK_CONFLICT', '非目标单元格变化：'+str(r['row']))
    member = next(s['path'] for s in sheet_info(source) if s['name'] == sheet)
    with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
        if a.namelist() != b.namelist():
            raise MvpError('TASK_CONFLICT', '输出ZIP部件变化')
        unchanged = 0
        for name in a.namelist():
            if name != member:
                if a.read(name) != b.read(name):
                    raise MvpError('TASK_CONFLICT', '非目标ZIP部件变化：'+name)
                unchanged += 1
        # Styles/row attributes/non-cell main-sheet content must also remain.
        old, new = ET.fromstring(a.read(member)), ET.fromstring(b.read(member))
        for tree in (old,new):
            for r in tree.findall(Q+'sheetData/'+Q+'row'):
                for cell in list(r):
                    if cell.get('r') in changes:
                        r.remove(cell)
        if ET.tostring(old) != ET.tostring(new):
            raise MvpError('TASK_CONFLICT', '非目标XML结构变化')
    return {'changed_cells': len(changes), 'non_target_cell_changes':0,
            'non_target_parts_byte_equal':unchanged, 'formulas_and_caches_preserved':True,
            'images_and_weight_parts_preserved':True}


def export(source, destination, sheet, changes):
    source, destination = Path(source), Path(destination)
    member = next(s['path'] for s in sheet_info(source) if s['name'] == sheet)
    temp = destination.with_suffix('.quantity.tmp')
    # A deterministic uncommitted export can be rebuilt after interruption.
    with zipfile.ZipFile(source) as old:
        tree = ET.fromstring(old.read(member))
        cells = {c.get('r'): c for c in tree.findall(Q+'sheetData/'+Q+'row/'+Q+'c')}
        rows = {r.get('r'): r for r in tree.findall(Q+'sheetData/'+Q+'row')}
        for address, value in sorted(changes.items()):
            if not re.fullmatch('[UVWX][0-9]+', address):
                raise MvpError('INPUT_INVALID', '数量导出只允许U/V/W/X')
            cell = cells.get(address)
            if cell is not None and (cell.find(Q+'f') is not None or cell.find(Q+'v') is not None or ''.join(cell.itertext()).strip()):
                raise MvpError('TASK_CONFLICT', '数量导出禁止覆盖已有格：'+address)
            row = rows[re.search('[0-9]+',address)[0]]
            if cell is None:
                cell = ET.SubElement(row,Q+'c',{'r':address})
            for child in list(cell):
                cell.remove(child)
            if address[0] == 'W':
                cell.set('t','inlineStr')
                ET.SubElement(ET.SubElement(cell,Q+'is'),Q+'t').text = value
            else:
                cell.set('t','n')
                ET.SubElement(cell,Q+'v').text = value
            row[:] = sorted(row,key=lambda c: col_number(re.match('[A-Z]+',c.get('r'))[0]))
        with zipfile.ZipFile(temp,'w',allowZip64=True) as out:
            for info in old.infolist():
                out.writestr(info,ET.tostring(tree,encoding='utf-8',xml_declaration=True) if info.filename == member and changes else old.read(info.filename))
    proof = compare(source,temp,sheet,changes)
    if destination.exists():
        with zipfile.ZipFile(destination) as a, zipfile.ZipFile(temp) as b:
            if a.namelist() != b.namelist() or any(a.read(n) != b.read(n) for n in a.namelist()):
                raise MvpError('TASK_CONFLICT', '既有数量输出不一致，禁止覆盖')
        temp.unlink()
    else:
        os.replace(temp,destination)
    return {'path':str(destination),'sha256':digest(destination),'preservation':proof}
