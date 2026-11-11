"""Read-only portable development startup check; not business approval."""
from pathlib import Path
import base64, hashlib, json, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
def git(*a):return subprocess.check_output(['git',*a],cwd=ROOT,text=True).strip()
def main():
    registry=json.loads((ROOT/'repro/version-registry.json').read_text('utf8'))
    errors=[];locked={};snapshots=json.loads((ROOT/'repro/guarded-text-snapshots.json').read_text('utf8'))
    for n in ['business-loop/dependency-lock.json','catalogue-pack-loop/reuse-lock.json']:
        locked.update(json.loads((ROOT/n).read_text('utf8'))['files'])
    for n,h in locked.items():
        p=ROOT/n
        if not p.exists():errors.append('Missing locked source: '+n);continue
        b=p.read_bytes();lf=b.replace(b'\r\n',b'\n');choices=[b,lf,lf.replace(b'\n',b'\r\n')]
        if n in snapshots:choices.append(base64.b64decode(snapshots[n]['base64']))
        if not any(hashlib.sha256(v).hexdigest()==h for v in choices):errors.append('Dependency cannot be reproduced: '+n)
    if git('branch','--show-current')!=registry['development_branch']:errors.append('Development branch differs from registry')
    for n in ['AGENTS.md','START_HERE.md','CURRENT_STATUS.md','BUSINESS_RULES.md','SOP_INDEX.md','TEST_INDEX.md',registry['entry'],registry['original_view']]:
        if not (ROOT/n).is_file():errors.append('Missing startup/entry file: '+n)
    report={'status':'conflict' if errors else 'passed','candidate':git('rev-parse','HEAD'),
            'branch':git('branch','--show-current'),'dirty':git('status','--porcelain'),
            'guarded_dependencies_reproducible':len(locked),'errors':errors,
            'business_blockers':registry['business_blockers'],'formal_output':False,
            'business_data_available':'Not implied; exact private manifest required before real replay'}
    print(json.dumps(report,ensure_ascii=False,indent=2));return bool(errors)
if __name__=='__main__':raise SystemExit(main())
