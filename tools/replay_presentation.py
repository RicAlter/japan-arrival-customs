"""Replay clean presentation through run.py using a new copy of saved test state."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
from freeze_unified import sha,save
REPO=Path(__file__).resolve().parents[1]

def replay(session,output,candidate):
    original=Path(session).resolve();config=json.loads(original.read_text('utf8'));out=Path(output).resolve()
    if out.exists():raise ValueError('Use a new replay directory')
    if not config.get('flow_test_final'):raise ValueError('Explicit historical test session required')
    background=Path(config['background']);pointer=background/'test-final/current.json';final=json.loads(pointer.read_text('utf8'))
    protected={str(original):sha(original),str(pointer):sha(pointer),**final['output_sha256']}
    manifest=json.loads(Path(config['flow_test_final']['manifest']).read_text('utf8'));protected.update(manifest['files'])
    if not all(sha(p)==h for p,h in protected.items()):raise ValueError('Saved inputs changed')
    out.mkdir(parents=True);saved=out/'saved-batch'
    shutil.copytree(background.parent,saved,ignore=shutil.ignore_patterns('__pycache__'))
    config.update(background=str(saved/background.name),root=str(saved/background.name/'live-state'),business_directory=str(out/'结果表'))
    save(out/'session.json',config);records=[]
    def check(name,value):
        records.append(dict(test=name,status='passed'if value else'failed'))
        if not value:raise AssertionError(name)
    def action(n,request,expected=0):
        q=out/(str(n)+'-request.json');r=out/(str(n)+'-result.json');save(q,request)
        p=subprocess.run([sys.executable,'-X','utf8','-B',str(REPO/'business-interaction/run.py'),'--config',str(out/'session.json'),'--request',str(q),'--result-file',str(r)],capture_output=True,text=True,encoding='utf8')
        if p.returncode!=expected:raise AssertionError(p.stdout[-1800:]+p.stderr[-2000:])
        return json.loads(r.read_text('utf8'))if r.exists()else json.loads(p.stdout)
    request=dict(action='presentation-preview',historical_preview=True,reference='USER:2026-11-13 历史结束批次查看外发版式，不涉及实际业务；固化版本及整改基线')
    result=action(1,request)
    check('main entry creates two verified presentation files',len(result['business_files'])==2 and result['verification']['passed'])
    check('business approval is unchanged',result['presentation_only']and not result['business_approval_changed']and not result['formal_output']and not result['calculation_confirmed'])
    check('every row, amount and weight cache preserved',result['rows']==final['rows']and result['verification']['all_rows_preserved']and result['verification']['weight_formulas_and_caches_preserved'])
    again=action(2,request);check('retry is idempotent',again['receipt_replayed']and again['output_sha256']==result['output_sha256'])
    current=action(3,dict(action='current'));check('current reopens same presentation pair',current['output_sha256']==result['output_sha256'])
    blocked=action(4,dict(action='confirm',confirmation_id='historical-preview',explicit_confirmation=True,reference='TEST'),1)
    check('ordinary business confirmation remains gated',blocked['status']=='blocked')
    check('original state and inputs unchanged',all(sha(p)==h for p,h in protected.items()))
    report=dict(candidate=candidate,passed=len(records),failed=0,not_executed=0,records=records,session=str(out/'session.json'),source_session=str(original),protected_files=len(protected),business_files=result['business_files'],output_sha256=result['output_sha256'],prepare_executed=False,business_approval=False,scope='presentation replay over previously sealed test-final pair; normal B00/A04 chain remains pending')
    save(out/'verification.json',report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--session',required=True);p.add_argument('--output',required=True);p.add_argument('--candidate',required=True);a=p.parse_args();r=replay(a.session,a.output,a.candidate);print(json.dumps(r,ensure_ascii=False))
