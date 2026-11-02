import argparse
import json
import sqlite3
from pathlib import Path

from .common import Rejected,save,clone,key


def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main(argv=None):
    parser=argparse.ArgumentParser(description='P2-B离线身份补充；不联网，不写D1或原库')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('collect');p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('prepare');p.add_argument('--p1-results',required=True);p.add_argument('--facts',required=True);p.add_argument('--context-config',required=True);p.add_argument('--p1-database',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('copy-register');p.add_argument('--source-database',required=True);p.add_argument('--destination',required=True);p.add_argument('--plan',required=True);p.add_argument('--reference',required=True)
    p=sub.add_parser('book-model');p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('preview-return');p.add_argument('--database',required=True);p.add_argument('--plan-id',required=True);p.add_argument('--workbook',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('apply-return');p.add_argument('--database',required=True);p.add_argument('--preview',required=True);p.add_argument('--confirm-preview',required=True);p.add_argument('--operator-reference',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('batch-query');p.add_argument('--database',required=True);p.add_argument('--queries',required=True);p.add_argument('--batch-id',required=True);p.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:
        if hasattr(args,'output') and Path(args.output).exists():raise Rejected('输出已存在，拒绝覆盖')
        if args.command=='collect':
            from .collect import collect_all
            cfg=load(args.config);facts,reports=collect_all(cfg['source_specs'],load(cfg['p1_results']),args.output)
            result={'facts':len(facts),'sources':len(reports)}
        elif args.command=='prepare':
            from .collect import original_b4_facts
            from .context import read_contexts
            from .analyze import analyze
            from .common import digest
            cfg=load(args.context_config);p1=load(args.p1_results);data=load(args.facts)
            facts=data['facts']+original_b4_facts(args.p1_database,p1)
            result=analyze(p1,facts,read_contexts(p1,cfg['query_workbook'],cfg['query_mapping']),target_batch_id=cfg['target_batch_id'])
            result.update(source_reports=data['reports'],p1_result_sha256=digest(args.p1_results),query_workbook_sha256=digest(cfg['query_workbook']))
            result['plan_id']=key(result);save(args.output,result);result=result['metrics']
        elif args.command=='copy-register':
            from .maintenance import register_plan
            clone(args.source_database,args.destination);result=register_plan(args.destination,load(args.plan),args.reference)
        elif args.command=='book-model':
            from .review import model
            result=model(load(args.plan));save(args.output,result);result={'cases':len(result['rows']),'sources':len(result['source_rows'])}
        elif args.command=='preview-return':
            from .review import preview
            result=preview(args.database,args.plan_id,args.workbook);save(args.output,result)
            result={'confirmed_rows':len(result['edits']),'filled_not_confirmed':len(result['filled_not_confirmed']),'preview_hash':result['preview_hash']}
        elif args.command=='batch-query':
            from .lookup import batch_query
            result=batch_query(args.database,load(args.queries),batch_id=args.batch_id);save(args.output,result)
            result={'rows':len(result['rows']),'complete_identity':result['metrics']['after_complete_identity'],'maintenance_events':result['maintenance_events']}
        else:
            from .maintenance import apply
            result=apply(args.database,load(args.preview),confirmation={'kind':'explicit_basic_product_maintenance_confirmation','preview_hash':args.confirm_preview,'operator_reference':args.operator_reference});save(args.output,result)
        print(json.dumps({'status':'ok','result':result,'material_approval':False,'formal_output':False},ensure_ascii=False));return 0
    except (Rejected,OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        print(json.dumps({'status':'rejected','reason':str(exc),'formal_output':False},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
