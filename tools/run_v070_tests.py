"""Portable source-only regression and reproducible, explicitly TEST-only reports."""
import argparse, hashlib, json, shutil, sys, unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'workbuddy/japan-arrival-customs/scripts'))
sys.path.insert(0,str(ROOT/'tests'))
from arrival_core.storage import atomic_json
from arrival_core.core import digest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    modules=['test_repository_smoke','test_v070_core','test_workbuddy_router','test_v070_workflow']
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(m) for m in modules if (ROOT/'tests'/(m+'.py')).exists())
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((ROOT/'workbuddy/japan-arrival-customs').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    receipt={'at':datetime.now(timezone.utc).isoformat(),'tests_run':result.testsRun,
             'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
             'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
             'source_manifest_sha256':digest(manifest),'source_manifest':manifest,
             'test_authority':'explicitly_isolated_technical_only','WorkBuddy':'not_run',
             'real_feishu':'not_connected','real_official_web':'not_connected','real_business_approval':False}
    atomic_json(out/'v070_test_results.json',receipt)
    if not result.wasSuccessful():return 1
    from test_v070_core import D1LifecycleIntegration
    from arrival_core.d2_candidates import analyze_library
    # Persist actual D1-derived technical replay separately from a clean formal
    # zero-sample report. Never relabel TEST metrics as production accuracy.
    case=D1LifecycleIntegration();case.setUp()
    try:
        as_of=datetime.now(timezone.utc).date().isoformat()
        atomic_json(out/'D2_formal_report.json',analyze_library(case.library,as_of=as_of))
        atomic_json(out/'D2_TEST_ONLY_report.json',analyze_library(case.library,as_of=as_of,realm='test'))
        rule=case.publish()
        atomic_json(out/'D3_TEST_ONLY_report.json',{'published_rule':rule,'match':case.match(),
                    'production_automatic_enabled':False,'technical_only':True,
                    'formal_learning_samples':case.library.statistics(as_of=as_of)['formal_learning_samples']})
    finally:case.tearDown()
    from test_v070_workflow import WorkflowTests
    flow=WorkflowTests();flow.setUp()
    try:
        flow.test_full_roundtrip_sync_drafts_and_cli_consistency()
        artifact_dir=out/'TEST_ONLY_end_to_end';artifact_dir.mkdir(exist_ok=True)
        retained=[]
        for path in [*flow.delivery.glob('*.xlsx'),*flow.output.glob('*/drafts/*/*.xlsx')]:
            target=artifact_dir/path.name
            if target.exists():raise RuntimeError('Refuse to overwrite retained evidence')
            shutil.copyfile(path,target);retained.append({'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        batch=__import__('arrival_core.storage',fromlist=['Store']).Store(flow.output).load(flow.batch_id)
        atomic_json(out/'workflow_TEST_ONLY_receipt.json',{'stage':'B2_commit_D1_sync_two_drafts',
                    'batch_id':batch['id'],'revision':batch['revision'],'state_hash':digest(batch),
                    'decision_events':[{k:e[k] for k in ('event_id','type','decision_id','decision_version')} for e in batch.get('decision_events',[])],
                    'artifacts':retained,'authority':'synthetic_technical_test','real_business_approval':False})
    finally:flow.tearDown()
    print(json.dumps({k:v for k,v in receipt.items() if k!='source_manifest'},ensure_ascii=False))
    return 0
if __name__=='__main__':raise SystemExit(main())
