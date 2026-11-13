"""WorkBuddy operations request entry; the UI supplies explicit confirmation values."""
import argparse
import json
from pathlib import Path
from arrival_core.operations_adapter import run

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding='utf-8-sig'))
    allowed = {'files', 'units_confirmation', 'comparison_files', 'no_code_reasons'}
    if not isinstance(request, dict) or set(request) - allowed or not request.get('files'):
        parser.error('运营适配请求字段不正确')
    result = run(args.output, **request)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] != 'needs_input' else 2)
