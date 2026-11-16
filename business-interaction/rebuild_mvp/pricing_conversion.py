"""R3-02 on the existing MVP interface; immutable upstream quantities."""
from pathlib import Path
from collections import Counter
import copy,csv,sqlite3
from .service import MvpError,code_version,digest,load_json,save_json,writer
from .storage import identity,canonical
from .quantity_conversion import portable
from .quantity_export import export
from .quantity_math import number
from .pricing_sources import quantity_delivery,PricingEvidence
from .pricing_math import POLICY,calculate,summarize,fraction
from .xlsxio import read_book

SCHEMA='arrival-price-tax/1'


def semantic_digest(rows,quantity_sha):
    return identity(portable({'rows':rows,'policy':POLICY,'quantity_sha256':quantity_sha}))


def validate(job):
    if code_version()!=job['code']:
        raise MvpError('SOURCE_CHANGED','价格税金任务程序变化；须另建版本')
    contract,delivery=quantity_delivery(job['config']['quantity_source'])
    if delivery!=job['delivery']:
        raise MvpError('SOURCE_CHANGED','上游数量交付绑定发生变化')
    for item in job['sources']:
        if not Path(item['path']).is_file()or digest(item['path'])!=item['sha256']:
            raise MvpError('SOURCE_CHANGED','价格或税率依据发生变化')
    return contract


def current(job):
    validate(job)
    for item in job.get('artifacts',[]):
        if not Path(item['path']).is_file()or digest(item['path'])!=item['sha256']:
            raise MvpError('SOURCE_CHANGED','价格税金交付发生变化，保留现文件')
    return {'schema':SCHEMA,'mode':'price_tax','task_id':job['task_id'],'step':job['step'],
            'status':job['status'],'completed_rows':job.get('completed_rows',0),
            'business_files':job.get('business_files',[]),'pricing_source':job.get('pricing_source'),
            'summary':job.get('summary',{}),'error':job.get('error'),
            'next_action':'current'if job['step']=='exported'else'resume',
            'acceptance':{'professional_tax_approved':False,'operator_approved':False,
                          'formally_installed':False,'R3_complete':False}}


def handle(req):
    action=req.get('action')
    if action not in {'prepare','current','resume'}:
        raise MvpError('INPUT_INVALID','价格税金只支持prepare/current/resume')
    required=('batch_id','quantity_source','pricing_binding')
    if action=='prepare'and set(req)-set(required)-{'workflow','action','mode','output'}:
        raise MvpError('CONFIG_INVALID','价格税金配置含不支持字段')
    rawroot=req.get('output')if action=='prepare'else req.get('task_root')
    if not rawroot:raise MvpError('INPUT_INVALID','缺价格税金任务目录')
    root=Path(rawroot).resolve()
    if action=='current':return current(load_json(root/'job.json'))
    root.mkdir(parents=True,exist_ok=True)
    with writer(root):
        jf=root/'job.json'
        if jf.exists():
            job=load_json(jf)
            if job.get('mode')!='price_tax':raise MvpError('TASK_CONFLICT','目录绑定其他模式')
            if action=='prepare'and {k:req.get(k)for k in required}!=job['config']:
                raise MvpError('TASK_CONFLICT','同目录绑定了其他价格配置')
            quantity=validate(job)
            if job['step']=='exported':return current(job)
            evidence=PricingEvidence(job['config']['pricing_binding'])
        else:
            if action!='prepare'or any(p.name!='.writer.lock'for p in root.iterdir()):
                raise MvpError('TASK_CONFLICT','价格任务须使用新目录')
            if any(not req.get(k)for k in required):raise MvpError('CONFIG_INVALID','缺数量契约或价格税率依据')
            config={k:copy.deepcopy(req[k])for k in required}
            quantity,delivery=quantity_delivery(config['quantity_source'])
            if config['batch_id']!=quantity['upstream']['batch_id']:
                raise MvpError('INPUT_INVALID','价格批次与数量保存批次不同')
            evidence=PricingEvidence(config['pricing_binding'])
            if evidence.data.get('quantity_source_sha256')!=config['quantity_source']['sha256']:
                raise MvpError('SOURCE_CHANGED','价格依据未绑定此数量契约版本')
            protected=[config['quantity_source']['path'],config['pricing_binding'],delivery['path'],delivery['job_path']]+[x['path']for x in evidence.versions]
            if any(Path(p).resolve().is_relative_to(root)for p in protected):
                raise MvpError('CONFIG_INVALID','输出目录不能包含来源或上游')
            job={'schema':SCHEMA,'mode':'price_tax','config':config,'delivery':delivery,
                 'sources':evidence.versions,'policy':POLICY,'code':code_version(),
                 'status':'running','step':'bound'}
            job['task_id']=identity(job);save_json(jf,job)
        book=read_book(job['delivery']['path'])
        sheet=next(s for s in book['sheets']if s['name']==quantity['upstream']['sheet'])
        originals={r['row']:r for r in sheet['rows']}
        rows=[];changes={}
        db=sqlite3.connect(root/'candidate.sqlite3')
        db.execute('CREATE TABLE IF NOT EXISTS pricing_rows(row_id TEXT PRIMARY KEY,input_sha TEXT,payload_sha TEXT,payload TEXT)')
        job.update(status='running',error=None);save_json(jf,job)
        try:
            for index,qrow in enumerate(quantity['rows']):
                raw=originals[qrow['row']]
                fingerprint=identity([qrow,raw,job['sources']])
                old=db.execute('SELECT input_sha,payload_sha,payload FROM pricing_rows WHERE row_id=?',(qrow['row_id'],)).fetchone()
                if old:
                    from json import loads
                    result=loads(old[2])
                    if old[0]!=fingerprint or identity(result)!=old[1]:
                        raise MvpError('TASK_CONFLICT','价格计算检查点漂移')
                else:
                    values=raw['values']
                    invoice={'quantity':values.get('K',''),'price':values.get('L',''),
                             'amount':values.get('M',''),'currency':'JPY',
                             'evidence':{'path':job['delivery']['path'],'sha256':job['delivery']['sha256'],
                                         'sheet':qrow['sheet'],'row':qrow['row'],'columns':{'quantity':'K','price':'L','amount':'M'},
                                         'formulas':{c:raw['formulas'][c]for c in 'KLM'if c in raw['formulas']}}}
                    facts,issues,candidates=evidence.facts(qrow,values.get('H',''),invoice)
                    origin=facts.get('invoice_source',{})
                    invoice['source_fields']=origin.get('source_fields',{})
                    invoice['currency']=origin.get('currency')
                    pricing=calculate(invoice,qrow['quantity'],facts)
                    pricing['issues']+=issues;pricing['rejected_candidates']=candidates
                    ratio=pricing['results'].get('purchase_ratio_round0')
                    if ratio and values.get('I','')!=''and number(values['I'])!=fraction(ratio['value']):
                        pricing['issues'].append({'code':'EXISTING_RATIO_DIFFERS','field':'purchase_ratio_round0'})
                        pricing['field_states']['purchase_ratio_round0']='conflict'
                    pricing['status']='partial'if pricing['issues']else'completed'
                    result={'row_id':qrow['row_id'],'row':qrow['row'],'sheet':qrow['sheet'],
                            'scope':qrow['scope'],'quantity_row_sha256':identity(qrow),'pricing':pricing,
                            'inherited':{c:{'value':values.get(c,''),'formula':raw['formulas'].get(c),
                                            'source_sha256':job['delivery']['sha256'],'scope':qrow['scope']}for c in 'HIKLMUVWX'}}
                    with db:db.execute('INSERT INTO pricing_rows VALUES(?,?,?,?)',(qrow['row_id'],fingerprint,identity(result),canonical(result)))
                rows.append(result)
                ratio=result['pricing']['results'].get('purchase_ratio_round0')
                if ratio and raw['values'].get('I','')==''and 'I'not in raw['formulas']:
                    changes['I'+str(qrow['row'])]=ratio['value']['numerator']
                job.update(step='calculating',completed_rows=index+1);save_json(jf,job)
            validate(job)
            semantic=semantic_digest(rows,job['config']['quantity_source']['sha256'])
            totals=summarize(rows)
            contract={'schema':SCHEMA,'result_id':semantic,'semantic_sha256':semantic,'policy':POLICY,
                      'code_sha256':job['code']['sha256'],'quantity_source':job['config']['quantity_source'],
                      'delivery':job['delivery'],'sources':job['sources'],'rows':rows,'totals':totals,
                      'professional_tax_approved':False,'R3_complete':False}
            file=root/'price-tax-results.json'
            if file.exists()and load_json(file)!=contract:raise MvpError('TASK_CONFLICT','既有价格契约不同，禁止覆盖')
            if not file.exists():save_json(file,contract)
            output=root/'价格金额与税金核对.xlsx'
            exported=export(job['delivery']['path'],output,quantity['upstream']['sheet'],changes,allowed_columns='I')
            pending=root/'价格税金待核.csv'
            with pending.open('w',encoding='utf-8-sig',newline='')as f:
                writer_=csv.writer(f);writer_.writerow(['原行','商品编码','字段','原因'])
                for row in rows:
                    for issue in row['pricing']['issues']:writer_.writerow([row['row'],row['scope']['code'],issue.get('field'),issue['code']])
            detail=root/'价格税金计算明细.csv'
            fields=['piece_price_exact','piece_price_round0','original_amount','rounded_line_amount',
                    'original_amount_difference','rounding_difference','difference_from_original_amount',
                    'duty_rate','vat_rate','tax_per_box_reference','tax_line_reference']
            labels=['未取整单个价JPY','取整单个价JPY','原金额JPY','取整金额JPY','原金额与Qty乘原价之差JPY',
                    '取整差JPY','取整金额与原金额之差JPY','关税率参考','增值税率参考','每盒税金参考JPY','本行税金参考JPY']
            unit_labels={x['row_id']:(x['quantity'].get('raw_unit')or{}).get('label','')for x in quantity['rows']}
            with detail.open('w',encoding='utf-8-sig',newline='')as f:
                writer_=csv.writer(f);writer_.writerow(['原行','商品编码','原Qty','原Qty单位',*labels,'计算状态','待核原因'])
                for row in rows:
                    pricing=row['pricing']
                    values=[str(fraction(pricing['results'][key]['value']))if key in pricing['results']else''for key in fields]
                    writer_.writerow([row['row'],row['scope']['code'],pricing['original']['quantity'],
                                      unit_labels[row['row_id']],
                                      *values,pricing['status'],';'.join(i['code']for i in pricing['issues'])])
            validate(job)
            counts=Counter(i['code']for row in rows for i in row['pricing']['issues'])
            job.update(step='exported',status='partial'if counts else'completed',error=None,
                       pricing_source={'path':str(file),'sha256':digest(file),'schema':SCHEMA,'semantic_sha256':semantic,'result_id':semantic},
                       business_files=[str(output)],export=exported,
                       artifacts=[{'path':str(p),'sha256':digest(p)}for p in [file,output,pending,detail]],
                       summary={'rows':len(rows),'rows_with_issues':sum(bool(r['pricing']['issues'])for r in rows),
                                'issue_counts':dict(sorted(counts.items())),'filled_I_cells':len(changes),
                                'totals':totals,'pending_reason_file':str(pending),'calculation_detail_file':str(detail)})
            save_json(jf,job);return current(job)
        except Exception as exc:
            code=getattr(exc,'code','RUNTIME_FAILURE');job.update(status='failed',error={'code':code,'message':str(exc),'retryable':code=='RUNTIME_FAILURE'});save_json(jf,job);raise
        finally:db.close()


def read_pricing_source(reference):
    if reference.get('schema')!=SCHEMA or digest(reference['path'])!=reference['sha256']:
        raise MvpError('SOURCE_CHANGED','价格契约摘要不符')
    data=load_json(reference['path'])
    if data.get('schema')!=SCHEMA or data.get('policy')!=POLICY or data.get('result_id')!=reference.get('result_id')or data.get('result_id')!=data.get('semantic_sha256')or data.get('semantic_sha256')!=reference['semantic_sha256']or semantic_digest(data['rows'],data['quantity_source']['sha256'])!=data['semantic_sha256']:
        raise MvpError('SOURCE_CHANGED','价格契约语义摘要不符')
    if data.get('totals')!=summarize(data['rows']):
        raise MvpError('SOURCE_CHANGED','价格契约汇总与逐行明细不符')
    _,delivery=quantity_delivery(data['quantity_source'])
    if delivery!=data['delivery']:raise MvpError('SOURCE_CHANGED','价格契约上游变化')
    for item in data['sources']:
        if digest(item['path'])!=item['sha256']:raise MvpError('SOURCE_CHANGED','价格契约来源变化')
    return data
