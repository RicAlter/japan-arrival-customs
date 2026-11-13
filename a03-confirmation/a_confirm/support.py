from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO/'a02-native-22'))
from native22.support import Rejected, digest, key, load, check_hashes
from native22.support import bootstrap as old_bootstrap


def bootstrap():
    lock = load(ROOT/'dependency-lock.json')
    if lock.get('schema') != 'a03-reused-dependencies/1' or lock.get('baseline') != '1fcacf1':
        raise Rejected('A-03依赖锁不匹配')
    for relative, expected in lock['files'].items():
        path = (REPO/relative).resolve(strict=True)
        if not path.is_relative_to(REPO) or digest(path) != expected:
            raise Rejected('冻结依赖变化：'+relative)
    old_bootstrap()
    return lock


def path(value):
    from native_copy.support import snapshot_root
    return snapshot_root(value)


def archive(file, data):
    from arrival_core.excel_return import _archive
    return _archive(path(file), data)


def put(root, value):
    """B2 exclusive content-addressed archive, not mutable business state."""
    import json
    identity = key(value)
    archive(Path(root)/'objects'/(identity+'.json'), json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode())
    return identity


def get(root, identity):
    from arrival_core.excel_return import safe_id
    safe_id(identity)
    value = load(path(Path(root)/'objects'/(identity+'.json')))
    if key(value) != identity: raise Rejected('不可变对象摘要不一致')
    return value
