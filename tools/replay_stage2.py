"""Real-data technical acceptance through the locked run.py entry point.

Operates only on bind_stage2's NEW copy. Test returns are explicitly technical;
the final workbook is restored to supplied source totals. No operator approval.
"""
from pathlib import Path
from collections import Counter,defaultdict
from fractions import Fraction
import argparse,copy,json,re,subprocess,sys,zipfile,xml.etree.ElementTree as ET
from freeze_unified import sha,save
from bind_stage2 import bind,number
REPO=Path(__file__).resolve().parents[1]
CELL=re.compile(rb'<c\b[^>]*?/>|<c\b[^>]*>.*?</c>',re.S)
def xml_cells(data):return {re.search(rb'\br="([^"]+)"',x[0])[1].decode():x[0] for x in CELL.finditer(data)}

def mutate(source,target,cell,value):
    """Technical return fixture: change one cell, preserve all other ZIP bytes."""
    from xml.sax.saxutils import escape
    with zipfile.ZipFile(source) as z:
        infos=z.infolist();parts={i.filename:z.read(i.filename) for i in infos}
    member='xl/worksheets/sheet1.xml';raw=parts[member]
    def change(m):
        if re.search(rb'\br="([^"]+)"',m[0])[1].decode()!=cell:return m[0]
        if isinstance(value,str):return ('<c r="'+cell+'" t="inlineStr"><is><t>'+escape(value)+'</t></is></c>').encode()
        return ('<c r="'+cell+'"><v>'+str(value)+'</v></c>').encode()
    parts[member]=CELL.sub(change,raw)
    with zipfile.ZipFile(target,'w') as z:
        for info in infos:z.writestr(copy.copy(info),parts[info.filename])

def replay(manifest,output,candidate):
    out=Path(output).resolve();info=bind(manifest,out);config=Path(info['session']);binding=json.loads((out/'binding.json').read_text('utf8'))
    protected={p:sha(p)for p in binding['sources']};records=[];count=0
    def check(name,value):
        records.append({'test':name,'status':'passed' if value else 'failed'})
        if not value:raise AssertionError(name)
    def action(request,expected=0,session=config):
        nonlocal count
        count+=1;req=out/('request-%02d.json'%count);result=out/('result-%02d.json'%count);save(req,request)
        run=subprocess.run([sys.executable,'-X','utf8','-B',str(REPO/'business-interaction/run.py'),'--config',str(session),'--request',str(req),'--result-file',str(result)],capture_output=True,text=True,encoding='utf8')
        if run.returncode!=expected:raise AssertionError('entrypoint '+str(request['action'])+': '+run.stdout[-3000:]+run.stderr[-1000:])
        return json.loads(result.read_text('utf8')) if result.exists() else json.loads(run.stdout)
    r=action({'action':'start'});initial=r['file']
    from openpyxl import load_workbook
    w=load_workbook(initial,read_only=True,data_only=True);values=list(w.worksheets[0].values);w.close()
    check('39 columns, 1967 unique full-identity matches',len(binding['rows'])==1967 and len(values[0])==39 and info['source_matches']==1967)
    check('source totals 104148 / original amount50083400 / ROUND0 difference216',sum(values[n-1][10]for n in range(2,1969))==104148 and sum(values[n-1][13]for n in range(2,1969))==50083400 and sum(values[n-1][29]for n in range(2,1969))==216)
    examples={n:{'c':values[n-1][23],'boxes':values[n-1][24],'tax_per_box':values[n-1][34]}for n in [125,759,790,834,1010]}
    check('five real examples incl36 pieces and17 boxes',[(examples[n]['c'],examples[n]['boxes'])for n in examples]==[(10,60),(51,13),(36,12),(10,21),(36,5)] and examples[1010]['tax_per_box']==315.12)
    with zipfile.ZipFile(binding['original_workbook']) as a,zipfile.ZipFile(initial) as b:
        changed=[n for n in a.namelist()if a.read(n)!=b.read(n)]
        before,after=xml_cells(a.read('xl/worksheets/sheet1.xml')),xml_cells(b.read('xl/worksheets/sheet1.xml'))
        diff=[n for n in before if before[n]!=after.get(n)]
        check('only84K and84I source cells changed, all other cells byte preserved',Counter(re.sub(r'\d','',n)for n in diff)=={'I':84,'K':84})
        check('weight, pictures, manual資料 ZIP members preserved',set(changed)=={'xl/styles.xml','xl/workbook.xml','xl/worksheets/sheet1.xml'})
        ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        aa=ET.fromstring(a.read('xl/styles.xml')).find(ns+'cellXfs');bb=ET.fromstring(b.read('xl/styles.xml')).find(ns+'cellXfs')
        check('existing style definitions and indices preserved',all(ET.tostring(x)==ET.tostring(y) for x,y in zip(aa,bb)))
        original=load_workbook(binding['original_workbook'],read_only=True,data_only=True);old=list(original.worksheets[0].values);original.close()
        rows=[n for n in range(2,1969)if old[n-1][10]!=values[n-1][10]]
        check('52 noninteger plus32 integer mismatches corrected',sum((number(old[n-1][10])/number(old[n-1][11])).denominator!=1 for n in rows)==52 and len(rows)==84)
    groups=defaultdict(list)
    for fact in binding['rows']:groups[(fact['identity']['code'],fact['identity']['spec'])].append(fact)
    repeated=[g for g in groups.values()if len(g)>1]
    check('73 split groups146 rows, observed packaging relation consistent',len(repeated)==73 and sum(map(len,repeated))==146 and all(len({number(x['total_pieces'])/number(x['reference_boxes'])for x in g})==1 for g in repeated))
    check('new formulas cache contains no spreadsheet errors',not any(isinstance(x,str)and x.startswith(('#REF!','#DIV/0!','#VALUE!','#N/A','#NAME?','#NUM!'))for v in values[1:1968]for x in v[21:39]))
    p=action({'action':'native-preview','file':initial});check('unchanged preview zero differences',p['modified_cells']==0)
    first=action({'action':'upload','file':initial,'reference':'TECHNICAL unchanged real-data return; not operator approval'})
    again=action({'action':'upload','file':initial,'reference':'TECHNICAL unchanged real-data return; not operator approval'})
    check('save/readback/idempotent replay',first['saved'] and again['receipt_replayed'] and again['revision']==first['revision'])
    stale=out/'stale-edited.xlsx';mutate(initial,stale,'K1010',360)
    rejected=action({'action':'upload','file':str(stale),'reference':'TECHNICAL stale return'},1)
    check('edited old-version workbook rejected',rejected['status']=='blocked' and '失效' in rejected['message'])
    current=action({'action':'current'});new=out/'quantity-edited.xlsx';mutate(current['business_files'][0],new,'K1010',360)
    changed=action({'action':'upload','file':str(new),'reference':'TECHNICAL new quantity branch; restore later'})
    check('qualified K saved and server recalculated',changed['accepted_changes']==1 and changed['totals']['1010']==360 and any(x['row']==1010 for x in changed['exceptions']))
    new=out/'invalid-total.xlsx';mutate(changed['business_files'][0],new,'K1010',-1)
    invalid=action({'action':'upload','file':str(new),'reference':'TECHNICAL invalid quantity; preserve accepted value'})
    check('invalid K retains last qualified total and saves exception',invalid['accepted_changes']==0 and invalid['totals']['1010']==360 and any('原合格值保留' in e for x in invalid['exceptions']if x['row']==1010 for e in x['reasons']))
    new=out/'restored-total.xlsx';mutate(invalid['business_files'][0],new,'K1010',180)
    restored=action({'action':'upload','file':str(new),'reference':'TECHNICAL restore source quantity180; not operator approval'})
    check('restored source input and no business approval',restored['totals']['1010']==180 and not restored['formal_output'] and not restored['professional_approval'] and not restored['calculation_confirmed'])
    final=restored['business_files'][0]
    for cell,value in [('L1010',999),('I1010','=SUM(M1010)'),('C1010','wrong-product')]:
        new=out/('protected-'+cell+'.xlsx');mutate(final,new,cell,value)
        rejected=action({'action':'native-preview','file':str(new)},1)
        check('protected source/formula '+cell+' rejected',rejected['status']=='blocked')
    for cell in ['F1010','G1010','R1010']:
        new=out/('basis-'+cell+'.xlsx');mutate(final,new,cell,'changed basis')
        p=action({'action':'native-preview','file':str(new)})
        check('basis change '+cell+' requires revalidation',p['status']=='requires_basics_sync_before_calculation' and not p['business_saved'])
    rejected=action({'action':'upload','file':final,'reference':'TECHNICAL compare-and-swap','expected_view_hash':'stale'},1)
    check('explicit stale CAS token rejected',rejected['status']=='blocked')
    original_config=json.loads(config.read_text('utf8'))
    for label,edit in [('head',{'base_head':'stale-head'}),('source',{'sources':{binding['original_workbook']:'0'*64}}),('code',{'code':{str(REPO/'business-interaction/stage2-author.mjs'):'0'*64}})]:
        bad=out/('bad-binding-'+label+'.json');save(bad,{**binding,**edit});cfg=out/('bad-config-'+label+'.json');save(cfg,{**original_config,'calculation_view_binding':str(bad),'calculation_view_binding_sha256':sha(bad)})
        rejected=action({'action':'current'},1,cfg);check(label+' drift invalidates calculation binding',rejected['status']=='blocked')
    check('original session/workbook/database/input SHA unchanged',all(sha(p)==h for p,h in protected.items()))
    w=load_workbook(final,read_only=True,data_only=True);finalvalues=list(w.worksheets[0].values);w.close()
    check('final deliverable restored104148 pieces and216JPY difference',sum(v[10]for v in finalvalues[1:1968])==104148 and sum(v[29]for v in finalvalues[1:1968])==216)
    exceptions=Counter(e for x in restored['exceptions']for e in x['reasons'])
    report={'candidate':candidate,'passed':len(records),'failed':0,'not_executed':0,'records':records,'kind':'real source copy through locked actual run.py; technical only',
            'rows':1967,'columns':39,'corrected_rows':84,'split_groups':73,'total_pieces':104148,'original_JPY_amount':50083400,'ROUND0_difference_JPY':216,
            'examples':examples,'exceptions':dict(exceptions),'calculated_rows':restored['calculated_rows'],'partial_rows':restored['partial_rows'],
            'session':str(config),'current_file':final,'current_file_sha256':sha(final),'original_session_changed':False,'formal_output':False,'operator_acceptance':False}
    save(out/'verification.json',report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
    r=replay(a.manifest,a.output,a.candidate);print(json.dumps({k:v for k,v in r.items()if k!='records'},ensure_ascii=False))
