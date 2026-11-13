import argparse
import json
from pathlib import Path

from .compat import Rejected
from .batch import run


def main(argv=None):
    parser=argparse.ArgumentParser(description='P2-A anime-store候选查询；缺站方授权时不联网，不写库')
    sub=parser.add_subparsers(dest='command',required=True)
    q=sub.add_parser('query');q.add_argument('--request',required=True);q.add_argument('--output',required=True);q.add_argument('--runtime',required=True);q.add_argument('--access-scope')
    q=sub.add_parser('export');q.add_argument('--candidates',required=True);q.add_argument('--runtime',required=True);q.add_argument('--output',required=True);q.add_argument('--authorization-reference',required=True);q.add_argument('--source-id',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='query':
            result=run(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),args.output,args.runtime,access_scope=args.access_scope)
            summary=result['metrics']
        else:
            from .bundle import export
            summary=export(args.candidates,args.runtime,args.output,authorization_reference=args.authorization_reference,source_id=args.source_id)
        print(json.dumps({'status':'completed','result':summary,'database_written':False,'formal_output':False},ensure_ascii=False))
        return 0
    except (Rejected,OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'rejected','reason':str(exc),'database_written':False,'formal_output':False},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
