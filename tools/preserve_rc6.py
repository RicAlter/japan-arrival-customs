"""Archive reviewed rc.6 working changes without touching any source or database."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / 'reports' / 'rc7' / 'rc6-preservation'

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = set(git('diff', '--name-only', '-z').decode().split('\0'))
    files.update(git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0'))
    files.discard('')
    files.add('tools/preserve_rc6.py')
    manifest = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(files)}
    target = OUT / 'rc6-local-changes.zip'
    if target.exists():
        raise RuntimeError('Preservation already exists; do not overwrite')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.writestr(name, (ROOT / name).read_bytes())
        archive.writestr('working-tree.patch', git('diff', '--binary'))
    with zipfile.ZipFile(target) as archive:
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == sha for name, sha in manifest.items())
    receipt = {'base': git('rev-parse', 'HEAD').decode().strip(),
               'branch': git('branch', '--show-current').decode().strip(),
               'files': manifest, 'archive': str(target),
               'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
               'archive_reopened': True, 'business_data_included': False}
    (OUT / 'manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))

if __name__ == '__main__':
    main()
