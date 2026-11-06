from . import ROOT,REPO
from loop.support import *
from . import ROOT,REPO

def bootstrap():
    from loop.support import bootstrap as old
    old()
    lock=ROOT/'reuse-lock.json'
    if lock.exists():check_hashes({str(REPO/p):h for p,h in load(lock)['files'].items()})

def code_snapshot():
    from loop.support import code_snapshot as old
    return {**old(),**{str(p):digest(p) for p in (ROOT/'packloop').glob('*.py')},str(ROOT/'review-author.mjs'):digest(ROOT/'review-author.mjs')}

def load_module(name,file,replace=None):
    import types,sys
    m=types.ModuleType(name);m.__file__=str(file);m.__package__=name.rpartition('.')[0];sys.modules[name]=m
    code=Path(file).read_text(encoding='utf-8')
    if replace:
        for a,b in replace.items():
            if a not in code:raise Rejected('复用接口版本已变化')
            code=code.replace(a,b)
    exec(compile(code,str(file),'exec'),m.__dict__);return m
