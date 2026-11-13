"""Explicit-file, hash-verified local copies; originals and old manifests never change."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,os,shutil

ROLES={'raw':'01_日方原件','reference':'02_业务参考','process':'03_过程与发出版本',
       'code':'04_程序与规则','evidence':'05_索引与交接'}

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # A published index is immutable; explicit new folders represent new freezes.
    with path.open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)

def archive_files(request, destination):
    destination=Path(destination).resolve()
    if destination.exists():
        raise ValueError('归档目录已存在，不能覆盖旧资产')
    if not isinstance(request,dict) or request.get('schema')!='a-stage-explicit-assets/1':
        raise ValueError('资产清单类型不符')
    entries=request.get('files',[])
    if not entries:
        raise ValueError('资产清单为空')
    checked=[];seen={}
    for item in entries:
        p=Path(item['path']).resolve(strict=True);role=item['role']
        if role not in ROLES or not p.is_file() or p.is_relative_to(destination):
            raise ValueError('资产类型或路径无效')
        identity=(str(p),role)
        if identity in seen:
            if seen[identity]!=item['sha256']:
                raise ValueError('同一路径存在冲突版本声明')
            continue
        seen[identity]=item['sha256']
        h=sha(p)
        if h!=item['sha256']:
            raise ValueError('来源版本发生变化：'+str(p))
        checked.append((item,p,h))
    destination.mkdir(parents=True)
    objects={};records=[]
    for item,p,h in checked:
        if h not in objects:
            # Same content is one asset, with all physical aliases listed below.
            target=destination/ROLES[item['role']]/(p.stem+'__'+h[:12]+p.suffix)
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.resolve().is_relative_to(destination):
                raise ValueError('归档路径越界')
            temp=target.with_name(target.name+'.copying')
            with temp.open('xb') as dst,p.open('rb') as src:
                shutil.copyfileobj(src,dst)
            if sha(temp)!=h or sha(p)!=h:
                raise ValueError('复制期间来源发生变化，归档未发布')
            os.replace(temp,target);objects[h]=target.relative_to(destination).as_posix()
        records.append({'original_path':str(p),'archive_relative_path':objects[h],
                        'sha256':h,'role':item['role'],'usage':item.get('usage'),
                        'read_only_reference':True,'same_sha_is_not_independent_evidence':True})
    # Recheck every source, including aliases, before publishing the index.
    if any(sha(p)!=h for _,p,h in checked):
        raise ValueError('归档前来源版本改变')
    manifest={'schema':'a-stage-asset-archive/1','created_utc':datetime.now(timezone.utc).isoformat(),
              'batch_label':request.get('batch_label'),'archive_root':str(destination),
              'physical_entries':len(records),'unique_contents':len(objects),'records':records,
              'source_files_moved_or_deleted':False,'business_approval':False}
    verify_archive(manifest,destination)
    write_json(destination/'资产索引.json',manifest)
    return manifest

def verify_archive(manifest,root=None):
    root=Path(root or manifest['archive_root']).resolve(strict=True)
    if manifest.get('schema')!='a-stage-asset-archive/1':
        raise ValueError('归档索引类型不符')
    for rec in manifest['records']:
        relative=Path(rec['archive_relative_path'])
        if relative.is_absolute():
            raise ValueError('归档成员必须为相对路径')
        p=(root/relative).resolve(strict=True)
        if not p.is_relative_to(root) or sha(p)!=rec['sha256']:
            raise ValueError('归档越界或内容变化')
    return True

def resolve_archived(manifest,original_path,sha256,root=None):
    """No fallback to a same-named/newer-mtime file; exact old path+hash only."""
    root=Path(root or manifest['archive_root']).resolve(strict=True)
    match=[r for r in manifest['records'] if r['original_path']==str(Path(original_path).resolve()) and r['sha256']==sha256]
    if not match:
        raise ValueError('指定原路径及版本未归档')
    p=(root/match[0]['archive_relative_path']).resolve(strict=True)
    if not p.is_relative_to(root) or sha(p)!=sha256:
        raise ValueError('归档文件校验失败')
    return p
