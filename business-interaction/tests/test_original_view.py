"""Technical layout fixtures only; no business SKU or approval is fabricated."""
import io, json, sys, tempfile, unittest, zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction.original_view import OriginalView, publish_original
from interaction import digest, Rejected

class OriginalLayout(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'original.xlsx'
        w=Workbook();s=w.active;s.title='invoice (計算)'
        s.append(['column '+str(n) for n in range(21)])
        s.append([None]*10+[40,20,100,'=L2*M2']+[None]*7)
        s['I2'].fill=PatternFill('solid',fgColor='FFFFFF')
        w.create_sheet('weight')['A1']='unchanged weight';w.save(self.source);w.close()
        self.binding={'columns':21,'source_sha256':digest(self.source),'sheet':s.title,'head':'test-head',
            'backend_root':str(self.root),'row_map':[{'source_row':2,'row_id':'technical-row'}],
            'items':[{'target':'I2','source_row':2,'formula':'=ROUND(M2/(K2/L2),0)','expected':50}]}
        self.issued=self.root/'issued.xlsx';publish_original(self.source,self.binding,self.issued)
        self.binding.update(issued_file=str(self.issued),issued_sha256=digest(self.issued),
            backend_export={'file':str(self.issued),'sha256':digest(self.issued)})
        (self.root/'binding.json').write_text(json.dumps(self.binding),encoding='utf8')
        self.fake=SimpleNamespace(root=self.root)
        self.patch=patch('interaction.original_view.Service',return_value=self.fake);self.patch.start();self.addCleanup(self.patch.stop)
        self.view=OriginalView({'native_view_binding':str(self.root/'binding.json')})
    def changed(self,cell,value):
        w=load_workbook(self.issued);w.worksheets[0][cell]=value
        p=self.root/('return-'+cell+'.xlsx');w.save(p);w.close();return p
    def test_I_only_and_other_zip_parts_exact(self):
        with zipfile.ZipFile(self.source) as a,zipfile.ZipFile(self.issued) as b:
            self.assertEqual(a.namelist(),b.namelist())
            for n in a.namelist():
                if n!='xl/worksheets/sheet1.xml':self.assertEqual(a.read(n),b.read(n),n)
        w=load_workbook(self.issued,data_only=True);self.assertEqual(w.worksheets[0]['I2'].value,50);w.close()
    def test_original_source_not_overwritten(self):
        with self.assertRaises(ValueError):publish_original(self.source,self.binding,self.source)
    def test_existing_output_not_overwritten(self):
        with self.assertRaises(ValueError):publish_original(self.source,self.binding,self.issued)
    def test_source_sha_checked(self):
        with self.assertRaises(ValueError):publish_original(self.source,{**self.binding,'source_sha256':'changed'},self.root/'new.xlsx')
    def test_only_verified_formula_allowed(self):
        binding={**self.binding,'items':[{**self.binding['items'][0],'formula':'=UNKNOWN()'}]}
        with self.assertRaises(ValueError):publish_original(self.source,binding,self.root/'new.xlsx')
    def test_zero_changes(self):self.assertEqual(self.view.preview(self.issued)['modified_cells'],0)
    def test_total_is_operator_edit(self):
        result=self.view.preview(self.changed('K2',80))
        self.assertEqual(result['modified_cells'],1);self.assertEqual(result['changes'][0]['field'],'declared_total_pieces')
    def test_original_qty_is_read_only(self):
        with self.assertRaises(ValueError):self.view.preview(self.changed('L2',21))
    def test_original_price_is_read_only(self):
        with self.assertRaises(ValueError):self.view.preview(self.changed('M2',101))
    def test_unknown_formula_not_executed(self):
        with self.assertRaises(ValueError):self.view.preview(self.changed('I2','=SUM(M2)'))
    def test_issued_sha_is_required(self):
        p=self.root/'binding.json';p.write_text(json.dumps({**self.binding,'issued_sha256':'wrong'}),encoding='utf8')
        with self.assertRaises(ValueError):OriginalView({'native_view_binding':str(p)})
    def test_different_session_root_rejected(self):
        self.fake.root=self.root/'other'
        with self.assertRaises(ValueError):OriginalView({'native_view_binding':str(self.root/'binding.json')})
    def test_basic_edit_requires_existing_basics_sync(self):
        result=self.view.project(self.changed('F2','submitted text'),'technical fixture')
        self.assertEqual(result['status'],'requires_basics_sync_before_calculation')
        self.assertNotIn('request',result)
    def test_no_binding_no_historical_batch_guess(self):
        with self.assertRaises(ValueError):OriginalView({})
