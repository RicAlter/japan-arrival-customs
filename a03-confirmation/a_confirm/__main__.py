import argparse
import json
from .service import Service
from .support import load

p=argparse.ArgumentParser(description='独立A-03：登记、预览、指定范围确认、保存及重读；无B计算')
p.add_argument('operation',choices=['register','read','preview','plan','commit','history'])
p.add_argument('--root',required=True);p.add_argument('--request',required=True)
a=p.parse_args();service=Service(a.root);r=load(a.request)
if a.operation=='register':result=service.register(**r)
elif a.operation=='read':result=service.read_current(**r)
elif a.operation=='preview':result=service.preview_return(**r)
elif a.operation=='plan':result=service.prepare_confirmation(**r)
elif a.operation=='commit':result=service.commit(**r)
else:result=service.history(**r)
print(json.dumps(result,ensure_ascii=False,indent=2))
