"""Read-only golden source/evidence inventory. Does not invoke live services."""
import argparse,hashlib,json,pathlib,sys,zipfile,xml.etree.ElementTree as ET
from collections import Counter
from release import sha,save
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    w=pathlib.Path(a.workspace).resolve();out=pathlib.Path(a.output).resolve();e=out/'governance-release'
    pointer=pathlib.Path('D:/日本到货海关报单数据/06_统一商品资料库/active/release.json')
    release=json.loads(pointer.read_text(encoding='utf8'));assert sha(release['database_path'])==release['database_sha256']
    save(e/'database-release.json',{'pointer':str(pointer),'pointer_sha256':sha(pointer),'release':release,'verified':True})
    samples=[('KMT20261002',w/'outputs/KMT20261002_JAN数量比对_20261109_v1/session.json'),('KMT20261003',w/'outputs/KMT20261003_关联材质原文修复_20261110/session.json')]
    wb=json.loads((w/'reports/workbuddy-native-phase1-20261109/user-native-acceptance-readback.json').read_text(encoding='utf8'))
    samples.append(('KMT20261101',pathlib.Path(wb['session'])))
    golden=[];all_sources={}
    for batch,session in samples:
        c=json.loads(session.read_text(encoding='utf8'));f=pathlib.Path(c.get('prepared_file') or wb['current_file']);inputfile=pathlib.Path(c.get('source',f));stats={}
        with zipfile.ZipFile(f) as z:
            names=z.namelist();stats['media_parts']=sum(n.startswith('xl/media/') for n in names)
            stats['formula_nodes']=sum(z.read(n).count(b'<f') for n in names if n.startswith('xl/worksheets/') and n.endswith('.xml'))
        sources=[]
        fixed=pathlib.Path(c['background'])/'fixed-inputs'
        for p in fixed.rglob('*') if fixed.exists() else []:
            if p.is_file() and p.suffix.lower() in {'.xlsx','.json','.sqlite3'}:
                item={'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size};sources.append(item);all_sources[str(p)]=item
        golden.append({'batch':batch,'session':str(session),'session_sha256':sha(session),'input':str(inputfile),'input_sha256':sha(inputfile),'current_file':str(f),'current_sha256':sha(f),'stats':stats,'sources':sources,'scope':'read-only source preservation; no prepare/current/confirm on historical session'})
    save(e/'golden-samples.json',golden)
    # Validate preserved historical material snapshots using the integrated reader.
    sys.path.insert(0,str(out/'src/github-progress-rc8-20261028/business-interaction'))
    import interaction.material_review as mr
    mr.WORKSPACE=w
    req=json.loads((w/'reports/dual-source-material-integration-20261109/request.json').read_text(encoding='utf8'))
    manifests=[str(w/p) for p in req['evidence_manifests']]
    evidence,rejected=mr.read_evidence(manifests)
    save(e/'historical-material-replay.json',{'jan_with_evidence':len(evidence),'accepted_evidence_records':sum(map(len,evidence.values())),'rejected':rejected,'source_manifests':[{'path':p,'sha256':sha(p)} for p in manifests],'network_requests':0})
    archive=[]
    for base in [w/'outputs',w/'reports']:
        for p in base.iterdir():
            if p.is_dir() and any(t in p.name for t in ['候选','冻结','材质','material','KMT20261002','KMT20261003','KMT20261101','workbuddy','business-loop','phase1','enrichment','return']):
                archive.append({'path':str(p),'retention':'retain_in_place_read_only_index','recoverability':'original path retained; runtime/source manifest and fixed inputs must be verified before reuse'})
    save(e/'archive-index.json',{'entries':archive,'physical_moves':0,'deletions':0,'reason':'live sessions and source manifests still depend on absolute paths'})
    save(e/'preservation-before.json',all_sources)
    print(json.dumps({'golden_batches':len(golden),'source_files':len(all_sources),'historical_evidence':sum(map(len,evidence.values())),'rejected_evidence':len(rejected),'archive_entries':len(archive)},ensure_ascii=False))
if __name__=='__main__':main()
