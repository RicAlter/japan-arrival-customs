"""Clean historical presentation copies; never changes business approval state."""
from pathlib import Path
from copy import deepcopy
from fractions import Fraction
import hashlib,json,re,zipfile,xml.etree.ElementTree as ET
from openpyxl import load_workbook
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def shift(value):return re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)',lambda m:m[1]+str(int(m[2])-2),value)
def same(a,b):
 if a in(None,'')or b in(None,''):return a in(None,'')and b in(None,'')
 if isinstance(a,(int,float))and isinstance(b,(int,float)):return abs(Fraction(str(a))-Fraction(str(b)))<Fraction(1,10**7)
 return a==b
headers={
 'internal':['箱号','产地','商品编码','JC','商品','规格','日文品名','盒数','数量','日方单价（JPY）','金额（JPY）','品类','材质','计价单位/盒','关税率','单位增值税（JPY）','单位关税（JPY）','每盒税金（JPY）','YD编码','备注','本行税金（JPY）'],
 'customs':['箱号','品番','Items & Descriptions','原产地','盒数','数量（单个）','单价（JPY）','品牌','品名','品类','是否盲盒','标签','材质','尺寸','规格','金额（JPY）','箱数CTNs','G/W (KG)','Total G/W (kgs)']}

def prepare(r,output,batch,node_modules):
 if r.get('stage')!='test-final'or r.get('test_only')is not True or r.get('formal_output')is not False:raise ValueError('Only a verified local historical test pair can be styled')
 if len(r['business_files'])!=2:raise ValueError('Both verified final workbooks are required')
 O=Path(output);O.mkdir(parents=True,exist_ok=False)
 books=[]
 for kind,file in zip(['internal','customs'],r['business_files']):
  assert sha(file)==r['output_sha256'][file]
  w=load_workbook(file,read_only=False,data_only=True);wf=load_workbook(file,read_only=False,data_only=False)
  s=w.worksheets[0];sf=wf.worksheets[0];values=list(s.values)[2:]
  assert len(values)==r['rows']+2 and len(values[0])==len(headers[kind])
  formulas=[dict(cell=re.sub(r'\d+',lambda m:str(int(m[0])-2),c.coordinate),formula=shift(c.value),source_cell=c.coordinate)for row in sf.iter_rows(min_row=4)for c in row if c.data_type=='f']
  books.append(dict(kind=kind,source=file,source_sha256=sha(file),sheet=s.title,source_rows=s.max_row,columns=s.max_column,headers=headers[kind],values=values,formulas=formulas,formats=[[sf.cell(n,c).number_format for c in range(1,s.max_column+1)]for n in range(3,s.max_row+1)],heights=[sf.row_dimensions[n].height or 42 for n in range(3,s.max_row+1)],output=str(O/(batch+'_'+('内部到货表'if kind=='internal'else'海关报关单')+'.xlsx'))))
  w.close();wf.close()
 plan=dict(books=books,rows=r['rows'],physical_cartons=r['logistics']['physical_cartons'],artifact_node_modules=node_modules,totals=r['totals'],rounding_difference_jpy=r['rounding_difference_jpy'],presentation_only=True,business_approval_changed=False,output_dir=str(O))
 (O/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n','utf8')
 return plan

def verify(output):
 O=Path(output);plan=json.loads((O/'plan.json').read_text('utf8'))
 files=[]
 for b in plan['books']:
  assert sha(b['source'])==b['source_sha256']
  source=load_workbook(b['source'],data_only=False);out=load_workbook(b['output'],data_only=False)
  # Independently verify row-adjusted formulas before retaining original caches.
  for f in b['formulas']:assert out.worksheets[0][f['cell']].value==f['formula'],f['cell']
  if b['kind']=='internal':
   for row in source.worksheets[1]:
    for c in row:
     if c.data_type=='f':assert out.worksheets[1][c.coordinate].value==c.value,c.coordinate
  source.close();out.close()
  with zipfile.ZipFile(b['source'])as z:old={n:z.read(n)for n in ['xl/worksheets/sheet1.xml']+(['xl/worksheets/sheet2.xml']if b['kind']=='internal'else[])}
  with zipfile.ZipFile(b['output'])as z:infos=z.infolist();parts={i.filename:z.read(i.filename)for i in infos}
  for member,raw in old.items():
   root=ET.fromstring(parts[member]);cells={c.get('r'):c for c in root.iter(NS+'c')}
   for c in ET.fromstring(raw).iter(NS+'c'):
    f=c.find(NS+'f')
    if f is None:continue
    addr=shift(c.get('r'))if member.endswith('sheet1.xml')else c.get('r');target=cells[addr]
    for tag in ['f','v']:
     existing=target.find(NS+tag)
     if existing is not None:target.remove(existing)
     original=c.find(NS+tag)
     if original is not None:
      replacement=deepcopy(original)
      if tag=='f'and member.endswith('sheet1.xml'):
       if replacement.text:replacement.text=shift(replacement.text)
       if replacement.get('ref'):replacement.set('ref',shift(replacement.get('ref')))
      target.append(replacement)
    target.attrib.pop('t',None)
    if c.get('t'):target.set('t',c.get('t'))
   if member.endswith('sheet1.xml'):
    last=len(b['values']);sd=root.find(NS+'sheetData')
    for row in list(sd):
     if int(row.get('r'))>last:
      assert all(c.find(NS+'f')is None and not ''.join(c.itertext()).strip()for c in row),'Unexpected trailing content'
      sd.remove(row)
    dim=root.find(NS+'dimension')
    if dim is None:
     dim=ET.Element(NS+'dimension');root.insert(1 if len(root)and root[0].tag==NS+'sheetPr'else 0,dim)
    dim.set('ref','A1:'+('U'if b['kind']=='internal'else'S')+str(last))
   parts[member]=ET.tostring(root,encoding='utf-8',xml_declaration=True)
  with zipfile.ZipFile(b['output'],'w',compression=zipfile.ZIP_DEFLATED)as z:
   for i in infos:z.writestr(i,parts[i.filename])
  w=load_workbook(b['output'],data_only=True);wf=load_workbook(b['output'],data_only=False);s=w.worksheets[0];sf=wf.worksheets[0]
  assert s.max_row==plan['rows']+2 and s.max_column==b['columns']
  assert [c.value for c in s[1]]==b['headers']
  expected=[b['headers'],*b['values'][1:]]
  assert all(same(c.value,value)for row,values in zip(s,expected)for c,value in zip(row,values))
  assert all(c.data_type!='e'for sheet in w for row in sheet for c in row)
  assert all(not any(t in str(c.value)for t in ['流程测试','受控草稿','正式外发关闭'])for sheet in w for row in sheet for c in row)
  assert all(sf.cell(n,c).fill.fgColor.rgb not in ['FFFFF2CC','FFFFC7CE','FFFCE4D6']for n in range(2,plan['rows']+2)for c in range(1,b['columns']+1))
  assert sf.freeze_panes=='D2'
  codecol=3 if b['kind']=='internal'else 2
  assert all(isinstance(s.cell(n,codecol).value,str)for n in range(2,plan['rows']+2))
  for f in b['formulas']:assert sf[f['cell']].value==f['formula']
  if b['kind']=='internal':
   original=load_workbook(b['source'],data_only=True);originalf=load_workbook(b['source'],data_only=False)
   assert w.sheetnames==original.sheetnames
   assert list(w.worksheets[1].values)==list(original.worksheets[1].values)
   assert list(wf.worksheets[1].values)==list(originalf.worksheets[1].values)
   original.close();originalf.close()
   assert s.cell(plan['rows']+2,11).value==plan['totals']['original_amount']
  else:assert s.cell(plan['rows']+2,16).value==plan['totals']['rounded_amount'] and s.cell(plan['rows']+2,17).value==plan['physical_cartons']
  files.append(dict(kind=b['kind'],file=b['output'],sha256=sha(b['output']),rows=plan['rows'],source=b['source'],source_sha256=b['source_sha256'],formulas_preserved_and_shifted=len(b['formulas'])))
  w.close();wf.close();assert sha(b['source'])==b['source_sha256']
 report=dict(passed=True,files=files,source_data_unchanged=True,all_rows_preserved=True,weight_formulas_and_caches_preserved=True,rounding_difference_jpy=plan['rounding_difference_jpy'],presentation_only=True,business_approval_changed=False,formal_release_created=False)
 (O/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf8')
 return report
