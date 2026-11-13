"""Run non-overlapping current regression groups and record executed test IDs."""
import argparse,io,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--suite',choices=['current','price','tools'],required=True);p.add_argument('--candidate',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output)
    if out.exists():raise ValueError('Use a new results file')
    manifest=json.loads((ROOT.parent/'source-manifest.json').read_text('utf8'))
    if manifest['commit']!=a.candidate or manifest['working_copy_changes']:raise ValueError('Tests require the matching committed freeze')
    if a.suite=='current':
        folder=ROOT/'business-interaction/tests';names=['test_stage2_calculation','test_confirmation_view','test_yellow_review','test_final_flow','test_presentation'];expected=90
    elif a.suite=='price':folder=ROOT/'catalogue-pack-loop/tests';names=['test_price_input'];expected=19
    else:folder=ROOT/'tools/tests';names=['test_baseline'];expected=8
    sys.path[:0]=[str(folder),str(folder.parent)]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n)for n in names);records=[];log=io.StringIO()
    class Result(unittest.TextTestResult):
        def startTest(self,t):super().startTest(t);records.append(dict(test=t.id(),status='started'))
        def addSuccess(self,t):super().addSuccess(t);records[-1]['status']='passed'
        def addFailure(self,t,e):super().addFailure(t,e);records[-1]['status']='failed'
        def addError(self,t,e):super().addError(t,e);records.append(dict(test=t.id(),status='error'))
        def addSkip(self,t,r):super().addSkip(t,r);records[-1]['status']='not_executed'
    result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    report=dict(candidate=a.candidate,suite=a.suite,passed=sum(r['status']=='passed'for r in records),failed=len(result.errors)+len(result.failures)+(result.testsRun!=expected),not_executed=len(result.skipped),expected=expected,tests_run=result.testsRun,records=records,log=log.getvalue(),business_approval=False)
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf8')
    print(json.dumps({k:v for k,v in report.items()if k not in ['records','log']}));print(log.getvalue()[-1200:])
    return bool(report['failed']or report['not_executed'])

if __name__=='__main__':raise SystemExit(main())
