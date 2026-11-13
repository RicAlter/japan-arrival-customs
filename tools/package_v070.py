"""Package committed, allowlisted source only. Never glob a runtime/data directory."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION='0.7.0-rc.4'
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    target=Path(args.output).resolve();target.mkdir(parents=True,exist_ok=True)
    if git('branch','--show-current').decode().strip()!='codex/0.7.0-isolated-development':raise RuntimeError('Wrong development branch')
    files=[s for s in git('ls-files','-z').decode().split('\0') if s]
    selected=[]
    for name in files:
        if name.startswith('workbuddy/japan-arrival-customs/') or name in (
            'README.md','.gitignore','docs/REPOSITORY_HYGIENE.md','docs/V070_TECHNICAL_DELIVERY.md',
            'tests/test_repository_smoke.py','tests/test_workbuddy_router.py','tests/test_v070_core.py',
            'tests/test_v070_workflow.py','tests/test_business_setup.py','tests/test_raw_intake.py',
            'tools/run_v070_tests.py','tools/package_v070.py'):
            p=ROOT/name
            if p.is_symlink() or any(x in p.parts for x in ('__pycache__','security','inputs','outputs','runs')) or p.suffix in ('.xlsx','.sqlite3','.db','.pyc','.zip'):
                raise RuntimeError('Unexpected source file: '+name)
            selected.append(name)
    if git('diff','HEAD','--name-only','--',*selected).strip():raise RuntimeError('Source must be committed before packaging')
    manifest={name:sha((ROOT/name).read_bytes()) for name in sorted(selected)}
    receipt={'version':VERSION,'branch':git('branch','--show-current').decode().strip(),
             'commit':git('rev-parse','HEAD').decode().strip(),'source_files':manifest,
             'source_manifest_sha256':sha(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()),
             'formal_output_authorized':False,'production_automatic_enabled':False,'WorkBuddy':'not_verified',
             'contains_business_data':False,'contains_credentials':False,'contains_knowledge_library':False}
    def archive(filename,items):
        path=target/filename
        with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as z:
            for name,content in items:
                entry=zipfile.ZipInfo(name,date_time=(2026,10,22,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(entry,content)
        return {'file':str(path),'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size}
    prefix='workbuddy/japan-arrival-customs/'
    # WorkBuddy installer expects SKILL.md at the archive root, not a repo wrapper.
    install=[(name.removeprefix(prefix),(ROOT/name).read_bytes()) for name in selected if name.startswith(prefix)]
    install.append(('RELEASE_MANIFEST.json',json.dumps(receipt,ensure_ascii=False,indent=2).encode()))
    packages=[archive('japan-arrival-customs-'+VERSION+'.zip',install)]
    source=[(name,(ROOT/name).read_bytes()) for name in selected]
    source.append(('RELEASE_MANIFEST.json',json.dumps(receipt,ensure_ascii=False,indent=2).encode()))
    packages.append(archive('japan-arrival-customs-'+VERSION+'-source-and-tests.zip',source))
    receipt['packages']=packages
    with (target/'RELEASE.json').open('x',encoding='utf-8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'version':VERSION,'commit':receipt['commit'],'source_manifest_sha256':receipt['source_manifest_sha256'],'packages':packages},ensure_ascii=False))
if __name__=='__main__':main()
