import argparse,json
from pathlib import Path
from .support import load,save
from .service import Service
def main():
    p=argparse.ArgumentParser(description='采购分表后的主表回传；查询表不作为确认回传')
    p.add_argument('action',choices=['status','preview','plan','commit','history']);p.add_argument('--workflow',required=True)
    p.add_argument('--file');p.add_argument('--expected-hash');p.add_argument('--preview');p.add_argument('--selection');p.add_argument('--plan')
    p.add_argument('--confirmed-hash');p.add_argument('--explicit-confirmation',action='store_true');p.add_argument('--reference')
    a=p.parse_args();m=load(a.workflow);s=Service(m['a03_root']);bid=m['batch_id']
    if a.action=='status':
        v=s.read_current(bid);result={k:v[k] for k in ['revision','current_hash','confirmed_field_count','pricing_deferred','purchase_columns_location','can_enter_b','formal_output']}
    elif a.action=='preview':result=s.preview_return(bid,a.file,expected_hash=a.expected_hash)
    elif a.action=='plan':result=s.prepare_confirmation(a.preview,load(a.selection))
    elif a.action=='commit':result=s.commit(a.plan,confirmed_hash=a.confirmed_hash,explicit_confirmation=a.explicit_confirmation,reference=a.reference)
    else:result=s.history(bid)
    if a.action in {'preview','plan','commit'}:
        identity=result.get('preview_id') or result.get('plan_id') or result['transaction_id'];target=Path(a.workflow).parent/'host-readouts'/(a.action+'-'+identity+'.json')
        if not target.exists():save(target,result)
        result={'result_file':str(target),**{k:result[k] for k in ['message','status','preview_id','plan_id','revision','current_hash'] if k in result}}
    print(json.dumps(result,ensure_ascii=False,default=str))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'rejected','reason':str(exc),'positions':getattr(exc,'positions',[])},ensure_ascii=False));raise SystemExit(1)
