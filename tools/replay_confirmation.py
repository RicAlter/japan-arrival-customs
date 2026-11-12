"""Verify the compact display through actual run.py, using a NEW saved copy."""
from pathlib import Path
import argparse,json,subprocess,sys,zipfile,xml.etree.ElementTree as ET
from fractions import Fraction
from bind_stage2 import bind
from stage2_math import calculate
from freeze_unified import save,sha
REPO=Path(__file__).resolve().parents[1]
Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

def replay(manifest,output,candidate,layout='confirmation21',i_role='price'):
    out=Path(output);bound=bind(manifest,out,display_layout=layout,i_role=i_role);config=bound['session'];records=[]
    def check(name,value):
        records.append(dict(test=name,status='passed'if value else'failed'))
        if not value:raise AssertionError(name)
    def action(n,request,expected=0):
        req=out/(str(n)+'-request.json');result=out/(str(n)+'-result.json');save(req,request)
        p=subprocess.run([sys.executable,'-X','utf8','-B',str(REPO/'business-interaction/run.py'),'--config',config,'--request',str(req),'--result-file',str(result)],capture_output=True,text=True,encoding='utf8')
        assert p.returncode==expected,p.stdout[-2500:]+p.stderr[-1000:]
        return json.loads(result.read_text('utf8'))if result.exists()else json.loads(p.stdout)
    r=action(1,{'action':'start'});issued=r['file'];binding=json.loads((out/'binding.json').read_text('utf8'))
    from openpyxl import load_workbook
    w=load_workbook(issued,read_only=True,data_only=True);values=list(w.worksheets[0].values);names=w.sheetnames;w.close()
    columns=26 if layout=='results26'else 21
    check('requested columns; no calculation-detail/reason sheet',len(values[0])==columns and names==['invoice (計算)','重さとサイズ (2)'])
    if layout=='results26':
        check('five necessary result columns retained',values[0][21:26]==('本行盒数','取整后金额JPY','取整差额JPY','每盒税金JPY','本行税金JPY'))
        matches=True
        for fact in binding['rows']:
            expected=[calculate(fact)['values'][i]for i in [3,7,8,13,14]];actual=values[fact['source_row']-1][21:26]
            matches=matches and all(a is None if e is None else a is not None and abs(float(e)-a)<1e-7 for a,e in zip(actual,expected))
        check('all1967 five-result caches match exact backend calculations',matches)
        check('1010 retains5 boxes/315.12 box tax/1575.6 row tax',values[1009][21]==5 and values[1009][24]==315.12 and abs(values[1009][25]-1575.6)<1e-7)
    check('1967 source K multipliers match s/q and requested I role',all(Fraction(str(f['unit_factor_reference']['value']))==Fraction(str(f['total_pieces']))/Fraction(str(f['quantity'])) and values[f['source_row']-1][8]==(f['unit_factor_reference']['value']if i_role=='factor'else int(Fraction(str(f['price']))/Fraction(str(f['unit_factor_reference']['value']))+Fraction(1,2))) for f in binding['rows']))
    if i_role=='factor':check('I is multiplier, not price:125=10,759=51,1010=3',values[0][8]=='倍数' and values[124][8]==10 and values[758][8]==51 and values[1009][8]==3)
    check('original quantities, prices and amounts preserved',all(values[f['source_row']-1][11:14]==(f['quantity'],f['price'],f['amount'])for f in binding['rows']))
    check('total pieces104148 and ROUND0 difference216 preserved',sum(v[10]for v in values[1:1968])==104148 and sum(v[23]if i_role=='factor'else v[8]*v[10]-v[13]for v in values[1:1968])==216)
    with zipfile.ZipFile(issued)as z,zipfile.ZipFile(binding['original_workbook'])as old:
        styles=ET.fromstring(z.read('xl/styles.xml'));fills=styles.find(Q+'fills');xfs=styles.find(Q+'cellXfs');s=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));colors={}
        for c in s.iter(Q+'c'):
            if c.get('r','').startswith('U')and c.get('r')!='U1':
                fill=fills[int(xfs[int(c.get('s','0'))].get('fillId','0'))];fg=fill.find(Q+'patternFill/'+Q+'fgColor')
                if fg is not None and fg.get('rgb')in ['FFFCE4D6','FFFFF2CC']:colors[c.get('r')]=fg.get('rgb')
        expected_red=sum(any('冲突'in e or'不能整除'in e for e in calculate(f)['errors'])for f in binding['rows'])
        check('red matches actual conflicts; sparse yellow only for explicit box SKU',sum(c=='FFFCE4D6'for c in colors.values())==expected_red and sum(c=='FFFFF2CC'for c in colors.values())<1890)
        check('images/weights and all other ZIP members byte preserved',all(z.read(name)==old.read(name)for name in old.namelist()if name not in ['xl/styles.xml','xl/workbook.xml','xl/worksheets/sheet1.xml']))
        before=ET.fromstring(old.read('xl/worksheets/sheet1.xml'));original={c.get('r'):c for c in before.iter(Q+'c')};after={c.get('r'):c for c in s.iter(Q+'c')}
        def content(c):return(c.get('t'),[(x.tag,x.text,tuple(x.attrib.items()))for x in c.iter()if x is not c])
        cleared={'U'+str(f['source_row'])for f in binding['rows']if f.get('clear_inapplicable_pack_reference')}
        check('all source cells except authorized I/K/reference corrections preserve content/formulas/cache',all(content(c)==content(after[a])for a,c in original.items()if not(a[0]in 'IK'and a[1:].isdigit()and 2<=int(a[1:])<=1968)and not(i_role=='factor'and a=='I1')and a not in cleared))
    p=action(2,{'action':'native-preview','file':issued});check('compact return preview has zero changes',p['modified_cells']==0)
    first=action(3,{'action':'upload','file':issued,'reference':'TECHNICAL compact view return; not operator approval'});again=action(4,{'action':'upload','file':issued,'reference':'TECHNICAL same compact attachment retry'})
    check('compact save/readback/idempotency',first['saved']and again['receipt_replayed']and first['revision']==again['revision'])
    runtime=json.loads((REPO.parent/'skill/runtime.json').read_text('utf8'));runtime['session']=config;save(out/'runtime.json',runtime)
    report=dict(candidate=candidate,passed=len(records),failed=0,not_executed=0,records=records,file=first['business_files'][0],sha256=sha(first['business_files'][0]),session=config,runtime=str(out/'runtime.json'),rows=1967,columns=columns,unit_factor_matches=1967,attention=dict(red=sum(c=='FFFCE4D6'for c in colors.values()),yellow=sum(c=='FFFFF2CC'for c in colors.values())),formal_output=False,operator_approval=False)
    save(out/'verification.json',report);return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--candidate',required=True);p.add_argument('--layout',choices=['confirmation21','results26'],default='confirmation21');p.add_argument('--i-role',choices=['price','factor'],default='price');a=p.parse_args();r=replay(a.manifest,a.output,a.candidate,a.layout,a.i_role);print(json.dumps({k:v for k,v in r.items()if k!='records'},ensure_ascii=False))
