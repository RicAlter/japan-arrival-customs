import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rebuild_mvp.storage import Store, identity
from rebuild_mvp.service import handle, row_semantics, writer, validated_config


def batch():
    return {'source': {'path': 'private.xlsx', 'sha256': 'a'*64}, 'rows': [
        {'row_id': 'r1', 'source_row': 18, 'sheet': 'invoice',
         'raw': {'code': '001', 'qty': '2', 'amount': '200', 'jpy_price': '100', 'carton': 'DA1', 'ja': '商品'},
         'raw_cells': {}, 'values': {}, 'evidence': {}, 'issues': []}]}


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path/'candidate.sqlite3')

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def test_original_facts_immutable_across_resume(self):
        first = batch()
        self.store.save_batch('B', first)
        self.store.save_batch('B', first)
        changed = copy.deepcopy(first); changed['rows'][0]['raw']['qty'] = '3'
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.store.save_batch('B', changed)
        self.assertEqual(self.store.get_checkpoint('extracted'), first)
        self.assertEqual(self.store.counts()['batch_rows'], 1)

    def test_separate_product_and_procurement_idempotent(self):
        sources=[];records=[]
        for role in ['business_summary','purchase_list']:
            sources.append({'source_id':role,'sha256':role,'role':role})
            records.append({'source_id':role,'source_sha256':role,'role':role,'sheet':'Sheet1','row':2,
                            'fields':{'name':'商品'},'columns':{'name':'A'}})
        payload={'sources':sources,'records':records,'audit':{}}
        self.store.save_sources(payload);self.store.save_sources(payload)
        counts=self.store.counts()
        self.assertEqual(counts['product_records'],1)
        self.assertEqual(counts['procurement_records'],1)

    def test_adopted_field_must_have_evidence_atomic(self):
        data=batch();self.store.save_batch('B',data)
        data['rows'][0]['values']={'name':'商品'}
        with self.assertRaisesRegex(ValueError,'no evidence'):
            self.store.save_matches('B',data['rows'])
        self.assertEqual(self.store.counts()['matched_rows'],0)

    def test_match_cannot_modify_quantity(self):
        data=batch();self.store.save_batch('B',data)
        data['rows'][0]['raw']['qty']='200'
        with self.assertRaisesRegex(ValueError,'original facts'):
            self.store.save_matches('B',data['rows'])

    def test_match_idempotent_and_restart_reads_checkpoint(self):
        data=batch();self.store.save_batch('B',data)
        row=data['rows'][0];row['values']={'name':'名称'};row['evidence']={'name':[{'source_id':'source','row':3}]}
        row['issues']=[{'code':'FIELD_MISSING','field':'yd'}]
        self.store.save_matches('B',data['rows']);self.store.save_matches('B',data['rows'])
        self.assertEqual(self.store.counts()['adopted_fields'],1)
        self.assertEqual(self.store.counts()['issues'],1)
        self.store.close();self.store=Store(self.path/'candidate.sqlite3')
        self.assertEqual(self.store.get_checkpoint('matched'),data['rows'])

    def test_corrupt_checkpoint_rejected(self):
        self.store.checkpoint('stage',{'value':'original'})
        self.store.db.execute("UPDATE checkpoints SET payload='{}' WHERE step='stage'")
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError,'drift'):self.store.get_checkpoint('stage')


class ToolContractTests(unittest.TestCase):
    def test_unknown_action_structured_error(self):
        result=handle({'action':'upload'})
        self.assertEqual(result['error']['code'],'INPUT_INVALID')
        self.assertFalse(result['business_files'])

    def test_missing_task_structured_error(self):
        result=handle({'action':'resume','task_root':'nonexistent-mvp-task'})
        self.assertEqual(result['error']['code'],'INPUT_INVALID')

    def test_opening_excluded_before_database_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            request={'action':'prepare','batch_id':'B','output':str(root/'output'),
                     'input_file':str(root/'raw.xlsx'),'layout_contract':str(root/'layout.json'),
                     'sources':[{'path':str(root/'开订.xlsx'),'role':'business_summary'}]}
            result=handle(request)
            self.assertEqual(result['error']['code'],'SOURCE_FORBIDDEN')
            self.assertFalse((root/'output').exists())

    def test_no_business_difference_excluded_from_semantic_hash(self):
        first={'raw':{'qty':'1'},'evidence':[{'path':'C:/local','source_sha256':'a','row':2}]}
        second=copy.deepcopy(first);second['evidence'][0]['path']='D:/local'
        self.assertEqual(identity(row_semantics(first)),identity(row_semantics(second)))
        second['evidence'][0]['row']=3
        self.assertNotEqual(identity(row_semantics(first)),identity(row_semantics(second)))

    def test_os_lock_prevents_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            with writer(Path(temp)):
                with self.assertRaisesRegex(ValueError,'执行进程'):
                    with writer(Path(temp)):pass
            with writer(Path(temp)):pass


class ResumeIntegrationTests(unittest.TestCase):
    def test_failed_matching_resumes_completed_source_checkpoint_and_replays(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            raw=root/'raw.xlsx';raw.write_bytes(b'raw-input')
            source=root/'purchase.xlsx';source.write_bytes(b'actual-purchase')
            layout=root/'layout.json';layout.write_text('{}')
            request={'action':'prepare','batch_id':'B','input_file':str(raw),
                     'sources':[{'path':str(source),'role':'purchase_list'}],
                     'layout_contract':str(layout),'output':str(root/'run')}
            data=batch()
            data['source']['sha256']=__import__('hashlib').sha256(raw.read_bytes()).hexdigest()
            collected={'sources':[{'source_id':'p','sha256':'b'*64,'role':'purchase_list'}],
                       'records':[{'source_id':'p','source_sha256':'b'*64,'role':'purchase_list',
                                   'sheet':'s','row':2,'fields':{'name':'商品'},'columns':{'name':'A'}}], 'audit':{}}
            rows=copy.deepcopy(data['rows']);rows[0]['values']={'name':'商品'}
            rows[0]['evidence']={'name':[{'source_sha256':'b'*64,'source_id':'p','sheet':'s','row':2,'column':'A'}]}
            def export(raw_source, output, result_rows, layout_contract, manifest):
                Path(output).write_bytes(b'test-export-placeholder-not-a-business-workbook')
                return {'rows':len(result_rows)}
            with patch('rebuild_mvp.xlsxio.extract_batch',return_value=data) as extract, \
                 patch('rebuild_mvp.sources.collect_sources',return_value=collected) as collect, \
                 patch('rebuild_mvp.matching.match_batch',side_effect=RuntimeError('interrupted')):
                failed=handle(request)
                self.assertEqual(failed['status'],'failed')
                self.assertTrue(failed['error']['retryable'])
                self.assertEqual(failed['step'],'sources_collected')
                self.assertEqual(extract.call_count,1);self.assertEqual(collect.call_count,1)
            with patch('rebuild_mvp.xlsxio.extract_batch') as extract, \
                 patch('rebuild_mvp.sources.collect_sources') as collect, \
                 patch('rebuild_mvp.matching.match_batch',return_value=rows) as match, \
                 patch('rebuild_mvp.xlsxio.write_book',side_effect=export) as write:
                good=handle({'action':'resume','task_root':str(root/'run')})
                self.assertEqual(good['step'],'exported',good)
                self.assertEqual(extract.call_count,0);self.assertEqual(collect.call_count,0)
                self.assertEqual(match.call_count,1);self.assertEqual(write.call_count,1)
                replay=handle(request)
                self.assertEqual(replay['semantic_sha256'],good['semantic_sha256'])
                self.assertEqual(write.call_count,1)
            source.write_bytes(b'changed-purchase')
            drift=handle({'action':'resume','task_root':str(root/'run')})
            self.assertEqual(drift['error']['code'],'SOURCE_CHANGED')
            # Edited operator files must remain untouched, not re-created.
            out=Path(good['business_files'][0]);out.write_bytes(b'operator-edit')
            current=handle({'action':'current','task_root':str(root/'run')})
            self.assertEqual(current['error']['code'],'SOURCE_CHANGED')
            self.assertEqual(out.read_bytes(),b'operator-edit')


if __name__=='__main__':unittest.main()
