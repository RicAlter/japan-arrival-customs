"""Hash-bound, read-only feasibility candidate for the existing operational pair.

Does not initialize/open/write B4, call websites, generate declarations, or alter
the frozen engine. Uses its unchanged read-only verifier for the existing pair.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

from openpyxl import load_workbook
from triage import Rejected,classify,summarize,sha


def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def save(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
def code(value):return str(int(value)) if isinstance(value,float) and value.is_integer() else str(value) if value is not None else None
def number(value):
    if value is None or value=='' or isinstance(value,bool):raise Rejected('缺少必要数值，不能报告为零异常')
    try:return Fraction(str(value))
    except (ValueError,ZeroDivisionError) as exc:raise Rejected('必要数值无效') from exc
def near(a,b):return abs(number(a)-number(b))<=Fraction(1,10**8)


def grid(path,last,columns):
    book=load_workbook(path,read_only=True,data_only=True,keep_links=False)
    try:
        sheet=book.worksheets[0];sheet.reset_dimensions()
        return sheet.title,[list(row) for row in sheet.iter_rows(min_row=1,max_row=last,max_col=columns,values_only=True)]
    finally:book.close()


def assert_pair_values(source,output,*,code_column,last):
    if source[0]!=output[0] or len(source)!=len(output):raise Rejected('原表与受控双表范围不一致')
    for n,(a,b) in enumerate(zip(source[1:last],output[1:last]),2):
        if len(a)!=len(b):raise Rejected('原表与受控双表列数不同')
        for col,(original,result) in enumerate(zip(a,b),1):
            different=(code(original)!=code(result)) if col==code_column else (original!=result)
            if different:
                raise Rejected(f'当前确认值与受控结果不一致：原行{n}，列{col}')


# Source columns are the already verified, confirmed 20/33-column pair. This
# is a read-only observation contract, not a replacement input/engine adapter.
OBSERVED={
 'carton':('internal',1,'packaging'),'origin':('internal',2,'product'),
 'japanese_name':('internal',7,'identity'),'internal_name':('internal',5,'product'),
 'customs_name':('customs',9,'product'),'category':('internal',12,'product'),
 'material':('internal',13,'material'),'business_quantity':('internal',9,'price'),
 'business_price':('internal',10,'price'),'business_amount':('internal',11,'price'),
 'internal_boxes':('internal',8,'packaging'),'internal_quantity':('internal',9,'packaging'),
 'pieces_per_box':('internal',14,'packaging'),'declaration_quantity':('customs',6,'packaging'),
 'declaration_price':('customs',7,'price'),'declaration_amount':('customs',16,'price'),
 'duty_rate':('internal',15,'tax'),'box_tax':('internal',18,'tax')}
LABELS={'carton':'箱号','origin':'原产国','japanese_name':'日文名','internal_name':'内部名','customs_name':'海关品名',
        'category':'品类','material':'材质','business_quantity':'业务数量','business_price':'业务单价','business_amount':'业务金额',
        'internal_boxes':'内部盒数','internal_quantity':'内部数量','pieces_per_box':'每盒件数','declaration_quantity':'申报数量',
        'declaration_price':'海关执行单价','declaration_amount':'海关金额','duty_rate':'关税率','box_tax':'盒装税金',
        'business_unit':'业务单位','internal_unit':'内部单位','declaration_unit':'申报单位','declaration_factor':'数量换算系数','vat_rate':'增值税率'}
REASONS={'missing_current_value':'缺少本批值','current_value_not_confirmed':'现有值待确认',
         'current_confirmed_sources_conflict':'本批两个确认来源不一致','current_value_invalid_type':'原值类型需核对'}


def analyze(cfg):
    out=Path(cfg['output']);out.mkdir(parents=True,exist_ok=False)
    protected=dict(cfg['protected_files'])
    for path,expected in protected.items():
        if digest(path)!=expected:raise Rejected('受保护原件/代码/数据库变化：'+Path(path).name)
    plan=load(cfg['p2b_plan']);payload=dict(plan);claimed=payload.pop('plan_id')
    if sha(payload)!=claimed:raise Rejected('P2-B计划哈希无效')
    batch=load(cfg['batch']);trace=load(cfg['trace']);provenance=load(cfg['provenance'])
    for source in provenance['sources']:
        if digest(source['path'])!=source['sha256']:raise Rejected('原确认依据或映射变化')
    if batch['formal_output_enabled'] is not False or trace['formal_output'] is not False:raise Rejected('正式门禁状态不符合本轮边界')
    if batch['operations_adapter']['source_bundle_hash']!=provenance['source_bundle_hash']:raise Rejected('批次与来源不一致')
    units=batch['operations_adapter']['units']
    if (units.get('confirm') is not True or not units.get('reference')
        or units['source_bundle_hash']!=provenance['source_bundle_hash']
        or units['special_conversion_hash']!=provenance['special_conversion_hash']
        or units['pairing_hash']!=provenance['pairing_hash']):raise Rejected('本批单位/特殊换算/配对确认不完整')
    # Original engine is imported only for its read-only verification operation.
    sys.path.insert(0,str(Path(cfg['engine_scripts']).resolve()))
    from arrival_core.colored_tables import verify
    verification=verify(batch,cfg['existing_pair_directory'])
    save(out/'unchanged-engine-readonly-verification.json',verification)
    count=len(plan['rows']);last=count+1
    if len(batch['rows'])!=count or len(trace['rows'])!=count:raise Rejected('原验证集范围不一致')
    sources={};outputs={};sheets={}
    for kind in ('internal','customs'):
        columns=20 if kind=='internal' else 33
        sheets[kind],sources[kind]=grid(cfg['sources'][kind],last,columns)
        _,outputs[kind]=grid(cfg['outputs'][kind],last,columns)
        assert_pair_values(sources[kind],outputs[kind],code_column=3 if kind=='internal' else 2,last=last)
    by_business={r['original_pairing']['business']:r for r in batch['rows']}
    if len(by_business)!=count:raise Rejected('原行配对重复')
    cases={rid:c['case_id'] for c in plan['cases'] for rid in c['row_ids']};facts={f['fact_id']:f for f in plan['facts']}
    items=[];background=[];independent={'business_amount':Fraction(),'customs_amount':Fraction(),'line_differences':0}
    for old,execution in zip(plan['rows'],trace['rows']):
        bi=old['query']['source']['row'];row=by_business[bi];ci=row['original_pairing']['declaration']
        if old['query']['source']['file_sha256']!=protected[cfg['sources']['internal']]:raise Rejected('P2-B原查询表哈希与本批不一致')
        if execution['source_rows']!=row['original_pairing']:raise Rejected('计算轨迹改变原行顺序')
        observed_code=code(sources['internal'][bi-1][2]);old_code=old['query']['code_raw']
        if observed_code!=old_code or observed_code!=row['identity']['code'] or observed_code!=code(sources['customs'][ci-1][1]):raise Rejected('当前原行与P2-B编码不一致')
        if sources['internal'][bi-1][6]!=old['query']['japanese_name']:raise Rejected('当前日文名与P2-B原行不一致')
        current={}
        for field,(kind,col,domain) in OBSERVED.items():
            source_row=bi if kind=='internal' else ci
            evidence={'path':cfg['sources'][kind],'sha256':protected[cfg['sources'][kind]],'sheet':sheets[kind],
                      'row':source_row,'column':col,'confirmation_reference':units['reference']}
            review=row['reviews'].get(domain,{})
            confirmed=review.get('reference')==units['reference'] and review.get('source_sha256')==batch['confirmed_input']['source_sha256']
            current[field]={'value':sources[kind][source_row-1][col-1],'confirmed':confirmed,'evidence':evidence}
        for field,value in [('business_unit',units['business_unit']),('internal_unit',units['internal_unit']),('declaration_unit',units['declaration_unit']),
                            ('declaration_factor',row['packaging']['declaration_factor']),('vat_rate',row['operational_tax_input']['vat_rate'])]:
            current[field]={'value':value,'confirmed':True,'evidence':{'batch':cfg['batch'],'row_id':row['id'],
                              'reference':units['reference'],'source_bundle_hash':provenance['source_bundle_hash']}}
        conflicts=[]
        if sources['internal'][bi-1][12]!=sources['customs'][ci-1][12]:
            conflicts.append({'field':'material','evidence':{'internal_row':bi,'customs_row':ci}})
        # Independent checks observe the accepted relationships; no rounding or
        # price/tax allocation algorithm is redefined here.
        v={k:c['value'] for k,c in current.items()}
        if not (near(number(v['business_quantity'])*number(v['business_price']),v['business_amount'])
                and near(number(v['declaration_quantity'])*number(v['declaration_price']),v['declaration_amount'])
                and near(number(v['internal_quantity'])/number(v['internal_boxes']),v['pieces_per_box'])
                and near(number(v['business_quantity'])*number(v['declaration_factor']),v['declaration_quantity'])):raise Rejected('当前数量/逐行金额关系复核失败')
        unit=number(v['business_price']);rate=number(v['duty_rate']);vat=number(v['vat_rate']);pieces=number(v['pieces_per_box'])
        if not near((unit*rate+unit*(1+rate)*vat)*pieces,v['box_tax']):raise Rejected('当前盒装税金复核失败')
        independent['business_amount']+=number(v['business_amount']);independent['customs_amount']+=number(v['declaration_amount'])
        independent['line_differences']+=number(v['business_amount'])!=number(v['declaration_amount'])
        history=[facts[fid] for fid in old['candidate_fact_ids']]
        identity_conflicts=[f for f in ('japanese_name','version','specification') if f in old['field_conflicts']]
        if old['before_status']=='identity_conflict':identity_conflicts.append('original_identity_conflict')
        item={'row_id':old['row_id'],'case_id':cases.get(old['row_id']),'code':old_code,'current':current,
              'required_fields':list(current),'current_conflicts':conflicts,
              'current_version':row['identity'].get('version') or None,
              'history_versions':[f['values'].get('version') for f in history],
              'library_issues':old['unresolved_fields'],'history_identity_conflicts':identity_conflicts}
        result=classify(item);items.append(item)
        background.append({'result':result,'current_evidence':current,'original_row_id':row['id'],'source_rows':row['original_pairing'],
                           'p2b_row_index':len(background),'original_unresolved_fields':old['unresolved_fields'],
                           'original_candidate_fact_ids':old['candidate_fact_ids'],'formal_missing_unchanged':row['confirmed_input']['formal_missing'],
                           'declaration_classification_unchanged':row['declaration_classification'],'operation_trace_index':len(background)})
    if independent['business_amount']!=number(verification['confirmed_amount_jpy']) or independent['customs_amount']!=number(verification['customs_amount_jpy']):raise Rejected('双表总金额与既有引擎不一致')
    if independent['line_differences']!=verification['line_amount_difference_rows']:raise Rejected('原有逐行金额差异未保留')
    results=[b['result'] for b in background];metrics=summarize(items,results,plan)
    formal_counts=dict(Counter(f for r in batch['rows'] for f in r['confirmed_input']['formal_missing']))
    tasks=[]
    for detail,item in zip(background,items):
        r=detail['result']
        for task in r['current_tasks']:
            tasks.append([detail['source_rows']['business'],item['current']['carton']['value'],item['code'],
                          item['current']['japanese_name']['value'],LABELS.get(task['field'],task['field']),REASONS[task['reason']],
                          item['current'].get(task['field'],{}).get('value'),task['action']])
    model={'schema':'p2c-business-exceptions/1','batch_label':cfg['batch_label'],'metrics':metrics,'exceptions':tasks,
           'source_description':'本批已确认运营双表及来源绑定计算轨迹',
           'formal_status':'正式输出继续关闭；现有正式关务缺项和权限要求保留',
           'headers':['原表行','箱号','商品编码','商品名','影响字段','原因','当前值','需要处理内容']}
    manifest={p:digest(p) for p in cfg['analysis_inputs']}
    save(out/'business-model.json',model)
    save(out/'technical-background.json',{'schema':'p2c-readonly-background/1','p2b_plan':{'path':cfg['p2b_plan'],'sha256':digest(cfg['p2b_plan']),'plan_id':claimed},
          'input_manifest':manifest,'rows':background,'formal_missing_counts_unchanged':formal_counts,
          'library_cases_preserved_by_reference':len(plan['cases']),'library_write':False,'formal_output':False})
    for path,expected in protected.items():
        if digest(path)!=expected:raise Rejected('分析期间受保护资料变化')
    acceptance={'schema':'p2c-readonly-candidate-validation/1','metrics':metrics,
        'formal_missing_counts_unchanged':formal_counts,'formal_rejected_by_unchanged_engine':verification['formal_rejected'],
        'existing_pair_verification':verification,'independent_amounts':{k:str(v) for k,v in independent.items()},
        'protected_files_unchanged':len(protected),'input_manifest':manifest,
        'source_order_preserved':True,'confirmed_values_preserved_in_existing_outputs':True,'db_opened_or_written':False,
        'd1_accessed':False,'web_requests':0,'workbuddy_tested':False,'formal_output':False}
    save(out/'acceptance.json',acceptance)
    print(json.dumps(metrics,ensure_ascii=False));return acceptance


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='只读业务适用性分析，不生成/修改报单，不回写资料库')
    parser.add_argument('--config',required=True)
    analyze(load(parser.parse_args().config))
