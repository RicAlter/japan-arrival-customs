"""Private P1 sample selection and zero-network permission-gate acceptance."""
import argparse
import json
from pathlib import Path

from site_reference.batch import run
from site_reference.client import AnimeStore,sha
from site_reference.compat import Rejected


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--p1-results',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();source=Path(args.p1_results).resolve(strict=True);before=sha(source.read_bytes())
    result=json.loads(source.read_text(encoding='utf-8'));rows=result['rows'];selected=[];seen=set()
    def material(row):
        return any(m['field'] in {'material_original','material_translation','complete_composition'}
                   for c in row['candidates'] for m in c['material_references'])
    groups=[('no_candidate',8,lambda r:r['status']=='no_match'),
            ('incomplete_identity_no_material',8,lambda r:r['status']=='candidates_incomplete_identity' and not material(r)),
            ('ambiguous_no_material',4,lambda r:r['status']=='ambiguous' and not material(r)),
            ('material_reference_identity_pending',4,lambda r:material(r))]
    for name,limit,predicate in groups:
        count=0
        for row in rows:
            code=row['query'].get('code_raw')
            if not code or code in seen or not predicate(row):continue
            seen.add(code);selected.append({'group':name,'p1_status':row['status'],'query':row['query']});count+=1
            if count==limit:break
        if count!=limit:raise Rejected('P1样本不足，不能静默替换分层：'+name)
    output=Path(args.output).resolve()
    if output.exists():raise Rejected('隔离验证目录已存在')
    output.mkdir(parents=True)
    request={'items':[row['query'] for row in selected]}
    (output/'selection.json').write_text(json.dumps({'selection':'deterministic_P1_row_order_stratified_not_population_estimate','source_sha256':before,'rows':selected},ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    client=AnimeStore(output/'runtime',access_scope=None)
    report=run(request,output/'candidate-gate',output/'runtime',client=client)
    assert client.network_calls==0 and not (output/'runtime').exists()
    assert all(row['status']=='permission_denied' and row['reason']=='site_permission_not_provided' for row in report['results'])
    assert all(row['site_response']['references']==[] and row['approval'] is False for row in report['results'])
    assert report['metrics']['product_hit_rate'] is None and report['metrics']['material_reference_rate'] is None
    assert sha(source.read_bytes())==before
    summary={'status':'permission_gate_passed_live_query_not_validated','sample_rows':len(selected),
             'network_calls':0,'database_written':False,'live_product_query_tested':False,
             'original_p1_result_unchanged':True,'metrics':report['metrics']}
    (output/'gate-acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
