"""Narrow 11/16-column price-input seam over the unchanged business loop.

The source workbook is never projected or rewritten.  Row coordinates, cached
amounts and provenance stay in their supplied layouts; units remain unknown.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from .support import Rejected, digest, load_module

NATIVE16 = 'kmt-native-16-v1'
RAW11 = 'kmt-raw-invoice-v1'


def read_invoice(file, legacy):
    from native22.profiles import inspect_source
    from arrival_core import _p0_frozen as p0
    s = inspect_source(file)
    if s['profile_id'] == RAW11:
        rows, s = legacy(file)
    elif s['profile_id'] == NATIVE16:
        rows = []
        t = s['sheet']
        source_rows = {r['source']['row']: r for r in s['batch']['rows']}
        for r in s['rows']:
            n = r['source_row']
            carton = source_rows[n]['raw']['carton']
            code, ja, origin = [p0.text(t.v(n, c)) for c in ('C', 'I', 'B')]
            rows.append({'row': n, 'identity': [carton, '', code, ja, '', '', origin],
                         'carton': carton, 'code': code, 'ja': ja, 'origin': origin,
                         'price': p0.text(t.v(n, 'K')), 'quantity': p0.text(t.v(n, 'J')),
                         'amount': p0.text(t.v(n, 'L')), 'source': deepcopy(r['source']),
                         'weight_observation': ''})
        totals = []
        for n in t.rows:
            if p0.text(t.v(n, 'I')).upper() == 'TOTAL':
                try:
                    valid = (Fraction(p0.text(t.v(n, 'J'))) == sum(Fraction(r['quantity']) for r in rows)
                             and Fraction(p0.text(t.v(n, 'L'))) == sum(Fraction(r['amount']) for r in rows))
                except (ValueError, ZeroDivisionError):
                    valid = False
                totals.append({'row': n, 'amount_cell': 'L' + str(n),
                               'quantity_cell': 'J' + str(n), 'consistent': valid})
        s['loop_total_checks'] = totals
    else:
        raise Rejected('日方价格更新仅支持已登记11列原表或完整16列布局，不猜其他业务成品列')
    for r in rows:
        r.update(currency='JPY', price_unit=None, quantity_unit=None,
                 unit_status='source_pricing_and_quantity_units_unconfirmed',
                 packaging_status='independent_packaging_evidence_required',
                 price_version={'sha256': s['book'].sha256, 'profile': s['profile_id'],
                                'sheet': s['sheet'].name, 'row': r['row']})
    return rows, s


def source_row(row, old):
    """Only raw11's existing projection has the historical +16 row offset."""
    return row['source']['row'] + (16 if old['profile_id'] == RAW11 else 0)


def identity_key(row, old):
    if old['profile_id'] == RAW11:
        return tuple(row['identity'])
    # Native16 has no Ref/HS columns. Do not invent values for those fields.
    return tuple(row[k] for k in ('carton', 'code', 'ja', 'origin'))


def valid_link(proof, old=None):
    allowed = [{'new_row', 'reference'}]
    if old and old['profile_id'] == NATIVE16:
        allowed.append({'new_row', 'reference', 'code_link'})
    return isinstance(proof, dict) and set(proof) in allowed


def link_matches(original, new, old, proof, view, row_id):
    if identity_key(original, old) == identity_key(new, old):
        return True
    if old['profile_id'] != NATIVE16 or 'code_link' not in proof:
        return False
    if any(original[k] != new[k] for k in ('carton', 'ja', 'origin')):
        return False
    link = proof['code_link']
    if not isinstance(link, dict) or set(link) != {'path', 'sha256', 'sheet', 'row', 'columns'}:
        raise Rejected('跨主JAN/pcs关联须有完整原文件SHA和单元格坐标')
    columns = link['columns']
    if set(columns) != {'jan', 'pcs', 'name', 'spec'} or any(
            not isinstance(c, str) or not c.isalpha() or not c.isupper() for c in columns.values()):
        raise Rejected('主JAN/pcs关联列未明确定义')
    if not isinstance(link['row'], int) or link['row'] < 2:
        raise Rejected('主JAN/pcs关联来源行无效')
    file = Path(link['path']).resolve(strict=True)
    if digest(file) != link['sha256']:
        raise Rejected('主JAN/pcs关联来源SHA变化')
    from arrival_core import _p0_frozen as p0
    book = p0.Book(file.read_bytes(), str(file))
    sheets = [s for s in book.sheets if s.name == link['sheet']]
    if len(sheets) != 1:
        raise Rejected('主JAN/pcs关联来源工作表无法唯一定位')
    values = {k: p0.text(sheets[0].v(link['row'], c)) for k, c in columns.items()}
    fields = {f['field']: f for f in view['fields'].values() if f['row_id'] == row_id}
    expected = {'jan': original['code'], 'pcs': new['code'],
                'name': fields.get('internal_name', {}).get('value', {}).get('value'),
                'spec': fields.get('specification', {}).get('value', {}).get('value')}
    if digest(file) != link['sha256']:
        raise Rejected('主JAN/pcs关联来源读取期间变化')
    return all(values[k] and values[k] == expected[k] for k in values)


def weight_sheet(book, source):
    names = source['weights']
    sheets = [s for s in book.sheets if s.name in names]
    if len(sheets) != 1:
        raise Rejected('箱重页无法按已登记布局唯一定位')
    return sheets[0]


def load_updates(name, file):
    """Replace only fixed layout seams; CAS, matching loop and commit stay frozen."""
    replace = {
        "oldcounts=Counter(tuple(r['identity']) for r in oldrows)":
            'oldcounts=Counter(_price_identity_key(r,old) for r in oldrows)',
        "bykey[tuple(r['identity'])].append(r)": 'bykey[_price_identity_key(r,old)].append(r)',
        "original=oldbyrow.get(row['source']['row']+16)":
            'original=oldbyrow.get(_price_source_row(row,old))',
        "candidates=bykey[tuple(original['identity'])]":
            'candidates=bykey[_price_identity_key(original,old)]',
        "if set(proof)!={'new_row','reference'}": 'if not _valid_price_link(proof,old)',
        "r['row']==proof['new_row'] and r['identity']==original['identity']":
            "r['row']==proof['new_row'] and _price_link_matches(original,r,old,proof,view,rid)",
        "oldcounts[tuple(original['identity'])]": 'oldcounts[_price_identity_key(original,old)]',
        "next(s for s in ob.sheets if s.name=='重さとサイズ')": '_price_weight_sheet(ob,old)',
        "next(s for s in nb.sheets if s.name=='重さとサイズ')": '_price_weight_sheet(nb,new)',
    }
    source = Path(file).read_text(encoding='utf-8')
    if any(source.count(a) != 1 for a in replace):
        raise Rejected('冻结价格更新适配点不唯一或已改变')
    module = load_module(name, file, replace)
    legacy = module.invoice
    module.invoice = lambda file: read_invoice(file, legacy)
    module._price_source_row = source_row
    module._price_identity_key = identity_key
    module._valid_price_link = valid_link
    module._price_link_matches = link_matches
    module._price_weight_sheet = weight_sheet
    return module
