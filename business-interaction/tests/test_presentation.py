import tempfile,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interaction import Rejected,save,digest,key
from interaction.presentation import generate,current
from interaction.presentation_copy import prepare,shift

class PresentationTests(unittest.TestCase):
    def test_explicit_historical_scope_required(self):
        for r in [{},{'historical_preview':True},{'historical_preview':False,'reference':'user'}]:
            with self.assertRaises(Rejected):generate(None,r)
    def test_only_scoped_test_final_source_allowed(self):
        for r in [dict(stage='stage2',test_only=True,formal_output=False),dict(stage='test-final',test_only=False,formal_output=False),dict(stage='test-final',test_only=True,formal_output=True)]:
            with self.assertRaises(ValueError):prepare(r,'unused','batch','modules')
    def test_both_books_required(self):
        with self.assertRaises(ValueError):prepare(dict(stage='test-final',test_only=True,formal_output=False,business_files=[]),'unused','batch','modules')
    def test_main_formula_references_follow_removed_title_rows(self):self.assertEqual(shift('=$J4*I4+SUM(K4:K9)'),'=$J2*I2+SUM(K2:K7)')
    def fixture(self,root):
        f=root/'file.xlsx';f.write_bytes(b'fixed');source={'output_sha256':{'source':'fixed'}}
        result=dict(source_final_fingerprint=key(source['output_sha256']),output_sha256={str(f):digest(f)},business_files=[str(f)],presentation_only=True,business_approval_changed=False,formal_output=False)
        save(root/'presentation/current.json',result);return SimpleNamespace(background=root),source,result,f
    def test_idempotent_retry_keeps_files_and_approval(self):
        with tempfile.TemporaryDirectory()as t:
            s,source,result,_=self.fixture(Path(t))
            with patch('interaction.presentation.test_current',return_value=source):r=generate(s,dict(historical_preview=True,reference='user'))
            self.assertEqual(r['business_files'],result['business_files']);self.assertTrue(r['receipt_replayed']);self.assertFalse(r['business_approval_changed']);self.assertFalse(r['formal_output'])
    def test_source_version_change_invalidates_preview(self):
        with tempfile.TemporaryDirectory()as t:
            s,_,_,_=self.fixture(Path(t))
            with patch('interaction.presentation.test_current',return_value={'output_sha256':{'source':'new'}}),self.assertRaises(Rejected):current(s)
    def test_output_tamper_rejected(self):
        with tempfile.TemporaryDirectory()as t:
            s,source,_,file=self.fixture(Path(t));file.write_bytes(b'changed')
            with patch('interaction.presentation.test_current',return_value=source),self.assertRaises(Rejected):current(s)

if __name__=='__main__':unittest.main()
