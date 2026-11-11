"""Resumable website-only R enrichment. Copies XLSX ZIP members losslessly."""
from __future__ import annotations
import argparse, collections, concurrent.futures, hashlib, html, json, queue, re
import sys, threading, time, unicodedata, urllib.error, urllib.request, zipfile
from urllib.parse import quote
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

# This is the verified 2026-11-09 provider, vendored with the interaction
# layer so a packaged Skill does not silently depend on a developer's project
# root.  `REPORT` is deliberately replaced by material_review for every run.
ROOT = Path(__file__).resolve().parents[2]
PLUGIN = Path(__file__).resolve().parent/'vendor/jp_material_query'
sys.path.insert(0, str(PLUGIN))
from jpmaterial.translate import DEFAULT_GLOSSARY
from jpmaterial.identity import name_similarity
from jpmaterial.adapters.amnibus import AmnibusAdapter
from jpmaterial.models import ProductQuery, SitePolicy
from patch_website_material_r import replace_cell

NS = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
SOURCE = ROOT/'outputs/KMT20261101_多网站材质补查_20261106/KMT20261101_核对版_高清图片_多网站材质补查.xlsx'
REPORT = ROOT/'reports/fast-material-batch-20261106'
OUTPUT = ROOT/'outputs/KMT20261101_快速网站材质补查_20261106/KMT20261101_核对版_高清图片_快速网站材质补查.xlsx'
SITES = ['anime_store','colleize','amiami','jumpcs','amnibus']
# Anime Store's public product JSON has completed >140 calls here without
# throttling; the batch SOP permits 20/minute (3 seconds). Other sites keep
# their existing conservative cadence.
RATES = dict(anime_store=3, colleize=5, amiami=3, jumpcs=8, amnibus=2)

def now(): return datetime.now().astimezone().isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def snapshot_name(path):
    try:return str(path.relative_to(ROOT))
    except ValueError:return str(path)
def save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(p)

def read_cells(data):
    with zipfile.ZipFile(__import__('io').BytesIO(data)) as z:
        st=[''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        cells={}
        for c in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:sheetData/s:row/s:c', NS):
            v=c.find('s:v',NS); v=v.text if v is not None else ''
            if c.get('t')=='s': v=st[int(v)]
            elif c.get('t')=='inlineStr': v=''.join(c.find('s:is',NS).itertext())
            cells[c.get('r')]=v
        return cells

class Text(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[];self.ignored=0
    def handle_starttag(self,t,a):
        if t in ('script','style'):self.ignored+=1
        if self.ignored:return
        if t in ('br','p','div','li','tr'):self.parts.append('\n')
    def handle_endtag(self,t):
        if t in ('script','style'):
            self.ignored=max(0,self.ignored-1);return
        if self.ignored:return
        if t in ('p','div','li','tr'):self.parts.append('\n')
    def handle_data(self,d):
        if not self.ignored:self.parts.append(d)

def plain(s):
    p=Text();p.feed(str(s));return html.unescape(''.join(p.parts))

try:
    from .quality import material_quality
except ImportError:
    from quality import material_quality

_LABEL=r'(?:製品素材|本体素材|素\s*材(?:・仕様)?|材質|材料|Materials?)'

def extract(body):
    # A saved public-browser response may be a JSON string with numbered lines.
    text_body=str(body)
    if text_body.lstrip().startswith('"'):
        try:
            decoded=json.loads(text_body)
            if isinstance(decoded,str):text_body=decoded
        except ValueError:pass
    text_body=re.sub(r'^L[0-9]+:\s?', '',text_body,flags=re.M)
    label=re.compile(r'^(?:[■□●○◆◇★☆【〖\[\s]*)?'+_LABEL+r'[】〗\]]?\s*[:：]?\s*(.*)',re.I)
    # Prefer bounded material elements over a flattened full product page.
    field=re.search(r'<dd\b[^>]*\bid=["\']spec_material["\'][^>]*>(.*?)</dd\s*>',text_body,re.S|re.I)
    bounded=[]
    if field:bounded=[plain(field[1]).strip()]
    else:
        for m in re.finditer(r'<(?:dt|th)\b[^>]*>(.*?)</(?:dt|th)>\s*<(?:dd|td)\b[^>]*>(.*?)</(?:dd|td)>',text_body,re.S|re.I):
            heading=unicodedata.normalize('NFKC',plain(m[1])).strip()
            if re.fullmatch(_LABEL+r'\s*[:：]?',heading,re.I):bounded.append(plain(m[2]).strip())
        if not bounded:
            for m in re.finditer(r'<(li|p)\b[^>]*>(.*?)</\1>',text_body,re.S|re.I):
                fragment=unicodedata.normalize('NFKC',plain(m[2])).strip();match=label.match(fragment)
                if match and match[1].strip():bounded.append(match[1].strip())
    if bounded:
        value=unicodedata.normalize('NFKC','\n'.join(dict.fromkeys(bounded)))
        value=re.split(r'\s+(?:サイズ|原産国|生産国|発売元|販売元)\s*[:：]',value)[0].strip()
        return (value,'explicit_material') if material_quality(value) else ('','parse_error')
    text=unicodedata.normalize('NFKC',plain(text_body))
    # Some saved retail pages expose their description only as metadata.
    if not any(label.match(line.strip()) for line in text.splitlines()):
        for m in re.finditer(r'<meta\b[^>]*(?:property|name)=["\'](?:og:description|description)["\'][^>]*content=["\'](.*?)["\'][^>]*>',text_body,re.S|re.I):
            desc=html.unescape(m[1]);match=re.search(_LABEL+r'\s*[:：]\s*(.+)',desc,re.I)
            if match:
                value=re.split(r'\s*(?:原産国|サイズ|※|©)',match[1])[0].strip()
                return (value,'explicit_material') if material_quality(value) else ('','parse_error')
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    stop=re.compile(r'^\(C\)|^(?:この商品のレビュー|レビュー|Tweet|ITEM CATEGORY)|^[■□●○◆◇★☆※©]|^(?:サイズ|商品サイズ|発売元|販売元|原産国|生産国|仕様|スペック|JAN|注意|作品|商品仕様|PKG|対象年齢|著作権|ラインナップ|もっと見る|Size\b|Color\b|Features\b|Art by\b|Copyright\b)|^[0-9]+(?:パック|BOX|枚|個)|^(?:本体|台座|パーツ|厚み)[:：].*(?:mm|cm)',re.I)
    values=[];active=False
    for line in lines:
        m=label.match(line)
        if m:value=m[1];active=True
        elif active and not stop.search(line):value=line
        else:active=False;continue
        value=re.split(r'\s+(?:サイズ|原産国|生産国|発売元|販売元)\s*[:：]',value)[0].strip()
        if value:values.append(value)
    if values:
        value='\n'.join(dict.fromkeys(values))
        return (value,'explicit_material') if material_quality(value) else ('','parse_error')
    for line in lines:
        m=re.match(r'^[■□●○\s]*(?:仕様|スペック)\s*[:：]\s*(.+)',line)
        if m and re.search(r'アクリル|ブリキ|樹脂|綿|ポリエステル|真鍮|錫|ユリア|紙製|鉄製|PVC|PET|ABS|PP|ナイロン|合皮|素材|材質',m[1],re.I):
            return (m[1],'material_in_specification') if material_quality(m[1]) else ('','parse_error')
    return '','no_material'

GLOSSARY={**DEFAULT_GLOSSARY,'亜鉛合金':'锌合金','Tinplate':'马口铁','Zinc alloy':'锌合金','Soft PVC Rubber':'软质PVC橡胶','台座':'底座','チャーム':'挂件','ナスカン':'弹簧扣','リボン':'丝带','錫':'锡','ユリア':'尿素树脂','スチロール':'聚苯乙烯','ユポ紙':'合成纸(ユポ)','Polypropylene':'聚丙烯','ボールチェーン':'珠链','ステッカー':'贴纸','製品素材':'产品材质','裏面':'背面','製':'制'}
PAT=re.compile('|'.join(re.escape(k) for k in sorted(GLOSSARY,key=len,reverse=True)),re.I)
LOOKUP={k.lower():v for k,v in GLOSSARY.items()}
def translate(s):
    s=unicodedata.normalize('NFKC',s)
    result=PAT.sub(lambda m:LOOKUP[m[0].lower()],s)
    assert re.findall(r'\d+(?:\.\d+)?\s*%',s)==re.findall(r'\d+(?:\.\d+)?\s*%',result)
    return result.replace('\n','；').strip()

def norm(s): return re.sub(r'[^\w一-龥ぁ-んァ-ヶー]','',unicodedata.normalize('NFKC',s).lower())
def version_set(s):
    return set(re.findall(r'vol\.?\s*\d+|ver\.?(?:\d+(?:\.\d+)*|[a-z]\d+)|全\s*\d+\s*種',unicodedata.normalize('NFKC',s).lower()))

def _unit_wrapper_name(value):
    return re.sub(r'[（(]単位[/／](?:BOX|コンプリートBOX)[）)]','',value,flags=re.I).strip()

def _cached_jan_chain(row,candidate):
    chain=row.get('identity_chain') or {}
    if chain.get('jan')!=row.get('jan') or chain.get('official_url')!=candidate.get('url'):return False
    try:
        p=Path(chain['snapshot']);p=p if p.is_absolute() else ROOT/p;raw=p.read_bytes()
        if sha(raw)!=chain['content_sha256']:return False
        records=[r for r in walk(json.loads(raw)) if str(r.get('janCode') or r.get('jancode') or '')==row['jan']
                 and norm(r.get('name') or r.get('goodsName') or '')==norm(chain.get('title',''))]
    except (KeyError,OSError,ValueError,UnicodeError):return False
    return bool(norm(candidate.get('title','')) and any(norm(candidate['title']) in norm(r.get('name') or r.get('goodsName') or '') for r in records))

def identity(row, candidate):
    if candidate.get('jan') != row['jan']:return False,'jan_mismatch'
    q,p=norm(row['name_ja']),norm(candidate.get('title',''))
    if not q or not p:return False,'missing_name'
    # Full Japanese source name is a stronger anchor than Chinese procurement suffixes.
    if candidate.get('jan_not_displayed'):
        if not _cached_jan_chain(row,candidate):return False,'name_only_requires_verified_JAN_chain'
        q,p=norm(_unit_wrapper_name(row['name_ja'])),norm(_unit_wrapper_name(candidate.get('title','')))
        if q and q in p:return True,'cached_exact_JAN_chain_and_official_name_scope'
    if q in p:return True,('exact_name_spec_jan_not_displayed' if candidate.get('jan_not_displayed') else 'exact_jan_full_japanese_name')
    size_pattern=r'サイズ\s*[/／:：]?\s*([a-z0-9.]+)'
    query=unicodedata.normalize('NFKC',row['name_ja']).lower()
    title=unicodedata.normalize('NFKC',candidate.get('title','')).lower()
    qs=set(re.findall(size_pattern,query));ps=set(re.findall(size_pattern,title))
    if qs and ps and qs!=ps:return False,'size_conflict'
    qbase=norm(re.sub(size_pattern,'',query));pbase=norm(re.sub(size_pattern,'',title))
    if qs and qs==ps and qbase and qbase in pbase and not candidate.get('jan_not_displayed'):
        return True,'exact_jan_full_name_size_reordered'
    if candidate.get('jan_not_displayed'):return False,'name_only_not_exact'
    a=version_set(row['name_ja']);b=version_set(candidate.get('title',''))
    if a and b and a != b:return False,'version_conflict'
    # Site catalogues move the quoted series before the product type. Require
    # the exact series on both sides, then compare the complete remaining title.
    series=re.findall(r'[「『]([^「『」』]+)[」』]',row['name_ja'])
    if series and all(norm(s) in p for s in series):
        qc,pc=q,p
        for s in series:qc=qc.replace(norm(s),'');pc=pc.replace(norm(s),'')
        qc=qc.replace('tvアニメ','');pc=pc.replace('tvアニメ','')
        if '整盒' in row.get('spec','') and a==b and any(x.startswith('全') for x in a):
            for token in ['ブラインド','トレーディング','コンプリートセット','単位box','box']:
                qc=qc.replace(token,'');pc=pc.replace(token,'')
        if qc==pc:return True,'exact_jan_series_title_reordered_scope_checked'
    score=name_similarity(row['name_ja'],candidate.get('title','')) or 0
    return score>=0.8, f'exact_jan_name_score_{score}'

def _local_path(path):
    path=Path(path)
    absolute=str(path.absolute())
    if sys.platform=='win32' and len(absolute)>=248 and not absolute.startswith('\\\\?\\'):
        return Path('\\\\?\\'+absolute)
    return path

class Client:
    def __init__(self,site):self.site=site;self.last=0;self.stopped='';self.count=0
    def get(self,url):
        if self.stopped:return {'error':self.stopped}
        cache=_local_path(REPORT/'responses'/self.site/(sha(url.encode())+'.txt'))
        if cache.exists():
            raw=cache.read_bytes();record={'url':url,'status':200,'from_cache':True,'content_sha256':sha(raw),'snapshot':snapshot_name(cache)}
            try:record['data']=json.loads(raw)
            except (ValueError,UnicodeError):record['text']=raw.decode('utf-8',errors='replace')
            return record
        time.sleep(max(0,RATES[self.site]-(time.monotonic()-self.last)))
        self.last=time.monotonic();self.count+=1;t=time.monotonic()
        headers={'User-Agent':'Mozilla/5.0'}
        if self.site=='amiami':headers={'User-Agent':'python-amiami_dev','X-User-Key':'amiami_dev'}
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=15) as r:
                raw=r.read();status=r.status
                record={'url':url,'status':status,'seconds':round(time.monotonic()-t,3),'fetched_at':now(),'content_sha256':sha(raw)}
                path=_local_path(REPORT/'responses'/self.site/(sha(url.encode())+'.txt'));path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                record['snapshot']=snapshot_name(path)
                try:record['data']=json.loads(raw)
                except (ValueError,UnicodeError):record['text']=raw.decode('utf-8',errors='replace')
                return record
        except urllib.error.HTTPError as e:
            if e.code==403:self.stopped='blocked_403'
            if e.code==429:self.stopped='rate_limited_429'
            raw=e.read();path=_local_path(REPORT/'errors'/self.site/(sha(url.encode())+'.bin'));path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            return {'url':url,'status':e.code,'error':self.stopped or ('http_'+str(e.code)),'detail':raw[:2000].decode('utf-8',errors='replace'),'fetched_at':now(),'snapshot':snapshot_name(path),'content_sha256':sha(raw),'retry_after':e.headers.get('Retry-After') if e.headers else None}
        except Exception as e:
            reason=getattr(e,'reason',e)
            error='environment_permission_blocked' if isinstance(reason,PermissionError) or getattr(reason,'winerror',None)==10013 else 'network_error'
            return {'url':url,'error':error,'detail':str(e),'fetched_at':now()}

def walk(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values():yield from walk(v)
    elif isinstance(obj,list):
        for v in obj:yield from walk(v)

def query(site,client,jan,row):
    attempts=[]
    def get(url):
        r=client.get(url);attempts.append({k:v for k,v in r.items() if k not in ('data','text')});return r
    candidate=None;identity_rejections=[]
    if site=='anime_store':
        r=get(f'https://anime-store.jp/products/{jan}.js');d=r.get('data',{})
        if d:
            codes=[str(x.get('barcode','')) for x in d.get('variants',[])]
            candidate={'jan':jan if jan in codes else '', 'title':d.get('title',''),'body':d.get('description',''),'url':f'https://anime-store.jp/products/{jan}'}
    elif site=='colleize':
        r=get(f'https://api.colleize.com/api/goods?name={jan}&sortType=RECOMMEND')
        data=r.get('data',{});refs=data.get('goodsList',[]) if isinstance(data,dict) else []
        refs=[d for d in refs if isinstance(d,dict) and d.get('id') and (not d.get('janCode') or str(d['janCode'])==jan)]
        if refs:
            r=get('https://api.colleize.com/api/goods/'+str(refs[0]['id']))
            refs=[d for d in walk(r.get('data',{})) if str(d.get('janCode',''))==jan]
            if refs:
                d=refs[0];candidate={'jan':jan,'title':d.get('name',d.get('goodsName','')),'body':'素材：'+str(d.get('material') or ''),'url':'https://colleize.com/lineup/'+str((d.get('artist') or {}).get('id',''))+'/'+str(d.get('id',''))}
    elif site=='amiami':
        r=get(f'https://api.amiami.com/api/v1.0/items?s_keywords={jan}&pagecnt=1&pagemax=20&lang=ja')
        refs=[d for d in walk(r.get('data',{})) if str(d.get('jancode',''))==jan and d.get('gcode')]
        if refs:
            code=refs[0]['gcode'];r=get(f'https://api.amiami.com/api/v1.0/item?gcode={code}')
            refs=[d for d in walk(r.get('data',{})) if str(d.get('jancode',''))==jan]
            if refs:
                d=refs[0];candidate={'jan':jan,'title':d.get('sname_simple_j') or d.get('gname_j') or d.get('name') or d.get('gname',''),'body':str(d.get('spec',''))+'\n'+str(d.get('memo','')),'url':'https://www.amiami.jp/top/detail/detail?gcode='+code}
    elif site=='jumpcs':
        if not jan.startswith('4530430'):return {'site':site,'status':'not_applicable'}
        url=f'https://jumpcs.shueisha.co.jp/shop/g/g{jan}/';r=get(url);text=r.get('text','')
        title=re.search(r'<title[^>]*>(.*?)</title>',text,re.S|re.I)
        if jan in text:candidate={'jan':jan,'title':html.unescape(title[1]) if title else '', 'body':text,'url':url}
    elif site=='amnibus':
        adapter=AmnibusAdapter(SitePolicy(site_id='amnibus',site_name='AMNIBUS',base_url='https://amnibus.com/'));q=ProductQuery(jan=jan,name_ja=row['name_ja'],spec='')
        terms=re.sub(r'[（(【\[].*?[）)】\]]',' ',row['name_ja'])
        r=get('https://amnibus.com/products/list?search_words='+quote(terms.strip()));refs=adapter.parse_search(r.get('text',''),q) if r.get('text') else []
        for ref in refs[:1]:
            r=get(ref.url)
            if r.get('text'):
                ev=adapter.parse_detail(r['text'],q,ref.url,ref)
                if norm(_unit_wrapper_name(row['name_ja'])) in norm(ev.name_ja) and norm(_unit_wrapper_name(row['name_ja'])):
                    candidate={'jan':jan,'jan_not_displayed':True,'title':ev.name_ja,'body':'素材：'+ev.material_original,'url':ref.url}
                else:identity_rejections.append({'url':ref.url,'title':ev.name_ja,'reason':'official_name_or_scope_not_verified'})
    result={'site':site,'attempts':attempts,'status':'not_found','queried_at':now()}
    if candidate:
        material,method=extract(candidate.pop('body'))
        result.update(candidate);result.update(material_original=material,extraction=method)
        if material:result.update(status='candidate',material_zh=translate(material))
        else:result['status']='parse_error' if method=='parse_error' else 'no_material'
    elif identity_rejections:result.update(status='identity_unresolved',rejected_pages=identity_rejections)
    elif attempts and attempts[-1].get('error'):result['status']=attempts[-1]['error']
    return result

class Batch:
    def __init__(self,limit,exclude_file=None,only_file=None,skip_sites=None,recover_colleize_failed=False):
        REPORT.mkdir(parents=True,exist_ok=True);self.input=SOURCE.read_bytes();self.source_sha=sha(self.input)
        backup=REPORT/(self.source_sha+'.input.xlsx')
        if not backup.exists():backup.write_bytes(self.input)
        self.cells=read_cells(self.input);groups=collections.defaultdict(list)
        for k,v in self.cells.items():
            if re.fullmatch(r'C\d+',k) and re.fullmatch(r'\d{13}',v) and not self.cells.get('R'+k[1:]):
                n=k[1:];groups[v].append(dict(row=int(n),jan=v,name_ja=self.cells.get('J'+n,''),spec=self.cells.get('G'+n,''),yd=self.cells.get('Q'+n,'')))
        self.groups=dict(list(groups.items())[:limit] if limit else groups.items())
        excluded=set(json.loads(Path(exclude_file).read_text(encoding='utf-8')).get('jan_codes',[])) if exclude_file else set()
        included=set(json.loads(Path(only_file).read_text(encoding='utf-8')).get('jan_codes',[])) if only_file else None
        if recover_colleize_failed:
            agent_state=json.loads((ROOT/'reports/fast-material-colleize-agent-20261106/state.json').read_text(encoding='utf-8'))
            included=set(agent_state.get('failed_jan',[]))
        self.groups={j:r for j,r in self.groups.items() if j not in excluded and (included is None or j in included)}
        self.skip_sites=set(skip_sites or [])
        self.path=REPORT/'state.json';self.state=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'source_sha256':self.source_sha,'results':{}}
        if self.state['source_sha256']!=self.source_sha:raise RuntimeError('Source changed; refusing stale resume')
        if excluded:self.state['delegated_jan']=sorted(excluded)
        self.state['skipped_sites']=sorted(self.skip_sites)
        self.queues=[queue.Queue() for _ in SITES];self.clients={s:Client(s) for s in SITES};self.lock=threading.RLock();self.completed=0;self.start=time.monotonic()
        # Resume prior station stop states, never bypass a 403/429 by restarting.
        for s,reason in self.state.get('stopped_sites',{}).items():self.clients[s].stopped=reason
        for jan,rows in self.groups.items():
            entry=self.state['results'].setdefault(jan,{'rows':rows,'sites':[]})
            for candidate in entry['sites']:
                if candidate.get('site')=='amiami' and not candidate.get('title'):
                    for attempt in candidate.get('attempts',[]):
                        if attempt.get('snapshot') and '/item?' in attempt.get('url',''):
                            raw=json.loads((ROOT/attempt['snapshot']).read_text(encoding='utf-8')).get('item',{})
                            candidate['title']=raw.get('sname_simple_j') or raw.get('gname_j') or raw.get('name') or raw.get('gname','')
                if candidate.get('status')=='candidate':
                    matches=self.row_matches(entry,candidate);candidate['row_identity']=matches
                    if all(x['accepted'] for x in matches.values()):entry['selected']=candidate;entry['done']=True;break
            if entry.get('done') and not entry.get('selected'):
                entry['done']=False
            if entry.get('done'):self.completed+=1
            else:self.queues[min(len(entry['sites']),len(SITES)-1)].put(jan)
    def row_matches(self,entry,c):
        return {str(r['row']):dict(zip(('accepted','reason'),identity(r,c))) for r in entry['rows']}
    def worker(self,index):
        site=SITES[index];q=self.queues[index]
        while True:
            jan=q.get()
            if jan is None:q.task_done();break
            entry=self.state['results'][jan]
            try:
                c=({'site':site,'status':'delegated_site','attempts':[]} if site in self.skip_sites else query(site,self.clients[site],jan,entry['rows'][0]));entry['sites'].append(c)
                if c.get('status')=='candidate':
                    matches=self.row_matches(entry,c);c['row_identity']=matches
                    if all(x['accepted'] for x in matches.values()):entry['selected']=c
                if entry.get('selected') or index==len(SITES)-1:
                    with self.lock:
                        entry['done']=True;self.completed+=1
                        if self.completed%10==0:print(json.dumps(self.progress(),ensure_ascii=False),flush=True)
                        self.checkpoint(export=self.completed%100==0)
                else:
                    with self.lock:self.checkpoint()
                    self.queues[index+1].put(jan)
            except Exception as e:
                entry.setdefault('errors',[]).append({'site':site,'error':repr(e)})
                if index<len(SITES)-1:self.queues[index+1].put(jan)
                else:
                    with self.lock:entry['done']=True;self.completed+=1;self.checkpoint()
            finally:q.task_done()
    def progress(self):
        return {'time':now(),'scope_jan':len(self.groups),'completed':self.completed,'selected_jan':sum(bool(e.get('selected')) for e in self.state['results'].values()),'elapsed_seconds':round(time.monotonic()-self.start,1),'requests':{s:c.count for s,c in self.clients.items()},'queues':[q.qsize() for q in self.queues]}
    def checkpoint(self,export=False):
        self.state['stopped_sites']={s:c.stopped for s,c in self.clients.items() if c.stopped};self.state['progress']=self.progress();save(self.path,self.state)
        if export:self.export()
    def export(self):
        if sha(SOURCE.read_bytes())!=self.source_sha:raise RuntimeError('Source changed during query')
        OUTPUT.parent.mkdir(parents=True,exist_ok=True)
        current=OUTPUT.read_bytes() if OUTPUT.exists() else self.input;cells=read_cells(current);changes={}
        for entry in self.state['results'].values():
            c=entry.get('selected')
            if not c:continue
            for row in entry['rows']:
                n=str(row['row']);target='R'+n
                if not cells.get(target) and all(cells.get(col+n,'')==row[key] for col,key in [('C','jan'),('J','name_ja'),('G','spec'),('Q','yd')]):changes[target]=c['material_zh']
        if changes:
            original=read_cells(current)
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(current)) as src:
                xml=src.read('xl/worksheets/sheet1.xml').decode('utf-8')
                for k,v in changes.items():xml=replace_cell(xml,k,v)
                tmp=OUTPUT.with_suffix('.tmp.xlsx')
                with zipfile.ZipFile(tmp,'w') as dst:
                    for info in src.infolist():dst.writestr(info,xml.encode('utf-8') if info.filename=='xl/worksheets/sheet1.xml' else src.read(info))
            after=read_cells(tmp.read_bytes())
            assert {k for k in original.keys()|after.keys() if original.get(k)!=after.get(k)}==set(changes)
            with zipfile.ZipFile(BytesIO(current)) as a,zipfile.ZipFile(tmp) as b:
                assert [x.filename for x in a.infolist()]==[x.filename for x in b.infolist()]
                for x,y in zip(a.infolist(),b.infolist()):
                    if x.filename!='xl/worksheets/sheet1.xml':assert a.read(x)==b.read(y),x.filename
            if OUTPUT.exists() and sha(OUTPUT.read_bytes())!=sha(current):raise RuntimeError('Output concurrently changed')
            tmp.replace(OUTPUT)
        elif not OUTPUT.exists():OUTPUT.write_bytes(self.input)
        save(REPORT/'verification.json',{'source_sha256':self.source_sha,'output_sha256':sha(OUTPUT.read_bytes()),'new_filled_R':sum(not self.cells.get(k) and bool(v) for k,v in read_cells(OUTPUT.read_bytes()).items() if re.fullmatch(r'R\d+',k)),'last_checkpoint_changes':len(changes),'non_target_cells_unchanged':True,'non_sheet_zip_members_unchanged':True,'progress':self.progress()})
    def run(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(SITES)) as pool:
            tasks=[pool.submit(self.worker,i) for i in range(len(SITES))]
            for i,q in enumerate(self.queues):q.join();q.put(None);tasks[i].result()
        self.checkpoint(export=True);print(json.dumps(self.progress(),ensure_ascii=False),flush=True)

def tests():
    assert extract('<p>■素材：紙、鉄、PET</p>')[0]=='紙、鉄、PET'
    assert extract('■素材：綿100%')[0]=='綿100%'
    assert translate('綿100%')=='棉100%'
    assert extract('■素材：本体：アクリル<br>台座：ABS<br>■サイズ：20mm')[0]=='本体:アクリル\n台座:ABS'
    assert extract('■仕様：真鍮製/色入れ')[0]=='真鍮製/色入れ'
    assert extract('■仕様：全10種')[0]==''
    assert extract('■素材：アクリル  サイズ：約W65×H140  原産国：日本')[0]=='アクリル'
    assert translate('未知成分、紙、スチール等')=='未知成分、纸、钢等'
    row={'jan':'4573643422394','name_ja':'テスト vol.2','spec':'整盒12'}
    assert not identity(row,{'jan':row['jan'],'title':'テスト vol.3'})[0]
    assert not identity(row,{'jan':'0000000000000','title':row['name_ja']})[0]
    row={'jan':'4573643235000','name_ja':'描き下ろし 沢村栄純 私服・ショッピングver. 着用刺繍BIGシルエットTシャツユニセックス(サイズ/M)','spec':'M11'}
    assert identity(row,{'jan':row['jan'],'title':'ダイヤのA actⅡ -Second Season-_サイズ/M_描き下ろし 沢村栄純 私服・ショッピングver. 着用刺繍BIGシルエットTシャツユニセックス'})[0]
    AmnibusAdapter(SitePolicy(site_id='amnibus',site_name='AMNIBUS',base_url='https://amnibus.com/'))
    assert not identity(row,{'jan':row['jan'],'title':'サイズ/L '+row['name_ja'].replace('(サイズ/M)','')})[0]
    row={'jan':'4589838312005','name_ja':'缶バッジ「ピアプロキャラクターズ」05/誕生日ver. ブラインド(全6種)(グラフアート)','spec':'吧唧整盒232'}
    assert identity(row,{'jan':row['jan'],'title':'『ピアプロキャラクターズ』缶バッジ 05/誕生日ver. BOX(全6種)(グラフアート)'})[0]
    assert not identity(row,{'jan':row['jan'],'title':'『ピアプロキャラクターズ』缶バッジ 05/誕生日ver. BOX(全8種)(グラフアート)'})[0]
    row={'jan':'4570215806804','name_ja':'アクリルスタンド「TVアニメ『正反対な君と僕』」07/鈴木 夏祭りver.(描き下ろしイラスト)','spec':'立牌07/鈴木16'}
    assert identity(row,{'jan':row['jan'],'title':'『正反対な君と僕』アクリルスタンド07/鈴木 夏祭りver.(描き下ろしイラスト)'})[0]
    assert not identity(row,{'jan':row['jan'],'title':'『正反対な君と僕』アクリルスタンド07/佐藤 夏祭りver.(描き下ろしイラスト)'})[0]
    from unittest.mock import patch
    for code,expected in [(403,'blocked_403'),(429,'rate_limited_429')]:
        client=Client('anime_store')
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://test.invalid',code,'fixture',{},None)) as mocked:
            result=client.get('https://test.invalid/fixture')
            assert result['error']==expected
            assert client.get('https://test.invalid/second')['error']==expected
            assert mocked.call_count==1
    client=Client('anime_store')
    with patch('urllib.request.urlopen',side_effect=TimeoutError('fixture')):
        assert client.get('https://test.invalid/timeout')['error']=='network_error'
        assert not client.stopped
    print('20 material/identity/network scenarios passed')

def probe_target_batch():
    samples=[]
    for path in (REPORT/'responses/anime_store').glob('*.txt'):
        d=json.loads(path.read_text(encoding='utf-8'))
        if d.get('id'):samples.append(d)
        if len(samples)==2:break
    ids=','.join(str(d['id']) for d in samples)
    response=Client('anime_store').get('https://anime-store.jp/products.json?limit=2&ids='+ids)
    products=response.get('data',{}).get('products',[])
    result={'requested_ids':[d['id'] for d in samples],'returned_ids':[d.get('id') for d in products],
            'filter_works':bool(products) and {d['id'] for d in products}=={d['id'] for d in samples},
            'attempt':{k:v for k,v in response.items() if k not in ('data','text')}}
    save(REPORT/'target-batch-probe.json',result);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int);p.add_argument('--test',action='store_true');p.add_argument('--probe-target-batch',action='store_true');p.add_argument('--exclude-file');p.add_argument('--only-file');p.add_argument('--skip-site',action='append');p.add_argument('--recover-colleize-failed',action='store_true');args=p.parse_args()
    if args.test:tests()
    elif args.probe_target_batch:probe_target_batch()
    else:Batch(args.limit,args.exclude_file,args.only_file,args.skip_site,args.recover_colleize_failed).run()
