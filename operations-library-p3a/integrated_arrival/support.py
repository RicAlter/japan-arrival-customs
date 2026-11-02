import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent


class Rejected(ValueError):pass


def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def key(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))


def dependencies():
    lock=load(ROOT/'dependency-lock.json')
    for rel,expected in lock['files'].items():
        path=(REPO/rel).resolve(strict=True)
        if not path.is_relative_to(REPO) or digest(path)!=expected:raise Rejected('冻结依赖哈希不匹配：'+rel)
    for rel in ('product-library-p1','product-identity-p2b','product-usability-p2c',
                'rc8-operations-colored-v1/workbuddy/japan-arrival-customs/scripts'):
        sys.path.insert(0,str(REPO/rel))
    return lock


def check_hashes(snapshot):
    for path,expected in snapshot.items():
        if digest(path)!=expected:raise Rejected('处理期间原件、资料库或结果发生变化：'+Path(path).name)
