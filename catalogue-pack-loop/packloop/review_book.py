"""Extend original review protection only over newly appended packaging fields."""
from .support import Rejected
from .review import SHEET
base=None
def protect(data,plan):
    from openpyxl import load_workbook
    from native_copy.ooxml import parts
    from stage1.workbook import packed
    from decimal import Decimal
    import io,re
    w=load_workbook(io.BytesIO(data));s=w[SHEET]
    for n,row in enumerate(plan['rows'],5):
        for col in range(35,42):
            cell=s.cell(n,col);letter=cell.column_letter;expected=row['values'][col-1]
            if letter in plan['formulas']:
                if cell.value!=plan['formulas'][letter][n-5]:raise Rejected('包装审核公式变化')
            elif col in {35,36} and expected not in (None,''):
                if cell.value is None or Decimal(str(cell.value))!=Decimal(str(expected)):raise Rejected('包装原参考精度变化')
            elif cell.value!=expected:raise Rejected('包装审核原输入变化')
    w.close();result,reg=base.protect(data,plan);p=parts(result)
    for k in list(p):
        if k.startswith('xl/worksheets/') and k.endswith('.xml'):p[k]=p[k].replace(('ref="A4:AH'+str(len(plan['rows'])+4)+'"').encode(),('ref="A4:AO'+str(len(plan['rows'])+4)+'"').encode())
    return packed(result,p),reg
