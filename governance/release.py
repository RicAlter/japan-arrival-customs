"""Create a local reproducible integration candidate; never run a live session."""
import argparse,hashlib,json,pathlib,shutil,subprocess,sys,zipfile,os,re

def sha(p):
    with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--output',required=True);ap.add_argument('--test-only',action='store_true');a=ap.parse_args()
    w=pathlib.Path(a.workspace).resolve();repo=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output).resolve()
    assert out.is_relative_to(w) and out!=w
    out.mkdir(parents=True,exist_ok=True);e=out/'governance-release';e.mkdir(exist_ok=True)
    baseline=w/'outputs/日本到货_关联材质原文修复候选_20261110/src'
    src=out/'src';target=src/'github-progress-rc8-20261028'
    if not src.exists():shutil.copytree(baseline,src,ignore=shutil.ignore_patterns('__pycache__'))
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=repo).decode().split('\0')
    for name in filter(None,tracked):
        source=repo/name;dest=target/name
        if not source.is_file():continue
        # Preserve already-verified runtime CRLF/locked snapshots when logically identical.
        if dest.is_file() and dest.read_bytes().replace(b'\r\n',b'\n')==source.read_bytes().replace(b'\r\n',b'\n'):continue
        if name=='p3b-validation/README.md':continue
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    guards={}
    for name in ['business-loop/dependency-lock.json','catalogue-pack-loop/reuse-lock.json']:
        guards.update(json.loads((target/name).read_text(encoding='utf8'))['files'])
    failures=[name for name,s in guards.items() if not (target/name).is_file() or sha(target/name)!=s]
    save(e/'dependency-verification.json',{'checked':len(guards),'failed':failures,'files':guards})
    if failures:raise SystemExit('guarded dependency bytes mismatch: '+str(failures[:5]))
    fixture='reports/first-phase-upgrade-20261106/prepare-request.json'
    (src/fixture).parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(w/fixture,src/fixture)
    results=[]
    suites=[('business-interaction',p) for p in ['test_matching_repair.py','test_attention_display.py','test_pcs_enrichment.py','test_dg_enrichment.py','test_material*.py','test_large_return.py','test_quantity_review.py','test_delivery_review.py','test_preparation.py','test_pack_reference.py','test_photo_layout.py','test_freeze_candidate.py']]
    suites += [('business-loop','test*.py'),('catalogue-pack-loop','test*.py')]
    for folder,pattern in suites:
        label=folder+'-'+pattern.replace('*','all');r=subprocess.run([sys.executable,'-X','utf8','-B','-m','unittest','discover','-s','tests','-p',pattern],cwd=target/folder,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=600)
        log=r.stdout+r.stderr
        (e/(label+'.log')).write_text(log,encoding='utf8')
        ran=re.search(r'Ran (\d+) tests?',log);skipped=re.search(r'skipped=(\d+)',log)
        results.append({'suite':label,'returncode':r.returncode,'discovered':int(ran[1]) if ran else None,'skipped':int(skipped[1]) if skipped else 0})
    save(e/'tests.json',results)
    if any(r['returncode'] for r in results):raise SystemExit('integration test failures: inspect tests.json/logs')
    if a.test_only:return
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    skill=out/'skill'
    if not skill.exists():shutil.copytree(target/'business-interaction/workbuddy/japan-arrival-customs-trial',skill)
    files={p.relative_to(src).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in src.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    save(out/'source-manifest.json',{'commit':commit,'files':files})
    runtime={'python':sys.executable,'node':str(w/'node_modules/.bin/node'),'entry':str(target/'business-interaction/run.py'),'source_root':str(src),'source_manifest':str(out/'source-manifest.json'),'source_manifest_sha256':sha(out/'source-manifest.json'),'session':None,'output_base':str(out/'isolated-runs'),'installed':False,'formal_output':False}
    runtime['node']=r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
    save(skill/'runtime.json',runtime)
    for folder,name in [(src,'完整源码.zip'),(skill,'Skill候选包.zip')]:
        with zipfile.ZipFile(out/name,'w',zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(folder))
    bundle=out/'历史提交.bundle'
    if not bundle.exists():subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=repo,check=True,capture_output=True)
    subprocess.run(['git','bundle','verify',str(bundle)],cwd=repo,check=True,capture_output=True)
    save(out/'release.json',{'commit':commit,'branch':'codex/unified-development-20261110','source':str(repo),'runtime':str(skill/'runtime.json'),'tests':results,'full_integration_accepted':not any(r['skipped'] for r in results),'business_material_success':0,'installed':False})
    sums={p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='SHA256.json'};save(out/'SHA256.json',sums)
    print(json.dumps({'commit':commit,'output':str(out),'tests':len(results),'source_files':len(files)},ensure_ascii=False))
if __name__=='__main__':main()
