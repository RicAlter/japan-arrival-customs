"""Read-only R4-03 QA. No business prepare, writeback, download or approval.

Consume a committed pair_source through its versioned reader. Compare the
actual native files independently, and require a complete source roster before
calling coverage complete. JSON/CSV evidence is the only writable output.
"""
from pathlib import Path
from collections import Counter
from fractions import Fraction
import argparse,csv,hashlib,json,re,sys,zipfile

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'business-interaction'))
from rebuild_mvp.service import digest,load_json,save_json,MvpError
from rebuild_mvp.dual_projection import read_pair_source
from rebuild_mvp.projection_sources import graph
from rebuild_mvp.xlsxio import read_book,extract_batch,sheet_info,HEADERS,col_letter

SCHEMA='arrival-pair-acceptance/1'
def fraction(v):
    return Fraction(int(v['numerator']),int(v['denominator']))if isinstance(v,dict)else Fraction(str(v))
def cell(row,col):
    return (row.get('values',{}).get(col,''),row.get('types',{}).get(col,'n'),row.get('formulas',{}).get(col))
def zip_parts(path):
    with zipfile.ZipFile(path)as z:return {n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()}
def preserved(r2,internal,main_name):
    original=read_book(r2);result=read_book(internal);errors=[];added=[];manual=0;formulas=0
    if [s['name']for s in original['sheets']]!=[s['name']for s in result['sheets']]:errors.append({'code':'SHEETS_CHANGED'})
    for source in original['sheets']:
        target=next((s for s in result['sheets']if s['name']==source['name']),None)
        if target is None:continue
        old={r['row']:r for r in source['rows']};new={r['row']:r for r in target['rows']}
        for n in sorted(set(old)|set(new)):
            a=old.get(n,{});b=new.get(n,{})
            for col in sorted(set(a.get('types',{}))|set(b.get('types',{}))):
                x,y=cell(a,col),cell(b,col)
                blank=x[0]==''and x[2]is None and x[1]not in {'e','b'}
                permitted=source['name']==main_name and n>1 and col in {'I','U','V','W','X'}and blank
                if x[2]is not None:formulas+=1
                if source['name']==main_name and col in {'I','U','V','W','X'}and not blank:manual+=1
                if x!=y:
                    if permitted:added.append({'sheet':source['name'],'row':n,'column':col,'after':y})
                    elif x[0]!=''or y[0]!=''or x[2]is not None or y[2]is not None:errors.append({'code':'PROTECTED_CELL_CHANGED','sheet':source['name'],'row':n,'column':col,'before':x,'after':y})
        if source['merges']!=target['merges']:errors.append({'code':'MERGES_CHANGED','sheet':source['name']})
    a,b=zip_parts(r2),zip_parts(internal);main=next(s['path']for s in original['sheets']if s['name']==main_name)
    changed=[n for n in set(a)|set(b)if a.get(n)!=b.get(n)and n not in {main,'xl/styles.xml'}]
    errors += [{'code':'NON_TARGET_PART_CHANGED','part':n}for n in sorted(changed)]
    images={n:v for n,v in a.items()if n.startswith(('xl/media/','xl/drawings/'))}
    return {'errors':errors,'authorized_blank_fills':added,'existing_manual_quantity_price_cells_checked':manual,
            'original_formulas_and_caches_checked':formulas,'non_target_zip_parts_changed':changed,
            'existing_media_drawing_parts':images,'media_drawing_parts_preserved':all(b.get(n)==v for n,v in images.items())}

def coverage(q,expected):
    if expected['kind']not in {'real_batch','technical_sample'}:raise ValueError('Expected roster kind must be explicit')
    source=expected['source']
    if digest(source['path'])!=source['sha256']:raise MvpError('SOURCE_CHANGED','Expected batch roster SHA changed')
    batch=extract_batch(source['path'])
    if batch['sheet']!=expected['sheet']:raise ValueError('Expected batch sheet mismatch')
    want=[(source['sha256'],r['sheet'],r['source_row'])for r in batch['rows']]
    actual=[(r['original_identity']['source_sha256'],r['sheet'],r['original_identity']['source_row'])for r in q['rows']]
    missing=[x for x in want if x not in set(actual)];extra=[x for x in actual if x not in set(want)]
    duplicates=[list(x)for x,n in Counter(actual).items()if n>1]
    same_batch=expected['batch_id']==q['upstream']['batch_id']
    complete=actual==want and same_batch and not duplicates
    sample=bool(re.search(r'SAMPLE|SYNTHETIC|TECHNICAL',q['upstream']['batch_id'],re.I))or expected['kind']=='technical_sample'
    return {'kind':expected['kind'],'source':source,'sheet':batch['sheet'],'batch_matches':same_batch,'expected_rows':len(want),
            'actual_rows':len(actual),'matched_exact_source_rows':len(want)-len(missing),'missing':missing,'extra':extra,'duplicate_rows':duplicates,
            'source_order_complete':complete,'sample_scope':sample,'whole_batch_covered':complete and not sample}

def customs_check(data,q,p,l):
    file=next(f['path']for f in data['files']if f['kind']=='customs');book=read_book(file);errors=[]
    if len(book['sheets'])!=1:return [{'code':'CUSTOMS_SHEETS_CHANGED'}]
    sheet=book['sheets'][0];actual={r['row']:r for r in sheet['rows']};qrows={r['row_id']:r for r in q['rows']};prows={r['row_id']:r for r in p['rows']}
    def error(code,row,col):errors.append({'code':code,'row':row,'column':col})
    for row in data['rows']:
        n=row['output_row'];a=actual.get(n,{});qr=qrows[row['row_id']];pr=prows[row['row_id']]
        for i in range(1,34):
            col=col_letter(i);v=row['values'].get(col);got=a.get('values',{}).get(col,'')
            if v is None:
                if got!='':error('UNLICENSED_CELL',n,col)
            elif isinstance(v,(int,float)):
                try:good=fraction(got)==fraction(v)
                except (ValueError,ZeroDivisionError):good=False
                if not good:error('VALUE_OR_FORMULA_CACHE_MISMATCH',n,col)
            elif got!=v:error('TEXT_MISMATCH',n,col)
            formula=a.get('formulas',{}).get(col);wanted=row['formula']if col=='P'else None
            if formula!=wanted:error('UNEXPECTED_FORMULA',n,col)
        if a.get('types',{}).get('B')not in {'inlineStr','s','str'}:error('CODE_NOT_TEXT',n,'B')
        for unit,col in [('piece','F'),('box','E')]:
            if col in row['values']:
                if qr['quantity']['field_states'].get(unit)not in {'derived','inherited'}or fraction(row['values'][col])!=fraction(qr['quantity']['results'][unit]):error('QUANTITY_SOURCE_MISMATCH',n,col)
        for key,col in [('piece_price_round0','G'),('rounded_line_amount','P')]:
            if col in row['values']:
                result=pr['pricing']['results'][key]
                if result['currency']!='JPY'or fraction(result['value'])!=fraction(row['values'][col]):error('PRICE_SOURCE_MISMATCH',n,col)
        if 'P'in row['values']and fraction(row['values']['P'])!=fraction(row['values']['F'])*fraction(row['values']['G']):error('AMOUNT_PRODUCT_MISMATCH',n,'P')
    footer=len(data['rows'])+2
    for col,total in data['totals'].items():
        values=[fraction(r['values'][col])for r in data['rows']if col in r['values']]
        if total['excel_value']is not None:
            a=actual[footer]
            if fraction(a['values'].get(col,''))!=sum(values,Fraction(0))or a['formulas'].get(col)!=f'SUM({col}2:{col}{footer-1})':error('TOTAL_OR_CACHE_MISMATCH',footer,col)
    for col,expected in [('Q',l['totals']['required_unique_cartons']),('S',l['totals']['linked_weight_kg'].get('value'))]:
        if expected is not None and data['totals'][col]['complete']:
            if fraction(data['totals'][col]['value'])!=fraction(expected):error('PHYSICAL_CARTON_TOTAL_MISMATCH',footer,col)
    allowed=set(range(1,footer+2))
    if any(r['row']not in allowed and (r['values']or r['formulas'])for r in sheet['rows']):errors.append({'code':'EXTRA_OUTPUT_ROWS'})
    return errors

def audit(request):
    data=read_pair_source(request['pair_source']);q,p,l,delivery=graph(data['config']);cov=coverage(q,request['expected_batch'])
    internal=next(f['path']for f in data['files']if f['kind']=='internal')
    proof=preserved(q['upstream']['path'],internal,q['upstream']['sheet'])
    byte_equal=digest(internal)==delivery['sha256'];errors=list(proof['errors'])+customs_check(data,q,p,l)
    if not byte_equal:errors.append({'code':'R3_TO_R4_INTERNAL_BYTES_CHANGED'})
    header=read_book(internal)['sheets'][0]['rows'][0]['values']
    if [header.get(col_letter(c),'')for c in range(1,25)]!=HEADERS:errors.append({'code':'INTERNAL_LAYOUT_NOT_CURRENT24'})
    pending=[{'kind':'internal',**i}for i in data['internal_issues']]+[{'kind':'upstream',**i}for i in data['upstream_issues']]
    pending += [{'kind':'customs','row':r['row'],'output_row':r['output_row'],**i}for r in data['rows']for i in r['issues']]
    technical=not errors
    status='failed'if not technical else('coverage_incomplete'if cov['kind']=='real_batch'and not cov['whole_batch_covered']else('technical_with_gaps'if pending else'technical_passed'))
    return {'schema':SCHEMA,'pair_source':request['pair_source'],'expected_batch':request['expected_batch'],'coverage':cov,
            'technical_checks_passed':technical,'whole_batch_technical_passed':technical and cov['whole_batch_covered'],
            'data_ready':technical and cov['whole_batch_covered']and not pending,'status':status,
            'preservation':proof,'internal_byte_identical_to_R3':byte_equal,'errors':errors,'pending':pending,'pending_records':len(pending),
            'pending_reason_counts':dict(Counter(i['code']for i in pending)),'customs_totals':data['totals'],
            'operator_approved':False,'professional_approved':False,'formal_output':False,'R4_complete':False,
            'wps_display':'Separate native observations required; never inferred from XML, package or Artifact render.'}

def run(request_path,output):
    request=load_json(request_path);out=Path(output).resolve()
    if out.exists()and any(out.iterdir()):raise ValueError('Use a new evidence directory; existing results are immutable')
    # Check output isolation before creating any evidence file.
    raw=load_json(request['pair_source']['path']);inputs=[Path(request_path),Path(request['pair_source']['path']),Path(request['expected_batch']['source']['path'])]
    inputs += [Path(f['path'])for f in raw['files']]+[Path(raw['config'][k]['path'])for k in ['quantity_source','pricing_source','logistics_source']]
    task_roots=[Path(request['pair_source']['path']).resolve().parent,Path(raw['config']['review_task_root']).resolve()]+[Path(raw['config'][k]['path']).resolve().parent for k in ['quantity_source','pricing_source','logistics_source']]
    if any(p.resolve().is_relative_to(out)for p in inputs)or any(out.is_relative_to(p)for p in task_roots):raise ValueError('Evidence must not be written inside an input or previous task')
    protected={str(p.resolve()):digest(p)for p in inputs}
    for parent in task_roots:
        for name in ['job.json','candidate.sqlite3']:
            p=parent/name
            if p.is_file():protected[str(p)]=digest(p)
    result=audit(request);assert protected=={p:digest(p)for p in protected},'Read-only input drift'
    result['protected_files']=protected;result['inputs_unchanged']=True;result['auditor_sha256']=digest(__file__)
    out.mkdir(parents=True,exist_ok=True);save_json(out/'acceptance.json',result)
    for name,items,fields in [('issues.csv',result['pending']+result['errors'],['kind','row','output_row','field','column','code']),
                              ('coverage-missing.csv',[{'sha256':x[0],'sheet':x[1],'row':x[2]}for x in result['coverage']['missing']],['sha256','sheet','row'])]:
        with (out/name).open('w',encoding='utf-8-sig',newline='')as f:
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(items)
    save_json(out/'evidence-manifest.json',{'schema':SCHEMA,'files':{name:digest(out/name)for name in ['acceptance.json','issues.csv','coverage-missing.csv']}})
    return result

if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('--request',required=True);cli.add_argument('--output',required=True);args=cli.parse_args()
    result=run(args.request,args.output)
    print(json.dumps({k:result[k]for k in ['status','technical_checks_passed','whole_batch_technical_passed','pending_records','inputs_unchanged']},ensure_ascii=False))
    sys.exit(1 if not result['technical_checks_passed']else(2 if result['status']=='coverage_incomplete'else 0))
