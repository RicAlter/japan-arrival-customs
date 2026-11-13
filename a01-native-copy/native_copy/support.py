"""Pin and reuse the frozen readers, read-only query and persistence helpers."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


class Rejected(ValueError):
    pass


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def key(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def snapshot_root(path):
    """Keep the frozen Store unchanged while supporting its long temp filenames."""
    value = str(Path(path).resolve())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def bootstrap():
    lock = load(ROOT / 'dependency-lock.json')
    if lock.get('schema') != 'a01-reused-dependencies/1' or lock.get('baseline') != '8dcd1cf':
        raise Rejected('A-01依赖锁类型或基线不一致')
    for rel, expected in lock['files'].items():
        path = (REPO / rel).resolve(strict=True)
        if not path.is_relative_to(REPO) or digest(path) != expected:
            raise Rejected('复用依赖变化：' + rel)
    paths = [REPO / 'rc8-operations-colored-v1/workbuddy/japan-arrival-customs/scripts',
             REPO / 'product-library-p1', REPO / 'operations-library-p3a']
    for name, root in [('arrival_core', paths[0]), ('product_reference', paths[1]), ('integrated_arrival', paths[2])]:
        existing = sys.modules.get(name)
        if existing and not Path(existing.__file__).resolve().is_relative_to(root):
            raise Rejected('不能混载其他版本：' + name)
    for path in paths:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return lock


def check_hashes(snapshot):
    for path, expected in snapshot.items():
        if digest(path) != expected:
            raise Rejected('处理期间来源、资料库或程序发生变化：' + Path(path).name)


def save(path, value):
    from arrival_core.storage import atomic_json
    path = Path(path)
    if path.exists():
        raise Rejected('登记/证据已存在，拒绝覆盖：' + path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value)
