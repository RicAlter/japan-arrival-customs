"""Explicit provisional review overlay: preserve originals, show all candidates."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import argparse,json,hashlib
from .xlsxio import write_book,read_book

def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def build(task,search,gaps,translations,output):
    task,output=Path(task),Path(output)
    if output.exists():raise ValueError('Use a new review directory')
    job=load(task/'job.json');original=load(task/'field-evidence.json')['rows'];rows=deepcopy(original)
    named=load(search);audit=load(gaps);translated=load(translations)
    for src in named['scanned']:
        if digest(src['path'])!=src['sha256']:raise ValueError('Source changed: '+src['path'])
    if digest(job['config']['input_file'])!=job['versions']['files'][0]['sha256']:raise ValueError('Raw source changed')
    by_id={r['row_id']:r for r in rows};by_row={r['source_row']:r for r in rows};adoptions=[]
    def fill(row,field,options,note):
        if row['values'].get(field) not in ('',None):return
        clean=[];seen=set()
        for value,evidence in options:
            value=str(value or '').strip()
            if not value or value in seen:continue
            seen.add(value);clean.append((value,evidence))
        if not clean:return
        value=clean[0][0] if len(clean)==1 else '\n'.join(f'{i+1}. {v}' for i,(v,_) in enumerate(clean))
        row['values'][field]=value+'（'+('待选' if len(clean)>1 else note)+'）'
        row.setdefault('review_candidates',{})[field]={'note':note,'options':[{'value':v,'evidence':ev} for v,ev in clean],'confirmed':False}
        adoptions.append({'source_row':row['source_row'],'field':field,'options':len(clean),'note':note})
    for row in rows:
        for issue in row['issues']:
            f=issue.get('field')
            if f not in {'name','specification','purchase_price','channel','yd','material_reference'}:continue
            opts=[]
            for c in issue.get('candidates',[]):
                value=c.get('value','');sources=c.get('sources') or [c.get('source',{})]
                if f=='purchase_price' and str(value).strip():
                    currency=c.get('currency') or ('JPY' if any(s.get('role')=='business_summary' for s in sources) else '')
                    value=str(value)+(('元' if currency in {'CNY','人民币','RMB'} else '日元' if currency in {'JPY','日元'} else ' '+currency))
                    if c.get('channel'):value+=' / '+c['channel']
                opts.append((value,sources))
            fill(row,f,opts,'待确认')
    for item in audit['rows']:
        row=by_row[item['source_row']]
        for f,d in item['missing'].items():
            opts=[]
            for c in d.get('candidates',[]):
                value=c['value']
                if f=='purchase_price':value=str(value)+('元' if c.get('currency') in {'CNY','人民币','RMB'} else '日元' if c.get('currency') in {'JPY','日元'} else ' '+str(c.get('currency','')))
                opts.append((value,c))
            fill(row,f,opts,'采购候选')
    for rid,records in named['hits'].items():
        row=by_id[rid]
        if row.get('yd_requirement',{}).get('status')=='not_required':continue
        opts=[(r['fields']['yd'],r) for r in records if r['fields'].get('yd')]
        fill(row,'yd',opts,'按名称补')
    for row in rows:
        trans=translated.get(row['raw']['code'])
        if not trans:continue
        for field,value in trans.items():
            fill(row,field,[(value,{'source':'japanese_batch','raw_japanese_name':row['raw']['ja'],'authority':'user permits translation and provisional judgment'})],'译名待确认' if field=='name' else '待确认')
    output.mkdir(parents=True)
    outfile=output/'KMT20261101_运营确认表_候选已填.xlsx'
    export=write_book(job['config']['input_file'],outfile,rows,job['config']['layout_contract'],{'schema':'arrival-candidate-review/1','source_task':job['task_id'],'provisional':True,'notes':'按名称补；多个候选待选；译名待确认'})
    # Independent comparison checks source row facts and all existing values.
    assert [(r['row_id'],r['raw'],r['raw_cells']) for r in rows]==[(r['row_id'],r['raw'],r['raw_cells']) for r in original]
    assert all(r['values'].get(f)==v for r,o in zip(rows,original) for f,v in o['values'].items() if v not in ('',None))
    before=read_book(job['business_files'][0]);after=read_book(outfile)
    a={r['row']:r for r in before['sheets'][0]['rows']};b={r['row']:r for r in after['sheets'][0]['rows']}
    for n,old in a.items():
        if n not in b:raise ValueError('Row lost')
        for col in ('A','B','C','J','K','L','M'):
            for part in ('values','formulas','types'):
                assert old.get(part,{}).get(col)==b[n].get(part,{}).get(col),(n,col,part)
    assert before['sheets'][1]==after['sheets'][1]
    summary={'changes':dict(Counter(x['field'] for x in adoptions)),'rows_updated':len({x['source_row'] for x in adoptions}),'original_rows':len(rows),'remaining_blank_name':sum(not r['values'].get('name') for r in rows),'remaining_blank_required_YD':sum(not r['values'].get('yd') and r.get('yd_requirement',{}).get('status')!='not_required' for r in rows),'provisional':True,'original_values_preserved':True,'export':export}
    save(output/'field-evidence.json',{'rows':rows});save(output/'review-adoptions.json',adoptions);save(output/'review-summary.json',summary)
    (output/'说明.md').write_text('候选已填入对应单元格。备注仅用：按名称补、采购候选、待选、译名待确认。候选不是已确认事实。原有人工值和日方数量金额、公式缓存、箱重保留；无图片、固定24列两张表。详细来源见field-evidence.json。\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--task',required=True);p.add_argument('--search',required=True);p.add_argument('--gaps',required=True);p.add_argument('--translations',required=True);p.add_argument('--output',required=True);a=p.parse_args();build(a.task,a.search,a.gaps,a.translations,a.output)
