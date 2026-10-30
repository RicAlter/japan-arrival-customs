"""Read capability evidence from protected host storage, pinned to installed code."""
import hashlib
import json
from pathlib import Path

CAPABILITIES = ('native_trigger', 'excel_display_save', 'D1_rejection')

def source_manifest_hash():
    from .core import digest
    skill = Path(__file__).resolve().parents[2]
    manifest = {p.relative_to(skill).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(skill.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
                and p.suffix != '.pyc' and p.name != 'installed-release.json'}
    return digest(manifest)

def capabilities(root):
    result = {name: {'state': 'unverified'} for name in CAPABILITIES}
    try:
        receipt = json.loads((Path(root) / 'security' / 'workbuddy_acceptance.json').read_text(encoding='utf-8'))
        if receipt.get('schema') != 'japan-arrival/workbuddy-acceptance-1':return result
        if receipt.get('source_manifest_sha256') != source_manifest_hash():return result
        if not receipt.get('host_version') or not receipt.get('package_sha256'):return result
        for name in CAPABILITIES:
            item = receipt.get('capabilities', {}).get(name, {})
            evidence = item.get('evidence', [])
            valid = bool(evidence) and bool(item.get('tested_at'))
            for entry in evidence:
                path = Path(entry['path']).resolve(strict=True)
                valid = valid and hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
            if valid and item.get('state') in ('passed', 'failed'):
                result[name] = {'state': item['state'], 'tested_at': item['tested_at'],
                                'host_version': receipt['host_version'], 'package_sha256': receipt['package_sha256']}
    except (OSError, ValueError, TypeError, KeyError):
        # Invalid receipt never grants a capability or approves business data.
        return {name: {'state': 'unverified'} for name in CAPABILITIES}
    return result
