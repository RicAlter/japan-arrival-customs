"""Read-back checks for explicitly pending local test outputs; no approval writer."""
from pathlib import Path
from fractions import Fraction
import re,zipfile,xml.etree.ElementTree as ET
from . import Rejected,digest
from .test_final import NS

def verify(data,weights,weight_formulas,files,source,logistics):
    from openpyxl import load_workbook
    def same(a,b):
        if a in(None,'')or b in(None,''):return a in(None,'')and b in(None,'')
        if isinstance(a,(int,float))and isinstance(b,(int,float,Fraction)):return abs(Fraction(str(a))-Fraction(str(b)))<Fraction(1,10**7)
        return a==b
    result={};checks=[]
    for kind,file in zip(['internal','customs'],files):
        # Dense color/formula lookups need one in-memory read; streaming random
        # access would reparse the complete worksheet for every marked cell.
        w=load_workbook(file,read_only=False,data_only=True);wf=load_workbook(file,read_only=False,data_only=False)
        try:
            sheet=w.worksheets[0];rows=list(sheet.values);expected=data[kind]
            if '流程测试'not in str(rows[0][0]):raise Rejected('缺少可见的流程测试标记')
            if tuple(rows[2])!=tuple(expected['headers']):raise Rejected('最终表字段范围不符')
            if len(rows)!=len(expected['rows'])+4:raise Rejected('最终表行数不符')
            for er,values in enumerate(expected['rows'],3):
                if not all(same(a,b)for a,b in zip(rows[er],values)):raise Rejected('最终表重算/回读不符：'+kind+'/'+str(er+1))
            for address,color in data['colors'][kind].items():
                if sheet[address].fill.fgColor.rgb!={'yellow':'FFFFF2CC','red':'FFFFC7CE'}[color]:raise Rejected('未核标色丢失：'+address)
            if any(c.data_type=='e'for row in sheet for c in row):raise Rejected('最终表有公式错误')
            if kind=='internal':
                if w.sheetnames!=['内部到货表','重さとサイズ (2)']:raise Rejected('内部表箱重页缺失')
                observed=list(w.worksheets[1].values)
                if len(observed)!=len(weights)or not all(same(a,b)for left,right in zip(observed,weights)for a,b in zip(left,right)):raise Rejected('原箱重值不符')
                for x in weight_formulas:
                    if wf.worksheets[1][x['cell']].value!=x['formula']:raise Rejected('原箱重公式不符')
                if not same(rows[-1][10],data['totals']['original_amount']):raise Rejected('原金额合计不符')
            else:
                if w.sheetnames!=['海关报关单']:raise Rejected('海关表出现额外资料页')
                private={str(t['identity'][k])for t in data['trace']for k in ['name','yd']if t['identity'].get(k)}
                privacy=re.compile('|'.join(re.escape(token)for token in sorted(private,key=len,reverse=True)if len(token)>=4))if private else None
                if privacy and any(privacy.search(c.value)for row in sheet for c in row if isinstance(c.value,str)):raise Rejected('海关表带内部商品名/YD')
                if not same(rows[-1][15],data['totals']['rounded_amount']):raise Rejected('取整金额合计不符')
                if not same(rows[-1][16],logistics['physical_cartons']):raise Rejected('物理箱数合计不符')
            result[kind]={'file':str(file),'sha256':digest(file),'rows':len(expected['rows']),'columns':len(expected['headers'])}
        finally:w.close();wf.close()
    with zipfile.ZipFile(source)as a,zipfile.ZipFile(files[0])as b:
        original=ET.fromstring(a.read('xl/worksheets/sheet2.xml'));out=ET.fromstring(b.read('xl/worksheets/sheet2.xml'));cells={c.get('r'):c for c in out.iter(NS+'c')}
        for c in original.iter(NS+'c'):
            if c.find(NS+'f')is not None:
                candidate=cells[c.get('r')]
                if any((c.find(NS+tag).text if c.find(NS+tag)is not None else None)!=(candidate.find(NS+tag).text if candidate.find(NS+tag)is not None else None)for tag in ['f','v']):raise Rejected('箱重公式或缓存原文变化')
    return {'passed':True,'files':result,'original_weight_formulas_and_caches_preserved':True,'privacy_scan':'passed','all_rows_included':True,'formal_output':False}
