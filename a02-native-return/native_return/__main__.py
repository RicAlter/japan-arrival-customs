import argparse
import json
from .support import load
from .service import preview

parser = argparse.ArgumentParser(description='A-02原表回传预览；不确认、不保存业务版本、不计算')
parser.add_argument('--request', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
result = preview(args.output, load(args.request))
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result['status'] == 'preview_ready' else 2)
