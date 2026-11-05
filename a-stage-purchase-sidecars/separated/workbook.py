"""Transfer verified Artifact column move, preserving every A:P cell bytewise."""
from pathlib import Path
import re,xml.etree.ElementTree as ET
from .support import Rejected
from stage1.workbook import packed
from native_copy.ooxml import parts,sheet_member,CELL,ROW,PREFIX,attr,set_attr,Q,NS
def main18(source,authored,sheet,token):
    from openpyxl import load_workbook
    data=Path(source).read_bytes();p=parts(data);member=sheet_member(p,sheet);original=p[member]
    old=load_workbook(source);new=load_workbook(authored);a=old[sheet];b=new[sheet]
    for n in range(1,1277):
        if a['T'+str(n)].value!=b['Q'+str(n)].value or a['U'+str(n)].value!=b['R'+str(n)].value:raise Rejected('AI列移动后的作者数据不一致')
    old.close();new.close()
    def move(match):
        address=attr(match[0],'r');col=address.rstrip('0123456789')
        if col in {'Q','R','S'}:return b''
        if col in {'T','U'}:return set_attr(match[0],'r',{'T':'Q','U':'R'}[col]+address[len(col):])
        return match[0]
    updated=CELL.sub(move,original)
    prefix=re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b',updated)[1] or b''
    def cols(match):
        result=match[0]
        result=re.sub(rb'<'+PREFIX+rb'col\b[^>]*?/>',lambda m:b'' if int(attr(m[0],'min'))>=17 else m[0],result)
        end=re.search(rb'</'+PREFIX+rb'cols>',result).start()
        extra=b''.join(b'<'+prefix+b'col min="'+str(n).encode()+b'" max="'+str(n).encode()+b'" width="'+str(w).encode()+b'" customWidth="1"/>' for n,w in [(17,16),(18,28)])
        return result[:end]+extra+result[end:]
    updated=re.sub(rb'<'+PREFIX+rb'cols\b[^>]*>.*?</'+PREFIX+rb'cols>',cols,updated,flags=re.S)
    for name,address in [('dimension','A1:R1316'),('autoFilter','B1:R1313')]:
        updated=re.sub(rb'<'+PREFIX+name.encode()+rb'\b[^>]*>',lambda m:set_attr(m[0],'ref',address),updated,count=1)
    cells=lambda raw:{attr(m[0],'r'):m[0] for m in CELL.finditer(raw) if len(attr(m[0],'r').rstrip('0123456789'))==1 and attr(m[0],'r').rstrip('0123456789')<='P'}
    if cells(original)!=cells(updated):raise Rejected('主表A:P原内容、公式/cache或样式发生变化')
    # The original per-row ordering stays intact; only Q:S disappear and T/U move.
    for before,after in zip(ROW.finditer(original),ROW.finditer(updated)):
        if re.match(rb'<[^>]+>',before[0])[0]!=re.match(rb'<[^>]+>',after[0])[0]:raise Rejected('数据行或原行高被改变')
    ET.fromstring(updated);p[member]=updated
    root=ET.fromstring(p['docProps/custom.xml']);matches=[e for e in root if e.get('name')=='CustomsAStageExportVersion']
    if len(matches)!=1:raise Rejected('原副本版本标记无效')
    previous=list(matches[0])[0].text
    if p['docProps/custom.xml'].count(previous.encode())!=1:raise Rejected('版本标记无法唯一更新')
    p['docProps/custom.xml']=p['docProps/custom.xml'].replace(previous.encode(),token.encode())
    result=packed(data,p);after=parts(result)
    if any(after[k]!=v for k,v in parts(data).items() if k not in {member,'docProps/custom.xml'}):raise Rejected('箱重、链接或其他原部件改变')
    return result,{'main_a_to_p_cells_byte_identical':True,'weight_and_links_byte_identical':True,'row_order_and_heights_preserved':True,
        'removed_columns':['采购数量（独立）','采购计价单位','采购数量单位'],'ai_reference_columns':['Q','R'],'columns':18}
