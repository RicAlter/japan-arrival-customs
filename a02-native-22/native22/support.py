from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO / 'a02-native-return'))
from native_return.support import Rejected, digest, key, load, check_hashes
from native_return.support import save as original_save
from native_return.support import bootstrap as old_bootstrap


def save(path, value):
    from native_copy.support import snapshot_root
    return original_save(snapshot_root(path), value)


def bootstrap():
    lock = load(ROOT / 'dependency-lock.json')
    if lock.get('schema') != 'a02-native22-dependencies/1' or lock.get('baseline') != 'a39603e':
        raise Rejected('22列候选依赖锁不匹配')
    for relative, expected in lock['files'].items():
        path = (REPO / relative).resolve(strict=True)
        if not path.is_relative_to(REPO) or digest(path) != expected:
            raise Rejected('原实现依赖已变化：' + relative)
    old_bootstrap()
    return lock


def code_snapshot():
    return {str(p): digest(p) for p in (ROOT / 'native22').glob('*.py')}
