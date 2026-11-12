"""Evidence-scoped stage-two arithmetic. No price-ratio packaging inference."""
from fractions import Fraction
import re
import unicodedata

POLICY = 'fixed-sku-packaging/20261112'
PRODUCT_KINDS=['姓名吧唧','文件夹','吧唧','冰箱贴','徽章','透卡','贴纸','明信片','立牌','拍立得','相卡','挂件','卡片','收藏卡','亚克力']

def product_kinds(text):
    found=[k for k in PRODUCT_KINDS if k in str(text or '')]
    if any('吧唧' in k for k in found):found=[k for k in found if k!='徽章']
    # A named badge is a separate SKU class, not the generic trading badge.
    return [k for k in found if not any(k!=other and k in other for other in found)]
HEADERS = ['每包单个数','每盒包数','每盒单个数','本行盒数','每原Qty单个数','每盒原Qty数',
           '未取整单个价JPY','取整后金额JPY','取整差额JPY','关税率参考','增值税率参考',
           '每原Qty关税JPY','每原Qty增值税JPY','每盒税金JPY','本行税金JPY','采购数量核对','计算状态','异常说明']

def number(value):
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None

def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC',str(value or '')))

def invoice_key(row):
    return tuple(norm(row[k]) for k in ['carton','code','origin','japanese_name']) + tuple(
        str(number(row[k])) for k in ['quantity','price','amount'])

def unique_match(targets, sources):
    index = {}
    for row in sources:
        index.setdefault(invoice_key(row), []).append(row)
    used, matches = set(), []
    for row in targets:
        found = index.get(invoice_key(row), [])
        if len(found) != 1 or found[0]['source_row'] in used:
            raise ValueError('分箱身份不能唯一匹配：'+str(row.get('source_row')))
        used.add(found[0]['source_row']); matches.append((row, found[0]))
    return matches

def packaging(text, *, identity_scoped=False, product_kind=None, product_spec=None):
    """Return all distinct explicit candidates; caller must retain source/identity."""
    text = unicodedata.normalize('NFKC', str(text or ''))
    found = []
    # Separate labelled alternatives, retaining adjacent packet/box descriptions.
    for clause in re.split('[;；]', text):
        labels = PRODUCT_KINDS
        present = [k for k in labels if k in clause]
        parts = re.split(r'[,，、](?=(?:'+ '|'.join(labels)+r'|[A-Z]整盒|vol\.?\s*\d+整盒))',clause,flags=re.I)
        for part in parts:
            alternatives=re.match(r'\s*([A-Za-z]{1,2}(?:[、,，][A-Za-z]{1,2})+)整盒',part)
            if alternatives:
                selected=re.match(r'([A-Za-z]{1,2})整盒',norm(product_spec))
                if not selected or selected[1].lower() not in [s.lower()for s in re.split('[、,，]',alternatives[1])]:continue
            version=re.match(r'\s*(vol\.?\s*\d+|[A-Z]{1,2})整盒',part,re.I)
            if version:
                selected=re.sub(r'[.\s]','',norm(product_spec)).lower()
                prefix=re.sub(r'[.\s]','',version[1]).lower()+'整盒'
                if not selected.startswith(prefix):continue
            labelled = product_kinds(part)
            if labelled:
                if product_kind not in labelled:
                    continue
            elif not identity_scoped:
                continue
            inner = re.findall(r'(?:1|每)包\s*(\d+)\s*(?:枚|张|个|件)',part)
            outer = re.findall(r'(?:1盒|每盒|整盒)\s*(\d+)\s*包',part)
            direct = re.findall(r'(?:1盒|每盒|整盒)\s*(\d+)\s*(?:枚|张|个|件)(?:入)?',part)
            if inner and outer:
                for units in inner:
                    for packets in outer:
                        u,p = int(units),int(packets)
                        if u>0 and p>0:found.append({'units_per_pack':u,'packs_per_box':p,'pieces_per_box':u*p})
            for value in direct:
                c=int(value)
                if c>0:found.append({'units_per_pack':None,'packs_per_box':None,'pieces_per_box':c})
    distinct = {tuple(x.values()):x for x in found}
    return list(distinct.values())

def calculate(fact, *, total=None):
    errors=[]; q=number(fact.get('quantity'));u=number(fact.get('price'));a=number(fact.get('amount'))
    s=number(total if total is not None else fact.get('total_pieces'))
    if q is None or q<=0:errors.append('原Qty缺失或无效')
    if u is None or u<=0:errors.append('原日方价缺失或无效')
    if s is None or s<=0 or s.denominator!=1:errors.append('总单个数须为正整数')
    if a is None or q is None or u is None or a!=q*u:errors.append('原金额与原Qty×原价不符')
    c=None; layers={}; candidates=fact.get('pack_candidates',[])
    sizes={number(x['pieces_per_box']) for x in candidates}
    if len(sizes)>1:errors.append('同SKU盒规来源冲突')
    elif len(sizes)==1:
        c=next(iter(sizes)); layers=candidates[0]
    else:errors.append('缺独立盒规，参考盒数待核')
    b=None; ref=number(fact.get('reference_boxes'))
    if c and s and s>0 and s.denominator==1:
        b=s/c
        if b.denominator!=1:errors.append('总单个数不能整除固定盒规')
        if ref is not None and b!=ref:errors.append('推导盒数与参考盒数冲突')
    elif len(sizes)==0 and ref is not None and ref>0:
        b=ref
    if b is None or b<=0:errors.append('盒数不可计算')
    factor=s/q if s and s>0 and s.denominator==1 and q and q>0 else None
    if factor is not None and (factor<1 or factor.denominator!=1):errors.append('每原Qty单个数不是正整数')
    unit=u/factor if u and factor and factor>0 else None
    rounded=(2*unit.numerator+unit.denominator)//(2*unit.denominator) if unit is not None else None
    duty,vat=number(fact.get('duty_rate')),number(fact.get('vat_rate'))
    if duty is None:errors.append('缺关税率依据')
    if vat is None:errors.append('缺增值税率依据')
    if duty is not None and not 0<=duty<=1:errors.append('关税率无效');duty=None
    if vat is not None and not 0<=vat<=1:errors.append('增值税率无效');vat=None
    tariff=u*duty if u is not None and duty is not None else None
    value_added=u*(1+duty)*vat if u is not None and duty is not None and vat is not None else None
    tax=tariff+value_added if tariff is not None and value_added is not None else None
    perbox=q/b if q and b and b>0 else None
    conflict=any('冲突' in x or '不能整除' in x for x in errors)
    status='可计算' if not errors else ('部分计算' if rounded is not None else '异常')
    values=[layers.get('units_per_pack'),layers.get('packs_per_box'),c,b,factor,perbox,unit,
            rounded*s if rounded is not None and s else None,
            rounded*s-a if rounded is not None and s and a is not None else None,
            duty,vat,tariff,value_added,tax*perbox if tax is not None and perbox is not None and not conflict else None,
            tax*q if tax is not None and q else None,fact.get('purchase_note','采购总量口径待核'),status,'；'.join(dict.fromkeys(errors))]
    return {'total_pieces':s,'rounded_price':rounded,'values':values,'errors':list(dict.fromkeys(errors)),
            'exact':{k:str(v) if v is not None else None for k,v in zip('c b factor perbox unit'.split(),[c,b,factor,perbox,unit])},
            'professional_approval':False,'formal_output':False}
