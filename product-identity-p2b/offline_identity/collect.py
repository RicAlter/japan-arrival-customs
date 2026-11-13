"""Read declared local columns, keeping original field values and cell evidence."""
import json
import zipfile
from collections import Counter
from contextlib import closing
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from .common import FIELDS,Rejected,digest,key,text,save,read_only,require_b4


def collect(spec,target_codes):
    required={'file','sheet','headers','columns','role','batch_id','mapping_version'}
    if not isinstance(spec,dict) or set(spec)!=required or not spec['columns'] or set(spec['columns'])-FIELDS:
        raise Rejected('本地资料映射结构或字段无效')
    path=Path(spec['file']).resolve(strict=True);before=digest(path)
    with zipfile.ZipFile(path) as archive:
        if any('vbaproject' in n.lower() for n in archive.namelist()):raise Rejected('不接受含宏的离线来源')
    book=load_workbook(path,read_only=True,data_only=False,keep_links=False)
    facts=[];counts=Counter();all_fields=Counter()
    try:
        if spec['sheet'] not in book.sheetnames:raise Rejected('来源工作表不匹配')
        sheet=book[spec['sheet']];declared_dimensions=sheet.calculate_dimension()
        sheet.reset_dimensions()  # Some real exports incorrectly declare A1:A1.
        max_col=max(column_index_from_string(c) for c in set(spec['headers'])|set(spec['columns'].values()))
        header=list(next(sheet.iter_rows(min_row=1,max_row=1,max_col=max_col)))
        for col,expected in spec['headers'].items():
            if header[column_index_from_string(col)-1].value!=expected:raise Rejected('来源表头不匹配：'+col)
        for row_num,cells in enumerate(sheet.iter_rows(min_row=2,max_col=max_col),2):
            if all(c.value is None for c in cells):continue
            counts['nonempty_rows']+=1
            values={};evidence={};issues=[]
            for field,col in spec['columns'].items():
                cell=cells[column_index_from_string(col)-1];raw=cell.value
                if cell.data_type in ('f','e'):
                    value=None;issues.append({'field':field,'reason':'source_formula_or_error','raw':raw})
                else:value=text(raw)
                values[field]=value
                evidence[field]={'file_sha256':before,'file_name':path.name,'sheet':sheet.title,'row':row_num,
                                 'cell':f'{col}{row_num}','raw':raw,'value':value,'type':cell.data_type}
                if value is not None:all_fields[field]+=1
            code=values.get('code_raw')
            if not code:counts['no_code_rows']+=1
            if code not in target_codes:
                counts['outside_target_rows']+=1;continue
            counts['target_rows']+=1
            if code and not values.get('code_type'):values['code_type']='source_identifier'
            fid=key([before,sheet.title,row_num,spec['mapping_version']])
            facts.append({'fact_id':fid,'values':values,'evidence':evidence,'issues':issues,
                          'source':{'path':str(path),'sha256':before,'sheet':sheet.title,'row':row_num,
                                    'role':spec['role'],'batch_id':spec['batch_id'],'mapping_version':spec['mapping_version']},
                          'review_status':'reference_only','approval':False})
    finally:book.close()
    if digest(path)!=before:raise Rejected('来源读取期间变化')
    return facts,{'source':str(path),'sha256':before,'declared_dimensions':declared_dimensions,
                  'counts':dict(counts),'nonempty_mapped_fields':dict(all_fields),'original_unchanged':True}


def collect_all(specs,p1_result,output):
    target={r['query'].get('code_raw') for r in p1_result['rows']};target.discard(None)
    output=Path(output)
    if output.exists():raise Rejected('采集目录已存在')
    output.mkdir(parents=True);facts=[];reports=[]
    for spec in specs:
        print('Reading offline source:',Path(spec['file']).name,flush=True)
        found,report=collect(spec,target);facts.extend(found);reports.append(report)
        save(output/(str(len(reports)).zfill(2)+'-source.json'),{'facts':found,'report':report})
    save(output/'facts.json',{'schema':'offline-product-facts/1','facts':facts,'reports':reports})
    return facts,reports


def original_b4_facts(database,p1):
    if digest(database)!=p1['database_sha256']:raise Rejected('P1候选对应的数据库快照已变化')
    wanted={s['observation_sha256'] for row in p1['rows']
            for candidate in row['candidates']+row['rejected_candidates'] for s in candidate['sources']}
    facts=[];ids=sorted(wanted)
    with closing(read_only(database)) as conn:
        require_b4(conn)
        for start in range(0,len(ids),500):
            group=ids[start:start+500]
            for row in conn.execute('SELECT observation_sha256,record_json FROM source_ingest_observations WHERE observation_sha256 IN ('+','.join('?' for _ in group)+')',group):
                record=json.loads(row['record_json']);values=dict(record['identity']);ev={}
                for field,body in record['fields'].items():
                    if field in FIELDS:
                        values[field]=body.get('value');ev[field]={'original_b4_field':body,'observation_sha256':row['observation_sha256']}
                fid=key(['original-b4',row['observation_sha256']]);p=record['provenance']
                facts.append({'fact_id':fid,'values':values,'evidence':ev,'issues':[],
                    'source':{'path':'b4://'+row['observation_sha256'],'sha256':p['file_sha256'],'sheet':p['sheet'],'row':p['row'],
                              'file_name':p['file_name'],'role':'original_b4','batch_id':'B4-history-snapshot','mapping_version':'original-b4-v1'},
                    'review_status':'reference_only','approval':False})
    if len(facts)!=len(wanted):raise Rejected('P1原始候选观察不完整')
    return facts
