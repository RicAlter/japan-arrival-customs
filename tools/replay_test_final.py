"""Actual main-entry final flow test on a new saved copy, never formal approval."""
from pathlib import Path
import json,argparse,subprocess,sys
from bind_test_final import bind
from freeze_unified import sha,save
REPO=Path(__file__).resolve().parents[1]
def replay(manifest,output,candidate):
    out=Path(output);bound=bind(manifest,out);config=bound['session'];records=[]
    def check(name,value):
        records.append({'test':name,'status':'passed'if value else'failed'})
        if not value:raise AssertionError(name)
    def action(n,body,expected=0):
        q=out/(str(n)+'-request.json');r=out/(str(n)+'-result.json');save(q,body)
        p=subprocess.run([sys.executable,'-X','utf8','-B',str(REPO/'business-interaction/run.py'),'--config',config,'--request',str(q),'--result-file',str(r)],capture_output=True,text=True,encoding='utf8')
        assert p.returncode==expected,p.stdout[-1800:]+p.stderr[-2000:]
        return json.loads(r.read_text('utf8'))if r.exists()else json.loads(p.stdout)
    blocked=action(1,{'action':'test-final','reference':'TEST missing explicit scope'},1);check('ordinary session cannot silently ignore pending gates',blocked['status']=='blocked')
    result=action(2,{'action':'test-final','purpose':'flow_test','allow_pending':True,'reference':'USER:2026-11-13 本次测试忽略待补资料，继续生成最终结果表，走完本地流程；不作为业务批准或正式外发'})
    check('two complete final test workbooks generated',len(result['business_files'])==2 and result['rows']==1967 and result['verification']['passed'])
    check('no false calculation/professional/formal approval',result['calculation_confirmed']is False and result['professional_approval']is False and result['formal_output']is False)
    check('all100 pending rows retained',len(result['retained_pending_rows'])==100)
    check('same104148 pieces50083400 original amount and216 rounding difference',result['totals']['pieces']==104148 and result['totals']['original_amount']==50083400 and result['rounding_difference_jpy']==216)
    check('374 cartons reconciled without guessed allocation',result['logistics']['passed']and result['logistics']['physical_cartons']==374 and not result['logistics']['per_carton_weight_allocated'])
    repeat=action(3,{'action':'test-final','purpose':'flow_test','allow_pending':True,'reference':'USER:2026-11-13 retry same test'})
    check('repeat is idempotent and reopens same output files',repeat['receipt_replayed']and repeat['output_sha256']==result['output_sha256'])
    current=action(4,{'action':'current'});check('current returns selected test final pair',current['business_files']==result['business_files'])
    final=action(5,{'action':'confirm','confirmation_id':'test-final','explicit_confirmation':True,'reference':'TEST'},1);check('normal business confirmation gate still rejects',final['status']=='blocked')
    m=json.loads(Path(manifest).read_text('utf8'));check('all original inputs and session unchanged',all(sha(p)==h for p,h in m['files'].items()))
    report=dict(candidate=candidate,passed=len(records),failed=0,not_executed=0,records=records,**{k:v for k,v in result.items()if k not in ['head','policy','reference','receipt_replayed']},session=config,prepare_executed=False,old_session_changed=False,scope='stage2-to-final projection and persistence flow test; no B00/A04 or formal business acceptance')
    save(out/'verification.json',report);return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--candidate',required=True);a=p.parse_args();r=replay(a.manifest,a.output,a.candidate);print(json.dumps({k:v for k,v in r.items()if k not in ['records','retained_pending_rows','verification','logistics']},ensure_ascii=False))
