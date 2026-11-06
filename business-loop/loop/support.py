from pathlib import Path
from copy import deepcopy
from . import ROOT,REPO
from separated.support import bootstrap as accepted_bootstrap
from separated.support import Rejected,digest,key,load,save,check_hashes
accepted_bootstrap()
from a_confirm.support import put,get,archive,path
from a_confirm.locking import writer
def bootstrap():
    accepted_bootstrap()
    pinned=load(ROOT/'dependency-lock.json')
    if pinned.get('schema')!='business-loop-reuse/1':raise Rejected('闭环候选依赖锁无效')
    check_hashes({str(REPO/p):h for p,h in pinned['files'].items()})
    own=ROOT/'runtime-code-lock.json'
    if own.exists():check_hashes({str(ROOT/p):h for p,h in load(own)['files'].items()})
def code_snapshot():return {str(p):digest(p) for p in (ROOT/'loop').glob('*.py')}
def advance(batch,out,action,reference,rows=()):
    from arrival_core.core import changed
    out=changed(batch,out,'local_host_identity_unverified',action,list(rows),{'reference':reference,'professional_approval':False})
    out['a03']['parent_hash']=key(batch)
    out['a03']['version_id']=key({'parent':batch['a03']['version_id'],'revision':out['revision'],'action':action,'data':key(out.get('loop',{}))})
    out['a03']['downstream']={'b_confirmation_valid':False,'c_delivery_valid':False,'recompute_required':True}
    return out
def original_raw(workflow):
    seen=set();p=Path(workflow)
    while str(p) not in seen:
        seen.add(str(p));m=load(p)
        if m.get('original_source'):return Path(m['original_source'])
        if not m.get('prior_workflow'):break
        p=Path(m['prior_workflow'])
    raise Rejected('未找到已登记的日方原始附件')
def field_fingerprint(view):
    return key({k:{name:v.get(name) for name in ['value','confirmed','status','identity_context_hash','confirmation','evidence']} for k,v in view['fields'].items()})
