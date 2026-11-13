import tempfile,unittest,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
from openpyxl import Workbook,load_workbook
from openpyxl.styles import PatternFill
from interaction import save,load,digest
from interaction.attention_display import apply_attention
class AttentionTests(unittest.TestCase):
 def test_only_real_issues_colored_and_every_value_formula_manual_cell_preserved(self):
  with tempfile.TemporaryDirectory() as folder:
   d=Path(folder);f=d/'file.xlsx';w=Workbook();s=w.active;s.title='invoice (計算)';s.append(list(range(20)))
   for n in [2,3]:
    s.append([None]*20)
    for c in s[n]:c.fill=PatternFill('solid',fgColor='FFA500')
   for cell,value in {'F2':'中文','G2':'规格','H2':777.4,'M2':'=K2*L2','N2':'人工品类','O2':'人工材质','G3':'规格'}.items():s[cell]=value
   w.save(f)
   save(d/'evidence.json',{'rows':{'2':{'values':{'name':'中文','spec':'规格','price':777.4},'price_review':{'category':'safe_linked_box_order_quote','purchase_unit':'盒'}},'3':{'values':{'spec':'规格'},'price_review':{'category':'true_price_conflict'}}}})
   with zipfile.ZipFile(f) as z:before=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
   apply_attention(f,{'background':str(d),'sheet':s.title})
   r=load(d/'business-attention.json')['summary'];self.assertEqual(r['colored_cells'],2);self.assertEqual(r['yellow_cells'],1);self.assertEqual(r['red_cells'],1);self.assertEqual(r['records_requiring_human_action'],1)
   with zipfile.ZipFile(f) as z:after=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
   Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
   def facts(root):return {c.get('r'):(c.get('t'),[ET.tostring(v) for v in c]) for c in root.iter(Q+'c')}
   self.assertEqual(facts(before),facts(after));wb=load_workbook(f);ws=wb.active
   for a in ['H2','M2','N2','O2','S2','T2']:self.assertIsNone(ws[a].fill.patternType)
   self.assertEqual(ws['F3'].fill.fgColor.rgb,'FFFFF2CC');self.assertEqual(ws['H3'].fill.fgColor.rgb,'FFFCE4D6');self.assertEqual(ws['H2'].value,777.4);self.assertEqual(ws['H2'].number_format,'0.########"日元/盒"');wb.close()
   stamp=f.stat().st_mtime_ns;sha=digest(f);apply_attention(f,{'background':str(d),'sheet':s.title});self.assertEqual((digest(f),f.stat().st_mtime_ns),(sha,stamp))
