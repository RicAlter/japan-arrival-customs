"""Find unresolved Japanese titles in audited main summaries; partial is evidence only."""
from pathlib import Path
import re
import unicodedata
from .sources import _sheet_names, SourceError
from .xlsxio import iter_rows


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value))).casefold()


def query_keys(value):
    original = unicodedata.normalize('NFKC', str(value))
    stripped = re.sub(r'\((?:単位|单位)[^)]*\)', '', original)
    stripped = re.sub('NO COMMERCIAL VALUE', '', stripped, flags=re.I)
    return sorted({k for k in (compact(original), compact(stripped)) if len(k) >= 6})


def attach_search_candidates(rows, sources, policy):
    unresolved = [r for r in rows if r.get('matching', {}).get('path') == 'unresolved']
    if not unresolved:
        return
    main = [s for s in sources if s['role'] == 'business_summary']
    queries = {r['row_id']: query_keys(r['raw']['ja']) for r in unresolved}
    results = {r['row_id']: [] for r in unresolved}
    scanned = []
    for source in main:
        path = Path(source['path'])
        # Version hashes are checked by the task before source collection and resume.
        if not path.is_file():
            raise SourceError('SOURCE_CHANGED', '日文名补查来源不存在：'+str(path))
        scanned.append({k: source[k] for k in ('source_id','sha256','path')})
        for sheet in _sheet_names(path, 'business_summary'):
            for raw in iter_rows(path, sheet):
                for column, value in raw['values'].items():
                    key = compact(value)
                    if len(key) < 6 or not re.search('[ぁ-ヿ一-龯]', key):
                        continue
                    for row_id, keys in queries.items():
                        if any(q == key or q in key or (len(key) >= 8 and key in q) for q in keys):
                            results[row_id].append({'source_id':source['source_id'],'source_sha256':source['sha256'],
                                'role':'business_summary','sheet':sheet,'row':raw['row'],'column':column,'value':value,
                                'match_kind':'normalized_exact' if key in keys else 'partial_text_only',
                                'adopted':False,'reason':'搜索命中仅作候选，须核对作品、人物、版本及包装；通用品名不能直接采用'})
    for row in unresolved:
        row['japanese_name_search'] = {'status':'candidates_only' if results[row['row_id']] else ('not_found' if main else 'source_not_supplied'),
             'query':row['raw']['ja'],'query_keys':queries[row['row_id']],'sources_scanned':scanned,
             'candidates':results[row['row_id']],'automatic_adoption':False}
