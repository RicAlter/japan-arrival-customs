import copy,math,unittest
from unittest.mock import patch
from rebuild_mvp.projection_export import check_author,sum_roundoff
from rebuild_mvp.service import MvpError

class AuthorRoundoff(unittest.TestCase):
    def setUp(self):
        self.plan={'sheet':'图片处理','footer_row':4,'matrix':[['kg'],[.1],[.2],[.3]],'formulas':{'A4':'SUM(A2:A3)'}}
        self.actual=repr(math.nextafter(.3,math.inf))
    def book(self):
        return {'sheets':[{'name':'图片处理','rows':[
            {'row':i,'values':{'A':self.actual if i==4 else v[0]},'formulas':{'A':'SUM(A2:A3)'}if i==4 else{}}
            for i,v in enumerate(self.plan['matrix'],1)]}]}
    def test_precise_adjacent_sum_is_evidenced(self):
        with patch('rebuild_mvp.projection_export.read_book',return_value=self.book()):
            r=check_author('unused',self.plan,allow_sum_roundoff=True)
        self.assertEqual(len(r),1);self.assertEqual(r[0]['artifact_cache'],self.actual)
        self.assertEqual(r[0]['exact_plan_cache'],'0.3')
    def test_final_check_remains_exact(self):
        with patch('rebuild_mvp.projection_export.read_book',return_value=self.book()):
            with self.assertRaises(MvpError):check_author('unused',self.plan)
    def test_two_ulp_rejected(self):
        actual=repr(math.nextafter(float(self.actual),math.inf))
        self.assertIsNone(sum_roundoff(self.plan,4,1,.3,actual))
    def test_literal_value_has_no_tolerance(self):
        self.assertIsNone(sum_roundoff(self.plan,2,1,.1,repr(math.nextafter(.1,math.inf))))
    def test_wrong_formula_has_no_tolerance(self):
        self.plan['formulas']['A4']='A2+A3'
        self.assertIsNone(sum_roundoff(self.plan,4,1,.3,self.actual))
    def test_integer_total_is_exact(self):
        self.assertIsNone(sum_roundoff(self.plan,4,1,3,3.0000000000000004))
    def test_plan_sum_disagreement_is_not_adjusted(self):
        self.plan['matrix'][1][0]=.11
        self.assertIsNone(sum_roundoff(self.plan,4,1,.3,self.actual))
    def test_error_cache_rejected(self):
        self.assertIsNone(sum_roundoff(self.plan,4,1,.3,'#VALUE!'))
