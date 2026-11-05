import argparse
import json
from .service import Service,load

p=argparse.ArgumentParser(description='B00本批依据分组预览、明确确认和A04复核；无Excel输出')
p.add_argument('operation',choices=['fork','preview','confirm','preflight','read'])
p.add_argument('--root',required=True);p.add_argument('--request',required=True)
a=p.parse_args();r=load(a.request)
if a.operation=='fork':
    service=Service.fork(r['existing'],a.root);result={'root':str(service.root)}
else:
    service=Service(a.root)
    result=getattr(service,{'preview':'preview_basis','confirm':'commit_basis','preflight':'preflight','read':'read_basis'}[a.operation])(**r)
print(json.dumps(result,ensure_ascii=False,indent=2))
