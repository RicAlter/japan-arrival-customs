"""No workbook fixtures or real business approvals in pure model checks."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage1.support import bootstrap,Rejected
bootstrap()
from stage1 import model
from stage1.service import Base
from a_confirm import service as original,model as original_model

class ModelTests(unittest.TestCase):
    def test_a03_namespace_is_isolated_but_transaction_code_is_reused(self):
        self.assertIs(original.model,original_model)
        for method in ['commit','_build','history','_state']:
            self.assertEqual(getattr(Base,method).__code__,getattr(original.Service,method).__code__)
        self.assertIs(sys.modules[Base.__module__].model,model)
    def test_unit_unknown_and_nonminimum_wording_are_not_minimum(self):
        for unit in [None,'','原规格单位（待核）','未知','盒','套','盒（非最小单位）','非最小单位']:
            self.assertFalse(model.minimum_unit(unit),unit)
        self.assertTrue(model.minimum_unit('个'))
    def test_finite_numeric_values_only(self):
        for value in ['NaN','Infinity',True,None,'bad']:
            self.assertIsNone(model.number(value))
        self.assertEqual(str(model.number('2629.1265')),'2629.1265')
    def test_stage1_defers_recheck_without_math(self):
        from unittest.mock import patch
        import native22.pricing as pricing
        with patch.object(pricing,'analyze',side_effect=AssertionError('forbidden')):
            fields,report=model.recheck({'profile_id':'kmt-native-16-v1'},None,
                {'fields':{},'price_basis':{'status':'stage1_purchase_reference_only'}},{'overrides':{}})
        self.assertEqual(fields,{})
        self.assertEqual(report['rows'],[])
        self.assertTrue(report['pricing_deferred'])
        self.assertFalse(report['can_enter_b'])
    def test_other_phase_basis_cannot_enter_stage1(self):
        with self.assertRaises(Rejected):model.recheck({'profile_id':'x'},None,{'price_basis':{},'fields':{}},{'overrides':{}})
    def test_box_and_source_identity_are_not_stage1_confirmation_targets(self):
        for field in ['pieces_per_box','product_code','origin']:
            with self.assertRaises(Rejected):
                model.eligibility({'field':field,'target':'S!H2','value':{'type':'number','value':'1'}},{},{},{})

if __name__=='__main__':unittest.main()
