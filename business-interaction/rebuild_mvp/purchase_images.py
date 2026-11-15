"""Audited procurement image observations and bounded, cached downloads."""
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler
import hashlib, io, re, zipfile, posixpath
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps
from .xlsxio import iter_rows, sheet_info
from .sources import validate_source, norm, code
from .service import digest, save_json

Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/package/2006/relationships}'
RID='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
X='{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'

def public_url(url):
    import ipaddress, socket
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise ValueError('IMAGE_URL_INVALID: 非公开HTTP图片链接')
    for value in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(value[4][0]).is_global:
            raise ValueError('IMAGE_URL_INVALID: 非公开网络地址')
    return url

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def image_rows(path, sheet):
    member=next(s['path'] for s in sheet_info(path) if s['name']==sheet)
    relname=posixpath.dirname(member)+'/_rels/'+posixpath.basename(member)+'.rels'
    result=set()
    with zipfile.ZipFile(path) as z:
        if relname not in z.namelist():return result
        for rel in ET.fromstring(z.read(relname)):
            if not rel.get('Type','').endswith('/drawing'):continue
            target=posixpath.normpath(posixpath.join(posixpath.dirname(member),rel.get('Target',''))).lstrip('/')
            for anchor in ET.fromstring(z.read(target)):
                if anchor.find('.//'+X+'pic') is None:continue
                row=anchor.findtext(X+'from/'+X+'row')
                if row is not None:result.add(int(row)+1)
    return result

def hyperlinks(path,member):
    """Read hyperlink targets, without executing formulas or external workbooks."""
    out={}; relname=posixpath.dirname(member)+'/_rels/'+posixpath.basename(member)+'.rels'
    with zipfile.ZipFile(path) as z:
        rels={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read(relname))} if relname in z.namelist() else {}
        for h in ET.fromstring(z.read(member)).iter(Q+'hyperlink'):
            if h.get(RID+'id') in rels:out[h.get('ref')]=rels[h.get(RID+'id')]
    return out

ALIASES={'image':['单品图片','图片链接','商品图片链接'], 'code':['条形码','商品编码','JAN','JC'],
         'sku':['SKU关联编码','SKU编码','SKU'], 'yd':['YD编码','YD'], 'spec':['单品名称','规格']}

def observations(sources, targets):
    records=[];audit=[]
    for config in sources:
        validate_source(config)
        if config['role']!='purchase_list':raise ValueError('SOURCE_FORBIDDEN: 图片只取实际采购清单')
        path=Path(config['path']);source_sha=digest(path)
        for sheet in sheet_info(path):
            if config.get('sheets') and sheet['name'] not in config['sheets']:continue
            head=list(__import__('itertools').islice(iter_rows(path,sheet['name']),40));best=None
            for row in head:
                mapping={}
                for key,aliases in ALIASES.items():
                    wanted=config.get('field_map',{}).get('image_url' if key=='image' else key)
                    if wanted:
                        wanted=wanted if isinstance(wanted,list) else [wanted]
                        cols=[]
                        for w in wanted:
                            matches=[c for c,v in row['values'].items() if norm(v)==norm(w)]
                            if not matches and re.fullmatch('[A-Z]+',str(w)):matches=[w]
                            cols+=matches
                    else:cols=[c for c,v in row['values'].items() if norm(v) in aliases]
                    if cols:mapping[key]=cols
                score=len(mapping)
                if 'image' in mapping and ('code' in mapping or 'sku' in mapping) and (best is None or score>best[0]):best=(score,row['row'],mapping)
            if best is None:
                audit.append({'file':str(path),'sheet':sheet['name'],'error':'FIELD_MAPPING_AMBIGUOUS'});continue
            _,header,mapping=best
            if len(mapping['image'])!=1:
                audit.append({'file':str(path),'sheet':sheet['name'],'error':'FIELD_MAPPING_AMBIGUOUS'});continue
            links=hyperlinks(path,sheet['path'])
            for row in iter_rows(path,sheet['name']):
                if row['row']<=header:continue
                values=row['values'];col=mapping['image'][0];url=links.get(col+str(row['row']),values.get(col,''))
                if not str(url).startswith(('http://','https://')):
                    formula=row.get('formulas',{}).get(col,'');m=re.match(r'\s*HYPERLINK\("([^"]+)"',formula,re.I)
                    url=m[1] if m else ''
                if not url:continue
                codes=[code(values.get(c)) for key in ('code','sku') for c in mapping.get(key,[])]
                if not any(c in targets or c.startswith('DG') and c[2:] in targets for c in codes):continue
                yd=next((str(values.get(c,'')) for c in mapping.get('yd',[]) if values.get(c)),'')
                records.append({'source':str(path),'source_sha256':source_sha,'version':config.get('version'), 'sheet':sheet['name'],'row':row['row'],'column':col,'codes':sorted(set(codes)), 'yd':yd,'url':str(url).strip(),'spec':next((str(values.get(c,'')) for c in mapping.get('spec',[]) if values.get(c)),'')})
    return records,audit

def match(rows, records, occupied):
    result={}
    for row in rows:
        n=row['row'];v=row['values'];jan=code(v.get('C'))
        if n in occupied:continue
        yds=set(re.findall(r'YD[A-Za-z0-9]+',str(v.get('Q','')),re.I))
        exact=[r for r in records if jan in r['codes']]
        if not exact:
            exact=[r for r in records if 'DG'+jan in r['codes'] and r['yd'] in yds]
        # An explicit current YD constrains adoption; do not silently fall back
        # to a different version when a matching YD is absent.
        selected=[r for r in exact if r['yd'] in yds] if yds else exact
        urls=sorted({r['url'] for r in selected})
        reason='采购清单未找到对应商品图片链接' if not urls else '图片链接不唯一，待核对' if len(urls)>1 else ''
        if exact and not selected:reason='编码命中但YD不一致，待核对'
        result[str(n)]={'code':jan,'status':'queued' if len(urls)==1 else 'unresolved','reason':reason,'url':urls[0] if len(urls)==1 else None,'evidence':selected}
    return result

def download(url, root, policy):
    key=hashlib.sha256(url.encode()).hexdigest();folder=Path(root)/'image-cache';folder.mkdir(exist_ok=True)
    path=folder/(key+'.png');receipt=folder/(key+'.json')
    if receipt.exists():
        value=__import__('json').loads(receipt.read_text(encoding='utf8'))
        if path.exists() and digest(path)==value['sha256']:return value
    public_url(url)
    with build_opener(SafeRedirect()).open(Request(url,headers={'User-Agent':'JapanArrival/1'}),timeout=policy['image_timeout_seconds']) as response:
        data=response.read(policy['max_image_bytes']+1)
        if len(data)>policy['max_image_bytes']:raise ValueError('IMAGE_TOO_LARGE')
        if 'text/html' in response.headers.get('Content-Type',''):raise ValueError('IMAGE_ACCESS_BLOCKED: 返回网页或验证页')
        im=Image.open(io.BytesIO(data))
        if im.width*im.height>40_000_000:raise ValueError('IMAGE_TOO_LARGE')
        im.load();im=ImageOps.exif_transpose(im)
        if im.mode not in ('RGB','RGBA'):im=im.convert('RGB')
        tmp=path.with_suffix('.tmp');im.save(tmp,format='PNG');tmp.replace(path)
        value={'url':url,'final_url':response.geturl(),'path':str(path.resolve()),'sha256':digest(path),'width':im.width,'height':im.height}
        save_json(receipt,value);return value
