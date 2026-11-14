"""Deterministic reader/mapping tests. Fixtures are constructed, not approvals."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rebuild_mvp.xlsxio import (Q, R, WorkbookError, detect_header, extract_batch,
                                iter_rows, read_book, remap_formula, translate_formula)


def fixture(path, duplicate=False):
    # Fields deliberately moved; 3-row carton merge followed by an unmerged gap.
    def string(c, r, value):
        return f'<c r="{c}{r}" t="inlineStr"><is><t>{value}</t></is></c>'
    headers = {'A':'Qty','B':'Origin','C':'DescriptionofGoods','D':'UnitPrice(日本JPY)',
               'E':'CartonNo.','F':'Subtotal','G':'ProductCode(JANCode)'}
    if duplicate:
        headers['H'] = 'Qty'
    top = '<row r="4">' + ''.join(string(c,4,v) for c,v in headers.items()) + '</row>'
    rows = [top]
    for n in range(5,9):
        cells = string('G',n,'0012345678901') + string('C',n,'日本商品') + string('B',n,'JP')
        cells += f'<c r="A{n}"><v>2</v></c><c r="D{n}"><v>12.50</v></c>'
        cells += f'<c r="F{n}"><f t="shared" si="0"' + (f' ref="F5:F8">A5*D5' if n==5 else '>') + '</f><v>25</v></c>'
        if n==5:
            cells += string('E',n,'BOX01')
        rows.append(f'<row r="{n}">{cells}</row>')
    rows.append('<row r="9"><c r="A9"><f>SUM(A5:A8)</f><v>8</v></c><c r="F9"><f>SUM(F5:F8)</f><v>100</v></c></row>')
    main = f'<worksheet xmlns="{Q[1:-1]}"><sheetData>{"".join(rows)}</sheetData><mergeCells count="1"><mergeCell ref="E5:E7"/></mergeCells></worksheet>'
    weight = f'<worksheet xmlns="{Q[1:-1]}"><sheetData><row r="1">{string("A",1,"箱番")}{string("B",1,"重さ")}</row></sheetData></worksheet>'
    workbook = f'<workbook xmlns="{Q[1:-1]}" xmlns:r="{R[1:-1]}"><sheets><sheet name="invoice (計算)" sheetId="1" r:id="rId1"/><sheet name="重さとサイズ" sheetId="2" r:id="rId2"/></sheets></workbook>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml',workbook)
        z.writestr('xl/_rels/workbook.xml.rels',rels)
        z.writestr('xl/worksheets/sheet1.xml',main)
        z.writestr('xl/worksheets/sheet2.xml',weight)


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'raw.xlsx'
        fixture(self.path)
    def tearDown(self):
        self.tmp.cleanup()
    def test_dynamic_fields_and_leading_zero(self):
        b = extract_batch(self.path)
        self.assertEqual(b['metadata']['header_row'],4)
        self.assertEqual(b['metadata']['mapping']['code'],'G')
        self.assertEqual(b['rows'][0]['raw']['code'],'0012345678901')
        self.assertEqual(b['rows'][0]['source_row'],5)
    def test_exact_merge_scope_no_forward_fill(self):
        b = extract_batch(self.path)
        self.assertEqual([r['raw']['carton'] for r in b['rows']],['BOX01','BOX01','BOX01',''])
        self.assertEqual(b['rows'][-1]['issues'][0]['code'],'CARTON_MISSING')
    def test_original_value_and_shared_formula_cache(self):
        b = extract_batch(self.path)
        self.assertEqual(b['rows'][1]['raw_cells']['amount']['formula'],'A6*D6')
        self.assertEqual(b['rows'][1]['raw_cells']['amount']['value'],'25')
        self.assertEqual(b['rows'][1]['raw']['jpy_price'],'12.50')
    def test_totals_are_auxiliary_not_products(self):
        b = extract_batch(self.path)
        self.assertEqual(len(b['rows']),4)
        self.assertEqual(b['metadata']['other_raw_rows'][0]['row'],9)
    def test_identity_repeatable_and_input_unchanged(self):
        before = self.path.read_bytes()
        a,b=extract_batch(self.path),extract_batch(self.path)
        self.assertEqual(a['rows'],b['rows'])
        self.assertEqual(before,self.path.read_bytes())
    def test_duplicate_header_requires_mapping(self):
        fixture(self.path,duplicate=True)
        with self.assertRaises(WorkbookError) as error:
            extract_batch(self.path)
        self.assertEqual(error.exception.code,'FIELD_MAPPING_AMBIGUOUS')
    def test_streaming_reader_preserves_rows(self):
        rs=list(iter_rows(self.path,'invoice (計算)'))
        self.assertEqual([r['row'] for r in rs],[4,5,6,7,8,9])
        self.assertEqual(rs[-1]['formulas']['F'],'SUM(F5:F8)')
    def test_translate_shared_formula_absolute_and_literal(self):
        self.assertEqual(translate_formula('A5*$B$2+C$3+"A5"',1,2),'B7*$B$2+D$3+"A5"')
    def test_main_formula_remap_weight_and_absolute(self):
        formula="I18*H18+重さとサイズ!$D$196+'invoice (計算)'!$K$2889"
        self.assertEqual(remap_formula(formula,{'I':'K','H':'L','K':'M'},-16,'invoice (計算)','重さとサイズ'),
                         "K2*L2+重さとサイズ!$D$196+'invoice (計算)'!$M$2873")
    def test_unknown_formula_dependency_rejected(self):
        with self.assertRaises(WorkbookError):
            remap_formula('Z18',{'I':'K'},-16,'invoice (計算)','重さとサイズ')


if __name__=='__main__':
    unittest.main()
