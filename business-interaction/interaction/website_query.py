"""Full-row, identity-bound website material review; only R may change."""
from pathlib import Path
from datetime import datetime
import json,sys,shutil
from . import load,save,digest,key,Rejected,ROOT
from .preparation_workbook import update_cells
from material_providers.quality import material_quality

def assess_page(row,candidate,similarity):
    from adapter import assess,norm
    checked=assess(row,candidate,similarity)
    # Plugin token checks can mistake the procurement suffix in 吧唧5枚套组3
    # for a product version. The complete Japanese source name carries the
    # actual count/scope; require it verbatim (normalized) in the page title.
    name=norm(row.get('name_ja'));page=norm(candidate.get('name_ja'))
    if (checked['status']=='identity_unresolved' and not checked['reasons'] and len(name)>=8
        and name in page and str(candidate.get('jan_on_page'))==str(row['jan'])
        and checked['query_versions']==checked['page_versions']):
        checked={**checked,'status':'candidate_only','host_evidence':'on-page JAN + complete Japanese source name incl. version/count/scope; procurement suffix not a product version'}
    return checked

def query_materials(config_file,request):
    from openpyxl import load_workbook
    config=load(config_file);back=Path(config['background']);queuefile=back/'website-queue.json';queue=load(queuefile)
    if request.get('queue_sha256')!=digest(queuefile):raise Rejected('查询须绑定当前全量清单摘要')
    if request.get('authorized') is not True:raise Rejected('须有本批网站查询授权')
    rows=queue['rows'];scope=request.get('rows')
    if scope is not None:
        if not isinstance(scope,list) or len(set(scope))!=len(scope) or set(scope)-{r['row'] for r in rows}:raise Rejected('查询行范围不合法')
        rows=[r for r in rows if r['row'] in scope]
    plugin=Path(request['plugin']).resolve(strict=True)
    sys.path.insert(0,str(ROOT.parent/'material-query-adapter'))
    from adapter import Service as PluginService,assess
    siteconfig=back/'website-site-config';siteconfig.mkdir(exist_ok=True)
    policies=load(plugin/'config/sites.json')
    for site,v in policies['sites'].items():v['enabled']=site=='anime_store'
    save(siteconfig/'sites.json',policies)
    for p in (plugin/'config').iterdir():
        if p.is_file() and p.name!='sites.json':shutil.copyfile(p,siteconfig/p.name)
    online=bool(request.get('allow_online'))
    if online and not request.get('access_review'):raise Rejected('联网须先提供站点访问范围检查')
    svc=PluginService(plugin,config['database']['path'],rows,back/'website-plugin-state',config=siteconfig,access_review=request.get('access_review'))
    from jpmaterial.models import ProductQuery
    from jpmaterial.identity import name_similarity
    from .service import Service as BusinessService
    file=Path(BusinessService(config).deliver()['business_files'][0]);original=file.read_bytes();sha=digest(file)
    ws=load_workbook(file,read_only=True).worksheets[0];current=list(ws.values)
    previous=load(back/'website-results.json') if (back/'website-results.json').exists() else {'rows':{}}
    prior_overlay=load(back/'website-overlay.json').get('rows',{}) if (back/'website-overlay.json').exists() else {}
    results=previous['rows'];changes=[];dedupe={}
    plugin_sha=digest(plugin/'jpmaterial/engine.py')
    for row in rows:
        n=row['row'];v=current[n-1]
        if (str(v[2]),str(v[9] or ''),str(v[6] or ''),str(v[16] or ''))!=(row['jan'],row['name_ja'],str(row.get('spec') or ''),str(row.get('yd') or '')):
            results[str(n)]={'status':'identity_changed','binding':row};continue
        binding=key({k:row.get(k) for k in ['jan','name_ja','spec','yd']})
        evidence_binding=key({'identity':binding,'source_sha256':config['source_sha256'],
                              'database_sha256':config['database']['sha256'],'plugin_sha256':plugin_sha})
        query_mode='online' if online else 'snapshot:'+str(request.get('snapshots',''))
        if not request.get('refresh') and str(n) in results and results[str(n)].get('identity_key')==binding and results[str(n)].get('evidence_binding')==evidence_binding and results[str(n)].get('query_mode')==query_mode and results[str(n)].get('status')=='found':
            candidate=results[str(n)]
        else:
            candidate=dedupe.get(binding)
            if candidate is None:
                svc.cache.binding=evidence_binding
                q=ProductQuery(jan=row['jan'],name_ja=row['name_ja'],spec=row.get('spec') or '')
                try:
                    raw=svc.engine.query(q,allow_online=True,all_sites=True).to_dict() if online else svc.engine.query_snapshots(q,request.get('snapshots',back/'no-snapshots'),site_ids=['anime_store'],all_sites=True).to_dict()
                    good=[]
                    for c in raw['candidates']:
                        checked=assess_page(row,c,name_similarity);c['identity_assessment']=checked
                        if material_quality(c.get('material_original')) and material_quality(c.get('material_zh') or c.get('material_original')) and checked['status']=='candidate_only':good.append(c)
                    alias_attempts=[]
                    if not good:
                        aliases=set()
                        for link in row.get('code_links',[]):
                            if str(link.get('pcs') or '')==row['jan'] and link.get('jan'):aliases.add(str(link['jan']))
                            elif str(link.get('jan') or '')==row['jan'] and link.get('pcs'):aliases.add(str(link['pcs']))
                        # Multiple linked codes require source review, not arbitrary retries.
                        if len(aliases)==1:
                            alias=next(iter(aliases));aq=ProductQuery(jan=alias,name_ja=row['name_ja'],spec=row.get('spec') or '')
                            ar=svc.engine.query(aq,allow_online=True,all_sites=True).to_dict() if online else svc.engine.query_snapshots(aq,request.get('snapshots',back/'no-snapshots'),site_ids=['anime_store'],all_sites=True).to_dict()
                            alias_attempts.append(ar)
                            for c in ar['candidates']:
                                checked=assess_page({**row,'jan':alias},c,name_similarity);c['identity_assessment']=checked;c['linked_from']=row['jan'];c['code_link_evidence']=row['code_links']
                                if material_quality(c.get('material_original')) and material_quality(c.get('material_zh') or c.get('material_original')) and checked['status']=='candidate_only':good.append(c)
                    material_values={c.get('material_zh') or c['material_original'] for c in good}
                    candidate={'status':'found' if len(material_values)==1 else 'conflict' if len(material_values)>1 else 'not_found',
                               'value':next(iter(material_values)) if len(material_values)==1 else None,'plugin_result':raw,'alias_attempts':alias_attempts,'matched_candidates':good,'identity_key':binding}
                except Exception as exc:candidate={'status':'error','reason':str(exc),'identity_key':binding}
                candidate['queried_at']=datetime.now().astimezone().isoformat();candidate['query_mode']=query_mode;candidate['evidence_binding']=evidence_binding;dedupe[binding]=candidate
            candidate={**candidate,'binding':row};results[str(n)]=candidate
        if candidate.get('status')=='found':
            if v[17] not in (None,'') and v[17]!=candidate['value']:candidate['status']='existing_R_conflict'
            elif v[17]!=candidate['value']:changes.append({'target':'R'+str(n),'value':candidate['value']})
        save(back/'website-results.json',{'rows':results,'approved':0,'scope':'all_products','source_sha256':sha})
    if digest(file)!=sha:raise Rejected('查询期间工作簿变化，结果已留后台，未写Excel')
    if changes:
        archive=back/'website-inputs';archive.mkdir(exist_ok=True);saved=archive/(sha+'.xlsx')
        if not saved.exists():saved.write_bytes(original)
        file.write_bytes(update_cells(original,config['sheet'],changes))
    # A later timeout/404 must not erase provenance for a successful R decoration
    # already present in the workbook (or make its A03 return fail).
    overlay_rows={**prior_overlay,**{n:r for n,r in results.items() if r.get('status')=='found'}}
    save(back/'website-overlay.json',{'rows':overlay_rows,'file_sha256':digest(file)})
    return {'business_files':[str(file)],'queried_rows':len(rows),'filled_rows':len(changes),'found_rows':sum(r.get('status')=='found' for r in results.values()),'retained_reference_rows':len(overlay_rows),
            'formal_output':False,'message':'已按授权清单查询；可靠网站材质填R，未取得新结果的空白保持不变，已有可靠参考保留。'}

def apply_review_overlay(config,dual):
    """Publish verified full-provider evidence through the existing R overlay."""
    report=load(dual['reference_report']);file=Path(config['prepared_file'])
    from openpyxl import load_workbook
    workbook=load_workbook(file,read_only=True,data_only=True)
    try:current=list(workbook[config['sheet']].values)
    finally:workbook.close()
    back=Path(config['background']);overlay=back/'website-overlay.json'
    prior=load(overlay).get('rows',{}) if overlay.exists() else {};changes=[];rows=dict(prior)
    for n,item in report['rows'].items():
        web=item['website'];b=item['binding'];v=current[int(n)-1]
        if web['status']!='found' or len(web['values'])!=1:continue
        if (str(v[2]),str(v[9] or ''),str(v[6] or ''),str(v[16] or ''))!=(b['jan'],b['name_ja'],b['spec'],b['yd']):continue
        value=web['values'][0]
        if not material_quality(value) or not web.get('evidence') or not all(material_quality(c.get('material_original')) and material_quality(c.get('material_zh')) for c in web['evidence']):continue
        if v[17] not in (None,'',value):continue
        if v[17]==value and n not in prior:continue
        rows[n]={'status':'found','value':value,'binding':b,'evidence':web['evidence'],
                 'reference_report':dual['reference_report'],'automatic_approval':False}
        if v[17]!=value:changes.append({'target':'R'+n,'value':value})
    if changes:file.write_bytes(update_cells(file.read_bytes(),config['sheet'],changes))
    if rows:save(overlay,{'rows':rows,'file_sha256':digest(file)})


def _canonical_website_return(config,file):
    """Remove only system website decoration before unchanged A03 comparison."""
    from openpyxl import load_workbook
    back=Path(config['background']);overlay=back/'website-overlay.json'
    if not overlay.exists():return file
    from . import rt
    engine=rt.updates.Service(config['root']);baseline=engine.basics._state(engine.bid)[1]
    baselinefile=engine.root/'objects'/(baseline['copy_sha256']+'.xlsx')
    before=list(load_workbook(baselinefile,read_only=True).worksheets[0].values)
    after=list(load_workbook(file,read_only=True).worksheets[0].values);changes=[]
    for n,r in load(overlay)['rows'].items():
        n=int(n)
        if after[n-1][17]==r['value']:changes.append({'target':'R'+str(n),'value':before[n-1][17]})
    if not changes:return file
    dest=back/'canonical-returns';dest.mkdir(exist_ok=True);target=dest/(digest(file)+'.xlsx')
    target.write_bytes(update_cells(Path(file).read_bytes(),config['sheet'],changes));return target

def canonical_return(config,file):
    file=_canonical_website_return(config,file)
    from .material_reference import canonical_material_return
    return canonical_material_return(config,file)

def apply_overlay(config,file):
    from openpyxl import load_workbook
    overlay=Path(config['background'])/'website-overlay.json'
    if not overlay.exists():return
    rows=list(load_workbook(file,read_only=True).worksheets[0].values);changes=[]
    for n,r in load(overlay)['rows'].items():
        n=int(n);v=rows[n-1];b=r['binding']
        if not material_quality(r.get('value')):continue
        if (str(v[2]),str(v[6] or ''),str(v[9] or ''),str(v[16] or ''))==(b['jan'],str(b.get('spec') or ''),b['name_ja'],str(b.get('yd') or '')) and not v[17]:changes.append({'target':'R'+str(n),'value':r['value']})
    if changes:Path(file).write_bytes(update_cells(Path(file).read_bytes(),config['sheet'],changes))
