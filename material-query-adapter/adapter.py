"""Independent, read-only candidate adapter for jp_material_query 0.2.0.
No imports from business engines and no workbook/state/library writes.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,re,sqlite3,sys,unicodedata

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def key(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def identity(q):
 return {k:str(q.get(k) or '') for k in ['jan','name_ja','name_zh','spec','yd','brand','source_sha256','source_sheet','source_row']}
def norm(t):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(t or '')).lower())
def version(t):
 return set(re.findall(r'vol\.?\s*\d+|第\s*\d+\s*[弾期部章]|(?:通常|限定|初回|再販|再生産|復刻)版?|ver\.?\s*[a-z0-9]+',unicodedata.normalize('NFKC',str(t or '')).lower()))
def assess(q,c,similarity):
 reasons=[];conflict=False
 if c.get('jan_on_page') and str(c['jan_on_page'])!=str(q['jan']):reasons.append('jan_mismatch');conflict=True
 if c.get('match_status') in ['jan_mismatch','name_mismatch','version_mismatch','multiple_candidates']:reasons.append(c['match_status']);conflict=True
 score=similarity(q.get('name_ja',''),c.get('name_ja',''))
 if score is not None and score<.42:reasons.append('name_mismatch');conflict=True
 qv=version(q.get('name_ja',''));cv=version(c.get('name_ja','')+' '+c.get('spec_text',''))
 # Different explicit numbered versions/editions are conflicts; absent version evidence stays unresolved.
 for pattern in [r'vol\.?\s*\d+',r'第\s*\d+\s*[弾期部章]']:
  x={norm(v) for v in qv if re.fullmatch(pattern,v)};y={norm(v) for v in cv if re.fullmatch(pattern,v)}
  if x and y and x!=y:reasons.append('version_mismatch');conflict=True
 if any('限定' in v for v in qv) and any('通常' in v for v in cv) or any('通常' in v for v in qv) and any('限定' in v for v in cv):reasons.append('version_mismatch');conflict=True
 if conflict:status='identity_conflict'
 elif c.get('match_status')!='exact' or not c.get('jan_on_page') or score is None or score<.62 or qv!=cv:status='identity_unresolved'
 else:status='candidate_only'
 return {'status':status,'reasons':sorted(set(reasons)),'name_score':score,'query_versions':sorted(qv),'page_versions':sorted(cv),'adopted':False}

class Catalogue:
 def __init__(self,path,queries):
  self.path=Path(path).resolve();self.sha=digest(path);self.materials={};self.exact={}
  db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
  yds={q.get('yd') for q in queries};codes={str(q['jan']) for q in queries}
  for r in db.execute('select * from yd_material_lookup'):
   if r['yd_key'] in yds and r['material_original']:self.materials.setdefault(r['yd_key'],[]).append(dict(r))
  selected={}
  for r in db.execute('select entry_id,descriptor_json from catalogue_entries'):
   d=json.loads(r['descriptor_json'])
   if str(d.get('code_raw')) in codes and d.get('yd') in yds:selected[r['entry_id']]={'descriptor':d,'materials':[],'sources':[]}
  for r in db.execute("select * from field_variants where field_name in ('material','material_original','material_zh')"):
   if r['entry_id'] in selected and json.loads(r['value_json']):selected[r['entry_id']]['materials'].append(dict(r))
  for r in db.execute('select * from record_links'):
   if r['entry_id'] in selected:selected[r['entry_id']]['sources'].append(dict(r))
  for v in selected.values():self.exact.setdefault((str(v['descriptor'].get('code_raw')),v['descriptor'].get('yd')),[]).append(v)
  db.close();assert digest(path)==self.sha
 def lookup(self,q):
  cards=self.materials.get(q.get('yd'),[]);records=self.exact.get((str(q['jan']),q.get('yd')),[])
  qualified=[r for r in records if norm(r['descriptor'].get('japanese_name'))==norm(q.get('name_ja')) and norm(q.get('name_ja')) and norm(r['descriptor'].get('specification'))==norm(q.get('spec')) and r['materials'] and r['sources']]
  values={json.loads(m['value_json']) for r in qualified for m in r['materials']}
  return {'status':'sku_material_candidate' if len(values)==1 else 'conflict' if len(values)>1 else 'sku_unclear' if cards else 'missing','cards':cards,'exact_records':records,'qualified':qualified,'snapshot_sha256':self.sha,'adopted':False}

class BoundCache:
 def __init__(self,cache):self.cache=cache;self.binding=''
 def get(self,site,jan):return self.cache.get(site,self.binding+':'+jan)
 def put(self,site,jan,url,data,ttl):return self.cache.put(site,self.binding+':'+jan,url,data,ttl)

class Service:
 def __init__(self,plugin,db,queries,state,config=None,transport=None,access_review=None):
  self.plugin=Path(plugin).resolve();sys.path.insert(0,str(self.plugin))
  from jpmaterial.cli import ADAPTERS
  from jpmaterial.config import load_sites,load_glossary
  from jpmaterial.engine import QueryEngine
  from jpmaterial.cache import CacheStore
  from jpmaterial.access import AccessRegistry
  from jpmaterial.transport import UrllibTransport
  self.state=Path(state);self.catalogue=Catalogue(db,queries);policies=load_sites(Path(config or self.plugin/'config')/'sites.json');glossary=load_glossary(Path(config or self.plugin/'config'))
  from reviewed_transport import ReviewedTransport
  transport=transport or ReviewedTransport(UrllibTransport(timeout=12),access_review,self.state)
  self.cache=BoundCache(CacheStore(self.state/'cache.json'));self.engine=QueryEngine(policies,{p.site_id:ADAPTERS[p.site_id](p,glossary) for p in policies if p.site_id in ADAPTERS},transport or UrllibTransport(timeout=12),self.cache,AccessRegistry(self.state/'access.json'))
 def query(self,q,online=False,snapshots=None):
  from jpmaterial.models import ProductQuery
  from jpmaterial.identity import name_similarity
  bound=identity(q);local=self.catalogue.lookup(q);output={'binding':bound,'identity_key':key(bound),'library':local,'candidates':[],'attempts':[],'adopted':False,'non_blocking':True}
  if q.get('manual_material'):
   output.update(status='keep_manual',manual_material=q['manual_material']);return output
  if local['status']=='sku_material_candidate':output.update(status='library_candidate',plugin_called=False);return output
  self.cache.binding=key({'identity':bound,'library':self.catalogue.sha,'plugin_version':'0.2.0'})
  query=ProductQuery(jan=str(q['jan']),name_ja=str(q.get('name_ja') or ''),name_zh=str(q.get('name_zh') or ''),spec=str(q.get('spec') or ''),brand=str(q.get('brand') or ''),source_row=q.get('source_row'),raw={'binding':bound})
  try:
   result=self.engine.query_snapshots(query,snapshots,all_sites=True) if snapshots else self.engine.query(query,allow_online=online,all_sites=True)
   raw=result.to_dict();output['plugin_raw']=raw;output['plugin_called']=True;output['attempts']=raw['attempts']
   for c in raw['candidates']:
    c['identity_assessment']=assess(q,c,name_similarity);c['binding']=bound;c['library_snapshot_sha256']=self.catalogue.sha
    output['candidates'].append(c)
   conflicts=[c for c in output['candidates'] if c['identity_assessment']['status']=='identity_conflict']
   found=[c for c in output['candidates'] if c.get('material_original') and c.get('material_status')=='found' and c['identity_assessment']['status']!='identity_conflict']
   vals={norm(c.get('material_zh') or c['material_original']) for c in found}
   output.update(status='identity_conflict' if conflicts and not found else 'material_conflict' if len(vals)>1 or raw['status']=='conflict' else 'network_candidate' if found else raw['status'],identity_conflict=bool(conflicts),has_material_candidate=bool(found),needs_review=True)
   # Local card collections remain in evidence; do not replace working material or select one constituent.
   if found and local['cards']:output['comparison_required_with_library']=True
  except Exception as exc:output.update(status='error',error=str(exc),has_material_candidate=False,needs_review=True)
  return output

def main():
 p=argparse.ArgumentParser(description='只读材质候选查询；默认不联网，不写业务表/资料库/A03')
 for name in ['plugin','database','input','state','output']:p.add_argument('--'+name,required=True)
 p.add_argument('--access-review');p.add_argument('--config');p.add_argument('--snapshots');p.add_argument('--allow-online',action='store_true');args=p.parse_args()
 qs=json.loads(Path(args.input).read_text('utf-8'));protected=[Path(args.input).resolve(),Path(args.database).resolve()]
 if Path(args.output).resolve() in protected:raise ValueError('输出不得覆盖输入/资料库')
 before={str(x):digest(x) for x in protected};service=Service(args.plugin,args.database,qs,args.state,args.config,access_review=args.access_review)
 results=[]
 for q in qs:
  result=service.query(q,args.allow_online,args.snapshots);results.append(result);save(args.output,{'schema':'read-only-material-candidates/1','generated_at':datetime.now(timezone.utc).isoformat(),'results':results,'approved':0})
 assert all(digest(k)==v for k,v in before.items());print(json.dumps({'rows':len(results),'status':dict(__import__('collections').Counter(r['status'] for r in results))}))
if __name__=='__main__':main()
