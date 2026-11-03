"""Re-run frozen P3-A synthetic cases, never call them a real-batch acceptance."""
import argparse
from contextlib import redirect_stdout,redirect_stderr
import json
from pathlib import Path
import sys
import unittest

REPO=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'operations-library-p3a'))


class RecordedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.records=[]
    def record(self,test,status):self.records.append({'test':test.id(),'sample_kind':'synthetic','status':status})
    def addSuccess(self,test):super().addSuccess(test);self.record(test,'passed')
    def addFailure(self,test,err):super().addFailure(test,err);self.record(test,'failed')
    def addError(self,test,err):super().addError(test,err);self.record(test,'error')
    def addSkip(self,test,reason):super().addSkip(test,reason);self.record(test,'skipped')


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    with (output/'synthetic-tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
        suite=unittest.defaultTestLoader.discover(str(REPO/'operations-library-p3a/tests'))
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=RecordedResult).run(suite)
    report={'baseline':'f420951','scope':'synthetic_regression_only','tests_run':result.testsRun,
            'passed':sum(r['status']=='passed' for r in result.records),'failures':len(result.failures),
            'errors':len(result.errors),'skipped':len(result.skipped),'cases':result.records,
            'real_batch_status':'not_verified','real_business_exception_total':None,
            'human_time_savings_measured':False,'formal_output':False,'workbuddy_tested':False}
    (output/'synthetic-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
    return 0 if result.wasSuccessful() else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);raise SystemExit(run(parser.parse_args().output))
