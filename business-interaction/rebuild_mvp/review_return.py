"""Operator returns with revision checks, partial acceptance and immutable originals."""
from pathlib import Path
import json,re,sqlite3,zipfile,copy,os,uuid
from decimal import Decimal,InvalidOperation
from .service import writer,save_json,digest,code_version,MvpError
from .xlsxio import read_book,sheet_info,col_number
from xml.etree import ElementTree as ET
Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
EDITABLE=set('EFGHNOPQRSTUVWX')

def overlay(source,destination,sheet,changes):
    member=next(s['path'] for s in sheet_info(source) if s['name']==sheet)
    before=read_book(source);temp=destination.with_suffix('.'+uuid.uuid4().hex+'.tmp');published=False
    try:
        with zipfile.ZipFile(source) as old:
            tree=ET.fromstring(old.read(member));rows={int(r.get('r')):r for r in tree.find(Q+'sheetData')}
            for address,value in changes.items():
                row=rows[int(re.search(r'\d+',address)[0])];cell=next((c for c in row if c.get('r')==address),None)
                if cell is None:cell=ET.SubElement(row,Q+'c',{'r':address})
                for c in list(cell):cell.remove(c)
                cell.set('t','inlineStr');text=ET.SubElement(ET.SubElement(cell,Q+'is'),Q+'t');text.text=value;text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
                row[:]=sorted(row,key=lambda c:col_number(re.match('[A-Z]+',c.get('r'))[0]))
            with zipfile.ZipFile(temp,'x',allowZip64=True) as out:
                for info in old.infolist():
                    if info.filename==member:out.writestr(info,ET.tostring(tree,encoding='utf-8',xml_declaration=True));continue
                    with old.open(info) as f,out.open(info,'w') as g:
                        while chunk:=f.read(1024*1024):g.write(chunk)
            after=read_book(temp)
            for a,b in zip(before['sheets'],after['sheets']):
                assert a['name']==b['name'] and a['merges']==b['merges'] and len(a['rows'])==len(b['rows'])
                for r,s in zip(a['rows'],b['rows']):
                    r=copy.deepcopy(r);s=copy.deepcopy(s)
                    for col in list(set(r['values'])|set(s['values'])):
                        address=col+str(r['row'])
                        if a['name']==sheet and address in changes:
                            assert s['values'].get(col,'')==changes[address]
                            for item in (r,s):item['values'].pop(col,None);item['types'].pop(col,None)
                    assert r==s,('NON_TARGET_CHANGED',a['name'],r['row'])
            with zipfile.ZipFile(temp) as check:
                assert old.namelist()==check.namelist()
                for name in old.namelist():
                    if name!=member:assert old.getinfo(name).CRC==check.getinfo(name).CRC
            temp.rename(destination);published=True
    finally:
        if not published and temp.exists():temp.unlink()

def handle(req):
    root=Path(req.get('output') or req.get('task_root','')).resolve()
    if not req.get('output') and not req.get('task_root'):raise MvpError('INPUT_INVALID','缺少任务目录')
    root.mkdir(parents=True,exist_ok=True)
    with writer(root):
        jf=root/'job.json'
        if not jf.exists():
            if req['action']!='prepare':raise MvpError('INPUT_INVALID','回传任务未建立')
            if any(p.name!='.writer.lock' for p in root.iterdir()):raise MvpError('TASK_CONFLICT','任务目录非空')
            source=Path(req['input_file']).resolve(strict=True);book=read_book(source)
            if source.with_name('~$'+source.name).exists():raise MvpError('TASK_CONFLICT','输入正在编辑')
            if len(book['sheets'])!=2:raise MvpError('INPUT_INVALID','要求固定两张表')
            sheet=book['sheets'][0]
            header=sheet['rows'][0]['values']
            if header.get('E')!='商品图片' or header.get('R')!='网站查找材质' or set(header)!={chr(65+i) for i in range(24)}:raise MvpError('INPUT_INVALID','要求固定24列核对表')
            job={'mode':'review_return','batch_id':req['batch_id'],'source':str(source),'code':code_version(),'sheet':sheet['name'],'initial_sha256':digest(source)}
            save_json(jf,job)
        job=json.loads(jf.read_text(encoding='utf8'))
        if job['mode']!='review_return' or job['code']!=code_version():raise MvpError('SOURCE_CHANGED','回传任务程序绑定变化')
        db=sqlite3.connect(root/'candidate.sqlite3')
        try:
            db.executescript('CREATE TABLE IF NOT EXISTS review_state(id INTEGER PRIMARY KEY,revision INTEGER,path TEXT,sha TEXT); CREATE TABLE IF NOT EXISTS review_submissions(sha TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS manual_decisions(revision INTEGER,address TEXT,value TEXT,evidence TEXT,PRIMARY KEY(revision,address));')
            with db:db.execute('INSERT OR IGNORE INTO review_state VALUES(1,0,?,?)',(job['source'],job['initial_sha256']))
            revision,path,sha=db.execute('SELECT revision,path,sha FROM review_state WHERE id=1').fetchone()
            if not Path(path).is_file() or digest(path)!=sha:raise MvpError('SOURCE_CHANGED','当前核对文件发生外部修改，保留原件并核对')
            if req['action']=='prepare':
                if str(Path(req['input_file']).resolve())!=job['source'] or req['batch_id']!=job['batch_id']:raise MvpError('TASK_CONFLICT','回传任务已绑定其他输入')
            result={'schema':'arrival-review-return/1','status':'ready','revision':revision,'reference_sha256':sha,'business_files':[path],'operator_submission_accepted':False,'professional_approved':False}
            result['reviewed_source']={'path':path,'sha256':sha,'role':'reviewed_basics','version':'operator-return-'+str(revision),'purpose':'inherit operator-saved fields within original shipment identity'}
            if req['action'] in ('current','prepare'):return result
            if req['action']!='resume':raise MvpError('INPUT_INVALID','回传仅支持prepare/current/resume')
            submitted=Path(req['submitted_file']).resolve(strict=True);subsha=digest(submitted)
            receipt=db.execute('SELECT payload FROM review_submissions WHERE sha=?',(subsha,)).fetchone()
            if receipt:return {**json.loads(receipt[0]),'idempotent':True,'current_revision':revision}
            if req.get('expected_revision')!=revision or req.get('expected_reference_sha256')!=sha:raise MvpError('TASK_CONFLICT','旧版回传，需以当前版本重新核对')
            if submitted.with_name('~$'+submitted.name).exists():raise MvpError('TASK_CONFLICT','回传表正在编辑')
            original=read_book(path);returned=read_book(submitted)
            if len(original['sheets'])!=len(returned['sheets']):raise MvpError('TASK_CONFLICT','工作表数量变化')
            changes={};issues=[];clear=req.get('clear_cells',[])
            if not isinstance(clear,list) or any(not isinstance(x,str) or not re.fullmatch('[EFGHNOPQRSTUVWX][0-9]+',x) for x in clear):raise MvpError('INPUT_INVALID','清空地址必须为可编辑业务格列表')
            for a,b in zip(original['sheets'],returned['sheets']):
                if a['name']!=b['name'] or a['merges']!=b['merges'] or [r['row'] for r in a['rows']]!=[r['row'] for r in b['rows']]:raise MvpError('TASK_CONFLICT','表结构或行序变化')
                for r,s in zip(a['rows'],b['rows']):
                    if r['formulas']!=s['formulas']:raise MvpError('TASK_CONFLICT','公式变化，拒绝覆盖')
                    for col in set(r['values'])|set(s['values']):
                        old=r['values'].get(col,'');new=s['values'].get(col,'');address=col+str(r['row'])
                        if new==old:continue
                        if a['name']!=job['sheet'] or r['row']==1 or col not in EDITABLE or col in r['formulas']:raise MvpError('TASK_CONFLICT','原始字段或箱重变化：'+address)
                        if not r['values'].get('C'):raise MvpError('TASK_CONFLICT','辅助行不是商品行：'+address)
                        if not new and address not in clear:issues.append({'cell':address,'reason':'空格未明确清空，保留当前值'});continue
                        if col in 'UVX' and new:
                            try:
                                n=Decimal(str(new));assert n.is_finite() and n>0
                            except (InvalidOperation,AssertionError):issues.append({'cell':address,'reason':'数量或盒规须为正数'});continue
                        if col=='E' and new and not str(new).startswith(('http://','https://')):issues.append({'cell':address,'reason':'图片格只接收HTTP链接'});continue
                        if col=='W' and new and new not in ('是','否','盲盒','盲抽','非盲盒','非盲抽'):issues.append({'cell':address,'reason':'盲抽标记不明确'});continue
                        changes[address]=str(new)
            if digest(submitted)!=subsha or digest(path)!=sha:raise MvpError('SOURCE_CHANGED','核对期间文件变化')
            destination=root/f'运营回传_{revision+1:03d}.xlsx'
            if destination.exists():
                # Interrupted publication: only reuse the exact expected overlay.
                temp=root/f'recovery-{uuid.uuid4().hex}.xlsx';overlay(path,temp,job['sheet'],changes)
                try:
                    if read_book(temp)['sheets']!=read_book(destination)['sheets']:raise MvpError('TASK_CONFLICT','既有输出内容不同')
                    with zipfile.ZipFile(temp) as a,zipfile.ZipFile(destination) as b:
                        if a.namelist()!=b.namelist() or any(a.read(n)!=b.read(n) for n in a.namelist()):raise MvpError('TASK_CONFLICT','既有输出部件变化')
                finally:temp.unlink()
            else:overlay(path,destination,job['sheet'],changes)
            if digest(path)!=sha or digest(submitted)!=subsha:raise MvpError('SOURCE_CHANGED','发布前来源已变化，保留待核输出')
            outsha=digest(destination)
            result.update(status='partial' if issues else 'saved',revision=revision+1,reference_sha256=outsha,business_files=[str(destination)],accepted_cells=len(changes),issues=issues,operator_submission_accepted=True)
            result['reviewed_source'].update(path=str(destination),sha256=outsha,version='operator-return-'+str(revision+1))
            with db:
                for address,value in changes.items():db.execute('INSERT INTO manual_decisions VALUES(?,?,?,?)',(revision+1,address,value,json.dumps({'submitted_file':str(submitted),'sha256':subsha,'source_cell':address,'scope':'operator_return_not_professional_approval'},ensure_ascii=False)))
                db.execute('UPDATE review_state SET revision=?,path=?,sha=? WHERE id=1',(revision+1,str(destination),outsha))
                db.execute('INSERT INTO review_submissions VALUES(?,?)',(subsha,json.dumps(result,ensure_ascii=False)))
            return result
        finally:db.close()
