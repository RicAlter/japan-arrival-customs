"""Explicit, state-bound professional group review; candidates never imply approval."""
import copy
from collections import defaultdict

from .core import (Rejected, _apply_domain_row, box_tax, changed, context, digest, now, require_actor, validate)
from .contracts import effective_permissions

ROLES = {'identity':'identity', 'material':'material', 'packaging':'packaging', 'tax':'customs'}

def observation(row, domain):
    historical=row.get('historical',{})
    internal=(historical.get('internal_reference',{}).get('record') or {})
    customs=(historical.get('customs_reference',{}).get('record') or {})
    if domain=='material':
        return {'candidate':row['material']['candidate'], 'history':internal.get('material'),
                'source_hash':row['source']['sha256']}
    if domain=='packaging':
        return {'source_unit':row['authority']['quantity_unit'],'category':row['product']['category'],
                'historical_pieces':internal.get('pieces'), 'source_hash':row['source']['sha256']}
    if domain=='tax':
        return {'historical_rate':internal.get('rate'),'category':row['product']['category'],
                'currency':row['authority']['currency'], 'source_hash':row['source']['sha256']}
    return {'version_observed':row['identity']['version'], 'japanese_name':row['identity']['japanese_name']}

def blockers(row, domain):
    result=[]
    if not row['identity']['code']: result.append('商品无码，须单独核实身份范围')
    if domain!='identity' and not row['reviews']['identity']: result.append('商品版本/规格尚未确认')
    result += [d.get('reason') or d['id'] for d in row['disputes'] if d.get('domain') in ('identity',domain)]
    if domain=='packaging' and not row['authority']['quantity_unit']: result.append('第3步计价单位待确认')
    return result

def group_package(batch, domain):
    validate(batch)
    if domain not in ROLES: raise Rejected('不支持的成组审核域')
    groups={};contexts=defaultdict(set)
    for row in batch['rows']:
        if row['reviews'][domain]: continue
        scope={'context':context(row),'observations':observation(row,domain)}
        # Cross-product groups are only a presentation convenience. Approval requires explicit
        # coverage of every displayed context, plus row-specific context and financial bases.
        key=digest(scope if domain=='identity' else scope['observations'])[:24]
        contexts[digest(context(row))].add(digest(scope['observations']))
        group=groups.setdefault(key,{'id':key,**scope,'contexts':[],'eligible_ids':[],'exceptions':[], 'rows':[]})
        if context(row) not in group['contexts']:group['contexts'].append(context(row))
        reasons=blockers(row,domain)
        group['rows'].append({'id':row['id'],'source_row':row['source']['row'],
            'carton':row['logistics']['carton_raw'],'quantity':row['authority']['quantity'],
            'context':context(row),'internal_name':row['product']['internal_name'],
            'historical_row':(row.get('historical',{}).get('internal_reference',{}).get('record') or {}),
            'selected': row['material']['selected'] if domain=='material' else row.get(domain),
            'candidate_only':True})
        if reasons: group['exceptions'].append({'id':row['id'],'reasons':reasons})
        else: group['eligible_ids'].append(row['id'])
    if domain!='identity':
        for g in groups.values():
            conflict={r['id'] for r in g['rows'] if len(contexts[digest(r['context'])])>1}
            g['exceptions'] += [{'id':i,'reasons':['同商品/版本存在不同候选依据，须单独核实或拆分适用范围']} for i in g['eligible_ids'] if i in conflict]
            g['eligible_ids']=[i for i in g['eligible_ids'] if i not in conflict]
    return {'schema':'japan-arrival/group-review-1','batch_id':batch['id'],'revision':batch['revision'],
            'state_hash':digest(batch),'domain':domain,'groups':list(groups.values()),
            'notice':'仅组织审核范围；候选未经批准。异常留待单独处理，可仅选择明确列出的部分普通行。'}

def approve_group(batch, package, group_id, row_ids, common, per_row, *, actor, evidence, permissions, scope_confirmed=False):
    domain=package.get('domain')
    if package!=group_package(batch,domain): raise Rejected('成组审核包过期或被修改，请重新取得审核包')
    require_actor(actor,ROLES[domain],effective_permissions(batch,permissions))
    if not isinstance(evidence,str) or not evidence.strip(): raise Rejected('成组审核依据必填')
    if not row_ids or len(row_ids)!=len(set(row_ids)): raise Rejected('审核范围为空或重复')
    group=next((g for g in package['groups'] if g['id']==group_id),None)
    if not group or set(row_ids)-set(group['eligible_ids']): raise Rejected('含范围外/有争议/已确认的商品，整次拒绝')
    selected_contexts={digest(r['context']) for r in group['rows'] if r['id'] in row_ids}
    cross_scope=len(selected_contexts)>1
    if cross_scope and scope_confirmed is not True:raise Rejected('跨商品/版本成组必须人工明确确认凭据覆盖所有所选身份范围')
    if not isinstance(common,dict) or not isinstance(per_row,dict) or set(per_row)-set(row_ids):
        raise Rejected('逐行参数含范围外商品或格式错误')
    out=copy.deepcopy(batch)
    payloads={}
    for row in out['rows']:
        if row['id'] not in row_ids: continue
        extra=per_row.get(row['id'],{})
        if not isinstance(extra,dict) or set(extra)&set(common): raise Rejected('公共参数与逐行参数不能相互覆盖')
        payload=dict(common,**extra)
        if cross_scope and 'context' not in extra:raise Rejected('跨商品/版本须逐行列明证据适用身份context')
        # Require explicit per-row packaging counts/tax bases; never spread another row's quantity or price.
        required={'packaging':{'internal_quantity','internal_boxes'},'tax':{'tax_unit_price'}}.get(domain,set())
        if not required<=set(extra): raise Rejected('盒装数量/盒数和税基单价必须逐行列出，不得跨商品套用')
        payloads[row['id']]=_apply_domain_row(row,domain,payload,actor=actor,evidence=evidence)
        if domain=='tax' and row['reviews']['packaging']:box_tax(row)
    return changed(batch,out,actor,'approve_group_'+domain,row_ids,
                   {'reference':evidence,'group_id':group_id,'payloads':payloads,'scope_confirmed':scope_confirmed})

def record_exception(batch, row_ids, domain, *, actor, evidence, permissions, status='pending'):
    if domain not in ROLES or status not in ('pending','rejected_candidate'): raise Rejected('未知异常处理状态')
    require_actor(actor,ROLES[domain],effective_permissions(batch,permissions))
    if not evidence or not evidence.strip() or not row_ids or len(row_ids)!=len(set(row_ids)):
        raise Rejected('异常范围及处理理由必填')
    if set(row_ids)-{r['id'] for r in batch['rows']}: raise Rejected('含未知源行')
    out=copy.deepcopy(batch)
    for row in out['rows']:
        if row['id'] not in row_ids: continue
        # Revoke only the affected professional domain; all other disputes survive.
        row['reviews'][domain]=None
        if domain=='material': row['material']['selected']=None
        elif domain in ('packaging','tax'): row[domain]=None
        if domain in ('identity','packaging'):
            row['reviews']['tax']=None;row['tax']=None
        if domain=='identity':
            for d in ('product','material','packaging'): row['reviews'][d]=None
            row['material']['selected']=None;row['packaging']=None
        row['disputes']=[d for d in row['disputes'] if d['id']!='group_review_'+domain]
        row['disputes'].append({'id':'group_review_'+domain,'domain':domain,'reason':evidence,'status':status,
                                 'recorded_by':actor,'recorded_at':now()})
    return changed(batch,out,actor,'exception_'+domain,row_ids,{'reference':evidence,'status':status})
