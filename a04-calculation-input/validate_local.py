"""Private local acceptance; outputs JSON/logs only, never approves actual rows."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter

from a_input.bridge import Bridge, REPO, key

WORKSPACE = REPO.parent
OUT = WORKSPACE/'outputs/a04_calculation_input_20261104_v1'
REPORT = WORKSPACE/'reports/a04-calculation-input-20261104'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()


def save(p,v):
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    if OUT.exists():raise RuntimeError('Acceptance output exists; refuse overwrite')
    OUT.mkdir();REPORT.mkdir(exist_ok=True)
    old=json.loads((WORKSPACE/'outputs/a03_confirmation_20261104_v1/protection-check.json').read_text(encoding='utf-8'))['files']
    # Respect the explicit archive migration: report missing historic paths rather
    # than restoring them or claiming they were verified at their old locations.
    existing={p:h for p,h in old.items() if Path(p).is_file()}
    missing=[p for p in old if not Path(p).is_file()]
    for folder in ['a01_native_copy_20261104_final02','a02_native_return_20261104_final02',
                   'a02_native22_20261104_final03','a03_confirmation_20261104_v1']:
        for p in (WORKSPACE/'outputs'/folder).rglob('*'):
            if p.is_file():existing[str(p)]=sha(p)
    for p,h in existing.items():
        if sha(Path(p))!=h:raise RuntimeError('Prior protected hash changed: '+p)
    before=dict(existing)
    results={}
    for label, service in [('native22','main-service'),('native16','legacy16-service')]:
        root=WORKSPACE/'outputs/a03_confirmation_20261104_v1'/service
        batches=list((root/'batches').iterdir());assert len(batches)==1
        bid=batches[0].name;bridge=Bridge(root)
        a=bridge.prepare(bid);b=bridge.prepare(bid)
        assert a==b and bridge.current_input(a)==a['rc5_input']
        assert a['ready_row_count']==0 and a['rc5_input'] is None
        save(OUT/(label+'-preflight.json'),a)
        results[label]={'rows':a['row_count'],'ready_rows':a['ready_row_count'],
                        'blocked_rows':a['blocked_row_count'], 'a_version':a['a_version'],
                        'fingerprint':a['input_fingerprint'],'deterministic':True,
                        'confirmed_field_rows':sum(bool(r['confirmed_fields']) for r in a['row_checks']),
                        'price_pending_rows':sum(r['price_reference_pending'] for r in a['row_checks']),
                        'price_counts':a['price_reference_counts'],
                        'blockers':dict(Counter(x for r in a['row_checks'] for x in r['blockers']))}
    suites=[]
    for directory in ['a04-calculation-input','a03-confirmation','a02-native-22','a02-native-return','a01-native-copy','rc8-operations-colored-v1']:
        env=dict(os.environ,PYTHONPATH=str(REPO/directory))
        if directory=='rc8-operations-colored-v1':
            env['PYTHONPATH']=str(REPO/directory/'workbuddy/japan-arrival-customs/scripts')
        r=subprocess.run([sys.executable,'-X','utf8','-B','-m','unittest','discover','-s',str(REPO/directory/'tests'),'-v'],
                         cwd=WORKSPACE,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        output=r.stdout.decode('utf-8',errors='replace')
        (REPORT/(directory+'-tests.log')).write_text(output,encoding='utf-8')
        suites.append({'suite':directory,'exit_code':r.returncode,'summary':output[-500:]})
        if r.returncode:raise RuntimeError('Regression failed: '+directory)
    for p,h in before.items():
        if sha(Path(p))!=h:raise RuntimeError('Protected hash changed during run: '+p)
    save(OUT/'protection-check.json',{'files':before,'unchanged':True,'missing_archived_historic_paths':missing})
    save(REPORT/'test-suites.json',suites)
    result={'all_passed':True,'samples':results,'protected_file_count':len(before),
            'missing_archived_path_count':len(missing),'protected_unchanged':True,
            'rc5_full_actual_batch_calculation':False,'rc5_schema_and_exact_price_synthetic_test':True,
            'no_excel_created':True,'formal_output':False}
    save(OUT/'acceptance.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
