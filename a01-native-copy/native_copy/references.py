"""Conservative field candidates through the existing P1 read-only API."""
from collections import defaultdict
from contextlib import closing
from decimal import Decimal, InvalidOperation
import json

from .support import Rejected, digest, key

UNKNOWN = {'', '未知', '未找到', '无资料', '待确认', '不明', 'unknown', 'no data', 'not found'}
FORBIDDEN = ('最终', '答案', '评分', 'answer', 'final', 'stage5', '第5步')


def scalar(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value)
    return None if text.strip().casefold() in UNKNOWN else text


def positive_integer(value):
    try:
        v = Decimal(str(value))
        return int(v) if v.is_finite() and v > 0 and v == v.to_integral_value() else None
    except (ValueError, InvalidOperation, TypeError):
        return None


def query(config, source, batch_id):
    if config is None:
        return {'status': 'not_configured', 'rows': [], 'database': None,
                'automatic_approval': False, 'field_candidates': {r['row_id']: {} for r in source['rows']}}
    if (not isinstance(config, dict) or set(config) != {'database', 'allowed_source_ids'}
            or not isinstance(config['database'], str) or not isinstance(config['allowed_source_ids'], list)
            or not config['allowed_source_ids'] or any(not isinstance(x, str) or not x for x in config['allowed_source_ids'])):
        raise Rejected('资料库须显式指定database和本次允许的来源ID，不默认使用全库')
    from integrated_arrival.library import inspect_database
    from product_reference.database import read_only
    from product_reference.query import BatchQuery
    info = inspect_database({'database': config['database'], 'current_batch_id': batch_id})
    allowed = set(config['allowed_source_ids'])
    with closing(read_only(info['path'])) as conn:
        manifests = [json.loads(r[0]) for r in conn.execute('SELECT manifest_json FROM source_ingest_bundles')]
    known = {m['source_id'] for m in manifests}
    if allowed - known:
        raise Rejected('允许的来源未在库中登记')
    for m in manifests:
        if m['source_id'] in allowed and (m.get('adapter_id') not in ('order', 'material', 'packaging')
                or not m.get('authorization_reference') or any(w in m['source_id'].casefold() for w in FORBIDDEN)):
            raise Rejected('来源不属于允许的参考资料范围')
    exclude_sources = known - allowed
    exclude_files = {source['book'].sha256}
    queries = [{'row_id': r['row_id'], 'code_raw': r['code'] or None,
                'code_type': 'source_identifier' if r['code'] else None,
                'japanese_name': r['japanese_name'] or None, 'version': None, 'specification': None}
               for r in source['rows']]
    api = BatchQuery(info['path'])
    result = api.run(queries, exclude_source_ids=sorted(exclude_sources), exclude_file_sha256=sorted(exclude_files))
    # A whitelisted bundle can contain several workbooks. Remove known answer or
    # target-batch lineage before resolving its fields, rather than filtering a summary.
    for row in result['rows']:
        for candidate in row['candidates'] + row['rejected_candidates']:
            for s in candidate['sources']:
                label = ' '.join(str(s.get(k, '')) for k in ('source_id', 'file_name', 'path', 'batch_id')).casefold()
                if any(w in label for w in FORBIDDEN) or batch_id.casefold() in label:
                    if s.get('file_sha256'):
                        exclude_files.add(s['file_sha256'])
                    else:
                        exclude_sources.add(s['source_id'])
    if exclude_files != {source['book'].sha256} or exclude_sources != known - allowed:
        result = api.run(queries, exclude_source_ids=sorted(exclude_sources), exclude_file_sha256=sorted(exclude_files))
    ids = sorted({s['observation_sha256'] for r in result['rows'] for c in r['candidates'] for s in c['sources']})
    records = {}
    with closing(read_only(info['path'])) as conn:
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            for oid, payload in conn.execute('SELECT observation_sha256,record_json FROM source_ingest_observations WHERE observation_sha256 IN (' + ','.join('?' for _ in chunk) + ')', chunk):
                record = json.loads(payload)
                if key(record) != oid or record.get('approval') is not False or record.get('review_status') != 'reference_only':
                    raise Rejected('来源事实校验或参考状态不一致')
                records[oid] = record
    fields = {}
    for row in result['rows']:
        values = {}
        if row['query']['code_raw'] and len(row['candidates']) == 1:
            candidate = row['candidates'][0]
            gathered = defaultdict(dict)
            for s in candidate['sources']:
                record = records[s['observation_sha256']]
                if record['status'] != 'succeeded':
                    continue
                label = ' '.join(str(s.get(k, '')) for k in ('source_id', 'file_name', 'path', 'batch_id')).casefold()
                if s['source_id'] not in allowed or any(w in label for w in FORBIDDEN) or batch_id.casefold() in label:
                    raise Rejected('查询返回已排除的来源')
                def add(field, value, evidence):
                    if value is None or not evidence:
                        return
                    bucket = gathered[field].setdefault(key(value), {'value': value, 'sources': []})
                    bucket['sources'].append({'observation_sha256': s['observation_sha256'],
                        'provenance': record['provenance'], 'evidence': evidence, 'approval': False})
                fs = record['fields']
                for source_field, target in [('internal_name', 'internal_name'), ('specification', 'specification'),
                        ('category', 'category'), ('channel', 'channel'), ('yd', 'yd')]:
                    body = fs.get(source_field, {})
                    add(target, scalar(body.get('value')), body.get('evidence'))
                # Prefer a complete supplied translation. Never invent a translation.
                body = fs.get('material_translation', {})
                if scalar(body.get('value')) is None or body.get('translation_status') in ('unknown', 'pending', 'failed'):
                    body = fs.get('material_original', {})
                add('material_reference', scalar(body.get('value')), body.get('evidence'))
                price = fs.get('unit_price', {})
                if fs.get('currency', {}).get('value') == 'JPY' and scalar(fs.get('purchase_unit', {}).get('value')):
                    try:
                        d = Decimal(str(price.get('value')))
                        if d.is_finite() and d >= 0:
                            add('purchase_unit_price', format(d, 'f'), price.get('evidence'))
                    except InvalidOperation:
                        pass
                # Only a structured relation, never packaging_label/BOX/name parsing.
                relation = fs.get('packaging_relations', {})
                rels = relation.get('value')
                if isinstance(rels, list) and len(rels) == 1 and isinstance(rels[0], dict):
                    rel = rels[0]
                    if rel.get('from_unit') == '盒' and rel.get('to_unit') in ('件', '个'):
                        add('pieces_per_box', positive_integer(rel.get('factor')), relation.get('evidence'))
            for field, variants in gathered.items():
                if len(variants) == 1 and field not in candidate['conflicts']:
                    values[field] = dict(next(iter(variants.values())), status='candidate', confirmed=False)
                elif len(variants) > 1:
                    values[field] = {'status': 'conflict', 'variants': list(variants.values()), 'confirmed': False}
        fields[row['row_id']] = values
    if digest(info['path']) != info['sha256']:
        raise Rejected('只读查询期间库变化')
    return {'status': 'queried', 'database': info, 'rows': result['rows'], 'field_candidates': fields,
            'excluded_source_ids': sorted(exclude_sources), 'excluded_file_sha256': sorted(exclude_files),
            'allowed_source_ids': sorted(allowed), 'automatic_approval': False,
            'p2b_overlay_used': False, 'd1_accessed': False}
