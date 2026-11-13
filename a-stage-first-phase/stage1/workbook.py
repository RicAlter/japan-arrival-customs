"""Surgical transfer of Artifact-authored business cells into the verified projection.

Only new business cells/styles/filter metadata change. Original mapped facts,
formula strings/caches, row order and all weight/external-link parts are retained.
"""
from pathlib import Path
from copy import deepcopy
import io,re,zipfile,xml.etree.ElementTree as ET
from .support import Rejected
from native_copy.ooxml import parts,sheet_member,Styles,Q,NS,PREFIX,ROW,CELL,attr,set_attr,patch_cell,signature

def packed(original,values):
    out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src,zipfile.ZipFile(out,'w') as dst:
        for info in src.infolist():dst.writestr(info,values[info.filename])
    return out.getvalue()

def version_marker(data,token):
    props='http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
    vt='http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
    p=parts(data);name='docProps/custom.xml'
    if name not in p:raise Rejected('仅复用已验证有自定义属性的原表，不猜新格式')
    root=ET.fromstring(p[name]);property='CustomsAStageExportVersion'
    if any(e.get('name')==property for e in root):raise Rejected('基础投影已带发出标记，不能重置旧业务副本')
    pid=max([1]+[int(e.get('pid')) for e in root])+1
    end=re.search(rb'</((?:\w+:)?)Properties\s*>',p[name]);prefix=end[1].decode()
    extra=f'<{prefix}property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="{pid}" name="{property}"><vt:lpwstr xmlns:vt="{vt}">{token}</vt:lpwstr></{prefix}property>'.encode()
    p[name]=p[name][:end.start()]+extra+p[name][end.start():];ET.fromstring(p[name]);return packed(data,p)

def patch_from_authored(plan):
    from openpyxl import load_workbook
    from decimal import Decimal
    original=Path(plan['input']).read_bytes();p=parts(original);member=sheet_member(p,plan['sheet']);raw=p[member]
    tree=ET.fromstring(raw);cells={c.get('r'):c for c in tree.findall('s:sheetData/s:row/s:c',NS)}
    styles=Styles(p['xl/styles.xml']);cache={};book=load_workbook(plan['artifact_output']);auth=book[plan['sheet']]
    prefix=re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b',raw)[1] or b''
    fill_ids={}
    for i,f in enumerate(styles.fills):
        pf=f.find(Q+'patternFill');fg=pf.find(Q+'fgColor') if pf is not None else None
        if fg is not None:fill_ids[fg.get('rgb')]=i
    # Existing template may not have candidate colors yet: append using the A01 helper.
    def fill_index(color):
        rgb={'yellow':'FFFFF2CC','red':'FFF4CCCC'}.get(color)
        if not rgb:return 0
        if rgb not in fill_ids:
            fill_ids[rgb]=len(styles.fills)+len(styles.extra_fills);x=styles.p
            styles.extra_fills.append(b'<'+x+b'fill><'+x+b'patternFill patternType="solid"><'+x+b'fgColor rgb="'+rgb.encode()+b'"/><'+x+b'bgColor indexed="64"/></'+x+b'patternFill></'+x+b'fill>')
        return fill_ids[rgb]
    def style(base,color,locked,general=False,wrap=False):
        k=(base,color,locked,general,wrap)
        if k in cache:return cache[k]
        frag=set_attr(set_attr(set_attr(styles.fragments[base],'fillId',fill_index(color)),'applyFill','1'),'applyProtection','1')
        if general:frag=set_attr(frag,'numFmtId','0')
        for tag,name,value in [('protection','locked','1' if locked else '0'),('alignment','wrapText','1' if wrap else None)]:
            if value is None:continue
            match=re.search(rb'<'+PREFIX+tag.encode()+rb'\b[^>]*?(?:/>|>.*?</'+PREFIX+tag.encode()+rb'>)',frag,re.S)
            if match:frag=frag[:match.start()]+set_attr(match[0],name,value)+frag[match.end():]
            else:
                extra=b'<'+styles.p+tag.encode()+b' '+name.encode()+b'="'+value.encode()+b'"/>'
                if frag.endswith(b'/>'):frag=frag[:-2]+b'>'+extra+b'</'+styles.p+b'xf>'
                else:
                    end=re.search(rb'</'+PREFIX+rb'xf>$',frag);frag=frag[:end.start()]+extra+frag[end.start():]
        idx=len(styles.xfs)+len(styles.extra_xfs);styles.extra_xfs.append(frag);cache[k]=idx;return idx
    records={r['cell']:r for r in plan['records']};rows={r['source_row'] for r in plan['row_map']};changes={};new=set();heights={}
    editable={'E','F','G','M','N','O','P','Q','R','S'}
    for n in rows:
        for col in editable|{'C','H','T','U'}:
            address=col+str(n);rec=records.get(address);old=cells.get(address)
            if rec:
                a=auth[address]
                if rec['kind']=='number':
                    if Decimal(str(a.value))!=Decimal(rec['value']):raise Rejected('数字原精度在编辑导出中变化：'+address)
                elif a.value!=rec['value']:raise Rejected('文字参考在编辑导出中变化：'+address)
            if old is not None and old.find(Q+'f') is not None:raise Rejected('计划触及原始公式：'+address)
            if rec and old is not None and (old.find(Q+'v') is not None or old.find(Q+'is') is not None):raise Rejected('业务补填不覆盖原表非空值：'+address)
            source_style=int(old.get('s','0')) if old is not None else int(cells['N'+str(n)].get('s','0'))
            changes[address]={'cell':address,'style_id':style(source_style,rec['color'] if rec else 'none',col not in editable,col in {'G','Q'},col in {'E','F','R','S'}),
                'write_value':rec['value'] if rec else None,'value_type':rec['kind'] if rec else 'text'}
            if old is None:new.add(address)
        height=auth.row_dimensions[n].height
        if height is not None:heights[n]=height
    header_sources={'G':'G1','H':'H1','Q':'G1','R':'F1','S':'F1','T':'M1','U':'N1'}
    for col,title in plan['headers'].items():
        addr=col+'1';base=int(cells[header_sources[col]].get('s','0'))
        if auth[addr].value!=title:raise Rejected('表头编辑不一致')
        changes[addr]={'cell':addr,'style_id':style(base,'none',True,False,True),'write_value':title,'value_type':'text'}
        # Preserve the gray header fill, while creating its locked clone.
        sid=changes[addr]['style_id'];frag=styles.extra_xfs[sid-len(styles.xfs)]
        frag=set_attr(frag,'fillId',styles.xfs[base].get('fillId','0'));styles.extra_xfs[sid-len(styles.xfs)]=frag
        if addr not in cells:new.add(addr)
    byrow={}
    for address,change in changes.items():byrow.setdefault(int(re.search(r'\d+$',address)[0]),{})[address]=change
    def row_patch(match):
        rawrow=match[0];n=int(attr(rawrow,'r'));items=byrow.get(n,{})
        seen=set()
        def cell_patch(m):
            a=attr(m[0],'r')
            if a not in items:return m[0]
            seen.add(a);return patch_cell(m[0],items[a],prefix)
        result=CELL.sub(cell_patch,rawrow)
        for addr in sorted(set(items)-seen,key=lambda a:(len(a.rstrip('0123456789')),a.rstrip('0123456789'))):
            fragment=patch_cell(None,items[addr],prefix)
            after=next((m.start() for m in CELL.finditer(result) if (len(attr(m[0],'r').rstrip('0123456789')),attr(m[0],'r').rstrip('0123456789'))>(len(addr.rstrip('0123456789')),addr.rstrip('0123456789'))),None)
            if after is None:after=re.search(rb'</'+PREFIX+rb'row>$',result).start()
            result=result[:after]+fragment+result[after:]
        if n in heights:result=set_attr(set_attr(result,'ht',heights[n]),'customHeight','1')
        return result
    updated=ROW.sub(row_patch,raw)
    end=re.search(rb'</'+PREFIX+rb'cols>',updated);assert end
    extra=b''.join(b'<'+prefix+b'col min="'+str(i).encode()+b'" max="'+str(i).encode()+b'" width="'+str(width).encode()+b'" customWidth="1" style="'+str(style(0,'none',i>=20)).encode()+b'"/>' for i,width in [(17,20),(18,28),(19,28),(20,16),(21,28)])
    updated=updated[:end.start()]+extra+updated[end.start():]
    dimension=re.search(rb'<'+PREFIX+rb'dimension\b[^>]*>',updated)
    if dimension:updated=updated.replace(dimension[0],set_attr(dimension[0],'ref','A1:U1316'),1)
    else:
        at=re.search(rb'<'+PREFIX+rb'(?:sheetViews|sheetFormatPr|cols|sheetData)\b',updated).start()
        updated=updated[:at]+b'<'+prefix+b'dimension ref="A1:U1316"/>'+updated[at:]
    protection=re.search(rb'<'+PREFIX+rb'sheetProtection\b[^>]*>',updated);updated=updated.replace(protection[0],set_attr(set_attr(protection[0],'autoFilter','0'),'sort','1'),1)
    af=re.search(rb'<'+PREFIX+rb'autoFilter\b[^>]*?(?:/>|>.*?</'+PREFIX+rb'autoFilter>)',updated,re.S)
    if af:updated=updated[:af.start()]+set_attr(af[0],'ref',plan['filter_range'])+updated[af.end():]
    else:
        at=re.search(rb'<'+PREFIX+rb'(?:mergeCells|conditionalFormatting|dataValidations|pageMargins|pageSetup|headerFooter)\b',updated).start()
        updated=updated[:at]+b'<'+prefix+b'autoFilter ref="'+plan['filter_range'].encode()+b'"/>'+updated[at:]
    # Restore every authorized edit, then assert the original source sheet matches.
    before=ET.fromstring(raw);after=ET.fromstring(updated)
    for r in after.findall('s:sheetData/s:row',NS):
        for c in list(r):
            addr=c.get('r')
            if addr in new:r.remove(c)
            elif addr in changes:
                idx=list(r).index(c);r.remove(c);r.insert(idx,deepcopy(cells[addr]))
    # Restore row metadata separately without relying on a replaced r attribute.
    for old,r in zip(before.findall('s:sheetData/s:row',NS),after.findall('s:sheetData/s:row',NS)):
        r.attrib.clear();r.attrib.update(old.attrib)
    for name in ['cols','dimension','sheetProtection','autoFilter']:
        old=before.find(Q+name);current=after.find(Q+name)
        if current is not None:
            idx=list(after).index(current);after.remove(current)
            if old is not None:after.insert(idx,deepcopy(old))
    if signature(before)!=signature(after):raise Rejected('原始事实、公式、行序或未授权布局发生变化')
    book.close();p[member]=updated;p['xl/styles.xml']=styles.export();result=packed(original,p)
    first,last=parts(original),parts(result)
    if any(first[k]!=last[k] for k in first if k not in {member,'xl/styles.xml'}):raise Rejected('箱重或原外部链接等部件改变')
    return result,{'source_projection_implementation_reused':True,'protected_facts_formulas_caches_preserved':True,'weight_parts_byte_identical':True,
        'other_package_parts_byte_identical':True,'business_rows':len(rows),'registered_columns':21,'pricing_deferred':True,
        'box_formula_written':False,'price_difference_written':False,'controlled_business_cell_edits':len(changes)}
