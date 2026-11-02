import argparse
import json
import sqlite3
from pathlib import Path

from .core import Rejected
from .database import inspect, clone, import_bundle
from .query import BatchQuery, evidence


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='独立商品参考库P1；不调用报单引擎或D1，无init命令')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('inspect'); p.add_argument('--database', required=True)
    p = sub.add_parser('clone'); p.add_argument('--source', required=True); p.add_argument('--destination', required=True)
    p = sub.add_parser('collect'); p.add_argument('--file', required=True); p.add_argument('--mapping', required=True)
    p.add_argument('--source-id', required=True); p.add_argument('--source-version', required=True); p.add_argument('--authorization-reference', required=True)
    p = sub.add_parser('collect-source'); p.add_argument('--request', required=True)
    p = sub.add_parser('import-bundle'); p.add_argument('--database', required=True); p.add_argument('--bundle', required=True)
    p.add_argument('--authorization', required=True); p.add_argument('--purchase-policy')
    p = sub.add_parser('query'); p.add_argument('--database', required=True); p.add_argument('--request')
    p.add_argument('--file'); p.add_argument('--mapping')
    p = sub.add_parser('evidence'); p.add_argument('--database', required=True); p.add_argument('--observation', required=True); p.add_argument('--file', required=True)
    p = sub.add_parser('site-plan'); p.add_argument('--request', required=True)
    for name in ('inspect','collect','collect-source','import-bundle','query','evidence','site-plan'):
        sub.choices[name].add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.output).resolve() if hasattr(args, 'output') else None
        if output and output.exists():
            raise Rejected('输出已存在，拒绝覆盖')
        if args.command == 'clone':
            result = clone(args.source, args.destination)
        elif args.command == 'collect':
            from .workbooks import collect_bundle
            result = collect_bundle(args.file, load(args.mapping), output, source_id=args.source_id,
                                    source_version=args.source_version, authorization_reference=args.authorization_reference)
        elif args.command == 'collect-source':
            from source_adapters.order import collect
            from source_adapters.common import write_bundle
            request = load(args.request)
            result = write_bundle(request, list(collect(request)), output, 'order')
        elif args.command == 'inspect':
            result = inspect(args.database)
        elif args.command == 'import-bundle':
            result = import_bundle(args.database, args.bundle, load(args.authorization),
                                   purchase_policy=load(args.purchase_policy) if args.purchase_policy else None)
        elif args.command == 'query':
            if bool(args.request) == bool(args.file):
                raise Rejected('query需且只能提供request或file/mapping')
            if args.file:
                from .workbooks import queries
                request = {'items': queries(args.file, load(args.mapping))}
            else:
                request = load(args.request)
            if set(request) - {'items','namespace_aliases','exclude_source_ids','exclude_file_sha256'}:
                raise Rejected('批量请求含未知字段')
            result = BatchQuery(args.database).run(**request)
        elif args.command == 'evidence':
            result = evidence(args.database, args.observation, args.file)
        else:
            from .sites import requests_for
            result = requests_for(load(args.request)['items'])
        if output and args.command not in ('collect','collect-source'):
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({'status': 'ok', 'command': args.command, 'output': str(output) if output else None,
                          'formal_output': False}, ensure_ascii=False))
        return 0
    except (Rejected, OSError, ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc), 'formal_output': False}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
