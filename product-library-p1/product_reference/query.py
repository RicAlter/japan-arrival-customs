"""Row-preserving batch retrieval; identity evidence never becomes approval."""
import json
from collections import Counter, defaultdict
from contextlib import closing

from .b4_store import IDENTITY_FIELDS, BASIC_FIELDS, MATERIAL_FIELDS, ORDER_FIELDS, canonical
from .core import Rejected
from .database import read_only, require_b4, digest


def text(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise Rejected('身份字段须为标量字符串/数值，不能是对象或布尔')
    if isinstance(value, float):
        if not value.is_integer():
            raise Rejected('数值编码/身份不能含小数；请保留源字符串')
        value = int(value)
    return str(value).strip() or None


def normalize(identity):
    value = {k: text(identity.get(k)) for k in IDENTITY_FIELDS}
    # JAN is a namespace, not a guess from a string's length or checksum.
    if value['code_type'] and value['code_type'].casefold() == 'jan':
        value['code_type'] = 'JAN'
    if value['code_raw'] and not value['code_type']:
        value['code_type'] = 'source_identifier'
    return value


def comparable(value):
    # No fuzzy names, translated-name substitutions or punctuation stripping.
    return ' '.join((value or '').split()).casefold()


def has_material(candidate):
    unknown = {'未找到','未知','无资料','待确认','不明','no data','no_data','unknown','not found'}
    return any(m['field'] in {'material_original','material_translation','complete_composition'}
               and comparable(str(m['value'])) not in unknown for m in candidate['material_references'])


class BatchQuery:
    def __init__(self, database):
        self.database = database

    def run(self, items, *, namespace_aliases=None, exclude_source_ids=None, exclude_file_sha256=None):
        if not isinstance(items, list) or any(not isinstance(q, dict) for q in items):
            raise Rejected('批量查询必须是逐行对象数组；同码不同版本不能折叠')
        aliases = namespace_aliases or []
        for alias in aliases:
            if (not isinstance(alias, dict) or set(alias) != {'from', 'to', 'reference'}
                    or not all(isinstance(v, str) and v.strip() for v in alias.values())):
                raise Rejected('跨编码命名空间需明确from/to及依据，禁止自动猜JAN')
        for exclusions in (exclude_source_ids, exclude_file_sha256):
            if exclusions is not None and (not isinstance(exclusions, list) or any(not isinstance(v, str) for v in exclusions)):
                raise Rejected('来源排除范围必须为字符串数组')
        excluded_sources = set(exclude_source_ids or [])
        excluded_files = set(exclude_file_sha256 or [])
        before = digest(self.database)
        with closing(read_only(self.database)) as conn:
            require_b4(conn)
            by_code, by_name, meta = defaultdict(set), defaultdict(set), {}
            for row in conn.execute('SELECT observation_sha256,identity_json,source_id FROM source_ingest_observations'):
                if row['source_id'] in excluded_sources:
                    continue
                raw = json.loads(row['identity_json']); identity = normalize(raw)
                oid = row['observation_sha256']; meta[oid] = (identity, raw)
                if identity['code_raw']:
                    by_code[(identity['code_type'], identity['code_raw'])].add(oid)
                elif identity['japanese_name']:
                    by_name[comparable(identity['japanese_name'])].add(oid)
            plans, requested_ids = [], set()
            for index, q in enumerate(items):
                allowed = set(IDENTITY_FIELDS) | {'row_id', 'jan', 'source'}
                if set(q) - allowed:
                    raise Rejected('查询包含未知字段：' + ','.join(sorted(set(q) - allowed)))
                identity = normalize(q); keys = []
                if identity['code_raw']:
                    keys.append((identity['code_type'], identity['code_raw']))
                jan = text(q.get('jan'))
                if jan:
                    keys.append(('JAN', jan))
                for kind, code in list(keys):
                    keys.extend((a['to'], code) for a in aliases if a['from'] == kind)
                ids = set().union(*(by_code.get(k, set()) for k in keys)) if keys else by_name.get(comparable(identity['japanese_name']), set())
                plans.append((index, q, identity, keys, set(ids))); requested_ids.update(ids)
            rows = {}
            ids = sorted(requested_ids)
            for start in range(0, len(ids), 500):
                chunk = ids[start:start+500]
                for row in conn.execute('SELECT * FROM source_ingest_observations WHERE observation_sha256 IN (' + ','.join('?' for _ in chunk) + ')', chunk):
                    record = json.loads(row['record_json'])
                    if record.get('review_status') != 'reference_only' or record.get('approval') is not False:
                        raise Rejected('来源记录含批准状态，拒绝将其混入参考查询')
                    if record['provenance'].get('file_sha256') not in excluded_files:
                        rows[row['observation_sha256']] = (dict(row), record)
            corrections = defaultdict(list)
            for row in conn.execute('SELECT * FROM source_ingest_corrections'):
                corrections[row['identity_key']].append(dict(row))
            results = [self._result(index, q, identity, keys, [rows[k] for k in sorted(ids) if k in rows], meta, corrections)
                       for index, q, identity, keys, ids in plans]
        if digest(self.database) != before:
            raise Rejected('批量查询期间库变化，结果失效')
        return {'schema': 'product-reference-batch-result/1', 'database_sha256': before,
                'rows': results, 'summary': dict(Counter(r['status'] for r in results)),
                'namespace_aliases': aliases, 'exclude_source_ids': sorted(excluded_sources),
                'exclude_file_sha256': sorted(excluded_files), 'database_unchanged': True,
                'automatic_approval': False, 'd1_accessed': False, 'formal_output': False}

    @staticmethod
    def _result(index, q, identity, keys, rows, meta, corrections):
        groups = defaultdict(list)
        for row, record in rows:
            groups[row['identity_key']].append((row, record))
        candidates, rejected = [], []
        for key, observations in sorted(groups.items()):
            first = observations[0][0]; candidate_identity, raw_identity = meta[first['observation_sha256']]
            mismatches, unknown = [], []
            for field in ('japanese_name', 'version', 'specification'):
                wanted, actual = identity[field], candidate_identity[field]
                if wanted and actual and comparable(wanted) != comparable(actual):
                    mismatches.append(field)
                elif wanted != actual and (wanted is None or actual is None):
                    unknown.append(field)
            values, sources, materials, issues, contextual = defaultdict(dict), [], [], [], []
            for row, record in observations:
                source = {'observation_sha256': row['observation_sha256'], 'source_id': row['source_id'],
                          'source_record_id': row['source_record_id'], **record['provenance'],
                          'status': row['status'], 'purchase_candidate_state': row['purchase_candidate_state']}
                sources.append(source)
                for field, body in record['fields'].items():
                    if body.get('value') is None and body.get('raw_value') not in (None, ''):
                        issues.append({'field': field, 'reason': 'unresolved_source_value', 'raw_value': body['raw_value'], 'source': source, 'evidence': body['evidence']})
                    if field in ORDER_FIELDS or field in IDENTITY_FIELDS:
                        continue
                    value = body.get('value')
                    if value in (None, '', []):
                        continue
                    item = {'value': value, 'raw_value': body.get('raw_value'), 'source': source,
                            'reference_type': body['reference_type'], 'evidence': body['evidence'],
                            'translation_status': body.get('translation_status'), 'approval': False}
                    if field in {'packaging_label','packaging_original'}:
                        # F may contain this batch's quantities. Preserve each
                        # observation, not a competing product-master value.
                        contextual.append({'field': field, **item})
                        continue
                    if field in MATERIAL_FIELDS:
                        materials.append({'field': field, **item})
                    if row['status'] == 'succeeded':
                        bucket = values[field].setdefault(canonical(value), {'value': value, 'sources': []})
                        bucket['sources'].append(item)
            conflicts = {field: list(variants.values()) for field, variants in values.items() if len(variants) > 1}
            fields = {field: next(iter(variants.values())) for field, variants in values.items() if len(variants) == 1}
            resolved = []
            for correction in corrections.get(key, []):
                # Existing B4 corrections are references; material/classification not promoted.
                if correction['field_name'] in BASIC_FIELDS:
                    field = correction['field_name']
                    fields[field] = {'value': json.loads(correction['value_json']), 'sources': [],
                                     'manual_reference': correction['reference']}
                    conflicts.pop(field, None); resolved.append(correction)
            exact = all(identity[f] == candidate_identity[f] for f in IDENTITY_FIELDS)
            anchor = bool(keys) and any(identity[f] for f in ('japanese_name', 'version', 'specification'))
            value = {'identity_key': key, 'identity': raw_identity, 'match': 'exact_observed_identity' if exact and anchor else 'candidate_only',
                     'identity_missing': [f for f in IDENTITY_FIELDS if not candidate_identity[f]],
                     'unknown_comparisons': unknown, 'mismatched_fields': mismatches,
                     'fields': fields, 'material_references': materials, 'conflicts': conflicts,
                     'missing_fields': sorted(BASIC_FIELDS - set(fields)), 'sources': sources,
                     'manual_resolutions': resolved, 'source_issues': issues,
                     'contextual_references': contextual, 'automatic_approval': False}
            (rejected if mismatches else candidates).append(value)
        if not keys:
            status = 'no_code_candidates' if candidates else 'no_source_code'
        elif not candidates:
            status = 'identity_conflict' if rejected else 'no_match'
        elif len(candidates) > 1:
            status = 'ambiguous'
        elif candidates[0]['conflicts']:
            status = 'matched_with_conflict'
        elif candidates[0]['match'] == 'exact_observed_identity':
            status = 'exact_reference'
        else:
            status = 'candidates_incomplete_identity'
        return {'index': index, 'row_id': q.get('row_id', str(index + 1)), 'query': q,
                'status': status, 'candidates': candidates, 'rejected_candidates': rejected,
                'missing_identity': [f for f in IDENTITY_FIELDS if not identity[f]],
                'material_reference_available': any(has_material(c) for c in candidates),
                'automatic_approval': False, 'final_material_selected': False}


def evidence(database, observation_sha256, relative_file):
    """Read a referenced evidence blob, checking bundle linkage and its hash."""
    with closing(read_only(database)) as conn:
        require_b4(conn)
        row = conn.execute('''SELECT f.content,f.sha256 FROM source_ingest_files f
            JOIN source_ingest_bundle_records r ON r.bundle_sha256=f.bundle_sha256
            WHERE r.observation_sha256=? AND f.relative_path=? LIMIT 1''', (observation_sha256, relative_file)).fetchone()
        if row is None:
            raise Rejected('该观察记录没有此证据文件')
        import hashlib
        if hashlib.sha256(row['content']).hexdigest() != row['sha256']:
            raise Rejected('数据库证据内容哈希不一致')
        return json.loads(row['content'])
