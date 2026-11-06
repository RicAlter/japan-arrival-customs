"""Reissue only an untouched candidate: category M is exclusively human input."""
from pathlib import Path
from copy import deepcopy
import re,xml.etree.ElementTree as ET,shutil
from . import rt,load,save,key,digest,Rejected
from native_copy.ooxml import parts,sheet_member,Styles,CELL,ROW,PREFIX,attr,set_attr,Q,NS
from stage1.workbook import packed
SHEET='invoice (計算)'

def check_untouched(engine,public_file,expected_sha):
    b=engine.store.load(engine.bid);v=engine.basics.read_current(engine.bid)
    if v['confirmed_field_count'] or b['a03']['overrides'] or b['a03']['receipts'] or b['loop']['active_update']:
        raise Rejected('已有人工保存/确认或实际更新，不能重新初始化；须先保留并迁移人工结果')
    if digest(public_file)!=expected_sha:raise Rejected('当前可编辑表已有变化，不能把可能的人工作业清空')
    return b,v

def clear_assistant_column(data,cells):
    p=parts(data);member=sheet_member(p,SHEET);raw=p[member];styles=Styles(p['xl/styles.xml']);cache={};seen=set()
    root=ET.fromstring(raw);columns=root.findall('s:cols/s:col',NS);column_style=next((int(c.get('style','0')) for c in columns if int(c.get('min'))<=13<=int(c.get('max'))),0)
    prefix=re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b',raw)[1] or b''
    def manual_style(base):
        if base in cache:return cache[base]
        f=set_attr(set_attr(styles.fragments[base],'fillId','0'),'applyFill','0')
        f=set_attr(f,'applyProtection','1');protection=b'<'+styles.p+b'protection locked="0" hidden="0"/>'
        found=re.search(rb'<'+PREFIX+rb'protection\b[^>]*?/>',f)
        if found:f=f[:found.start()]+protection+f[found.end():]
        elif f.endswith(b'/>'):f=f[:-2]+b'>'+protection+b'</'+styles.p+b'xf>'
        else:
            at=re.search(rb'</'+PREFIX+rb'xf>$',f).start();f=f[:at]+protection+f[at:]
        index=len(styles.xfs)+len(styles.extra_xfs);styles.extra_xfs.append(f);cache[base]=index;return index
    def blank(address,base):return b'<'+prefix+b'c r="'+address.encode()+b'" s="'+str(manual_style(base)).encode()+b'"/>'
    def cell(m):
        address=attr(m[0],'r')
        if address not in cells:return m[0]
        if re.search(rb'<'+PREFIX+rb'f\b',m[0]):raise Rejected('M含公式，不能作为助手预填清空')
        seen.add(address);return blank(address,int(attr(m[0],'s') or str(column_style)))
    updated=CELL.sub(cell,raw)
    def row(m):
        n=attr(m[0],'r');address='M'+n
        if address not in cells or address in seen:return m[0]
        fragment=m[0];following=next((c.start() for c in CELL.finditer(fragment) if (lambda s:len(s)>1 or s>'M')(attr(c[0],'r').rstrip('0123456789'))),None)
        at=following if following is not None else re.search(rb'</'+PREFIX+rb'row>$',fragment).start()
        seen.add(address);return fragment[:at]+blank(address,column_style)+fragment[at:]
    updated=ROW.sub(row,updated)
    if seen!=set(cells):raise Rejected('M原行无法完整定位')
    p[member]=updated;p['xl/styles.xml']=styles.export();result=packed(data,p)
    before={attr(c[0],'r'):c[0] for c in CELL.finditer(raw)};after={attr(c[0],'r'):c[0] for c in CELL.finditer(updated)}
    if any(before[a]!=after[a] for a in before if a not in cells):raise Rejected('清空M影响了其他格')
    original=parts(data);result_parts=parts(result)
    if any(original[k]!=result_parts[k] for k in p if k not in {member,'xl/styles.xml'}):raise Rejected('清空M影响其他部件')
    return result

def reissue(engine,public_file,expected_sha,output):
    from native_copy.service import registered_copy
    from native_copy.support import snapshot_root
    from arrival_core.storage import Store
    from separated.service import Service
    b,v=check_untouched(engine,public_file,expected_sha);oldm=load(engine.owner['workflow']);parent=Path(engine.owner['workflow']).parent
    old=registered_copy(parent/'native-copy');reg=deepcopy(old);reg.pop('file');previous_export=reg.pop('export_id')
    output=Path(output).resolve()
    if output.exists():raise Rejected('人工品类新底稿目录必须为空')
    fields=[f for f in reg['fields'] if f['field']=='category'];addresses={f['cell'] for f in fields}
    # Only the specifically audited assistant copy is eligible for this reissue.
    # Any independent M content requires preserving/migrating it, never clearing it.
    from openpyxl import load_workbook
    workbook=load_workbook(public_file,read_only=True);sheet=workbook[SHEET]
    try:
        observed={'M'+str(n):(row[0].value,row[4].value) for n,row in enumerate(sheet.iter_rows(min_row=2,max_row=1313,min_col=13,max_col=17),2) if 'M'+str(n) in addresses}
        if len(observed)!=len(addresses) or any(m not in (None,'') and m!=q for m,q in observed.values()):raise Rejected('M含与Q不同的独立内容，须保留并核对，不能清空')
    finally:workbook.close()
    data=clear_assistant_column(Path(oldm['issued_file']).read_bytes(),addresses)
    from .pack_reference import source_rows
    from native_copy.ooxml import build,patch_cell,verify
    raw_sources=source_rows(oldm);source_addresses={'S'+c[1:] for c in addresses}
    p=parts(data);member=sheet_member(p,SHEET);prefix=re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b',p[member])[1] or b''
    def clear_old_pack(m):
        address=attr(m[0],'r')
        if address not in source_addresses and address!='S1':return m[0]
        return b'<'+prefix+b'c r="'+address.encode()+b'" s="'+(attr(m[0],'s') or '0').encode()+b'"/>'
    p[member]=CELL.sub(clear_old_pack,p[member]);data=packed(data,p)
    plans=[{'cell':'S1','color':'yellow','write_value':'盒规原文参考（人工判断）','value_type':'text'}]
    plans += [{'cell':'S'+n,'color':'yellow','write_value':r['display_text'],'value_type':'text'} for n,r in raw_sources.items() if r['display_text'] and 'S'+n in source_addresses]
    olddata=data;data,changes=build(data,SHEET,plans);verify(olddata,data,SHEET,changes);p=parts(data)
    def widen_s(m):
        if attr(m[0],'min')=='19' and attr(m[0],'max')=='19':return set_attr(set_attr(m[0],'width','82'),'customWidth','1')
        return m[0]
    p[member]=re.sub(rb'<'+PREFIX+rb'col\b[^>]*?/>',widen_s,p[member]);data=packed(data,p)
    save(output/'technical/packaging-original-text.json',raw_sources)
    token=key({'parent_export':previous_export,'old_live_hash':key(b),'change':'M manual input only; S original text; no packaging inference','copy':__import__('hashlib').sha256(data).hexdigest()})
    props=ET.fromstring(p['docProps/custom.xml']);hit=[e for e in props if e.get('name')=='CustomsAStageExportVersion']
    if len(hit)!=1 or len(hit[0])!=1:raise Rejected('版本属性不唯一')
    previous=list(hit[0])[0].text;p['docProps/custom.xml']=p['docProps/custom.xml'].replace(previous.encode(),token.encode());data=packed(data,p)
    native=output/'native-copy';nt=native/'technical';nt.mkdir(parents=True);(native/'delivery').mkdir();issued=native/'delivery/issued-baseline.xlsx';issued.write_bytes(data)
    removed={f['cell']:deepcopy(f) for f in fields}
    for f in fields:
        f.update(working_value=None,status='missing',confirmed=False,sources=[{'kind':'manual_input_only','source_ref':'用户2026-11-06：M品类不自动填写，Q只保留AI参考','old_assistant_value_retained_in_parent_export':previous_export}])
        f['stage1_source_metadata']={**f.get('stage1_source_metadata',{}),'manual_input_only':True,'auto_fill_allowed':False}
    refs=load(parent/'native-copy/technical/reference-candidates.json');refs['manual_category_policy']={'column':'M','reference_column':'Q','auto_fill':False,'previous_export':previous_export}
    save(nt/'reference-candidates.json',refs);save(output/'technical/removed-assistant-category.json',removed)
    reg['stage1_policy'].update(manual_category_input_only=True,manual_packaging_original_text_only=True,packaging_reference_column='S',automatic_packaging_calculation=False)
    reg.update(copy_sha256=digest(issued),reference_snapshot_hash=key(refs),stage1_version={'property':'CustomsAStageExportVersion','value':token},version_marker={'property':'CustomsAStageExportVersion','value':token},
        a_version=key({'parent':reg['a_version'],'token':token}),layout_parent_export=previous_export,copy_changes=[c for c in reg['copy_changes'] if c.get('field')!='category'])
    reg['export_id']=key(reg);save(nt/'export-registration.json',reg)
    Store(snapshot_root(nt/'batch-store')).save(Store(snapshot_root(parent/'native-copy/technical/batch-store')).load(reg['batch_id']))
    save(native/'result.json',{'schema':'a01-native-copy-result/1','status':'prepared_reference_copy','export_id':reg['export_id'],'a_version':reg['a_version'],'confirmed':False,'formal_output':False})
    context=output/'technical/trusted-context.json';save(context,{'schema':'a02-trusted-context/1','current_output':str(native),'business_batch_id':reg['business_batch_id'],'export_id':reg['export_id'],'a_version':reg['a_version'],'known_outputs':[str(native)]})
    svc=Service(output/'state');svc.register(context);shutil.copyfile(parent/'technical/authoring-plan.json',output/'technical/authoring-plan.json')
    m={**oldm,'business_file':str(output/'KMT20261101_基础资料.xlsx'),'issued_file':str(issued),'issued_sha256':digest(issued),'a03_root':str(svc.root),'export_id':reg['export_id'],
        'current_hash':svc.read_current(reg['batch_id'])['current_hash'],'prior_workflow':engine.owner['workflow'],'manual_category_input_only':True,'manual_packaging_original_text_only':True,'parent_live_history':{'root':str(engine.root),'hash':key(b),'confirmed':v['confirmed_field_count']}}
    shutil.copyfile(issued,m['business_file']);save(output/'workflow-manifest.json',m);return m
