import unittest
from unittest.mock import patch
from rebuild_mvp.japanese_search import query_keys,attach_search_candidates

class JapaneseSearchTests(unittest.TestCase):
    def test_width_space_and_unit_label_only_normalized_for_search(self):
        keys=query_keys('トレーディンググリッター缶バッジ(単位/BOX)')
        self.assertIn('トレーディンググリッター缶バッジ',keys)
        self.assertTrue(any('box' in k for k in keys))
    def test_generic_partial_match_is_candidate_never_adopted(self):
        row={'row_id':'r','matching':{'path':'unresolved'},'raw':{'ja':'トレーディンググリッター缶バッジ(単位/BOX)'},'values':{}}
        source={'source_id':'s','sha256':'sha','path':'main.xlsx','role':'business_summary'}
        raw=[{'row':2,'values':{'C':'【FGO】トレーディンググリッター缶バッジ ABOX'}}]
        with patch('rebuild_mvp.japanese_search.Path.is_file',return_value=True),patch('rebuild_mvp.japanese_search._sheet_names',return_value=['主表']),patch('rebuild_mvp.japanese_search.iter_rows',return_value=iter(raw)):
            attach_search_candidates([row],[source],{})
        self.assertEqual(row['japanese_name_search']['status'],'candidates_only')
        self.assertFalse(row['japanese_name_search']['candidates'][0]['adopted'])
        self.assertEqual(row['values'],{})
    def test_not_found_preserves_explicit_search_evidence(self):
        row={'row_id':'r','matching':{'path':'unresolved'},'raw':{'ja':'実際の具体的な商品名'},'values':{}}
        source={'source_id':'s','sha256':'sha','path':'main.xlsx','role':'business_summary'}
        with patch('rebuild_mvp.japanese_search.Path.is_file',return_value=True),patch('rebuild_mvp.japanese_search._sheet_names',return_value=['主表']),patch('rebuild_mvp.japanese_search.iter_rows',return_value=iter([])):
            attach_search_candidates([row],[source],{})
        self.assertEqual(row['japanese_name_search']['status'],'not_found')
        self.assertEqual(row['japanese_name_search']['sources_scanned'][0]['source_id'],'s')
