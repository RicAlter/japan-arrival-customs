"""Sparse business-attention fills; all other data cells have no fill."""
from copy import deepcopy
from pathlib import Path
from collections import Counter
import xml.etree.ElementTree as ET
from .photo_layout import parts,pack,sheet_member
from . import load,save,digest
Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def apply_attention(file,config):
 file=Path(file);record=Path(config['background'])/'attention-render.json'
 if record.exists() and load(record).get('sha256')==digest(file):return
 from openpyxl import load_workbook
 w=load_workbook(file,read_only=True,data_only=True)
 actual=list(w[config['sheet']].values);w.close()
 p=parts(file.read_bytes());member=sheet_member(p,config['sheet']);sheet=ET.fromstring(p[member]);styles=ET.fromstring(p['xl/styles.xml']);fills=styles.find(Q+'fills');xfs=styles.find(Q+'cellXfs');original=list(xfs);newstyles={}
 for color in ['FFF2CC','FCE4D6']:
  fill=ET.SubElement(fills,Q+'fill');pattern=ET.SubElement(fill,Q+'patternFill',{'patternType':'solid'});ET.SubElement(pattern,Q+'fgColor',{'rgb':'FF'+color});ET.SubElement(pattern,Q+'bgColor',{'indexed':'64'})
 fills.set('count',str(len(fills)));yellow=len(fills)-2;red=len(fills)-1
 evidence=load(Path(config['background'])/'evidence.json')['rows'];attention={};reasons={};box_formats={}
 for n,row in evidence.items():
  review=row.get('price_review',{})
  if review.get('category') in {'safe_linked_box_order_quote','safe_dg_order_quote'} and review.get('purchase_unit')=='盒' and actual[int(n)-1][7] not in (None,''):
   # H remains an original-unit purchase reference, visibly labelled per box.
   if not isinstance(actual[int(n)-1][7],str):box_formats['H'+n]='0.########"日元/盒"'
 numfmts=styles.find(Q+'numFmts')
 if box_formats and numfmts is None:numfmts=ET.Element(Q+'numFmts');styles.insert(0,numfmts)
 format_ids={}
 if box_formats:
  existing={e.get('formatCode'):int(e.get('numFmtId')) for e in numfmts}
  next_id=max([163]+list(existing.values()))+1
  for fmt in set(box_formats.values()):
   if fmt not in existing:ET.SubElement(numfmts,Q+'numFmt',{'numFmtId':str(next_id),'formatCode':fmt});existing[fmt]=next_id;next_id+=1
   format_ids[fmt]=existing[fmt]
  numfmts.set('count',str(len(numfmts)))
 for n,row in evidence.items():
  v=dict(row.get('values',{}));issues=[]
  displayed=actual[int(n)-1]
  for field,col in [('name',5),('spec',6),('price',7)]:v[field]=displayed[col]
  for col,field in [('F','name'),('G','spec')]:
   if v.get(field) in (None,''):attention[col+n]=yellow;issues.append({'cell':col+n,'kind':'missing','field':field})
  review=row.get('price_review',{});cat=review.get('category')
  if v.get('price') in (None,''):
   # No fabricated zero; missing reference price needs source/unit review.
   attention['H'+n]=red if cat in {'true_price_conflict','substantive_identity_conflict'} else yellow
   issues.append({'cell':'H'+n,'kind':cat or 'source_missing'})
  if row.get('status')=='substantive_identity_conflict' and v.get('spec')==row.get('values',{}).get('spec'):
   attention['G'+n]=red;issues.append({'cell':'G'+n,'kind':'substantive_identity_conflict'})
  if row.get('status')=='special_identity_requires_context':
   attention['C'+n]=yellow;issues.append({'cell':'C'+n,'kind':'special_identity_requires_context'})
  if issues:reasons[n]=issues
 for row in sheet.find(Q+'sheetData'):
  if int(row.get('r','0'))==1:continue
  for c in row:
   addr=c.get('r');old=int(c.get('s','0'));fill=attention.get(addr,0);fmt=format_ids.get(box_formats.get(addr));k=(old,fill,fmt)
   if k not in newstyles:
    xf=deepcopy(original[old]);xf.set('fillId',str(fill));xf.set('applyFill','1')
    if fmt is not None:xf.set('numFmtId',str(fmt));xf.set('applyNumberFormat','1')
    xfs.append(xf);newstyles[k]=len(xfs)-1
   c.set('s',str(newstyles[k]))
 xfs.set('count',str(len(xfs)));p['xl/styles.xml']=ET.tostring(styles,encoding='utf-8',xml_declaration=True);p[member]=ET.tostring(sheet,encoding='utf-8',xml_declaration=True)
 data=pack(file.read_bytes(),p)
 if file.read_bytes()!=data:file.write_bytes(data)
 save(Path(config['background'])/'business-attention.json',{'rows':reasons,'summary':{'records_requiring_human_action':len(reasons),'colored_cells':len(attention),'yellow_cells':sum(x==yellow for x in attention.values()),'red_cells':sum(x==red for x in attention.values()),'optional_material_and_packaging_blanks_not_mandatory':True,'automatic_fill_and_unconfirmed_are_not_color_reasons':True}})

 save(record,{'sha256':digest(file)})
