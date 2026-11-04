import argparse
import json
from .service import execute
from .support import load


def main():
    parser = argparse.ArgumentParser(description='A-01同版式工作副本与登记；不确认、不计算')
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = execute(args.output, load(args.request))
    except Exception as exc:
        result = {'status': 'rejected', 'reason': str(exc), 'business_files': [],
                  'formal_output': False, 'confirmed': False, 'can_enter_b': False}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'prepared_reference_copy' else 2


if __name__ == '__main__':
    raise SystemExit(main())
