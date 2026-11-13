from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
sys.path.insert(0,str(REPO/'a03-confirmation'))
from a_confirm.support import Rejected,digest,key,load,path,put,get,check_hashes
from a_confirm.support import bootstrap as legacy_bootstrap

def bootstrap():
    legacy_bootstrap()
    lock=ROOT/'dependency-lock.json'
    if lock.is_file():
        data=load(lock)
        if data.get('schema')!='stage1-frozen-reuse/1':raise Rejected('第一阶段依赖锁无效')
        check_hashes({str(REPO/p):h for p,h in data['files'].items()})

def code_snapshot():
    return {str(p):digest(p) for p in sorted((ROOT/'stage1').glob('*.py'))}

def save(file,value):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
