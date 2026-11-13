from copy import deepcopy
import re,xml.etree.ElementTree as ET
from native_copy.ooxml import parts,sheet_member,CELL,ROW,attr,set_attr,Styles,Q,NS,PREFIX
from stage1.workbook import packed
from .support import Rejected
from .review import EDIT,SHEET
def protect(data,plan):
    from openpyxl import load_workbook
    import io
    book=load_workbook(io.BytesIO(data));s=book[SHEET]
    if s['A3'].value!=plan['version_token']:raise Rejected('计算审核作者版本不符')
    from decimal import Decimal
    for i,r in enumerate(plan['rows'],5):
        if s['AG'+str(i)].value!=r['parent_id']:raise Rejected('计算审核原行业务ID变化')
        for col in range(1,35):
            cell=s.cell(i,col);letter=cell.column_letter
            if letter in plan['formulas']:
                if cell.value!=plan['formulas'][letter][i-5]:raise Rejected('计算审核受控公式发生变化')
                continue
            expected=r['values'][col-1];actual=cell.value
            if col in {1,6,8,10,12,13,14,17,18,19,24,25,29,34} and expected not in (None,''):
                if actual is None or Decimal(str(actual))!=Decimal(str(expected)):raise Rejected('计算审核作者改变原数值精度：'+cell.coordinate)
            elif actual!=(None if expected=='' else expected):raise Rejected('计算审核作者改变基础值：'+cell.coordinate)
    book.close();p=parts(data);member=sheet_member(p,SHEET);styles=Styles(p['xl/styles.xml']);cache={}
    def style(base,locked):
        if (base,locked) in cache:return cache[(base,locked)]
        frag=set_attr(styles.fragments[base],'applyProtection','1')
        protection=re.search(rb'<'+PREFIX+rb'protection\b[^>]*?/>',frag)
        value=b'<'+styles.p+b'protection locked="'+(b'1' if locked else b'0')+b'"/>'
        if protection:frag=frag[:protection.start()]+value+frag[protection.end():]
        elif frag.endswith(b'/>'):frag=frag[:-2]+b'>'+value+b'</'+styles.p+b'xf>'
        else:
            at=re.search(rb'</'+PREFIX+rb'xf>$',frag).start();frag=frag[:at]+value+frag[at:]
        idx=len(styles.xfs)+len(styles.extra_xfs);styles.extra_xfs.append(frag);cache[(base,locked)]=idx;return idx
    def cell(m):
        address=attr(m[0],'r');col=address.rstrip('0123456789');n=int(address[len(col):]);locked=not (n>=5 and n<5+len(plan['rows']) and col in EDIT)
        return set_attr(m[0],'s',style(int(attr(m[0],'s') or '0'),locked))
    raw=CELL.sub(cell,p[member]);prefix=re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b',raw)[1] or b''
    raw=re.sub(rb'<'+PREFIX+rb'sheetProtection\b[^>]*?(?:/>|>.*?</'+PREFIX+rb'sheetProtection>)',b'',raw,flags=re.S)
    raw=re.sub(rb'<'+PREFIX+rb'autoFilter\b[^>]*?(?:/>|>.*?</'+PREFIX+rb'autoFilter>)',b'',raw,flags=re.S)
    at=re.search(rb'<'+PREFIX+rb'(?:mergeCells|pageMargins|pageSetup|headerFooter|drawing)\b',raw)
    at=at.start() if at else re.search(rb'</'+PREFIX+rb'worksheet>',raw).start()
    extra=b'<'+prefix+b'sheetProtection sheet="1" autoFilter="0" sort="1" selectLockedCells="0" selectUnlockedCells="0"/>'
    extra+=b'<'+prefix+b'autoFilter ref="A4:AH'+str(len(plan['rows'])+4).encode()+b'"/>'
    raw=raw[:at]+extra+raw[at:];ET.fromstring(raw);p[member]=raw;p['xl/styles.xml']=styles.export()
    fields=[];rowmap=[]
    for n,r in enumerate(plan['rows'],5):
        for c,name in EDIT.items():fields.append({'row_id':r['parent_id'],'sheet':SHEET,'cell':c+str(n),'field':name,'status':'candidate','sources':[]})
        rowmap.append({'row_id':r['parent_id'],'source_row':n,'code':r['values'][2],'japanese_name':r['raw']['ja'] if r['raw'] else '',
            'source':{'sheet':SHEET,'row':n,'cells':{'code':{'cell':'C'+str(n)},'qty':{'cell':'J'+str(n)},'ja':{'cell':'D'+str(n)},'identity':{'cell':'AG'+str(n)}}}})
    reg={'fields':fields,'row_map':rowmap,'source_header_row':4,'profile_id':'loop-review-v1','protected_weight_sheets':[]}
    return packed(data,p),reg
