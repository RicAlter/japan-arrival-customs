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
        for col in range(42,len(plan['headers'])+1):
            from openpyxl.utils.cell import get_column_letter
            letter=get_column_letter(col)
            if letter in plan['formulas']:
                if s.cell(n,col).value!=plan['formulas'][letter][n-5]:raise Rejected('原始事实核验公式变化')
                continue
            expected=row['values'][col-1];actual=s.cell(n,col).value
            if col in {42,43,44} and expected not in (None,''):
                if actual is None or Decimal(str(actual))!=Decimal(str(expected)):raise Rejected('原数量金额精度变化')
            elif actual!=(None if expected=='' else expected):raise Rejected('计算审核追加原始事实变化')
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
