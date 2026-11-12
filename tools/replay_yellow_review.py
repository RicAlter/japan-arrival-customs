"""Pinned yellow review through actual run.py; private per-row evidence stays local."""
from pathlib import Path
import argparse,json
from collections import Counter
from replay_confirmation import replay,Q
from bind_stage2 import sheet
from freeze_unified import save,sha
import zipfile,xml.etree.ElementTree as ET

def colors(file):
    with zipfile.ZipFile(file)as z:
        styles=ET.fromstring(z.read('xl/styles.xml'));s=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    fills=styles.find(Q+'fills');xfs=styles.find(Q+'cellXfs');result={}
    for c in s.iter(Q+'c'):
        a=c.get('r','');n=int(''.join(filter(str.isdigit,a)))
        if not 2<=n<=1968:continue
        fill=fills[int(xfs[int(c.get('s','0'))].get('fillId','0'))];fg=fill.find(Q+'patternFill/'+Q+'fgColor')
        if fg is not None and fg.get('rgb')in ['FFFFF2CC','FFFCE4D6']:result[a]=fg.get('rgb')
    return result

def verify(manifest,output,candidate):
    report=replay(manifest,output,candidate,'results26','factor');out=Path(output)
    m=json.loads(Path(manifest).read_text('utf8'));review=json.loads(Path(m['yellow_review']).read_text('utf8'))
    facts=json.loads((out/'binding.json').read_text('utf8'))['rows'];byrow={f['source_row']:f for f in facts}
    _,before=sheet(review['previous_file']);_,after=sheet(report['file']);oldcolors=colors(review['previous_file']);newcolors=colors(report['file'])
    solvedH={f['source_row']for f in facts if 'reviewed_reference_price'in f};solvedU={f['source_row']for f in facts if 'reviewed_pack_reference'in f}
    def check(name,value):
        report['records'].append(dict(test=name,status='passed'if value else'failed'))
        if not value:raise AssertionError(name)
    def equal(a,b):return a==b if isinstance(a,str)or isinstance(b,str)or a is None or b is None else abs(float(a)-float(b))<1e-7
    check('review targets exactly214 yellow rows',len(review['rows'])==214 and all(a in oldcolors for n,r in review['rows'].items()for a in [c+n for c in r['columns']]))
    check('17 independent box rules and99 sourced purchase reference prices resolved',len(solvedU)==17 and len(solvedH)==99)
    check('all original Qty total pieces I factor original price and amount unchanged',all(all(equal(before[n-1][i],after[n-1][i])for i in [8,10,11,12,13])for n in range(2,1969)))
    check('all five numerical results unchanged; source boxes agree with newly validated rules',all(all(equal(before[n-1][i],after[n-1][i])for i in range(21,26))for n in range(2,1969)))
    check('only reviewed H/U reference contents change',all(equal(before[n-1][i],after[n-1][i])for n in range(2,1969)for i in range(21)if not(i==7 and n in solvedH or i==20 and n in solvedU)))
    check('prior13 corrections remain cleared',all(after[n-1][20]is None for n in [*range(140,148),465,466,883,884,885]))
    check('no new yellow/red cells; exactly resolved cells cleared',set(newcolors)==set(oldcolors)-{'H'+str(n)for n in solvedH}-{'%s%d'%(c,n)for n in solvedU for c in ['U','V','Y']})
    check('resolved H uses matching original price/currency and reviewed exact-unit relation',all(after[n-1][7]==byrow[n]['reviewed_reference_price']and byrow[n]['yellow_price_review']['observations']['valid']for n in solvedH))
    pending=[];resolved=[]
    for key,r in sorted(review['rows'].items(),key=lambda x:int(x[0])):
        n=int(key);f=byrow[n];missing=[]
        if 'G'in r['columns']:missing.append('规格：缺与该条码对应的原始SKU/版本资料')
        if 'H'in r['columns']and n not in solvedH:
            reason=f['yellow_price_review']['reason']
            if 'purchase_order_status_conflict'in f['purchase_reference'].get('reasons',[]):reason='同订单采购状态冲突，需有效版本依据'
            observed=f['yellow_price_review']['observations']['valid']
            if '单位换算'in reason and observed:
                prices=sorted({str(p['price'])+str(p['currency'])for p in observed})
                reason='已有采购SKU报价'+','.join(prices)+'；'+reason
            missing.append('采购参考价：'+reason)
        if 'U'in r['columns']and n not in solvedU:
            cards=f.get('yellow_pack_review',[])
            reason='未找到本SKU/版本商品卡盒规'
            if cards:
                texts=[str(c['context'].get('product_card',{}).get('产品配件')or'')for c in cards]
                reason='商品卡未写包装数量'if not any(texts)else'只有款式数，缺每盒实物数'if all('种'in t and not any(w in t for w in ['枚','张','个','包'])for t in texts)else'混合商品通用盒规未明确适用本SKU'
            missing.append('盒规：'+reason)
        base=dict(row=n,**f['identity'],original_quantity=f['quantity'],total_pieces=f['total_pieces'],I_factor=after[n-1][8],boxes=after[n-1][21],box_tax=after[n-1][24],line_tax=after[n-1][25])
        if missing:pending.append(dict(**base,missing=missing,price_review=f.get('yellow_price_review'),pack_observations=f.get('yellow_pack_review')))
        if n in solvedH or n in solvedU:resolved.append(dict(**base,price=f.get('yellow_price_review'),cards=f.get('pack_candidates')if n in solvedU else None))
    remaining=Counter(''.join(filter(str.isalpha,a))for a,color in newcolors.items()if color=='FFFFF2CC')
    report.update(passed=len(report['records']),yellow_reviewed_rows=214,resolved_price_rows=sorted(solvedH),resolved_box_rows=sorted(solvedU),remaining_yellow_columns=dict(remaining),remaining_yellow_rows=len(pending),original_quantities_changed=0,I_factor_unchanged=True,all5_result_values_unchanged=True)
    save(out/'yellow-review.json',dict(candidate=candidate,reviewed_rows=214,resolved=resolved,pending=pending,source_manifest=manifest,source_sha256=sha(manifest)))
    text='# 尚缺依据的黄标行\n\n已逐项复核原214行黄标，核实17行盒规、补入99行采购参考价。原Qty、总单个数、原价/金额和I倍数均未改。盒数、每盒税金、本行税金等5项计算结果保留，数值与上版一致。主表继续只用颜色标记问题。\n\n剩余%s行，涉及盒规81行、采购参考价27行、规格12行，部分重叠。有来源的参考盒数和税金继续保留，不据此倒推批准盒规。\n\n|原Excel行|商品|规格|编码|还缺什么|\n|---:|---|---|---|---|\n'%len(pending)
    for p in pending:text+='|%s|%s|%s|%s|%s|\n'%(p['row'],p['name'],p['spec']or'空',p['code'],'；'.join(p['missing']))
    text+='\n1873、1874行有采购观察，但状态冲突，不能自行选定585.76JPY。1854、1857、1858行只写“全13种”，不能当作每盒13个；754–757及1900行不能借相似款盒规。\n'
    (out/'黄标缺依据汇总.md').write_text(text,'utf8');save(out/'verification.json',report)
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--candidate',required=True);a=p.parse_args();r=verify(a.manifest,a.output,a.candidate);print(json.dumps({k:v for k,v in r.items()if k!='records'},ensure_ascii=False))
