"""Verify full website queue and R-only decoration with captured real HTML, plus bounded live probe."""
from pathlib import Path
import sys,io,zipfile,xml.etree.ElementTree as ET,json
from interaction import load,save,digest
from interaction.service import Service
from interaction.website_query import query_materials
W=Path(__file__).resolve().parents[2];R=W/'reports/first-phase-upgrade-20261106';request=load(R/'prepare-request.json');root=Path(request['output']);config=load(root/'session.json');s=Service(config)
file=Path(s.deliver()['business_files'][0]);before=file.read_bytes()
scope={'queue_sha256':digest(Path(config['background'])/'website-queue.json'),'authorized':True,'plugin':str(W/'reports/material-plugin-20261106/vendor/jp_material_query'),'snapshots':str(R/'snapshots')}
if '--live' in sys.argv:
    review=load(W/'reports/material-plugin-20261106/authorized-test-20261106/access-review.json')
    review['hosts']={k:v for k,v in review['hosts'].items() if k=='anime-store.jp'};review['request_budget']=1
    review['approval']='2026-11-06 user approved full product website review; this implementation probe is restricted to one public product request.'
    save(R/'live-access-review.json',review);scope.update(rows=[6],allow_online=True,access_review=str(R/'live-access-review.json'))
if '--missing-snapshot' in sys.argv:scope.update(rows=[6],snapshots=str(R/'missing-snapshots'))
result=query_materials(root/'session.json',scope);after=file.read_bytes();ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(io.BytesIO(before)) as a,zipfile.ZipFile(io.BytesIO(after)) as b:
    for n in a.namelist():
        if n!='xl/worksheets/sheet1.xml':assert a.read(n)==b.read(n),n
    def cells(data):return {c.get('r'):ET.tostring(c) for c in ET.fromstring(data).findall('.//x:c',ns)}
    ca,cb=cells(a.read('xl/worksheets/sheet1.xml')),cells(b.read('xl/worksheets/sheet1.xml'));assert ca.keys()==cb.keys()
    changed=[k for k in ca if ca[k]!=cb[k]];assert all(k.startswith('R') for k in changed)
v=s.engine.basics.read_current(s.engine.bid)
returned=s.upload(file,kind='basics',reference='SYNTHETIC full website reference return',selection={'save_changes':[],'confirm_fields':[],'adopt_candidates':[],'evidence':{}})
assert returned.get('proposed_changes',0)==0
results=load(Path(config['background'])/'website-results.json')
report={**result,'only_R_changed':True,'changed_cells':changed,'reference_return_changes':0,'business_confirmations':v['confirmed_field_count'],
        'full_online_run_completed':False,'live_probe':'--live' in sys.argv}
if '--live' not in sys.argv and '--missing-snapshot' not in sys.argv:assert result['queried_rows']==1275 and result['found_rows']>=2
if '--missing-snapshot' in sys.argv:assert not changed;report['prior_R_provenance_preserved_after_failure']=True
save(R/('website-live-probe.json' if '--live' in sys.argv else 'website-failure.json' if '--missing-snapshot' in sys.argv else 'website-offline.json'),report)
print(json.dumps(report,ensure_ascii=False))
