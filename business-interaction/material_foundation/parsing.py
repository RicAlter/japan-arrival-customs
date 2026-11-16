from html.parser import HTMLParser
from pathlib import Path
from collections import Counter
import json,re,sys,unicodedata

class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.ignored=0
    def handle_starttag(self,t,a):
        if t in ('script','style'):self.ignored+=1
        if not self.ignored and t in ('br','p','div','li','tr','th','td','h1','h2'):self.parts.append('\n')
    def handle_endtag(self,t):
        if t in ('script','style'):self.ignored=max(0,self.ignored-1)
        if not self.ignored and t in ('p','div','li','tr','th','td'):self.parts.append('\n')
    def handle_data(self,d):
        if not self.ignored:self.parts.append(d)
def plain(value):
    p=Text();p.feed(str(value));return unicodedata.normalize('NFKC',''.join(p.parts))
def clean(value):
    value=re.split(r'※|(?:サイズ|商品サイズ|寸法)\s*[:：]|約\s*[WＷ]?\d+(?:\.\d+)?\s*(?:mm|cm|[×xX])',value,maxsplit=1)[0]
    return re.sub(r'^[\s■●□【】:：]+|[\s。;；]+$','',value).strip()
def extract(value,site=''):
    lines=[s.strip() for s in plain(value).splitlines() if s.strip()]
    # Hobby Search's 商品説明 material line precedes a less complete spec field.
    if site=='hobbysearch':
        start=next((i for i,s in enumerate(lines) if '商品説明' in s),0)
        lines=lines[start:]+lines[:start]
    for label in ('素材','材質','仕様','スペック','Material','Materials'):
        pattern=re.compile(r'^(?:[■●□◆\s]*)(?:製品|商品|本体)?'+re.escape(label)+r'\s*[:：]?\s*(.*)$',re.I)
        for i,line in enumerate(lines):
            m=pattern.match(line)
            if not m:continue
            chunks=[m[1]] if m[1].strip() else []
            for nxt in lines[i+1:]:
                if re.match(r'^[■●□◆]?\s*(?:素材|材質|仕様|スペック|サイズ|Size|JAN|対象年齢|原産国|商品説明|商品名|発売|注意|備考|メーカー|ブランド|価格|重量|パッケージ)',nxt,re.I):break
                if chunks and not re.match(r'^(?:本体|台座|ボールチェーン|金具|生地|裏面|表面|[\w一-龯ァ-ヶ]+[:：])',nxt):break
                chunks.append(nxt)
            found=clean(' '.join(chunks))
            if found:return {'original':found,'label':label}
    return None

def translate(original):
    # Reuse the existing glossary only; bypass the old "already Chinese" shortcut.
    vendor=Path(__file__).resolve().parents[1]/'material_providers/vendor/jp_material_query'
    if str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    from jpmaterial.translate import DEFAULT_GLOSSARY
    terms={**DEFAULT_GLOSSARY,'紙製':'纸质','合成紙':'合成纸','レザー':'人造革(PU革)','合皮':'人造革(PU革)','ブリキ':'马口铁(锡制)','本体':'本体','台座':'底座','錫':'锡','ユリア':'尿素树脂','ABS':'ABS树脂','Soft PVC Rubber':'软质PVC'}
    text=unicodedata.normalize('NFKC',original)
    regex=re.compile('|'.join(re.escape(k) for k in sorted(terms,key=len,reverse=True)),re.I)
    lower={k.lower():v for k,v in terms.items()}
    zh=regex.sub(lambda m:lower[m[0].lower()],text)
    zh=re.sub(r'[,，/／・]+','、',zh)
    zh=re.sub(r'(本体|底座):',r'\1：',zh)
    zh=re.sub(r'(\d+(?:\.\d+)?\s*%)\s+','\\1',zh)
    zh=re.sub(r'棉\s*(\d+(?:\.\d+)?%)',r'\1棉',zh)
    percentages=lambda s:Counter(re.findall(r'\d+(?:\.\d+)?%',s.replace(' ','')))
    if percentages(text)!=percentages(zh):raise ValueError('TRANSLATION_LOSS: 比例丢失')
    return {'zh':zh,'original':original,'unknown_retained':bool(re.search('[ぁ-ヿ]',zh)),'method':'full-text-versioned-glossary-no-component-filter'}

def objects(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():yield from objects(v)
    elif isinstance(value,list):
        for v in value:yield from objects(v)

def parse(site,jan,phase,body,url,selected=None):
    if re.search(r'cf-chl-|^\s*Just a moment|<title[^>]*>\s*(?:Just a moment|Access Denied)|Verify you are human',body,re.I):return {'status':'error'}
    try:data=json.loads(body)
    except (ValueError,TypeError):data=None
    if isinstance(data,dict) and (data.get('error') or data.get('errors')):return {'status':'error'}
    if site in ('anime_store','colleize','amiami') and not isinstance(data,dict):return {'status':'error','error_code':'INVALID_API_RESPONSE'}
    if phase=='search' and site in ('colleize','amiami'):
        key='janCode' if site=='colleize' else 'jancode'
        matches=[o for o in objects(data) if str(o.get(key,''))==jan]
        idkey='id' if site=='colleize' else 'gcode'
        ids=list(dict.fromkeys(str(o[idkey]) for o in matches if o.get(idkey)))
        if not ids:return {'status':'not_found'}
        return {'status':'detail','ids':ids}
    if site=='anime_store' and data is not None:
        product=data.get('product',data)
        if not any(str(o.get('barcode',''))==jan for o in objects(product)):return {'status':'identity_mismatch'}
        text=product.get('body_html','')
    elif site in ('colleize','amiami') and data is not None:
        key='janCode' if site=='colleize' else 'jancode'
        matched=[o for o in objects(data) if str(o.get(key,''))==jan]
        if not matched and site=='amiami':matched=[o for o in objects(data) if selected and str(o.get('gcode',''))==str(selected)]
        if not matched:return {'status':'identity_mismatch'}
        obj=matched[0]
        if site=='colleize':
            material=obj.get('material')
            if material:return {'status':'found','original':str(material),'label':'material'}
            return {'status':'no_material'}
        text='\n'.join(str(v) if not isinstance(v,list) else '\n'.join(map(str,v)) for k,v in obj.items() if k in ('spec','memo'))
    else:
        # On HTML pages require an explicitly labelled JAN or exact canonical product route.
        canonical=re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',body,re.I)
        labelled=re.search(r'(?:JAN(?:コード)?|janCode|jancode|バーコード)[\s:：<>=/"\'a-zA-Z-]*'+re.escape(jan)+r'(?!\d)',body,re.I)
        route=canonical and re.search(r'/(?:g/g|products/)'+jan+r'(?:/|$|[?"\'])',canonical[1])
        if not (labelled or route):return {'status':'identity_mismatch'}
        text=body
    result=extract(text,site)
    return {'status':'found',**result} if result else {'status':'no_material'}
