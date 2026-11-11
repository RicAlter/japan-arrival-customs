"""Freeze source from this checkout without touching its guarded dependencies."""
from pathlib import Path
import argparse, base64, hashlib, json, shutil, subprocess, sys, zipfile

REPO = Path(__file__).resolve().parents[1]

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def save(p, v):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(v, ensure_ascii=False, indent=2)+'\n', encoding='utf8')

def freeze(output):
    out = Path(output).resolve()
    if out.exists():
        raise ValueError('Use a new freeze directory; existing snapshots are immutable')
    out.mkdir(parents=True)
    src = out/'src'
    names = subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'], cwd=REPO).decode().split('\0')
    for name in sorted(set(filter(None, names))):
        p = REPO/name
        if p.is_file():
            q = src/name
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, q)
    locks = {}
    for name in ['business-loop/dependency-lock.json','catalogue-pack-loop/reuse-lock.json']:
        locks.update(json.loads((src/name).read_text('utf8'))['files'])
    snapshots = json.loads((src/'repro/guarded-text-snapshots.json').read_text('utf8'))
    restored = []
    for name, expected in locks.items():
        p = src/name
        b = p.read_bytes()
        if sha(p) == expected:
            continue
        lf = b.replace(b'\r\n', b'\n')
        candidates = [lf, lf.replace(b'\n', b'\r\n')]
        if name in snapshots:
            candidates.append(base64.b64decode(snapshots[name]['base64']))
        replacement = next((x for x in candidates if hashlib.sha256(x).hexdigest() == expected), None)
        if replacement is None:
            raise ValueError('Cannot reproduce guarded dependency: '+name)
        p.write_bytes(replacement)
        restored.append(name)
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    dirty = subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True).strip()
    files = {p.relative_to(src).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size}
             for p in sorted(src.rglob('*')) if p.is_file()}
    manifest = {'schema':'unified-source-freeze/1','commit':head,'working_copy_changes':bool(dirty),
                'files':files,'guarded_dependencies':len(locks),'guarded_bytes_restored':restored}
    save(out/'source-manifest.json',manifest)
    with zipfile.ZipFile(out/'source.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for n in files:
            info=zipfile.ZipInfo(n,date_time=(2026,11,11,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,(src/n).read_bytes())
    skill=out/'skill'
    shutil.copytree(src/'business-interaction/workbuddy/japan-arrival-customs-trial',skill)
    save(skill/'runtime.json',{'python':sys.executable,'entry':str(src/'business-interaction/run.py'),
        'source_root':str(src),'source_manifest':str(out/'source-manifest.json'),
        'source_manifest_sha256':sha(out/'source-manifest.json'),'session':None,'installed':False,'formal_output':False})
    with zipfile.ZipFile(out/'skill.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(skill.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(skill))
    save(out/'SHA256.json',{n:sha(out/n) for n in ['source-manifest.json','source.zip','skill.zip']})
    return {'source':str(src),'commit':head,'source_manifest_sha256':sha(out/'source-manifest.json'),
            'guarded_dependencies':len(locks),'working_copy_changes':bool(dirty)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    print(json.dumps(freeze(p.parse_args().output),ensure_ascii=False))
