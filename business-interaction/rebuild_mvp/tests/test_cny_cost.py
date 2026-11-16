import unittest
from unittest.mock import patch
from rebuild_mvp.cny_cost import normalize_options,display_selection
from rebuild_mvp.candidate_pipeline import apply_candidates
from test_matching import run,record

class CnyCost(unittest.TestCase):
    def test_same_numeric_prices_normalized(self):
        d=normalize_options([{'value':v,'currency':'CNY','unit':'个'}for v in ['32','32.0','32.00']])
        self.assertEqual(d['value'],'32');self.assertEqual(len(d['groups']),1);self.assertEqual(len(d['selected']),3)
    def test_screenshot_cost_examples(self):
        for prices,want in [(['32','32.0'],'32'),(['111','111.0'],'111'),(['35','31','31.0'],'35'),(['121','112','112.0'],'121'),(['109','109.0'],'109')]:
            d=normalize_options([{'value':v,'currency':'CNY','unit':'原SKU'}for v in prices]);self.assertEqual(d['value'],want)
    def test_yen_does_not_use_highest_policy(self):
        self.assertIsNone(normalize_options([{'value':v,'currency':'JPY','unit':'个'}for v in ['10','12']]))
        row=run([record('purchase_list',code='1234567890123',price='10',currency='JPY',unit='个'),record('purchase_list',2,code='1234567890123',price='12',currency='JPY',unit='个')])
        self.assertNotIn('purchase_price',row['values'])
    def test_currency_unit_and_packaging_conflicts_are_not_ranked(self):
        a={'value':'10','currency':'CNY','unit':'个','packaging':'单个'}
        for change in [{'currency':'JPY'},{'unit':'盒'},{'packaging':'整盒'}]:
            self.assertIsNone(normalize_options([a,{**a,'value':'999',**change}]))
    def test_unknown_unit_and_invalid_number_not_guessed(self):
        for value in ['-1','NaN','Infinity','未定']:
            self.assertIsNone(normalize_options([{'value':value,'currency':'CNY','unit':'个'}]))
        self.assertIsNone(normalize_options([{'value':'35','currency':'CNY','unit':None}]))
    def test_direct_purchase_selection_keeps_all_quotes_and_selected_sources(self):
        row=run([record('purchase_list',code='1234567890123',price='31',currency='CNY',unit='个'),record('purchase_list',2,code='1234567890123',price='35.0',currency='CNY',unit='个')])
        self.assertEqual(row['values']['purchase_price'],'35元')
        self.assertEqual(len(row['purchase_price_selection']['all_quotes']),2)
        self.assertEqual(row['evidence']['purchase_price'][0]['row'],2)
    def test_existing_manual_cost_not_overridden(self):
        from rebuild_mvp.matching import _price
        row={'values':{'purchase_price':'人工99元'},'evidence':{},'issues':[]}
        _price(row,[record('purchase_list',price='1000',currency='CNY',unit='个')],False)
        self.assertEqual(row['values']['purchase_price'],'人工99元')
        from test_strict_flow import run as strict,record as rec,batch
        main=rec('business_summary',code='4573643350147',price='10',currency='JPY')
        expensive=rec('purchase_list',code='4573643350147',price='999',currency='CNY',unit='个')
        self.assertEqual(strict([main,expensive])['values']['purchase_price'],'10日元')
    def test_display_dedup_and_max_preserve_metadata(self):
        row={'row_id':'r','raw':{'code':'1','ja':'商品'},'matching':{'path':'unresolved'},'values':{},'evidence':{},'issues':[{'field':'purchase_price','code':'PROCUREMENT_CONFLICT','candidates':[{'value':v,'currency':'CNY','unit':'个','sources':[{'source_id':'s','sheet':'采购','row':i+1,'column':'H'}]}for i,v in enumerate(['32','32.0','35'])]}]}
        apply_candidates([row],{'candidate_review':{'enabled':True},'sources':[]})
        self.assertEqual(row['values']['purchase_price'],'35元');data=row['review_candidates']['purchase_price']
        self.assertEqual(len(data['original_options']),3);self.assertEqual(len(data['options']),2)
    def test_currency_label_and_pending_suffix_normalize(self):
        d=display_selection([(v,{'currency':'CNY','unit':'个','row':i})for i,v in enumerate(['32元','32.0元（待选）'])])
        self.assertEqual(d['value'],'32');self.assertEqual(len(d['groups']),1)

    def test_equal_cost_candidates_stop_false_orange_conflict(self):
        from rebuild_mvp.candidate_display import export_marks
        row={'row_id':'r','source_row':2,'raw':{'code':'1','ja':'商品'},'matching':{'path':'unresolved'},'values':{},'evidence':{},'issues':[{'field':'purchase_price','code':'PROCUREMENT_CONFLICT','candidates':[{'value':v,'currency':'CNY','unit':'个','sources':[{'source_id':'s','sheet':'采购','row':i+1,'column':'H'}]}for i,v in enumerate(['32','32.0'])]}]}
        apply_candidates([row],{'candidate_review':{'enabled':True},'sources':[]})
        self.assertEqual(row['values']['purchase_price'],'32元');self.assertEqual(len(row['resolved_price_issues']),1)
        self.assertEqual(export_marks([row],0),[])

    def test_existing_cell_scientific_and_pending_labels(self):
        from rebuild_mvp.cny_cost import existing_cell_selection
        d=existing_cell_selection('1. 5.2E+2元 / PHP\n2. 520.0元 / 日本塑唐（待选）',same_original_cost_field=True)
        self.assertEqual(d['value'],'520');self.assertEqual(len(d['groups']),1)
        self.assertFalse(d['physical_unit_inferred'])
    def test_existing_cell_other_currency_and_unapproved_scope_untouched(self):
        from rebuild_mvp.cny_cost import existing_cell_selection
        self.assertIsNone(existing_cell_selection('1. 32元\n2. 35元'))
        for text in ['1. 32日元\n2. 35日元','1. 32元/个\n2. 35元/盒','1. 32元\n2. 35美元','32元']:
            self.assertIsNone(existing_cell_selection(text,same_original_cost_field=True))
