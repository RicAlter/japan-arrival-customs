"""P2-A field contract. Excel edits are proposals, never business approvals."""
from openpyxl.utils import get_column_letter
from .core import DOMAINS, digest

SCHEMA='japan-arrival/intermediate-1'
LEVELS={
 'reviewed':'高：已审核且范围一致',
 'reviewed_history':'高：已审历史匹配，本批未确认',
 'observed':'中：来源明确，业务未审',
 'candidate':'候选：未经审核',
 'conflict':'冲突：待单独核实',
 'missing':'缺失：待补充或说明',
 'allowed_absence':'允许空缺：已有原因',
}
DOMAIN_NAMES={'product':'商品基础','identity':'身份版本','price':'金额','material':'材质','packaging':'盒规','tax':'税率'}

def definitions():
    specs=[]
    def add(key,label,domain,kind='text',editable=True,raw=None,choices=None,width=24,rule=None):
        specs.append(dict(key=key,label=label,domain=domain,kind=kind,editable=editable,raw=raw,
            choices=choices or [],width=width,rule=rule or '业务修改提议；回传校验与授权审核前不生效'))
    # Immutable source identity/amounts are visible; source corrections require a new authoritative input.
    add('identity.code','源商品编码','identity',editable=False,raw='code',width=20,rule='保留文本，无码不虚构；禁止用Excel改码解除D06争议')
    add('identity.japanese_name','日文商品名','identity',editable=False,raw='ja',width=48)
    for key,label,raw,width in [('internal_name','内部商品名','internal',54),('customs_name','申报品名',None,30),
            ('category','品类','category',22),('channel','渠道','channel',20),('yd','YD','yd',24),
            ('yd_absence_reason','无YD原因',None,34),('frontend_status','前台记录状态',None,20),
            ('frontend_absence_reason','无前台原因',None,34),('procurement','采购类型',None,24),('internal_note','内部备注',None,48)]:
        add('product.'+key,label,'product',raw=raw,width=width,choices=['exists','absent','unknown'] if key=='frontend_status' else None)
    add('identity.version','确认版本提议','identity',raw='variant',width=32)
    add('identity.specification','确认规格提议','identity',width=32)
    for key,label,kind in [('amount','第3步金额','decimal'),('currency','币种','text'),('quantity','第3步数量','decimal'),
                           ('quantity_unit','当前计价单位','text'),('unit_price_observed','第3步原单价','decimal')]:
        add('authority.'+key,label,'price',kind,False,raw={'quantity':'qty','unit_price_observed':'price'}.get(key,key),
            rule='只读权威源；修改金额/数量/币种须更新第3步文件并建立新版本，不能直接回填覆盖')
    add('proposal.quantity_unit','计价单位提议（待D07）','price',width=28,rule='仅单位提议；须修改输入合同并重新签核，不直接改authority')
    for key,label,kind in [('original','材质完整原文','text'),('translation','材质完整译文提议','text'),
                           ('source','材质核实来源','text'),('completeness_confirmed','成分完整性确认提议','boolean')]:
        add('material.'+key,label,'material',kind,width=38,
            choices=['是','否'] if kind=='boolean' else None)
    for key,label,kind in [('source_unit','采购/计价单位','text'),('declaration_unit','申报单位','text'),('internal_unit','内部数量单位','text'),
        ('declaration_factor','申报换算系数','positive_decimal'),('pieces_per_box','每盒件数','positive_decimal'),
        ('internal_quantity','内部数量','positive_decimal'),('internal_boxes','内部盒数','positive_decimal'),('source','盒规证据来源','text')]:
        add('packaging.'+key,label,'packaging',kind,width=30 if key=='source' else 23)
    for key,label,kind in [('classification','税号/归类','text'),('duty_rate','关税率提议','rate'),('vat_rate','VAT税率提议','rate'),
        ('tax_unit_price','计税单位单价','positive_decimal'),('tax_unit','计税数量单位','text'),('effective_date','税率适用日期','date'),
        ('formula_version','盒装税金公式版本','text'),('source','税率审核来源','text')]:
        add('tax.'+key,label,'tax',kind,width=30,
            choices=['historical-box-v1'] if key=='formula_version' else None)
    return specs

def invalidation(spec):
    """Proposed P2-B dependency contract; no invalidation is applied by P2-A export."""
    domain=spec['domain'];key=spec['key']
    if not spec['editable']:return '禁止覆盖源值；更新权威输入版本'
    if key=='proposal.quantity_unit':return 'D07重新签核后才更新；金额/盒规审核及数量、单价、盒装税金重新核验'
    if domain=='product':return '商品基础审核；'+('税率审核/盒装税金' if key in ('product.category','product.customs_name') else '其他专业审核保留')
    return {'identity':'身份、商品基础、材质、盒规、税率审核；数量/单价/税金重算，原金额值保留',
        'material':'材质审核；其他专业审核保留',
        'packaging':'盒规、税率审核；数量/单价/盒装税金重算，原金额审核保留',
        'tax':'税率审核及盒装税金；商品/材质/盒规/原金额审核保留'}[domain]

def build_contract():
    fields=[]
    def system(key,label,kind='text',width=26):
        fields.append({'key':key,'label':label,'kind':kind,'editable':False,'domain':'system','width':width,
                       'rule':'只读导出快照；不得覆盖、删除或自行生成','role':'system'})
    system('row_id','稳定行ID',width=29)
    # Put the two business identifiers first. All confidence/evidence fields follow each data value.
    specs=definitions();priority=['identity.code','product.internal_name']
    ordered=[next(s for s in specs if s['key']==key) for key in priority]+[s for s in specs if s['key'] not in priority]
    for spec in ordered[:2]:fields.append(dict(spec,role='value',invalidate=invalidation(spec)))
    system('pending_domains','待确认审核域',width=34)
    system('exceptions','异常原因及缺项',width=58)
    for domain,label in [('material','材质组ID'),('packaging','盒规组ID'),('tax','税率组ID')]:system('group.'+domain,label,width=29)
    for spec in ordered:
        if spec['key'] not in priority:fields.append(dict(spec,role='value',invalidate=invalidation(spec)))
        for role,label,width in [('confidence','置信度快照',29),('evidence','来源证据快照',46)]:
            fields.append({'key':role+':'+spec['key'],'label':spec['label']+'｜'+label,'kind':'text','editable':False,
                'domain':spec['domain'],'width':width,'role':role,'field_key':spec['key'],
                'rule':'导出时字段级证据判断；修改后的状态须回传核验，不能由Excel自行变为已审核'})
    for domain in DOMAINS:
        title=DOMAIN_NAMES[domain]
        system('review_status.'+domain,title+'审核状态（快照）',width=28)
        fields[-1]['domain']=domain
        for part,label,width in [('request','审核申请',25),('reviewer','申请审核人',24),('reference','申请凭据',40),('resolution','争议处理说明',44)]:
            fields.append({'key':f'request.{domain}.{part}','label':title+label,'kind':'text','editable':True,
                'domain':domain,'width':width,'role':'request','choices':['保持待确认','申请批量确认','申请单项处理'] if part=='request' else [],
                'rule':'仅人工审核意向；P2-B须核验实际角色/凭据/范围，不能直接覆盖当前确认',
                'invalidate':'填写申请本身不使其他审核失效'})
        system('review_proof.'+domain,title+'已有审核依据（快照）',width=48)
    for key,label,width in [
        ('original_status','日方身份连接状态',34),
        ('original_source_rows','日方原行/候选行',24),('related_source3_rows','同组第3步源行',26),
        ('identity_candidate_method','身份候选依据（非批准）',58),('identity_candidate_snapshot','身份候选完整证据（只读）',72),
        ('original_code','日方原编码/候选',28),('original_quantity','日方原数量/候选',28),('original_amount','日方原金额/候选（非计价基准）',36),
        ('historical_material','历史材质候选（未审）',38),('historical_pack','历史盒装数候选（未审）',28),
        ('historical_pieces','历史每盒件数候选（未审）',28),('historical_rate','历史关税率候选（未审）',28),
        ('historical_vat_amount','历史VAT金额（非税率）',32),('carton','箱号',20),('origin','产地',16),('weight_groups','箱重组ID（见箱重资料）',36),
        ('declaration_quantity','申报数量计算快照',28),('exact_price','申报单价精确比快照',30),('box_tax','盒装税金计算快照',30),
        ('batch_id','批次ID',29),('data_revision','数据版本',16),('batch_hash','基准明细SHA256',68),
        ('row_hash','基准行SHA256',68),('source_row','第3步源行',18),('source_record_id','来源记录ID',40),
        ('source_version','来源版本SHA256',68),('native_record_id','飞书原生记录ID（尚未接入）',32),
        ('source_link','来源链接（尚无则空）',46),('source_queried_at','来源查询时间（尚无则空）',32),
        ('row_snapshot','完整原记录及审核快照（只读）',72)]:system(key,label,width=width)
    for i,f in enumerate(fields,1):f['column']=get_column_letter(i)
    value={'schema':SCHEMA,'sheet':'统一主明细','header_row':6,'first_data_row':7,'row_id_key':'row_id',
        'fields':fields,'confidence_levels':LEVELS,'automatic_approval':False,'return_import_implemented':False,
        'locking_implemented':False,'formal_output_enabled':False,
        'sources':{'record_id':'Excel:sheet!row; Feishu native record ID reserved, never invented',
            'version':'local file SHA256; native revision reserved','link':'only original supplied link; missing stays null',
            'queried_at':'only actual source query timestamp; local export time is not Feishu query time'},
        'authority_policy':{'price':'第3步业务确认源；禁止其他来源覆盖',
            'product':'业务基础资料审核结果；飞书为主要候选来源，本地可补充，冲突不得静默覆盖',
            'material':'已审核且同身份/版本/规格历史优先；未经审核仅候选',
            'packaging_tax_identity':'实际有权限审核人及适用范围证据；不得由候选/相似商品自动决定'}}
    value['contract_hash']=digest(value)
    return value
