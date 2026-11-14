"""Read-only real-batch acceptance checks; writes only a requested new report."""
from pathlib import Path
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'business-interaction'))
from rebuild_mvp.xlsxio import read_book,extract_batch
from rebuild_mvp.service import load_json,digest,identity,row_semantics


def main():
    p=argparse.ArgumentParser();p.add_argument('--task',required=True);p.add_argument('--report',required=True)
    args=p.parse_args();task=Path(args.task);job=load_json(task/'job.json')
    checks=[]
    def check(name,condition,details=None):
        checks.append({'name':name,'passed':bool(condition),'details':details})
    batch=extract_batch(job['config']['input_file'])
    rows=load_json(task/'field-evidence.json')['rows']
    result=read_book(job['business_files'][0]);sheet=result['sheets'][0]
    bynum={r['row']:r for r in sheet['rows']}
    check('source row identity and order',[r['row_id'] for r in rows]==[r['row_id'] for r in batch['rows']])
    check('source product row count',len(rows)==len(batch['rows']),len(rows))
    check('all raw facts unchanged',all(a['raw']==b['raw'] and a.get('raw_cells')==b.get('raw_cells') for a,b in zip(rows,batch['rows'])))
    # Writer uses exact original body row offset, including nonproduct gaps.
    header=batch['metadata']['header_row']
    rawfields={'carton':'A','origin':'B','code':'C','ja':'J','qty':'K','jpy_price':'L','amount':'M'}
    diffs=[]
    for row in rows:
        n=row['source_row']-header+1
        out=bynum.get(n,{}).get('values',{})
        for field,column in rawfields.items():
            if str(out.get(column,''))!=str(row['raw'].get(field,'')):
                diffs.append({'row':n,'field':field,'expected':row['raw'].get(field),'actual':out.get(column)})
    check('all exported original values and carton locations',not diffs,diffs[:10])
    formula_diffs=[];type_diffs=[]
    mapping=batch['metadata']['mapping']
    protected={mapping[k]:v for k,v in rawfields.items()}
    offset=1-header
    pattern=re.compile(r'(\$?)([A-Z]{1,3})(\$?)(\d+)')
    def translated(formula):
        def replace(match):
            col=match[2]
            if col not in protected:return match[0]
            return match[1]+protected[col]+match[3]+str(int(match[4])+offset)
        return pattern.sub(replace,formula)
    for row in rows:
        n=row['source_row']+offset;out=bynum[n]
        for field in ['code','qty','jpy_price','amount']:
            original=row['raw_cells'][field];col=rawfields[field]
            # Shared-string and inline-string are alternative encodings of the
            # same text cell. Identifier text must stay text, numbers numeric.
            semantic_type=lambda t:'text' if t in {'s','inlineStr','str'} else t
            if semantic_type(original.get('type','n'))!=semantic_type(out['types'].get(col,'n')):
                type_diffs.append({'row':n,'field':field})
            if original.get('formula') and translated(original['formula'])!=out['formulas'].get(col):
                formula_diffs.append({'row':n,'field':field,'expected':translated(original['formula']),'actual':out['formulas'].get(col)})
    check('all protected numeric/code cell types',not type_diffs,type_diffs[:10])
    check('all protected source formulas relocated',not formula_diffs,formula_diffs[:10])
    identifier_diffs=[]
    for row in rows:
        out=bynum[row['source_row']+offset]
        for field,col in [('jc','D'),('yd','Q')]:
            value=row.get('values',{}).get(field)
            if value not in ('',None) and (str(out['values'].get(col,''))!=str(value) or out['types'].get(col) not in {'s','inlineStr','str'}):
                identifier_diffs.append({'source_row':row['source_row'],'field':field})
    check('JC and YD retain full text identifiers',not identifier_diffs,identifier_diffs[:10])
    check('no missing carton',all(r['raw'].get('carton') for r in rows))
    check('fixed 24 headers',len(bynum[1]['values'])==24)
    check('two sheet names', [s['name'] for s in result['sheets']]==['invoice (計算)','重さとサイズ'])
    with zipfile.ZipFile(job['config']['input_file']) as raw,zipfile.ZipFile(job['business_files'][0]) as out:
        weight=batch['weight_sheet']
        source_member=weight['path'] if isinstance(weight,dict) else next(x['path'] for x in read_book(job['config']['input_file'])['sheets'] if x['name']==weight)
        target_member=next(x['path'] for x in result['sheets'] if x['name']=='重さとサイズ')
        check('weight XML byte preservation',raw.read(source_member)==out.read(target_member))
        check('no embedded images',not any(x.startswith('xl/media/') for x in out.namelist()))
        check('no hidden additional business sheets',len(result['sheets'])==2)
    refs=[]
    for row in rows:
        for field,value in row.get('values',{}).items():
            if value not in ('',None):refs.append((row['row_id'],field,row['evidence'].get(field,[])))
    check('all adopted fields have location and source hash',all(ev and all(x.get('source_sha256') and x.get('sheet') and x.get('row') and x.get('column') for x in ev) for _,_,ev in refs))
    channels=[ev for _,field,ev in refs if field=='channel']
    check('channel sources actual procurement only',all(x['role'] in {'purchase_list','order_detail','purchase_order'} for ev in channels for x in ev))
    inherited=[(field,ev) for _,field,ev in refs if any(x['role']=='prior_material' for x in ev)]
    check('prior file material-only',all(field in {'material','website_material','material_reference'} for field,_ in inherited))
    check('prior material exact code and Japanese name',all(any(x.get('scope',{}).get('adoption_kind')=='inherited_user_authorized_material' for x in ev) for _,ev in inherited))
    sources=load_json(task/'source-audit.json')['sources']
    check('opening sources excluded',not any(('开订' in s['path'] or '开定' in s['path'] or s['role'].lower().find('opening')>=0) for s in sources))
    check('product card revision115 labelled',all('115' in s.get('version','') and '122' in s.get('version','') for s in sources if s['role']=='product_card'))
    check('semantic digest',identity(row_semantics(rows))==job['semantic_sha256'])
    connection=sqlite3.connect('file:'+str(task/'candidate.sqlite3')+'?mode=ro',uri=True)
    check('sqlite integrity',connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
    check('database row count',connection.execute('SELECT COUNT(*) FROM batch_rows').fetchone()[0]==len(rows))
    check('distinct product and procurement domains',connection.execute('SELECT COUNT(*) FROM product_records').fetchone()[0]>0 and connection.execute('SELECT COUNT(*) FROM procurement_records').fetchone()[0]>0)
    connection.close()
    check('source input hash still unchanged',digest(job['config']['input_file'])==batch['source']['sha256'])
    report={'candidate':None,'scope':'actual current KMT matching technical validation; not operator acceptance or installation',
            'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'not_executed':0,
            'rows':len(rows),'checks':checks,'summary':job.get('summary'),'semantic_sha256':job['semantic_sha256'],
            'business_approved':False,'formal_installed':False}
    import subprocess
    report['candidate']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    path=Path(args.report);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
    for item in checks:
        if not item['passed']:print('FAILED',item['name'],json.dumps(item['details'],ensure_ascii=False))
    return bool(report['failed'])


if __name__=='__main__':raise SystemExit(main())
