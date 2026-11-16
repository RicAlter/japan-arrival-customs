"""Short model-facing wrapper; runtime/profile binding replaces model-written config."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--action', choices=['prepare','current','resume'], required=True)
    parser.add_argument('--responses',help='外部网页工具原文回传JSON；仅resume，模型不得编造材质')
    parser.add_argument('--finalize-pictures',action='store_true',help='仅resume：下载并嵌入已登记图片链接')
    parser.add_argument('--submitted-file')
    parser.add_argument('--expected-revision',type=int)
    parser.add_argument('--expected-reference-sha256')
    parser.add_argument('--clear-cells',nargs='*')
    args=parser.parse_args()
    try:
        runtime=json.loads(Path(args.runtime).read_text(encoding='utf-8-sig'))
        profile=Path(runtime['profile'])
        if hashlib.sha256(profile.read_bytes()).hexdigest()!=runtime['profile_sha256']:
            raise ValueError('SOURCE_CHANGED: 运行配置变化；模型不得自行重绑')
        config=json.loads(profile.read_text(encoding='utf-8-sig'))
        request={'workflow':'rebuild_mvp_v1','action':args.action}
        if args.action=='prepare':request.update(config)
        else:request['task_root']=config['output']
        if args.responses:
            if args.action!='resume':raise ValueError('INPUT_INVALID: responses仅用于resume')
            request['responses']=json.loads(Path(args.responses).read_text(encoding='utf-8-sig'))
        if args.finalize_pictures:
            if args.action!='resume':raise ValueError('INPUT_INVALID: finalize-pictures仅用于resume')
            request['finalize_pictures']=True
        if args.submitted_file:
            if args.action!='resume':raise ValueError('INPUT_INVALID: submitted-file仅用于resume')
            request.update(submitted_file=args.submitted_file,expected_revision=args.expected_revision,expected_reference_sha256=args.expected_reference_sha256)
            if args.clear_cells is not None:request['clear_cells']=args.clear_cells
        folder=Path(runtime['request_directory']);folder.mkdir(parents=True,exist_ok=True)
        raw=json.dumps(request,ensure_ascii=False,sort_keys=True,indent=2)
        name=hashlib.sha256(raw.encode()).hexdigest()+'.json'
        target=folder/name
        if not target.exists():target.write_text(raw,encoding='utf-8')
        result=subprocess.run([runtime['python'],'-X','utf8','-B',runtime['entry'],'--request',str(target)],capture_output=True,text=True,encoding='utf-8')
        # The program, not the model, owns input defaults and action decisions.
        if result.stdout:
            print(result.stdout.strip())
            return result.returncode
        raise RuntimeError(result.stderr.strip() or '工具没有返回结构化结果')
    except Exception as exc:
        code=str(exc).split(':',1)[0]
        if code not in {'SOURCE_CHANGED','CONFIG_INVALID','INPUT_INVALID'}:code='RUNTIME_FAILURE'
        print(json.dumps({'schema':'arrival-matching-mvp/1','status':'failed','business_files':[],
                          'error':{'code':code,'message':str(exc),'retryable':code=='RUNTIME_FAILURE'}},ensure_ascii=False))
        return 1


if __name__=='__main__':raise SystemExit(main())
