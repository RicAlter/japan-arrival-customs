import argparse,json
from pathlib import Path
from .support import load,save

def main():
    p=argparse.ArgumentParser(description='第一阶段基础资料候选；不计算盒规/差价，不更新日方价格')
    s=p.add_subparsers(dest='action',required=True)
    a=s.add_parser('prepare');a.add_argument('--request',required=True);a.add_argument('--output',required=True)
    a=s.add_parser('finalize');a.add_argument('--output',required=True)
    for action in ['status','preview','plan','commit','history']:
        a=s.add_parser(action);a.add_argument('--workflow',required=True)
        if action=='preview':a.add_argument('--file',required=True);a.add_argument('--expected-hash',required=True)
        if action=='plan':a.add_argument('--preview',required=True);a.add_argument('--selection',required=True)
        if action=='commit':
            a.add_argument('--plan',required=True);a.add_argument('--confirmed-hash',required=True);a.add_argument('--explicit-confirmation',action='store_true');a.add_argument('--reference',required=True)
    args=p.parse_args()
    if args.action in {'prepare','finalize'}:
        from .build import prepare,finalize
        result=prepare(load(args.request),args.output) if args.action=='prepare' else finalize(args.output)
    else:
        from .service import Service
        m=load(args.workflow);svc=Service(m['a03_root']);bid=m['batch_id']
        if args.action=='status':
            v=svc.read_current(bid);result={k:v[k] for k in ['batch_id','revision','current_hash','confirmed_field_count','stage','pricing_deferred','box_confirmation_required','can_enter_b','formal_output']}
        elif args.action=='preview':result=svc.preview_return(bid,args.file,expected_hash=args.expected_hash)
        elif args.action=='plan':result=svc.prepare_confirmation(args.preview,load(args.selection))
        elif args.action=='commit':result=svc.commit(args.plan,confirmed_hash=args.confirmed_hash,explicit_confirmation=args.explicit_confirmation,reference=args.reference)
        else:result=svc.history(bid)
        if args.action in {'preview','plan','commit'}:
            identity=result.get('preview_id') or result.get('plan_id') or result.get('transaction_id');target=Path(args.workflow).parent/'host-readouts'/(args.action+'-'+identity+'.json')
            if not target.exists():save(target,result)
            result={'result_file':str(target),**{k:result[k] for k in ['message','status','preview_id','plan_id','current_hash','revision','replayed'] if k in result}}
    print(json.dumps(result,ensure_ascii=False,default=str))
if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'status':'rejected','reason':str(e),'positions':getattr(e,'positions',[])},ensure_ascii=False));raise SystemExit(1)
