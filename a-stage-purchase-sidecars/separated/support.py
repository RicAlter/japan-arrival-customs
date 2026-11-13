from pathlib import Path
from . import ROOT,REPO
from stage1.support import Rejected,digest,key,load,save,check_hashes
from stage1.support import bootstrap as original_bootstrap
def bootstrap():
    original_bootstrap()
    lock=load(ROOT/'dependency-lock.json')
    if lock.get('schema')!='stage1-sidecar-reuse/1':raise Rejected('分表候选复用锁无效')
    check_hashes({str(REPO/p):h for p,h in lock['files'].items()})
def code_snapshot():
    return {str(p):digest(p) for p in (ROOT/'separated').glob('*.py')}
