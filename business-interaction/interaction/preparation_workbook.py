"""Native XML projection: preserve cached source facts and untouched weight parts."""
from copy import deepcopy
from decimal import Decimal
import re,xml.etree.ElementTree as ET
from . import Rejected
from .photo_layout import parts,pack,package_xml,REL,RID,XDR
Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
HEADERS=['CartonNo.','Origin','ProductCode(JANCode)','JC','商品图片','商品名称','规格','采购单价（原计价单位）','后续算价（预留）','DescriptionofGoods','Qty','UnitPrice(日本JPY)','Subtotal','品类','材质','渠道','YD','网站查找材质','材质参考','盒规原文参考（人工判断）']
H16=['CartonNo.','Origin','ProductCode(JANCode)','JC','商品名称','规格','采购单价','盒规','DescriptionofGoods','Qty','UnitPrice(日本JPY)','Subtotal','品类','材质','渠道','YD']


def reviewed_copy(source, filename, expected_sha256):
    """Retain an explicitly bound reviewed copy only after checking every raw fact.

    This is a display baseline, never an A03 confirmation or adoption receipt.
    The raw attachment remains independently archived by prepare.
    """
    from io import BytesIO
    from pathlib import Path
    from hashlib import sha256
    from openpyxl import load_workbook
    from openpyxl.utils.cell import column_index_from_string
    data=Path(filename).read_bytes()
    if not expected_sha256 or sha256(data).hexdigest()!=expected_sha256:
        raise Rejected('核对表摘要变化，须明确绑定实际版本')
    view=load_workbook(BytesIO(data),read_only=True,data_only=True)
    raw=load_workbook(BytesIO(source['bytes']),read_only=True,data_only=True)
    try:
        ws=view[source['sheet'].name];observed=list(ws.values)
        if list(observed[0])!=HEADERS:
            raise Rejected('核对表必须是已验证的20列布局')
        product_rows=[n for n,v in enumerate(observed,1) if len(v)>2 and re.fullmatch(r'\d{8,14}',str(v[2] or ''))]
        if product_rows!=list(range(2,len(source['rows'])+2)):
            raise Rejected('核对表商品行与原件不一致，不能猜配或覆盖')
        original=list(raw[source['sheet'].name].values)
        columns={'carton':0,'origin':1,'code':2,'ja':9,'qty':10,'price':11,'amount':12}
        carton=None
        for n,record in enumerate(source['rows'],2):
            for role,index in columns.items():
                meta=record['source']['cells'][role]
                value=original[record['source_row']-1][column_index_from_string(meta['column'])-1]
                if role=='carton':
                    if value not in (None,''):carton=value
                    if value in (None,'') and observed[n-1][index]==carton:continue
                actual=observed[n-1][index]
                if str('' if value is None else value)!=str('' if actual is None else actual):
                    raise Rejected(f'核对表与原件业务事实不一致：{role}，行{n}')
        if view.sheetnames!=raw.sheetnames:
            raise Rejected('核对表页签与原件不一致')
        for name in raw.sheetnames:
            if name==source['sheet'].name:continue
            def facts(sheet):
                return {(c.row,c.column):c.value for row in sheet for c in row if c.value is not None}
            if facts(view[name])!=facts(raw[name]):
                raise Rejected('核对表箱重等附页与原件不一致：'+name)
    finally:
        view.close();raw.close()
    # Check formula text independently of its preserved cached value.
    projected=load_workbook(BytesIO(native_project(source,20)),read_only=True,data_only=False)
    formulas=load_workbook(BytesIO(data),read_only=True,data_only=False)
    try:
        expected=list(projected[source['sheet'].name].values)
        current=list(formulas[source['sheet'].name].values)
        for n in range(2,len(source['rows'])+2):
            for col in (10,11,12):
                value=expected[n-1][col]
                actual=current[n-1][col]
                if ((isinstance(value,str) and value.startswith('=')) or (isinstance(actual,str) and actual.startswith('='))) and value!=actual:
                    raise Rejected(f'核对表原始业务公式变化：行{n}，列{col+1}')
    finally:
        projected.close();formulas.close()
    return data

def cell(address,value):
    c=ET.Element(Q+'c',{'r':address})
    if value is None:return c
    if isinstance(value,(int,float,Decimal)):
        ET.SubElement(c,Q+'v').text=str(value)
    else:
        c.set('t','inlineStr');ET.SubElement(ET.SubElement(c,Q+'is'),Q+'t').text=str(value)
    return c

def native_project(source,columns=16,values=None):
    from native_copy.ooxml import sheet_member
    from openpyxl.utils import get_column_letter
    package=parts(source['bytes']);member=sheet_member(package,source['sheet'].name)
    main=ET.fromstring(package[member]);old={c.get('r'):c for c in main.iter(Q+'c')}
    shared={f.get('si'):(addr,f.text) for addr,c in old.items() if (f:=c.find(Q+'f')) is not None and f.get('t')=='shared' and f.text}
    rows=source['rows'];rowmap={r['source_row']:i+2 for i,r in enumerate(rows)}
    rolecols={'carton':'A','origin':'B','code':'C','ja':'I' if columns==16 else 'J','qty':'J' if columns==16 else 'K','price':'K' if columns==16 else 'L','amount':'L' if columns==16 else 'M'}
    sourcecols={k:v['column'] for k,v in rows[0]['source']['cells'].items()}
    wrap_style=photo_style=None
    if columns==20:
        styles=ET.fromstring(package['xl/styles.xml']);xfs=styles.find(Q+'cellXfs')
        ja_style=int(old[rows[0]['source']['cells']['ja']['cell']].get('s','0'))
        for kind in ['wrap','photo']:
            xf=deepcopy(list(xfs)[ja_style]);align=xf.find(Q+'alignment')
            if align is None:
                align=ET.Element(Q+'alignment');xf.insert(0,align)
            align.set('wrapText','1');align.set('vertical','bottom' if kind=='photo' else 'center');xf.set('applyAlignment','1')
            index=len(xfs);xfs.append(xf)
            if kind=='wrap':wrap_style=str(index)
            else:photo_style=str(index)
        xfs.set('count',str(len(xfs)));package['xl/styles.xml']=ET.tostring(styles,encoding='utf-8',xml_declaration=True)
    def formula(text):
        def replace(m):
            col,n=m[2],int(m[4]);role=next((k for k,v in sourcecols.items() if v==col),None)
            if role is None:raise Rejected('原公式含未映射列：'+col)
            return m[1]+rolecols[role]+m[3]+str(rowmap.get(n,n-source['header_row']+1))
        return re.sub(r'(?<![A-Za-z0-9_])([$]?)([A-Z]{1,3})([$]?)(\d+)(?![A-Za-z0-9_])',replace,text)
    sd=main.find(Q+'sheetData');sd.clear()
    header=ET.SubElement(sd,Q+'row',{'r':'1'})
    for i,label in enumerate(H16 if columns==16 else HEADERS,1):header.append(cell(get_column_letter(i)+'1',label))
    for i,record in enumerate(rows,2):
        row=ET.SubElement(sd,Q+'row',{'r':str(i),'ht':'156' if columns==20 else '20','customHeight':'1'})
        cells={}
        for role,col in rolecols.items():
            meta=record['source']['cells'][role];c=deepcopy(old[meta['cell']]);c.set('r',col+str(i))
            f=c.find(Q+'f')
            if f is not None:
                if f.get('t')=='array':raise Rejected('原表含数组公式，须先核验投影规则')
                if f.get('t')=='shared':
                    from openpyxl.formula.translate import Translator
                    if f.get('si') not in shared:raise Rejected('共享公式缺少主公式')
                    origin,expression=shared[f.get('si')];f.text=Translator('='+expression,origin=origin).translate_formula(meta['cell'])[1:];f.attrib.clear()
                f.text=formula(f.text or '')
            cells[col]=c
        cells['D']=cell('D'+str(i),record['code'])
        if columns==20:
            for col,value in (values or {}).get(i,{}).items():
                c=cell(col+str(i),value)
                if col in {'F','G','P','Q','R','S','T'}:c.set('s',wrap_style)
                if col=='E':c.set('s',photo_style)
                cells[col]=c
        for j in range(1,columns+1):
            col=get_column_letter(j);row.append(cells.get(col,cell(col+str(i),None)))
    total=ET.SubElement(sd,Q+'row',{'r':str(len(rows)+2)})
    total.append(cell('B'+str(len(rows)+2),'TOTAL'))
    # Preserve original aggregate observations and caches when present.
    for oldn in sorted(source['sheet'].rows):
        if str(source['sheet'].v(oldn,sourcecols['origin']) or '').upper()=='TOTAL':
            for role in ['qty','amount']:
                addr=sourcecols[role]+str(oldn)
                if addr not in old:continue
                c=deepcopy(old[addr]);c.set('r',rolecols[role]+str(len(rows)+2));f=c.find(Q+'f')
                if f is not None:f.text=f'SUM({rolecols[role]}2:{rolecols[role]}{len(rows)+1})'
                total.append(c)
            break
    # Seven-column adapter uses the existing native16 interface. Retain every
    # original trailing aggregate/difference cell and its formula/cache.
    final_row=len(rows)+2
    if source['profile_id']=='kmt-native-16-v1':
        trailing=[n for n in sorted(source['sheet'].rows) if n>max(r['source_row'] for r in rows)]
        if trailing:
            sd.remove(total)
            for offset,n in enumerate(trailing,len(rows)+2):
                outputrow=ET.SubElement(sd,Q+'row',{'r':str(offset)})
                for role,col in rolecols.items():
                    address=sourcecols[role]+str(n)
                    if address not in old:continue
                    c=deepcopy(old[address]);c.set('r',col+str(offset));f=c.find(Q+'f')
                    if f is not None:f.text=formula(f.text or '')
                    outputrow.append(c)
                final_row=offset
    for tag in ['mergeCells','autoFilter','cols','drawing','conditionalFormatting','dataValidations','sheetProtection']:
        for node in list(main.findall(Q+tag)):main.remove(node)
    dim=main.find(Q+'dimension')
    if dim is not None:dim.set('ref',f'A1:{get_column_letter(columns)}{final_row}')
    for view in main.findall(Q+'sheetViews/'+Q+'sheetView'):
        for oldview in list(view):
            if oldview.tag in {Q+'pane',Q+'selection'}:view.remove(oldview)
        ET.SubElement(view,Q+'pane',{'ySplit':'1','topLeftCell':'A2','activePane':'bottomLeft','state':'frozen'})
        ET.SubElement(view,Q+'selection',{'pane':'bottomLeft','activeCell':'A2','sqref':'A2'})
    cols=ET.Element(Q+'cols')
    for i in range(1,columns+1):ET.SubElement(cols,Q+'col',{'min':str(i),'max':str(i),'width':str(34 if i==5 and columns==20 else 28 if i in [6,7,10,18,19,20] else 16),'customWidth':'1'})
    main.insert(list(main).index(sd),cols)
    ET.SubElement(main,Q+'autoFilter',{'ref':f'B1:{get_column_letter(columns)}{len(rows)+1}'})
    package[member]=ET.tostring(main,encoding='utf-8',xml_declaration=True)
    return pack(source['bytes'],package)

def update_cells(data,sheet,changes):
    from native_copy.ooxml import sheet_member
    p=parts(data);m=sheet_member(p,sheet);root=ET.fromstring(p[m]);wanted={x['target']:x['value'] for x in changes};seen=set()
    for row in root.findall(Q+'sheetData/'+Q+'row'):
        for c in list(row):
            addr=c.get('r')
            if addr in wanted:
                new=cell(addr,wanted[addr])
                if c.get('s'):new.set('s',c.get('s'))
                row.insert(list(row).index(c),new);row.remove(c);seen.add(addr)
    if seen!=set(wanted):raise Rejected('目标单元格缺失')
    p[m]=ET.tostring(root,encoding='utf-8',xml_declaration=True);return pack(data,p)

def graft_images(data,canvas,sheet,items=None):
    from native_copy.ooxml import sheet_member
    p=parts(data);images=parts(canvas);m=sheet_member(p,sheet)
    if items:
        drawing=ET.fromstring(images['xl/drawings/drawing1.xml']);template=deepcopy(list(drawing)[0]);drawing.clear()
        rels=ET.Element(REL+'Relationships')
        from pathlib import Path
        for i,item in enumerate(items,1):
            anchor=deepcopy(template);start=anchor.find(XDR+'from');start.find(XDR+'row').text=str(item['row']-1);start.find(XDR+'col').text='4'
            ext=anchor.find(XDR+'ext')
            if ext is not None:ext.set('cx',str(round(item['width']*9525)));ext.set('cy',str(round(item['height']*9525)))
            for node in anchor.iter():
                if node.tag.endswith('}blip'):node.set(RID+'embed','rId'+str(i))
                if node.tag.endswith('}cNvPr'):node.set('id',str(i));node.set('name','Product '+str(item['row']))
            # Move and size with the row, so filtering/copying does not detach pictures.
            if ext is not None:
                end=deepcopy(start);end.tag=XDR+'to';end.find(XDR+'colOff').text=str(int(start.find(XDR+'colOff').text)+int(ext.get('cx')));end.find(XDR+'rowOff').text=str(int(start.find(XDR+'rowOff').text)+int(ext.get('cy')))
                anchor.tag=XDR+'twoCellAnchor';anchor.set('editAs','twoCell');anchor.remove(ext);anchor.insert(1,end)
            drawing.append(anchor);suffix=Path(item['file']).suffix.lower();suffix='.jpg' if suffix=='.jpeg' else suffix
            media=f'prepared_{i}{suffix}';images['xl/media/'+media]=Path(item['file']).read_bytes()
            ET.SubElement(rels,REL+'Relationship',{'Id':'rId'+str(i),'Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image','Target':'../media/'+media})
        images['xl/drawings/drawing1.xml']=ET.tostring(drawing,encoding='utf-8',xml_declaration=True)
        images['xl/drawings/_rels/drawing1.xml.rels']=package_xml(rels,REL[1:-1])
        ct=ET.fromstring(images['[Content_Types].xml']);ctns='{http://schemas.openxmlformats.org/package/2006/content-types}'
        for suffix,mime in [('jpg','image/jpeg'),('png','image/png')]:
            if not any(e.get('Extension')==suffix for e in ct):ET.SubElement(ct,ctns+'Default',{'Extension':suffix,'ContentType':mime})
        images['[Content_Types].xml']=package_xml(ct,ctns[1:-1])
    if any(k.startswith('xl/drawings/') for k in p):raise Rejected('原表有绘图，不能覆盖')
    for k,v in images.items():
        if k.startswith(('xl/drawings/','xl/media/')):p[k]=v
    if 'xl/drawings/drawing1.xml' not in p:return data
    root=ET.fromstring(p[m]);ET.SubElement(root,Q+'drawing',{RID+'id':'rIdPreparedPhotos'});p[m]=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    relname=m.rsplit('/',1)[0]+'/_rels/'+m.rsplit('/',1)[1]+'.rels'
    rels=ET.fromstring(p[relname]) if relname in p else ET.Element(REL+'Relationships')
    ET.SubElement(rels,REL+'Relationship',{'Id':'rIdPreparedPhotos','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing','Target':'../drawings/drawing1.xml'})
    p[relname]=package_xml(rels,REL[1:-1]);ct=ET.fromstring(p['[Content_Types].xml']);known={(e.tag,e.get('Extension') or e.get('PartName')) for e in ct}
    for e in ET.fromstring(images['[Content_Types].xml']):
        name=e.get('PartName','');ext=e.get('Extension','')
        if (name.startswith('/xl/drawings/') or ext in {'png','jpeg','jpg'}) and (e.tag,ext or name) not in known:ct.append(e)
    p['[Content_Types].xml']=package_xml(ct,'http://schemas.openxmlformats.org/package/2006/content-types')
    return pack(data,p)
