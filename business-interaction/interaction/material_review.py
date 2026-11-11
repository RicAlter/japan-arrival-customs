"""Full-row website and read-only catalogue review, independent of A03 adoption.

Evidence-only stage: it never saves the source workbook or writes the catalogue.
Online transport reuses the validated workspace providers, not a second scraper.
"""
from collections import Counter, defaultdict
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import re
import sys
import unicodedata

from . import ROOT, Rejected, digest, key, load, save
from .preparation_sources import database_records, snapshot

WORKSPACE = ROOT.parents[1]
FIELDS = {'jan': 'ProductCode(JANCode)', 'name_ja': 'DescriptionofGoods',
          'spec': '规格', 'channel': '渠道', 'yd': 'YD',
          'manual_material': '材质', 'website_material': '网站查找材质',
          'database_material_display': '材质参考'}


def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')).lower())


def read_rows(file, sheet=None):
    from openpyxl import load_workbook
    wb = load_workbook(file, read_only=True, data_only=False)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        labels = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))
        columns = {}
        for field, label in FIELDS.items():
            matches = [i for i, v in enumerate(labels) if norm(v) == norm(label)]
            if len(matches) != 1:
                raise Rejected('材质全量查询须唯一表头：' + label)
            columns[field] = matches[0]
        rows = []
        for n, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
            row = {k: str(values[i] if i < len(values) and values[i] is not None else '')
                   for k, i in columns.items()}
            if not row['jan']:
                continue
            # Keep short internal codes in coverage without treating them as JANs.
            if not re.fullmatch(r'\d{1,14}', row['jan']):
                continue
            row.update(row=n, identity_key=key({k: row[k] for k in ('jan', 'name_ja', 'spec', 'yd')}))
            rows.append(row)
        return ws.title, rows
    finally:
        wb.close()


def same_binding(row, binding):
    return all(str(row.get(k) or '') == str(binding.get(k) or '')
               for k in ('jan', 'name_ja', 'spec', 'yd'))


def read_evidence(manifests):
    """Reuse audited successes only, preserving each manifest and raw response."""
    from material_providers.quality import material_quality
    by_jan = defaultdict(list)
    rejected = []
    for filename in manifests:
        p = Path(filename).resolve(strict=True)
        manifest_sha = digest(p)
        data = load(p)
        if 'results' in data and isinstance(data['results'], dict):
            candidates = [{**e['selected'], 'rows': e['rows']}
                          for e in data['results'].values() if e.get('selected')]
        else:
            candidates = data.get('candidates', [])
        for c in candidates:
            reason = None
            if c.get('status') not in (None, 'selected', 'candidate', 200):
                continue
            if not c.get('material_original') or not c.get('material_zh') or not c.get('url'):
                reason = 'incomplete_material_or_source'
            if not material_quality(c.get('material_original')) or not material_quality(c.get('material_zh')):
                reason = 'material_quality_rejected'
            if not c.get('rows'):
                reason = 'missing_identity_bindings'
            if c.get('proposed') is False:
                reason = 'not_accepted'
            rawpaths = []
            if c.get('snapshot'):
                rawpaths.append((c['snapshot'], c.get('content_sha256')))
            rawpaths += [(a['snapshot'], a.get('content_sha256'))
                         for a in c.get('attempts', []) if a.get('snapshot')]
            chain=c.get('identity_chain')
            if chain:
                if str(chain.get('jan'))!=str(c.get('jan')) or not chain.get('snapshot') or not chain.get('content_sha256'):
                    reason='identity_chain_incomplete'
                else:rawpaths.append((chain['snapshot'],chain['content_sha256']))
            if not rawpaths:
                reason = 'missing_raw_snapshot'
            for path, sha in rawpaths:
                raw = Path(path)
                raw = raw if raw.is_absolute() else WORKSPACE / raw
                if not sha or not raw.is_file() or digest(raw) != sha:
                    reason = 'raw_snapshot_hash_mismatch'
            if reason:
                rejected.append({'manifest': str(p), 'jan': c.get('jan'), 'reason': reason})
                continue
            by_jan[str(c.get('jan') or c['rows'][0]['jan'])].append({
                **c, 'manifest': str(p), 'manifest_sha256': manifest_sha})
    return by_jan, rejected


def valid_for_row(c, row):
    if not any(same_binding(row, r) for r in c.get('rows', [])):
        return False
    assessment = c.get('row_identity', {}).get(str(row['row']))
    if isinstance(assessment, dict) and assessment.get('accepted') is False:
        return False
    checks = c.get('identity_checks', {}).get(str(row['row']))
    if isinstance(checks, list) and checks and checks[0] is False:
        return False
    # A JAN-only or fuzzy candidate must not become publishable merely because
    # it carries a nonempty match-status string. Preserve explicit audited rows.
    return (isinstance(assessment,dict) and assessment.get('accepted') is True
            or isinstance(checks,list) and bool(checks) and checks[0] is True
            or c.get('match_status')=='exact_jan_name_spec')


def website_result(candidates, row):
    accepted = [c for c in candidates if valid_for_row(c, row)]
    values = sorted({c['material_zh'] for c in accepted})
    return {'status': 'found' if len(values) == 1 else 'conflict' if values else 'pending',
            'values': values, 'evidence': accepted,
            'existing_R': row['website_material'], 'existing_R_is_new_evidence': False}


def library_result(row, records, cards):
    direct = [r for r in records if str(r.get('jan')) == row['jan']]
    exact = [r for r in direct if r.get('source', {}).get('records') and row['name_ja'] and norm(r.get('name_ja')) == norm(row['name_ja'])
             and norm(r.get('spec')) == norm(row['spec']) and str(r.get('yd') or '') == row['yd']]
    values = sorted({str(v) for r in exact for f in ('material_original', 'material', 'material_zh')
                     for v in r.get('versions', {}).get(f, []) if v})
    return {'status': 'conflict' if len(values) > 1 else 'sku_candidate' if values else 'reference_only' if direct or cards else 'missing',
            'sku_material_values': values, 'exact_records': exact, 'same_code_records': direct,
            'yd_link_sources': cards, 'yd_scope': 'link_material_collection_not_automatic_SKU_material',
            'existing_S': row['database_material_display'], 'adopted': False}


def comparison(library, website):
    left = {norm(v) for v in library['sku_material_values']}
    right = {norm(v) for v in website['values']}
    if library['status'] == 'conflict' or website['status'] == 'conflict':
        return 'source_conflict'
    if left and right:
        # Different languages, percentages or component granularity require review.
        return 'same_text' if left == right else 'needs_review'
    return 'website_only' if right else 'library_only' if left else 'unresolved'


def material_reference_candidate(library):
    """Return a non-approving S-column reference and its evidence level.

    Exact JAN/name/spec/YD material is safe to label SKU-level.  A YD lookup
    remains useful to a reviewer, but is deliberately retained as a collection
    rather than being represented as a SKU confirmation.
    """
    values = library.get('sku_material_values', [])
    if library.get('status') == 'sku_candidate' and len(values) == 1:
        return values[0], 'sku_exact'
    if library.get('status') == 'reference_only':
        yd_values = sorted({str(item.get('material_original')) for item in library.get('yd_link_sources', [])
                            if item.get('material_original') not in (None, '')})
        if yd_values:
            return '\n'.join(yd_values), 'yd_collection_reference'
    return None, 'unavailable'


def apply_material_reference_overlay(config, dual):
    """Fill only blank S cells with auditable library references; never touch O."""
    from openpyxl import load_workbook
    from .preparation_workbook import update_cells

    report = load(dual['reference_report'])
    file = Path(config['prepared_file'])
    wb = load_workbook(file, read_only=True, data_only=True)
    try:
        current = list(wb[config['sheet']].values)
    finally:
        wb.close()
    from .material_reference import binding as reference_binding
    record = Path(config['background']) / 'material-reference-overlay.json'
    prior = load(record).get('rows', {}) if record.exists() else {}
    rows, changes, overlays = {}, [], dict(prior)
    for text_row, item in report['rows'].items():
        row = int(text_row)
        value = current[row - 1]
        binding = item['binding']
        if (str(value[2]), str(value[9] or ''), str(value[6] or ''), str(value[16] or '')) != (
                binding['jan'], binding['name_ja'], binding['spec'], binding['yd']):
            rows[text_row] = {'level': 'identity_changed', 'written': False}
            continue
        candidate, level = material_reference_candidate(item['library'])
        existing = value[18]
        rows[text_row] = {'level': level, 'candidate': candidate, 'existing': existing,
                          'written': False, 'automatic_approval': False}
        if existing in (None, '') and candidate:
            changes.append({'target': 'S' + text_row, 'value': candidate})
            rows[text_row]['written'] = True
            overlays[text_row] = {'binding': reference_binding(value), 'value': candidate,
                                  'before': existing, 'sources': item['library'].get('yd_link_sources', []) or item['library'].get('exact_records', []),
                                  'reference_level': level, 'confirmed': False}
    if changes:
        file.write_bytes(update_cells(file.read_bytes(), config['sheet'], changes))
    payload = {'schema': 'material-reference-overlay/1', 'rows': rows,
               'written_cells': len(changes), 'levels': dict(Counter(r['level'] for r in rows.values())),
               'manual_material_column': 'O', 'manual_material_overwritten': False,
               'file_sha256': digest(file), 'confirmed': 0}
    save(Path(config['background']) / 'material-reference-overlay-audit.json', payload)
    save(record, {'schema': 'linked-material-original-overlay/1', 'rows': overlays, 'approved': 0})
    return payload


def online_candidates(rows, request, output, existing):
    """All products are eligible, regardless of database/manual/R/S contents."""
    if request.get('authorized') is not True or not request.get('access_review'):
        raise Rejected('联网查询须绑定本次授权和站点访问检查文件')
    review = load(request['access_review'])
    allowed = set(review.get('enabled_sites', []))
    if not allowed:
        raise Rejected('访问检查缺少 enabled_sites')
    budget = review.get('request_budget')
    if not isinstance(budget, int) or budget <= 0:
        raise Rejected('访问检查须明确正整数 request_budget')
    provider = ROOT / 'material_providers' / 'fast_material_batch.py'
    if not provider.is_file():
        raise Rejected('已验证的多站材质提供器未随Skill发布；拒绝退化为单站查询')
    spec = importlib.util.spec_from_file_location('material_review_providers', provider)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(provider.parent))
    spec.loader.exec_module(module)
    if allowed - set(module.SITES):
        raise Rejected('访问检查包含尚无自动适配器的站点')
    module.REPORT = output / 'online'
    clients = {s: module.Client(s) for s in module.SITES if s in allowed}
    stops = dict(review.get('stopped_sites', {}))
    # A new isolated batch must receive any historical stop state explicitly.
    # Never reach into a developer's report directory, and never clear a stop
    # state merely because the process restarted.
    for path in request.get('stop_state_files', []):
        stops.update(load(path).get('stopped_sites', {}))
    statefile = output / 'online-state.json'
    state = load(statefile) if statefile.exists() else {'attempts': {}, 'stopped_sites': {}}
    state['enabled_sites']=sorted(allowed)
    stops.update(state['stopped_sites'])
    for s, client in clients.items():
        client.stopped = stops.get(s, '')
        client_get = client.get
        def limited_get(url, get=client_get):
            # Cache reads also consume this conservative run budget.
            nonlocal budget
            if budget <= 0:
                return {'url': url, 'error': 'request_budget_exhausted'}
            budget -= 1
            return get(url)
        client.get = limited_get
    selected_rows = request.get('online_rows')
    if selected_rows is not None:
        if not isinstance(selected_rows, list) or len(set(selected_rows)) != len(selected_rows):
            raise Rejected('online_rows必须是当前表中不重复的行号列表')
        available = {r['row'] for r in rows}
        if set(selected_rows) - available:
            raise Rejected('online_rows包含当前表不存在的行号')
        scope = set(selected_rows)
    else:
        scope = {r['row'] for r in rows}
    pending = {}
    for row in rows:
        if row['row'] not in scope:
            continue
        if not re.fullmatch(r'\d{8,14}',row['jan']):
            continue
        if website_result(existing.get(row['jan'], []), row)['status'] == 'pending':
            pending.setdefault(row['identity_key'], row)
    manifest = output / 'online-candidates.json'
    collected = load(manifest).get('candidates', []) if manifest.exists() else []
    state['scope_rows']=sorted(scope)
    state['strategy']=['verified_cache','jan_fast_sites','channel_or_official_site','japanese_name_fallback','independent_site_fallback']
    state['budget_exhausted']=False
    for binding, row in pending.items():
        if all(client.stopped for client in clients.values()):
            state['stopped_sites']={s:v.stopped for s,v in clients.items() if v.stopped}
            break
        if budget<=0:
            state['budget_exhausted']=True
            break
        attempts = state['attempts'].setdefault(binding, [])
        if any(same_binding(row, r) for c in collected for r in c.get('rows', [])):
            continue
        seen = {a['site'] for a in attempts
                if a.get('status') not in ('network_error', 'http_400', 'http_500', 'http_502', 'http_503')
                and not any(t.get('error') == 'request_budget_exhausted' for t in a.get('attempts', []))}
        for site in module.SITES:
            if site not in clients or site in seen:
                continue
            # A domain-level stop is not a global stop.  In particular, do
            # not spend the shared budget repeatedly calling a client that
            # has already received 403/429; continue with the other sites.
            if clients[site].stopped:
                attempts.append({'site': site, 'status': clients[site].stopped,
                                 'attempts': [], 'skipped': 'domain_stopped'})
                continue
            c = module.query(site, clients[site], row['jan'], row)
            attempts.append(c)
            if c.get('status') == 'http_503':
                clients[site].stopped = 'stopped_503'
            if c.get('material_original'):
                ok, why = module.identity(row, c)
                # Fuzzy similarity alone remains a review candidate, never accepted here.
                if ok and 'name_score_' not in why:
                    bound_rows = [r for r in rows if same_binding(row, r)]
                    c['row_identity'] = {str(r['row']): {'accepted': True, 'reason': why} for r in bound_rows}
                    c['rows'] = bound_rows
                    collected.append(c)
                    save(manifest, {'candidates': collected})
                    break
            state['stopped_sites'] = {s: v.stopped for s, v in clients.items() if v.stopped}
            save(statefile, state)
        state['stopped_sites'] = {s: v.stopped for s, v in clients.items() if v.stopped}
        save(statefile, state)
    # Reuse the same evidence validation path for online and captured results.
    save(statefile, state)
    save(manifest, {'candidates': collected})
    return manifest


def website_execution(row, web, request, state):
    if web['status'] in {'found','conflict'}:
        return {'status':'verified_evidence' if web['status']=='found' else 'conflict',
                'reason':'row_bound_raw_snapshot_verified' if web['status']=='found' else 'conflicting_verified_website_values'}
    if not re.fullmatch(r'\d{8,14}',row['jan']):
        return {'status':'not_executed','reason':'nonstandard_code_not_verified_JAN'}
    if not request.get('allow_online'):
        return {'status':'not_executed','reason':'cache_only_no_verified_evidence'}
    requested = request.get('online_rows')
    if requested is not None and row['row'] not in set(requested):
        return {'status':'not_executed','reason':'outside_authorized_online_scope'}
    attempts=state.get('attempts',{}).get(row['identity_key'],[])
    if not attempts:
        if state.get('enabled_sites') and all(state.get('stopped_sites',{}).get(s) for s in state['enabled_sites']):
            return {'status':'external_access_blocked','reason':'all_enabled_sites_previously_stopped',
                    'stopped_sites':state['stopped_sites'],'network_attempted':False}
        return {'status':'not_executed','reason':'request_budget_exhausted' if state.get('budget_exhausted') else 'no_recorded_website_attempt'}
    transport=[t for a in attempts for t in a.get('attempts',[])]
    errors=[str(t.get('error')) for t in transport if t.get('error')]
    if transport and all(t.get('error')=='request_budget_exhausted' for t in transport):
        status,reason='not_executed','request_budget_exhausted'
    elif transport and all(t.get('error') in {'blocked_403','rate_limited_429','stopped_503'} and not t.get('fetched_at') for t in transport):
        status,reason='external_access_blocked','website_site_previously_stopped'
    elif errors and any(x!='request_budget_exhausted' for x in errors):
        status,reason='external_failure','website_access_failed_or_site_stopped'
    else:
        status,reason='queried_unresolved','no_verified_matching_material'
    return {'status':status,'reason':reason,'site_statuses':[{'site':a.get('site'),'status':a.get('status')} for a in attempts],
            'transport_errors':errors,'network_attempted':any(t.get('fetched_at') and not t.get('from_cache') for t in transport)}


def review_materials(config_file, request):
    config = load(config_file) if config_file else {}
    request = {**config.get('material_review_settings', {}), **request}
    input_path = request.get('input_file') or config.get('prepared_file')
    database_path = request.get('database') or config.get('database', {}).get('path')
    if not input_path or not database_path:
        raise Rejected('材质双来源查询须指定当前工作簿和资料库')
    file, db = Path(input_path).resolve(strict=True), Path(database_path).resolve(strict=True)
    output = Path(request['output']).resolve()
    if output == file.parent or output == db.parent:
        raise Rejected('材质查询输出须用独立后台目录')
    source_sha = digest(file)
    sheet, rows = read_rows(file, request.get('sheet'))
    if not rows:
        raise Rejected('工作簿中未识别到商品行')
    identity = {'source_sha256': source_sha, 'database_original': str(db), 'sheet': sheet}
    if (output / 'run.json').exists():
        if load(output / 'run.json')['identity'] != identity:
            raise Rejected('查询目录已绑定不同输入，须使用新目录')
    else:
        output.mkdir(parents=True, exist_ok=False)
        save(output / 'run.json', {'identity': identity, 'created_at': datetime.now().astimezone().isoformat()})
    dbcopy = output / 'catalogue-snapshot.sqlite3'
    if not dbcopy.exists():
        dbinfo = snapshot(db, dbcopy)
        save(output / 'database-snapshot.json', dbinfo)
    dbinfo = load(output / 'database-snapshot.json')
    if digest(dbcopy) != dbinfo['sha256']:
        raise Rejected('只读资料库快照摘要变化')
    records, cards = database_records(dbcopy, {r['jan'] for r in rows})
    by_code = defaultdict(list)
    for record in records:
        by_code[record['jan']].append(record)
    evidence, rejected = read_evidence(request.get('evidence_manifests', []))
    if request.get('allow_online'):
        manifest = online_candidates(rows, request, output, evidence)
        live, bad = read_evidence([manifest])
        rejected += bad
        for jan, candidates in live.items():
            evidence[jan].extend(candidates)
    online_state=load(output/'online-state.json') if (output/'online-state.json').exists() else {}
    results, queue = {}, []
    for row in rows:
        local = library_result(row, by_code[row['jan']], cards.get(row['yd'], []))
        web = website_result(evidence.get(row['jan'], []), row)
        results[str(row['row'])] = {'binding': row, 'library': local, 'website': web,
                                    'comparison': comparison(local, web), 'adopted': False,
                                    'website_execution':website_execution(row,web,request,online_state)}
        queue.append({**row, 'scope': 'all_products', 'website_status': web['status'],
                      'next_step': 'review_conflict' if web['status'] == 'conflict' else 'reuse_verified_evidence' if web['status'] == 'found' else 'JAN_then_channel_then_exact_Japanese_name',
                      'database_hit_does_not_skip_website': True})
    if digest(file) != source_sha or digest(dbcopy) != dbinfo['sha256']:
        raise Rejected('输入在查询期间变化，请保留证据并用最新输入重跑')
    summary = {'scope': 'all_products', 'rows': len(rows), 'unique_jan': len({r['jan'] for r in rows}),
               'library': dict(Counter(r['library']['status'] for r in results.values())),
               'website': dict(Counter(r['website']['status'] for r in results.values())),
               'comparison': dict(Counter(r['comparison'] for r in results.values())),
               'rejected_evidence': len(rejected), 'online_requested': bool(request.get('allow_online')),
               'online_executed': any(t.get('fetched_at') and not t.get('from_cache') for attempts in online_state.get('attempts',{}).values() for a in attempts for t in a.get('attempts',[])),
               'website_execution':dict(Counter(r['website_execution']['status'] for r in results.values())),
               'workbook_modified': False, 'database_source_read_only': True, 'confirmed': 0}
    save(output / 'full-website-queue.json', {'scope': 'all_products', 'rows': queue})
    save(output / 'material-review.json', {'schema': 'dual-source-material-review/1',
         'source': str(file), 'source_sha256': source_sha, 'database': dbinfo,
         'rows': results, 'summary': summary, 'rejected_evidence': rejected})
    save(output / 'summary.json', summary)
    return {'summary': summary, 'reference_report': str(output / 'material-review.json'),
            'website_queue': str(output / 'full-website-queue.json'), 'business_files': [str(file)],
            'formal_output': False}
