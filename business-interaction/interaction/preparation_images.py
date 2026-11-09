"""Bounded procurement-image fetch with source and cached-content hashes."""
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,urlopen
import hashlib,io
from . import digest,save

def fetch(url,folder,allowed_hosts):
    from PIL import Image,ImageOps
    if urlparse(url).scheme!='https' or urlparse(url).hostname not in allowed_hosts:return {'status':'denied','url':url}
    folder=Path(folder);folder.mkdir(exist_ok=True);uid=hashlib.sha256(url.encode()).hexdigest()
    try:
        with urlopen(Request(url,headers={'User-Agent':'JPMaterialQuery image reference','Accept':'image/*'}),timeout=15) as response:
            if urlparse(response.url).hostname not in allowed_hosts:raise ValueError('image redirect outside approved hosts')
            raw=response.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:raise ValueError('image exceeds 16MiB')
        image=ImageOps.exif_transpose(Image.open(io.BytesIO(raw)));image.load();image=image.convert('RGB');image.thumbnail((800,800))
        file=folder/(uid+'.jpg');image.save(file,'JPEG',quality=90,optimize=True)
        result={'status':'downloaded','url':url,'file':str(file),'sha256':digest(file),'source_sha256':hashlib.sha256(raw).hexdigest(),'width':image.width,'height':image.height}
    except Exception as exc:result={'status':'failed','url':url,'reason':str(exc)}
    save(folder/(uid+'.json'),result);return result
