"""Opt-in 39-column view over a saved batch, with immutable stage receipts."""
from pathlib import Path
from collections import Counter
from fractions import Fraction
import copy,hashlib,json,re,subprocess,zipfile,io,xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from .stage2_math import POLICY,HEADERS,calculate,number
from . import load,save,digest,Rejected,put

Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
MEMBER='xl/worksheets/sheet1.xml'
CELL=re.compile(rb'<c\b[^>]*?/>|<c\b[^>]*>.*?</c>',re.S)
def address(c):return re.search(rb'\br="([^"]+)"',c)[1].decode()
def col(n):
    s=''
    while n:n,r=divmod(n-1,26);s=chr(65+r)+s
    return s
def scalar(v):return float(v) if isinstance(v,Fraction) and v.denominator!=1 else int(v) if isinstance(v,Fraction) else v

def cells_file(file):
    from openpyxl import load_workbook
    w=load_workbook(file,read_only=True,data_only=False,keep_links=False)
    try:
        return {(s.title,c.coordinate):c.value for s in w for row in s for c in row if c.value is not None}
    finally:w.close()

def view_token(file):
    with zipfile.ZipFile(file) as z:
        root=ET.fromstring(z.read('xl/workbook.xml'))
    return next((x.text for x in root.iter(Q+'definedName') if x.get('name')=='stage2_view_token'),None)

def confirmation_attention(facts,rows):
    """Same sparse yellow/red convention as stage one; no explanation cells."""
    result={}
    for fact,row in zip(facts,rows):
        errors=row['errors'];cell='U'+str(row['row'])
        if any('冲突' in e or '不能整除' in e for e in errors):result[cell]='red'
        elif '缺独立盒规，参考盒数待核' in errors and '整盒' in str(fact['identity'].get('spec') or ''):result[cell]='yellow'
        if row['rounded_price'] is None:result['I'+str(row['row'])]='red'
    return result

def patch_workbook(source,authored,target,changed,token,*,compact=False,attention=None,results_only=False,factor_column=False,clear_references=None):
    """Keep old cells/styles/cache, pictures and weight members intact."""
    with zipfile.ZipFile(authored) as z:
        xml=z.read(MEMBER).replace(b'<x:',b'<').replace(b'</x:',b'</')
        new={address(m[0]):m[0] for m in CELL.finditer(xml)}
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        for a,c in list(new.items()):
            if b't="s"' in c:
                value=strings[int(re.search(rb'<v>(\d+)</v>',c)[1])]
                new[a]=re.sub(rb'<v>.*?</v>',('<is><t xml:space="preserve">'+escape(value)+'</t></is>').encode(),c.replace(b't="s"',b't="inlineStr"'),flags=re.S)
    with zipfile.ZipFile(source) as z:
        infos=z.infolist();parts={i.filename:z.read(i.filename) for i in infos}
    raw=parts[MEMBER];old={address(m[0]):m[0] for m in CELL.finditer(raw)}
    header_style=re.search(rb'\bs="(\d+)"',old.get('U1',b''));body_style=re.search(rb'\bs="(\d+)"',old['I2'])
    # Extend styles without altering any existing style index or definition.
    styles=parts['xl/styles.xml'];xf=ET.fromstring(styles).find(Q+'cellXfs');index=len(xf)
    style_root=ET.fromstring(styles);formats=style_root.find(Q+'numFmts')
    fmtid=max([163]+[int(x.get('numFmtId')) for x in formats] if formats is not None else [163])+1
    fmt=('<numFmt numFmtId="%d" formatCode="0.########"/>'%fmtid).encode()
    if formats is not None:
        styles=re.sub(rb'<numFmts\b.*?</numFmts>',lambda m:re.sub(rb'count="\d+"',('count="%d"'%(len(formats)+1)).encode(),m[0],count=1).replace(b'</numFmts>',fmt+b'</numFmts>'),styles,flags=re.S)
    else:styles=styles.replace(b'<fonts',b'<numFmts count="1">'+fmt+b'</numFmts><fonts',1)
    base=copy.deepcopy(xf[int(body_style[1])]);base.set('numFmtId',str(fmtid));base.set('applyNumberFormat','1')
    alignment=base.find(Q+'alignment')
    if alignment is None:alignment=ET.SubElement(base,Q+'alignment')
    alignment.set('wrapText','1');alignment.set('vertical','top')
    percent=copy.deepcopy(base);percent.set('numFmtId','10')
    appended=b''.join(ET.tostring(x,encoding='utf-8').replace(b'ns0:',b'').replace(b':ns0',b'') for x in [base,percent])
    def extend(m):
        block=m[0];block=re.sub(rb'count="\d+"',('count="%d"'%(index+2)).encode(),block,count=1)
        return block.replace(b'</cellXfs>',appended+b'</cellXfs>')
    parts['xl/styles.xml']=re.sub(rb'<cellXfs\b.*?</cellXfs>',extend,styles,flags=re.S)
    attention=attention or {};attention_styles={}
    if (compact or results_only) and attention:
        root=ET.fromstring(parts['xl/styles.xml']);fills=root.find(Q+'fills');fill_start=len(fills)
        additions=b''.join(('<fill><patternFill patternType="solid"><fgColor rgb="%s"/><bgColor indexed="64"/></patternFill></fill>'%color).encode() for color in ['FFFFF2CC','FFFCE4D6'])
        parts['xl/styles.xml']=re.sub(rb'<fills\b.*?</fills>',lambda m:re.sub(rb'count="\d+"',('count="%d"'%(fill_start+2)).encode(),m[0],count=1).replace(b'</fills>',additions+b'</fills>'),parts['xl/styles.xml'],flags=re.S)
        extra_styles=[];keys={}
        for addr,color in attention.items():
            result_cell=results_only and re.fullmatch(r'(V|W|X|Y|Z)\d+',addr)
            if addr not in old and not result_cell:continue
            original_style=re.search(rb'\bs="(\d+)"',old.get(addr,b''));sid=int(original_style[1])if original_style else 0
            k=('result'if result_cell else sid,color)
            if k not in keys:
                x=copy.deepcopy(base if result_cell else xf[sid]);x.set('fillId',str(fill_start+int(color=='red')));x.set('applyFill','1')
                keys[k]=index+2+len(extra_styles)
                extra_styles.append(ET.tostring(x,encoding='utf-8').replace(b'ns0:',b'').replace(b':ns0',b''))
            attention_styles[addr]=keys[k]
        parts['xl/styles.xml']=re.sub(rb'<cellXfs\b.*?</cellXfs>',lambda m:re.sub(rb'count="\d+"',('count="%d"'%(index+2+len(extra_styles))).encode(),m[0],count=1).replace(b'</cellXfs>',b''.join(extra_styles)+b'</cellXfs>'),parts['xl/styles.xml'],flags=re.S)
    def newcell(a):
        c=new.get(a,('<c r="'+a+'"/>').encode());style=header_style if a.endswith('1') and not re.search(r'\d',a[:-1]) else body_style
        # Header row is addressed explicitly, not by a string suffix (row11 etc).
        style=header_style if re.sub(r'\D','',a)=='1' else body_style
        c=re.sub(rb'\s+s="[^"]*"',b'',c)
        sid=style[1] if re.sub(r'\D','',a)=='1' and style else str(index+int(a.startswith(('AE','AF')))).encode()
        c=c.replace(b'<c ',b'<c s="'+sid+b'" ',1)
        # Header/text content must carry inline strings: sidecar uses t=str or inlineStr.
        return c
    def row(m):
        rr=m[0];n=int(re.search(rb'\br="(\d+)"',rr)[1])
        if n==1 or n in changed:
            def replace(c):
                a=address(c[0])
                if factor_column and a=='I1':return newcell('I1')
                if a in (clear_references or set()):
                    attrs=re.search(rb'<c\b([^>]*?)(?:/?>)',c[0])[1]
                    return b'<c'+re.sub(rb'\s+t="[^"]*"',b'',attrs)+b'/>'
                if n in changed and a in {'I'+str(n),'K'+str(n)}:
                    replacement=new[a];inner=re.search(rb'<c\b[^>]*>(.*)</c>',replacement,re.S)[1]
                    # Preserve exact original XML for numerically unchanged I/K.
                    before=re.search(rb'<v>([^<]+)</v>',c[0]);after=re.search(rb'<v>([^<]+)</v>',replacement)
                    if not(factor_column and a.startswith('I')) and before and after and number(before[1].decode())==number(after[1].decode()):return c[0]
                    attrs=re.search(rb'<c\b([^>]*?)(?:/?>)',c[0])[1];attrs=re.sub(rb'\s+t="[^"]*"',b'',attrs)
                    return b'<c'+attrs+b'>'+inner+b'</c>'
                return c[0]
            rr=CELL.sub(replace,rr)
            end=27 if results_only else 40
            extras=b'' if compact and not results_only else b''.join(newcell(col(i)+str(n)) for i in range(22,end) if col(i)+str(n) in new or col(i)+str(n) in attention_styles)
            rr=rr.replace(b'</row>',extras+b'</row>')
        return rr
    raw=re.sub(rb'<row\b[^>]*>.*?</row>',row,raw,flags=re.S)
    if attention_styles:
        def recolor(m):
            a=address(m[0])
            if a not in attention_styles:return m[0]
            c=re.sub(rb'\s+s="[^"]*"',b'',m[0])
            return c.replace(b'<c ',('<c s="%d" '%attention_styles[a]).encode(),1)
        raw=CELL.sub(recolor,raw)
    dim=re.search(rb'<dimension\b[^>]*\bref="([^"]+)"',raw)
    last=max(max(changed),int(re.search(rb'(\d+)$',dim[1])[1]) if dim else 1)
    raw=re.sub(rb'(<dimension\b[^>]*\bref=")[^"]+("[^>]*/>)',rb'\g<1>A1:'+ (b'Z'if results_only else b'U'if compact else b'AM')+str(last).encode()+rb'\g<2>',raw)
    # Append only new column widths. Preserve original A:U definitions exactly.
    extra=b''.join(('<col min="%d" max="%d" width="%s" customWidth="1"/>'%(i,i,22 if results_only else 44 if i==39 else 30 if i in {37,38} else 18)).encode() for i in range(22,27 if results_only else 40))
    if not compact or results_only:
        if b'</cols>' in raw:raw=raw.replace(b'</cols>',extra+b'</cols>')
        else:raw=raw.replace(b'<sheetData>',b'<cols>'+extra+b'</cols><sheetData>')
    parts[MEMBER]=raw
    wb=parts['xl/workbook.xml'];name=('<definedName name="stage2_view_token">"'+token+'"</definedName>').encode()
    if b'</definedNames>' in wb:wb=wb.replace(b'</definedNames>',name+b'</definedNames>')
    else:wb=wb.replace(b'</workbook>',b'<definedNames>'+name+b'</definedNames></workbook>')
    parts['xl/workbook.xml']=wb
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        for info in infos:z.writestr(copy.copy(info),parts[info.filename])
    Path(target).write_bytes(buf.getvalue())

class CalculationView:
    def __init__(self,service):
        self.service=service;self.config=service.config;self.path=Path(self.config['calculation_view_binding'])
        if digest(self.path)!=self.config['calculation_view_binding_sha256']:raise Rejected('第二阶段绑定SHA变化')
        self.binding=load(self.path);b=self.binding
        if b.get('schema')!='business-calculation-view/2' or b.get('policy')!=POLICY:raise Rejected('第二阶段策略版本不符')
        self.background=service.background/'stage2';self.background.mkdir(exist_ok=True)
        self.pointer=self.background/'current.json'
        self.validate()
    def validate(self):
        b=self.binding
        if self.service.status()['head']!=b['base_head']:raise Rejected('上游身份/版本已变化，旧计算绑定失效')
        for p,h in {**b['sources'],**b['code']}.items():
            if digest(p)!=h:raise Rejected('计算来源或程序版本变化：'+p)
    def current(self):
        self.validate()
        if self.pointer.exists():
            state=load(self.pointer)
            if digest(state['file'])!=state['sha256']:raise Rejected('当前计算表被外部修改，请作为回传附件提交')
            return state
        return self.publish({},0)
    def publish(self,totals,revision,extra_errors=None):
        from a_confirm.locking import writer
        extra_errors=extra_errors or {}
        rows=[];errors=[]
        for fact in self.binding['rows']:
            r=calculate(fact,total=totals.get(str(fact['source_row']),fact['total_pieces']))
            if str(fact['source_row']) in extra_errors:
                r['errors']+=extra_errors[str(fact['source_row'])];r['values'][-2]='部分计算';r['values'][-1]='；'.join(r['errors'])
            errors += [{'row_id':fact['row_id'],'row':fact['source_row'],'reasons':r['errors']}] if r['errors'] else []
            rows.append({'row':fact['source_row'],'quantity':fact['quantity'],'price':fact['price'],'amount':fact['amount'],
                         'total_pieces':scalar(r['total_pieces']),'rounded_price':r['rounded_price'],
                         'values':[scalar(x) for x in r['values']],'errors':r['errors'],'exact':r['exact']})
        groups={}
        for fact,r in zip(self.binding['rows'],rows):
            i=fact['identity'];key=(i['code'],i['yd'],i['spec'])
            groups.setdefault(key,[]).append(r)
        for grouped in groups.values():
            if len(grouped)>1 and all(r['exact']['b'] is not None for r in grouped):
                boxes=sum(number(r['exact']['b']) for r in grouped)
                for r in grouped:r['values'][15]='本批同SKU合计'+str(boxes)+'盒；'+r['values'][15]
        identity=hashlib.sha256(json.dumps({'binding':digest(self.path),'revision':revision,'totals':totals,'extra_errors':extra_errors},sort_keys=True).encode()).hexdigest()
        folder=self.background/identity;folder.mkdir(exist_ok=True)
        plan={'rows':rows,'headers':HEADERS,'layout':self.binding.get('layout','detailed39'),'i_role':self.binding.get('i_role','price'),'draft_file':str(folder/'cells.xlsx'),
              'artifact_node_modules':str(Path(self.config['node']).parent.parent/'node_modules')}
        save(folder/'plan.json',plan)
        authored=subprocess.run([self.config['node'],str(Path(__file__).parents[1]/'stage2-author.mjs'),str(folder/'plan.json')],capture_output=True,text=True,encoding='utf-8')
        if authored.returncode:raise Rejected('计算表生成失败：'+authored.stderr[-2500:])
        compact=self.binding.get('layout')=='confirmation21'
        results_only=self.binding.get('layout')=='results26'
        factor_column=self.binding.get('i_role')=='factor'
        file=folder/(self.config['batch_label']+('_倍数计算确认表.xlsx'if factor_column else '_计算结果确认表.xlsx'if results_only else '_计算确认表.xlsx'if compact else '_第二阶段计算审核.xlsx'))
        attention=confirmation_attention(self.binding['rows'],rows)if compact or results_only else {}
        if results_only:
            for row in rows:
                n=str(row['row'])
                if attention.get('U'+n):
                    attention['V'+n]=attention['U'+n];attention['Y'+n]=attention['U'+n]
                if any('税率' in e for e in row['errors']):attention['Y'+n]='yellow';attention['Z'+n]='yellow'
        clear_references={'U'+str(f['source_row'])for f in self.binding['rows']if f.get('clear_inapplicable_pack_reference')}
        patch_workbook(self.binding['original_workbook'],plan['draft_file'],file,{r['row'] for r in rows},identity,compact=compact,attention=attention,results_only=results_only,factor_column=factor_column,clear_references=clear_references)
        counts=Counter(r['values'][-2]for r in rows)
        state={'schema':'stage2-calculation-state/2','policy':POLICY,'binding_sha256':digest(self.path),'base_head':self.binding['base_head'],
               'revision':revision,'view_hash':identity,'file':str(file),'sha256':digest(file),'totals':totals,
               'calculated_rows':counts['可计算'],'partial_rows':counts['部分计算'],'blocked_rows':counts['异常'],'rows':len(rows),
               'exceptions':errors,'professional_approval':False,'formal_output':False,'calculation_confirmed':False}
        with writer(self.service.root,self.service.engine.bid):
            self.validate()
            prior=load(self.pointer)['revision'] if self.pointer.exists() else -1
            if prior!=revision-1:raise Rejected('并发回传版本已变化，未覆盖当前计算表')
            save(self.pointer,state)
        save(folder/'calculation-evidence.json',{'state':state,'rows':rows,'attention':attention,'layout':self.binding.get('layout','detailed39')})
        return state
    def result(self,state,**extra):
        public=self.service._publish(state['file'],Path(state['file']).name)
        result={**state,'stage':'calculation','head':state['base_head'],'business_files':[public],
                'confirmation_required':False,'message':'第二阶段计算审核表；回传校验后保存，异常集中列示；完整业务门禁及正式外发仍独立。',**extra}
        if self.binding.get('layout')in {'confirmation21','results26'}:result['message']='请核对计算结果及颜色标记后回传；校验后保存。'
        save(self.service.background/'current-stage2-delivery.json',result)
        return result
    def preview(self,file):
        state=self.current()
        if view_token(file)!='"'+state['view_hash']+'"':raise Rejected('旧计算审核版本或绑定已失效')
        old=cells_file(state['file']);new=cells_file(file)
        if set(old)!=set(new):raise Rejected('工作表结构或非空单元格范围变化')
        changes=[];basic=[]
        for k,before in old.items():
            after=new[k]
            if before==after:continue
            sheet,cell=k
            if sheet==self.binding['sheet'] and re.fullmatch(r'K\d+',cell) and int(cell[1:])in {r['source_row']for r in self.binding['rows']}:
                if isinstance(after,str)and after.startswith('='):raise Rejected('总单个数不执行回传公式')
                changes.append({'cell':cell,'row':int(cell[1:]),'before':before,'after':after});continue
            if sheet==self.binding['sheet'] and re.fullmatch(r'(F|G|H|O|P|Q|R)\d+',cell):basic.append(cell);continue
            raise Rejected('受保护源数据或计算公式变化：'+sheet+'!'+cell)
        if basic:return {'status':'requires_basics_sync_before_calculation','basis_changes':basic,'changes':changes,'business_saved':False}
        return {'status':'ready','view_hash':state['view_hash'],'revision':state['revision'],'changes':changes,'modified_cells':len(changes),'business_saved':False}
    def operate(self,request):
        action=request['action']
        if action in {'current','start'}:return self.result(self.current())
        if action=='native-preview':return self.preview(request['file'])
        if action!='upload':raise Rejected('第二阶段视图不支持该动作')
        if not str(request.get('reference') or '').strip():raise Rejected('回传必须有本次业务出处')
        file=Path(request['file']).resolve(strict=True);sha=digest(file);state=self.current()
        latest=self.background/'last-submission.json'
        if latest.exists():
            old=load(latest)
            if old['input_sha256']==sha and old['after_view']==state['view_hash']:return self.result(state,saved=True,receipt_replayed=True)
        p=self.preview(file)
        if p['status']!='ready':return p
        if request.get('expected_view_hash',state['view_hash'])!=state['view_hash']:raise Rejected('旧计算审核版本已失效')
        # A retained earlier issued file must not silently replace a newer revision.
        for oldfile in self.background.glob('*/'+state['file'].split('\\')[-1].split('/')[-1]):
            if str(oldfile)!=state['file'] and digest(oldfile)==sha:raise Rejected('旧版计算审核表回传已失效')
        totals=dict(state['totals']);invalid={};accepted=0
        for c in p['changes']:
            x=number(c['after'])
            if x is None or x<=0 or x.denominator!=1:invalid[str(c['row'])]=['回传总单个数无效，原合格值保留']
            else:totals[str(c['row'])]=int(x);accepted+=1
        retained=self.background/'submissions'/sha;retained.mkdir(parents=True,exist_ok=True)
        raw=retained/'operator.xlsx'
        if not raw.exists():raw.write_bytes(file.read_bytes())
        nextstate=self.publish(totals,state['revision']+1,invalid)
        receipt={'input_sha256':sha,'before_view':state['view_hash'],'after_view':nextstate['view_hash'],'reference':request['reference'],
                 'accepted_changes':accepted,'invalid_changes':invalid,'changes':p['changes'],'formal_output':False}
        save(retained/'receipt.json',receipt);save(latest,receipt)
        return self.result(nextstate,saved=True,accepted_changes=accepted,receipt_replayed=False)
