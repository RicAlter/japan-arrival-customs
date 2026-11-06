"""WorkBuddy host adapter. Business users never prepare JSON/commands themselves."""
import argparse,json,sys
from interaction.service import Service
p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--request',required=True);p.add_argument('--result-file');a=p.parse_args()
try:
    from interaction import load,save
    request=load(a.request);s=Service(a.config);action=request.pop('action')
    if action in {'start','current'}:result=s.deliver()
    elif action=='upload':result=s.upload(**request)
    elif action=='confirm':result=s.confirm(**request)
    else:raise ValueError('不支持的动作；正式外发未开放')
    if a.result_file:save(a.result_file,result)
    print(json.dumps(result,ensure_ascii=False,default=str))
except Exception as e:print(json.dumps({'status':'blocked','message':str(e),'business_files':[]},ensure_ascii=False));sys.exit(1)
