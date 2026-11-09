import unittest
from copy import deepcopy
from interaction.quantity_review import reconcile,number
from interaction.preparation_sources import Index

def observed(jan='a',quantity=2,unit='件',row=1,batch='old'):
    return {'jan':jan,'quantity':quantity,'unit':unit,'row':row,'batch_id':batch,
            'source':{'sha256':'file-'+batch,'sheet':'items','row':row}}

def purchase(jan='a',quantity=10,order='PO1',unit='件',file='order-file',row=2,**kw):
    return {'jan':jan,'quantity':quantity,'order_id':order,'status':'已采购','unit':unit,
            'source':{'sha256':file,'sheet':'orders','row':row},**kw}

def policy():
    return {'purchase_coverage':{'complete':True,'reference':'explicit test order scope'},
            'history_coverage':{'complete':True,'reference':'explicit test complete history'}}

class QuantityReviewTests(unittest.TestCase):
    def run_review(self,a=None,p=None,h=None,config=None,links=()):
        return reconcile(a if a is not None else [observed(batch='now')],p if p is not None else [purchase()],
                         h if h is not None else [],Index(links),policy() if config is None else config,'now')

    def test_sum_same_jan_arrivals_and_partial_not_error(self):
        r=self.run_review(a=[observed(quantity=3,row=2,batch='now'),observed(quantity=2,row=3,batch='now')],h=[observed(quantity=2)])['rows']['a']
        self.assertEqual((r['purchase_total'],r['historical_received'],r['current_received'],r['remaining_pending']),('10','2','5','3'))
        self.assertEqual(r['status'],'pending_future_arrival');self.assertFalse(r['is_error'])

    def test_sum_independent_valid_order_lines(self):
        r=self.run_review(p=[purchase(quantity=7),purchase(quantity=3,order='PO2')])['rows']['a']
        self.assertEqual(r['purchase_total'],'10');self.assertEqual(r['purchase_order_ids'],['PO1','PO2'])

    def test_duplicate_export_not_added_twice(self):
        r=self.run_review(p=[purchase(file='v1'),purchase(file='v2')])
        self.assertEqual(r['rows']['a']['purchase_total'],'10')
        self.assertEqual(r['summary']['deduplicated_purchase_export_observations'],1)

    def test_same_physical_source_alias_not_added_twice(self):
        self.assertEqual(self.run_review(p=[purchase(),purchase()])['rows']['a']['purchase_total'],'10')

    def test_changed_order_snapshot_retains_conflict(self):
        r=self.run_review(p=[purchase(quantity=8,file='v1'),purchase(quantity=9,file='v2')])['rows']['a']
        self.assertIsNone(r['cumulative_difference']);self.assertIn('purchase_order_line_version_conflict',r['reasons'])

    def test_identical_lines_without_line_ids_are_ambiguous(self):
        r=self.run_review(p=[purchase(row=2),purchase(row=3)])['rows']['a']
        self.assertIn('purchase_order_line_identity_ambiguous',r['reasons']);self.assertIsNone(r['purchase_total'])

    def test_explicit_line_ids_allow_distinct_lines(self):
        r=self.run_review(p=[purchase(row=2,order_line_id='L1'),purchase(row=3,order_line_id='L2')])['rows']['a']
        self.assertEqual(r['purchase_total'],'20')

    def test_revoked_order_excluded(self):
        p=purchase(quantity=99,order='cancel');p['status']='已撤销'
        r=self.run_review(p=[purchase(),p]);self.assertEqual(r['rows']['a']['purchase_total'],'10');self.assertEqual(r['summary']['excluded_purchase_lines'],1)

    def test_cut_quantity_not_silently_deducted(self):
        r=self.run_review(p=[purchase(cut_quantity=2)])['rows']['a']
        self.assertIn('purchase_cancellation_quantity_basis_unresolved',r['reasons']);self.assertIsNone(r['purchase_total'])

    def test_purchase_never_falls_back_to_arrival(self):
        r=self.run_review(p=[])['rows']['a'];self.assertIsNone(r['purchase_total']);self.assertIsNone(r['purchase_raw_sum_unconverted'])
        self.assertEqual(r['current_arrival_raw'],'2');self.assertIsNone(r['cumulative_difference'])

    def test_unit_unknown_keeps_raw_observation_only(self):
        r=self.run_review(p=[purchase(unit=None)])['rows']['a']
        self.assertEqual(r['purchase_raw_sum_unconverted'],'10');self.assertIsNone(r['remaining_pending'])

    def test_empty_partial_history_is_not_zero(self):
        c=policy();c['history_coverage']={'complete':False}
        r=self.run_review(config=c)['rows']['a'];self.assertIsNone(r['historical_received']);self.assertIsNone(r['cumulative_difference'])

    def test_current_batch_excluded_from_history(self):
        r=self.run_review(h=[observed(batch='now')]);self.assertEqual(r['summary']['excluded_history_observations'],1)
        self.assertIsNone(r['rows']['a']['cumulative_difference'])

    def test_history_duplicate_observation_counted_once(self):
        r=self.run_review(h=[observed(),observed()])['rows']['a'];self.assertEqual(r['historical_received'],'2')

    def test_pcs_relation_alone_never_implies_a_factor(self):
        r=self.run_review(a=[observed('piece',quantity=8,batch='now')],p=[purchase('box',quantity=2,unit='盒')],
                          links=[{'jan':'box','pcs':'piece'}])['rows']['piece']
        self.assertEqual(r['purchase_raw_sum_unconverted'],'2');self.assertIsNone(r['cumulative_difference'])

    def test_confirmed_pcs_conversion_is_exact(self):
        c=policy();c['conversions']=[{'from_jan':'box','to_jan':'piece','from_unit':'盒','to_unit':'件','factor':8,'confirmed':True,'reference':'test: verified package relation'}]
        r=self.run_review(a=[observed('piece',quantity=8,batch='now')],p=[purchase('box',quantity=2,unit='盒')],
                          config=c,links=[{'jan':'box','pcs':'piece'}])['rows']['piece']
        self.assertEqual((r['purchase_total'],r['remaining_pending']),('16','8'))
        c['conversions'][0]['confirmed']=False
        self.assertIsNone(self.run_review(a=[observed('piece',batch='now')],p=[purchase('box',unit='盒')],config=c,links=[{'jan':'box','pcs':'piece'}])['rows']['piece']['purchase_total'])

    def test_multiple_box_codes_not_arbitrarily_selected(self):
        r=self.run_review(a=[observed('piece',batch='now')],p=[purchase('box1')],links=[{'jan':'box1','pcs':'piece'},{'jan':'box2','pcs':'piece'}])['rows']['piece']
        self.assertIn('main_pcs_link_conflict',r['reasons']);self.assertIsNone(r['purchase_total'])

    def test_over_received_and_fully_received(self):
        r=self.run_review(a=[observed(quantity=12,batch='now')])['rows']['a'];self.assertTrue(r['is_error']);self.assertEqual(r['cumulative_difference'],'2')
        r=self.run_review(a=[observed(quantity=10,batch='now')])['rows']['a'];self.assertEqual(r['status'],'fully_received')

    def test_no_reliable_comparisons_does_not_report_zero_differences(self):
        r=self.run_review(config={});self.assertEqual(r['summary']['comparable_jans'],0);self.assertIsNone(r['summary']['over_received_jans'])
        self.assertIsNone(r['frontend']['future_arrival_jans']);self.assertEqual(r['frontend']['future_arrivals_scope'],'undetermined_due_to_sources')

    def test_original_inputs_unchanged(self):
        a,p,h=[observed(batch='now')],[purchase()],[observed()];before=deepcopy((a,p,h))
        self.run_review(a,p,h);self.assertEqual((a,p,h),before)

    def test_orders_after_replay_cutoff_do_not_inflate_purchase(self):
        c=policy();c['as_of']='2026-10-02'
        r=self.run_review(p=[purchase(order_date='2026-10-01'),purchase(quantity=99,order='future',order_date='2026-10-03')],config=c)
        self.assertEqual(r['rows']['a']['purchase_total'],'10')
        self.assertEqual(r['summary']['excluded_purchase_reason_counts']['purchase_after_batch_cutoff'],1)

    def test_nonstandard_current_code_not_treated_as_verified_JAN(self):
        c=policy();c['require_jan_syntax']=True
        r=self.run_review(config=c)['rows']['a'];self.assertIsNone(r['cumulative_difference'])
        self.assertIn('nonstandard_code_not_verified_JAN',r['reasons'])

    def test_confirmed_comparison_unit_converts_mixed_arrival_units(self):
        c=policy();c['comparison_units']={'a':{'unit':'件','confirmed':True,'reference':'explicit comparison unit'}}
        c['conversions']=[{'from_jan':'a','to_jan':'a','from_unit':'盒','to_unit':'件','factor':8,'confirmed':True,'reference':'verified relation'}]
        r=self.run_review(a=[observed(quantity=1,unit='盒',batch='now'),observed(quantity=2,row=2,batch='now')],config=c)['rows']['a']
        self.assertEqual(r['current_received'],'10');self.assertEqual(r['status'],'fully_received')

    def test_cancelled_snapshot_prevents_using_old_effective_version(self):
        cancelled=purchase(file='new');cancelled['status']='已撤销'
        r=self.run_review(p=[purchase(file='old'),cancelled])['rows']['a']
        self.assertIn('purchase_order_status_conflict',r['reasons']);self.assertIsNone(r['purchase_total'])

    def test_box_and_piece_arrivals_do_not_spend_one_order_twice(self):
        c=policy();c['conversions']=[{'from_jan':'box','to_jan':'piece','from_unit':'盒','to_unit':'件','factor':8,'confirmed':True,'reference':'verified relation'}]
        r=self.run_review(a=[observed('box',unit='盒',batch='now'),observed('piece',unit='件',row=2,batch='now')],
            p=[purchase('box',unit='盒')],config=c,links=[{'jan':'box','pcs':'piece'}])
        self.assertTrue(all(x['purchase_total'] is None for x in r['rows'].values()))
        self.assertTrue(all('shared_order_quantity_across_JAN_groups_not_allocated' in x['reasons'] for x in r['rows'].values()))

if __name__=='__main__':unittest.main()
