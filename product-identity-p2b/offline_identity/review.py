"""Compact operator fields; caller confirmation and source checks are separate."""
from pathlib import Path
import json
import zipfile

from openpyxl import load_workbook

from .common import IDENTITY,BASIC,FIELDS,Rejected,key,digest,canonical,comparable
from .maintenance import load_plan
from .analyze import specification_usable

HEADERS=['编号','商品编码','现有日文名','待补字段','候选及来源','来源编号','补充日文名','补充版本','补充规格','补充材质参考','确认依据','确认基础关联']
SOURCE_HEADERS=['来源编号','商品编码','日文名','版本','规格原文','中文名','材质参考','YD原值','原文件','工作表','原行','字段定位','资料范围','品牌','品类','渠道']
LABELS={'code_raw':'编码','code_type':'编码类型','japanese_name':'日文名','version':'版本','specification':'规格','internal_name':'中文名',
        'customs_name':'申报品名候选','brand':'品牌','category':'品类','channel':'渠道','yd':'YD','material_reference':'材质参考','candidate_selection':'候选选择'}
EDIT_COLUMNS={'F','G','H','I','J','K','L'}


def source_catalog(plan):
    return {f'S{index:05d}':f for index,f in enumerate(plan['facts'],1)}


def display_source(fact):
    source=fact['source'];v=fact['values'];file_name=source.get('file_name') or Path(source['path']).name
    refs=[]
    for field,e in sorted(fact['evidence'].items()):
        if e.get('cell'):refs.append(f'{LABELS.get(field,field)}:{e["cell"]}')
        elif e.get('original_b4_field'):refs.append(f'{LABELS.get(field,field)}:原B4字段证据')
    return [v.get('code_raw'),v.get('japanese_name'),v.get('version'),v.get('specification') or v.get('packaging_label'),
            v.get('internal_name'),v.get('material_original') or v.get('material_translation'),v.get('yd'),file_name,
            source['sheet'],source['row'],'；'.join(refs),source['batch_id'],v.get('brand'),v.get('category'),v.get('channel')]


def model(plan):
    catalog=source_catalog(plan);by_fact={f['fact_id']:sid for sid,f in catalog.items()};rows=[]
    for case in plan['cases']:
        sources=[by_fact[f] for f in case['candidate_fact_ids']]
        rows.append([case['case_id'],case['query']['code_raw'],case['query']['japanese_name'],
                     '、'.join(LABELS.get(f,f) for f in case['unresolved_fields']),
                     f'原候选{len(case["original_candidates"])}；来源{len(sources)}；关联{len(case["row_ids"])}行',
                     None,None,None,None,None,None,None])
    return {'schema':'offline-identity-review-book/1','plan_id':plan['plan_id'],
            'headers':HEADERS,'source_headers':SOURCE_HEADERS,'rows':rows,
            'source_rows':[[sid]+display_source(fact) for sid,fact in catalog.items()],
            'case_fields':{c['case_id']:c['unresolved_fields'] for c in plan['cases']}}


def _read(file):
    with zipfile.ZipFile(file) as archive:
        if any('vbaproject' in n.lower() or 'externallinks/' in n.lower() for n in archive.namelist()):raise Rejected('回传包含宏或外链')
    book=load_workbook(file,read_only=True,data_only=False,keep_links=False)
    try:
        if book.sheetnames!=['人工补充','候选与来源']:raise Rejected('回传工作表结构不匹配')
        result={}
        for sheet in book.worksheets:
            if sheet.sheet_state!='visible':raise Rejected('不接受隐藏工作表')
            result[sheet.title]=[(ri,[c.value for c in row],[c.data_type for c in row])
                                 for ri,row in enumerate(sheet.iter_rows(min_row=5),5)]
        return result
    finally:book.close()


def preview(database,plan_id,workbook):
    workbook=Path(workbook).resolve(strict=True);before=digest(workbook)
    plan=load_plan(database,plan_id);expected=model(plan);tables=_read(workbook)
    originals={r[0]:r for r in expected['rows']};cases={c['case_id']:c for c in plan['cases']};catalog=source_catalog(plan)
    expected_sources={r[0]:r for r in expected['source_rows']}
    def data_rows(name,headers):
        content=tables[name]
        if content[0][1][:len(headers)]!=headers or any(v is not None for v in content[0][1][len(headers):]):raise Rejected('回传表头被改动')
        data={}
        for ri,values,types in content[1:]:
            if not any(v is not None for v in values):continue
            if any(t in ('f','e') for t in types):raise Rejected('回传填写/来源区域不能含公式或错误')
            if any(v is not None for v in values[len(headers):]):raise Rejected('回传含未知额外字段')
            values=(values+[None]*len(headers))[:len(headers)]
            if values[0] in data:raise Rejected('回传编号重复')
            data[values[0]]=(ri,values)
        return data
    rows=data_rows('人工补充',HEADERS);sources=data_rows('候选与来源',SOURCE_HEADERS)
    if set(rows)!=set(originals) or set(sources)!=set(expected_sources):raise Rejected('回传商品或来源范围被增删')
    for sid,(_,values) in sources.items():
        if values!=expected_sources[sid]:raise Rejected('原始候选或来源值被改动')
    edits=[];unconfirmed=[]
    for cid,case in cases.items():
        ri,values=rows[cid]
        if values[:5]!=originals[cid][:5]:raise Rejected('原始编码/日文名/待补范围被改动')
        sidtext,new_ja,new_version,new_spec,new_material,basis,confirmed=values[5:12]
        if confirmed not in (None,'','确认'):raise Rejected('确认基础关联只接受“确认”或留空')
        if confirmed!='确认':
            if any(v not in (None,'') for v in values[5:11]):unconfirmed.append(cid)
            continue
        if not isinstance(basis,str) or not basis.strip():raise Rejected('确认行必须提供来源/业务确认依据')
        if any(v is not None and not isinstance(v,str) for v in (sidtext,new_ja,new_version,new_spec,new_material)):
            raise Rejected('补充内容须为文本，编码不得数值化')
        selected=[s.strip() for s in (sidtext or '').replace('，',',').split(',') if s.strip()]
        if len(selected)!=len(set(selected)) or set(selected)-set(catalog):raise Rejected('来源编号未知或重复')
        for sid in selected:
            f=catalog[sid]
            if f['fact_id'] not in case['candidate_fact_ids']:raise Rejected('来源不属于本商品候选范围')
            if f['values'].get('code_raw')!=case['query'].get('code_raw'):raise Rejected('不得按来源改码或给无码商品造码')
            if f['values'].get('code_type')!=case['query'].get('code_type'):raise Rejected('来源编码命名空间不一致')
        vals=dict(case['query']);origins={}
        for field,value in case['resolved_fields'].items():
            if field in IDENTITY and not vals.get(field):
                vals[field]=value['value'];origins[field]={'kind':'source_bound_offline_fact','sources':value['sources']}
        for field in ('version','specification'):
            options={catalog[s]['values'].get(field) for s in selected if catalog[s]['values'].get(field) is not None}
            if len(options)==1 and not vals.get(field):
                chosen=next(iter(options))
                if field!='specification' or specification_usable(chosen):
                    vals[field]=chosen;origins[field]={'kind':'explicit_selected_source','fact_ids':[catalog[s]['fact_id'] for s in selected]}
        supplied={'japanese_name':new_ja,'version':new_version,'specification':new_spec,'material_original':new_material}
        for field,value in supplied.items():
            if value is not None and value.strip():
                if value.strip().lower() in {'未知','不明','待确认','待补','n/a','unknown','-'}:raise Rejected('未确认字段请保持空缺，不能用占位词确认身份')
                vals[field]=value.strip();origins[field]={'kind':'human_return_pending_maintenance_confirmation','cell':f'{dict(japanese_name="G",version="H",specification="I",material_original="J")[field]}{ri}'}
        for field in BASIC:
            options={catalog[s]['values'].get(field) for s in selected if catalog[s]['values'].get(field) is not None}
            if len(options)==1:
                vals[field]=next(iter(options));origins[field]={'kind':'explicit_selected_source','fact_ids':[catalog[s]['fact_id'] for s in selected if catalog[s]['values'].get(field) is not None]}
        if not selected and not any(v not in (None,'') for v in supplied.values()):raise Rejected('确认行没有选择来源或填写补充值')
        if not vals.get('japanese_name'):raise Rejected('缺少日文身份，不能仅凭同码确认基础关联')
        selected_ja={catalog[s]['values'].get('japanese_name') for s in selected if catalog[s]['values'].get('japanese_name')}
        mismatch=any(comparable(ja)!=comparable(vals['japanese_name']) for ja in selected_ja)
        if mismatch and not new_ja:raise Rejected('选择来源与本批日文名冲突，需明确填写纠正值及依据')
        for field,override in [('version',new_version),('specification',new_spec)]:
            chosen={comparable(catalog[s]['values'].get(field)) for s in selected if catalog[s]['values'].get(field)}
            if (len(chosen)>1 or vals.get(field) and any(v!=comparable(vals[field]) for v in chosen)) and not override:
                raise Rejected('选择来源的版本/规格冲突，需明确填写纠正值及依据')
        # Unknowns remain blank. A basic-data confirmation never approves materials.
        edits.append({'case_id':cid,'values':vals,'selected_fact_ids':[catalog[s]['fact_id'] for s in selected],
                      'basis':basis.strip(),'identity_correction':vals['japanese_name']!=case['query'].get('japanese_name'),
                      'value_origins':origins,
                      'missing_after':[f for f in IDENTITY if not vals.get(f)],
                      'cell_evidence':{field:f'{col}{ri}' for field,col in [('japanese_name','G'),('version','H'),('specification','I'),('material_original','J'),('basis','K'),('confirmation','L')]}})
    if digest(workbook)!=before:raise Rejected('回传读取期间变化')
    result={'schema':'offline-identity-return-preview/1','plan_id':plan_id,'database_sha256':digest(database),
            'workbook':str(workbook),'workbook_sha256':before,'edits':edits,'filled_not_confirmed':unconfirmed,
            'material_approval':False,'d1_accessed':False,'formal_output':False}
    result['preview_hash']=key(result);return result
