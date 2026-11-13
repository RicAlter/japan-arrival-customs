"""Run unchanged workspace regression against this candidate's imported core."""
import argparse
import hashlib
import json
import sys
import unittest
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('legacy_root',type=Path);p.add_argument('receipt',type=Path)
    args=p.parse_args();root=args.legacy_root.resolve()
    candidate=Path(__file__).resolve().parents[1]/'workbuddy/japan-arrival-customs/scripts'
    sys.path.insert(0,str(candidate))
    import arrival_core
    frozen=json.loads((root/'reports/p2_d1/historical_manifest.json').read_text(encoding='utf-8'))
    def check():
        changed=[name for name,h in frozen.items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=h]
        if changed:raise RuntimeError('历史资产变化:'+repr(changed))
    check()
    suite=unittest.TestSuite();loader=unittest.TestLoader()
    for pattern in ('test_p1*.py','test_p2a.py','test_p2b1.py','test_p2b2.py','test_p2d1.py'):
        suite.addTests(loader.discover(str(root/'tests'),pattern=pattern))
    for name,module in list(sys.modules.items()):
        if name.startswith('test_') and hasattr(module,'SCRIPTS'):module.SCRIPTS=candidate
    result=unittest.TextTestRunner(verbosity=1).run(suite);check()
    receipt={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
             'skipped':len(result.skipped),'frozen_files_unchanged':len(frozen),'candidate_core':arrival_core.__file__,
             'version':arrival_core.__version__,'workbuddy_live_test':'not_run'}
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False));sys.exit(not result.wasSuccessful())


if __name__=='__main__':main()
