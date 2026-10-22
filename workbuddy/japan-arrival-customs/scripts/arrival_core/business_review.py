"""Business-facing evidence lists. No candidate mapping is executed here."""
from collections import Counter
from . import _p0_frozen as p0
from .batchflow import read_stage, serial
from .core import digest, validate
from .storage import check_sources

def identity_checklist(batch):
    from .business_setup import require_contract
    require_contract(batch)
    validate(batch);check_sources(batch)
    source=batch['input_contract']['sources']['invoice']
    _,originals=read_stage(source['path'],1)
    unassigned=set(batch['original_input_summary']['unassigned_original_rows'])
    result=[]
    for row in batch['rows']:
        purchase=row.get('original_purchase',{})
        if purchase.get('status')!='identity_pending':continue
        candidates=purchase.get('candidates',[])
        method='同日文名且箱号相交的未审候选'
        if not candidates:
            candidates=[serial(r) for r in originals if r['row'] in unassigned
                        and set(p0.expand(r.get('carton')) or []) & set(p0.expand(row['logistics']['carton_raw']) or [])]
            method='仅箱号相交的未分配原表候选，名称/版本可能不同，禁止自动连接'
        candidates=sorted(candidates,key=lambda r:int(r['row']))
        key=digest({'source':source['sha256'],'rows':[r['row'] for r in candidates],
                    'unmatched':row['id'] if not candidates else None})[:16]
        result.append({'decision_group':key,'id':row['id'],'authority_source':row['source'],
            'current_code':row['identity']['code'],'japanese_name':row['identity']['japanese_name'],
            'version_observed':row['identity']['version'],'internal_name':row['product']['internal_name'],
            'carton':row['logistics']['carton_raw'],'authority_quantity':row['authority']['quantity'],
            'authority_amount':row['authority']['amount'],'unit':row['authority']['quantity_unit'] or None,
            'candidate_method':method,'original_candidates':candidates,'decision':None,'reviewer':None,
            'evidence':None,'confirmed_version':None,'confirmed_specification':None,'confirmed_at':None})
    counts=Counter(r['decision_group'] for r in result)
    for row in result:
        row['related_authority_rows']=[r['authority_source']['row'] for r in result if r['decision_group']==row['decision_group']]
        row['issue']='原表一行对应多行/版本拆分候选' if counts[row['decision_group']]>1 else '改码或身份不一致候选'
    return {'schema':'japan-arrival/identity-checklist-1','state_hash':digest(batch),'batch_id':batch['id'],
            'rows':result,'pending_rows':len(result),'decision_groups':len(counts),'automatic_links_created':0,
            'notice':'填写清单仅收集人工判断；D06身份映射合同未批准，不能据此自动改码或解除原表身份争议。'}

def input_decisions(batch):
    from .business_setup import require_contract
    contract=require_contract(batch);rows=[]
    def add(key,scope,observed,action,owner,impact):
        rows.append([key,scope,observed,action,owner,impact,None,None,None,None])
    add('D07-01','日方采购单位',contract.get('invoice_quantity_unit'),
        '明确原始Qty是件/盒/套及适用行范围，不由名称或价格推断','采购/日本对接负责人（待指定）','影响原始数量核对')
    add('D07-02',f'第3步 {len(batch["rows"])} 行计价单位',contract.get('authority_quantity_unit'),
        '提供统一单位适用范围；混合单位按源行区间/逐行列出例外','业务金额确认人（待指定）','影响价格审核和盒规换算')
    add('D07-03','币种JPY、重量KG','文件表头观测，尚无业务签核',
        '确认本票采用的币种、重量单位及源文件SHA版本','业务签核人（待指定）','表头观测不替代签核')
    names={'business':'商品基础资料','identity':'改码/版本/拆分','amount':'第3步金额','material':'材质及历史审核范围',
           'packaging':'盒规换算','customs':'税号税率与公式适用性','logistics':'箱号/总重','release':'最终放行'}
    for role,title in names.items():
        add('D08-'+role,title,'、'.join(contract['responsibilities'].get(role) or []) or None,
            '指定实际审核人和代理范围；同步管理员维护的角色权限配置','业务负责人','未分配仅限制对应审核域')
    add('D07-签核','首票输入合同',None,'对明确的源版本、单位及责任范围签核；留附件/记录号、日期和确认人',
        '业务负责人/合同管理员（待指定）','已分配business角色并完成合同签核后可先审核基础资料，其余域继续待确认')
    add('D05','正式海关字段白名单',None,'批准字段、来源、字段含义及格式；尤其品牌与渠道隔离','关务/业务负责人','正式输出保持关闭，草稿可继续')
    add('D01','单价尾差规则',None,'明确精度、顺序、允许范围及失败处理','关务/财务负责人','未批准不自动调价；精确金额仍可核对')
    return rows
