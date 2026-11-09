"""WorkBuddy host adapter. Business users never prepare JSON/commands themselves."""
import argparse,json,sys
from interaction.service import Service
p=argparse.ArgumentParser();p.add_argument('--config');p.add_argument('--request',required=True);p.add_argument('--result-file');a=p.parse_args()
try:
    from interaction import load,save
    request=load(a.request);action=request.pop('action')
    if action=='prepare':
        from interaction.preparation import prepare
        result=prepare(request)
    elif action=='material-review':
        from interaction.material_review import review_materials
        result=review_materials(a.config,request)
    elif action=='query-materials':
        from interaction.website_query import query_materials
        result=query_materials(a.config,request)
    elif action=='delivery-review':
        from interaction.delivery_review import review_delivery
        result=review_delivery(a.config,**request)
    elif action in {'start','current'}:result=Service(a.config).deliver()
    elif action=='upload':result=Service(a.config).upload(**request)
    elif action=='confirm':result=Service(a.config).confirm(**request)
    else:raise ValueError('不支持的动作；正式外发未开放')
    if a.result_file:save(a.result_file,result)
    print(json.dumps(result,ensure_ascii=False,default=str))
except Exception as e:print(json.dumps({'status':'blocked','message':str(e),'business_files':[]},ensure_ascii=False));sys.exit(1)
