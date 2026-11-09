from pathlib import Path
from copy import deepcopy
import json,hashlib,re,zipfile,io,xml.etree.ElementTree as ET
from openpyxl.formula.translate import Translator
Q="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HEADERS=['CartonNo.','Origin','ProductCode(JANCode)','JC','商品名称','规格','采购单价','盒规','DescriptionofGoods','Qty','UnitPrice(日本JPY)','Subtotal','品类','材质','渠道','YD']
def adapt(request):
 from openpyxl import load_workbook
 p=Path(request['input_file']);w=load_workbook(p,read_only=True,data_only=False);s=w.worksheets[0];header=list(next(s.values));w.close()
 if header!=['CartonNo.','Origin','ProductCode(JANCode)','DescriptionofGoods','Qty','UnitPrice(日本JPY)','Subtotal']:return request
 folder=Path(request['output']).with_name(Path(request['output']).name+'_原件及映射');folder.mkdir(exist_ok=True)
 raw=p.read_bytes();sha=hashlib.sha256(raw).hexdigest();archive=folder/'original7.xlsx'
 if archive.exists() and archive.read_bytes()!=raw:raise ValueError('原件版本变化')
 existing=folder/'mapped16.xlsx';metadata=folder/'mapping.json'
 if existing.exists() and metadata.exists():
  prior=json.loads(metadata.read_text(encoding='utf-8'))
  if prior.get('sha256')!=sha or not prior.get('normalized_sha256') or hashlib.sha256(existing.read_bytes()).hexdigest()!=prior['normalized_sha256']:raise ValueError('已登记映射快照变化')
  return {**request,'input_file':str(existing)}
 archive.write_bytes(raw)
 with zipfile.ZipFile(io.BytesIO(raw)) as z:parts={n:z.read(n) for n in z.namelist()}
 tree=ET.fromstring(parts['xl/worksheets/sheet1.xml']);mapping={'A':'A','B':'B','C':'C','D':'I','E':'J','F':'K','G':'L'}
 shared={f.get('si'):(c.get('r'),f.text) for c in tree.iter(Q+'c') if (f:=c.find(Q+'f')) is not None and f.get('t')=='shared' and f.text}
 for row in tree.findall(Q+'sheetData/'+Q+'row'):
  for cell in list(row):
   address=cell.get('r');m=re.fullmatch(r'([A-Z]+)([0-9]+)',address)
   if not m or m[1] not in mapping:raise ValueError('未知列')
   new=mapping[m[1]]+m[2];cell.set('r',new)
   f=cell.find(Q+'f')
   if f is not None:
    if f.get('t')=='array':raise ValueError('数组公式须另行核验')
    if f.get('t')=='shared':
     origin,expression=shared[f.get('si')];f.text=Translator('='+expression,origin=origin).translate_formula(address)[1:];f.attrib.clear()
    f.text=re.sub(r'(?<![A-Za-z0-9_])([$]?)([A-G])([$]?)([0-9]+)',lambda a:a[1]+mapping[a[2]]+a[3]+a[4],f.text or '')
  if row.get('r')=='1':
   row.clear();row.set('r','1')
   for n,label in enumerate(HEADERS):
    c=ET.SubElement(row,Q+'c',{'r':chr(65+n)+'1','t':'inlineStr'});ET.SubElement(ET.SubElement(c,Q+'is'),Q+'t').text=label
 for tag in ['cols','autoFilter','mergeCells']:
  for node in tree.findall(Q+tag):tree.remove(node)
 dim=tree.find(Q+'dimension')
 if dim is not None:dim.set('ref','A1:P'+str(max(int(x.get('r')) for x in tree.findall(Q+'sheetData/'+Q+'row'))))
 parts['xl/worksheets/sheet1.xml']=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
 book=ET.fromstring(parts['xl/workbook.xml']);book.find(Q+'sheets/'+Q+'sheet').set('name','invoice (計算)');parts['xl/workbook.xml']=ET.tostring(book,encoding='utf-8',xml_declaration=True)
 normalized=folder/'mapped16.xlsx'
 with zipfile.ZipFile(normalized,'w',zipfile.ZIP_DEFLATED) as z:
  for n,data in parts.items():z.writestr(n,data)
 (folder/'mapping.json').write_text(json.dumps({'original':str(p),'sha256':sha,'normalized':str(normalized),'normalized_sha256':hashlib.sha256(normalized.read_bytes()).hexdigest(),'columns':mapping,'original_unchanged':p.read_bytes()==raw,'note':'Explicit seven-column input adapter; mapped16 is an intermediate, not the original or an approval.'},ensure_ascii=False,indent=2),encoding='utf-8')
 return {**request,'input_file':str(normalized)}

def install():
 import native_copy.profiles as profiles
 from interaction import key
 original=profiles.inspect_source
 def inspect(path):
  result=original(path)
  if result['profile_id']=='kmt-native-16-v1':
   for row in result['batch']['rows']:
    for cell in row['source']['cells'].values():cell.setdefault('column',re.sub(r'[0-9]+$','',cell['cell']))
   result['row_map_hash']=key([{'id':row['id'],'source':row['source']} for row in result['batch']['rows']])
  return result
 profiles.inspect_source=inspect
