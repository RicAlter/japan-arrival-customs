"""Version-bound, resumable matching jobs. All business decisions are in code/config."""
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import copy
import datetime
import hashlib
import json
import os
import re
import traceback

from . import SCHEMA
from .storage import Store, canonical, identity

HERE = Path(__file__).resolve().parent
ERRORS = {'INPUT_INVALID', 'CONFIG_INVALID', 'SOURCE_FORBIDDEN', 'FIELD_MAPPING_AMBIGUOUS',
          'SOURCE_CHANGED', 'TASK_CONFLICT', 'RUNTIME_FAILURE'}


class MvpError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def code_version():
    files = sorted(p for p in HERE.rglob('*') if p.is_file() and p.suffix in {'.py', '.json', '.mjs'}
                   and 'tests' not in p.parts and '__pycache__' not in p.parts)
    values = {p.relative_to(HERE).as_posix(): digest(p) for p in files}
    values['../run.py'] = digest(HERE.parent / 'run.py')
    return {'sha256': identity(values), 'files': values}


@contextmanager
def writer(root):
    """OS-owned lock releases automatically on process exit, including interruption."""
    file = (root / '.writer.lock').open('a+b')
    try:
        if file.tell() == 0:
            file.write(b'0'); file.flush()
        file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MvpError('TASK_CONFLICT', '本任务已有执行进程；请查看current，勿并发重建') from exc
        yield
    finally:
        file.close()


def validated_config(request):
    config = {k: copy.deepcopy(v) for k, v in request.items()
              if k not in {'action', 'request_id', 'workflow', 'task_root'}}
    allowed = {'batch_id', 'input_file', 'sources', 'layout_contract', 'output', 'policy','candidate_review','translation_file'}
    if set(config) - allowed:
        raise MvpError('CONFIG_INVALID', '不支持的配置字段：' + ','.join(sorted(set(config) - allowed)))
    if not re.fullmatch(r'[\w.-]{1,100}', str(config.get('batch_id', ''))):
        raise MvpError('INPUT_INVALID', '需要有效批次编号')
    if not config.get('sources') or not isinstance(config['sources'], list):
        raise MvpError('CONFIG_INVALID', '需要已审计来源配置列表')
    if sum(source.get('role') == 'business_summary' for source in config['sources']) > 1:
        raise MvpError('CONFIG_INVALID', '至今报单汇总只能绑定已确认的最新版，不能混用历史版本')
    from .sources import validate_source
    # Validate all restrictions before reading any source content or creating a database.
    for source in config['sources']:
        validate_source(source)
    for key in ['input_file', 'layout_contract', 'output']:
        if not config.get(key):
            raise MvpError('CONFIG_INVALID', '缺少配置：' + key)
        config[key] = str(Path(config[key]).resolve())
    if Path(config['input_file']).suffix.lower() != '.xlsx':
        raise MvpError('INPUT_INVALID', '本MVP只接收xlsx原表')
    config['policy'] = str(Path(config.get('policy', HERE / 'policy.json')).resolve())
    if 'candidate_review' in config and (not isinstance(config['candidate_review'],dict) or set(config['candidate_review'])-{'enabled'} or not isinstance(config['candidate_review'].get('enabled',False),bool)):
        raise MvpError('CONFIG_INVALID','candidate_review只支持enabled布尔开关')
    if config.get('translation_file'):config['translation_file']=str(Path(config['translation_file']).resolve(strict=True))
    for source in config['sources']:
        source['path'] = str(Path(source['path']).resolve())
    output = Path(config['output'])
    for source in [config['input_file'], config['layout_contract'], config['policy']] + [s['path'] for s in config['sources']]:
        if Path(source).is_relative_to(output):
            raise MvpError('CONFIG_INVALID', '输出目录不能包含原始来源')
    return config


def version_manifest(config):
    paths = [(config['input_file'], 'japanese_batch'), (config['layout_contract'], 'layout'), (config['policy'], 'policy')]
    paths += [(s['path'], s['role']) for s in config['sources']]
    if config.get('translation_file'):paths.append((config['translation_file'],'translation_candidates'))
    files = []
    for path, role in paths:
        p = Path(path)
        if not p.is_file():
            raise MvpError('INPUT_INVALID', '本机来源不存在：' + path)
        files.append({'path': path, 'role': role, 'sha256': digest(p), 'bytes': p.stat().st_size})
    for source in config['sources']:
        found = next(x for x in files if x['path'] == source['path'] and x['role'] == source['role'])
        if source.get('sha256') and source['sha256'] != found['sha256']:
            raise MvpError('SOURCE_CHANGED', '已登记来源哈希不符：' + source['path'])
    return {'code': code_version(), 'config_sha256': identity(config), 'files': files}


def verify_versions(job):
    expected = job['versions']
    if expected['code'] != code_version():
        raise MvpError('SOURCE_CHANGED', '源码版本变化；本任务不能静默换代码续跑，请另建任务')
    for item in expected['files']:
        if not Path(item['path']).is_file() or digest(item['path']) != item['sha256']:
            raise MvpError('SOURCE_CHANGED', '固定输入、来源或规则已变化：' + item['path'])


def row_semantics(rows):
    """Comparison excludes only local paths/time/run bookkeeping, never business evidence."""
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in {'path', 'source_path', 'observed_at', 'queried_at'}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return clean(rows)


def summarize(rows):
    values = Counter()
    routes = Counter()
    issues = Counter()
    for row in rows:
        values.update(k for k, v in row.get('values', {}).items() if v not in ('', None))
        routes[row.get('matching', {}).get('path', row.get('match_path', row.get('match_method', 'unspecified')))] += 1
        issues.update(i['code'] for i in row.get('issues', []))
    return {'rows': len(rows), 'filled_fields': dict(sorted(values.items())),
            'match_routes': dict(sorted(routes.items())), 'issue_counts': dict(sorted(issues.items())),
            'rows_with_issues': sum(bool(x.get('issues')) for x in rows)}


def public(job):
    return {'schema': SCHEMA, 'task_id': job['task_id'], 'batch_id': job['config']['batch_id'],
            'task_root': job['config']['output'], 'status': job['status'], 'step': job['step'],
            'versions': {'code_sha256': job['versions']['code']['sha256'],
                         'config_sha256': job['versions']['config_sha256'],
                         'policy_sha256': next(x['sha256'] for x in job['versions']['files'] if x['role'] == 'policy')},
            'business_files': job.get('business_files', []), 'summary': job.get('summary', {}),
            'semantic_sha256': job.get('semantic_sha256'), 'issues': job.get('issue_sample', []),
            'error': job.get('error'), 'next_action': 'current' if job['step'] == 'exported' else 'resume',
            'acceptance': {'technical_verified': False, 'terra_verified': False,
                           'operator_approved': False, 'formally_installed': False},
            'message': '基础资料及候选核对稿；运营修改通过独立review_return任务接收，完整计算与正式安装尚未完成。'}


def execute(request):
    action = request.get('action')
    if action not in {'prepare', 'current', 'resume'}:
        raise MvpError('INPUT_INVALID', '匹配MVP仅支持prepare/current/resume')
    if action == 'prepare':
        config = validated_config(request)
        root = Path(config['output'])
    else:
        root = Path(request.get('task_root', '')).resolve()
        config = None
        if not request.get('task_root') or not (root / 'job.json').is_file():
            raise MvpError('INPUT_INVALID', '请提供已建立的任务目录')
    if action == 'current':
        job = load_json(root / 'job.json')
        result = public(job)
        for output in job.get('business_files', []):
            if not Path(output).is_file() or digest(output) != job['output_sha256']:
                result.update(status='failed', error={'code': 'SOURCE_CHANGED', 'message': '已交付文件有变化；保留现文件，不覆盖，请人工核对', 'retryable': False}, business_files=[])
        return result
    root.mkdir(parents=True, exist_ok=True)
    with writer(root):
        if (root / 'job.json').exists():
            job = load_json(root / 'job.json')
            if config is not None and config != job['config']:
                raise MvpError('TASK_CONFLICT', '同一输出目录已绑定其他输入或配置；请使用新目录')
            verify_versions(job)
            if job['step'] == 'exported':
                return execute({'action': 'current', 'task_root': str(root)})
        else:
            if action != 'prepare':
                raise MvpError('INPUT_INVALID', '任务尚未建立')
            extras = [p for p in root.iterdir() if p.name != '.writer.lock']
            if extras:
                raise MvpError('TASK_CONFLICT', '输出目录非空且没有本MVP任务记录，请使用新目录')
            versions = version_manifest(config)
            job = {'schema': SCHEMA, 'task_id': identity([config['batch_id'], versions])[:24],
                   'config': config, 'versions': versions, 'status': 'running', 'step': 'registered',
                   'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
            save_json(root / 'job.json', job)
        store = Store(root / 'candidate.sqlite3')
        try:
            from .xlsxio import extract_batch, write_book
            from .sources import collect_sources
            from .matching import match_batch
            config = job['config']
            batch = store.get_checkpoint('extracted')
            if batch is None:
                batch = extract_batch(config['input_file'])
                store.save_batch(config['batch_id'], batch)
            job.update(step='extracted', status='running', error=None)
            save_json(root / 'job.json', job)
            collected = store.get_checkpoint('sources')
            if collected is None:
                def progress(value):
                    job['source_progress'] = value
                    save_json(root / 'job.json', job)
                collected = collect_sources(config['sources'], batch, progress=progress)
                store.save_sources(collected)
            job['step'] = 'sources_collected'; save_json(root / 'job.json', job)
            rows = store.get_checkpoint('matched')
            if rows is None:
                rows = match_batch(batch, collected, policy=load_json(config['policy']))
                from .candidate_pipeline import apply_candidates
                rows = apply_candidates(rows,config)
                if [x['row_id'] for x in rows] != [x['row_id'] for x in batch['rows']]:
                    raise MvpError('TASK_CONFLICT', '匹配改变了商品原行序或身份')
                store.save_matches(config['batch_id'], rows)
            job.update(step='matched', summary=summarize(rows), semantic_sha256=identity(row_semantics(rows)))
            job['issue_sample'] = []
            for row in rows:
                for issue in row.get('issues', []):
                    if len(job['issue_sample']) >= 8: break
                    sample = {k: v for k, v in issue.items() if k != 'candidates'}
                    sample.update(row_id=row['row_id'], source_row=row['source_row'], product_code=row['raw']['code'])
                    if issue.get('candidates'):
                        sample['candidate_count'] = len(issue['candidates'])
                    job['issue_sample'].append(sample)
            save_json(root / 'job.json', job)
            save_json(root / 'field-evidence.json', {'schema': SCHEMA, 'rows': rows})
            from .yd_diagnostics import explain_yd
            save_json(root / 'YD-reasons.json',explain_yd(rows,batch.get('metadata',{}).get('header_row',1)))
            save_json(root / 'source-audit.json', {'sources': collected['sources'], 'audit': collected.get('audit', {})})
            # Inputs might have been changed during a long import; never export a mixed snapshot.
            verify_versions(job)
            outfile = root / (config['batch_id'] + '_基础资料匹配_无图片.xlsx')
            if outfile.exists():
                raise MvpError('TASK_CONFLICT', '存在尚未登记的交付文件；保留现文件，请人工核对')
            export = write_book(config['input_file'], outfile, rows, config['layout_contract'],
                                {'schema': SCHEMA, 'task_id': job['task_id'], 'semantic_sha256': job['semantic_sha256'],
                                 'source_sha256': batch['source']['sha256'], 'rules_sha256': digest(config['policy'])})
            job.update(step='exported', status='partial' if job['summary']['rows_with_issues'] else 'completed',
                       business_files=[str(outfile)], output_sha256=digest(outfile), export=export,
                       database_counts=store.counts())
            save_json(root / 'job.json', job)
            return public(job)
        except Exception as exc:
            code = getattr(exc, 'code', str(exc).split(':', 1)[0])
            if code not in ERRORS: code = 'RUNTIME_FAILURE'
            job.update(status='failed', error={'code': code, 'message': str(exc), 'retryable': code == 'RUNTIME_FAILURE'})
            save_json(root / 'job.json', job)
            (root / 'failure-trace.txt').write_text(traceback.format_exc(), encoding='utf-8')
            return public(job)
        finally:
            store.close()


def handle(request):
    try:
        mode=request.get('mode')
        if not mode and request.get('task_root'):
            jf=Path(request['task_root'])/'job.json'
            if jf.is_file():mode=load_json(jf).get('mode')
        if mode=='review_return':
            from .review_return import handle as review_return
            return review_return(request)
        enrichment=request.get('mode')=='enrich_review'
        if not enrichment and request.get('task_root'):
            jobfile=Path(request['task_root'])/'job.json'
            enrichment=jobfile.is_file() and load_json(jobfile).get('mode')=='enrich_review'
        if enrichment:
            from .enrichment import handle as enrich
            return enrich(request)
        return execute(request)
    except Exception as exc:
        code = getattr(exc, 'code', str(exc).split(':', 1)[0])
        if code not in ERRORS: code = 'RUNTIME_FAILURE'
        return {'schema': SCHEMA, 'task_id': None, 'status': 'failed', 'step': 'not_started',
                'business_files': [], 'summary': {}, 'issues': [],
                'error': {'code': code, 'message': str(exc), 'retryable': code == 'RUNTIME_FAILURE'},
                'next_action': 'correct_input_or_config' if code != 'RUNTIME_FAILURE' else 'resume'}
