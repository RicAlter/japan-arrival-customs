"""Reuse pinned A-01 and B2, without changing their contracts."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO / 'a01-native-copy'))
from native_copy.support import Rejected, digest, key, load, save, check_hashes
from native_copy.support import bootstrap as a01_bootstrap


def bootstrap():
    lock = load(ROOT / 'dependency-lock.json')
    if lock.get('schema') != 'a02-reused-dependencies/1' or lock.get('baseline') != '3ccbc76':
        raise Rejected('A-02依赖锁类型或基线不一致')
    for rel, expected in lock['files'].items():
        path = (REPO / rel).resolve(strict=True)
        if not path.is_relative_to(REPO) or digest(path) != expected:
            raise Rejected('A-02复用依赖变化：' + rel)
    existing = sys.modules.get('native_copy')
    if existing and not Path(existing.__file__).resolve().is_relative_to(REPO / 'a01-native-copy'):
        raise Rejected('不能混载其他A-01版本')
    a01_bootstrap()
    return lock
