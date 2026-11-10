"""Bounded media validation for registered large basic-data returns.

Original uploads and pictures are never rewritten. Only the legacy parser's
in-memory comparison view substitutes already hash-verified picture payloads.
All XML, cell data, formulas, links and version checks remain with original A03.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from hashlib import sha256
import base64,io,posixpath,re,zipfile,xml.etree.ElementTree as ET
from . import Rejected,load,save,digest

MAX_FILE=256*1024*1024
MAX_EXPANDED=384*1024*1024
MAX_XML=64*1024*1024
MAX_IMAGE=16*1024*1024
MAX_PARTS=10000
Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
D='{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
# Parser-only placeholder; never written to an upload, archive or business file.
PIXEL=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
ACTIVE=ContextVar('registered_large_return',default=None)

def _headers(data):
    if len(data)>MAX_FILE:raise Rejected('基础资料回传超过256MiB受控上限')
    try:
        z=zipfile.ZipFile(io.BytesIO(data));infos=z.infolist();names=[i.filename for i in infos]
        if len(infos)>MAX_PARTS or len(names)!=len(set(names)):raise Rejected('Excel部件重复或数量超限')
        if sum(i.file_size for i in infos)>MAX_EXPANDED:raise Rejected('Excel解压范围超过384MiB受控上限')
        for i in infos:
            if i.flag_bits&1:raise Rejected('不接受加密Excel部件')
            raw_name=i.orig_filename
            if '\\' in raw_name or raw_name.startswith('/') or ':' in raw_name or '..' in raw_name.split('/'):
                raise Rejected('Excel部件路径无效')
            if any(t in i.filename.lower() for t in ('vbaproject','embeddings/','connections.xml','querytables/')):
                raise Rejected('不接受宏、外部连接或嵌入对象')
        return z,infos
    except (zipfile.BadZipFile,OSError) as exc:raise Rejected('无法安全读取Excel压缩包') from exc

def has_basics_marker(file):
    # Detect the stage without inflating every picture into a dictionary.
    file=Path(file)
    if file.stat().st_size>MAX_FILE:raise Rejected('基础资料回传超过256MiB受控上限')
    with zipfile.ZipFile(file) as z:
        if len(z.infolist())>MAX_PARTS:raise Rejected('Excel部件数量超限')
        try:info=z.getinfo('docProps/custom.xml')
        except KeyError:return False
        if info.file_size>1024*1024:raise Rejected('Excel版本属性超限')
        raw=z.read(info)
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise Rejected('不接受XML实体声明')
        return b'CustomsAStageExportVersion' in raw

def _resolve(member,target):
    if target.startswith('/'):path=posixpath.normpath(target).lstrip('/')
    else:path=posixpath.normpath(posixpath.join(posixpath.dirname(member),target))
    if path.startswith('../') or ':' in path:raise Rejected('Excel关系路径无效')
    return path

def _rels(xml,member):
    name=posixpath.join(posixpath.dirname(member),'_rels',posixpath.basename(member)+'.rels')
    if name not in xml:return {}
    return {r.get('Id'):(_resolve(member,r.get('Target','')),r.get('TargetMode')) for r in ET.fromstring(xml[name])}

def _pictures(xml,media):
    workbook=ET.fromstring(xml['xl/workbook.xml']);bookrels=_rels(xml,'xl/workbook.xml');rows=[];used=set()
    for sheet in workbook.find(Q+'sheets'):
        member=bookrels[sheet.get(R+'id')][0];sheetxml=ET.fromstring(xml[member]);links=_rels(xml,member)
        for drawing in sheetxml.findall(Q+'drawing'):
            target,external=links[drawing.get(R+'id')]
            if external=='External':raise Rejected('不接受外部图片关系')
            rels=_rels(xml,target)
            for anchor in ET.fromstring(xml[target]):
                for blip in anchor.findall('.//'+A+'blip'):
                    if blip.get(R+'link'):raise Rejected('不接受外部图片')
                    image,mode=rels[blip.get(R+'embed')]
                    origin=anchor.find(D+'from')
                    if mode=='External' or image not in media or origin is None:raise Rejected('图片归属或锚点不可核验')
                    row=origin.find(D+'row');col=origin.find(D+'col')
                    if row is None or col is None:raise Rejected('图片锚点不完整')
                    rows.append((sheet.get('name'),int(row.text),int(col.text),media[image]));used.add(media[image])
    return sorted(rows),sorted(set(media.values())-used)

def inspect_package(data):
    """Scan the original package; stream image hashes before parser reduction."""
    xml={};media={};xml_bytes=0;out=io.BytesIO()
    z,infos=_headers(data)
    try:
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as reduced:
            for info in infos:
                name=info.filename
                if info.is_dir():
                    reduced.writestr(name,b'')
                elif name.startswith('xl/media/'):
                    if info.file_size>MAX_IMAGE:raise Rejected('单张图片超过16MiB受控上限')
                    h=sha256()
                    with z.open(info) as stream:
                        while chunk:=stream.read(1024*1024):h.update(chunk)
                    media[name]=h.hexdigest();reduced.writestr(name,PIXEL)
                else:
                    xml_bytes+=info.file_size
                    if xml_bytes>MAX_XML:raise Rejected('Excel非图片内容超过64MiB受控上限')
                    raw=z.read(info)
                    if name.endswith(('.xml','.rels')):
                        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise Rejected('不接受XML实体声明')
                        xml[name]=raw
                    reduced.writestr(name,raw)
        pictures,unreferenced=_pictures(xml,media)
        return {'view':out.getvalue(),'pictures':pictures,'unreferenced_media':unreferenced,'file_bytes':len(data),
                'expanded_bytes':sum(i.file_size for i in infos),'nonimage_bytes':xml_bytes,
                'media_parts':len(media),'picture_anchors':len(pictures)}
    except Rejected:raise
    except Exception as exc:raise Rejected('无法核验Excel图片关系：'+type(exc).__name__) from exc
    finally:z.close()

class Guard:
    def __init__(self,config,engine,file):
        self.config=config;self.engine=engine;self.views={};self.receipts=[]
        state=engine.store.load(engine.bid);baseline=engine.basics._baseline(state)[0]
        from . import get
        reg=get(engine.root,baseline['registration_ref'])
        if config.get('schema')!='prepared-basics-session/1' or reg.get('stage1_policy',{}).get('registered_output_columns')!=20:
            raise Rejected('大文件回传仅支持本批已登记20列基础资料表')
        issued=engine.root/'objects'/(baseline['copy_sha256']+'.xlsx')
        if digest(issued)!=baseline['copy_sha256']:raise Rejected('已登记底稿摘要变化')
        checked=inspect_package(issued.read_bytes());self.expected=checked['pictures'];self.original_unused=set(checked['unreferenced_media'])
        if not self.expected:raise Rejected('没有可核验的已登记原图，不启用大文件图片通道')
        self.views[baseline['copy_sha256']]=checked['view']
        for known in baseline['known']:
            if known['copy_sha256'] not in self.views:
                p=engine.root/'objects'/(known['copy_sha256']+'.xlsx')
                if digest(p)!=known['copy_sha256']:raise Rejected('已知底稿摘要变化')
                self.views[known['copy_sha256']]=inspect_package(p.read_bytes())['view']
        self.authorize(file)

    def authorize(self,file):
        file=Path(file)
        if file.stat().st_size>MAX_FILE:raise Rejected('基础资料回传超过256MiB受控上限')
        data=file.read_bytes();h=sha256(data).hexdigest();checked=inspect_package(data)
        if checked['pictures']!=self.expected:raise Rejected('原图内容、归属或锚点发生变化，拒绝回传')
        if set(checked['unreferenced_media'])-self.original_unused:raise Rejected('存在未登记的额外图片内容')
        if digest(file)!=h:raise Rejected('回传在核验期间变化')
        self.views[h]=checked['view']
        receipt={k:v for k,v in checked.items() if k not in {'view','pictures'}}
        receipt.update(original_sha256=h,comparison_view_sha256=sha256(checked['view']).hexdigest(),
                       original_images_verified=True,original_upload_untouched=True,
                       parser_only_view=True,limits={'file':MAX_FILE,'expanded':MAX_EXPANDED,'nonimage':MAX_XML,'image':MAX_IMAGE})
        self.receipts.append(receipt)
        back=Path(self.config['background'])/'large-return-checks';back.mkdir(exist_ok=True)
        save(back/(h+'.json'),receipt)

    def retain_original(self,file):
        """Keep raw bytes as well when R decoration needs a canonical copy."""
        data=Path(file).read_bytes();h=sha256(data).hexdigest()
        if h!=self.receipts[0]['original_sha256']:raise Rejected('回传在归一化期间变化')
        folder=Path(self.config['background'])/'large-return-inputs';folder.mkdir(exist_ok=True)
        target=folder/(h+'.xlsx')
        if target.exists():
            if digest(target)!=h:raise Rejected('原回传归档摘要变化')
        else:target.write_bytes(data)

def _install():
    import native_return.compare as compare
    if getattr(compare.read,'_registered_media_wrapper',False):return
    original=compare.read
    def read(data,*,trusted_external=None):
        guard=ACTIVE.get()
        if guard is None:return original(data,trusted_external=trusted_external)
        h=sha256(data).hexdigest()
        if h not in guard.views:raise Rejected('大文件比较内容不在本次已核验范围')
        return original(guard.views[h],trusted_external=trusted_external)
    read._registered_media_wrapper=True
    compare.read=read

def needed(engine,file):
    if Path(file).stat().st_size>64*1024*1024:return True
    with zipfile.ZipFile(file) as z:
        if sum(i.file_size for i in z.infolist())>128*1024*1024:return True
    state=engine.store.load(engine.bid)
    from . import get
    baseline=get(engine.root,state['a03']['baseline_ref'])
    issued=engine.root/'objects'/(baseline['copy_sha256']+'.xlsx')
    return issued.stat().st_size>64*1024*1024

def preview(config,engine,file,expected_hash):
    """Retain every original A03 rule, CAS and receipt; scope only image parsing."""
    _install()
    guard=Guard(config,engine,file);token=ACTIVE.set(guard)
    try:
        from .website_query import canonical_return
        canonical=canonical_return(config,file)
        if Path(canonical)!=Path(file):
            guard.retain_original(file)
            guard.authorize(canonical)
        result=engine.basics.preview_return(engine.bid,canonical,expected_hash=expected_hash)
        result['large_return_validation']=guard.receipts[-1]
        return result
    finally:ACTIVE.reset(token)
