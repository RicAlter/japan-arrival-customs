"""Review the13 previously red rows against pinned source evidence, via run.py."""
from pathlib import Path
import argparse,json
from replay_confirmation import replay
from bind_stage2 import sheet,number
from freeze_unified import save,sha
RED={*range(140,148),465,466,883,884,885}
def verify(manifest,output,candidate):
    report=replay(manifest,output,candidate,'results26','factor');out=Path(output);m=json.loads(Path(manifest).read_text('utf8'))
    b=json.loads((out/'binding.json').read_text('utf8'));before=json.loads(Path(m['previous_binding']).read_text('utf8'));oldconfig=json.loads(Path(m['previous_binding']).with_name('session.json').read_text('utf8'))
    state=json.loads((Path(oldconfig['background'])/'stage2/current.json').read_text('utf8'));assert sha(state['file'])==state['sha256']
    _,old=sheet(state['file']);_,new=sheet(report['file']);_,reference=sheet(m['reference']);oldfacts={x['source_row']:x for x in before['rows']};facts={x['source_row']:x for x in b['rows']}
    def check(name,passed):
        report['records'].append(dict(test=name,status='passed'if passed else'failed'))
        if not passed:raise AssertionError(name)
    def equal(a,b):return a==b if a is None or b is None or isinstance(a,str)or isinstance(b,str)else abs(float(a)-float(b))<1e-7
    clear={x['source_row']for x in b['rows']if x.get('clear_inapplicable_pack_reference')}
    check('scope corrections affect exactly the13 reviewed rows',clear==RED)
    check('no red box/tax conflicts remain',report['attention']['red']==0)
    check('I multiplier K total and original L M N unchanged across1967 rows',all(all(equal(old[n-1][i],new[n-1][i])for i in [8,10,11,12,13])for n in range(2,1969)))
    check('all5 result columns outside13 rows unchanged',all(all(equal(old[n-1][i],new[n-1][i])for i in range(21,26))for n in range(2,1969)if n not in RED))
    check('rounded amounts differences and line tax unchanged for13 rows',all(all(equal(old[n-1][i],new[n-1][i])for i in [22,23,25])for n in RED))
    check('no inferred one-piece box rule approved',all(not facts[n]['pack_candidates']and facts[n]['rejected_pack_candidates']for n in RED))
    details=[]
    quantity=json.loads(Path(oldconfig['quantity_review']['path']).read_text('utf8'))['rows']
    for n in sorted(RED):
        f=facts[n];refrow=reference[f['source_coordinates']['reference_row']-1]
        check('row%d box count and both taxes agree with374-box source'%n,equal(new[n-1][21],refrow[7])and equal(new[n-1][24],refrow[17])and equal(new[n-1][25],number(refrow[17])*number(refrow[7]))and new[n-1][20]is None)
        orders=quantity[str(f['identity']['code'])].get('purchase_order_lines',[])
        details.append(dict(row=n,code=f['identity']['code'],name=f['identity']['name'],spec=f['identity']['spec'],japanese_name=f['japanese_name'],original_quantity=f['quantity'],total_pieces=f['total_pieces'],I_factor=new[n-1][8],previous_boxes=old[n-1][21],reference_boxes=f['reference_boxes'],boxes=new[n-1][21],duty_rate=f['duty_rate'],vat_rate=f['vat_rate'],box_tax=new[n-1][24],line_tax=new[n-1][25],removed_reference=old[n-1][20],rejected_rules=f['rejected_pack_candidates'],purchase_observations=[{k:o.get(k)for k in ['order_id','spec','quantity','cut_quantity','source']}for o in orders],source_coordinates=f['source_coordinates']))
    report.update(passed=len(report['records']),reviewed_rows=sorted(RED),resolved_red_rows=13,original_quantities_changed=0,scope='reference box/tax calculation restored; no fixed c=1 approval or professional tax release')
    save(out/'red13-review.json',dict(candidate=candidate,rows=details));save(out/'verification.json',report)
    text='# 13行盒数与税金逐项核对\n\n13行均为盒规跨SKU误用。已排除不适用的整盒盒规，盒数沿用有来源的374箱表，参考盒税恢复；未改原Qty、总单个数、I倍数或原价。未倒推批准每盒1个。税率沿用本批来源，专业税率批准仍独立。\n\n|原行|规格|原Qty|总单个数|盒数参考|每盒参考税JPY|本行税JPY|\n|---|---|---:|---:|---:|---:|---:|\n'
    for d in details:text+='|%s|%s|%s|%s|%s|%s|%s|\n'%(d['row'],d['spec'],d['original_quantity'],d['total_pieces'],d['boxes'],d['box_tax'],d['line_tax'])
    text+='\n140–147：角色立牌不得套共享“整盒8枚”。465–466：姓名徽章不得套普通随机吧唧8枚盒规。883–885：文件夹不得套透卡5枚盒规。原文、商品卡版本、JAN/SKU、订单观察、源行坐标和校验结果见red13-review.json。\n'
    (out/'13行核对记录.md').write_text(text,encoding='utf8');return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--candidate',required=True);a=p.parse_args();r=verify(a.manifest,a.output,a.candidate);print(json.dumps({k:v for k,v in r.items()if k!='records'},ensure_ascii=False))
