import argparse
import json
from .support import load
from .prepare import prepare
from .returns import preview

p = argparse.ArgumentParser(description='独立A-02补充：22列副本准备或回传预览')
p.add_argument('operation', choices=['prepare', 'preview'])
p.add_argument('--request', required=True); p.add_argument('--output', required=True)
args = p.parse_args()
result = (prepare if args.operation == 'prepare' else preview)(args.output, load(args.request))
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result['status'] in ('prepared_reference_copy', 'preview_ready') else 2)
