"""Real-input isolated replay invariants and original A03 save/return verification."""
from pathlib import Path
import json,hashlib,sys,shutil,zipfile,xml.etree.ElementTree as ET,re
from openpyxl import load_workbook
from interaction import load,save,digest,key
from interaction.service import Service
from interaction.preparation import prepare
from interaction.preparation_workbook import update_cells
from interaction.website_query import query_materials

W=Path(__file__).resolve().parents[2];R=W/'reports/first-phase-upgrade-20261106'
request=load(R/'prepare-request.json');root=Path(request['output']);config=load(root/'session.json');file=Path(config['prepared_file'])
source=load_workbook(config['source'],read_only=False,data_only=True);out=load_workbook(file,read_only=False,data_only=True)
evidence=load(Path(config['background'])/'evidence.json')['rows'];main=out.worksheets[0]
assert len(evidence)==1275 and main.max_column==20 and len(main._images)>1200
for n,item in evidence.items():
    n=int(n);cells=item['source']['cells'];sr=source[item['source']['sheet']]
    for role,col in [('code',3),('ja',10),('qty',11),('price',12),('amount',13),('origin',2)]:
        assert main.cell(n,col).value==sr[cells[role]['cell']].value,(n,role)
with zipfile.ZipFile(config['source']) as a,zipfile.ZipFile(file) as b:
    assert a.read('xl/worksheets/sheet2.xml')==b.read('xl/worksheets/sheet2.xml')
cny_rows=sum(bool(main.cell(n,8).value and str(main.cell(n,8).value).endswith('元')) for n in range(2,1277))
source.close();out.close()
sourcef=load_workbook(config['source'],read_only=False,data_only=False);outf=load_workbook(file,read_only=False,data_only=False)
from openpyxl.formula.translate import Translator
for n,item in evidence.items():
    n=int(n);cells=item['source']['cells'];oldaddress=cells['amount']['cell'];formula=sourcef[item['source']['sheet']][oldaddress].value
    if isinstance(formula,str) and formula.startswith('='):
        projected=Translator(formula,origin=oldaddress).translate_formula(re.sub(r'\d+$',str(n),oldaddress))
        cols={cells['qty']['column']:'K',cells['price']['column']:'L',cells['amount']['column']:'M'}
        projected=re.sub(r'([A-Z]+)(\d+)',lambda m:cols.get(m[1],m[1])+m[2],projected)
        assert outf.worksheets[0]['M'+str(n)].value==projected,(n,projected,outf.worksheets[0]['M'+str(n)].value)
sourcef.close();outf.close()
svc=Service(config);v=svc.engine.basics.read_current(svc.engine.bid)
p=svc.engine.basics.preview_return(svc.engine.bid,file,expected_hash=v['current_hash']);assert p['modified_cells']==0
before=digest(file);same=prepare(request);assert digest(file)==before and len(same['business_files'])==1
queue=load(Path(config['background'])/'website-queue.json');assert len(queue['rows'])==1275
assert len({q['row'] for q in queue['rows']})==1275
# Real saved public pages only; preserve old source metadata and compare actual body SHA.
snapshots=R/'snapshots/anime_store';snapshots.mkdir(parents=True,exist_ok=True);captured=0
for meta in (W/'reports/material-plugin-20261106/authorized-test-20261106/state/pages').glob('*.json'):
    m=load(meta)
    if m.get('status')==200 and m.get('url','').startswith('https://anime-store.jp/products/'):
        body=Path(m['body'])
        if body.is_file() and digest(body)==m['sha256']:
            jan=m['url'].rstrip('/').split('/')[-1];shutil.copyfile(body,snapshots/(jan+'.html'));captured+=1
webbefore=file.read_bytes();result=query_materials(root/'session.json',{'queue_sha256':digest(Path(config['background'])/'website-queue.json'),
    'authorized':True,'plugin':str(W/'reports/material-plugin-20261106/vendor/jp_material_query'),'snapshots':str(snapshots.parent)})
afterfile=file.read_bytes()
assert result['found_rows']>=2
ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
import io
with zipfile.ZipFile(io.BytesIO(webbefore)) as a,zipfile.ZipFile(io.BytesIO(afterfile)) as b:
    for n in a.namelist():
        if n!='xl/worksheets/sheet1.xml':assert a.read(n)==b.read(n),n
    def cells(data):return {c.get('r'):ET.tostring(c) for c in ET.fromstring(data).findall('.//x:c',ns)}
    ca,cb=cells(a.read('xl/worksheets/sheet1.xml')),cells(b.read('xl/worksheets/sheet1.xml'))
    assert ca.keys()==cb.keys();assert all(k.startswith('R') for k in ca if ca[k]!=cb[k])
# Website references are display decorations, not user confirmations.
zero=svc.upload(file,kind='basics',reference='SYNTHETIC website decorated return',selection={'save_changes':[],'confirm_fields':[],'adopt_candidates':[],'evidence':{}})
assert zero.get('proposed_changes',0)==0
returned=root/'后台/SYNTHETIC_return.xlsx';returned.write_bytes(update_cells(file.read_bytes(),config['sheet'],[{'target':'F2','value':'SYNTHETIC 人工名称'}]))
target=config['sheet']+'!F2';scope={'save_changes':[target],'confirm_fields':[],'adopt_candidates':[],'evidence':{}}
p=svc.upload(returned,kind='basics',reference='SYNTHETIC save-only F2',selection=scope);assert p['proposed_changes']==1
saved=svc.confirm(p['confirmation_id'],explicit_confirmation=True,reference='SYNTHETIC explicit F2 save-only')
v=svc.engine.basics.read_current(svc.engine.bid);assert v['confirmed_field_count']==0
current=Path(saved['business_files'][0]);assert load_workbook(current,read_only=True).worksheets[0]['F2'].value=='SYNTHETIC 人工名称'
assert len(load_workbook(current)._sheets[0]._images)==len(main._images)
again=prepare(request);assert load_workbook(again['business_files'][0],read_only=True).worksheets[0]['F2'].value=='SYNTHETIC 人工名称'
report={'session':str(root/'session.json'),'source_sha256':config['source_sha256'],'database_sha256':config['database']['sha256'],
 'rows':1275,'image_count':len(main._images),'cny_rows_in_raw_replay':cny_rows,'shared_formulas_expanded_and_translated':True,'source_values_and_amount_caches_equal':True,'weight_xml_identical':True,'zero_return':0,
 'all_rows_website_queue':1275,'offline_queried_rows':result['queried_rows'],'offline_found_rows':result['found_rows'],'real_html_snapshots':captured,
 'offline_is_not_full_online_verification':True,'website_only_R_changes':True,'synthetic_save_only_confirmations':0,'manual_edit_resume_preserved':True,
 'formal_output':False,'workbuddy_native_verified':False,'installed':False}
save(R/'validation.json',report);print(json.dumps(report,ensure_ascii=False))
