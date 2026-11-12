"""Bind a NEW stage-two copy of a saved batch. Never prepares or confirms stage one.

Private manifest pins every input by SHA; this tool is a host adapter, not a new
calculation entry point. Issuing and returning the workbook still use run.py.
"""
from pathlib import Path
import argparse,hashlib,json,re,shutil,sqlite3,sys
from collections import defaultdict
from functools import lru_cache
from freeze_unified import sha,save
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'business-interaction/interaction'))
from stage2_math import POLICY,PRODUCT_KINDS,packaging,unique_match,norm,number

KINDS=PRODUCT_KINDS
def kind(spec,name):
    for text in [spec,name]:
        found=[k for k in KINDS if k in str(text or '')]
        if len(found)==1:return found[0]
    return None

def compatible(spec,reference):
    a,b=norm(spec),norm(reference)
    if not a or not b:return False
    return a==b or a.startswith(b) and bool(re.fullmatch(r'[\d.→\-砍改单]+',a[len(b):]))

@lru_cache(maxsize=4)
def descriptors(db):
    result=defaultdict(list)
    for (raw,) in db.execute('select descriptor_json from catalogue_entries'):
        x=json.loads(raw);result[str(x.get('code_raw'))].append(x)
    return result

def card_candidates(db,identity):
    """JAN AND YD AND compatible SKU, followed by specific mixed-card selection."""
    entries=descriptors(db).get(str(identity['code']),[])
    entries=[x for x in entries if norm(x.get('yd'))==norm(identity['yd']) and compatible(identity['spec'],x.get('specification'))]
    if not identity['yd'] or not entries:return []
    selected_kind=kind(identity['spec'],identity['name']);result=[]
    for source,row,context in db.execute('select source_sha256,source_row,context_json from yd_product_card_details where yd_key=?',(identity['yd'],)):
        context=json.loads(context);card=context.get('product_card',{});text=card.get('产品配件','')
        # A shared YD cannot establish a different product/version by itself.
        names=[norm(e.get('internal_name')) for e in entries if e.get('internal_name')]
        cardname=norm(card.get('商品名称'))
        if not cardname or not any(n==cardname for n in names):continue
        for candidate in packaging(text,identity_scoped=True,product_kind=selected_kind,product_spec=identity['spec']):
            result.append({**candidate,'source_sha256':source,'source_row':row,'source_version':context['source'],
                           'database_sha256':identity['database_sha256'],'identity':identity,'text':text})
    return result

def sheet(file,formulas=False):
    from openpyxl import load_workbook
    w=load_workbook(file,read_only=True,data_only=not formulas,keep_links=False)
    try:return w.worksheets[0].title,list(w.worksheets[0].values)
    finally:w.close()

def bind(manifest_file,output):
    m=json.loads(Path(manifest_file).read_text('utf8'));out=Path(output).resolve()
    if out.exists():raise ValueError('新计算副本目录已存在，禁止覆盖')
    for file,expected in m['files'].items():
        if sha(file)!=expected:raise ValueError('输入SHA不符：'+file)
    source=Path(m['session']);config=json.loads(source.read_text('utf8'))
    layout=json.loads(Path(m['layout']).read_text('utf8'));rowmap={x['source_row']:x['row_id'] for x in layout['row_map']}
    title,current=sheet(m['workbook']);_,raw=sheet(m['raw']);_,reference=sheet(m['reference']);_,formulas=sheet(m['reference'],True)
    def records(values,columns):
        return [dict(source_row=n,**{k:r[v-1] for k,v in columns.items()}) for n,r in enumerate(values,1) if n in rowmap]
    target=records(current,dict(carton=1,origin=2,code=3,japanese_name=10,quantity=12,price=13,amount=14))
    sources=records(raw,dict(carton=1,origin=2,code=3,japanese_name=9,quantity=13,price=14,amount=15))
    refs=records(reference,dict(carton=1,origin=2,code=3,japanese_name=7,quantity=9,price=10,amount=11))
    a=unique_match(target,sources);b={x['source_row']:y for x,y in unique_match(target,refs)}
    dbfile=config['database']['path']
    dbsha=sha(dbfile)
    if dbsha!=config['database']['sha256']:raise ValueError('商品卡快照版本漂移')
    quantity=json.loads(Path(config['quantity_review']['path']).read_text('utf8'))
    if sha(config['quantity_review']['path'])!=config['quantity_review']['sha256']:raise ValueError('采购参考版本漂移')
    db=sqlite3.connect('file:'+Path(dbfile).as_posix()+'?mode=ro',uri=True)
    rows=[]
    try:
        for t,s in a:
            n=t['source_row'];rr=b[n]['source_row'];v=current[n-1];rf=reference[rr-1]
            identity=dict(code=str(v[2]),name=v[5],spec=v[6],yd=v[17],database_sha256=dbsha)
            duty=rf[14]
            if isinstance(duty,str) and duty.endswith('%'):duty=str(number(duty[:-1])/100)
            formula=formulas[rr-1][15]
            # VAT is an explicit sourced constant in this batch, never a default.
            vat=None
            match=re.fullmatch(r'=J'+str(rr)+r'\*\(1\+O'+str(rr)+r'\)\*(0?\.\d+)',str(formula))
            if match:vat=match[1]
            qrow=quantity.get('rows',{}).get(str(v[2]),{})
            notes=qrow.get('reasons',qrow.get('reason_codes',[]))
            note='采购总量口径待核（取消、重复及批次范围独立核验）'
            observed={}
            for order in qrow.get('purchase_order_lines',[])+qrow.get('purchase_ambiguous_lines',[]):
                if norm(order.get('yd'))!=norm(identity['yd']) or not compatible(identity['spec'],order.get('spec')):continue
                k=tuple(str(order.get(f))for f in ['order_id','yd','spec','quantity','cut_quantity','status'])
                observed[k]=order
            if observed:
                note='采购观察：'+'、'.join('数量%s/砍单%s'%(x.get('quantity'),x.get('cut_quantity'))for x in list(observed.values())[:3])+'（单位、取消及范围待核，不重复减砍单）'
            rows.append({**t,'row_id':rowmap[n],'identity':identity,'total_pieces':raw[s['source_row']-1][11],
                         'reference_boxes':rf[7],'duty_rate':duty,'vat_rate':vat,'pack_candidates':card_candidates(db,identity),
                         'purchase_note':note,'source_coordinates':{'raw_row':s['source_row'],'reference_row':rr},
                         'purchase_reference':{'jan':str(v[2]),'status':qrow.get('status'),'reasons':notes}})
    finally:db.close()
    out.mkdir(parents=True)
    run=out/'saved-batch';shutil.copytree(source.parent,run,ignore=shutil.ignore_patterns('__pycache__'))
    back=run/'后台';public=run/'业务当前文件'
    config={**config,'root':str(back/'live-state'),'background':str(back),'business_directory':str(public),
            'isolation_note':'New opt-in stage2 calculation copy; inherited4302 approvals, no prepare; no formal release.'}
    config.pop('native_view_binding',None)
    original=out/'original-21-columns.xlsx';shutil.copyfile(m['workbook'],original)
    code={str(REPO/p):sha(REPO/p) for p in ['business-interaction/interaction/stage2_math.py','business-interaction/interaction/calculation_view.py','business-interaction/stage2-author.mjs','tools/bind_stage2.py']}
    binding={'schema':'business-calculation-view/2','policy':POLICY,'base_head':layout['head'],'rows':rows,'sheet':title,
             'original_workbook':str(original),'sources':{**m['files'],str(original):sha(original),dbfile:sha(dbfile),
              config['quantity_review']['path']:sha(config['quantity_review']['path'])},'code':code,'manifest_sha256':sha(manifest_file)}
    save(out/'binding.json',binding);config['calculation_view_binding']=str(out/'binding.json');config['calculation_view_binding_sha256']=sha(out/'binding.json')
    save(out/'session.json',config)
    report={'session':str(out/'session.json'),'binding':str(out/'binding.json'),'rows':len(rows),'source_matches':len(a),
            'packaging_with_independent_evidence':sum(bool(x['pack_candidates'])for x in rows),'prepare_executed':False,
            'inherited_approvals_reconfirmed':False,'original_session_changed':False,'formal_output':False}
    save(out/'binding-report.json',report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(bind(a.manifest,a.output),ensure_ascii=False))
