"""Conservative public-product parser; URL/code agreement alone is insufficient."""
import html
import json
import re
import unicodedata
from html.parser import HTMLParser

PARSER_VERSION = 'anime-product-identity-1'


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld = []; self.parts = []; self.in_ld = False
        self.title = ''; self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type','').lower() == 'application/ld+json':
            self.in_ld = True; self.parts = []
        if tag == 'title': self.in_title = True

    def handle_data(self, data):
        if self.in_ld: self.parts.append(data)
        if self.in_title: self.title += data

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_ld:
            self.ld.append(''.join(self.parts)); self.in_ld = False
        if tag == 'title': self.in_title = False


class Text(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]; self.hidden=0
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','noscript'}:self.hidden+=1
        if tag in {'br','p','div','li','tr'}:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript'}:self.hidden=max(0,self.hidden-1)
        if tag in {'p','div','li','tr'}:self.parts.append('\n')


def visible(value):
    p=Text();p.feed(str(value or ''))
    return '\n'.join(line.strip() for line in ''.join(p.parts).splitlines() if line.strip())


def walk(value):
    if isinstance(value, dict):
        kind=value.get('@type',[])
        if kind=='Product' or isinstance(kind,list) and 'Product' in kind:yield value
        for child in value.values():yield from walk(child)
    elif isinstance(value,list):
        for child in value:yield from walk(child)


LABELS = r'素材|材質|材料|サイズ|仕様|規格|型番|バージョン|版本|発売元|製造元|販売元|原産国|対象年齢|商品番号|商品コード|JANコード|備考|注意事項|発売日'


def labelled(description, labels):
    # Only the selected Product.description is scanned, never related products.
    text=visible(description)
    marker=r'(?:^|\n|■|【)(?:'+labels+r')(?:】)?\s*[:：]?\s*'
    match=re.search(marker,text)
    if not match:return None
    tail=text[match.end():]
    end=re.search(r'(?:\n|■|【)(?:'+LABELS+r')(?:】)?\s*[:：]?|(?:'+LABELS+r')\s*[:：]',tail)
    result=tail[:end.start()] if end else tail
    return result.strip(' \t\r\n■') or None


TOKENS={'ポリエステル':'聚酯纤维','ポリウレタン':'聚氨酯','ポリプロピレン':'聚丙烯',
        'ポリカーボネート':'聚碳酸酯','ポリエチレン':'聚乙烯','ステンレス':'不锈钢',
        'アルミニウム':'铝','アルミ':'铝','亜鉛合金':'锌合金','合成皮革':'合成革',
        'アクリル':'亚克力','スチール':'钢','ナイロン':'尼龙','シリコーン':'硅胶','シリコン':'硅胶',
        'コットン':'棉','ラバー':'橡胶','ゴム':'橡胶','紙':'纸','鉄':'铁','綿':'棉',
        '本体':'主体','金具':'金属配件','ボールチェーン':'珠链','その他':'其他','等':'等',
        'PVC':'PVC','ABS':'ABS','PET':'PET','PP':'PP','PE':'PE','PU':'PU','金属':'金属'}


def translate(original):
    if not original:return None, []
    pattern=re.compile('|'.join(re.escape(k) for k in sorted(TOKENS,key=len,reverse=True)))
    residue=pattern.sub('',original)
    unknown=re.sub(r'[\s\d.,、・/／:：;；()（）%％+＋\[\]【】\-—～~]+','',residue)
    if unknown:return None,[unknown]
    return pattern.sub(lambda m:TOKENS[m.group()],original),[]


def comparable(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value or '')).split()).casefold()


def parse(code, page, expected):
    doc=Document();doc.feed(page)
    if re.search(r'just a moment|access denied|captcha|アクセス制限',doc.title,re.I):
        return {'status':'permission_denied','reason':'challenge_page','product_hit':False,'identity_status':'pending'}
    products=[];bad_json=0
    for raw in doc.ld:
        try:products.extend(walk(json.loads(raw)))
        except (ValueError,TypeError):bad_json+=1
    matching=[]
    for product in products:
        ids={k:str(product[k]) for k in ('gtin','gtin13','gtin8','sku')
             if isinstance(product.get(k),(str,int)) and not isinstance(product[k],bool)}
        if code in ids.values():matching.append((product,ids))
    if not matching:
        return {'status':'unsupported_mapping','reason':'no_structured_product_code_match',
                'product_hit':False,'identity_status':'pending','structured_products':len(products),'invalid_json_ld':bad_json}
    signatures={json.dumps(p,sort_keys=True,ensure_ascii=False) for p,_ in matching}
    if len(signatures)>1:
        return {'status':'partial_failure','reason':'multiple_products_with_same_code',
                'product_hit':True,'identity_status':'conflict','matching_products':len(matching)}
    product,identifiers=matching[0]
    description=product.get('description') if isinstance(product.get('description'),str) else ''
    props=product.get('additionalProperty',[])
    if isinstance(props,dict):props=[props]
    if not isinstance(props,list):props=[]
    property_conflicts=[]
    def property_value(names):
        values={str(p.get('value')).strip() for p in props if isinstance(p,dict)
                and isinstance(p.get('name'),str) and p['name'] in names
                and isinstance(p.get('value'),(str,int,float)) and not isinstance(p['value'],bool) and p['value']!=''}
        if len(values)>1:property_conflicts.append({'labels':sorted(names),'values':sorted(values)})
        return next(iter(values)) if len(values)==1 else None
    version=property_value({'version','バージョン','版本'}) or labelled(description,'バージョン|版本')
    specification=property_value({'specification','仕様','規格','型番'}) or labelled(description,'仕様|規格|型番')
    name=visible(product['name']) if isinstance(product.get('name'),str) else None
    material=labelled(description,'素材|材質|材料')
    translated,unknown=translate(material)
    namespace=None
    if expected.get('code_type')=='JAN' and any(identifiers.get(k)==code for k in ('gtin','gtin13','gtin8')):namespace='JAN'
    elif expected.get('code_type')=='source_identifier' and identifiers.get('sku')==code:namespace='source_identifier'
    observed={'code_raw':code,'code_type':namespace,'japanese_name':name,
              'version':version,'specification':specification}
    differences=[];missing=[];agree=[]
    for key in ('japanese_name','version','specification'):
        wanted=expected.get(key);actual=observed[key]
        if wanted and actual:
            (agree if comparable(wanted)==comparable(actual) else differences).append(key)
        else:missing.append(key)
    if namespace is None:missing.append('code_type')
    if property_conflicts:differences.append('site_property_conflict')
    identity_status='conflict' if differences else ('confirmed' if not missing else 'pending')
    status='no_match' if differences else ('succeeded' if material else 'no_data')
    return {'status':status,'reason':'identity_conflict' if differences else ('material_extracted' if material else 'material_not_present'),
            'product_hit':True,'identity_status':identity_status,'observed_identity':observed,
            'identifiers':identifiers,'identity_quote':name,'identity_checks':{'agreed':agree,'conflicting':differences,'pending':missing},
            'site_property_conflicts':property_conflicts,
            'material_original':material,'material_translation':translated,'unknown_translation_tokens':unknown,
            'field_evidence':{'japanese_name':'Product.name','version':'Product.additionalProperty/description explicit label',
                              'specification':'Product.additionalProperty/description explicit label','material':'Product.description'},
            'parser_version':PARSER_VERSION}
