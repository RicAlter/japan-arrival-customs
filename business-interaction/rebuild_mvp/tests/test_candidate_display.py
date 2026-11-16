import copy,unittest
from unittest.mock import patch
from rebuild_mvp.candidate_pipeline import apply_candidates
from rebuild_mvp.candidate_display import candidate_text,export_marks,ORANGE

class CandidateDisplay(unittest.TestCase):
    def row(self):
        return {'row_id':'row-a','source_row':18,'raw':{'code':'00123','ja':'商品原文'},'values':{},'evidence':{},'issues':[],'matching':{'path':'unresolved'}}
    def apply(self,records,row=None):
        row=row or self.row()
        refs=[{'role':'purchase_list','source_id':'s','source_sha256':'a'*64,'sheet':'采购','row':i+2,'fields':{'name':'商品原文',**f},'columns':{'yd':'B'},'scope':{}}for i,f in enumerate(records)]
        with patch('rebuild_mvp.candidate_pipeline.digest',return_value='a'*64),patch('rebuild_mvp.candidate_pipeline._iter_records',return_value=iter(refs)):
            apply_candidates([row],{'candidate_review':{'enabled':True},'sources':[{'role':'purchase_list','path':'synthetic-source'}]})
        return row
    def test_unique_full_name_YD_clean_but_provenance_retained(self):
        row=self.apply([{'yd':'YD2026010101'}])
        self.assertEqual(row['values']['yd'],'YD2026010101')
        self.assertEqual(row['review_candidates']['yd']['note'],'按名称补')
        self.assertEqual(row['evidence']['yd'][0]['row'],2)
        self.assertFalse(row['review_candidates']['yd']['confirmed'])
    def test_multiple_different_YDs_remain_numbered_and_orange(self):
        row=self.apply([{'yd':'YD2026010101'},{'yd':'YD2026010102'}])
        self.assertEqual(row['values']['yd'],'1. YD2026010101\n2. YD2026010102（待选）')
        self.assertEqual(export_marks([row],-16),[{'row':2,'field':'yd','code':'CANDIDATE_AMBIGUOUS'}])
        self.assertEqual(ORANGE,'#FCE4D6')
    def test_duplicate_same_YD_keeps_both_refs_without_false_ambiguity(self):
        row=self.apply([{'yd':'YD2026010101'},{'yd':'YD2026010101'}])
        self.assertEqual(row['values']['yd'],'YD2026010101')
        self.assertEqual(len(row['evidence']['yd']),2)
        self.assertEqual(export_marks([row],0),[])
    def test_existing_manual_YD_never_rewritten_or_stripped(self):
        row=self.row();row['values']['yd']='人工YD（按名称补）'
        self.assertEqual(self.apply([{'yd':'YD2026010101'}],row)['values']['yd'],'人工YD（按名称补）')
    def test_orange_ambiguity_beats_earlier_missing_mark(self):
        row=self.row();row['issues']=[{'field':'yd','code':'FIELD_MISSING'},{'field':'yd','code':'FIELD_CONFLICT'}]
        self.assertEqual(export_marks([row],-16),[{'row':2,'field':'yd','code':'FIELD_CONFLICT'}])
    def test_name_multi_marker_beats_missing_without_business_issue_mutation(self):
        row=self.row();row['issues']=[{'field':'yd','code':'FIELD_MISSING'}]
        row['review_candidates']={'yd':{'options':[{'value':'YD1'},{'value':'YD2'}]}}
        before=copy.deepcopy(row)
        self.assertEqual(export_marks([row],0)[0]['code'],'CANDIDATE_AMBIGUOUS');self.assertEqual(row,before)
    def test_other_field_notes_retained(self):
        self.assertEqual(candidate_text('name',['中文名'],'译名待确认'),'中文名（译名待确认）')
        self.assertEqual(candidate_text('purchase_price',['99元'],'采购候选'),'99元（采购候选）')
        self.assertEqual(candidate_text('yd',['YD1'],'待确认'),'YD1（待确认）')
    def test_cancelled_name_result_not_shown(self):
        self.assertNotIn('yd',self.apply([{'yd':'YD2026010101','status':'取消'}])['values'])

    def test_selected_highest_cny_still_marks_genuinely_different_records(self):
        row=self.row();row['purchase_price_selection']={'rule':'highest-comparable-cny-cost/20261116','all_quotes':[{'value':'31'},{'value':'35'}]}
        self.assertEqual(export_marks([row],0),[{'row':18,'field':'purchase_price','code':'CNY_SOURCE_PRICE_CONFLICT'}])
    def test_same_cny_numeric_records_do_not_create_false_orange(self):
        row=self.row();row['purchase_price_selection']={'rule':'highest-comparable-cny-cost/20261116','all_quotes':[{'value':'32'},{'value':'32.0'}]}
        self.assertEqual(export_marks([row],0),[])
