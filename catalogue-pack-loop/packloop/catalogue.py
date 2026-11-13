"""Read-only current catalogue, complete source variants and scoped card evidence."""
import sqlite3,json,re
from pathlib import Path
from collections import defaultdict
from .support import digest,Rejected,key

def layers(raw,spec,jp):
    from .kinds import kind,matches
    text=str(raw or '');k=kind(spec,jp);found=[]
    for clause in re.split('[;；]',text):
        inner=re.search(r'1包\s*(\d+)\s*(枚|张|个|件)',clause);outer=re.search(r'1盒\s*(\d+)\s*包',clause)
        if inner and outer and matches(k,clause[:inner.start()].strip(),spec):
            p,u=int(outer[1]),int(inner[1])
            if p>0 and u>0:found.append({'packs_per_box':p,'units_per_pack':u,'declaration_units_per_box':p*u,'unit':'张' if inner[2] in {'枚','张'} else inner[2],'raw':text,'match_kind':k})
    # Alternate explicitly adjacent syntax: 贴纸整盒7包，每包2枚.
    for m in re.finditer(r'整盒\s*(\d+)\s*包\s*[,，、]?\s*每包\s*(\d+)\s*(枚|张|个|件)',text):
        label=re.split('[,，;；、]',text[:m.start()])[-1].strip()
        if matches(k,label,spec):
            p,u=int(m[1]),int(m[2])
            if p>0 and u>0:found.append({'packs_per_box':p,'units_per_pack':u,'declaration_units_per_box':p*u,'unit':'张' if m[3] in {'枚','张'} else m[3],'raw':text,'match_kind':k})
    return found

def snapshot(database,rows):
    database=Path(database).resolve(strict=True);sha=digest(database)
    db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON');db.row_factory=sqlite3.Row
    codes={str(r['code']) for r in rows};yds={r['yd'] for r in rows if r['yd']};entries=defaultdict(list);materials=defaultdict(list)
    # One exact scan of descriptors, no fuzzy name/implicit version matching.
    selected={}
    for e in db.execute('SELECT entry_id,descriptor_json,grouping_method FROM catalogue_entries'):
        d=json.loads(e['descriptor_json'])
        if str(d.get('code_raw')) in codes and d.get('yd') in yds:
            record={'entry_id':e['entry_id'],'descriptor':d,'variants':[],'sources':[],'identity_approved':False};selected[e['entry_id']]=record
            entries[(str(d.get('code_raw')),d.get('yd'))].append(record)
    for f in db.execute('SELECT entry_id,field_name,value_json,sample_observation_sha256 FROM field_variants'):
        if f['entry_id'] in selected:selected[f['entry_id']]['variants'].append({'field':f['field_name'],'value':json.loads(f['value_json']),'observation':f['sample_observation_sha256']})
    for f in db.execute('SELECT entry_id,observation_sha256,position_id,provenance_json,raw_record_sha256,fields_sha256 FROM record_links'):
        if f['entry_id'] in selected:selected[f['entry_id']]['sources'].append(dict(f))
    columns={r['import_sha256']:json.loads(r['columns_json']) for r in db.execute('SELECT import_sha256,columns_json FROM yd_material_imports')}
    for m in db.execute('SELECT * FROM yd_material_lookup'):
        if m['yd_key'] in yds:materials[m['yd_key']].append(dict(m))
    result={}
    for row in rows:
        related=entries[(str(row['code']),row['yd'])];exact=[e for e in related if e['descriptor'].get('specification')==row['specification']]
        refs=materials[row['yd']];candidates=[]
        for card in refs:
            for p in layers(card['accessories_original'],row['specification'],row['japanese_name']):
                names=columns[card['import_sha256']];column=names.index('产品配件')+1 if '产品配件' in names else None
                if column is None:raise Rejected('包装原文缺少可定位的配件列')
                letter='';v=column
                while v:v,rem=divmod(v-1,26);letter=chr(65+rem)+letter
                p['source']={'sha256':card['import_sha256'],'path':card['archive_path'],'sheet':card['sheet'],'row':card['source_row'],'cell':letter+str(card['source_row']),'yd':card['yd_key'],'kind':'YD_link_accessories_selected_by_specific_product_type'}
                candidates.append(p)
        unique={(p['packs_per_box'],p['units_per_pack']) for p in candidates}
        result[str(row['row'])]={'code':str(row['code']),'yd':row['yd'],'specification':row['specification'],'catalogue_exact_spec':exact,'other_descriptors_same_code_yd':related,
            'material_link_sources':refs,'material_scope':'YD链接成分集合；不自动作为具体SKU最终材质','pack_candidates':candidates,
            'pack_reference':candidates[0] if len(unique)==1 else None,'pack_conflict':len(unique)>1,'automatic_confirmation':False}
    counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['catalogue_entries','record_links','yd_material_rows']};db.close()
    if digest(database)!=sha:raise Rejected('资料库在只读快照期间变化，请重新读取')
    return {'schema':'catalogue-pack-source/1','database':str(database),'sha256':sha,'counts':counts,'rows':result,'raw_values_directly_quoted':True,'same_source_position_is_not_independent_evidence':True}
