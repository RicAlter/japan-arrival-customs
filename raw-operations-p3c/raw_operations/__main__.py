import argparse
import json
from .bridge import execute,load,Rejected


def main():
    parser=argparse.ArgumentParser(description='KMT1002原始附件到运营输入候选；仅准备，不自动确认或出双表')
    parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        result=execute(args.output,load(args.request))
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status'] in ('needs_confirmation','needs_input') else 2
    except (Rejected,OSError,ValueError,TypeError) as exc:
        print(json.dumps({'status':'validation_incomplete','reason':str(exc),'business_exception_total':None,
          'business_files':[],'can_enter_pair_calculation':False,'formal_output':False},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
