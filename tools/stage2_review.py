"""Opt-in review of pinned yellow cells; no price/quantity cross inference."""
from pathlib import Path
from collections import defaultdict
import json,re
from stage2_math import norm,number,packaging,product_kinds

def product_name(value):
    text=norm(value)
    if text.startswith('模玩熊'):text=text[3:]
    for note in ['(只有二维码到货要打印条码入库)','(不同产品只有一个编码,到货需要打印编码入库)']:
        text=text.removesuffix(note)
    # Only documented sales suffixes; series, schools, volumes and types remain.
    return re.sub(r'(?:DG)?周边(?:预定金|预金|追定金)?$|DG$','',text)

def sku(value):
    text=norm(value)
    text=re.sub(r'\(\d{13,14}\)$','',text)
    return text

def same_sku(current,reference):
    a,b=sku(current),sku(reference)
    return bool(a and b)and(a==b or a.startswith(b)and bool(re.fullmatch(r'\d+(?:\.\d+)?',a[len(b):])))

def reviewed_cards(db,identity):
    """Approved parent name + YD + explicit boxed SKU; never YD alone."""
    if not identity.get('yd') or '整盒'not in str(identity.get('spec')or''):return []
    spec_kinds=product_kinds(identity['spec']);parent_kinds=product_kinds(identity['name'])
    if '卡片'in parent_kinds and any(k in parent_kinds for k in ['收藏卡','拍立得']):parent_kinds.remove('卡片')
    selected=spec_kinds[0]if len(spec_kinds)==1 else parent_kinds[0]if len(parent_kinds)==1 else None
    result=[]
    for source,row,raw in db.execute('select source_sha256,source_row,context_json from yd_product_card_details where yd_key=?',(identity['yd'],)):
        context=json.loads(raw);card=context.get('product_card',{});name=card.get('商品名称');text=card.get('产品配件','')
        if not product_name(name)or product_name(name)!=product_name(identity['name']):continue
        # A generic rule cannot identify one product of a mixed parent here.
        if not product_kinds(text)and len(parent_kinds)>1:continue
        for candidate in packaging(text,identity_scoped=True,product_kind=selected,product_spec=identity['spec']):
            result.append({**candidate,'source_sha256':source,'source_row':row,'source_version':context['source'],
                'database_sha256':identity['database_sha256'],'identity':identity,'text':text,
                'identity_basis':'pinned accepted parent name/YD + explicit boxed SKU + scoped card rule',
                'card_product_name':name})
    return result

def purchase_observations(quantity,files):
    """Read original transaction rows, retaining price/currency on the same row."""
    from openpyxl import load_workbook
    from freeze_unified import sha
    records=[]
    for source in quantity['sources']['purchase']:
        p=source['path']
        if sha(p)!=source['sha256']or files.get(p)!=source['sha256']:raise ValueError('复核采购来源未固定或漂移：'+p)
        w=load_workbook(p,read_only=True,data_only=True)
        try:
            for row,values in enumerate(w[source['sheet']].values,1):
                if row==1:continue
                record={k:values[v-1]if v<=len(values)else None for k,v in source['columns'].items()}
                if hasattr(record.get('order_date'),'isoformat'):record['order_date']=record['order_date'].isoformat()
                record['source']={'path':p,'sha256':source['sha256'],'sheet':source['sheet'],'row':row,'columns':source['columns']}
                records.append(record)
        finally:w.close()
    from interaction.quantity_review import purchase_lines
    policy=quantity['policy']
    valid,excluded,ambiguous,_=purchase_lines(records,set(policy['accepted_purchase_statuses']),policy['as_of'])
    positions={(r['source']['sha256'],r['source']['sheet'],r['source']['row']):r for r in records}
    for item in valid:
        observations=[positions[(s['sha256'],s['sheet'],s['row'])]for s in item['all_sources']]
        if len({(str(number(r.get('price'))),str(r.get('currency')))for r in observations})>1:
            item['price_export_conflict']=True
    index=defaultdict(lambda:{'valid':[],'ambiguous':[],'excluded':[]})
    for group,items in [('valid',valid),('ambiguous',ambiguous),('excluded',excluded)]:
        for item in items:
            if item.get('yd'):index[norm(item['yd'])][group].append(item)
    return index

def price_review(identity,fact,index):
    group=index.get(norm(identity.get('yd')),{});matches={}
    for key in ['valid','ambiguous','excluded']:
        matches[key]=[r for r in group.get(key,[])if product_name(r.get('name'))==product_name(identity['name'])and same_sku(identity['spec'],r.get('spec'))]
    result={'observations':matches,'value':None}
    if matches['ambiguous']:result['reason']='采购状态、砍单或订单行版本待核';return result
    valid=matches['valid']
    if any(r.get('price_export_conflict')for r in valid):result['reason']='同订单重复导出报价冲突';return result
    prices={(number(r.get('price')),str(r.get('currency')))for r in valid}
    if not valid:result['reason']='缺对应商品/规格的有效采购报价';return result
    if len(prices)!=1:result['reason']='同SKU采购币种或报价不唯一';return result
    price,currency=next(iter(prices))
    if price is None or price<=0 or currency not in ['人民币','日元','CNY','JPY']:result['reason']='采购报价或币种缺依据';return result
    # H is a reference for the original priced unit. No speculative conversion.
    q,s,b=number(fact['quantity']),number(fact['total_pieces']),number(fact['reference_boxes'])
    boxed='整盒'in str(identity['spec'])
    explicit_units={int(m[1])for r in valid if(m:=re.search(r'随机(\d+)(?:枚|张|个)$',sku(r.get('spec'))))}
    same_packet=not boxed and q and explicit_units=={s/q}
    if (boxed and(not fact['pack_candidates']or q!=b))or(not boxed and q!=s and not same_packet):
        result['reason']='采购SKU与原Qty计价单位换算待核';return result
    display=str(valid[0]['price'])if price.denominator!=1 else str(price.numerator)
    result.update(value=display+('元'if currency in ['人民币','CNY']else'JPY'),reason=None,
                  scope='采购SKU参考价；不参与I或税金计算，不构成采购累计放行')
    return result
