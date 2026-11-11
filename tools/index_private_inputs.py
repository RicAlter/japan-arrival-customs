"""Extend a private manifest with existing transitive JSON file references.

Read-only sources; a NEW manifest is written. No credentials are copied to Git.
"""
from pathlib import Path
import argparse, collections, json
from freeze_unified import sha, save

def index(source, output):
    target=Path(output)
    if target.exists():raise ValueError('Private manifest output must be new')
    m=json.loads(Path(source).read_text('utf8'));found={};queue=collections.deque(Path(x['path']) for x in m['files'])
    queued={str(p.resolve()) for p in queue};checked_refs=set();opaque=[]
    def strings(v):
        if isinstance(v,str):yield v
        elif isinstance(v,list):
            for x in v:yield from strings(x)
        elif isinstance(v,dict):
            for k,x in v.items():yield k;yield from strings(x)
    while queue:
        p=queue.popleft().resolve();key=str(p)
        if key in found:continue
        found[key]={'path':key,'sha256':sha(p)}
        if len(found)%100==0:print('Indexed',len(found),'sources; remaining',len(queue),flush=True)
        if p.suffix.lower()!='.json':continue
        # Historical content-addressed records can be hundreds of MiB each.
        # Hash them verbatim; inspect dependency/config manifests separately.
        if p.stat().st_size>8*1024*1024:
            opaque.append(key);continue
        value=json.loads(p.read_text('utf-8-sig'))
        for text in strings(value):
            # Only declared absolute file references, never scan a disk/directory.
            if len(text)>3 and text[1]==':' and text[2] in '/\\':
                if text in checked_refs:continue
                checked_refs.add(text)
                q=Path(text)
                try:
                    absolute=str(q.resolve())
                    if absolute not in queued and q.is_file():queue.append(q);queued.add(absolute)
                except (OSError,ValueError):pass
    m['files']=sorted(found.values(),key=lambda x:x['path']);m['opaque_history_records']=opaque
    m['scope']='Pinned session files plus existing references from bounded dependency/config JSON; large immutable history records are SHA-only, not recursively parsed. No directory scan or source writes.'
    save(target,m);return {'files':len(found),'manifest_sha256':sha(target)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(index(a.manifest,a.output)))
