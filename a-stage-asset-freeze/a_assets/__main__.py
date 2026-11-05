from pathlib import Path
import argparse,json
from .archive import archive_files,verify_archive

def main():
    p=argparse.ArgumentParser(description='本地A阶段显式清单归档，不移动原件，不执行确认或计算')
    s=p.add_subparsers(dest='action',required=True)
    a=s.add_parser('archive');a.add_argument('--request',required=True);a.add_argument('--destination',required=True)
    v=s.add_parser('verify');v.add_argument('--manifest',required=True);v.add_argument('--root')
    args=p.parse_args()
    if args.action=='archive':
        result=archive_files(json.loads(Path(args.request).read_text('utf-8')),args.destination)
        print(json.dumps({'physical_entries':result['physical_entries'],'unique_contents':result['unique_contents'],'archive_root':result['archive_root']},ensure_ascii=False))
    else:
        verify_archive(json.loads(Path(args.manifest).read_text('utf-8')),args.root)
        print('归档内容哈希核验通过')
if __name__=='__main__':main()
