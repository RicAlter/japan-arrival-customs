"""Inspect existing B4 databases read-only; mutations require an explicit clone."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .core import Rejected


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_only(path):
    path = Path(path).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


def metadata(conn):
    try:
        return dict(conn.execute('SELECT key,value FROM metadata'))
    except sqlite3.DatabaseError as exc:
        raise Rejected('不是支持的商品参考库；禁止初始化、迁移或打开D1索引') from exc


def require_b4(conn):
    meta = metadata(conn)
    if meta.get('source_bundle_schema_version') != '1':
        raise Rejected('需现有B4来源库V1；旧商品库和D1不能当作B4来源库使用')
    required = {
        'source_ingest_observations': {'observation_sha256', 'identity_json', 'fields_json', 'record_json', 'status'},
        'source_ingest_files': {'bundle_sha256', 'relative_path', 'content', 'sha256'},
        'source_ingest_bundle_records': {'bundle_sha256', 'observation_sha256'},
        'source_ingest_bundles': {'sha256', 'manifest_json', 'record_count'},
        'source_ingest_corrections': {'identity_key', 'field_name', 'value_json', 'reference'},
    }
    for table, fields in required.items():
        if not fields <= {r['name'] for r in conn.execute('PRAGMA table_info(' + table + ')')}:
            raise Rejected('B4结构不完整：' + table)
    return meta


def inspect(path):
    path = Path(path).resolve(strict=True)
    before = digest(path)
    with closing(read_only(path)) as conn:
        meta = metadata(conn)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        integrity = [r[0] for r in conn.execute('PRAGMA integrity_check')]
        result = {'path': str(path), 'sha256': before, 'metadata': meta,
                  'integrity': integrity, 'tables': {}, 'rc5_legacy_schema_supported': meta.get('schema_version') == '2',
                  'b4_query_supported': meta.get('source_bundle_schema_version') == '1', 'migrated': False}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            result['tables'][table] = {
                'rows': conn.execute('SELECT count(*) FROM ' + quoted).fetchone()[0],
                'columns': [r['name'] for r in conn.execute('PRAGMA table_info(' + quoted + ')')]}
        if result['b4_query_supported']:
            require_b4(conn)
            counts = {k: 0 for k in ('code_raw', 'code_type', 'japanese_name', 'version', 'specification')}
            for row in conn.execute('SELECT identity_json FROM source_ingest_observations'):
                identity = json.loads(row[0])
                for k in counts:
                    counts[k] += identity.get(k) not in (None, '')
            result['identity_nonempty'] = counts
            result['sources'] = [{'manifest': json.loads(r[0]), 'records': r[1]}
                                 for r in conn.execute('SELECT manifest_json,record_count FROM source_ingest_bundles')]
            result['foreign_key_errors'] = list(map(tuple, conn.execute('PRAGMA foreign_key_check')))
    if digest(path) != before:
        raise Rejected('检查期间数据库变化，结果失效')
    result['unchanged'] = True
    return result


def clone(source, destination):
    source = Path(source).resolve(strict=True)
    target = Path(destination).resolve()
    marker = Path(str(target) + '.p1-snapshot.json')
    if target.exists() or marker.exists():
        raise Rejected('副本或标记已存在；拒绝覆盖/重新初始化')
    before = digest(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(read_only(source)) as src:
        require_b4(src)
        with target.open('xb'):
            pass
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise Rejected('副本完整性失败')
    if digest(source) != before:
        raise Rejected('复制期间原库变化；不得导入该副本')
    value = {'kind': 'p1-explicit-working-copy/1', 'source': str(source),
             'source_sha256': before, 'destination': str(target), 'initial_sha256': digest(target)}
    marker.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


def working_copy(path):
    path = Path(path).resolve(strict=True)
    marker = Path(str(path) + '.p1-snapshot.json')
    if not marker.is_file():
        raise Rejected('只允许导入clone命令创建的工作副本，原库拒绝写入')
    value = json.loads(marker.read_text(encoding='utf-8'))
    if (value.get('kind') != 'p1-explicit-working-copy/1' or value.get('destination') != str(path)
            or Path(value['source']).resolve() == path):
        raise Rejected('工作副本标记不匹配')
    if digest(value['source']) != value['source_sha256']:
        raise Rejected('原库已变化，需重新核对后创建新副本')
    with closing(read_only(path)) as conn:
        require_b4(conn)
    return path, value


def import_bundle(database, bundle, authorization, *, purchase_policy=None):
    from .b4_store import SourceBundleStore, verify_bundle, _purchase_decisions
    path, marker = working_copy(database)
    checked = verify_bundle(bundle)
    _purchase_decisions(checked['records'],checked['manifest']['adapter_id'],purchase_policy)
    if checked['manifest']['authorization_reference'] != authorization.get('reference'):
        raise Rejected('授权引用与来源包不一致')
    if (checked['manifest']['source_id'] not in authorization.get('source_ids', [])
            or checked['manifest']['adapter_id'] not in authorization.get('adapter_ids', [])):
        raise Rejected('来源或适配器不在本次用户授权范围')
    store = SourceBundleStore(path)
    if authorization.get('reference', '').startswith('TEST:'):
        raise Rejected('CLI真实导入不能使用TEST授权')
    store.record_authorization(authorization)
    result = store.import_bundle(bundle, authorization_reference=authorization['reference'],
                                 backup_directory=path.parent / (path.stem + '-backups'),
                                 purchase_policy=purchase_policy)
    if digest(marker['source']) != marker['source_sha256']:
        raise Rejected('原库发生变化，验证失效')
    return result
