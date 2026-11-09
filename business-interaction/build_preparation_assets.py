"""Inventory exact reusable inputs and generate a private replay request; never scans a whole library."""
from pathlib import Path
import json,hashlib,sqlite3,zipfile,posixpath,xml.etree.ElementTree as ET
W=Path(__file__).resolve().parents[2];R=W/'reports/first-phase-upgrade-20261106';R.mkdir(parents=True,exist_ok=True)
def load(p):return json.loads(Path(p).read_text('utf8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
registry=load(W/'inputs/asset-registry/KMT20261101_20261105.json');archive=Path(registry['archive_manifest']).parent
raw=next(archive/a['archive_relative_path'] for a in registry['aliases'] if a['archive_relative_path'].startswith('01_'))
old=load(W/'reports/stage1-basic-candidate-20261105/request.json')
origin=load(W/'outputs/KMT20261101_资料库包装闭环候选_20261106_v3/19列受控基础资料/fixed-inputs/snapshot-origin.json');db=origin['source_database']
sources=[{'path':str(W/'reports/unprotected-reference-review-20261106/fixed-inputs/25.6.1-至今报单汇总(1).xlsx'),'sheet':'25.6.1-至今报单汇总','kind':'registry','price_scope':'order_total',
 'columns':{'jan':2,'pcs':9,'name':3,'spec':4,'channel':10,'material':14}}]
for a in registry['aliases']:
 if '采购清单' in a['archive_relative_path']:
  sources.append({'path':str(archive/a['archive_relative_path']),'sheet':'采购清单信息','columns':{'jan':'条形码','sku':'SKU关联编码','name':'商品名称','spec':'单品名称','image':'单品图片','yd':'YD编码','channel':'渠道商名称','currency':'货币类型','price':'单品报价','actual_price':'实际单品报价','purchase_required':'单品需采购总数','purchase_bought':'单品已采购数量','purchase_current':'渠道商本次采购数量'}})
sources.append({'path':str(W/'reports/unprotected-reference-review-20261106/fixed-inputs/采购清单25.4-26.10.9.xlsx'),'sheet':'采购清单信息','priority':0,
 'columns':{'jan':9,'sku':8,'name':4,'yd':5,'spec':6,'image':7,'channel':15,'currency':18,'price':19,'actual_price':20,'purchase_required':11,'purchase_bought':13,'purchase_current':21}})
oldcache=W/'reports/hd-photos-20261106/photo-downloads.json'
# Recover only URL-bound image parts from the previously delivered HD workbook.
# Stale file-cache hashes are not silently trusted or overwritten.
hd=W/'outputs/KMT20261101_高清图片_20261106/业务当前文件/KMT20261101_基础资料.xlsx';hdsha=sha(hd)
photo_refs=load(W/'reports/unprotected-reference-review-20261106/photo-source-index-v3.json')
cache=R/'verified-image-cache.json';imagefolder=R/'verified-image-assets';imagefolder.mkdir(exist_ok=True);verified={}
from PIL import Image
with zipfile.ZipFile(hd) as z:
 drawing=ET.fromstring(z.read('xl/drawings/drawing1.xml'));rels={e.get('Id'):e.get('Target') for e in ET.fromstring(z.read('xl/drawings/_rels/drawing1.xml.rels'))}
 ns='{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'
 for anchor in drawing:
  n=int(anchor.find(ns+'from/'+ns+'row').text)+1;ref=photo_refs.get(str(n),{});url=ref.get('selected_url')
  if not url:continue
  rid=next(e for e in anchor.iter() if e.tag.endswith('}blip')).get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
  target=rels[rid];member=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/drawings/'+target);data=z.read(member)
  file=imagefolder/(hashlib.sha256(data).hexdigest()+Path(member).suffix);file.write_bytes(data)
  with Image.open(file) as im:width,height=im.size
  verified[url]={'url':url,'file':str(file),'status':'downloaded','sha256':sha(file),'width':width,'height':height,'provenance':{'workbook':str(hd),'workbook_sha256':hdsha,'row':n,'media':member,'source_url_evidence':ref}}
cache.write_text(json.dumps(verified,ensure_ascii=False,indent=2),encoding='utf8')
request={'action':'prepare','input_file':str(raw),'batch_id':'SYNTHETIC_KMT20261101_replay','database':db,'sources':sources,'image_caches':[str(cache)],'download_images':False,
 'output':str(W/'outputs/第一阶段升级隔离回放_20261106_v11'),'node':r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe','mode':'synthetic',
 'history_rules':[{'term':t,'material':m,'verified':True,'source':'USER:2026-11-06:已授权历史参考对应；原案例见reports/explicit-material-split-20261106/candidates.json'} for t,m in [('相卡','纸'),('插画卡','纸'),('亚克力卡','亚克力'),('亚克力块','亚克力'),('立板','亚克力')]]}
assets=[]
for p,role,status in [(raw,'日方原始附件','reusable'),(db,'只读资料库；运行时SQLite backup','reusable'),(cache,'高清图片缓存索引','reusable')]+[(s['path'],'业务来源字段映射','reusable') for s in sources]:
 assets.append({'path':str(p),'sha256':sha(p),'role':role,'status':status})
for p,role,status in [(W/'tools/prepare_spec_pack_split.py','本批盒规逗号脚本；新实现须保留每包信息','historical_only'),(W/'tools/patch_website_material_r.py','本批定向R补丁','historical_only'),(W/'github-progress-rc8-20261028/material-query-adapter/adapter.py','已验收只读插件接口；全量查询直接用其engine避免本地命中跳站','reusable'),(W/'github-progress-rc8-20261028/business-interaction/interaction/photo_layout.py','原图片及公式平移适配','reusable')]:
 assets.append({'path':str(p),'sha256':sha(p),'role':role,'status':status})
(R/'assets.json').write_text(json.dumps({'assets':assets,'validation':'source hashes recorded; execution receipt is separate','installed':False},ensure_ascii=False,indent=2),encoding='utf8')
(R/'prepare-request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'assets':len(assets),'source_workbooks':len(sources),'request':str(R/'prepare-request.json')},ensure_ascii=False))
