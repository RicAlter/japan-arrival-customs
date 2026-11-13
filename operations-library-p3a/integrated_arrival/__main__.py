import argparse
import json
from .support import load,Rejected
from .flow import execute


def main():
    parser=argparse.ArgumentParser(description='P3-A隔离运营入口；资料库只读、候选不覆盖、正式输出关闭')
    parser.add_argument('--request',required=True);parser.add_argument('--library-config',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        result=execute(args.output,load(args.request),load(args.library_config))
        # Full technical evidence remains on disk; business sees two file paths.
        public={k:result[k] for k in ('status','business_exception_total','business_exception_rows','manual_input_cells','business_files','formal_output')}
        if 'reason' in result:public['reason']=result['reason']
        if 'input_confirmation' in result and result['input_confirmation']:public['input_confirmation']=result['input_confirmation']
        print(json.dumps(public,ensure_ascii=False));return 0 if result['status'] in ('ok','ok_with_business_exceptions','needs_confirmation') else 2
    except (Rejected,OSError,ValueError,TypeError) as exc:
        print(json.dumps({'status':'validation_incomplete','reason':str(exc),'business_exception_total':None,
                          'business_exception_rows':None,'business_files':[],'formal_output':False},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
