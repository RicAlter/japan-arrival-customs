"""Build an isolated rc.7 WorkBuddy candidate; never alter an installed Skill."""
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
VERSION='0.7.0-rc.7'

def sha(data): return hashlib.sha256(data).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path);args=parser.parse_args()
    out=args.destination.resolve();out.mkdir(parents=True,exist_ok=True)
    files=sorted(path for path in SKILL.rglob('*') if path.is_file() and '__pycache__' not in path.parts and 'security' not in path.parts)
    permitted={'.py','.mjs','.md','.txt','.json'}
    if any(path.suffix not in permitted for path in files): raise RuntimeError('候选安装目录含未允许文件')
    if (SKILL/'scripts/arrival_core/__init__.py').read_text(encoding='utf-8').find(VERSION)<0: raise RuntimeError('候选版本号不一致')
    asset=json.loads((SKILL/'templates/accepted_layout.json').read_text(encoding='utf-8'))
    if set(asset)!={'schema','customs','internal','weights'} or any('rows' in asset[k] for k in ('customs','internal','weights')):
        raise RuntimeError('模板资源合同不符或含业务行')
    manifest={path.relative_to(SKILL).as_posix():sha(path.read_bytes()) for path in files}
    source_hash=sha(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    package=out/f'japan-arrival-customs-{VERSION}-workbuddy-candidate.zip'
    if package.exists(): raise RuntimeError('拒绝覆盖已有候选包')
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            entry=zipfile.ZipInfo(path.relative_to(SKILL).as_posix(),(2026,10,26,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,path.read_bytes())
    with tempfile.TemporaryDirectory() as directory:
        target=Path(directory)/'skill'
        with zipfile.ZipFile(package) as archive: archive.extractall(target)
        for name, expected in manifest.items():
            if sha((target/name).read_bytes())!=expected: raise RuntimeError('解压候选哈希不一致')
        probe=subprocess.run([sys.executable,str(target/'scripts/run.py'),'--help'],capture_output=True,text=True)
        if probe.returncode: raise RuntimeError('解压后入口不可执行:'+probe.stderr)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    receipt={'version':VERSION,'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
             'commit':commit,'install_package':package.name,'zip_sha256':sha(package.read_bytes()),
             'source_manifest_sha256':source_hash,'file_count':len(files),'fresh_extraction_cli':'passed',
             'business_data_in_package':False,'credentials_in_package':False,'formal_output':'closed',
             'workbuddy_live_test':'not_run','files':manifest}
    (out/'release-manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k!='files'},ensure_ascii=False))

if __name__=='__main__': main()
