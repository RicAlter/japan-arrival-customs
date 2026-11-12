"""Minimal OOXML technical fixtures; no real business values or approvals."""
import sys,tempfile,unittest,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction.calculation_view import patch_workbook,confirmation_attention,Q,view_token

class ConfirmationViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'source.xlsx';self.authored=self.root/'cells.xlsx';self.out=self.root/'out.xlsx'
        self.sheet='<worksheet xmlns="'+Q[1:-1]+'"><dimension ref="A1:U3"/><cols><col min="1" max="21" width="16"/></cols><sheetData><row r="1"><c r="U1" s="0" t="str"><v>reference</v></c></row><row r="2"><c r="I2" s="0"><f>ROUND(M2/(K2/L2),0)</f><v>100</v></c><c r="K2" s="0"><v>20</v></c><c r="L2"><v>20</v></c><c r="M2"><v>100</v></c><c r="N2"><f>L2*M2</f><v>2000</v></c><c r="U2" s="0" t="str"><v>box</v></c></row></sheetData></worksheet>'
        styles='<styleSheet xmlns="'+Q[1:-1]+'"><fonts count="1"><font/></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs></styleSheet>'
        with zipfile.ZipFile(self.source,'w')as z:
            z.writestr('xl/worksheets/sheet1.xml',self.sheet);z.writestr('xl/styles.xml',styles);z.writestr('xl/workbook.xml','<workbook xmlns="'+Q[1:-1]+'"/>'.replace('/>','></workbook>'))
            z.writestr('xl/worksheets/sheet2.xml','unchanged weight');z.writestr('xl/media/image1.png',b'unchanged image')
        with zipfile.ZipFile(self.authored,'w')as z:
            z.writestr('xl/worksheets/sheet1.xml','<worksheet><sheetData><row r="2"><c r="I2"><f>ROUND(M2/(K2/L2),0)</f><v>50</v></c><c r="K2"><v>40</v></c><c r="V2" t="str"><v>backend reason</v></c></row></sheetData></worksheet>')
    def build(self,**kw):
        patch_workbook(self.source,self.authored,self.out,{2},'version',**kw)
        with zipfile.ZipFile(self.out)as z:return ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    def test_compact_has_only_original_columns_and_no_reason_cells(self):
        s=self.build(compact=True);self.assertEqual(s.find(Q+'dimension').get('ref'),'A1:U3');self.assertIsNone(s.find('.//'+Q+'c[@r="V2"]'));self.assertEqual(len(s.find(Q+'cols')),1)
    def test_detailed_layout_remains_available(self):
        s=self.build();self.assertEqual(s.find(Q+'dimension').get('ref'),'A1:AM3');self.assertIsNotNone(s.find('.//'+Q+'c[@r="V2"]'))
    def test_I_and_K_update_but_original_amount_formula_cache_stays(self):
        s=self.build(compact=True);self.assertEqual(s.find('.//'+Q+'c[@r="I2"]/'+Q+'v').text,'50');self.assertEqual(s.find('.//'+Q+'c[@r="N2"]/'+Q+'v').text,'2000');self.assertEqual(s.find('.//'+Q+'c[@r="N2"]/'+Q+'f').text,'L2*M2')
    def test_colors_use_stage_one_palette_without_changing_text(self):
        for kind,color in [('yellow','FFFFF2CC'),('red','FFFCE4D6')]:
            s=self.build(compact=True,attention={'U2':kind});c=s.find('.//'+Q+'c[@r="U2"]');self.assertEqual(c.find(Q+'v').text,'box')
            with zipfile.ZipFile(self.out)as z:styles=ET.fromstring(z.read('xl/styles.xml'))
            xf=styles.find(Q+'cellXfs')[int(c.get('s'))];fill=styles.find(Q+'fills')[int(xf.get('fillId'))];self.assertEqual(fill.find(Q+'patternFill/'+Q+'fgColor').get('rgb'),color)
    def test_original_images_weight_and_version_preserved(self):
        self.build(compact=True)
        self.assertEqual(view_token(self.out),'"version"')
        with zipfile.ZipFile(self.source)as a,zipfile.ZipFile(self.out)as b:
            for name in ['xl/media/image1.png','xl/worksheets/sheet2.xml']:self.assertEqual(a.read(name),b.read(name))
    def test_only_explicit_box_missing_rule_is_yellow(self):
        facts=[{'identity':{'spec':s}}for s in ['本体','整盒17','整盒']]
        rows=[dict(row=n,errors=['缺独立盒规，参考盒数待核']if n<4 else ['推导盒数与参考盒数冲突'],rounded_price=10)for n in [2,3,4]]
        self.assertEqual(confirmation_attention(facts,rows),{'U3':'yellow','U4':'red'})
    def result_fixture(self):
        with zipfile.ZipFile(self.authored,'w')as z:
            z.writestr('xl/worksheets/sheet1.xml','<worksheet><sheetData><row r="1"><c r="V1" t="str"><v>boxes</v></c><c r="Z1" t="str"><v>row tax</v></c></row><row r="2"><c r="I2"><v>50</v></c><c r="K2"><v>40</v></c><c r="V2"><v>4</v></c><c r="W2"><f>I2*K2</f><v>2000</v></c><c r="X2"><v>0</v></c><c r="Z2"><v>260</v></c></row></sheetData></worksheet>')
    def test_results_layout_keeps_boxes_amount_and_tax_columns(self):
        self.result_fixture();s=self.build(results_only=True)
        self.assertEqual(s.find(Q+'dimension').get('ref'),'A1:Z3')
        self.assertEqual(s.find('.//'+Q+'c[@r="V2"]/'+Q+'v').text,'4')
        self.assertEqual(s.find('.//'+Q+'c[@r="Z2"]/'+Q+'v').text,'260')
        self.assertEqual(s.find('.//'+Q+'c[@r="W2"]/'+Q+'f').text,'I2*K2')
        self.assertEqual(len(s.find(Q+'cols')),6)
    def test_unavailable_tax_is_blank_red_without_explanation(self):
        self.result_fixture();s=self.build(results_only=True,attention={'V2':'red','Y2':'red'})
        c=s.find('.//'+Q+'c[@r="Y2"]');self.assertIsNotNone(c);self.assertIsNone(c.find(Q+'v'))
        with zipfile.ZipFile(self.out)as z:styles=ET.fromstring(z.read('xl/styles.xml'))
        xf=styles.find(Q+'cellXfs')[int(c.get('s'))];fill=styles.find(Q+'fills')[int(xf.get('fillId'))]
        self.assertEqual(fill.find(Q+'patternFill/'+Q+'fgColor').get('rgb'),'FFFCE4D6')
        self.assertFalse(any(c.get('r','').startswith(('AA','AB','AM'))for c in s.iter(Q+'c')))
    def test_factor_column_replaces_price_formula_and_header(self):
        with zipfile.ZipFile(self.source)as z:parts={n:z.read(n)for n in z.namelist()}
        parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'<row r="1">',b'<row r="1"><c r="I1" t="str"><v>old price header</v></c>')
        with zipfile.ZipFile(self.source,'w')as z:
            for n,b in parts.items():z.writestr(n,b)
        with zipfile.ZipFile(self.authored,'w')as z:z.writestr('xl/worksheets/sheet1.xml','<worksheet><sheetData><row r="1"><c r="I1" t="str"><v>倍数</v></c></row><row r="2"><c r="I2"><f>K2/L2</f><v>100</v></c><c r="K2"><v>40</v></c></row></sheetData></worksheet>')
        s=self.build(results_only=True,factor_column=True)
        self.assertEqual(s.find('.//'+Q+'c[@r="I1"]/'+Q+'v').text,'倍数')
        self.assertEqual(s.find('.//'+Q+'c[@r="I2"]/'+Q+'f').text,'K2/L2')
    def test_clear_inapplicable_reference_keeps_quantity_and_raw_archive(self):
        s=self.build(results_only=True,clear_references={'U2'})
        self.assertIsNone(s.find('.//'+Q+'c[@r="U2"]/'+Q+'v'))
        self.assertEqual(s.find('.//'+Q+'c[@r="L2"]/'+Q+'v').text,'20')
        with zipfile.ZipFile(self.source)as z:self.assertIn(b'<v>box</v>',z.read('xl/worksheets/sheet1.xml'))
