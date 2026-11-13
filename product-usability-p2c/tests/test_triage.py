import copy
import unittest

from triage import classify,version_state,Rejected
from analyze_private import assert_pair_values,number,code


def item():
    return {'row_id':'2','case_id':'SYNTHETIC-1','code':'00123',
            'current':{'material':{'value':'ABS','confirmed':True,'evidence':{'cell':'M2','reference':'TEST:current'}},
                       'customs_name':{'value':'合成品名','confirmed':True,'evidence':{'cell':'I2','reference':'TEST:current'}}},
            'required_fields':['material','customs_name'],'history_versions':[],
            'current_version':None,'library_issues':['version','specification','candidate_selection'],
            'history_identity_conflicts':['specification']}


class TriageTests(unittest.TestCase):
    def test_unknown_version_is_long_term_not_current_task(self):
        r=classify(item());self.assertEqual(r['version_state'],'unknown');self.assertEqual(r['current_tasks'],[])
        self.assertIn('version',r['library_issues']);self.assertIsNone(r['version_value'])

    def test_explicit_no_independent_version_has_evidence(self):
        proof={'kind':'no_independent_version','source_sha256':'a'*64,'reference':'TEST:explicit source','explicit_confirmation':True}
        x=item();x['version_proof']=proof;r=classify(x)
        self.assertEqual(r['version_state'],'confirmed_no_independent_version');self.assertIsNone(r['version_value'])
        self.assertNotIn('version',r['library_issues']);self.assertFalse(r['automatic_identity_confirmation'])

    def test_no_independent_version_cannot_be_defaulted(self):
        for proof in [{},{'kind':'no_independent_version','reference':'用户说没有'}]:
            with self.subTest(proof=proof),self.assertRaises(Rejected):version_state(None,[],proof)

    def test_explicit_no_version_does_not_erase_known_version(self):
        proof={'kind':'no_independent_version','source_sha256':'a'*64,'reference':'TEST','explicit_confirmation':True}
        with self.assertRaises(Rejected):version_state(None,['v1'],proof)

    def test_single_historical_version_not_promoted_to_current(self):
        self.assertEqual(version_state(None,['v1']),'unknown')

    def test_confirmed_current_version_is_known(self):
        self.assertEqual(version_state('v1',['v1']),'known')

    def test_known_version_conflict_keeps_current_confirmed_value(self):
        x=item();x['history_versions']=['v1','v2'];r=classify(x)
        self.assertEqual(r['version_state'],'known_version_conflict');self.assertEqual(r['current_tasks'],[])
        self.assertEqual(r['reference_use'],'conflict_reference_only');self.assertEqual(r['effective_values']['material'],'ABS')

    def test_missing_material_still_requires_current_business_action(self):
        x=item();x['current']['material']['value']=None;r=classify(x)
        self.assertEqual(r['current_required_fields'],['material']);self.assertIsNone(r['effective_values']['material'])

    def test_unconfirmed_populated_value_requires_confirmation(self):
        x=item();x['current']['material']['confirmed']=False;r=classify(x)
        self.assertEqual(r['current_tasks'][0]['reason'],'current_value_not_confirmed')
        self.assertEqual(r['effective_values']['material'],'ABS')

    def test_missing_evidence_does_not_count_as_confirmed(self):
        x=item();x['current']['material']['evidence']=None
        self.assertEqual(len(classify(x)['current_tasks']),1)

    def test_history_conflict_never_changes_current_value(self):
        x=item();x['historical_candidate']={'material':'PVC'};before=copy.deepcopy(x);r=classify(x)
        self.assertEqual(x,before);self.assertEqual(r['effective_values']['material'],'ABS')
        self.assertEqual(r['historical_values_applied'],0);self.assertFalse(r['material_approval'])

    def test_optional_empty_yd_and_no_code_do_not_create_task(self):
        x=item();x['code']=None;x['current']['yd']={'value':None};r=classify(x)
        self.assertEqual(r['current_tasks'],[]);self.assertIsNone(r['code'])

    def test_zero_tax_rate_is_valid_not_missing(self):
        x=item();x['current']['duty_rate']={'value':0,'confirmed':True,'evidence':{'cell':'O2'}};x['required_fields'].append('duty_rate')
        self.assertEqual(classify(x)['current_tasks'],[])

    def test_numeric_material_does_not_count_as_confirmed_text(self):
        x=item();x['current']['material']['value']=0
        self.assertEqual(classify(x)['current_tasks'][0]['reason'],'current_value_invalid_type')

    def test_unknown_material_placeholder_is_missing(self):
        x=item();x['current']['material']['value']='未找到'
        self.assertEqual(classify(x)['current_required_fields'],['material'])

    def test_current_sources_conflict_requires_action(self):
        x=item();x['current_conflicts']=[{'field':'material','evidence':['M2','M2']}]
        self.assertEqual(classify(x)['current_tasks'][0]['reason'],'current_confirmed_sources_conflict')

    def test_history_conflicts_are_retained_in_background(self):
        r=classify(item());self.assertEqual(r['history_identity_conflicts'],['specification'])
        self.assertEqual(r['library_issues'],['version','specification','candidate_selection'])

    def test_required_field_contract_must_be_complete(self):
        x=item();x['required_fields'].append('absent')
        with self.assertRaises(Rejected):classify(x)

    def test_current_value_no_automatic_identity_or_release(self):
        r=classify(item());self.assertFalse(r['automatic_identity_confirmation']);self.assertFalse(r['formal_output'])

    def test_code_leading_zero_preserved(self):
        self.assertEqual(code('00123'),'00123')
        with self.assertRaises(Rejected):assert_pair_values([['code'],['00123']],[['code'],['123']],code_column=1,last=2)

    def test_source_numeric_code_and_output_text_are_same_original_value(self):
        assert_pair_values([['code'],[123]],[['code'],['123']],code_column=1,last=2)

    def test_source_content_difference_rejects_zero_exception_claim(self):
        with self.assertRaises(Rejected):assert_pair_values([['material'],['ABS']],[['material'],['PVC']],code_column=2,last=2)

    def test_missing_invalid_numbers_are_not_hidden_as_zero(self):
        for value in [None,'',True,'unknown','nan']:
            with self.subTest(value=value),self.assertRaises(Rejected):number(value)


if __name__=='__main__':unittest.main()
