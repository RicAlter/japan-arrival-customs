import sys,unittest,copy,tempfile,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from triage_pair_acceptance import classify,topic,verified_audit,SCHEMA

ROWS=[{'row_id':'shipment-a','sheet':'invoice','row':191,'scope':{'code':'same','qty':'1','specification':'A'}},
      {'row_id':'shipment-b','sheet':'invoice','row':192,'scope':{'code':'same','qty':'2','specification':'A'}}]
def issue(code,row=191,kind='quantity',field='raw_unit',**extra):return {'code':code,'row':row,'kind':kind,'field':field,**extra}
def run(items):return classify(items,ROWS,'invoice','weight')

class TriageTests(unittest.TestCase):
    def test_exact_duplicate_retains_every_raw_reference(self):
        x=issue('QUANTITY_UNIT_MISSING');r=run([x,dict(x)])
        self.assertEqual((r['raw_records'],r['unique_exact_records'],r['exact_duplicate_records']),(2,1,1));self.assertEqual(r['unique_issues'][0]['raw_indices'],[0,1])
    def test_different_fields_and_messages_are_not_exact_duplicates(self):
        r=run([issue('INPUT_INVALID',field='relations',message='one'),issue('INPUT_INVALID',field='relations',message='two')]);self.assertEqual(r['unique_exact_records'],2)
    def test_quantity_dependencies_one_scoped_case_with_all_causes(self):
        r=run([issue('QUANTITY_UNIT_MISSING'),issue('INVOICE_UNIT_MISSING',kind='price'),issue('PRICE_RESULT_UNAVAILABLE',kind='customs',field='piece_price_round0',column='G')]);self.assertEqual(r['review_cases'],1);self.assertEqual(len(r['cases'][0]['codes']),3)
    def test_same_jan_does_not_merge_shipments(self):
        r=run([issue('QUANTITY_UNIT_MISSING'),issue('QUANTITY_UNIT_MISSING',row=192)]);self.assertEqual(r['review_cases'],2)
    def test_weight_and_product_same_row_are_separate(self):
        r=run([issue('QUANTITY_UNIT_MISSING'),issue('WEIGHT_TOTAL_INVALID',kind='weight:weight',field='weight')]);self.assertEqual(r['review_cases'],2);self.assertEqual({l['domain']for l in r['raw_links']},{'product','weight'})
    def test_weight_fields_share_case_but_summary_stays_separate(self):
        r=run([issue('WEIGHT_TOTAL_INVALID',kind='weight:weight'),issue('WEIGHT_COUNT_INVALID',kind='weight:weight',field='count'),issue('WEIGHT_SUMMARY_UNRESOLVED',row=196,kind='weight_summary')]);self.assertEqual(r['review_cases'],2)
    def test_global_rate_question_keeps_both_rate_fields_and_rows(self):
        r=run([issue('RATE_MISSING',field='duty_rate'),issue('RATE_MISSING',row=192,field='vat_rate')]);c=r['cases'][0];self.assertEqual(r['review_cases'],1);self.assertEqual(c['fields'],['duty_rate','vat_rate']);self.assertEqual(c['affected_rows'],2);self.assertIn('不表示全批税率相同',c['question'])
    def test_dimensions_global_question_preserves_all_three_fields(self):
        r=run([issue('TEMPLATE_DIMENSION_MAPPING_REVIEW',field=f)for f in ['carton_dimensions','carton_measure','carton_volume']]);self.assertEqual(r['review_cases'],1);self.assertEqual(len(r['cases'][0]['fields']),3)
    def test_paused_material_and_picture_are_never_business_resolved(self):
        r=run([issue('PUBLIC_FIELD_MISSING',field='material'),issue('PICTURE_MISSING',field='picture')]);self.assertEqual(r['paused_cases'],2);self.assertEqual(r['needs_business_confirmation'],0)
    def test_internal_material_and_customs_material_share_trace_only(self):
        r=run([issue('PUBLIC_FIELD_MISSING',field='material'),issue('INTERNAL_FIELD_MISSING_OR_FORMULA_CACHE',kind='internal',field='O',column='O')]);self.assertEqual(r['review_cases'],1);self.assertEqual(r['unique_exact_records'],2)
    def test_missing_internal_and_public_category_one_business_case(self):
        r=run([issue('PUBLIC_FIELD_MISSING',field='category'),issue('INTERNAL_FIELD_MISSING_OR_FORMULA_CACHE',kind='internal',field='N',column='N')]);self.assertEqual(r['review_cases'],1)
    def test_unknown_reason_is_retained_with_original_code(self):
        r=run([issue('NEW_UNRECOGNIZED_REASON')]);self.assertEqual(r['raw_records'],1);self.assertEqual(r['cases'][0]['topic'],'other');self.assertIn('NEW_UNRECOGNIZED_REASON',r['cases'][0]['codes'])
    def test_determinism_and_no_input_mutation(self):
        items=[issue('QUANTITY_UNIT_MISSING'),issue('RATE_MISSING')];old=copy.deepcopy(items);self.assertEqual(run(items),run(items));self.assertEqual(items,old)
    def test_missing_code_refused(self):
        with self.assertRaises(Exception):run([{'row':191}])
    def test_business_and_paused_case_counts_are_not_sum_of_code_counts(self):
        r=run([issue('QUANTITY_UNIT_MISSING'),issue('INVOICE_UNIT_MISSING'),issue('RATE_MISSING'),issue('PICTURE_MISSING')]);self.assertEqual(r['review_cases'],3);self.assertEqual(r['needs_business_confirmation'],2)
    def test_audit_version_drift_and_sample_scope_are_refused(self):
        with tempfile.TemporaryDirectory()as folder:
            p=Path(folder)/'audit.json';pair={'sha256':'bound'}
            for audit in [{'schema':'arrival-pair-acceptance/1','pair_source':{'sha256':'other'},'whole_batch_technical_passed':True}, {'schema':'arrival-pair-acceptance/1','pair_source':pair,'whole_batch_technical_passed':False}]:
                p.write_text(json.dumps(audit),encoding='utf-8');reference={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                with self.assertRaises(Exception):verified_audit(reference,pair)
    def test_preservation_errors_not_relabelled_as_business_questions(self):
        with tempfile.TemporaryDirectory()as folder:
            p=Path(folder)/'audit.json';pair={'sha256':'bound'};p.write_text(json.dumps({'schema':'arrival-pair-acceptance/1','pair_source':pair,'whole_batch_technical_passed':True,'errors':[{'code':'FORMULA_CHANGED'}]}),encoding='utf-8')
            with self.assertRaises(Exception):verified_audit({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()},pair)

if __name__=='__main__':unittest.main()
