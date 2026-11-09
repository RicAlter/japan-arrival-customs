from pathlib import Path
import json,sys,subprocess,argparse,hashlib,re
p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--result-file');p.add_argument('--session');a=p.parse_args()
runtime=Path(__file__).resolve().parents[1]/'runtime.json'
if not runtime.exists():raise SystemExit('候选尚未绑定本机runtime.json；不要改用旧正式Skill。')
c=json.loads(runtime.read_text(encoding='utf-8'))
if c.get('source_manifest'):
    manifest=Path(c['source_manifest']);root=Path(c['source_root']).resolve()
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=c['source_manifest_sha256']:
        raise SystemExit('冻结源码清单漂移，停止执行')
    for name,item in json.loads(manifest.read_text(encoding='utf-8'))['files'].items():
        file=(root/name).resolve()
        if not file.is_relative_to(root) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
            raise SystemExit('冻结源码漂移，停止执行：'+name)
    if not Path(c['entry']).resolve().is_relative_to(root):raise SystemExit('入口不在冻结源码中')
request=json.loads(Path(a.request).read_text(encoding='utf8'))
request_path=Path(a.request).resolve()
if request.get('action')=='prepare' and c.get('preparation_defaults'):
    request={**c['preparation_defaults'],**request}
    if not re.fullmatch(r'[\w.-]{1,100}',str(request.get('batch_id',''))):raise SystemExit('须有明确批次标识')
    if not request.get('output'):
        suffix=hashlib.sha256(Path(request['input_file']).read_bytes()).hexdigest()[:12]
        request['output']=str(Path(c['output_base'])/(request['batch_id']+'-'+suffix))
    folder=Path(c['output_base'])/'requests';folder.mkdir(parents=True,exist_ok=True)
    text=json.dumps(request,ensure_ascii=False,indent=2);request_path=folder/(hashlib.sha256(text.encode()).hexdigest()+'.json');request_path.write_text(text,encoding='utf8')
args=[c['python'],'-X','utf8','-B',c['entry'],'--request',str(request_path)]
if request.get('action')!='prepare':
    session=a.session or c.get('session')
    if not session:raise SystemExit('请先prepare取得本批session')
    args+=['--config',session]
if a.result_file:args+=['--result-file',str(Path(a.result_file).resolve())]
raise SystemExit(subprocess.run(args,check=False).returncode)
