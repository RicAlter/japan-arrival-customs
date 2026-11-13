"""Isolated historical source reuse and partial-new-batch acceptance; JSON only."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import json
import os
import sys
import subprocess
import re

from basis.service import Service,REPO,digest,key,load
from a_input.bridge import Bridge

WORKSPACE=REPO.parent
OUT=WORKSPACE/'outputs/b00_business_basis_20261104_v1'
REPORT=WORKSPACE/'reports/b00-business-basis-20261104'


def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    resume='--resume-checks' in sys.argv
    if OUT.exists() and not resume:raise RuntimeError('已有验收目录，拒绝覆盖')
    OUT.mkdir(exist_ok=resume);REPORT.mkdir(exist_ok=True)
    previous=load(WORKSPACE/'outputs/a04_calculation_input_20261104_v1/protection-check.json')['files']
    protected={p:digest(Path(p)) for p in previous}
    protected.update({str(p):digest(p) for p in (REPO/'a03-confirmation/a_confirm').glob('*.py')})
    for folder in ['a01_native_copy_20261104_final02','a02_native_return_20261104_final02','a02_native22_20261104_final03','a03_confirmation_20261104_v1','a04_calculation_input_20261104_v1']:
        for p in (WORKSPACE/'outputs'/folder).rglob('*'):
            if p.is_file():protected[str(p)]=digest(p)
    basis_file=Path(r'C:\Users\Administrator\Downloads\KMT20261003 共374箱(1).xlsx')
    protected[str(basis_file)]=digest(basis_file)
    # Reuse only the historical confirmation receipt, not final numeric answers.
    historical_file=next((WORKSPACE/'outputs/p3a_kmt20261003_20261102_v2/technical/engine').glob('*/batch.json'))
    history=load(historical_file);units=history['operations_adapter']['units']
    assert units['confirm'] is True and units['source_bundle_hash']==history['operations_adapter']['source_bundle_hash']
    assert any(s['path']==str(basis_file) and s['sha256']==digest(basis_file) for s in history['sources'])
    save(OUT/'historical-confirmation-reuse.json',{'receipt_path':str(historical_file),'sha256':digest(historical_file),
         'units_receipt':units,'business_source':str(basis_file),'business_source_sha256':digest(basis_file),
         'final_numeric_answers_used':False,'mode':'isolated_history_replay_not_new_business_approval'})
    if resume:
        service=Service(OUT/'history-service')
    else:
        service=Service.fork(WORKSPACE/'outputs/a03_confirmation_20261104_v1/main-service',OUT/'history-service')
    bid=next((service.root/'batches').iterdir()).name
    before=load(OUT/'history-before.json') if resume else service.preflight(bid)
    if not resume:save(OUT/'history-before.json',before)
    ids=[r['id'] for r in service.store.load(bid)['rows']]
    group={'row_ids':ids,'business_unit':units['business_unit'],'declaration_unit':units['declaration_unit'],
           'reference':'HISTORY_REPLAY：同批已确认第3步I/J/K与H盒数，原表L单个数量；普通相等范围，不批准173行特殊换算；'+units['reference'],
           'exceptions':{}}
    plan=load(OUT/'history-preview.json') if resume else service.preview_basis(bid,business_file=basis_file,groups=[group])
    if not resume:save(OUT/'history-preview.json',plan)
    print('History eligible',len(plan['items']),'excluded',Counter(plan['excluded'].values()),flush=True)
    receipt=service.commit_basis(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,
                                 reference='HISTORY_REPLAY：复用已保存同批业务确认，仅隔离回放；不代表新真人签核')
    save(OUT/'history-save-receipt.json',receipt)
    after=service.preflight(bid);save(OUT/'history-after.json',after)
    assert after==service.preflight(bid)
    assert after['ready_row_count']==len(plan['items']) and after['ready_row_count']>0
    assert service.commit_basis(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference='HISTORY_REPLAY：同一范围重试')['replayed']
    try:Bridge(service.root).current_input(before)
    except ValueError:pass
    else:raise AssertionError('旧A版本未失效')
    # New/partial bases stay in the original state; no history reused across batch.
    partial={}
    for label,folder in [('native22','main-service'),('native16','legacy16-service')]:
        bridge=Bridge(WORKSPACE/'outputs/a03_confirmation_20261104_v1'/folder)
        bid0=next((bridge.service.root/'batches').iterdir()).name
        p=bridge.prepare(bid0);save(OUT/(label+'-partial-preflight.json'),p)
        assert p['ready_row_count']==0
        partial[label]={'rows':p['row_count'],'ready':p['ready_row_count'],'price_pending':sum(x['price_reference_pending'] for x in p['row_checks'])}
    suites=[]
    for directory in ['b00-business-basis','a04-calculation-input','a03-confirmation','a02-native-22','a02-native-return','a01-native-copy','rc8-operations-colored-v1']:
        env=dict(os.environ,PYTHONPATH=str(REPO/directory))
        if directory=='rc8-operations-colored-v1':
            env['PYTHONPATH']=str(REPO/directory/'workbuddy/japan-arrival-customs/scripts')
            env['KMT_REAL_RAW_WORKBOOK']=str(next((WORKSPACE/'inputs/sample_kmt20261002').glob('1.*.xlsx')))
        r=subprocess.run([sys.executable,'-X','utf8','-B','-m','unittest','discover','-s',str(REPO/directory/'tests'),'-v'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        log=r.stdout.decode('utf-8',errors='replace');(REPORT/(directory+'-tests.log')).write_text(log,encoding='utf-8')
        suites.append({'suite':directory,'exit_code':r.returncode,'tests':int(re.search(r'Ran (\d+) tests',log)[1]),'skips':re.findall(r'skipped=\d+',log)})
        if r.returncode or suites[-1]['skips']:raise RuntimeError('测试失败或跳过：'+directory)
    changed=[p for p,h in protected.items() if digest(Path(p))!=h]
    assert not changed,changed
    result={'all_passed':True,'historical_rows':after['row_count'],'historical_ready':after['ready_row_count'],
            'historical_remaining':after['blocked_row_count'],'historical_price_reference_pending':sum(x['price_reference_pending'] for x in after['row_checks']),
            'exception_reasons':dict(Counter(plan['excluded'].values())),'partial_states':partial,
            'tests':sum(s['tests'] for s in suites),'suites':suites,'protected_files':len(protected),'protected_unchanged':True,
            'new_business_approvals':0,'final_numeric_answers_used':False,'formal_output':False,'new_excel_outputs':0}
    save(OUT/'acceptance.json',result);save(OUT/'protection-check.json',{'files':protected,'changed':changed})
    save(REPORT/'test-suites.json',suites);print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
