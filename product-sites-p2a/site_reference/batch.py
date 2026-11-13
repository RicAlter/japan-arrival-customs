"""Independent candidate files and honest denominators for live evaluation."""
import csv
import json
from collections import Counter
from pathlib import Path

from .client import AnimeStore
from .compat import Rejected,normalize


def metrics(results,network_calls,cache_hits):
    evaluated=[r for r in results if r.get('query_mode')=='live_http' and r.get('fetch',{}).get('http_status') in (200,404)]
    denominator=len(evaluated)
    hits=sum(r.get('product_hit',False) for r in evaluated)
    confirmed=sum(r.get('identity_status')=='confirmed' for r in evaluated)
    materials=sum(bool(r.get('material_original')) and r.get('identity_status')!='conflict' for r in evaluated)
    return {'planned_rows':len(results),'status_counts':dict(Counter(r['status'] for r in results)),
            'live_evaluated_rows':denominator,'network_calls':network_calls,'cache_hits':cache_hits,
            'fresh_live_evaluated_rows':sum(not r['fetch'].get('from_cache',False) for r in evaluated),
            'cached_evidence_evaluated_rows':sum(r['fetch'].get('from_cache',False) for r in evaluated),
            'unique_requested_codes':len({r['query_identity']['code_raw'] for r in results}),
            'product_hit_count':hits,'product_hit_rate':hits/denominator if denominator else None,
            'identity_confirmed_count':confirmed,'identity_confirmation_rate':confirmed/denominator if denominator else None,
            'candidate_material_count':materials,'material_reference_rate':materials/denominator if denominator else None,
            'complete_material_translation_count':sum(bool(r.get('material_original')) and bool(r.get('material_translation')) and r.get('identity_status')!='conflict' for r in evaluated),
            'confirmed_identity_material_count':sum(bool(r.get('material_original')) and r.get('identity_status')=='confirmed' for r in evaluated),
            'identity_conflicts_rejected':sum(r.get('identity_status')=='conflict' for r in evaluated),
            'independently_adjudicated_rows':0,'false_association_rate':None,
            'notice':'无独立人工标注，不把未发现错误称为零错误率；无实测分母时比率为null'}


def run(request,output,runtime,*,access_scope=None,client=None):
    if not isinstance(request,dict) or set(request)!={'items'} or not isinstance(request['items'],list):
        raise Rejected('批量请求须仅含items数组；授权单独由可信操作侧提供')
    allowed={'row_id','code_raw','code_type','jan','japanese_name','version','specification','source'}
    if any(not isinstance(q,dict) or set(q)-allowed for q in request['items']):raise Rejected('请求包含未知字段或凭据')
    for q in request['items']:normalize(q)  # Reject malformed input before any request.
    out=Path(output).resolve()
    if out.exists():raise Rejected('候选输出目录已存在，拒绝覆盖')
    client=client or AnimeStore(runtime,access_scope=access_scope)
    results=[client.query(q) for q in request['items']]
    report={'schema':'product-site-candidate-batch/1','site_id':'anime-store',
            'results':results,'metrics':metrics(results,client.network_calls,client.cache_hits),
            'database_written':False,'d1_accessed':False,'formal_output':False,'workbuddy_tested':False}
    out.mkdir(parents=True)
    (out/'candidates.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    with (out/'unmatched.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['query_id','code','status','identity_status','reason'])
        for r in results:
            if r['identity_status']!='confirmed' or not r.get('material_original'):
                values=[r['query_id'],r['query_identity']['code_raw'],r['status'],r['identity_status'],r.get('reason')]
                writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in values])
    return report
