"""Read-only SQLite snapshots and explicitly configured source columns."""
import json,re,sqlite3
from decimal import Decimal,InvalidOperation
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from openpyxl import load_workbook
from . import digest,save,Rejected

def code(v):
    if v is None:return ''
    if isinstance(v,float) and v.is_integer():return str(int(v))
    return str(v).strip()

def snapshot(database,destination):
    original=Path(database).resolve(strict=True);destination=Path(destination)
    with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as a,closing(sqlite3.connect(destination)) as b:
        a.backup(b)
    return {'path':str(destination),'sha256':digest(destination),'original':str(original),'read_only_source':True}

def database_records(database,codes):
    db=sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    selected={};records=[]
    for r in db.execute('select entry_id,descriptor_json from catalogue_entries'):
        d=json.loads(r['descriptor_json'])
        if code(d.get('code_raw')) in codes:
            rec={'jan':code(d.get('code_raw')),'name':d.get('internal_name'),'spec':d.get('specification'),
                 'name_ja':d.get('japanese_name'),'yd':d.get('yd'),'versions':{},'source':{'kind':'catalogue','entry_id':r['entry_id'],'database':str(database)}}
            selected[r['entry_id']]=rec;records.append(rec)
    for r in db.execute('select * from field_variants'):
        if r['entry_id'] in selected:
            selected[r['entry_id']].setdefault('variant_sources',[]).append(dict(r))
            value=json.loads(r['value_json'])
            if value not in (None,''):selected[r['entry_id']]['versions'].setdefault(r['field_name'],[]).append(value)
    for r in db.execute('select entry_id,provenance_json,raw_record_sha256 from record_links'):
        if r['entry_id'] in selected:
            selected[r['entry_id']]['source'].setdefault('records',[]).append({'provenance':json.loads(r['provenance_json']),
                                                                            'raw_record_sha256':r['raw_record_sha256']})
    for rec in records:
        for target,field in [('channel','channel'),('currency','currency'),('price','unit_price'),('material','material_original'),('packaging','packaging_label')]:
            vals=rec['versions'].get(field,[])
            if field=='currency':
                vals=list(dict.fromkeys({'日元':'JPY','円':'JPY','人民币':'CNY','RMB':'CNY'}.get(str(v),str(v)) for v in vals))
            if field=='unit_price':
                normalized={}
                for v in vals:
                    try:
                        d=Decimal(str(v))
                        if d.is_finite():normalized.setdefault(d,v)
                    except InvalidOperation:pass
                vals=list(normalized.values())
            rec[target]=vals[0] if len(vals)==1 else None
        rec['purchase_observations']={k:rec['versions'].get(k,[]) for k in ['purchase_quantity','order_id']}
    cards=defaultdict(list)
    try:
        for r in db.execute('select * from yd_material_lookup'):
            if r['material_original']:cards[r['yd_key']].append(dict(r))
    except sqlite3.OperationalError:pass
    db.close();return records,cards

def workbook_records(config):
    file=Path(config['path']).resolve(strict=True)
    if config.get('sha256') and digest(file)!=config['sha256']:raise Rejected('来源摘要变化：'+str(file))
    wb=load_workbook(file,read_only=True,data_only=True);s=wb[config['sheet']];header=config.get('header_row',1)
    labels=next(s.iter_rows(min_row=header,max_row=header,values_only=True));cols=config['columns'];ix={}
    for k,v in cols.items():
        if isinstance(v,int):ix[k]=v-1
        else:
            found=[i for i,x in enumerate(labels) if str(x or '').strip()==v]
            if len(found)!=1:raise Rejected('来源表头须唯一；可明确列序号：'+v)
            ix[k]=found[0]
    rows=[];sha=digest(file)
    for n,row in enumerate(s.iter_rows(min_row=header+1,values_only=True),header+1):
        rec={k:row[i] if i<len(row) else None for k,i in ix.items()}
        for k in ['jan','pcs','sku']:rec[k]=code(rec.get(k))
        if not any(rec[k] for k in ['jan','pcs','sku']):continue
        rec['source']={'kind':config.get('kind','procurement'),'path':str(file),'sha256':sha,'sheet':s.title,'row':n,'columns':ix,'column_index_base':0}
        if rec.get('actual_price') not in (None,''):rec['price']=rec['actual_price']
        rec['price_scope']=config.get('price_scope','source_sku')
        rec['priority']=config.get('priority',100)
        rows.append(rec)
    wb.close();return rows

class Index:
    def __init__(self,records):
        self.direct=defaultdict(list);self.pcs=defaultdict(list)
        for r in records:
            for k in ['jan','sku']:
                if r.get(k):self.direct[code(r[k])].append(r)
            if r.get('pcs'):self.pcs[code(r['pcs'])].append(r)
    def lookup(self,jan):
        direct=self.direct.get(jan,[]);links=self.pcs.get(jan,[])
        boxcodes={code(r['jan']) for r in links if r.get('jan') and code(r['jan'])!=jan}
        if len(boxcodes)>1:return {'records':direct,'links':links,'status':'box_code_conflict','related':[]}
        related=[]
        for box in boxcodes:related+=self.direct.get(box,[])
        # Reverse link is evidence only, never copy a piece price into its box.
        reverse=[r for r in direct if r.get('pcs') and r['pcs']!=jan]
        for r in reverse:related+=self.direct.get(r['pcs'],[])
        return {'records':direct+links,'links':links+reverse,'related':related,'status':'linked' if links or reverse else 'direct'}

def unique(records,field):
    values=[r[field] for r in records if r.get(field) not in (None,'')]
    distinct={json.dumps(v,ensure_ascii=False,sort_keys=True,default=str) for v in values}
    return values[0] if len(distinct)==1 else None
