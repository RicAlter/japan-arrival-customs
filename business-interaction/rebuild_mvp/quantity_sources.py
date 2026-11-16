"""Read-only R2 receipt and coordinate-verified quantity evidence adapters."""
from pathlib import Path
import copy
import json
import re
import sqlite3
import zipfile
from contextlib import closing

from .service import MvpError, digest, load_json
from .storage import identity
from .xlsxio import read_book, HEADERS
from .sources import validate_source, _iter_sheet_rows, norm
from .quantity_math import parse_layers, number, UNITS, product_kinds, title_key

SCOPE_COLUMNS = {'carton': 'A', 'origin': 'B', 'code': 'C', 'name': 'F',
                 'specification': 'G', 'ja': 'J', 'qty': 'K', 'yd': 'Q'}


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve(strict=True).as_uri() + '?mode=ro', uri=True)


def read_upstream(root, reference):
    """Never call the old R2 handler: its immutable code binding stays intact."""
    root = Path(root).resolve(strict=True)
    job = load_json(root / 'job.json')
    if job.get('mode') != 'review_return':
        raise MvpError('INPUT_INVALID', '数量换算必须承接R2保存任务')
    with closing(connect_readonly(root / 'candidate.sqlite3')) as db:
        revision, path, sha = db.execute('SELECT revision,path,sha FROM review_state WHERE id=1').fetchone()
        receipts = [json.loads(x[0]) for x in db.execute('SELECT payload FROM review_submissions')]
        decisions = [dict(revision=r, address=a, value=v, evidence=json.loads(e)) for r, a, v, e in
                     db.execute('SELECT revision,address,value,evidence FROM manual_decisions ORDER BY revision,address')]
    if revision < 1 or not any(x.get('revision') == revision and x.get('reference_sha256') == sha
                               and x.get('operator_submission_accepted') is True for x in receipts):
        raise MvpError('INPUT_INVALID', 'R2尚无对应版本保存回执；不能把prepare当运营保存')
    source = Path(path).resolve(strict=True)
    if (reference.get('role') != 'reviewed_basics' or reference.get('sha256') != sha or
            Path(reference.get('path', '')).resolve() != source or
            reference.get('version') != 'operator-return-' + str(revision)):
        raise MvpError('SOURCE_CHANGED', 'reviewed_source与R2当前保存版本不一致')
    initial = Path(job['source']).resolve(strict=True)
    if digest(source) != sha or digest(initial) != job['initial_sha256']:
        raise MvpError('SOURCE_CHANGED', 'R2原始或保存文件发生外部变化')
    if source.with_name('~$' + source.name).exists():
        raise MvpError('TASK_CONFLICT', 'R2保存文件正在编辑')
    return {'task_root': str(root), 'revision': revision, 'path': str(source), 'sha256': sha,
            'batch_id':job['batch_id'],
            'initial_path': str(initial), 'initial_sha256': job['initial_sha256'],
            'job_sha256': digest(root / 'job.json'), 'sheet': job['sheet'], 'decisions': decisions}


def extract_reviewed(upstream):
    book = read_book(upstream['path'])
    initial = read_book(upstream['initial_path'])
    if len(book['sheets']) != 2 or [x['name'] for x in book['sheets']] != [x['name'] for x in initial['sheets']]:
        raise MvpError('INPUT_INVALID', 'R2要求固定两张工作表')
    sheet = next(s for s in book['sheets'] if s['name'] == upstream['sheet'])
    oldsheet = next(s for s in initial['sheets'] if s['name'] == upstream['sheet'])
    if [sheet['rows'][0]['values'].get(chr(65+i), '') for i in range(24)] != HEADERS:
        raise MvpError('FIELD_MAPPING_AMBIGUOUS', 'R2保存件不是认可24列表形')
    oldrows = {r['row']: r for r in oldsheet['rows']}
    lineage = None
    original_rows = {}
    with zipfile.ZipFile(upstream['initial_path']) as z:
        if 'customXml/arrival-mvp-manifest.json' in z.namelist():
            lineage = json.loads(z.read('customXml/arrival-mvp-manifest.json'))
    parent = Path(upstream['initial_path']).parent
    if lineage and (parent/'job.json').is_file() and (parent/'field-evidence.json').is_file():
        from .service import row_semantics
        matching = load_json(parent/'job.json')
        matched = load_json(parent/'field-evidence.json').get('rows', [])
        if matching.get('output_sha256') == upstream['initial_sha256'] and identity(row_semantics(matched)) == matching.get('semantic_sha256'):
            original_rows = {r['source_row']+lineage['layout']['row_offset']:r for r in matched}
    result = []
    merges = sheet['merges']
    anchors = {}
    for merge in merges:
        m = re.fullmatch(r'A(\d+):A(\d+)', merge)
        if m:
            anchor = oldrows.get(int(m[1]), {}).get('values', {}).get('A', '')
            for n in range(int(m[1]), int(m[2])+1):
                anchors[n] = anchor
    for row in sheet['rows'][1:]:
        values = row['values']
        if not values.get('C') or not values.get('J'):
            continue
        n = row['row']
        previous = oldrows.get(n)
        if previous is None or any(values.get(c, '') != previous['values'].get(c, '') for c in ['A','B','C','J','K','L','M']):
            raise MvpError('TASK_CONFLICT', 'R2行身份或原始数量金额变化：'+str(n))
        if any(row['formulas'].get(c) != previous['formulas'].get(c) for c in ['K','L','M']):
            raise MvpError('TASK_CONFLICT', 'R2原始数量金额公式变化：'+str(n))
        scope = {key: values.get(col, '') for key, col in SCOPE_COLUMNS.items()}
        scope['carton'] = scope['carton'] or anchors.get(n, '')
        if n in original_rows:
            original = original_rows[n]
            original_row = original['source_row']
            source_sha = lineage['source_sha256']
            row_id = original['row_id']
        else:
            original_row, source_sha = n, upstream['initial_sha256']
            row_id = identity([source_sha, sheet['name'], n])
        inherited = {}
        for col in 'UVWX':
            if values.get(col, '') != '' or col in row['formulas']:
                decisions = [d for d in upstream['decisions'] if d['address'] == col+str(n)]
                inherited[col] = {'value': values.get(col, ''), 'formula': row['formulas'].get(col),
                                  'kind': 'operator_saved' if decisions else 'inherited_saved_reference',
                                  'source': {'path': upstream['path'], 'sha256': upstream['sha256'],
                                             'sheet': sheet['name'], 'row': n, 'column': col,
                                             'revision': upstream['revision']},
                                  'scope': copy.deepcopy(scope), 'decisions': decisions}
        result.append({'row_id': row_id, 'row': n, 'sheet': sheet['name'], 'scope': scope,
                       'original_identity': {'source_sha256': source_sha, 'source_row': original_row},
                       'raw_cell': {k: row[k].get('K') for k in ('values','types','formulas')},
                       'existing': {c: values.get(c, '') for c in 'UVWX'},
                       'formulas': {c: row['formulas'][c] for c in 'UVWX' if c in row['formulas']},
                       'inherited': inherited})
    return result


class Evidence:
    def __init__(self, path):
        self.path = str(Path(path).resolve(strict=True))
        self.data = load_json(self.path)
        if self.data.get('schema') != 'arrival-quantity-evidence/1':
            raise MvpError('CONFIG_INVALID', '数量依据契约须为arrival-quantity-evidence/1')
        self.sources, self.cells = {}, {}
        for source in self.data.get('sources', []):
            sid = source['source_id']
            if sid in self.sources or not source.get('version') or not source.get('sha256'):
                raise MvpError('CONFIG_INVALID', '数量来源须有唯一ID、版本和SHA')
            source = copy.deepcopy(source)
            source['path'] = str(Path(source['path']).resolve(strict=True))
            role = source['role']
            if role not in {'japanese_batch','reviewed_basics','completed_reference','business_summary',
                            'purchase_list','order_detail','product_catalog','product_card'}:
                raise MvpError('SOURCE_FORBIDDEN', '数量用途未许可来源角色')
            # Reuse exclusion/lineage/hash checks; raw invoices have no matching role.
            validation = {**source, 'source_type': role}
            if role == 'japanese_batch':
                validation['role'] = 'reviewed_basics'
            validate_source(validation)
            self.sources[sid] = source
        self.versions = [{'path': self.path, 'sha256': digest(self.path)}] + [
            {'path': s['path'], 'sha256': s['sha256']} for s in self.sources.values()]

    def verify(self):
        for item in self.versions:
            if not Path(item['path']).is_file() or digest(item['path']) != item['sha256']:
                raise MvpError('SOURCE_CHANGED', '数量来源发生变化')

    def refs(self, refs):
        if not isinstance(refs, list) or not refs:
            raise MvpError('INPUT_INVALID', '数量事实缺原始坐标')
        output = []
        for ref in refs:
            source = self.sources.get(ref.get('source_id'))
            if source is None:
                raise MvpError('SOURCE_FORBIDDEN', '数量引用来源未登记')
            key = (ref['source_id'], ref['sheet'])
            if key not in self.cells:
                role = source['role']
                self.cells[key] = {r['row']: r['values'] for r in _iter_sheet_rows(source['path'], ref['sheet'], role)}
            actual = self.cells[key].get(ref['row'], {}).get(ref['column'])
            if actual is None or str(actual) != str(ref.get('value')):
                raise MvpError('INPUT_INVALID', '数量来源引用与原格不一致')
            output.append({**ref, 'source_sha256': source['sha256'], 'source_version': source['version'],
                           'role': source['role']})
        return output

    def facts(self, row):
        result = {'relations': [], 'observations': {}}
        issues, candidates = [], []
        matches = [x for x in self.data.get('rows', []) if x.get('sheet') == row['sheet'] and x.get('row') == row['row']]
        if len(matches) > 1:
            return result, [{'code':'IDENTITY_AMBIGUOUS','field':'scope'}], matches
        if matches:
            record = matches[0]
            if set(record.get('scope', {})) != set(SCOPE_COLUMNS) or any(norm(record['scope'][k]) != norm(v) for k,v in row['scope'].items()):
                return result, [{'code':'PACKAGING_SCOPE_MISMATCH','field':'scope'}], matches
            try:
                for item in record.get('packaging', []):
                    try:
                        refs = self.refs(item['evidence'])
                        excerpt = item['excerpt']
                        if not excerpt or not any(excerpt in r['value'] for r in refs) or item.get('scope') != 'exact_sku':
                            raise MvpError('INPUT_INVALID', '包装须为原文子段并经过具体SKU范围核验')
                        target_kinds = product_kinds(row['scope']['specification'])
                        reference_kinds = product_kinds(excerpt)
                        if reference_kinds and (not target_kinds or not set(target_kinds) & set(reference_kinds)):
                            raise MvpError('INPUT_INVALID', '包装原文属于其他SKU品种')
                        if any(r['role'] == 'product_card' for r in refs):
                            identities = self.refs(item.get('identity_evidence', []))
                            names = [r['value'] for r in identities if r['role'] == 'product_card']
                            if not any(title_key(name) == title_key(row['scope']['name']) for name in names):
                                raise MvpError('INPUT_INVALID', '产品卡商品身份未能对应当前名称')
                            box_sku = bool(re.search(r'整盒|盒装|BOX',row['scope']['specification'],re.I))
                            if not reference_kinds and not box_sku and any(len(product_kinds(name)) > 1 for name in names):
                                raise MvpError('INPUT_INVALID', '混合商品通用盒规不得套角色单品')
                        for relation in parse_layers(excerpt):
                            result['relations'].append({**relation, 'evidence':refs, 'scope':record['scope']})
                    except (MvpError,KeyError,TypeError) as exc:
                        candidates.append(item)
                        issues.append({'code':getattr(exc,'code','INPUT_INVALID'),'field':'relations','message':str(exc)})
                if record.get('qty_unit'):
                    unit = record['qty_unit']
                    if unit['unit'] not in UNITS or not unit.get('basis'):
                        raise MvpError('INPUT_INVALID', '原数量单位须有明确解释')
                    result['qty_unit'] = {**unit, 'evidence': self.refs(unit['evidence'])}
                if record.get('allow_split_quantity'):
                    result['allow_split_quantity'] = self.refs(record['split_quantity_evidence'])
                if record.get('v_unit'):
                    if record['v_unit'] not in {'box','pack','set'}:
                        raise MvpError('INPUT_INVALID', 'V包装单位不明确')
                    result['v_unit'] = record['v_unit']
                if record.get('blind'):
                    blind = record['blind']
                    refs = self.refs(blind['evidence'])
                    text = ' '.join(x['value'] for x in refs)
                    positive = bool(re.search(r'盲盒|盲抽|ブラインド|ﾌﾞﾗｲﾝﾄﾞ', text))
                    negative = bool(re.search(r'非盲盒|非盲抽|非ランダム', text))
                    if not isinstance(blind['value'],bool) or (blind['value'] and (not positive or negative)) or (not blind['value'] and not negative):
                        raise MvpError('INPUT_INVALID', '盲抽标记缺明确原文')
                    result['blind'] = {**blind, 'evidence': refs}
                for field, obs in record.get('observations', {}).items():
                    if field not in {'total_pieces','box_count'}:
                        raise MvpError('CONFIG_INVALID', '不支持的数量观察字段')
                    refs = self.refs(obs['evidence'])
                    if not any(number(r['value']) == number(obs['value']) for r in refs) or number(obs['value']) is None:
                        raise MvpError('INPUT_INVALID', '数量观察必须对应明确数值原格')
                    result['observations'][field] = {**obs, 'evidence': refs, 'kind':'source_observation'}
            except (MvpError, KeyError, TypeError) as exc:
                # Invalid evidence affects this shipment only, never becomes a fact.
                result = {'relations': [], 'observations': {}}
                candidates.append(record)
                issues.append({'code': getattr(exc,'code','INPUT_INVALID'), 'field':'evidence', 'message':str(exc)})
        for col, field in [('U','box_count'), ('X','total_pieces')]:
            inherited = row['inherited'].get(col)
            if inherited and col not in row['formulas']:
                if field in result['observations']:
                    result.setdefault('observation_candidates',[]).append({'field':field,**result['observations'][field]})
                result['observations'][field] = {'value': inherited['value'], 'evidence':[inherited['source']],
                                                  'kind': inherited['kind']}
        inherited = row['inherited'].get('W')
        if inherited and 'W' not in row['formulas'] and inherited['value'] in ('是','否','盲盒','盲抽','非盲盒','非盲抽'):
            result['blind'] = {'value':inherited['value'] in ('是','盲盒','盲抽'),
                               'evidence':[inherited['source']],'kind':inherited['kind']}
        return result, issues, candidates
