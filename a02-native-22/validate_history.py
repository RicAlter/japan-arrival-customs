"""Explicit historical inputs, independent preservation checks and actual xlsx returns."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from native22.support import bootstrap, check_hashes, digest, load, save
bootstrap()
from native22.prepare import prepare, registered_copy
from native22.returns import preview, read_preview
from native_return.compare import read, passive_links
from openpyxl import load_workbook


def run(config, output):
    output=Path(output).resolve()
    if output.exists():raise ValueError('不覆盖旧验收目录')
    protected=dict(config['protected_files']);check_hashes(protected)
    output.mkdir(parents=True);records=[];registrations=[]
    for case in config['cases']:
        dest=output/case['name'];result=prepare(dest,case['request'])
        assert result['status']=='prepared_reference_copy',result
        assert result['rows']==case['expected_rows'],result
        reg=registered_copy(dest);registrations.append((dest,reg))
        if case.get('expected_copy_file'):
            assert digest(reg['file'])==digest(case['expected_copy_file']),case['name']
        if 'expected_pricing_counts' in case:assert result['pricing_counts']==case['expected_pricing_counts'],result
        records.append({'name':case['name'],'result':result})
        print(json.dumps({'case':case['name'],'rows':result['rows'],'pricing_counts':result.get('pricing_counts'),
                          'prefilled_cells':result['prefilled_cells'],'red_cells':result['red_cells']},ensure_ascii=False),flush=True)
    current,reg=registrations[0]
    context=output/'trusted-context.json'
    save(context,{'schema':'a02-trusted-context/1','current_output':str(current),'business_batch_id':reg['business_batch_id'],
                  'export_id':reg['export_id'],'a_version':reg['a_version'],'known_outputs':[str(d) for d,r in registrations]})
    actual=load(current/'technical/pricing.json');baseline=load(config['rounding_example'])
    oracle={r['row']:r for r in baseline['rows']}
    assert len(actual['rows'])==len(oracle)==1967
    before_bytes=Path(config['cases'][0]['request']['input_file']).read_bytes();after_bytes=Path(reg['file']).read_bytes()
    before,p0before=read(before_bytes,trusted_external=passive_links(before_bytes))
    after,p0after=read(after_bytes,trusted_external=passive_links(before_bytes));new_sheet=p0after.sheets[0]
    expected_red={m['cell'] for m in actual['display_marks']}
    physical_red={c.coordinate for c in after.worksheets[0]._cells.values() if c.fill.patternType=='solid' and c.fill.fgColor.type=='rgb' and c.fill.fgColor.rgb=='FFF4CCCC'}
    price_physical_red={a for a in physical_red if a.rstrip('0123456789') in ('H','U')}
    assert expected_red==price_physical_red,(len(expected_red),len(price_physical_red))
    for r in actual['rows']:
        expected=oracle[r['source_row']]
        assert r['status']==expected['status'],r
        assert r['pieces_per_box']==expected['rounded_or_preserved_pieces_per_box'],r
        assert r['difference_jpy']==expected['difference_jpy'],r
        if r['status']=='within_100_jpy':
            assert r['h_cell'] not in expected_red and r['u_cell'] not in expected_red
    # Non-H/U facts, formulas, and their caches remain exact, apart from authorized blank fills.
    allowed_fills={c['cell'] for c in reg['copy_changes'] if c.get('write_value') is not None}
    changed_helpers={c['cell'] for c in reg['controlled_formula_changes']}
    original=p0before.sheets[0]
    for address,cell in original.cells.items():
        if address in changed_helpers or address in allowed_fills:continue
        other=new_sheet.cells.get(address,{})
        assert cell.get('v')==other.get('v') and cell.get('f')==other.get('f'),address
    assert before.sheetnames==after.sheetnames
    marker_counts=dict(Counter(a.rstrip('0123456789') for a in physical_red))
    before.close();after.close()
    uploads=output/'test-uploads';uploads.mkdir();returns=[]
    def edited(name,changes,sheet='Sheet1'):
        file=uploads/(name+'.xlsx');w=load_workbook(reg['file'],keep_links=True)
        for address,value in changes.items():w[sheet][address]=value
        w.save(file);w.close();return file
    def check(name,file,status,*,modified=None,needed=None,pricing_status=None):
        dest=output/'return-tests'/name
        result=preview(dest,{'context_file':str(context),'uploaded_file':str(file)})
        assert result['status']==status,result
        if modified is not None:assert result['modified_cells']==modified,result
        if needed is not None:assert result['needs_further_confirmation_cells']==needed,result
        if pricing_status:assert result['pricing_counts'].get(pricing_status,0)>0,result
        returns.append({'name':name,'file':str(file),'result':result})
        return dest,result
    changes={};w=load_workbook(reg['file'])
    for n in (2,3):
        for col in ('E','P','Q','R','S'):changes[col+str(n)]=str(w['Sheet1'][col+str(n)].value or '')+'（回传测试）'
    for col in ('E','P'):changes[col+'4']=str(w['Sheet1'][col+'4'].value or '')+'（回传测试）'
    w.close()
    for a in ('E2','P2','Q2'):changes[a]=None
    good=edited('合法12格修改_程序测试',changes)
    good_dir,_=check('legal-12',good,'preview_ready',modified=12,needed=3)
    good_detail=read_preview(good_dir)
    save(output/'修改前后对比.json',{'test_only':True,'issued':reg['file'],'uploaded':str(good),'edits':good_detail['edits']})
    text=['# 实际回传修改前后对比','','仅程序模拟编辑，不是业务确认。','','| 单元格 | 发出值 | 回传值 | 额外待核 |','|---|---|---|---|']
    def val(v):return ('（空）' if v is None else str(v)).replace('|','\\|').replace('\n',' ')
    for e in good_detail['edits']:text.append('| '+' | '.join([e['cell'],val(e['before']['value']),val(e['after']['value']),'是' if e['needs_further_confirmation'] else '否'])+' |')
    (output/'修改前后对比.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    check('purchase-price-proposal',edited('采购价修改提案_程序测试',{'G2':3000}),'preview_ready',modified=1,needed=1,pricing_status='manual_purchase_price_pending_source')
    check('literal-box-proposal',edited('数值盒规修改提案_程序测试',{'H2':9}),'preview_ready',modified=1,needed=1,pricing_status='manual_packaging_pending_confirmation')
    for name,address,value in [('quantity','M2',261),('amount','O2',999),('original-h-formula','H4',8),('controlled-u-formula','U2',0),('japanese-unit-price','N2',100)]:
        dest,result=check(name+'-rejected',edited(name+'_误改', {address:value}),'rejected')
        assert address in json.dumps(result,ensure_ascii=False),result
    check('weight-rejected',edited('箱重误改',{'B2':999},reg['protected_weight_sheets'][0]),'rejected')
    check('unchanged',Path(reg['file']),'preview_ready',modified=0,needed=0)
    check('other-batch-rejected',Path(registrations[1][1]['file']),'rejected')
    check_hashes(protected);bootstrap()
    report={'schema':'a02-native22-history-acceptance/1','test_kind':'authorized_historical_programmatic_edit',
            'independent_new_batch_validated':False,'real_human_review':False,'all_cases_passed':True,
            'preparation_cases':records,'return_cases':returns,'physical_red_cells_by_column':marker_counts,
            'price_red_h_cells':sum(a.startswith('H') for a in expected_red),
            'price_red_u_cells':sum(a.startswith('U') for a in expected_red),
            'reference_example_matches_all_1967_rows':True,'normal_h_u_false_red_cells':0,
            'pricing_counts':actual['counts'],'issue_groups':[{'kind':g['kind'],'affected_rows':g['affected_rows']} for g in actual['groups']],
            'program_groups':[{'kind':g['kind'],'affected_rows':g['affected_rows']} for g in actual['program_groups']],
            'protected_files_checked':len(protected),'protected_files_unchanged':True,
            'confirmed':False,'a_version_saved':False,'b_calculated':False,'formal_output':False,
            'business_exception_total':None,'actual_human_actions':None,'time_saved':None}
    save(output/'acceptance.json',report);save(output/'protection-check.json',{'files':protected,'all_unchanged':True})
    return {k:report[k] for k in ('all_cases_passed','pricing_counts','physical_red_cells_by_column','normal_h_u_false_red_cells','protected_files_checked')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(run(load(args.config),args.output),ensure_ascii=False,indent=2))
