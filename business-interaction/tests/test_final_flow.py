import unittest,tempfile,json,zipfile,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction.test_final import project,generate,current,restore_weight_caches,NS
from interaction.stage2_math import calculate
from interaction import Rejected,save
from interaction.submission import Service

class FinalFlowTests(unittest.TestCase):
    def fixture(self,**changes):
        f=dict(source_row=2,row_id='row',code='123',carton='A01',quantity=60,price=202,amount=12120,total_pieces=180,reference_boxes=5,duty_rate=0,vat_rate='.13',pack_candidates=[],identity=dict(code='123',name='内部中文商品',spec='整盒17',yd='YD1234'))
        f.update(changes);r=calculate(f)
        v=['A01','JP','123','JC',None,'内部中文商品','整盒17',None,None,'Japanese description',f['total_pieces'],f['quantity'],f['price'],f['amount'],'徽章','马口铁',None,'YD1234',None,None,None]
        v += [float(r['values'][i])if r['values'][i]is not None else None for i in [3,7,8,13,14]]
        return f,[[],v]
    def test_missing_box_rule_retains_sourced_boxes_without_approval(self):
        f,v=self.fixture();p=project([f],v)
        self.assertEqual(p['internal']['rows'][0][7],5);self.assertEqual(p['customs']['rows'][0][4],5)
        self.assertFalse(p['trace'][0]['professional_approval']);self.assertIn('H4',p['colors']['internal'])
    def test_original_units_amount_and_rounding_difference_separate(self):
        f,v=self.fixture();p=project([f],v)
        self.assertEqual(p['internal']['rows'][0][8:11],[60,202,12120]);self.assertEqual(p['customs']['rows'][0][5:7],[180,67]);self.assertEqual(p['totals']['rounded_amount']-p['totals']['original_amount'],-60)
    def test_tax_uses_original_price_not_rounded_single_price(self):
        f,v=self.fixture();p=project([f],v)
        self.assertAlmostEqual(p['internal']['rows'][0][17],315.12);self.assertAlmostEqual(p['internal']['rows'][0][20],1575.6)
    def test_zero_rate_is_valid(self):
        f,v=self.fixture();p=project([f],v);self.assertEqual(p['internal']['rows'][0][16],0)
    def test_missing_tax_stays_blank_not_zero(self):
        f,v=self.fixture(duty_rate=None);p=project([f],v)
        self.assertIsNone(p['internal']['rows'][0][20]);self.assertEqual(p['colors']['internal']['U4'],'red')
    def test_protected_quantity_drift_rejected(self):
        f,v=self.fixture();v[1][11]=61
        with self.assertRaises(Rejected):project([f],v)
    def test_saved_calculation_drift_rejected(self):
        f,v=self.fixture();v[1][21]=6
        with self.assertRaises(Rejected):project([f],v)
    def test_public_table_excludes_internal_name_and_yd(self):
        f,v=self.fixture();v[1][9]='内部中文商品';p=project([f],v)
        self.assertIsNone(p['customs']['rows'][0][2]);self.assertNotIn('YD1234',str(p['customs']))
    def test_explicit_local_test_request_required(self):
        for r in [{},{'purpose':'flow_test','reference':'test'},{'purpose':'business','allow_pending':True,'reference':'test'}]:
            with self.assertRaises(Rejected):generate(SimpleNamespace(config={}),r)
    def test_test_configuration_required(self):
        with self.assertRaises(Rejected):generate(SimpleNamespace(config={}),dict(purpose='flow_test',allow_pending=True,reference='test'))
    def test_normal_confirmation_gate_remains_closed(self):
        s=Service.__new__(Service);s.config={'calculation_view_binding':'pinned'}
        with self.assertRaises(Rejected):s.confirm('id',explicit_confirmation=True,reference='test')
    def test_exact_original_weight_formula_cache_preserved(self):
        with tempfile.TemporaryDirectory()as tmp:
            a=Path(tmp)/'a.xlsx';b=Path(tmp)/'b.xlsx'
            for file,value in [(a,'0.05379199999999999'),(b,'0.053792')]:
                with zipfile.ZipFile(file,'w')as z:z.writestr('xl/worksheets/sheet2.xml','<worksheet xmlns="'+NS[1:-1]+'"><sheetData><row r="2"><c r="H2"><f>C2*E2*F2*G2/1000000</f><v>'+value+'</v></c></row></sheetData></worksheet>')
            restore_weight_caches(a,b)
            with zipfile.ZipFile(b)as z:self.assertIn(b'0.05379199999999999',z.read('xl/worksheets/sheet2.xml'))
    def test_cached_result_tamper_rejected(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);file=root/'out.xlsx';file.write_bytes(b'changed');save(root/'test-final/current.json',{'calculation_sha256':'fixed','output_sha256':{str(file):'bad'}})
            with patch('interaction.test_final.inputs',return_value=({},None,{'sha256':'fixed'})):
                with self.assertRaises(Rejected):current(SimpleNamespace(background=root))
    def test_shared_weight_formulas_restored_without_changing_expanded_meaning(self):
        with tempfile.TemporaryDirectory()as tmp:
            a=Path(tmp)/'a.xlsx';b=Path(tmp)/'b.xlsx'
            source='<row r="2"><c r="D2"><f t="shared" si="0" ref="D2:D3">B2*C2</f><v>15</v></c></row><row r="3"><c r="D3"><f t="shared" si="0"/><v>16</v></c></row>'
            target='<row r="2"><c r="D2"><f>B2*C2</f><v>15</v></c></row><row r="3"><c r="D3"><f>B3*C3</f><v>16</v></c></row>'
            for file,xml in [(a,source),(b,target)]:
                with zipfile.ZipFile(file,'w')as z:z.writestr('xl/worksheets/sheet2.xml','<worksheet xmlns="'+NS[1:-1]+'"><sheetData>'+xml+'</sheetData></worksheet>')
            restore_weight_caches(a,b,[{'cell':'D2','formula':'=B2*C2'},{'cell':'D3','formula':'=B3*C3'}])
            with zipfile.ZipFile(b)as z:
                self.assertIn(b't="shared"',z.read('xl/worksheets/sheet2.xml'));self.assertIn(b'ref="D2:D3"',z.read('xl/worksheets/sheet2.xml'))

if __name__=='__main__':unittest.main()
