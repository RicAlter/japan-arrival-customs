"""Read-only R4-03 issue triage. No business adoption or calculation engine.

Lossless raw-record references -> exact dedup -> scoped review cases.
Global questions consolidate display only, never authorize a global value.
"""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,csv,json,sys

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'business-interaction'))
from rebuild_mvp.service import load_json,save_json,digest,MvpError
from rebuild_mvp.storage import identity,canonical
from rebuild_mvp.dual_projection import read_pair_source

SCHEMA='arrival-acceptance-triage/1'
QUESTIONS={
 'quantity':('数量、包装及依赖计算','请按所列出荷行确认原Qty单位、适用包装层级及盲抽；冲突值逐项选定，精度问题另核，保留值未经确认不改。','原始数量单位、同SKU包装原文、适用行；异常或精度原因另附'),
 'purchase':('采购报价及计价依据','请提供本商品有效采购报价、币种和原计价单位；已有H文本不等于单位或换算依据。','同商品有效采购记录及计价单位；跨币种不直接比较'),
 'public':('海关字段及规格用途','请补所列缺项或确认来源字段用途；内部名、渠道和采购选项不可直接替代海关品名、品牌或对外规格。','明确表头、商品与规格范围、原格出处；不采用历史模板业务值'),
 'tax':('税率依据与适用范围','请提供关税/VAT的有效来源及逐项适用范围；本条合并提问不表示全批税率相同。','有效税率证据、商品分类与适用行；专业确认'),
 'dimensions':('尺寸体积展示口径','请明确认可模板T:X、Y、Z分别表示什么、单位及多箱展示方式；上游尺寸保留，不擅选映射。','模板字段定义及箱组/行适用范围'),
 'weight':('重量页空白模板或汇总','请核实这些重量页原行的用途和汇总范围；空白公式行尚未获准排除，不补猜数值。','对应重量表原始行及明确处置；确认后另建版本'),
 'material':('材质补查暂停','既有O材质可按原文继承；本项未补，不查询R/S、日更材质或网站，待后续授权。','暂停；不将参考或候选升级为申报事实'),
 'picture':('图片补查暂停','保留现有图及锚点；缺图暂不下载、查询或补齐。','暂停；已有图对应关系另外保留待核'),
 'price':('价格计算或展示异常','请核对所列价格异常及实际来源；不以价格比推包装，不覆盖原金额。','原价金额、单位及异常对应证据'),
 'other':('其他明确原因','请核对原始原因及关联字段；未知原因保留，不归为已解决。','原始坐标和原因明细')}
GLOBAL={'tax','dimensions','picture','material'}
QUANTITY={'BOX_RULE_MISSING','INPUT_INVALID','PACKAGING_CONFLICT','PROTECTED_PACKAGING_CONFLICT','QUANTITY_UNIT_MISSING','V_UNIT_MISSING','INVOICE_UNIT_MISSING','QUANTITY_CONVERSION_UNAVAILABLE','BLIND_UNRESOLVED','VALUE_UNAVAILABLE_OR_EXCEL_PRECISION'}
REASON_LABELS={'BLIND_UNRESOLVED':'盲抽属性缺依据','BOX_RULE_MISSING':'缺适用本SKU的盒规','CARTON_LABEL_INVALID':'重量页箱号为空或无效','INPUT_INVALID':'输入或包装范围异常（见原文）','INTERNAL_FIELD_MISSING_OR_FORMULA_CACHE':'内部字段为空或缓存缺失','INVOICE_UNIT_MISSING':'日方原计价单位缺依据','PACKAGING_CONFLICT':'包装原文存在多组冲突关系','PICTURE_MISSING':'缺图片（暂停补查）','PRICE_RESULT_UNAVAILABLE':'依赖单个价或行金额不可用','PROTECTED_PACKAGING_CONFLICT':'包装依据与保留值冲突','PUBLIC_FIELD_MISSING':'海关字段未绑定许可来源','PURCHASE_QUOTE_UNRESOLVED':'采购报价或计价单位未定','QUANTITY_CONVERSION_UNAVAILABLE':'单个数量换算不可用','QUANTITY_UNIT_MISSING':'原到货数量单位缺依据','RATE_MISSING':'税率来源或适用范围缺失','TEMPLATE_DIMENSION_MAPPING_REVIEW':'模板尺寸体积映射需确认','VALUE_UNAVAILABLE_OR_EXCEL_PRECISION':'数量结果缺失或Excel精度受限','VOLUME_INPUT_INVALID':'重量页体积输入异常','V_UNIT_MISSING':'保留V值的包装单位未明','WEIGHT_COUNT_INVALID':'重量页箱数异常','WEIGHT_FORMULA_UNSUPPORTED':'重量页空白行或不支持公式','WEIGHT_SUMMARY_UNRESOLVED':'重量页汇总待核','WEIGHT_TOTAL_INVALID':'重量页重量异常'}

def topic(issue):
    code=issue['code'];kind=issue.get('kind','')
    if code.startswith(('WEIGHT_','VOLUME_','CARTON_LABEL_'))and (kind.startswith('weight')or kind=='weight_summary'):return 'weight'
    if code=='RATE_MISSING':return 'tax'
    if code=='TEMPLATE_DIMENSION_MAPPING_REVIEW':return 'dimensions'
    if code.startswith('PICTURE_'):return 'picture'
    if code=='PUBLIC_FIELD_MISSING':return 'material'if issue.get('field')=='material'else'public'
    if code=='INTERNAL_FIELD_MISSING_OR_FORMULA_CACHE':
        col=issue.get('column')
        if col=='O':return 'material'
        if col=='H':return 'purchase'
        return 'quantity'if col in {'U','V','W','X'}else'public'
    if code=='PURCHASE_QUOTE_UNRESOLVED':return 'purchase'
    if code in QUANTITY:return 'quantity'
    if code=='PRICE_RESULT_UNAVAILABLE':return 'quantity'
    if code.startswith(('PRICE_','ORIGINAL_AMOUNT_')):return 'price'
    return 'other'

def atom(record):
    """Full original issue; messages and distinct fields are never discarded."""
    return canonical(record)

def scope_of(issue,rows,main_sheet,weight_sheet):
    kind=issue.get('kind','');n=issue.get('row')
    if kind.startswith('weight:')or kind=='weight_summary':
        sheet=kind.split(':',1)[1]if ':'in kind else weight_sheet
        return {'domain':'weight','sheet':sheet,'row':n,'row_id':identity(['weight',sheet,n]),'scope':{}}
    if n in rows:
        r=rows[n];return {'domain':'product','sheet':r['sheet'],'row':n,'row_id':r['row_id'],'scope':r['scope']}
    return {'domain':kind or 'unknown','sheet':issue.get('sheet',main_sheet),'row':n,'row_id':identity(['unknown',kind,issue.get('sheet'),n]),'scope':{}}

def classify(pending,product_rows,main_sheet,weight_sheet):
    rows={r['row']:r for r in product_rows};unique={};groups={};links=[]
    for index,issue in enumerate(pending):
        if not isinstance(issue,dict)or not issue.get('code'):raise MvpError('INPUT_INVALID','待核原因缺完整code')
        key=atom(issue);info=scope_of(issue,rows,main_sheet,weight_sheet);t=topic(issue)
        # Unknown reasons keep their full scope and code, rather than disappear
        # into a broad known category. Global groups retain all row identities.
        groupkey=[t,'global']if t in GLOBAL else[t,info['domain'],info['sheet'],info['row_id']]
        if t=='other':groupkey.append(issue['code'])
        gid=identity([SCHEMA,groupkey]);entry=unique.setdefault(key,{'issue':issue,'raw_indices':[],'case_id':gid,'scope':info})
        assert entry['case_id']==gid
        entry['raw_indices'].append(index)
        case=groups.setdefault(gid,{'case_id':gid,'topic':t,'title':QUESTIONS[t][0],'status':'paused'if t in {'material','picture'}else'needs_business_confirmation','question':QUESTIONS[t][1],'required_evidence':QUESTIONS[t][2],'raw_indices':[],'issue_ids':[],'rows':{},'codes':set(),'fields':set()})
        case['raw_indices'].append(index);case['rows'][info['row_id']]=info;case['codes'].add(issue['code']);case['fields'].add(str(issue.get('field')or issue.get('column')or ''))
        links.append({'raw_index':index,'issue_id':identity([SCHEMA,key]),'case_id':gid,'row_id':info['row_id'],'domain':info['domain'],'sheet':info['sheet'],'row':info['row']})
    details=[]
    for key,item in unique.items():
        iid=identity([SCHEMA,key]);groups[item['case_id']]['issue_ids'].append(iid);details.append({'issue_id':iid,**item})
    cases=[]
    for case in groups.values():
        case.update(rows=sorted(case['rows'].values(),key=lambda r:(r['domain'],r['sheet'],str(r['row']))),codes=sorted(case['codes']),fields=sorted(case['fields']),issue_ids=sorted(set(case['issue_ids'])))
        case['affected_rows']=len(case['rows']);case['raw_record_count']=len(case['raw_indices']);cases.append(case)
    cases.sort(key=lambda c:(c['status'],c['topic'],c['case_id']))
    assert len(links)==len(pending)and sorted(i for c in cases for i in c['raw_indices'])==list(range(len(pending)))
    counts=Counter(i['code']for i in pending)
    summary=[{'code':code,'raw_records':count,'unique_exact_records':sum(x['issue']['code']==code for x in details),'case_count':sum(code in c['codes']for c in cases),'affected_product_rows':len({x['scope']['row_id']for x in details if x['issue']['code']==code and x['scope']['domain']=='product'})}for code,count in sorted(counts.items())]
    return {'raw_records':len(pending),'unique_exact_records':len(details),'exact_duplicate_records':len(pending)-len(details),'review_cases':len(cases),'needs_business_confirmation':sum(c['status']=='needs_business_confirmation'for c in cases),'paused_cases':sum(c['status']=='paused'for c in cases),'reason_summary':summary,'cases':cases,'unique_issues':details,'raw_links':links}

def verified_audit(reference,pair_reference):
    if digest(reference['path'])!=reference['sha256']:raise MvpError('SOURCE_CHANGED','验收报告SHA变化')
    audit=load_json(reference['path'])
    if audit.get('schema')!='arrival-pair-acceptance/1'or audit.get('pair_source')!=pair_reference or not audit.get('whole_batch_technical_passed'):
        raise MvpError('INPUT_INVALID','仅承接同版本已保存整批技术验收，不以抽样冒充')
    if audit.get('errors'):raise MvpError('INPUT_INVALID','仍有保全错误，不可当业务待核归并')
    return audit

def write_csv(path,headers,rows):
    with path.open('w',encoding='utf-8-sig',newline='')as f:
        writer=csv.writer(f);writer.writerow(headers);writer.writerows(rows)

def run(request_path,output):
    req=load_json(request_path);out=Path(output).resolve();ref=req['pair_source'];parent_ref=req['parent_pair_source']
    if out.exists():raise MvpError('TASK_CONFLICT','使用新目录，禁止覆盖旧待核结果')
    pair=read_pair_source(ref);parent=load_json(parent_ref['path'])
    if digest(parent_ref['path'])!=parent_ref['sha256']:raise MvpError('SOURCE_CHANGED','父版本SHA变化')
    audit=verified_audit(req['acceptance_report'],ref);old=verified_audit(req['parent_acceptance_report'],parent_ref)
    for key in ['batch_id','reviewed_source','quantity_source','pricing_source','logistics_source']:
        if pair['config'][key]!=parent['config'][key]:raise MvpError('SOURCE_CHANGED','本次仅投影承接，不能混入不同R2/R3版本')
    identities=lambda data:[(r['row_id'],r['sheet'],r['row'],r['scope'])for r in data['rows']]
    if identities(pair)!=identities(parent):raise MvpError('SOURCE_CHANGED','父子出荷行不同')
    protected={str(Path(p).resolve()):digest(p)for p in [request_path,ref['path'],parent_ref['path'],req['acceptance_report']['path'],req['parent_acceptance_report']['path']]}
    for data in [pair,parent]:
        for f in data['files']:protected[f['path']]=digest(f['path'])
    inputs=[Path(p).resolve()for p in protected]
    if any(p.is_relative_to(out)or out.is_relative_to(p.parent)for p in inputs):raise MvpError('CONFIG_INVALID','待核目录须独立于输入及旧任务')
    l=load_json(pair['config']['logistics_source']['path']);weight_sheet=next((g.get('evidence',{}).get('carton',{}).get('sheet')for g in l['groups']if g.get('evidence',{}).get('carton')),None)
    result=classify(audit['pending'],pair['rows'],pair['rows'][0]['sheet'],weight_sheet)
    oldcounts=Counter(atom(i)for i in old['pending']);newcounts=Counter(atom(i)for i in audit['pending'])
    resolved=[{'issue':json.loads(k),'count':count,'state':'resolved_in_projection_as_local_reference_only'}for k,count in sorted((oldcounts-newcounts).items())]
    added=[{'issue':json.loads(k),'count':count}for k,count in sorted((newcounts-oldcounts).items())]
    result.update(schema=SCHEMA,triage_tool_sha256=digest(__file__),pair_source=ref,parent_pair_source=parent_ref,acceptance_report=req['acceptance_report'],parent_acceptance_report=req['parent_acceptance_report'],parent_raw_records=len(old['pending']),resolved_original_records=sum(x['count']for x in resolved),resolved=resolved,added=added,global_question_scope='Display consolidation only; answers must declare exact applicable fields/rows. No implied shared tax rate or quantity unit.',operator_approved=False,professional_approved=False,R4_complete=False,data_ready=False,wps_display='not_performed',material_lookup_resumed=False,image_lookup_resumed=False)
    assert result['parent_raw_records']-result['resolved_original_records']+sum(x['count']for x in added)==result['raw_records']
    out.mkdir(parents=True);save_json(out/'triage.json',result)
    write_csv(out/'原因归类.csv',['原因代码','原因说明','原提示数','精确去重数','关联确认项数','影响商品行数'],[[x['code'],REASON_LABELS.get(x['code'],'未知原因保留'),*[x[k]for k in ['raw_records','unique_exact_records','case_count','affected_product_rows']]]for x in result['reason_summary']])
    business=[]
    for c in result['cases']:
        r=c['rows'][0];scope=r['scope'];business.append([c['case_id'],c['title'],'暂停'if c['status']=='paused'else'待业务确认',c['affected_rows'],r['sheet'],r['row']if c['affected_rows']==1 else'多行，见逐行关联',scope.get('code','')if c['affected_rows']==1 else'',scope.get('ja','')if c['affected_rows']==1 else'',scope.get('specification','')if c['affected_rows']==1 else'',scope.get('qty','')if c['affected_rows']==1 else'',','.join(c['fields']),c['question'],c['raw_record_count'],c['required_evidence'],'',''])
    write_csv(out/'业务确认事项.csv',['确认项ID','原因组','状态','影响行数','工作表','原行','商品编码','日文名','原规格','原Qty','涉及字段','需业务确认','关联提示数','所需证据','业务回复','明确适用行范围'],business)
    write_csv(out/'逐行提示关联.csv',['原提示索引','提示ID','确认项ID','稳定行ID','领域','工作表','原行'],[[x[k]for k in ['raw_index','issue_id','case_id','row_id','domain','sheet','row']]for x in result['raw_links']])
    assert protected=={p:digest(p)for p in protected},'Read-only triage input drift'
    save_json(out/'evidence-manifest.json',{'schema':SCHEMA,'files':{p.name:digest(p)for p in out.iterdir()if p.is_file()},'protected_inputs':protected,'inputs_unchanged':True,'raw_records_all_linked':True})
    print(json.dumps({k:result[k]for k in ['raw_records','unique_exact_records','review_cases','needs_business_confirmation','paused_cases','resolved_original_records']},ensure_ascii=False))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--output',required=True);args=parser.parse_args();run(args.request,args.output)
