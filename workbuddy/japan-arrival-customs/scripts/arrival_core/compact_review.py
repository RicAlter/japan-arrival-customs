"""Exception-first business view. Export only: no review/import/identity decisions.

Navigation groups are deliberately separate from the existing approval packages.
All original state, field evidence and immutable row IDs remain in the sidecar.
"""
import copy
import hashlib
import json
import os
import tempfile
from collections import defaultdict, Counter
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from . import _p0_frozen as p0
from .batchflow import serial
from .business_review import identity_checklist
from .core import Rejected, context, digest, review_package, validate, reconcile_amounts, product_disputes
from .drafts import private_tokens
from .excel_writer import save_exact, sheet
from .group_review import group_package
from .storage import Store, atomic_json, check_sources

FILENAME = 'KMT_业务审核_精简版.xlsx'
PROFILE = 'exception-first-v1'
SHEETS = ['处理总览', '待处理问题', '完整商品明细']
CHOICES = '采用候选,补充资料,拆分范围,保留待确认,不适用并说明'


def text(value):
    return p0.text(value) if p0.good(value) else ''


def material_catalog(path):
    """Historical query text is not original Japanese composition or a live lookup."""
    if not path:
        return {'path':None,'sha256':None,'stage':2,'index':{},'records':0,
                'status':'not_provided','notice':'未提供历史材质资料；不创建空文件，不生成虚假候选'}
    path = Path(path).resolve(); data = path.read_bytes()
    book = p0.Book(data, str(path)); records = p0.records(book, 2)
    index = defaultdict(list)
    for record in records:
        key = tuple(text(record.get(k)) for k in ('code', 'ja', 'variant'))
        index[key].append(serial(record))
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
            'stage': 2, 'index': dict(index), 'records': len(records)}


def material_candidate(row, catalog):
    key = tuple(text(row['identity'].get(k)) for k in ('code', 'japanese_name', 'version'))
    records = catalog['index'].get(key, [])
    observations = {tuple(text(r.get(k)) for k in ('material', 'search_material', 'url', 'site')) for r in records}
    unique = len(observations) == 1
    first = records[0] if unique else {}
    history = row.get('historical', {}).get('internal_reference', {}).get('record') or {}
    current = text(row['material']['candidate'])
    queried = text(first.get('search_material'))
    return {'business': current, 'history6': text(history.get('material')),
            'query': queried, 'query_url': text(first.get('url')), 'site': text(first.get('site')),
            'match': 'exact_unreviewed' if unique else 'ambiguous' if records else 'missing',
            'text_difference': bool(queried and queried != current),
            'evidence': records, 'review_status': 'candidate_only',
            'original_composition_verified': False}


def prepare_candidates(batch, catalog):
    validate(batch)
    prepared = copy.deepcopy(batch); prepared['product_review_profile'] = PROFILE
    observations = {}; tokens = private_tokens(batch)
    for row in prepared['rows']:
        history = row.get('historical', {})
        customs = history.get('customs_reference', {})
        internal = history.get('internal_reference', {})
        h = customs.get('record') or {}; i = internal.get('record') or {}
        candidate = text(h.get('customs_name'))
        # Stage5 has no version column. Require its unique same-code/carton alignment
        # AND matching Stage6 variant/name as corroboration; never resolve source1 disputes.
        aligned = (customs.get('match') == internal.get('match') == 'unique'
                   and text(h.get('code')) == text(row['identity']['code'])
                   and text(i.get('code')) == text(row['identity']['code'])
                   and p0.expand(h.get('carton')) == p0.expand(row['logistics']['carton_raw'])
                   and bool(text(row['identity']['version']))
                   and text(i.get('variant')) == text(row['identity']['version'])
                   and text(i.get('ja')) == text(row['identity']['japanese_name'])
                   and text(i.get('internal')) == text(row['product']['internal_name']))
        safe = bool(candidate) and not any(t in candidate for t in tokens)
        use = bool(aligned and safe and not row['product']['customs_name'] and not row['reviews']['product'])
        if use: row['product']['customs_name'] = candidate
        observations[row['id']] = {
            'customs_name': {'prefilled': use, 'value': candidate if aligned and safe else None,
                'level': '历史精确对齐候选（未审核）' if aligned and safe else '来源不足或冲突',
                'evidence': h, 'version_corroboration': i,
                'current_product_review': row['reviews']['product']},
            'material': material_candidate(row, catalog)}
    validate(prepared)
    return prepared, observations


def build_plan(batch, catalog):
    prepared, observations = prepare_candidates(batch, catalog)
    package = review_package(prepared)
    rows = batch['rows']; by_id = {r['id']: r for r in rows}
    ordinals = {r['id']: n for n, r in enumerate(rows, 1)}
    issues = []
    def add(domain, ids, subject, candidate, reason, needed, *, priority='本票需处理', grouping=None):
        ids = sorted(set(ids), key=ordinals.__getitem__)
        issue_id = 'Q' + str(len(issues) + 1).zfill(3)
        issues.append({'id': issue_id, 'domain': domain, 'row_ids': ids, 'subject': subject,
            'candidate': candidate, 'reason': reason, 'needed': needed, 'priority': priority,
            'navigation_group_only': True, 'group_key': grouping,
            'contexts': {rid: context(by_id[rid]) for rid in ids}})
    all_ids = list(by_id)
    proposed = {r['id']: text((r.get('historical',{}).get('customs_reference',{}).get('record') or {}).get('amount'))
                or r['authority']['amount'] for r in rows}
    amount_check = reconcile_amounts(rows, proposed)
    changed_amount_ids = [r['id'] for r in amount_check['lines'] if r['delta'] != '0']
    raw=batch.get('input_mode')=='raw_invoice_preliminary'
    amount_label='日方原表Subtotal初步到货金额' if raw else '第3步业务金额'
    add('contract', all_ids, '首票单位及输入签核（D07）', f'币种JPY、重量KG来自表头；{amount_label}原值保留',
        ('原始Qty最大到货单位及混合单位例外未从开定/采购资料确认' if raw else '日方采购单位、第3步计价单位及混合单位例外未签核'),
        '采购/金额负责人给出单位及适用范围、例外行；签核文件版本与记录号')
    if batch.get('product_data_policy') != 'single-person-v1':
        add('responsibilities', all_ids, '审核责任（D08）', '基础资料、身份、金额、材质、盒规、关务、物流、放行八类职责',
            '专业批准需对应有效职责，同一可信人员可兼任；不让业务逐行填写审核人',
            '管理员配置实际职责及代理范围；Excel不能提供执行者身份')
    add('release', all_ids, '海关外发白名单（D05）', '正式输出继续关闭',
        '对外字段及品牌来源尚未批准，不阻止基础资料候选核对',
        '关务/业务批准允许字段、来源与格式', priority='正式输出前处理')
    add('price', changed_amount_ids or all_ids, '金额确认节点与尾差规则（D01）',
        ((f"日方原表Subtotal原样保留为初步到货金额；最终申报金额尚未确认" if raw else f"第3步金额原样保留；历史第5步金额有{len(changed_amount_ids)}行不同，不自动采用")),
        f"历史整批差额{amount_check['batch_delta']}不代表逐商品通过；尚无获批尾差算法",
        ('在本页填写最终金额=...；币种=JPY；计价数量=...；计价单位=...；原因=...；依据=...，明确范围；金额角色预览后确认，不自动调尾差'
         if raw else '关务/财务批准精度、顺序、范围；无差额行无需逐行填尾差规则'), priority='金额确认及差额时处理')
    # Reuse the exact P1-C identity investigation; display grouping never executes mapping.
    identity = identity_checklist(batch)
    identity_ids = {r['id'] for r in identity['rows']}
    groups = defaultdict(list)
    for item in identity['rows']: groups[item['decision_group']].append(item)
    for key, members in groups.items():
        candidates = members[0]['original_candidates']
        lines = [f"原表行{r['row']} 编码{text(r.get('code'))} {text(r.get('variant'))} 数量{text(r.get('qty'))}\n日文名：{text(r.get('ja'))}"
                 for r in candidates]
        add('identity', [r['id'] for r in members], members[0]['issue'], '\n'.join(lines) or '无可靠连接候选',
            '；'.join(sorted({m['candidate_method'] for m in members})) +
            ('；原始日方发票商品尚未与开定/商品档案闭合' if raw else '；日方原表与第3步身份未闭合'),
            '核定映射、改码/拆分依据及各行版本规格；不同版本分别核对。D06未批准不执行改码', grouping=key)
    no_yd = ([] if batch.get('product_data_policy') == 'single-person-v1' else
             [r['id'] for r in rows if not r['product']['yd'] and not r['product']['yd_absence_reason']])
    if no_yd:
        add('product', no_yd, 'YD空缺原因（允许无YD）', '保留空白，不生成编码；无需填写前台记录状态',
            '缺少无YD的实际业务原因，并非认定商品不合法',
            '相同原因可明确范围一次说明；不同原因分组或按商品序号补充，不能默认全部是代购')
    # Only unresolved product fields outside the common no-YD issue receive extra tasks.
    for row in prepared['rows']:
        missing = [k for k in ('internal_name', 'customs_name', 'category') if not row['product'][k]]
        if missing:
            add('product', [row['id']], '基础资料候选缺失', '未强行采用内部名称作申报名',
                '、'.join(missing), '仅补充缺失字段及来源')
        if product_disputes(row) and row['id'] not in identity_ids:
            add('product', [row['id']], '商品基础资料争议', '现有字段保留，未擅自选择',
                '；'.join(d.get('reason') or d['id'] for d in product_disputes(row)),
                '仅核实所列争议及依据，不通过专业审核替代商品审核')
    material_groups = defaultdict(list)
    for row in rows:
        if row['reviews']['material']: continue
        m = observations[row['id']]['material']
        # Never coalesce ambiguous observations as a common fact. Full per-row evidence
        # and exact scopes survive; URLs differ within a text navigation group.
        key = (m['business'], m['history6'], m['query'], m['match'],
               row['id'] if raw and m['match'] != 'exact_unreviewed' else '')
        material_groups[key].append(row['id'])
    for key, ids in material_groups.items():
        business, old, queried, match, _ = key
        candidate = '本批填写：' + (business or '缺失') + '\n历史内部：' + (old or '缺失')
        if queried: candidate += '\n历史查询：' + queried
        reason = ('历史填写与查询文本不同，需核实完整组成；' if queried and queried != business else '')
        reason += '未提供已审核历史证明/原文完整组成；' + ('历史查询仅候选' if match == 'exact_unreviewed' else '历史查询缺失或多义')
        add('material', ids, '材质与证据范围', candidate, reason,
            '材质审核人核实完整原文及译文，提供证据；仅批准证据覆盖且版本/规格一致的所选商品', grouping=digest(key))
    for domain, title in [('packaging', '盒规与单位换算'), ('tax', '税率及盒装税金口径')]:
        for group in group_package(batch, domain)['groups']:
            o = group['observations']; ids = [r['id'] for r in group['rows']]
            if domain == 'packaging':
                candidate = f"品类：{o['category']}；历史每盒件数：{o['historical_pieces'] or '未记录'}"
                reason = '历史盒规未经审核；计价单位、版本/规格和包装证据未确认'
                needed = '确认采购/内部/申报单位、每盒件数、换算系数及适用范围；数量盒数逐行计算，不由“全N种”猜测'
            else:
                candidate = f"品类：{o['category']}；历史税率：{o['historical_rate'] or '未记录'}（不自动采用）"
                reason = '历史税率不等于当前有效口径；税号、适用日、税基单位等尚未审核'
                needed = '关务确认税号、关税/增值税、适用日期、税基单位和证据；只复现盒装税金'
            add(domain, ids, title, candidate, reason, needed, grouping=group['id'])
    membership = defaultdict(list)
    for issue in issues:
        for rid in issue['row_ids']: membership[rid].append(issue['id'])
    stats = {'product_rows': len(rows), 'issue_groups': len(issues),
        'issue_groups_by_domain': dict(Counter(i['domain'] for i in issues)),
        'ordinary_product_candidates': len(package['ordinary_ids']),
        'individual_product_rows': len(package['individual_ids']),
        'identity_rows': identity['pending_rows'], 'identity_groups': identity['decision_groups'],
        'yd_reason_rows': len(no_yd),
        'customs_name_prefilled': sum(o['customs_name']['prefilled'] for o in observations.values()),
        'material_query_matched_rows': sum(o['material']['match'] == 'exact_unreviewed' for o in observations.values()),
        'material_query_with_url_rows': sum(bool(o['material']['query_url']) for o in observations.values()),
        'material_query_text_difference_rows': sum(o['material']['text_difference'] for o in observations.values()),
        'actual_product_reviews': sum(bool(r['reviews']['product']) for r in rows),
        'new_reviews_created': 0, 'frontend_manual_fields': 0, 'review_request_fields': 0,
        'editable_columns': 2, 'editable_cell_capacity': 2 * len(issues),
        'authority_amount': str(sum((Decimal(r['authority']['amount']) for r in rows if r['authority']['amount']),Decimal(0))),
        'amount_label':amount_label,'amount_status':'preliminary_not_final' if raw else 'legacy_stage3_business_source',
        'material_history_records':catalog['records']}
    stats['historical_amount_changed_rows'] = len(changed_amount_ids)
    stats['historical_batch_amount_delta'] = amount_check['batch_delta']
    return {'schema': 'japan-arrival/compact-review-1', 'batch_id': batch['id'], 'revision': batch['revision'],
        'base_hash': digest(batch), 'candidate_hash': digest(prepared), 'profile': PROFILE,
        'return_import_implemented': False, 'automatic_approval': False, 'formal_output_enabled': False,
        'source_catalog': {k: v for k, v in catalog.items() if k != 'index'},
        'stats': stats, 'issues': issues, 'ordinary_candidate_ids': package['ordinary_ids'],
        'ordinals': ordinals, 'memberships': dict(membership), 'observations': observations,
        'historical_amount_check': amount_check, 'base_snapshot': batch, 'candidate_snapshot': prepared}


def validate_navigation_scope(batch, plan, issue_id, row_ids):
    """Read-only guard usable by B2 later; NOT an approval endpoint."""
    if digest(batch) != plan['base_hash']: raise Rejected('审核视图已过期')
    issue = next((i for i in plan['issues'] if i['id'] == issue_id), None)
    if not issue or not row_ids or len(row_ids) != len(set(row_ids)) or set(row_ids) - set(issue['row_ids']):
        raise Rejected('问题范围外或重复商品，拒绝扩展')
    by_id = {r['id']: r for r in batch['rows']}
    for rid in row_ids:
        if context(by_id[rid]) != issue['contexts'][rid]: raise Rejected('版本/规格范围已变化')
    return {'navigation_only': True, 'row_ids': list(row_ids), 'approval_allowed': False}


def _write(plan, target):
    b = plan['candidate_snapshot']; s = plan['stats']; ordinals = plan['ordinals']
    by_id = {r['id']: r for r in b['rows']}
    wb = Workbook(); wb.remove(wb.active)
    warning = '仅供内部审核；填写不等于批准。本阶段不导入修改、不签核、不生成正式报单。'
    raw=b.get('input_mode')=='raw_invoice_preliminary'
    basis = ('本批直接来自日方原始发票及同工作簿箱重页；历史/开定资料未提供时保持待补。原件只读。'
             if raw else '本批来源：第2步材质查询记录、第3步业务确认资料、第5步海关历史、第6步内部历史；均保留原件。')
    overview = [
        ['先做什么', '普通商品基础资料', s['ordinary_product_candidates'], '行候选可选一次批量确认',
         '名称/品类/YD/渠道预填，申报名来自历史；专业审核独立，不要求前台状态。D08可信身份到位后由Skill记录明确范围。'],
        ['再看什么', '待处理问题', s['issue_groups'], '组（范围可能重叠）', '点击下方“待处理问题”；只处理必要决策；无修改可由Skill接收明确操作和范围，无需逐行填申请。'],
        ['身份异常', '改码/拆分', s['identity_rows'], f"行 / {s['identity_groups']}组", '需要真实映射及版本证据；不执行推测改码。'],
        ['内部参考', 'YD为可选内部编码' if b.get('product_data_policy') == 'single-person-v1' else 'YD空缺原因',
         s['yd_reason_rows'], '需处理行', 'YD空缺无需补齐，不作为异常或阻塞项。' if b.get('product_data_policy') == 'single-person-v1' else '相同实际原因可合并说明；保留YD空白，不补前台状态。'],
        ['已经预填', '申报品名候选', s['customs_name_prefilled'], '行', '历史第5步C列；第6步版本/内部名交叉对齐。未冒充已审核，不使用内部名替代。'],
        ['证据有限', '历史材质查询网址', s['material_query_with_url_rows'], '行', '网址为旧查询记录，未访问或验证当前页面；文本不同不等于已证明实质冲突。'],
        ['专业审核', '材质 / 盒规 / 税率', f"{s['issue_groups_by_domain'].get('material',0)} / {s['issue_groups_by_domain'].get('packaging',0)} / {s['issue_groups_by_domain'].get('tax',0)}", '导航组',
         '相同文本仅便于集中看；证据须覆盖所选商品版本/规格，不保证一组一个批准动作。'],
        ['到货金额', s['amount_label']+'合计', float(Decimal(s['authority_amount'])), 'JPY', '原始Subtotal不改；这不是最终申报金额批准。逐商品差异不得互相抵消，尾差算法待批准。'],
        ['当前状态', '本次自动批准', 0, '项', '全部保留待审核。本表不要求2688行×六域逐行点击；也不把缺证据事项隐藏。'],
        ['安全门禁', '正式输出', '关闭', 'D05尚未批准', '单位、责任、身份及专业证据均按原门禁核验。'],
        ['重复到货', '未来审核知识复用', '有条件减少', '尚未实施P2-D', '同身份/版本/包装且凭据有效时可减少查名、抄材质、重复找证据；单位数量金额物流仍须核对，盒规免审规则未批准。'],
        ['填写方法', '仅待处理问题两列可填', '处理选择 + 必要修改或依据', '不填审核人', '有改动才填必要字段；既有候选无需重抄。执行身份来自可信环境。B2待本表验收后实施。'],
    ]
    ws = sheet(wb, SHEETS[0], 'KMT｜先看异常，再确认普通项', ['顺序/主题','内容','数量/状态','范围','需要的动作'],
        overview, [16,24,29,30,86], warning=warning, basis=basis,
        summary=f"{s['product_rows']}商品行 · {s['issue_groups']}问题导航组 · 普通基础资料{s['ordinary_product_candidates']}行可批量核对")
    ws.freeze_panes = 'A7'; ws.sheet_view.zoomScale = 85
    ws['B8'].hyperlink = "#'待处理问题'!A6"; ws['B8'].style = 'Hyperlink'
    issue_rows = []
    for i in plan['issues']:
        ids = i['row_ids']; samples = ids[:2]
        sample = '\n'.join(f"{ordinals[rid]:04d}｜{by_id[rid]['identity']['code']}｜{(by_id[rid]['product']['internal_name'].splitlines() or ['待补中文名'])[0]}" for rid in samples)
        if i['domain']=='identity':
            sample = '\n'.join(f"{ordinals[rid]:04d}｜本批编码{by_id[rid]['identity']['code']}\n"
                f"描述：{by_id[rid]['identity']['version']}；数量{by_id[rid]['authority']['quantity']}（单位待签）\n"
                f"日文名：{by_id[rid]['identity']['japanese_name']}" for rid in ids)
        if len(ids) > 2: sample += f"\n另{len(ids)-2}行；点查看或在明细‘相关问题’筛选{i['id']}"
        if i['domain'] in ('contract','responsibilities','release'):
            sample = '全批共同事项，一次明确适用范围；不需逐行填写。'
        issue_rows.append([i['id']+'｜'+i['subject']+'\n'+i['priority'],
            f"共{len(ids)}行（点击查看）\n"+sample, i['candidate'], i['reason'], i['needed'], None, None])
    issues_ws = sheet(wb,SHEETS[1], '只处理需要决定的内容',
        ['需要决定的问题','商品范围（可点击）','已有候选（未审核）','为什么需要决定','最少需要补充','处理选择','必要修改或依据'],
        issue_rows,[27,43,43,43,49,22,48], warning=warning,
        basis='同文字分组仅用于导航；批准时必须明确行范围、版本、规格和凭据覆盖。不同结论请拆分范围。',
        summary='仅浅黄色两列供记录必要修改；可直接向Skill明确操作与范围，不需填写24个申请栏。当前不接收回传。',inputs=(6,7))
    issues_ws.freeze_panes = 'C7'; issues_ws.sheet_view.zoomScale = 80
    dv=DataValidation(type='list',formula1='"'+CHOICES+'"',allow_blank=True)
    dv.errorTitle='请选择处理方式'; dv.error='不确定时请选择保留待确认'; dv.showErrorMessage=True
    issues_ws.add_data_validation(dv); dv.add(f'F7:F{6+len(issue_rows)}')
    for n,i in enumerate(plan['issues'],7):
        issues_ws.cell(n,2).hyperlink = f"#'完整商品明细'!A{6+ordinals[i['row_ids'][0]]}"
        issues_ws.cell(n,2).font=Font(name='Arial',size=10,color='1267A6',underline='single')
    ordinary = set(plan['ordinary_candidate_ids']); detail=[]
    for r in b['rows']:
        rid=r['id']; o=plan['observations'][rid]; m=o['material']
        h=r.get('historical',{}).get('internal_reference',{}).get('record') or {}
        detail.append([ordinals[rid], '基础资料已确认（保留）' if r['reviews']['product'] else '基础资料可批量核对' if rid in ordinary else '基础资料有待处理项',
            r['logistics']['carton_raw'], r['identity']['code'], r['product']['internal_name'],
            r['product']['customs_name'], r['product']['category'], r['product']['yd'] or '（无YD，保留空白）',
            r['product']['channel'], r['identity']['version'], m['business'], m['query'],
            text(h.get('pieces')), text(h.get('rate')), r['authority']['quantity'], float(Decimal(r['authority']['amount'])),
            f"第5步 {o['customs_name']['evidence'].get('sheet','')} C{o['customs_name']['evidence'].get('row','')}（候选）" if o['customs_name']['value'] else o['customs_name']['level'],
            m['query_url'], ' '.join(plan['memberships'].get(rid,[]))])
    ws = sheet(wb,SHEETS[2], '完整商品明细｜查看与筛选',
        ['本表序号','基础资料处理方式','箱号','商品编码','内部商品名（本批候选）','申报品名候选','品类','YD（允许空缺）','渠道',
         '本批版本/包装描述','本批材质填写','历史查询材质（未验证）','历史每盒件数（未审）','历史税率（未审）',
         '原始到货Qty（单位待查）' if raw else '第3步数量（单位待签）',
         '原始Subtotal JPY（初步）' if raw else '第3步金额JPY','申报名来源','历史材质查询网址','相关问题'],
        detail,[10,23,14,20,64,36,16,24,18,26,26,36,18,18,20,23,30,48,39], warning=warning,
        basis=basis,summary='此页以查看为主；修改仅填问题页必要内容。序号只在本导出版导航，底层稳定行ID和版本映射另行保存。')
    ws.sheet_view.zoomScale=75
    for n in range(7,7+len(detail)): ws.cell(n,16).number_format='#,##0.00'
    # At standard desktop zoom the business viewport starts with 4 frozen identity columns.
    # No formula-dependent cells: edits are notes, calculations update only in the future import.
    for tab in wb:
        tab.sheet_properties.outlinePr.summaryRight=False
        for ri in (2,3,4,5):
            tab.merge_cells(start_row=ri,start_column=1,end_row=ri,end_column=tab.max_column)
            tab.cell(ri,1).alignment=Alignment(wrap_text=True,vertical='center')
            tab.row_dimensions[ri].height=32 if ri != 2 else 28
    save_exact(wb,target); wb.close()


def verify_workbook(path, plan):
    wb=load_workbook(path,data_only=False)
    try:
        if wb.sheetnames != SHEETS: raise Rejected('审核工作簿页签不一致')
        detail=wb[SHEETS[2]]; questions=wb[SHEETS[1]]
        if detail.max_row-6 != plan['stats']['product_rows'] or questions.max_row-6 != len(plan['issues']):
            raise Rejected('商品或问题范围不一致')
        for ws in wb:
            if any(c.data_type=='f' for row in ws for c in row): raise Rejected('业务审核表不应包含可执行公式')
        total=Decimal(0)
        for n,r in enumerate(plan['candidate_snapshot']['rows'],7):
            expected=[r['identity']['code'],r['product']['internal_name'],r['product']['customs_name'],
                      r['product']['category'],r['product']['channel'],r['identity']['version']]
            values=[detail.cell(n,c).value or '' for c in (4,5,6,7,9,10)]
            if values!=expected or detail.cell(n,15).value!=r['authority']['quantity']:
                raise Rejected('回读商品内容不一致')
            amount=Decimal(str(detail.cell(n,16).value))
            if amount!=Decimal(r['authority']['amount']): raise Rejected('逐商品金额不一致')
            total+=amount
        if total!=Decimal(plan['stats']['authority_amount']): raise Rejected('金额合计不一致')
        editable=[c.coordinate for row in questions.iter_rows(min_row=7) for c in row if not c.protection.locked]
        if len(editable)!=2*len(plan['issues']): raise Rejected('可填写范围不一致')
        for n,issue in enumerate(plan['issues'],7):
            if not questions.cell(n,1).value.startswith(issue['id']+'｜') or not questions.cell(n,2).value.startswith('共'+str(len(issue['row_ids']))+'行'):
                raise Rejected('问题映射不一致')
        return {'sheets':wb.sheetnames,'product_rows':detail.max_row-6,'issue_groups':questions.max_row-6,
                'amount_per_product_verified':True,'amount_total':str(total),'editable_cells':len(editable),
                'no_executable_formulas':True,'no_reviews_written':True,'return_import_implemented':False}
    finally: wb.close()


def export_compact(batch, material_history, directory):
    check_sources(batch); before=digest(batch)
    catalog=material_catalog(material_history)
    target=Path(directory).resolve(); Store(target).guard(batch)
    history=Path(catalog['path']) if catalog.get('path') else None
    if history and (target.is_relative_to(history.parent) or history.is_relative_to(target)):
        raise Rejected('输出目录必须与材质源文件目录分离')
    if target.exists(): raise Rejected('拒绝覆盖已有业务审核文件，请选择新目录')
    target.parent.mkdir(parents=True,exist_ok=True)
    plan=build_plan(batch,catalog)
    with tempfile.TemporaryDirectory(prefix='.compact-',dir=target.parent) as tmp:
        folder=Path(tmp); file=folder/FILENAME
        _write(plan,file); verification=verify_workbook(file,plan)
        atomic_json(folder/'review_plan.json',plan)
        manifest={'schema':plan['schema'],'base_hash':before,'candidate_hash':plan['candidate_hash'],
            'workbook_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'stats':plan['stats'],
            'verification':verification,'business_state_modified':False,'WorkBuddy':'not_run',
            'note':'Excel中的文字选择不构成审核批准；B2尚未实施，可信操作者身份不从表格取得。'}
        atomic_json(folder/'export_manifest.json',manifest)
        check_sources(batch)
        if ((history and hashlib.sha256(history.read_bytes()).hexdigest()!=catalog['sha256']) or digest(batch)!=before):
            raise Rejected('导出过程中输入或批次发生变化')
        os.replace(folder,target)
    return dict(manifest,directory=str(target),workbook=str(target/FILENAME))
