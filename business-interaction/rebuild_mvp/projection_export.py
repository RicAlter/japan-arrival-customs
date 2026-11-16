"""Artifact authors customs; native finalization retains the approved OOXML style.

The internal workbook is a byte-identical copy, retaining images and all native
features. No historical customs workbook is copied into the new package.
"""
from pathlib import Path
from copy import deepcopy
import json,math,os,re,subprocess,zipfile,xml.etree.ElementTree as ET
from fractions import Fraction
from .service import MvpError,save_json,load_json,digest,HERE
from .storage import identity
from .xlsxio import Q,read_book,sheet_info,col_letter
from .projection_sources import TEMPLATE
from .projection_math import excel_number


def author_plan(rows,total,output,renderer):
    template=load_json(TEMPLATE);layout=template['customs'];matrix=[layout['headers']];formulas={};marks={}
    for row in rows:
        n=row['output_row'];matrix.append([row['values'].get(col_letter(c))for c in range(1,34)])
        if row['formula']:formulas['P'+str(n)]=row['formula']
        for col,state in row['cells'].items():
            if state['state']in {'pending','reference'}:marks[col+str(n)]=state['state']
    footer=len(matrix)+1;values=[None]*33
    partial=any(not t['complete']for t in total.values())
    values[0]='已填合计（有缺项）'if partial else'已填合计'
    for col,t in total.items():
        if t['excel_value']is not None:
            values[ord(col)-65]=t['excel_value'];formulas[col+str(footer)]=f'SUM({col}2:{col}{footer-1})'
            if not t['complete']:marks[col+str(footer)]='pending'
    matrix.append(values)
    note=['草稿：红色为待补，黄色为参考。单价和金额为JPY；原金额保留在内部表。箱重仅在首次出现处计一次。']+[None]*32
    matrix.append(note)
    return {'sheet':layout['sheet'],'matrix':matrix,'formulas':formulas,'marks':marks,'footer_row':footer,
            'merges':template['customs_merges']+[f'A{footer+1}:S{footer+1}'],'layout':layout,
            'output':str(output),'inspection':str(Path(output).with_suffix('.author-inspection.json')),
            'node_modules':renderer['node_modules']}


def run_author(plan,renderer,plan_file):
    save_json(plan_file,plan)
    p=subprocess.run([renderer['node'],str(HERE/'dual_author.mjs'),str(plan_file)],capture_output=True,text=True,encoding='utf8',timeout=300)
    save_json(Path(plan_file).with_suffix('.process.json'),{'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    if p.returncode:raise MvpError('RUNTIME_FAILURE','Artifact生成海关模板失败；查看本任务author process记录')


def finite_text(value):
    return repr(value)if isinstance(value,float)else str(value)


def sum_roundoff(plan,n,c,value,actual):
    """One-ULP Artifact SUM residue only; exact plan and final file stay strict."""
    from .quantity_math import number
    col=col_letter(c)
    if (n!=plan['footer_row'] or not isinstance(value,float) or not math.isfinite(value)
            or plan['formulas'].get(col+str(n))!=f'SUM({col}2:{col}{n-1})'):
        return None
    terms=[row[c-1] for row in plan['matrix'][1:n-1] if row[c-1] is not None]
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in terms):return None
    if sum((number(x) for x in terms),Fraction(0))!=number(value):return None
    observed=number(actual)
    if observed is None or abs(observed-number(value))>Fraction.from_float(math.ulp(value)):return None
    return {'cell':col+str(n),'formula':plan['formulas'][col+str(n)],'artifact_cache':actual,
            'exact_plan_cache':str(value),'maximum_absolute_error':repr(math.ulp(value)),
            'classification':'one_ULP_SUM_engine_residue','final_cache_policy':'exact_versioned_result_required'}


def check_author(path,plan,allow_sum_roundoff=False):
    book=read_book(path)
    if len(book['sheets'])!=1 or book['sheets'][0]['name']!=plan['sheet']:raise MvpError('TASK_CONFLICT','海关生成器工作表不符')
    rows={r['row']:r for r in book['sheets'][0]['rows']};roundoff=[]
    from .quantity_math import number
    for n,expected in enumerate(plan['matrix'],1):
        for c,value in enumerate(expected,1):
            col=col_letter(c);actual=rows.get(n,{}).get('values',{}).get(col,'')
            if isinstance(value,(int,float))and number(actual)!=number(value):
                residue=sum_roundoff(plan,n,c,value,actual)if allow_sum_roundoff else None
                if residue is None:raise MvpError('RUNTIME_FAILURE','Artifact数值/公式重算与版本化结果不符：'+col+str(n))
                roundoff.append(residue)
            if value is None and actual not in {'',None}:raise MvpError('RUNTIME_FAILURE','缺项被误填数值：'+col+str(n))
            if isinstance(value,str)and actual not in {value,"'"+value}:raise MvpError('RUNTIME_FAILURE','Artifact文本不符：'+col+str(n))
            if rows.get(n,{}).get('formulas',{}).get(col)!=plan['formulas'].get(col+str(n)):
                raise MvpError('RUNTIME_FAILURE','Artifact公式位置或写法不符：'+col+str(n))

    return roundoff


def element(text):
    node=ET.fromstring(text)
    for e in node.iter():
        if not e.tag.startswith('{'):e.tag=Q+e.tag
    return node


def styles_for(plan):
    root=ET.Element(Q+'styleSheet');formats=ET.SubElement(root,Q+'numFmts');fonts=ET.SubElement(root,Q+'fonts');fills=ET.SubElement(root,Q+'fills');borders=ET.SubElement(root,Q+'borders')
    fonts.append(element('<font><sz val="10"/><name val="Arial"/></font>'))
    fills.append(element('<fill><patternFill patternType="none"/></fill>'));fills.append(element('<fill><patternFill patternType="gray125"/></fill>'))
    borders.append(element('<border/>'));stylexfs=ET.SubElement(root,Q+'cellStyleXfs');ET.SubElement(stylexfs,Q+'xf',{'numFmtId':'0','fontId':'0','fillId':'0','borderId':'0'})
    xfs=ET.SubElement(root,Q+'cellXfs');ET.SubElement(xfs,Q+'xf',{'numFmtId':'0','fontId':'0','fillId':'0','borderId':'0','xfId':'0'})
    cache={};indices={}
    def add(style,mark=None,identifier=False):
        key=identity([style,mark,identifier])
        if key in cache:return cache[key]
        font=element(style['font']);fill=element(style['fill']);border=element(style['border'])
        if mark:fill=element('<fill><patternFill patternType="solid"><fgColor rgb="'+('FFFCE4D6'if mark=='pending'else'FFFFF2CC')+'"/></patternFill></fill>')
        fi,fl,bi=len(fonts),len(fills),len(borders);fonts.append(font);fills.append(fill);borders.append(border)
        fmt='@'if identifier else style['number_format'];num=0
        if fmt!='General':num=164+len(formats);ET.SubElement(formats,Q+'numFmt',{'numFmtId':str(num),'formatCode':fmt})
        xf=ET.SubElement(xfs,Q+'xf',{'numFmtId':str(num),'fontId':str(fi),'fillId':str(fl),'borderId':str(bi),'xfId':'0','applyAlignment':'1','applyNumberFormat':'1'})
        xf.append(element(style['alignment']));xf.append(element(style['protection']))
        cache[key]=len(xfs)-1;return cache[key]
    for n,row in enumerate(plan['matrix'],1):
        for c in range(1,34):
            col=col_letter(c);style=plan['layout']['header_styles'if n==1 else'data_styles'][c-1]
            indices[col+str(n)]=add(style,plan['marks'].get(col+str(n)),c==2 and n>1)
    for group in [formats,fonts,fills,borders,stylexfs,xfs]:group.set('count',str(len(group)))
    cs=ET.SubElement(root,Q+'cellStyles',{'count':'1'});ET.SubElement(cs,Q+'cellStyle',{'name':'Normal','xfId':'0','builtinId':'0'})
    return ET.tostring(root,encoding='utf-8',xml_declaration=True),indices


def finalize_native(path,plan):
    with zipfile.ZipFile(path)as z:parts={name:z.read(name)for name in z.namelist()}
    member=sheet_info(path)[0]['path'];sheet=ET.fromstring(parts[member]);data=sheet.find(Q+'sheetData');data[:]=[]
    styles,indices=styles_for(plan)
    for n,row in enumerate(plan['matrix'],1):
        r=ET.SubElement(data,Q+'row',{'r':str(n),'ht':str(plan['layout']['header_height']if n==1 else plan['layout']['data_height']),'customHeight':'1'})
        for c,value in enumerate(row,1):
            addr=col_letter(c)+str(n);cell=ET.SubElement(r,Q+'c',{'r':addr,'s':str(indices[addr])});formula=plan['formulas'].get(addr)
            if formula:ET.SubElement(cell,Q+'f').text=formula
            if value is None:continue
            if isinstance(value,(int,float)):
                cell.set('t','n');ET.SubElement(cell,Q+'v').text=finite_text(value)
            else:
                cell.set('t','inlineStr');text=ET.SubElement(ET.SubElement(cell,Q+'is'),Q+'t');text.set('{http://www.w3.org/XML/1998/namespace}space','preserve');text.text=str(value)
    dimension=sheet.find(Q+'dimension')
    if dimension is not None:dimension.set('ref',f'A1:AG{len(plan["matrix"])}')
    cols=sheet.find(Q+'cols')
    if cols is None:cols=ET.Element(Q+'cols');sheet.insert(list(sheet).index(data),cols)
    cols[:]=[]
    for d in plan['layout']['column_dimensions'].values():
        first,end=max(1,d['min']),min(33,d['max'])
        if first<=end:ET.SubElement(cols,Q+'col',{'min':str(first),'max':str(end),'width':str(d['width']),'customWidth':'1','hidden':'0'})
    parts[member]=ET.tostring(sheet,encoding='utf-8',xml_declaration=True);parts['xl/styles.xml']=styles
    if 'xl/theme/theme1.xml'in parts:parts['xl/theme/theme1.xml']=load_json(TEMPLATE)['theme_xml'].encode('utf8')
    parts.pop('xl/sharedStrings.xml',None)
    for filename in ['xl/_rels/workbook.xml.rels','[Content_Types].xml']:
        tree=ET.fromstring(parts[filename])
        for child in list(tree):
            if child.get('Type','').endswith('/sharedStrings')or child.get('PartName')=='/xl/sharedStrings.xml':tree.remove(child)
        # OPC readers expect the package roots in their default namespace.
        # Restore the spreadsheet namespace immediately for deterministic styles.
        namespace=tree.tag.split('}')[0][1:]
        try:
            ET.register_namespace('',namespace)
            parts[filename]=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
        finally:ET.register_namespace('',Q[1:-1])
    temp=Path(path).with_suffix('.style.tmp')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True)as z:
        for name,value in parts.items():z.writestr(name,value)
    os.replace(temp,path)


def verify_customs(path,plan,tokens):
    check_author(path,plan)
    styles,indices=styles_for(plan)
    with zipfile.ZipFile(path)as z:
        if z.read('xl/styles.xml')!=styles:raise MvpError('TASK_CONFLICT','海关版式样式发生变化')
        forbidden=[n for n in z.namelist()if any(s in n.lower()for s in ['externallinks','vba','comments','customxml','embeddings','drawings','connections'])]
        if forbidden:raise MvpError('TASK_CONFLICT','海关包包含非许可部件')
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        if wb.find(Q+'definedNames')is not None and len(wb.find(Q+'definedNames')):raise MvpError('TASK_CONFLICT','海关草稿不得带原内部名称')
        tree=ET.fromstring(z.read(sheet_info(path)[0]['path']))
        if sheet_info(path)[0]['state']!='visible':raise MvpError('TASK_CONFLICT','海关工作表被隐藏')
        pane=tree.find(Q+'sheetViews/'+Q+'sheetView/'+Q+'pane')
        if pane is None or pane.get('topLeftCell')!='A2'or pane.get('ySplit')!='1':raise MvpError('TASK_CONFLICT','海关冻结布局不符')
        if {m.get('ref')for m in tree.findall(Q+'mergeCells/'+Q+'mergeCell')}!=set(plan['merges']):raise MvpError('TASK_CONFLICT','海关合并布局不符')
        for cell in tree.findall(Q+'sheetData/'+Q+'row/'+Q+'c'):
            if cell.get('s')!=str(indices[cell.get('r')]):raise MvpError('TASK_CONFLICT','海关单元格样式不符')
        if any(r.get('hidden')in {'1','true'}for r in tree.findall(Q+'sheetData/'+Q+'row')):raise MvpError('TASK_CONFLICT','海关商品行被隐藏')
        actual_cols=[(int(c.get('min')),int(c.get('max')),float(c.get('width')))for c in tree.findall(Q+'cols/'+Q+'col')]
        wanted=[(max(1,d['min']),min(33,d['max']),float(d['width']))for d in plan['layout']['column_dimensions'].values()if max(1,d['min'])<=min(33,d['max'])]
        if actual_cols!=wanted:raise MvpError('TASK_CONFLICT','海关列宽/列数不符')
        texts=[]
        for name in z.namelist():
            if name.endswith('.xml'):
                e=ET.fromstring(z.read(name));texts.extend(e.itertext());texts.extend(v for n in e.iter()for v in n.attrib.values())
        xml='\n'.join(texts)
        # Explicit origin/carton/code values may coincide with short private labels;
        # all free text was checked before authoring. Longer private tokens cannot
        # survive in hidden metadata either.
        permitted={str(row[i])for row in plan['matrix']for i in [0,1,3]if row[i]is not None}
        if any(token in xml for token in tokens if token not in permitted):raise MvpError('TASK_CONFLICT','海关文件含内部文本')
    return {'path':str(path),'sha256':digest(path),'columns':33,'sheet':plan['sheet'],'headers_and_formula_caches_verified':True,'approved_style_sha256':identity(load_json(TEMPLATE)['customs']),'private_text_excluded':True}


def export_customs(rows,total,output,renderer,tokens):
    output=Path(output);plan=author_plan(rows,total,output.with_suffix('.authoring.xlsx'),renderer)
    if output.exists():return verify_customs(output,plan,tokens)
    run_author(plan,renderer,output.with_suffix('.author-plan.json'))
    roundoff=check_author(plan['output'],plan,allow_sum_roundoff=True)
    save_json(output.with_suffix('.author-roundoff.json'),{'formula_roundoff':roundoff,'final_verification':'strict_exact'})
    finalize_native(plan['output'],plan);proof=verify_customs(plan['output'],plan,tokens)
    proof['artifact_formula_roundoff']=roundoff
    os.replace(plan['output'],output);proof.update(path=str(output),sha256=digest(output));return proof
