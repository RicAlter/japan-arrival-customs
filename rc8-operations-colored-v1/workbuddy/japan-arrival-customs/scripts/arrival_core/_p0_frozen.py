"""P0 offline audit only. Reads OOXML/archives; writes reports, never source XLSX.

Run with bundled Python: python -X utf8 analysis/p0_audit.py
No network, database writes, business output workbooks or P1 runtime.
"""
from __future__ import annotations
import ast
import csv
import copy
import gzip
import hashlib
import io
import json
import posixpath
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import xml.etree.ElementTree as ET
from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import range_boundaries

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/p0'
DETAIL = OUT / 'details'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
ERRORS = {'#N/A', '#VALUE!', '#REF!', '#DIV/0!', '#NUM!', '#NAME?', '#NULL!'}

def sha(data): return hashlib.sha256(data).hexdigest()
def number(v): return isinstance(v, Decimal)
def numeric_text(v):
    if number(v): return v
    if isinstance(v,str) and re.fullmatch(r'[+-]?\d+(?:\.\d+)?',v.strip()): return Decimal(v.strip())
    return None
def text(v):
    if v is None: return ''
    if isinstance(v, Decimal): return format(v, 'f')
    return str(v)
def clean(v): return re.sub(r'\s+', ' ', text(v)).strip()
def present(v): return v is not None and clean(v) != ''
def good(v): return present(v) and clean(v) not in ERRORS | {'未找到'}
def sumv(rows, key): return sum((r[key] for r in rows if number(r.get(key))), Decimal(0))
def dumps(v): return json.dumps(v, ensure_ascii=False, indent=2, default=text, sort_keys=True)
def write_json(name, obj):
    p=OUT/name; p.parent.mkdir(parents=True, exist_ok=True)
    payload=dumps(obj)+'\n'; temp=p.with_suffix(p.suffix+'.tmp'); temp.write_text(payload,encoding='utf-8'); temp.replace(p)
    assert json.loads(p.read_text(encoding='utf-8')) == json.loads(payload)
def write_csv(name, rows, fields=None):
    rows=list(rows); p=DETAIL/name; p.parent.mkdir(parents=True,exist_ok=True)
    fields=fields or list(dict.fromkeys(k for r in rows for k in r))
    if not fields: fields=['status']
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for row in rows:
            # No Excel formulas in review CSV exports; keep raw values in JSON evidence.
            values={k:(dumps(v) if isinstance(v,(dict,list,tuple)) else text(v)) for k,v in row.items()}
            w.writerow({k:("'"+v if isinstance(row.get(k),str) and v.startswith(('=','+','-','@')) else v) for k,v in values.items()})

class Sheet:
    def __init__(self,name,state,tree):
        self.name=name; self.state=state; self.cells={}; self.rows=defaultdict(dict)
        dim=tree.find('s:dimension',NS); self.dimension=dim.get('ref') if dim is not None else None
        self.hidden_rows=[r.get('r') for r in tree.findall('s:sheetData/s:row',NS) if r.get('hidden')=='1']
        self.hidden_columns=[dict(c.attrib) for c in tree.findall('s:cols/s:col',NS) if c.get('hidden')=='1']
        self.merges=[m.get('ref') for m in tree.findall('s:mergeCells/s:mergeCell',NS)]
    def v(self,row,col): return self.cells.get(f'{col}{row}',{}).get('v')
    def f(self,row,col): return self.cells.get(f'{col}{row}',{}).get('f')
    def ref(self,row): return f'{self.name}!{row}'

class Book:
    def __init__(self,data,label):
        self.label=label;self.sha256=sha(data);self.sheets=[];self.metadata={}
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            strings=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                strings=[''.join(t.text or '' for t in e.findall('.//s:t',NS)) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
            workbook=ET.fromstring(z.read('xl/workbook.xml'))
            rels={e.attrib['Id']:e.attrib['Target'] for e in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
            for sh in workbook.findall('s:sheets/s:sheet',NS):
                target=rels[sh.attrib[RID]]
                member=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl',target))
                tree=ET.fromstring(z.read(member)); s=Sheet(sh.get('name'),sh.get('state','visible'),tree); shared={}
                for row in tree.findall('s:sheetData/s:row',NS):
                    ri=int(row.get('r'))
                    for c in row.findall('s:c',NS):
                        addr=c.get('r');typ=c.get('t');v=c.find('s:v',NS);f=c.find('s:f',NS)
                        value=v.text if v is not None else None
                        if typ=='s' and value is not None: value=strings[int(value)]
                        elif typ=='inlineStr':value=''.join(t.text or '' for t in c.findall('.//s:t',NS))
                        elif value is not None and typ not in ('str','e','b'):
                            try:value=Decimal(value)
                            except Exception:pass
                        formula=None
                        if f is not None:
                            if f.text:
                                formula='='+f.text
                                if f.get('t')=='shared':shared[f.get('si')]=(addr,formula)
                            elif f.get('t')=='shared' and f.get('si') in shared:
                                base,orig=shared[f.get('si')];formula=Translator(orig,origin=base).translate_formula(addr)
                            else: formula='[UNRESOLVED_SHARED_FORMULA]'
                        if value is not None or formula is not None:
                            record={'v':value,'type':typ,'style':c.get('s')}
                            if formula is not None:record['f']=formula
                            s.cells[addr]=record;s.rows[ri][re.sub(r'\d','',addr)]=record
                self.sheets.append(s)
            names=[{'name':e.get('name'),'text':e.text,'hidden':e.get('hidden'),'localSheetId':e.get('localSheetId')} for e in workbook.findall('s:definedNames/s:definedName',NS)]
            extra={}
            for n in z.namelist():
                if n.endswith('.xml') and (n.startswith('docProps/') or 'comment' in n.lower() or n.startswith('xl/externalLinks/')):
                    try: extra[n]=' '.join(ET.fromstring(z.read(n)).itertext())
                    except ET.ParseError:extra[n]='XML_PARSE_ERROR'
            self.metadata={'media_count':sum(n.startswith('xl/media/') for n in z.namelist()),'comment_parts':[n for n in z.namelist() if 'comment' in n.lower()], 'external_links':[n for n in z.namelist() if n.startswith('xl/externalLinks/')], 'defined_names':names,'extra_text':extra,'calculation_properties':dict(workbook.find('s:calcPr',NS).attrib) if workbook.find('s:calcPr',NS) is not None else {}}
    def summary(self):
        return {'sha256':self.sha256,'metadata':self.metadata,'sheets':[{'name':s.name,'state':s.state,'dimension':s.dimension,'nonempty_rows':len(s.rows),'nonempty_cells':len(s.cells),'formulas':sum('f'in c for c in s.cells.values()),'unresolved_formulas':sum(c.get('f')=='[UNRESOLVED_SHARED_FORMULA]' for c in s.cells.values()),'error_cells':sum(c.get('type')=='e' for c in s.cells.values()),'formula_no_cache':sum('f'in c and c['v'] is None for c in s.cells.values()),'hidden_rows':s.hidden_rows,'hidden_columns':s.hidden_columns,'merged_ranges':s.merges,'columns':dict(Counter(re.sub(r'\d','',a) for a in s.cells))} for s in self.sheets]}

def carton(v):
    s=clean(v).upper();m=re.fullmatch(r'([A-Z]*)(\d+)',s)
    return f'{m[1]}{int(m[2])}' if m else s
def expand(v):
    s=clean(v).upper();m=re.fullmatch(r'([A-Z]*)(\d+)\s*[-~～－–]\s*([A-Z]*)(\d+)',s)
    if m:
        a,b=int(m[2]),int(m[4]);p=m[1];q=m[3] or p
        if p==q and a<=b and b-a<10000:return [f'{p}{i}' for i in range(a,b+1)]
        return None
    if re.fullmatch(r'[A-Z]*\d+',s):return [carton(s)]
    return None

CONFIG={
1:dict(sheet=0,start=18,code='D',carton='A',ja='H',origin='K',qty='M',price='L',amount='O',wholesale='Z',wholesale_amount='AA',internal='F',variant='G',category='AB',material='AC'),
2:dict(sheet=0,start=2,code='C',ja='F',internal='D',variant='E',qty='G',category='H',material='I',search_material='J',channel='K',yd='L',url='M',site='N'),
3:dict(sheet=0,start=2,code='C',carton='A',origin='B',internal='E',variant='F',ja='I',qty='J',price='K',amount='L',category='M',material='N',channel='O',yd='P',lookup_price='G',lookup_ratio='H'),
4:dict(sheet=0,start=2,code='B',carton='A',customs_name='C',origin='D',pack='E',qty='F',price='G',channel='H',internal='I',category='J',blind='K',label='L',material='M',size='N',spec='O',amount='P',ctns='Q',unit_weight='R',weight='S'),
5:dict(sheet=0,start=2,code='B',carton='A',customs_name='C',origin='D',pack='E',qty='F',price='G',channel='H',export_name='I',category='J',blind='K',label='L',material='M',size='N',spec='O',amount='P',ctns='Q',unit_weight='R',weight='S'),
6:dict(sheet=0,start=2,code='C',carton='A',origin='B',internal='E',variant='F',ja='G',pack='H',qty='I',price='J',amount='K',category='L',material='M',pieces='N',rate='O',vat='P',duty='Q',box_tax='R',yd='S',note='T')}

def records(book,stage):
    cfg=CONFIG[stage];s=book.sheets[cfg['sheet']];out=[];carry=None
    for ri in sorted(s.rows):
        if ri<cfg['start']:continue
        cv=s.v(ri,cfg['code'])
        if not present(cv):continue
        r={k:s.v(ri,c) for k,c in cfg.items() if k not in ('sheet','start')}
        if not any(present(r.get(k)) for k in ('ja','internal','customs_name')):continue
        if 'carton' in cfg:
            if present(r['carton']):carry=r['carton']
            else:r['carton']=carry;r['carton_inherited']=True
            r['carton_key']=carton(r['carton'])
        r.update(stage=stage,file=book.label,sha256=book.sha256,sheet=s.name,row=ri,code=clean(cv))
        out.append(r)
    return out

def link(left,right,keys):
    indexes=defaultdict(list)
    for r in right:indexes[tuple(clean(r.get(k)) for k in keys)].append(r)
    groups=Counter(tuple(clean(r.get(k)) for k in keys) for r in left);used=Counter();out=[]
    for l in left:
        k=tuple(clean(l.get(f)) for f in keys);candidates=indexes.get(k,[]);i=used[k];used[k]+=1
        match=candidates[i] if i<len(candidates) else None
        out.append((l,match,{'keys':keys,'candidate_count':len(candidates),'left_key_count':groups[k],'occurrence':i+1,'status':'unique' if len(candidates)==groups[k]==1 else ('ordered_duplicate_candidate' if match else 'unmatched')}))
    return out

def evaluate_simple(formula,sheet):
    if not formula or not formula.startswith('='):raise ValueError('no formula')
    f=formula[1:]
    def cell(m):
        v=sheet.cells.get(m[0].replace('$',''),{}).get('v')
        if not number(v):raise ValueError('non-numeric precedent '+m[0])
        return str(v)
    f=re.sub(r'\$?[A-Z]{1,3}\$?\d+',cell,f)
    tree=ast.parse(f,mode='eval')
    def go(n):
        if isinstance(n,ast.Expression):return go(n.body)
        if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)):return Decimal(ast.get_source_segment(f,n))
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.USub,ast.UAdd)):return -go(n.operand) if isinstance(n.op,ast.USub) else go(n.operand)
        if isinstance(n,ast.BinOp):
            a,b=go(n.left),go(n.right)
            if isinstance(n.op,ast.Add):return a+b
            if isinstance(n.op,ast.Sub):return a-b
            if isinstance(n.op,ast.Mult):return a*b
            if isinstance(n.op,ast.Div):return a/b
        raise ValueError('unsupported expression')
    return go(tree)

def main():
    OUT.mkdir(parents=True,exist_ok=True);DETAIL.mkdir(exist_ok=True)
    input_paths=sorted(set(p for base in [ROOT/'inputs',ROOT/'历史数据',ROOT/'Codex 项目开发启动资料包/inputs'] for p in base.rglob('*') if p.is_file()))
    before={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in input_paths}
    inventory=[];cache={};books={};formula_rows=[];errors=[];columns=[]
    for p in input_paths:
        label=str(p.relative_to(ROOT)).replace('\\','/');data=p.read_bytes();h=sha(data)
        item={'file':label,'bytes':len(data),'sha256':h,'mtime':p.stat().st_mtime,'readonly_policy':'read_only_source','extension':p.suffix.lower()}
        if p.suffix.lower()=='.xlsx':
            if h not in cache:cache[h]=Book(data,label)
            books[label]=cache[h];item['audit']=cache[h].summary()
        elif p.suffix.lower()=='.rar':
            names=subprocess.run(['tar','-tf',str(p)],check=True,capture_output=True).stdout.decode('utf-8',errors='replace').splitlines();item['archive_members']=names
            for name in names:
                if not name.lower().endswith('.xlsx'):continue
                raw=subprocess.run(['tar','-xOf',str(p),name],check=True,capture_output=True).stdout
                member_label=label+'::'+name;mh=sha(raw)
                if mh not in cache:cache[mh]=Book(raw,member_label)
                books[member_label]=cache[mh]
                inventory.append({'file':member_label,'bytes':len(raw),'sha256':mh,'archive_parent':label,'audit':cache[mh].summary()})
        inventory.append(item)
    # All distinct workbook cells/formulas are scanned, including auxiliary and hidden content.
    for h,b in sorted(cache.items()):
        family=defaultdict(lambda:{'count':0,'refs':[]})
        for s in b.sheets:
            for a,c in s.cells.items():
                if c.get('type')=='e':errors.append({'file':b.label,'sha256':h,'sheet':s.name,'cell':a,'error':c['v'],'formula':c.get('f')})
                if 'f' in c:
                    normalized=re.sub(r'(\$?[A-Z]{1,3}\$?)\d+',r'\1#',c['f'])
                    k=(s.name,re.sub(r'\d','',a),normalized);family[k]['count']+=1
                    if len(family[k]['refs'])<5:family[k]['refs'].append(a)
            for col in sorted({re.sub(r'\d','',a) for a in s.cells},key=lambda x:(len(x),x)):
                cells=[(a,c) for a,c in s.cells.items() if re.sub(r'\d','',a)==col]
                columns.append({'file':b.label,'sha256':h,'sheet':s.name,'column':col,'populated':len(cells),'formulas':sum('f'in c for a,c in cells),'errors':sum(c.get('type')=='e' for a,c in cells),'first_values':[{'cell':a,'value':c['v']} for a,c in cells[:3]]})
        formula_rows.extend({'file':b.label,'sha256':h,'sheet':k[0],'column':k[1],'formula_pattern':k[2],**v} for k,v in family.items())
    manifests=[]
    for manifest in [ROOT/'inputs/SHA256SUMS.txt',ROOT/'Codex 项目开发启动资料包/inputs/SHA256SUMS.txt']:
        base=manifest.parent.parent
        for line in manifest.read_text(encoding='utf-8-sig').splitlines():
            expected,rel=line.split(maxsplit=1);p=base/rel
            actual=sha(p.read_bytes()) if p.exists() else None
            manifests.append({'manifest':str(manifest.relative_to(ROOT)),'file':str(p.relative_to(ROOT)),'expected':expected,'actual':actual,'match':expected.lower()==actual})
    stages={};stage_books={}
    for p in sorted((ROOT/'inputs/sample_kmt20261002').glob('*.xlsx')):
        stage=int(p.name[0]);label=str(p.relative_to(ROOT)).replace('\\','/');stage_books[stage]=copy.copy(books[label]);stage_books[stage].label=label;stages[stage]=records(stage_books[stage],stage)
    stats={str(n):{'rows':len(rs),'unique_codes':len({r['code'] for r in rs}),'quantity':sumv(rs,'qty'),'amount':sumv(rs,'amount'),'wholesale_amount':sumv(rs,'wholesale_amount'),'non13_codes':sum(not re.fullmatch(r'\d{13}',r['code']) for r in rs)} for n,rs in stages.items()}
    links={};alignment=[]
    for a,b in [(1,3),(3,4),(3,5),(3,6),(4,5)]:
        linked=link(stages[a],stages[b],['carton_key','code'])
        if (a,b)==(1,3):
            # Candidate changed-code links must be evidenced by carton, full Japanese name AND quantity.
            used_rows={r['row'] for l,r,m in linked if r}; refined=[]
            for l,r,m in linked:
                if r is None:
                    candidates=[x for x in stages[b] if x['row'] not in used_rows and x['carton_key']==l['carton_key'] and clean(x['ja'])==clean(l['ja']) and x['qty']==l['qty']]
                    if len(candidates)==1:
                        r=candidates[0];used_rows.add(r['row']);m={'keys':['carton_key','ja','qty'],'candidate_count':1,'left_key_count':1,'occurrence':1,'status':'changed_code_candidate_requires_review'}
                refined.append((l,r,m))
            linked=refined
        links[(a,b)]=linked
        for l,r,m in linked:alignment.append({'from_stage':a,'to_stage':b,'from_file':l['file'],'from_sheet':l['sheet'],'from_row':l['row'],'to_file':r['file'] if r else None,'to_sheet':r['sheet'] if r else None,'to_row':r['row'] if r else None,'carton':l.get('carton'),'code':l['code'],**m,'ja_equal':clean(l.get('ja'))==clean(r.get('ja')) if r and 'ja'in l and 'ja'in r else None,'name_crosscheck':clean(text(l.get('internal'))+' '+text(l.get('variant')))==clean(r.get('internal')) if r and a==3 and b==4 else None})
    quantities=[];money=[];unmatched=[]
    for l,r,m in links[(3,5)]:
        if not r:unmatched.append({'source':l,'target_stage':5});continue
        delta=r['amount']-l['amount'] if number(r.get('amount')) and number(l.get('amount')) else None
        ratio=r['qty']/l['qty'] if number(l['qty']) and l['qty'] else None
        pack_ratio=r['qty']/r['pack'] if number(r.get('pack')) and r['pack'] else None
        q={'stage3_file':l['file'],'stage3_row':l['row'],'stage5_file':r['file'],'stage5_row':r['row'],'carton':l['carton'],'code':l['code'],'ja':l['ja'],'internal_variant':l['variant'],'qty3':l['qty'],'pack5':r['pack'],'pieces5':r['qty'],'pieces_per_pack_observed':pack_ratio,'qty5_over_qty3':ratio,'stage3_lookup_H':l['lookup_ratio'],'status':'historical_arithmetic_only_not_packaging_approval','match':m['status']}
        quantities.append(q)
        money.append({'stage3_file':l['file'],'stage3_row':l['row'],'stage5_file':r['file'],'stage5_row':r['row'],'carton':l['carton'],'code':l['code'],'qty3':l['qty'],'price3':l['price'],'amount3':l['amount'],'qty5':r['qty'],'price5':r['price'],'amount5':r['amount'],'delta':delta,'unrounded_price_from_authority':l['amount']/r['qty'] if number(l['amount']) and number(r['qty']) and r['qty'] else None,'match':m['status']})
    money_changed=[r for r in money if r['delta']!=0]
    quantity_changed=[r for r in quantities if r['qty3']!=r['pieces5']]
    source_changes=[]
    for l,r,m in links[(1,3)]:
        if r:source_changes.append({'stage1_file':l['file'],'stage1_row':l['row'],'stage3_file':r['file'],'stage3_row':r['row'],'code1':l['code'],'code3':r['code'],'carton1':l['carton'],'carton3':r['carton'],'qty1':l['qty'],'qty3':r['qty'],'retail1':l['amount'],'wholesale1':l['wholesale_amount'],'amount3':r['amount'],'delta_from_wholesale':r['amount']-l['wholesale_amount'] if number(r['amount']) and number(l['wholesale_amount']) else None,'ja_equal':clean(l['ja'])==clean(r['ja']),'match':m['status']})
    source_unmatched=[l for l,r,m in links[(1,3)] if r is None]
    used3={r['row'] for l,r,m in links[(1,3)] if r}
    target_unmatched=[r for r in stages[3] if r['row'] not in used3]
    source_split=[]
    for l in source_unmatched:
        entities=set(expand(l['carton']) or [])
        candidates=[r for r in target_unmatched if set(expand(r['carton']) or []) and set(expand(r['carton']) or [])<=entities]
        source_split.append({'source':l,'target_candidates':candidates,'candidate_quantity_sum':sumv(candidates,'qty'),'candidate_amount_sum':sumv(candidates,'amount'),'status':'carton_split_and_product_identity_changed_candidate' if candidates else 'unmatched'})
    # Material search sheet does not carry cartons: do not resolve repeated ambiguous codes by JAN alone.
    mat_idx=defaultdict(list)
    for r in stages[2]:mat_idx[(r['code'],clean(r['ja']),clean(r['internal']),clean(r['variant']))].append(r)
    materials=[]
    old_by_new={r['row']:l for l,r,m in links[(1,3)] if r}
    for r in stages[3]:
        k=(r['code'],clean(r['ja']),clean(r['internal']),clean(r['variant']));candidates=mat_idx.get(k,[])
        evidence_match='current_code_and_names'
        if not candidates:
            old=old_by_new.get(r['row'])
            if old:
                candidates=[m for m in stages[2] if m['code']==old['code'] and clean(m['ja'])==clean(old['ja']) and clean(m['variant'])==clean(old['variant'])]
                evidence_match='source1_old_code_candidate_not_approved_transfer'
        if len(candidates)>1:
            signatures={tuple(clean(m.get(k)) for k in ['material','search_material','url','site']) for m in candidates}
            if len(signatures)==1:evidence_match+=':multiple_equivalent_evidence'
            else:evidence_match+=':ambiguous'
        material=candidates[0] if len(candidates)==1 else None
        materials.append({'stage3_row':r['row'],'code':r['code'],'carton':r['carton'],'stage2_candidate_rows':[m['row'] for m in candidates],'evidence_match':evidence_match,'business_material':r['material'],'search_material':material.get('search_material') if material else None,'source_url':material.get('url') if material else None,'source_site':material.get('site') if material else None,'comparison':'different_text_not_proven_conflict' if material and good(material.get('search_material')) and clean(r['material'])!=clean(material['search_material']) else ('search_missing_business_present' if material and not good(material.get('search_material')) and good(r['material']) else ('same_text' if material else 'ambiguous_or_unmatched')),'review_status':'not_proven_reviewed'})
    # Tax formula arithmetic verification (cached precedents; no rate or legal conclusion).
    tax=[];s6=stage_books[6].sheets[0]
    for r in stages[6]:
        rr={'file':r['file'],'sheet':r['sheet'],'row':r['row'],'code':r['code'],'pack':r['pack'],'qty':r['qty'],'price':r['price'],'rate':r['rate'],'note':r['note']}
        for col,key in [('N','pieces'),('P','vat'),('Q','duty'),('R','box_tax')]:
            f=s6.f(r['row'],col);rr[key+'_formula']=f;rr[key+'_cached']=r[key]
            try:
                calc=evaluate_simple(f,s6);diff=calc-r[key] if number(r[key]) else None
                rr[key+'_recalculated']=calc;rr[key+'_difference']=diff;rr[key+'_status']='within_1e-8' if diff is not None and abs(diff)<=Decimal('0.00000001') else 'mismatch'
            except Exception as e:rr[key+'_status']='not_recalculated: '+str(e)
        if all(number(r.get(k)) for k in ['pack','qty','price','rate']) and r['pack']:
            common=(r['price']*(1+r['rate'])*Decimal('.13')+r['price']*r['rate'])*(r['qty']/r['pack'])
            rr['common_box_tax_candidate']=common;rr['common_candidate_difference']=r['box_tax']-common if number(r['box_tax']) else None
        tax.append(rr)
    # Carton source and target granularity, no silent allocation of a grouped weight.
    weights=[];weight_stats={}
    for st in [1,3,6]:
        s=stage_books[st].sheets[1];rows=[]
        for ri in sorted(s.rows):
            if present(s.v(ri,'A')) and number(s.v(ri,'C')) and number(s.v(ri,'D')):
                rows.append({'stage':st,'file':stage_books[st].label,'sheet':s.name,'row':ri,'carton':s.v(ri,'A'),'ctns':s.v(ri,'C'),'unit_weight_raw':s.v(ri,'B'),'unit_weight':numeric_text(s.v(ri,'B')),'weight':s.v(ri,'D'),'entities':expand(s.v(ri,'A'))})
        weights.extend(rows);entities=[x for r in rows for x in (r['entities'] or [])]
        weight_stats[str(st)]={'groups':len(rows),'ctns':sumv(rows,'ctns'),'weight':sumv(rows,'weight'),'unit_weight_sum':sumv(rows,'unit_weight'),'physical_entities':len(entities),'unique_entities':len(set(entities)),'unparsed':[r for r in rows if r['entities'] is None],'range_count_mismatches':[r for r in rows if r['entities'] is not None and len(r['entities'])!=r['ctns']]}
    target_weights=[r for r in stages[5] if number(r.get('ctns')) or number(r.get('weight'))]
    target_entities=[x for r in target_weights for x in (expand(r['carton']) or [])]
    weight_stats['5']={'groups':len(target_weights),'ctns':sumv(target_weights,'ctns'),'weight':sumv(target_weights,'weight'),'unit_weight_sum':sumv(target_weights,'unit_weight'),'physical_entities':len(target_entities),'unique_entities':len(set(target_entities)),'duplicate_entity_fills':dict((k,n) for k,n in Counter(target_entities).items() if n>1)}
    src=[r for r in weights if r['stage']==1];weight_links=[]
    for r in src:
        es=set(r['entities'] or []);matched=[t for t in target_weights if set(expand(t['carton']) or []) & es]
        weight_links.append({'source_file':r['file'],'source_row':r['row'],'source_carton':r['carton'],'source_entities':r['entities'],'source_ctns':r['ctns'],'source_weight':r['weight'],'target_rows':[t['row'] for t in matched],'target_cartons':[t['carton'] for t in matched],'target_ctns':sumv(matched,'ctns'),'target_weight':sumv(matched,'weight'),'status':'equal' if r['ctns']==sumv(matched,'ctns') and r['weight']==sumv(matched,'weight') else 'mismatch'})
    # Static review routing is a candidate inventory, not an approval engine.
    reviews=[]
    material_by_row={m['stage3_row']:m for m in materials}
    changed_amount_rows={r['stage3_row'] for r in money_changed}
    changed_qty_rows={r['stage3_row'] for r in quantity_changed}
    changed_identity_rows={r['row'] for l,r,m in links[(1,3)] if r and m['status']!='unique'}
    for r in stages[3]:
        issues=[];flags=[]
        for k in ['code','origin','category','material']:
            if not good(r.get(k)):issues.append('missing_'+k)
        if not number(r['qty']) or r['qty']<=0:issues.append('invalid_quantity')
        if not number(r['amount']):issues.append('invalid_authoritative_amount')
        if not good(r.get('yd')):flags.append('YD_missing_requires_reason_not_automatic_block')
        if not good(r.get('internal')):flags.append('internal_name_missing_manual_supplement')
        if material_by_row[r['row']]['comparison'] in ['different_text_not_proven_conflict','ambiguous_or_unmatched']:flags.append('material_evidence_needs_review')
        if r['row'] in changed_amount_rows:flags.append('historical_price_difference_pending_policy')
        if r['row'] in changed_qty_rows:flags.append('packaging_conversion_needs_evidence')
        if r['row'] in changed_identity_rows:flags.append('changed_product_code_identity_review')
        if not re.fullmatch(r'\d{13}',r['code']):flags.append('non_JAN_identifier_preserve_raw')
        if re.search(r'扫货|代购|手办部|万代部|现货|到货通知',text(r.get('internal'))+' '+text(r.get('variant'))):flags.append('procurement_or_department_clue_only')
        reviews.append({'stage3_row':r['row'],'code':r['code'],'carton':r['carton'],'yd_raw':r['yd'],'issues':issues,'flags':flags,'route_candidate':'blocking_candidate' if issues else ('individual_review_candidate' if flags else 'batch_review_candidate'),'human_confirmed':False,'release_status':'not_approved_global_rules_and_reviews_pending','missing_frontend_status':'cannot_infer_from_workbook_alone'})
    # Exact long internal-name / YD scans across populated cells and metadata; whitelist still requires approval.
    allowed={clean(r['customs_name']) for r in stages[5]};internal={clean(r['internal']) for r in stages[3] if len(clean(r.get('internal')))>=8 and clean(r['internal']) not in allowed};yds={clean(r['yd']) for r in stages[3] if good(r['yd'])}
    privacy=[];b5=stage_books[5]
    for s in b5.sheets:
        for a,c in s.cells.items():
            if not isinstance(c['v'],str):continue
            value=clean(c['v'])
            for token in internal:
                if token in value:privacy.append({'part':'cell','sheet':s.name,'cell':a,'kind':'internal_full_name','token':token})
            for token in yds:
                if token in value:privacy.append({'part':'cell','sheet':s.name,'cell':a,'kind':'YD','token':token})
    for part,value in {**b5.metadata['extra_text'],'defined_names':dumps(b5.metadata['defined_names'])}.items():
        for token in internal|yds:
            if token in value:privacy.append({'part':part,'kind':'metadata_token','token':token})
    # Cross-batch completed files and historical tax table; all intermediate files remain in inventory/catalog.
    history=[]
    for label,b in books.items():
        if not label.startswith('历史数据/8月/') or '已完成/' not in label or '/原表/' in label:continue
        s=b.sheets[0]
        if s.name=='图片处理':
            body=[ri for ri in s.rows if ri>1 and present(s.v(ri,'B')) and number(s.v(ri,'F'))]
            history.append({'file':label,'sheet':s.name,'role':'customs','rows':len(body),'amount':sum((s.v(ri,'P') for ri in body if number(s.v(ri,'P'))),Decimal(0)),'ctns':sum((s.v(ri,'Q') for ri in body if number(s.v(ri,'Q'))),Decimal(0)),'weight':sum((s.v(ri,'S') for ri in body if number(s.v(ri,'S'))),Decimal(0)),'non13_rows':[ri for ri in body if not re.fullmatch(r'\d{13}',clean(s.v(ri,'B')))]})
        else:
            code,qty,amount,start=('J','G','I',11) if s.name=='Packing' else ('C','I','K',2)
            body=[ri for ri in s.rows if ri>=start and present(s.v(ri,code)) and present(s.v(ri,qty))]
            missing=[ri for ri in body if not number(s.v(ri,amount))];merged_tails=[];amount_groups=[]
            for merged in s.merges:
                c1,r1,c2,r2=range_boundaries(merged)
                if c1==c2 and c1==__import__('openpyxl').utils.column_index_from_string(amount) and r1 in body and r2>r1:
                    tails=[ri for ri in range(r1+1,r2+1) if ri in missing];merged_tails.extend(tails)
                    price='H' if s.name=='Packing' else 'J'
                    products=sum((s.v(ri,qty)*s.v(ri,price) for ri in range(r1,r2+1) if number(s.v(ri,qty)) and number(s.v(ri,price))),Decimal(0))
                    amount_groups.append({'range':merged,'stored_group_amount':s.v(r1,amount),'line_qty_price_sum':products,'difference':products-s.v(r1,amount) if number(s.v(r1,amount)) else None})
            history.append({'file':label,'sheet':s.name,'role':'internal','rows':len(body),'amount':sum((s.v(ri,amount) for ri in body if number(s.v(ri,amount))),Decimal(0)),'amount_missing_rows':missing,'merged_amount_tail_rows':merged_tails,'unexplained_amount_missing_rows':[ri for ri in missing if ri not in merged_tails],'amount_groups':amount_groups,'tax_formula_patterns':dict(Counter(re.sub(r'(\$?[A-Z]{1,3}\$?)\d+',r'\1#',c['f']) for a,c in s.cells.items() if 'f'in c and re.sub(r'\d','',a) in (['M','O','P','Q'] if s.name=='Packing' else ['N','P','Q','R'])))})
    rate_book=next(b for label,b in books.items() if label=='历史数据/周边产品税率202601.xlsx');rates=[];s=rate_book.sheets[0]
    for ri in sorted(s.rows):
        if present(s.v(ri,'A')) and number(s.v(ri,'B')):rates.append({'file':rate_book.label,'row':ri,'category':s.v(ri,'A'),'rate':s.v(ri,'B'),'note':s.v(ri,'C')})
        if present(s.v(ri,'F')) and number(s.v(ri,'G')):rates.append({'file':rate_book.label,'row':ri,'category':s.v(ri,'F'),'rate':s.v(ri,'G'),'note':'特别注意区域 F:G'})
    duplicate_rates={k:sorted(set(text(r['rate']) for r in rates if clean(r['category'])==k)) for k in {clean(r['category']) for r in rates} if len(set(r['rate'] for r in rates if clean(r['category'])==k))>1}
    # Source non-modification is checked after all reads and artifact writes.
    unchanged=all(sha(p.read_bytes())==before[str(p.relative_to(ROOT))] for p in input_paths)
    summary={'status':'P0_ANALYSIS_ONLY_NOT_RELEASE_APPROVAL','stage_stats':stats,'manifest_checks':manifests,'all_sources_unchanged':unchanged,'physical_input_files':len(input_paths),'workbook_references':len(books),'unique_workbook_hashes':len(cache),'scanned_sheets':sum(len(b.sheets) for b in cache.values()),'formula_cells':sum(sum('f'in c for c in s.cells.values()) for b in cache.values() for s in b.sheets),'cached_error_cells':len(errors),'quantity_changes_3_to_5':len(quantity_changed),'amount_changes_3_to_5':len(money_changed),'amount_delta_sum':sumv(money_changed,'delta'),'positive_delta':sum((r['delta'] for r in money_changed if number(r['delta']) and r['delta']>0),Decimal(0)),'negative_delta':sum((r['delta'] for r in money_changed if number(r['delta']) and r['delta']<0),Decimal(0)),'quantity_ratios':dict(Counter(text(r['qty5_over_qty3']) for r in quantity_changed)),'noninteger_pack_ratios':[r for r in quantities if number(r['pieces_per_pack_observed']) and r['pieces_per_pack_observed']%1],'alignment':dict(Counter(f"{r['from_stage']}->{r['to_stage']}:{r['status']}" for r in alignment)),'unmatched':unmatched,'source_changes_count':sum(r['delta_from_wholesale']!=0 for r in source_changes),'source_wholesale_delta':sumv(source_changes,'delta_from_wholesale'),'material_comparisons':dict(Counter(r['comparison'] for r in materials)),'search_material_counts':dict(Counter(clean(r['search_material']) for r in stages[2])),'material_source_counts':dict(Counter(clean(r['site']) for r in stages[2])),'weight_stats':weight_stats,'weight_mismatches':[r for r in weight_links if r['status']!='equal'],'tax_status':{key:dict(Counter(r[key+'_status'] for r in tax)) for key in ['pieces','vat','duty','box_tax']},'tax_common_candidate_mismatches':[r for r in tax if number(r.get('common_candidate_difference')) and abs(r['common_candidate_difference'])>Decimal('0.00000001')],'tax_rates':dict(Counter(text(r['rate']) for r in stages[6])),'review_routes':dict(Counter(r['route_candidate'] for r in reviews)),'yd_missing_count':sum(not good(r['yd']) for r in stages[3]),'procurement_clue_count':sum('procurement_or_department_clue_only' in r['flags'] for r in reviews),'privacy_exact_hits':privacy,'privacy_name_equal_count':sum(clean(r['export_name'])==clean(r['customs_name']) for r in stages[5]),'privacy_metadata':b5.summary()['metadata'],'historical_batches':history,'duplicate_tax_rates':duplicate_rates}
    summary['source_unmatched_count']=len(source_unmatched);summary['target_unmatched_count']=len(target_unmatched);summary['source_split_candidates']=source_split
    summary['source_unmatched_rows']=source_unmatched;summary['target_unmatched_rows']=target_unmatched
    summary['material_sheet2_comparisons']=dict(Counter('search_missing_business_present' if not good(r.get('search_material')) and good(r.get('material')) else ('same_text' if clean(r.get('material'))==clean(r.get('search_material')) else 'different_text_not_proven_conflict') for r in stages[2]))
    write_json('input_inventory.json',inventory);write_json('computed_baseline.json',summary);write_json('stage_records.json',stages)
    write_csv('formula_catalog.csv',formula_rows);write_csv('column_inventory.csv',columns);write_csv('all_cached_errors.csv',errors)
    write_csv('all_stage_alignments.csv',alignment);write_csv('quantity_all_rows.csv',quantities);write_csv('quantity_changes.csv',quantity_changed);write_csv('amount_all_rows.csv',money);write_csv('amount_changes.csv',money_changed);write_csv('source1_to_authority3.csv',source_changes);write_csv('material_evidence.csv',materials);write_csv('tax_recalculation.csv',tax);write_csv('weight_sources.csv',weights);write_csv('weight_group_reconciliation.csv',weight_links);write_csv('review_candidates.csv',reviews);write_csv('historical_tax_rates.csv',rates)
    write_csv('material_sheet2_comparison.csv',[{k:r.get(k) for k in ['file','sheet','row','code','material','search_material','url','site']} for r in stages[2]])
    # Detailed, immutable-address evidence. One entry per populated cell, original data types and formulas.
    evidence=DETAIL/'all_workbook_cells.jsonl';tmp=evidence.with_suffix('.jsonl.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        for h,b in sorted(cache.items()):
            for s in b.sheets:
                for a,c in s.cells.items():f.write(json.dumps({'file':b.label,'sha256':h,'sheet':s.name,'cell':a,**c},ensure_ascii=False,default=text)+'\n')
    compressed=evidence.with_suffix('.jsonl.gz')
    with tmp.open('rb') as source, compressed.open('wb') as dest:
        with gzip.GzipFile(fileobj=dest,mode='wb',mtime=0,filename='') as gz:
            while chunk:=source.read(1024*1024):gz.write(chunk)
    tmp.unlink()
    if evidence.exists():evidence.unlink()
    assert unchanged and all(r['match'] for r in manifests)
    print(dumps({k:v for k,v in summary.items() if k not in ['manifest_checks','noninteger_pack_ratios','tax_common_candidate_mismatches','privacy_metadata','search_material_counts','privacy_exact_hits','unmatched','source_split_candidates','source_unmatched_rows','target_unmatched_rows']}))
if __name__=='__main__':main()
