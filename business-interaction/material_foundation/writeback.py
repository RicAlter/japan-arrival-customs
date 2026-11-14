"""Minimal OOXML text edits, backup and disk reread; never round-trip a workbook."""
from pathlib import Path
from copy import deepcopy
import shutil,zipfile,io,hashlib,re,os
from xml.etree import ElementTree as ET
from rebuild_mvp.xlsxio import read_book,sheet_info,col_number
from rebuild_mvp.service import save_json
Q='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def apply(job,root,req):
    source=Path(req.get('input_file') or (job.get('business_files') or [job['source']])[0]).resolve(strict=True)
    lock=source.with_name('~$'+source.name)
    if lock.exists():raise ValueError('TASK_CONFLICT: 表格正在编辑，未写回')
    data=source.read_bytes();digest=hashlib.sha256(data).hexdigest();book=read_book(source);sheet=next(s for s in book['sheets'] if s['name']==job['sheet']);rows={r['row']:r for r in sheet['rows']};changes={};skipped=[]
    all_terminal=all(i['status'] in ('found','not_found') for i in job['codes'].values())
    for item in job['codes'].values():
        if item['status']=='found':result=item['result'];values={'material':result['translation']['zh'],'url':result['url'],'site':result['site']}
        elif item['status']=='not_found' and req.get('finalize_not_found') and all_terminal:values={'material':'未找到'}
        else:continue
        for n in item['rows']:
            row=rows.get(n,{})
            if str(row.get('values',{}).get(job['columns']['code'],''))!=item['jan']:
                skipped.append({'row':n,'reason':'编码变化，未写'});continue
            target=job['columns']['material'];existing=row['values'].get(target)
            if existing not in ('',None,values['material']):
                skipped.append({'row':n,'reason':'材质已有值，保留'});continue
            for field,value in values.items():
                col=job['columns'].get(field)
                if not col or not value or row['values'].get(col) not in ('',None) or col in row.get('formulas',{}):continue
                changes[col+str(n)]=value
    destination=Path(req.get('destination') or root/'材质查询_阶段结果.xlsx').resolve()
    if destination==source and not req.get('in_place'):raise ValueError('INPUT_INVALID: 覆盖原件需明确in_place')
    if destination.exists() and destination!=source:raise ValueError('TASK_CONFLICT: 输出已存在，不覆盖')
    backup=root/'backups'/f'{digest}.xlsx';backup.parent.mkdir(exist_ok=True)
    if not backup.exists():backup.write_bytes(data)
    member=next(s['path'] for s in sheet_info(source) if s['name']==job['sheet'])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        tree=ET.fromstring(z.read(member));sd=tree.find(Q+'sheetData');rowmap={int(r.get('r')):r for r in sd}
        for address,value in changes.items():
            n=int(re.search(r'\d+',address)[0]);r=rowmap[n];cell=next((c for c in r if c.get('r')==address),None)
            if cell is None:cell=ET.SubElement(r,Q+'c',{'r':address})
            for c in list(cell):cell.remove(c)
            cell.set('t','inlineStr');text=ET.SubElement(ET.SubElement(cell,Q+'is'),Q+'t');text.text=value;text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            r[:]=sorted(r,key=lambda c:col_number(re.match('[A-Z]+',c.get('r'))[0]))
        changed=ET.tostring(tree,encoding='utf-8',xml_declaration=True);temporary=destination.with_name(destination.name+'.tmp')
        destination.parent.mkdir(parents=True,exist_ok=True)
        if temporary.exists():raise ValueError('TASK_CONFLICT: 临时输出已存在')
        with zipfile.ZipFile(temporary,'x') as out:
            for info in z.infolist():out.writestr(info,changed if info.filename==member else z.read(info.filename))
    after=read_book(temporary);a={r['row']:r for r in next(s for s in after['sheets'] if s['name']==job['sheet'])['rows']}
    for n,row in rows.items():
        for col in set(row['values'])|set(a[n]['values']):
            address=col+str(n)
            if address in changes:assert a[n]['values'].get(col)==changes[address]
            else:assert a[n]['values'].get(col)==row['values'].get(col)
        assert row['formulas']==a[n]['formulas']
    with zipfile.ZipFile(backup) as before,zipfile.ZipFile(temporary) as out:
        assert before.namelist()==out.namelist()
        assert all(before.read(name)==out.read(name) for name in before.namelist() if name!=member)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise ValueError('SOURCE_CHANGED: 写回期间文件变化，保留备份及待检查输出')
    if destination==source:os.replace(temporary,destination)
    else:temporary.rename(destination)
    report={'status':'written','business_files':[str(destination)],'filled_cells':len(changes),'backup':str(backup),'skipped':skipped,'non_target_differences':0,'unmapped_provenance_fields':[f for f in ('url','site') if f not in job['columns']],'scope':'仅网站材质参考，不批准O正式材质'}
    save_json(root/'last-writeback.json',report);return report
