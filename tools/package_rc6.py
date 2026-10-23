"""Build a source-only installable candidate and verify a fresh extraction."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SKILL=ROOT/'workbuddy/japan-arrival-customs'


def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path)
    args=p.parse_args();out=args.destination.resolve();out.mkdir(parents=True,exist_ok=True)
    files=sorted(path for path in SKILL.rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    permitted={'.py','.mjs','.md','.txt','.json'}
    if any(path.suffix not in permitted or 'security' in path.parts for path in files):
        raise RuntimeError('安装目录含未允许文件')
    asset=json.loads((SKILL/'templates/accepted_layout.json').read_text(encoding='utf-8'))
    if set(asset)!={'schema','customs','internal','weights'}:raise RuntimeError('模板样式合同不符')
    for key in ('customs','internal','weights'):
        if 'rows' in asset[key]:raise RuntimeError('模板不得包含业务行')
    manifest={path.relative_to(SKILL).as_posix():sha(path.read_bytes()) for path in files}
    source_hash=sha(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    package=out/'japan-arrival-customs-0.7.0-rc.6-workbuddy-test.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name=path.relative_to(SKILL).as_posix()
            entry=zipfile.ZipInfo(name,(2026,10,23,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,path.read_bytes())
    with tempfile.TemporaryDirectory() as directory:
        target=Path(directory)/'skill'
        with zipfile.ZipFile(package) as archive:archive.extractall(target)
        for name,h in manifest.items():
            if sha((target/name).read_bytes())!=h:raise RuntimeError('安装包哈希不一致')
        probe=subprocess.run([sys.executable,str(target/'scripts/run.py'),'--help'],capture_output=True,text=True)
        if probe.returncode:raise RuntimeError('解压后入口不可执行:'+probe.stderr)
        probe=subprocess.run([sys.executable,'-c',
            'import sys;sys.path.insert(0,sys.argv[1]);from arrival_core.report_templates import layout;assert layout()["customs"]["columns"]==33',str(target/'scripts')],capture_output=True,text=True)
        if probe.returncode:raise RuntimeError('解压后模板不可读取:'+probe.stderr)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    receipt={'version':'0.7.0-rc.6','branch':'codex/report-template-integration-rc6','commit':commit,
             'install_package':package.name,'zip_sha256':sha(package.read_bytes()),'source_manifest_sha256':source_hash,
             'file_count':len(files),'fresh_extraction_cli':'passed','template_resource':'passed',
             'business_data_in_package':False,'credentials_in_package':False,'workbuddy_live_test':'not_run',
             'files':manifest}
    (out/'release-manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k!='files'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
