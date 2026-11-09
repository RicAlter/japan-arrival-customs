"""Read-only, row-bound delivery audit. Coverage is separate from approval."""
from collections import Counter
from decimal import Decimal
from pathlib import Path
import posixpath
import re
import io
import xml.etree.ElementTree as ET

from . import Rejected, digest, key, load, save
from .photo_layout import parts, sheet_member, XDR, RID, REL
from .preparation_workbook import Q, native_project
from .material_review import same_binding, website_execution, read_evidence, valid_for_row

FIELDS={'F':'name','G':'spec','H':'price','P':'channel','Q':'yd','R':'website_material','S':'library_material','T':'packaging'}


def picture_rows(package, sheet):
    """Count actual E-column pictures with resolvable embedded media, not URLs."""
    member=sheet_member(package,sheet)
    relfile=posixpath.join(posixpath.dirname(member),'_rels',posixpath.basename(member)+'.rels')
    relations={r.get('Id'):r.get('Target') for r in ET.fromstring(package[relfile])} if relfile in package else {}
    observed=set();verified_media=set()
    for drawing in ET.fromstring(package[member]).findall(Q+'drawing'):
        target=relations.get(drawing.get(RID+'id'))
        if not target:raise Rejected('图片drawing缺少关系')
        path=posixpath.normpath(posixpath.join(posixpath.dirname(member),target)).lstrip('/')
        if target.startswith('/'):path=target.lstrip('/')
        if path not in package:raise Rejected('图片drawing资源缺失')
        relpath=posixpath.join(posixpath.dirname(path),'_rels',posixpath.basename(path)+'.rels')
        image_rels={r.get('Id'):r.get('Target') for r in ET.fromstring(package[relpath])} if relpath in package else {}
        for anchor in ET.fromstring(package[path]):
            origin=anchor.find(XDR+'from')
            if origin is None or origin.findtext(XDR+'col')!='4':continue
            for picture in anchor.findall(XDR+'pic'):
                blip=picture.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
                link=image_rels.get(blip.get(RID+'embed')) if blip is not None else None
                media=posixpath.normpath(posixpath.join(posixpath.dirname(path),link)).lstrip('/') if link else None
                if link and link.startswith('/'):media=link.lstrip('/')
                if not media or media not in package or not package[media]:raise Rejected('嵌入图片媒体缺失')
                if media not in verified_media:
                    from PIL import Image
                    try:
                        with Image.open(io.BytesIO(package[media])) as image:image.verify()
                    except Exception as exc:raise Rejected('嵌入图片媒体损坏') from exc
                    verified_media.add(media)
                observed.add(int(origin.findtext(XDR+'row'))+1)
    return observed


def numeric(value):
    if value in (None,''):return None
    try:return Decimal(str(value))
    except Exception:return str(value)


def review_delivery(config, file=None, *, head=None, output=None):
    from openpyxl import load_workbook
    from native_copy.profiles import inspect_source
    config=load(config) if not isinstance(config,dict) else config
    back=Path(config['background']);file=Path(file or config['prepared_file'])
    strict=config.get('delivery_review_required',False)
    sop=config.get('preparation_policy',{}).get('sop')
    if strict and (not sop or digest(sop['path'])!=sop['sha256']):raise Rejected('交付核验：本批业务SOP版本缺失或漂移')
    if digest(config['source'])!=config['source_sha256']:raise Rejected('交付核验：原件快照摘要变化')
    source=inspect_source(config['source']);package=parts(file.read_bytes());media_rows=picture_rows(package,config['sheet'])
    workbook=load_workbook(file,read_only=True,data_only=True)
    try:
        sheet=workbook[config['sheet']];observed=list(sheet.values)
        if sheet.max_column!=20:raise Rejected('交付核验：不是唯一20列布局')
    finally:workbook.close()
    # Use native projection for formula addresses, without recalculating or saving.
    expected_package=parts(native_project(source,20));member=sheet_member(package,config['sheet'])
    expected_sheets=[s.get('name') for s in ET.fromstring(expected_package['xl/workbook.xml']).iter(Q+'sheet')]
    actual_sheets=[s.get('name') for s in ET.fromstring(package['xl/workbook.xml']).iter(Q+'sheet')]
    if actual_sheets!=expected_sheets:raise Rejected('交付核验：页签变化')
    for values in observed[len(source['rows'])+1:]:
        if len(values)>2 and values[2] not in (None,''):
            raise Rejected('交付核验：原行范围外出现商品编码')
    expected_member=sheet_member(expected_package,config['sheet'])
    cells={c.get('r'):c for c in ET.fromstring(package[member]).iter(Q+'c')}
    expected_cells={c.get('r'):c for c in ET.fromstring(expected_package[expected_member]).iter(Q+'c')}
    for address,c in expected_cells.items():
        if not address.startswith('M') or address=='M1':continue
        actual=cells.get(address)
        if actual is None or actual.findtext(Q+'f')!=c.findtext(Q+'f') or numeric(actual.findtext(Q+'v'))!=numeric(c.findtext(Q+'v')):
            raise Rejected('交付核验：原金额公式或缓存变化 '+address)
    for name,data in expected_package.items():
        if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',name) and name!=expected_member and package.get(name)!=data:
            raise Rejected('交付核验：箱重或其他页签变化 '+name)
    evidence=load(back/'evidence.json')['rows']
    completed=load(back/'material-review-complete.json') if (back/'material-review-complete.json').exists() else {}
    dual=load(completed['reference_report']) if completed.get('reference_report') else {'rows':{}}
    online_path=Path(completed.get('reference_report',back/'none')).parent/'online-state.json'
    online=load(online_path) if online_path.is_file() else {}
    settings=config.get('material_review_settings',{})
    manifests=sorted({e['manifest'] for r in dual['rows'].values() for e in r['website'].get('evidence',[]) if e.get('manifest')})
    verified,bad=read_evidence(manifests)
    rows={};unresolved=Counter();execution=Counter();counts=Counter();missing=Counter();preserved=Counter();lookup_count=0
    for n,rawrow in enumerate(source['rows'],2):
        if n>len(observed):raise Rejected('交付核验：商品行缺失')
        values=observed[n-1];raw=rawrow['source']['cells']
        for role,col in [('code',2),('ja',9),('qty',10),('price',11),('amount',12),('origin',1)]:
            expected=raw[role]['value'];actual=values[col]
            equal=numeric(expected)==numeric(actual) if role in {'qty','price','amount'} else str(expected or '')==str(actual or '')
            if not equal:raise Rejected(f'交付核验：原始{role}变化，行{n}')
        item=evidence.get(str(n))
        if item is None:raise Rejected('交付核验：缺少本行资料检索记录 '+str(n))
        lookup=item.get('lookup_execution',{}).get('executed') is True
        if not strict and all(k in item for k in ['status','sources','row_id']):lookup=True
        if not lookup and strict:raise Rejected('交付核验：缺少实际资料检索状态 '+str(n))
        lookup_count+=bool(lookup)
        issues=[];display={}
        for col,field in FIELDS.items():
            value=values[ord(col)-65];display[col]=value not in (None,'')
            if display[col]:counts[col]+=1
            else:
                missing[col]+=1
                if col not in {'R'}:
                    issues.append({'field':col,'reason':'source_identity_conflict' if 'conflict' in item.get('status','') else 'no_unique_usable_source_value'})
        for field in item.get('preserved_source_fields',{}):preserved[field]+=1
        image=item.get('image_execution')
        if n in media_rows:
            image={'status':'embedded','reason':'actual_E_anchor_and_media_verified','source_execution':image or {'status':'retained_existing_picture'}}
            counts['E']+=1
        else:
            missing['E']+=1
            if not image:
                image={'status':'not_executed','reason':'legacy_image_execution_not_recorded'}
            if not image.get('reason') or strict and image['status'] in {'cache_verified','downloaded'}:
                raise Rejected('交付核验：图片未嵌入或未完成原因缺失 '+str(n))
            issues.append({'field':'E',**image})
        entry=dual['rows'].get(str(n));binding={'jan':str(values[2]),'name_ja':str(values[9] or ''),'spec':str(values[6] or ''),'yd':str(values[16] or '')}
        if entry and same_binding(binding,entry['binding']):
            web=entry['website'];webexec=entry.get('website_execution') or website_execution({**binding,'identity_key':key(binding)},web,settings,online)
            if web['status'] in {'found','conflict'}:
                actual_evidence=[c for c in verified.get(binding['jan'],[]) if valid_for_row(c,{**binding,'row':n})]
                if not actual_evidence:
                    if strict:raise Rejected('交付核验：网站缓存证据无法复核 '+str(n))
                    webexec={'status':'not_executed','reason':'website_evidence_no_longer_verifiable'}
                elif web['status']=='found' and values[17]!=web['values'][0]:
                    issues.append({'field':'R','reason':'existing_R_conflict_or_verified_result_not_presented'})
        else:
            webexec={'status':'not_executed','reason':'nonstandard_code_not_verified_JAN' if not re.fullmatch(r'\d{8,14}',binding['jan']) else 'material_review_missing_or_identity_changed'}
        if not webexec.get('reason'):raise Rejected('交付核验：网站未完成原因缺失 '+str(n))
        if webexec['status']!='verified_evidence':issues.append({'field':'website_material',**webexec})
        execution['image:'+image['status']]+=1;execution['website:'+webexec['status']]+=1
        for issue in issues:unresolved[issue['reason']]+=1
        rows[str(n)]={'jan':binding['jan'],'lookup_executed':lookup,'fields_present':display,'image':image,'website':webexec,'issues':issues}
    if len(evidence)!=len(source['rows']):raise Rejected('交付核验：商品行数与来源不一致')
    quantity=config.get('quantity_review')
    if quantity and digest(quantity['path'])!=quantity['sha256']:raise Rejected('交付核验：JAN数量报告摘要变化')
    result={'schema':'prepared-delivery-review/1','file':str(file),'file_sha256':digest(file),'head':head,'sop':sop,
            'source_sha256':config['source_sha256'],'rows':rows,'summary':{
                'status':'complete' if not unresolved else 'incomplete_with_reasons','row_count':len(rows),'columns':20,
                'lookup_executed_rows':lookup_count,'fields_filled':dict(counts),'fields_missing':dict(missing),
                'actual_embedded_image_rows':len(media_rows),'execution_counts':dict(execution),
                'unfinished_reason_counts':dict(unresolved),'rows_needing_attention':sum(bool(r['issues']) for r in rows.values()),
                'original_facts_formulas_cache_and_other_sheets_preserved':True,
                'preserved_source_field_rows':dict(preserved),'unexplained_omissions':0,'new_confirmations':0,
                'quantity_unknown_blocks_delivery':False,'rejected_website_evidence':len(bad)}}
    target=Path(output) if output else back/'delivery-completeness.json'
    # current is idempotent: do not touch even the report if nothing changed.
    if not target.exists() or load(target)!=result:save(target,result)
    return {'report':str(target),'sha256':digest(target),**result['summary']}
