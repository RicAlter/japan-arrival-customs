"""Execute unchanged legacy tests with an OS-file copy-on-write test overlay.
Original paths and content-addressed JSON bytes remain unchanged. Only writes
are redirected; no business data, confirmations, or prices are fabricated.
"""
import os,sys,io,json,hashlib,shutil,tempfile,unittest,importlib.util,traceback
from pathlib import Path
RUN=Path(os.environ['REGRESSION_OUTPUT']).resolve();RUN.mkdir(parents=True,exist_ok=True);W=Path(os.environ['PRIVATE_PROJECT_ROOT']).resolve()
SRC=Path(os.environ['CANDIDATE_SOURCE']).resolve()
FIXED=os.environ['CANDIDATE_VERSION']
mode=sys.argv[1];attempt=sys.argv[2] if len(sys.argv)>2 else 'initial'
overlay=RUN/('overlay-'+mode+'-'+attempt);overlay.mkdir(exist_ok=True)
temp=RUN/('temp-'+mode+'-'+attempt);temp.mkdir(exist_ok=True);tempfile.tempdir=str(temp)
def sha(p):
    with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
original={n:getattr(os,n) for n in ['stat','lstat','mkdir','unlink','rmdir','rename','replace','scandir','listdir','open','link','chmod','utime']}
open0=io.open;builtin_open=open;deleted=set();writes=[]
base=os.path.normcase(str(W));ov=os.path.normcase(str(overlay));run=os.path.normcase(str(RUN))
def normalized(p):
    s=os.fsdecode(p)
    if s.startswith('\\\\?\\'):s=s[4:]
    return os.path.normcase(os.path.abspath(s))
def inside(p,root):return p==root or p.startswith(root+os.sep)
def native(p):
    if isinstance(p,int):return p
    s=os.fsdecode(p)
    return s if s.startswith('\\\\?\\') else '\\\\?\\'+os.path.abspath(s)
def mapped(p):
    if isinstance(p,int):return p
    s=normalized(p)
    # Some unchanged tests derive report/helper paths from the frozen source.
    # Redirect those writes too; package and results need not share a directory.
    frozen=normalized(SRC.parent)
    if inside(s,frozen) and not inside(s,run):return str(overlay/'frozen-runtime'/Path(os.path.relpath(s,frozen)))
    return str(overlay/Path(os.path.relpath(s,base))) if inside(s,base) and not inside(s,run) else p
def exists(p):
    try:original['stat'](native(p));return True
    except FileNotFoundError:return False
def readpath(p):
    if isinstance(p,int):return p
    if normalized(p) in deleted:raise FileNotFoundError(2,'No such file',str(p))
    q=mapped(p)
    if q!=p and exists(q):return native(q)
    # Legacy helper derives its workspace from its source location. Bind its
    # report/pointer reads to existing original fixtures, not invented data.
    logical=normalized(p);fixture_root=normalized(SRC.parent)
    for folder in ['reports','outputs']:
        prefix=os.path.join(fixture_root,folder)
        if inside(logical,prefix):
            alias=W/Path(os.path.relpath(logical,fixture_root))
            if exists(alias):return native(alias)
    return native(p)
def ensure(p):
    if exists(p):return
    parent=os.path.dirname(p)
    if parent and parent!=p:ensure(parent)
    try:original['mkdir'](native(p))
    except FileExistsError:pass
def writepath(p,retain=False):
    if isinstance(p,int):return p
    q=mapped(p);s=normalized(q)
    if not inside(s,run):raise PermissionError('write outside isolated test run: '+str(p))
    ensure(os.path.dirname(str(q)))
    if retain and q!=p and not exists(q) and exists(p):
        with open0(native(p),'rb') as a,open0(native(q),'wb') as b:shutil.copyfileobj(a,b)
    deleted.discard(normalized(p));writes.append({'logical':os.fsdecode(p),'physical':os.fsdecode(q)})
    return native(q)
def opened(file,mode='r',*a,**k):
    writing=any(x in mode for x in 'wax+')
    if 'x' in mode and exists(readpath(file)):raise FileExistsError(str(file))
    return open0(writepath(file,retain=('a' in mode or '+' in mode)) if writing else readpath(file),mode,*a,**k)
import builtins,_io
builtins.open=opened;io.open=opened
_io.open_code=lambda p:opened(p,'rb')
os.stat=lambda p,*a,**k:original['stat'](readpath(p),*a,**k)
os.lstat=lambda p,*a,**k:original['lstat'](readpath(p),*a,**k)
os.mkdir=lambda p,*a,**k:original['mkdir'](writepath(p),*a,**k)
def unlink(p,*a,**k):
    q=writepath(p)
    if exists(q):original['unlink'](q,*a,**k)
    deleted.add(normalized(p))
os.unlink=unlink;os.remove=unlink
os.rmdir=lambda p,*a,**k:original['rmdir'](writepath(p),*a,**k)
os.rename=lambda a,b,*args,**k:original['rename'](readpath(a),writepath(b),*args,**k)
os.replace=lambda a,b,*args,**k:original['replace'](readpath(a),writepath(b),*args,**k)
def osopen(p,flags,*a,**k):
    writing=bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
    if flags & os.O_EXCL and normalized(p) not in deleted and exists(readpath(p)):raise FileExistsError(str(p))
    return original['open'](writepath(p,retain=not bool(flags & os.O_TRUNC)) if writing else readpath(p),flags,*a,**k)
os.open=osopen
os.link=lambda a,b,*args,**k:shutil.copyfile(readpath(a),writepath(b))
os.chmod=lambda p,*a,**k:original['chmod'](writepath(p,retain=True),*a,**k)
os.utime=lambda p,*a,**k:original['utime'](writepath(p,retain=True),*a,**k)
class Entry:
    def __init__(self,p,name):self.name=name;self.path=os.path.join(os.fsdecode(p),name)
    def __fspath__(self):return self.path
    def is_dir(self,follow_symlinks=True):return __import__('stat').S_ISDIR(self.stat(follow_symlinks=follow_symlinks).st_mode)
    def is_file(self,follow_symlinks=True):return __import__('stat').S_ISREG(self.stat(follow_symlinks=follow_symlinks).st_mode)
    def is_symlink(self):return False
    def is_junction(self):return False
    def stat(self,follow_symlinks=True):return os.stat(self.path,follow_symlinks=follow_symlinks)
    def inode(self):return self.stat().st_ino
class Scan:
    def __init__(self,p):
        names={}
        for q in [p,mapped(p)]:
            try:
                with original['scandir'](native(q)) as it:
                    for x in it:names[x.name]=Entry(p,x.name)
            except FileNotFoundError:pass
        self.it=iter(x for x in names.values() if normalized(x.path) not in deleted)
    def __iter__(self):return self
    def __next__(self):return next(self.it)
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def close(self):pass
os.scandir=Scan;os.listdir=lambda p:[e.name for e in Scan(p)]
# A second independent guard sees physical OS mutations after redirection.
def audit(event,args):
    paths=[]
    if event=='open':
        f,m,flags=args
        if isinstance(f,(str,bytes)) and ((isinstance(m,str) and any(c in m for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):paths=[f]
    elif event in {'os.mkdir','os.remove','os.rmdir','os.chmod','os.utime'}:paths=[args[0]]
    elif event in {'os.rename','os.link'}:paths=list(args[:2])
    for p in paths:
        if isinstance(p,(str,bytes)) and not inside(normalized(p),run):raise PermissionError('audit denied external mutation: '+str(p))
sys.addaudithook(audit)
if mode in ('interaction','units'):
    file=SRC/'business-interaction/tests';cls=None;expected=None
elif mode=='loop':
    os.environ['LOOP_REPLAY_DIR']=str(W/'outputs/KMT20261101_完整闭环候选_20261106_v1')
    file=SRC/'business-loop/tests/test_loop.py';cls='FullReplay';expected=21
else:
    os.environ['PACK_REPLAY_DIR']=str(W/'outputs/KMT20261101_资料库包装闭环候选_20261106_v3')
    file=SRC/'catalogue-pack-loop/tests/test_units.py';cls='Full';expected=16
    helper=SRC.parent/'reports/business-loop-20261105/run.py'
    # This is a test helper/configuration copy, never a candidate source edit.
    q=writepath(helper)
    if not exists(q):
        with open0(W/'reports/business-loop-20261105/run.py','rb') as a,open0(q,'wb') as b:b.write(a.read())

network_attempts=[]
def no_network(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):
        network_attempts.append({'event':event,'args':str(args)});raise PermissionError('offline regression only')
sys.addaudithook(no_network)

records=[]
class Result(unittest.TextTestResult):
    def startTest(self,test):
        super().startTest(test);records.append({'test':test.id(),'status':'started'})
    def addSuccess(self,test):super().addSuccess(test);records[-1]['status']='passed'
    def addFailure(self,test,err):super().addFailure(test,err);records[-1].update(status='failed',reason=self._exc_info_to_string(err,test))
    def addError(self,test,err):
        super().addError(test,err)
        if records and records[-1]['test']==test.id():records[-1].update(status='error',reason=self._exc_info_to_string(err,test))
        else:records.append({'test':test.id(),'status':'setup_error','reason':self._exc_info_to_string(err,test)})
    def addSkip(self,test,reason):super().addSkip(test,reason);records[-1].update(status='not_executed',reason=reason)
try:
    if mode in ('interaction','units'):
        sys.path.insert(0,str(SRC/'business-interaction'));sys.path.insert(0,str(SRC/'business-interaction/material_providers'))
        suite=unittest.defaultTestLoader.discover(str(file))
        def flatten(s):
            for t in s:
                if isinstance(t,unittest.TestSuite):yield from flatten(t)
                else:yield t
        if mode=='units':
            modules={'test_matching_repair','test_attention_display','test_pcs_enrichment','test_dg_enrichment','test_material_review','test_material_reference','test_material_provider_release','test_kmt_accuracy','test_material_v2_sample30','test_large_return','test_quantity_review','test_delivery_review','test_preparation','test_pack_reference','test_photo_layout','test_freeze_candidate','test_original_view','test_stage_submission'}
            suite=unittest.TestSuite(t for t in flatten(suite) if t.__class__.__module__ in modules)
            for rel,excluded in [('business-loop/tests/test_loop.py','FullReplay'),('catalogue-pack-loop/tests/test_units.py','Full')]:
                spec=importlib.util.spec_from_file_location('unified_'+excluded,SRC/rel);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
                extra=unittest.defaultTestLoader.loadTestsFromModule(mod)
                suite.addTests(t for t in flatten(extra) if t.__class__.__name__!=excluded)
        ids=[t.id() for t in flatten(suite)]
        if mode=='units':assert len(ids)==231,len(ids)
    else:
        spec=importlib.util.spec_from_file_location('fixed_'+mode,file);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(getattr(mod,cls));ids=[t.id() for t in suite];assert len(ids)==expected
    if os.environ.get('TEST_FILTER'):
        suite=unittest.TestSuite(t for t in (flatten(suite) if mode in ('interaction','units') else suite) if any(k in t.id() for k in os.environ['TEST_FILTER'].split(',')));ids=[t.id() for t in suite]
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    started={r['test'] for r in records}
    for test in ids:
        if test not in started:records.append({'test':test,'status':'not_executed','reason':'class setup failed; see setup_error'})
    payload={'candidate':FIXED,'kind':'unchanged existing synthetic regression assets; not real business approval','mode':mode,'records':records,'tests_run':result.testsRun,'network_attempts':network_attempts,'write_paths':writes}
except Exception:
    payload={'candidate':FIXED,'mode':mode,'fatal':traceback.format_exc(),'records':records,'write_paths':writes}
with open0(RUN/(mode+'-'+attempt+'-results.json'),'w',encoding='utf8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
if payload.get('fatal') or any(r['status']!='passed' for r in payload['records']):
    raise SystemExit(1)
