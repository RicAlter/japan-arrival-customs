"""Historical clean presentation over a pinned final test pair, not a release."""
from pathlib import Path
import subprocess
from . import load,save,key,digest,Rejected
from .test_final import current as test_current
from .presentation_copy import prepare,verify

def current(service):
    source=test_current(service);result=load(service.background/'presentation/current.json')
    if result['source_final_fingerprint']!=key(source['output_sha256']):raise Rejected('外发版式的来源版本已失效')
    for file,sha in result['output_sha256'].items():
        if digest(file)!=sha:raise Rejected('外发版式文件已被改动')
    return result

def generate(service,request):
    if request.get('historical_preview')is not True or not str(request.get('reference')or'').strip():raise Rejected('须明确历史版式查看范围及本次用户出处')
    source=test_current(service);pointer=service.background/'presentation/current.json'
    if pointer.exists():return {**current(service),'receipt_replayed':True}
    folder=service.background/'presentation'/key(source['output_sha256'])[:16];attempt=1
    base=folder
    while folder.exists():folder=base.with_name(base.name+'-attempt'+str(attempt));attempt+=1
    prepare(source,folder,service.config['batch_label'],str(Path(service.config['node']).parent.parent/'node_modules'))
    p=subprocess.run([service.config['node'],str(Path(__file__).parents[1]/'presentation-author.mjs'),str(folder/'plan.json')],capture_output=True,text=True,encoding='utf8')
    if p.returncode:raise Rejected('版式生成失败：'+p.stderr[-1800:])
    check=verify(folder);fresh=test_current(service)
    if fresh['output_sha256']!=source['output_sha256']:raise Rejected('版式生成期间来源已变化')
    files=[service._publish(f['file'],Path(f['file']).name)for f in check['files']]
    result={'stage':'presentation-preview','business_files':files,'output_sha256':{f:digest(f)for f in files},'rows':source['rows'],
        'source_final_fingerprint':key(source['output_sha256']),'source_files':source['output_sha256'],'reference':request['reference'],
        'presentation_only':True,'business_approval_changed':False,'calculation_confirmed':False,'professional_approval':False,'formal_output':False,
        'verification':check,'receipt_replayed':False,'message':'历史批次成品版式；业务数据、计算口径和确认状态保持不变。'}
    save(pointer,result);return result
