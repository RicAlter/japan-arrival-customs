"""A-03 authorized historical save simulation; never a real business approval."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from a_confirm.support import ROOT, bootstrap, check_hashes, digest, key, load
bootstrap()
from a_confirm.service import Service
from native22.support import save
from native22.prepare import registered_copy
from openpyxl import load_workbook


def scope(save_changes=(),confirm_fields=(),adopt_candidates=(),evidence=None):
    return {'save_changes':list(save_changes),'confirm_fields':list(confirm_fields),
            'adopt_candidates':list(adopt_candidates),'evidence':evidence or {}}


def run(config,output):
    output=Path(output).resolve()
    if output.exists():raise ValueError('不覆盖历史验收或保存根')
    protected=config['protected_files'];check_hashes(protected);output.mkdir(parents=True)
    service=Service(output/'main-service');registered=service.register(config['context_file']);bid=registered['batch_id']
    before=service.read_current(bid);assert before['pricing_counts']=={'within_100_jpy':1602,'exceeds_100_jpy':28,'price_input_unavailable':175,'rounded_packaging_not_positive_integer':162}
    save(output/'保存前读取.json',before)
    preview=service.preview_return(bid,config['legal_upload'],expected_hash=before['current_hash'])
    assert preview['modified_cells']==12 and preview['needs_further_confirmation_cells']==3,preview
    save(output/'原始修改预览.json',preview)
    plan=service.prepare_confirmation(preview['preview_id'],scope(['Sheet1!E3','Sheet1!R2','Sheet1!Q2'],['Sheet1!E3','Sheet1!R2']))
    competing=service.prepare_confirmation(preview['preview_id'],scope(['Sheet1!S3'],['Sheet1!S3']))
    save(output/'首次明确确认范围.json',plan)
    first=service.commit(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference='TEST:仅确认E3/R2；Q2仅保存待核，非真人批准')
    after_first=Service(output/'main-service').read_current(bid)
    assert after_first['revision']==1 and after_first['confirmed_field_count']==2
    assert after_first['fields']['Sheet1!Q2']['status']=='saved_pending' and not after_first['fields']['Sheet1!Q2']['confirmed']
    assert after_first['fields']['Sheet1!P3']['value']==before['fields']['Sheet1!P3']['value']
    assert after_first['pricing_counts']==before['pricing_counts']
    save(output/'部分确认后读取.json',after_first)
    replay=service.commit(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference='TEST:重复点击确认')
    assert replay['replayed'] and replay['transaction_id']==first['transaction_id'] and service.read_current(bid)['revision']==1
    try:
        service.commit(competing['plan_id'],confirmed_hash=competing['plan_id'],explicit_confirmation=True,reference='TEST:旧范围不能覆盖新版本')
    except ValueError as exc:conflict={'rejected':True,'reason':str(exc)}
    else:raise AssertionError('旧确认范围未被拒绝')
    refreshed=service.preview_return(bid,config['legal_upload'],expected_hash=after_first['current_hash'])
    assert refreshed['modified_cells']==9 and set(refreshed['already_saved'])=={'Sheet1!E3','Sheet1!R2','Sheet1!Q2'}
    follow=service.prepare_confirmation(refreshed['preview_id'],scope(['Sheet1!S3'],['Sheet1!S3']))
    second=service.commit(follow['plan_id'],confirmed_hash=follow['plan_id'],explicit_confirmation=True,reference='TEST:仅追加确认S3，保留其他待核')
    second_read=service.read_current(bid);assert second_read['revision']==2 and second_read['confirmed_field_count']==3
    # A separately supplied synthetic purchase fact, never inferred from Japanese price/final amounts.
    proposal={'sheet':'Sheet1','cell':'G573','value':{'type':'number','value':'9990.00'},
              'message_ref':'TEST:独立合成采购凭据给定9990 JPY，仅测试，不是真实本批采购价'}
    price_preview=service.preview_return(bid,config['issued_file'],expected_hash=second_read['current_hash'],field_proposals=[proposal])
    proof={'source_ref':proposal['message_ref'],'source_kind':'purchase_document','price_basis_hash':second_read['price_basis_hash'],'currency':'JPY'}
    price_plan=service.prepare_confirmation(price_preview['preview_id'],scope(['Sheet1!G573'],['Sheet1!G573'],evidence={'Sheet1!G573':proof}))
    third=service.commit(price_plan['plan_id'],confirmed_hash=price_plan['plan_id'],explicit_confirmation=True,reference='TEST:仅采用上述合成采购价范围，不批量批准365行')
    final=Service(output/'main-service').read_current(bid)
    assert final['revision']==3 and final['confirmed_field_count']==4
    assert final['pricing_counts']=={'within_100_jpy':1603,'exceeds_100_jpy':28,'price_input_unavailable':174,'rounded_packaging_not_positive_integer':162},final['pricing_counts']
    assert final['saved_pending_fields']==['Sheet1!Q2'] and final['fields']['Sheet1!G573']['value']['value']=='9990'
    assert not final['can_enter_b'] and not final['downstream']['b_confirmation_valid']
    assert not final['downstream']['c_delivery_valid'] and final['downstream']['input_fingerprint'] is None
    save(output/'保存后重新读取.json',final)
    history=service.history(bid);assert [h['revision'] for h in history]==[0,1,2,3]
    save(output/'已提交版本链.json',history)
    save(output/'事务回执与版本冲突.json',{'first':first,'repeat':replay,'conflict':conflict,'second':second,'third':third})
    # Independently launch the real CLI reader, avoiding an in-memory-only validation.
    read_request=output/'read-request.json';save(read_request,{'batch_id':bid})
    cli_file=output/'独立进程重新读取.json';env=dict(os.environ,PYTHONPATH=str(ROOT))
    with cli_file.open('xb') as stream:
        child=subprocess.run([sys.executable,'-X','utf8','-B','-m','a_confirm','read','--root',str(service.root),'--request',str(read_request)],env=env,cwd=ROOT,stdout=stream,stderr=subprocess.PIPE,timeout=90)
    assert child.returncode==0,child.stderr.decode('utf-8',errors='replace')
    assert load(cli_file)==final
    print('22-column partial confirmations, one scoped test price, idempotency, conflict and CLI reread passed.',flush=True)
    # Legacy 16-column output is registered independently; original formatted files remain untouched.
    ctx=load(config['context_file']);legacy_reg=registered_copy(config['legacy_output'])
    ctx.update(current_output=config['legacy_output'],business_batch_id=legacy_reg['business_batch_id'],export_id=legacy_reg['export_id'],a_version=legacy_reg['a_version'])
    legacy_context=output/'legacy-context.json';save(legacy_context,ctx)
    legacy=Service(output/'legacy16-service');legacy_id=legacy.register(str(legacy_context))['batch_id'];old=legacy.read_current(legacy_id)
    workbook=load_workbook(legacy_reg['file']);workbook['Sheet1']['E2']=str(workbook['Sheet1']['E2'].value)+'（A03保存测试）'
    legacy_upload=output/'16列实际修改回传_程序测试.xlsx';workbook.save(legacy_upload);workbook.close()
    lp=legacy.preview_return(legacy_id,str(legacy_upload),expected_hash=old['current_hash'])
    lplan=legacy.prepare_confirmation(lp['preview_id'],scope(['Sheet1!E2'],['Sheet1!E2']))
    lr=legacy.commit(lplan['plan_id'],confirmed_hash=lplan['plan_id'],explicit_confirmation=True,reference='TEST:16列单格保存')
    legacy_final=Service(output/'legacy16-service').read_current(legacy_id)
    assert legacy_final['revision']==1 and legacy_final['fields']['Sheet1!E2']['confirmed']
    save(output/'16列保存后读取.json',legacy_final)
    print('16-column actual return and save passed.',flush=True)
    failures=[]
    for mode in ('before','after'):
        fault=Service(output/('fault-'+mode+'-service'));fid=fault.register(config['context_file'])['batch_id'];initial=fault.read_current(fid)
        p=fault.preview_return(fid,config['legal_upload'],expected_hash=initial['current_hash'])
        chosen=fault.prepare_confirmation(p['preview_id'],scope(['Sheet1!E3'],['Sheet1!E3']))
        child=subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'tests/process_fault.py'),str(fault.root),chosen['plan_id'],mode],env=env,capture_output=True,timeout=120)
        assert child.returncode==(71 if mode=='before' else 72),child.stderr.decode('utf-8',errors='replace')
        restarted=Service(fault.root);visible=restarted.read_current(fid)
        assert visible['revision']==(0 if mode=='before' else 1)
        receipt=restarted.commit(chosen['plan_id'],confirmed_hash=chosen['plan_id'],explicit_confirmation=True,reference='TEST:同一已确认范围恢复')
        assert receipt['recovered_stale_lock']
        recovered=Service(fault.root).read_current(fid);assert recovered['revision']==1
        repeat=restarted.commit(chosen['plan_id'],confirmed_hash=chosen['plan_id'],explicit_confirmation=True,reference='TEST:恢复后重领回执')
        assert repeat['replayed'] and len(restarted.history(fid))==2 and recovered['pricing_counts']==before['pricing_counts']
        failures.append({'mode':mode,'actual_process_exit_code':child.returncode,'visible_revision_after_crash':visible['revision'],
                         'recovered_revision':recovered['revision'],'same_transaction_replayed':repeat['replayed'],
                         'stale_candidate_lock_recovered':receipt['recovered_stale_lock'],'history':restarted.history(fid)})
        print('Real process termination '+mode+' HEAD and safe recovery passed.',flush=True)
    assert Service(service.root).read_current(bid)==final
    save(output/'真实进程中断与恢复.json',failures)
    changes=[]
    for target in ('Sheet1!E3','Sheet1!R2','Sheet1!Q2','Sheet1!S3','Sheet1!G573'):
        changes.append({'target':target,'before':before['fields'][target]['value'],'after':final['fields'][target]['value'],
                        'status':final['fields'][target]['status'],'confirmed':final['fields'][target]['confirmed'],
                        'working_formula_before':before['fields'][target]['working_formula'],
                        'working_formula_after':final['fields'][target]['working_formula']})
    save(output/'保存前后对比.json',{'test_simulation_only':True,'changes':changes})
    text=['# A-03保存前后对比','','程序模拟确认，仅保存到隔离候选；不是实际业务批准。','','| 字段 | 保存前 | 保存后 | 最终状态 |','|---|---|---|---|']
    def fmt(v):return ('（空）' if v['value'] is None else str(v['value'])).replace('|','\\|').replace('\n',' ')
    for r in changes:text.append('| '+' | '.join([r['target'],fmt(r['before']),fmt(r['after']),r['status']])+' |')
    text+=['','主链版本0→1→2→3；重复确认未增加版本；旧范围确认被拒绝。',
           '前三格保存后价格待核仍365行。只在明确采用一条独立合成采购价后变为364行；不是自动调平或本批真实采购价批准。',
           '原件、工作副本和受控公式保持不变，当前有效业务值从A-03后台版本读取。']
    (output/'保存前后对比.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    check_hashes(protected);bootstrap()
    result={'schema':'a03-historical-acceptance/1','all_passed':True,'test_simulation_only':True,'real_human_approval':False,
            'main_batch_id':bid,'main_revisions':[h['revision'] for h in history],'confirmed_fields':final['confirmed_field_count'],
            'saved_pending_fields':final['saved_pending_fields'],'price_pending_before':365,'price_pending_after_first_save':365,
            'price_pending_after_one_scoped_test_price':364,'pricing_counts_after':final['pricing_counts'],
            'duplicate_confirmation_adds_versions':False,'stale_confirmation_rejected':True,'independent_cli_reread_identical':True,
            'legacy16_saved':True,'fault_process_cases':failures,'source_formulas_and_controlled_rules_unchanged':True,
            'protected_files_checked':len(protected),'all_protected_hashes_unchanged':True,
            'a_stage_saved':True,'can_enter_b':False,'formal_output':False,'b_calculated':False,'professional_approvals':0,
            'actual_human_actions':None,'time_saved':None}
    save(output/'acceptance.json',result);save(output/'protection-check.json',{'files':protected,'all_unchanged':True})
    return {k:result[k] for k in ('all_passed','main_revisions','confirmed_fields','saved_pending_fields','price_pending_before',
                                 'price_pending_after_one_scoped_test_price','legacy16_saved','protected_files_checked')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();print(json.dumps(run(load(args.config),args.output),ensure_ascii=False,indent=2))
