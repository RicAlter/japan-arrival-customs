"""Insert the requested E photo column, retaining native values/formula caches.

Images are authored by Artifact Tool, then its native drawing/media parts are
grafted into the existing workbook. No importer/calculation engine is replaced.
"""
import io,re,zipfile,xml.etree.ElementTree as ET
from copy import deepcopy
from openpyxl.utils.cell import column_index_from_string,get_column_letter
from openpyxl.formula.tokenizer import Tokenizer
from native_copy.ooxml import parts,sheet_member,Styles,Q,NS,patch_cell,set_attr
from . import Rejected
SHEET='invoice (計算)'
XDR='{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'
REL='{http://schemas.openxmlformats.org/package/2006/relationships}'
RID='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

def package_xml(root,namespace):
    """Use conventional default OPC namespaces for Excel/.NET compatibility."""
    raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    match=re.search(rb'<([A-Za-z_][\w.-]*):'+root.tag.rsplit('}',1)[-1].encode()+rb'\b',raw)
    if match:
        prefix=match[1];raw=raw.replace(b'xmlns:'+prefix+b'="'+namespace.encode()+b'"',b'xmlns="'+namespace.encode()+b'"')
        raw=raw.replace(b'<'+prefix+b':',b'<').replace(b'</'+prefix+b':',b'</')
    return raw

def address(text):
    def shift(m):
        col=column_index_from_string(m[2]);return m[1]+get_column_letter(col+1 if col>=5 else col)+m[3]+m[4]
    return re.sub(r'(?<![A-Za-z0-9_])([$]?)([A-Z]{1,3})([$]?)(\d+)(?![A-Za-z0-9_])',shift,text)

def reference(text,local=True):
    if '!' in text:
        prefix,tail=text.rsplit('!',1)
        if prefix.strip("'").replace("''", "'")!=SHEET:return text
        return prefix+'!'+address(tail)
    return address(text) if local else text

def formula(text,local=True):
    if not text:return text
    prefix='' if text.startswith('=') else '='
    tokens=Tokenizer(prefix+text).items
    return ('' if prefix else '=')+''.join(reference(t.value,local) if t.type=='OPERAND' and t.subtype=='RANGE' else t.value for t in tokens)

def unprotect(p):
    prefix=rb'(?:[A-Za-z_][\w.-]*:)?'
    for name in list(p):
        if name=='xl/workbook.xml' or name.startswith('xl/worksheets/') and name.endswith('.xml'):
            for tag in [b'sheetProtection',b'workbookProtection',b'protectedRanges']:
                p[name]=re.sub(rb'<'+prefix+tag+rb'\b[^>]*?(?:/>|>.*?</'+prefix+tag+rb'>)',b'',p[name],flags=re.S)

def pack(original,p):
    out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as dest:
        old=set(src.namelist())
        for info in src.infolist():dest.writestr(info,p[info.filename])
        for name,value in p.items():
            if name not in old:dest.writestr(name,value)
    return out.getvalue()

def transform(original,image_canvas,decisions,photo_rows,business_rows):
    p=parts(original);member=sheet_member(p,SHEET);root=ET.fromstring(p[member]);styles=Styles(p['xl/styles.xml']);style_cache={}
    fills={}
    for pending in [True,False]:
        rgb='FFF4CCCC' if pending else 'FFFFF2CC'
        fills[pending]=len(styles.fills)+len(styles.extra_fills)
        styles.extra_fills.append(b'<'+styles.p+b'fill><'+styles.p+b'patternFill patternType="solid"><'+styles.p+b'fgColor rgb="'+rgb.encode()+b'"/></'+styles.p+b'patternFill></'+styles.p+b'fill>')
    def qstyle(base,pending):
        key=(base,pending)
        if key not in style_cache:
            style_cache[key]=len(styles.xfs)+len(styles.extra_xfs)
            styles.extra_xfs.append(set_attr(set_attr(styles.fragments[base],'fillId',fills[pending]),'applyFill','1'))
        return style_cache[key]
    photo_styles={}
    def photo_style(base):
        if base not in photo_styles:
            fragment=styles.fragments[base]
            match=re.search(rb'<(?:[A-Za-z_][\w.-]*:)?alignment\b[^>]*?/>',fragment)
            if match:fragment=fragment[:match.start()]+set_attr(set_attr(match[0],'vertical','bottom'),'horizontal','center')+fragment[match.end():]
            else:
                tag=b'<'+styles.p+b'alignment vertical="bottom" horizontal="center"/>'
                if fragment.endswith(b'/>'):fragment=fragment[:-2]+b'>'+tag+b'</'+styles.p+b'xf>'
                else:at=fragment.rfind(b'</');fragment=fragment[:at]+tag+fragment[at:]
            photo_styles[base]=len(styles.xfs)+len(styles.extra_xfs);styles.extra_xfs.append(fragment)
        return photo_styles[base]
    sd=root.find(Q+'sheetData')
    for row in sd:
        n=int(row.get('r'));oldcells={c.get('r'):c for c in row}
        if str(n) in decisions:
            old=oldcells.get('Q'+str(n));d=decisions[str(n)]
            if old is None:old=ET.SubElement(row,Q+'c',{'r':'Q'+str(n)})
            base=int(old.get('s','0'));style=qstyle(base,d['pending'])
            if d['value'] is None:
                old.attrib.pop('t',None);old[:]=[];old.set('s',str(style))
            else:
                serialized=ET.tostring(old);prefix=re.search(rb'<([A-Za-z_][\w.-]*:)?c\b',serialized)[1] or b''
                data=patch_cell(serialized,{'cell':'Q'+str(n),'style_id':style,'write_value':d['value'],'value_type':'text'},prefix)
                # The serialized prefix has a namespace declaration on the c node.
                replacement=ET.fromstring(data);row[list(row).index(old)]=replacement
        for cell in row:
            cell.set('r',address(cell.get('r')))
            f=cell.find(Q+'f')
            if f is not None:
                f.text=formula(f.text)
                if f.get('ref'):f.set('ref',address(f.get('ref')))
        if n==1 or n in business_rows:
            c=ET.Element(Q+'c',{'r':'E'+str(n),'s':oldcells.get('D'+str(n),oldcells.get('D1',next(iter(oldcells.values())))).get('s','0')})
            if n==1 or n not in photo_rows:
                c.set('t','inlineStr');ET.SubElement(ET.SubElement(c,Q+'is'),Q+'t').text='商品图片' if n==1 else '暂无匹配图片'
            elif isinstance(photo_rows,dict) and photo_rows[n]=='box_reference':
                c.set('s',str(photo_style(int(c.get('s','0')))));c.set('t','inlineStr');ET.SubElement(ET.SubElement(c,Q+'is'),Q+'t').text='整盒参考图'
            row.append(c)
            if n in business_rows:row.set('ht','72');row.set('customHeight','1')
        row[:]=sorted(row,key=lambda c:column_index_from_string(re.match(r'[A-Z]+',c.get('r'))[0]))
        if row.get('spans'):
            a,b=map(int,row.get('spans').split(':'));row.set('spans',str(a)+':'+str(b+1 if b>=5 else b))
    cols=root.find(Q+'cols');newcols=[]
    for c in cols:
        lo,hi=int(c.get('min')),int(c.get('max'))
        if hi<5:newcols.append(c)
        elif lo>=5:c.set('min',str(lo+1));c.set('max',str(hi+1));newcols.append(c)
        else:
            left=deepcopy(c);left.set('max','4');newcols.append(left);c.set('min','6');c.set('max',str(hi+1));newcols.append(c)
    newcols.append(ET.Element(Q+'col',{'min':'5','max':'5','width':'19','customWidth':'1'}));cols[:]=sorted(newcols,key=lambda c:int(c.get('min')))
    for element in root.iter():
        if element.tag in {Q+'c',Q+'f'}:continue
        for attr in ['ref','sqref','activeCell','topLeftCell']:
            if element.get(attr):element.set(attr,address(element.get(attr)))
        if element.tag==Q+'filterColumn' and int(element.get('colId'))>=3:element.set('colId',str(int(element.get('colId'))+1))
    p[member]=ET.tostring(root,encoding='utf-8',xml_declaration=True);p['xl/styles.xml']=styles.export()
    for name in list(p):
        if name.startswith('xl/worksheets/') and name.endswith('.xml') and name!=member:
            other=ET.fromstring(p[name]);changed=False
            for f in other.iter(Q+'f'):
                new=formula(f.text,False)
                if new!=f.text:f.text=new;changed=True
            if changed:p[name]=ET.tostring(other,encoding='utf-8',xml_declaration=True)
    wb=ET.fromstring(p['xl/workbook.xml'])
    for node in wb.findall('s:definedNames/s:definedName',NS):node.text=reference(node.text or '',False)
    p['xl/workbook.xml']=ET.tostring(wb,encoding='utf-8',xml_declaration=True)
    images=parts(image_canvas)
    if any(name.startswith('xl/drawings/') for name in p):raise Rejected('原副本已有绘图，须显式保留合并，不能覆盖')
    for name,value in images.items():
        if name.startswith(('xl/drawings/','xl/media/')):p[name]=value
    # Native move-and-size-with-cells anchors support the existing row filter.
    drawing=ET.fromstring(p['xl/drawings/drawing1.xml'])
    for anchor in list(drawing):
        if anchor.tag!=XDR+'oneCellAnchor':raise Rejected('图片锚点类型改变')
        ext=anchor.find(XDR+'ext');start=anchor.find(XDR+'from');end=deepcopy(start);end.tag=XDR+'to'
        end.find(XDR+'colOff').text=str(int(start.find(XDR+'colOff').text)+int(ext.get('cx')))
        end.find(XDR+'rowOff').text=str(int(start.find(XDR+'rowOff').text)+int(ext.get('cy')))
        anchor.tag=XDR+'twoCellAnchor';anchor.set('editAs','twoCell');anchor.remove(ext);anchor.insert(1,end)
    p['xl/drawings/drawing1.xml']=ET.tostring(drawing,encoding='utf-8',xml_declaration=True)
    main=ET.fromstring(p[member]);ET.SubElement(main,Q+'drawing',{RID+'id':'rIdProductPhotos'});p[member]=ET.tostring(main,encoding='utf-8',xml_declaration=True)
    relname=member.rsplit('/',1)[0]+'/_rels/'+member.rsplit('/',1)[1]+'.rels'
    rels=ET.fromstring(p[relname]) if relname in p else ET.Element(REL+'Relationships')
    ET.SubElement(rels,REL+'Relationship',{'Id':'rIdProductPhotos','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing','Target':'../drawings/drawing1.xml'})
    p[relname]=package_xml(rels,REL[1:-1])
    content=ET.fromstring(p['[Content_Types].xml']);known={(e.tag,e.get('Extension') or e.get('PartName')) for e in content}
    for e in ET.fromstring(images['[Content_Types].xml']):
        name=e.get('PartName','');ext=e.get('Extension','')
        if name.startswith('/xl/drawings/') or ext.lower() in {'jpg','jpeg','png'}:
            if (e.tag,ext or name) not in known:content.append(e)
    p['[Content_Types].xml']=package_xml(content,'http://schemas.openxmlformats.org/package/2006/content-types')
    unprotect(p)
    return pack(original,p)
