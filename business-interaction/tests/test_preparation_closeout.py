import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from interaction import ROOT, load, save, digest, Rejected
from interaction.preparation import complete_preparation
from interaction.preparation_workbook import reviewed_copy, Q
from interaction.photo_layout import parts, pack
from interaction.service import Service


class PreparationCompletionTests(unittest.TestCase):
    def test_failure_blocks_delivery_and_retry_runs_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);file=root/'prepared.xlsx';file.write_bytes(b'fixture')
            db=root/'snapshot';db.write_bytes(b'database')
            config={'background':str(root),'prepared_file':str(file),'database':{'path':str(db),'sha256':digest(db)},'preparation_status':'material_review_pending'}
            session=root/'session.json';save(session,config)
            with patch('interaction.material_review.review_materials',side_effect=ValueError('bad evidence')):
                with self.assertRaisesRegex(ValueError,'bad evidence'):
                    complete_preparation(config,{},session)
            self.assertEqual(load(session)['preparation_status'],'material_review_pending')
            service=Service.__new__(Service);service.config=load(session)
            with self.assertRaises(Rejected):service.deliver()
            dual={'summary':{'rows':1},'business_files':[str(file)]}
            with patch('interaction.material_review.review_materials',return_value=dual) as query,patch('interaction.preparation.prepared_current',return_value={'business_files':[str(file)]}):
                result=complete_preparation(load(session),{},session)
            self.assertEqual(query.call_count,1)
            self.assertEqual(load(session)['preparation_status'],'complete')
            self.assertEqual(result['material_review'],dual)
            self.assertEqual(file.read_bytes(),b'fixture')


class ReviewedInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native_copy.profiles import inspect_source
        workspace=ROOT.parents[1]
        request=load(workspace/'reports/first-phase-upgrade-20261106/prepare-request.json')
        review=load(workspace/'reports/dual-source-material-integration-20261109/request.json')
        cls.source=inspect_source(request['input_file'])
        cls.file=workspace/review['input_file']

    def test_actual_review_preserves_every_byte(self):
        self.assertEqual(reviewed_copy(self.source,self.file,digest(self.file)),self.file.read_bytes())

    def test_changed_snapshot_rejected(self):
        with self.assertRaises(Rejected):reviewed_copy(self.source,self.file,'wrong')

    def test_same_cache_with_different_amount_formula_rejected(self):
        data=self.file.read_bytes();p=parts(data)
        tree=ET.fromstring(p['xl/worksheets/sheet1.xml'])
        cell=next(c for c in tree.iter(Q+'c') if c.get('r')=='M2')
        cell.find(Q+'f').text+=' + 1'
        p['xl/worksheets/sheet1.xml']=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'changed.xlsx';target.write_bytes(pack(data,p))
            with self.assertRaisesRegex(Rejected,'公式变化'):
                reviewed_copy(self.source,target,digest(target))


if __name__=='__main__':unittest.main()
