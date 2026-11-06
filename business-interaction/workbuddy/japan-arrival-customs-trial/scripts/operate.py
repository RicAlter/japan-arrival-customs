from pathlib import Path
import json,sys,subprocess,argparse
p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--result-file');a=p.parse_args()
runtime=Path(__file__).resolve().parents[1]/'runtime.json'
if not runtime.exists():raise SystemExit('候选尚未绑定本机runtime.json；不要改用旧正式Skill。')
c=json.loads(runtime.read_text(encoding='utf-8'))
args=[c['python'],'-X','utf8','-B',c['entry'],'--config',c['session'],'--request',str(Path(a.request).resolve())]
if a.result_file:args+=['--result-file',str(Path(a.result_file).resolve())]
raise SystemExit(subprocess.run(args,check=False).returncode)
