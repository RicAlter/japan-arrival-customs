"""Presentation-only colors and approved sparse values using original OOXML APIs."""
import re,xml.etree.ElementTree as ET
from . import load,save,key,digest,Rejected
from native_copy.ooxml import parts,sheet_member,CELL,ROW,PREFIX,attr,patch_cell,build,verify,NS,Q
from stage1.workbook import packed
SHEET='invoice (計算)'

def main_copy(service,background):
    batch=service.store.load(service.bid);baseline=service.basics._state(service.bid)[1];view=service.basics.read_current(service.bid)
    registration=load(service.root/'objects'/(baseline['registration_ref']+'.json'));manual_category=registration.get('stage1_policy',{}).get('manual_category_input_only',False)
    data=__import__('pathlib').Path(service.root/'objects'/(baseline['copy_sha256']+'.xlsx')).read_bytes()
    p=parts(data);member=sheet_member(p,SHEET);raw=p[member];prefix=re.search(rb'<([A-Za-z_][\w.-]*:)?worksheet\b',raw)[1] or b''
    overrides=batch['a03']['overrides'];approved={}
    for target,rec in overrides.items():
        f=baseline['fields'][target]
        if rec['value']==f['value']:continue
        if f['field'] not in {'internal_name','specification','purchase_unit_price','category','material_reference','channel','yd'}:raise Rejected('展示层不改只读字段')
        approved[f['cell']]=rec['value']
    seen=set()
    def patch(m):
        address=attr(m[0],'r')
        if address not in approved:return m[0]
        seen.add(address);v=approved[address]
        if v['type']=='blank':
            e=ET.fromstring(m[0]);e.attrib.pop('t',None)
            for child in list(e):e.remove(child)
            return ET.tostring(e,encoding='utf-8')
        return patch_cell(m[0],{'cell':address,'style_id':int(attr(m[0],'s') or '0'),'write_value':v['value'],'value_type':v['type']},prefix)
    # Registered editable cells already exist in this verified layout.
    raw=CELL.sub(patch,raw);p[member]=raw;current=packed(data,p)
    missing=[{'cell':address,'color':'yellow','write_value':v['value'],'value_type':v['type']} for address,v in approved.items() if address not in seen and v['type']!='blank']
    if missing:
        current,added=build(current,SHEET,missing);verify(packed(data,p),current,SHEET,added)
    plans=[];counts={'red_missing_basic':0,'yellow_reference_or_pending':0}
    for f in view['fields'].values():
        if f['field'] not in {'internal_name','specification','purchase_unit_price','category','material_reference','channel','yd'}:continue
        if manual_category and f['field']=='category':continue
        value=f['value']['value'];blank=value in (None,'');color=None
        if blank and f['field'] in {'internal_name','category'}:color='red';counts['red_missing_basic']+=1
        elif (not blank and not f['confirmed']) or (blank and f['field'] in {'specification','purchase_unit_price','channel'}):color='yellow';counts['yellow_reference_or_pending']+=1
        if color:plans.append({'cell':f['cell'],'color':color,'write_value':None,'value_type':'text'})
    result,changes=build(current,SHEET,plans);verify(current,result,SHEET,changes)
    # Full value/formula/cache/type equality outside explicitly saved overrides;
    # existing native verifier also preserves styles/protection except the fill.
    before=parts(data);after=parts(result)
    assert all(before[k]==after[k] for k in before if k not in {member,'xl/styles.xml'})
    a={c.get('r'):c for c in ET.fromstring(before[member]).iter(Q+'c')};b={c.get('r'):c for c in ET.fromstring(after[member]).iter(Q+'c')}
    for address in set(a)|set(b):
        if address in approved:continue
        old,new=a.get(address),b.get(address)
        def value_signature(c):
            if c is None:return None
            return (c.get('t'),tuple(ET.tostring(child) for child in c))
        if value_signature(old)!=value_signature(new) and not (old is None and new is not None and not list(new)):raise Rejected('展示层改变业务值/公式/cache')
    versions=background/'business-versions';versions.mkdir(parents=True,exist_ok=True);file=versions/(key(batch)+'.xlsx')
    if file.exists() and file.read_bytes()!=result:raise Rejected('同一状态展示版本不一致')
    if not file.exists():file.write_bytes(result)
    save(background/'main-display-verification.json',{'head':key(batch),'sha256':digest(file),'all_noneditable_values_formulas_cache_preserved':True,'weights_other_parts_identical':True,'new_rows_or_columns':False,'counts':counts,'original_hidden_rows_and_filter_preserved':True})
    return file,counts
