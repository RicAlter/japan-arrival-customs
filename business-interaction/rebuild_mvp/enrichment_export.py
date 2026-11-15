"""Lossless reference-material and picture overlay. No workbook round-trip."""
import copy, csv, html, os, posixpath, re, zipfile, hashlib, json, uuid
from pathlib import Path
import xml.etree.ElementTree as ET
from .xlsxio import read_book, sheet_info
from .service import digest, save_json
from .purchase_images import X, R, RID, Q
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
C='{http://schemas.openxmlformats.org/package/2006/content-types}'

def serialize(root):return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def export(source,destination,sheet,materials,pictures,policy):
    source=Path(source);destination=Path(destination)
    source_sha=digest(source)
    signature=hashlib.sha256(json.dumps([source_sha,sheet,materials,{n:v['sha256'] for n,v in pictures.items()},policy],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    receipt=destination.with_suffix('.export.json')
    if receipt.exists():
        old=json.loads(receipt.read_text(encoding='utf8'))
        if old['signature']!=signature:raise ValueError('TASK_CONFLICT: 既有导出绑定不同内容')
        target=destination if destination.exists() else Path(old['temporary'])
        if not target.exists() or digest(target)!=old['result']['sha256']:raise ValueError('SOURCE_CHANGED: 导出结果或恢复文件变化')
        if target!=destination:target.replace(destination)
        return old['result']
    if destination.exists():raise ValueError('TASK_CONFLICT: 输出已存在，不覆盖')
    if source.with_name('~$'+source.name).exists():raise ValueError('TASK_CONFLICT: 表格正在编辑')
    before=read_book(source);source_sha=before['sha256'];rows=next(s['rows'] for s in before['sheets'] if s['name']==sheet)
    rowmap={r['row']:r for r in rows};member=next(s['path'] for s in before['sheets'] if s['name']==sheet)
    relname=posixpath.dirname(member)+'/_rels/'+posixpath.basename(member)+'.rels'
    edits={int(n):v for n,v in materials.items() if not rowmap[int(n)]['values'].get('R') and 'R' not in rowmap[int(n)]['formulas']}
    with zipfile.ZipFile(source) as z:
        names=set(z.namelist());data=z.read(member)
        for n,v in edits.items():
            addr='R'+str(n);pattern=rb'<(?:\w+:)?c\b(?=[^>]*\br="'+addr.encode()+rb'")[^>]*?(?:/>|>.*?</(?:\w+:)?c>)'
            def replace(m):
                start=m.group(0).split(b'>',1)[0].rstrip(b'/')
                start=re.sub(rb'\s+t="[^"]*"',b'',start)
                prefix=re.match(rb'<(\w+:)?c',start)[1] or b''
                return start+b' t="inlineStr"><'+prefix+b'is><'+prefix+b't xml:space="preserve">'+html.escape(v).encode()+b'</'+prefix+b't></'+prefix+b'is></'+prefix+b'c>'
            data,count=re.subn(pattern,replace,data,flags=re.S)
            if count==0:
                # A genuinely absent target cell is inserted in column order.
                rt=ET.fromstring(data);row=next(x for x in rt.find(Q+'sheetData') if x.get('r')==str(n));c=ET.Element(Q+'c',{'r':addr,'t':'inlineStr'});ET.SubElement(ET.SubElement(c,Q+'is'),Q+'t').text=v
                row.append(c)
                from .xlsxio import col_number
                row[:]=sorted(row,key=lambda c:col_number(re.match('[A-Z]+',c.get('r'))[0]));data=serialize(rt)
            elif count!=1:raise ValueError('TASK_CONFLICT: 目标单元格不唯一')
        rels=ET.fromstring(z.read(relname)) if relname in names else ET.Element(R+'Relationships')
        drawing_rel=next((x for x in rels if x.get('Type','').endswith('/drawing')),None)
        if drawing_rel is not None:
            drawname=posixpath.normpath(posixpath.join(posixpath.dirname(member),drawing_rel.get('Target'))).lstrip('/')
            drawing=ET.fromstring(z.read(drawname))
        else:
            number=1
            while f'xl/drawings/drawing{number}.xml' in names:number+=1
            drawname=f'xl/drawings/drawing{number}.xml';drawing=ET.Element(X+'wsDr')
        drawrels=posixpath.dirname(drawname)+'/_rels/'+posixpath.basename(drawname)+'.rels'
        image_rels=ET.fromstring(z.read(drawrels)) if drawrels in names else ET.Element(R+'Relationships')
        occupied={int(a.findtext(X+'from/'+X+'row'))+1 for a in drawing if a.find('.//'+X+'pic') is not None and a.findtext(X+'from/'+X+'row') is not None}
        pic_edits={int(n):v for n,v in pictures.items() if int(n) not in occupied}
        extra={};known={x.get('Id') for x in image_rels};maxid=max([int(x.get('id','0')) for x in drawing.iter(X+'cNvPr')]+[0]);cache={}
        for n,v in sorted(pic_edits.items()):
            if digest(v['path'])!=v['sha256']:raise ValueError('SOURCE_CHANGED: 图片缓存变化')
            key=v['sha256']
            if key not in cache:
                k=1
                while 'rId'+str(k) in known:k+=1
                rid='rId'+str(k);known.add(rid);name='xl/media/enrich_'+key+'.png';cache[key]=rid;extra[name]=Path(v['path'])
                ET.SubElement(image_rels,R+'Relationship',{'Id':rid,'Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image','Target':posixpath.relpath(name,posixpath.dirname(drawname))})
            scale=min(policy['image_width_emu']/v['width'],policy['image_height_emu']/v['height']);w=int(v['width']*scale);h=int(v['height']*scale)
            anchor=ET.SubElement(drawing,X+'twoCellAnchor',{'editAs':'twoCell'})
            for label,dx,dy in [('from',38100,38100),('to',38100+w,38100+h)]:
                marker=ET.SubElement(anchor,X+label)
                for key2,val in [('col',4),('colOff',dx),('row',n-1),('rowOff',dy)]:ET.SubElement(marker,X+key2).text=str(val)
            pic=ET.SubElement(anchor,X+'pic');nv=ET.SubElement(pic,X+'nvPicPr');maxid+=1
            ET.SubElement(nv,X+'cNvPr',{'id':str(maxid),'name':'采购图片 '+str(n)})
            ET.SubElement(ET.SubElement(nv,X+'cNvPicPr'),A+'picLocks',{'noChangeAspect':'1'})
            fill=ET.SubElement(pic,X+'blipFill');ET.SubElement(fill,A+'blip',{RID+'embed':cache[v['sha256']]});ET.SubElement(ET.SubElement(fill,A+'stretch'),A+'fillRect')
            sp=ET.SubElement(pic,X+'spPr');ET.SubElement(ET.SubElement(sp,A+'prstGeom',{'prst':'rect'}),A+'avLst');ET.SubElement(anchor,X+'clientData')
        changes={member:data}
        if pic_edits:
            def height(m):
                tag=m.group(0);n=int(re.search(rb'\br="(\d+)"',tag)[1])
                if n not in pic_edits:return tag
                tag=re.sub(rb'\s+(?:ht|customHeight)="[^"]*"',b'',tag)
                return tag[:-1]+f' ht="{policy["row_height_points"]}" customHeight="1">'.encode()
            data=re.sub(rb'<(?:\w+:)?row\b[^>]*>',height,data)
            if drawing_rel is None:
                ids={x.get('Id') for x in rels};k=1
                while 'rId'+str(k) in ids:k+=1
                rid='rId'+str(k);ET.SubElement(rels,R+'Relationship',{'Id':rid,'Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing','Target':posixpath.relpath(drawname,posixpath.dirname(member))})
                # Preserve the source namespace and schema ordering.
                rt=ET.fromstring(data);node=ET.Element(Q+'drawing',{RID+'id':rid});late={Q+x for x in ['legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst']}
                at=next((i for i,x in enumerate(rt) if x.tag in late),len(rt));rt.insert(at,node);data=serialize(rt);changes[relname]=serialize(rels)
            changes[member]=data;changes[drawname]=serialize(drawing);changes[drawrels]=serialize(image_rels)
            types=ET.fromstring(z.read('[Content_Types].xml'))
            if not any(x.get('Extension')=='png' for x in types):types.insert(0,ET.Element(C+'Default',{'Extension':'png','ContentType':'image/png'}))
            if not any(x.get('PartName')=='/'+drawname for x in types):ET.SubElement(types,C+'Override',{'PartName':'/'+drawname,'ContentType':'application/vnd.openxmlformats-officedocument.drawing+xml'})
            changes['[Content_Types].xml']=serialize(types)
        temporary=destination.with_suffix('.tmp-'+uuid.uuid4().hex+'.xlsx')
        with zipfile.ZipFile(temporary,'x',allowZip64=True) as out:
            for old in z.infolist():
                info=zipfile.ZipInfo(old.filename,old.date_time);info.compress_type=old.compress_type;info.file_size=old.file_size;info.external_attr=old.external_attr
                if old.filename in changes:out.writestr(info,changes[old.filename]);continue
                with z.open(old) as f,out.open(info,'w') as g:
                    while chunk:=f.read(1024*1024):g.write(chunk)
            for name,value in changes.items():
                if name not in names:out.writestr(name,value,compress_type=zipfile.ZIP_DEFLATED)
            for name,path in extra.items():out.write(path,name,compress_type=zipfile.ZIP_DEFLATED)
        after=read_book(temporary)
        assert len(before['sheets'])==len(after['sheets'])
        for x,y in zip(before['sheets'],after['sheets']):
            assert x['name']==y['name'] and x['merges']==y['merges'] and len(x['rows'])==len(y['rows'])
            for r,s in zip(x['rows'],y['rows']):
                r=copy.deepcopy(r);s=copy.deepcopy(s)
                if x['name']==sheet and r['row'] in edits:
                    assert s['values']['R']==edits[r['row']]
                    for obj in (r,s):obj['values'].pop('R',None);obj['types'].pop('R',None)
                assert r==s,('NON_TARGET_CHANGED',x['name'],r['row'])
        with zipfile.ZipFile(temporary) as check:
            assert check.testzip() is None
            for name in names-changes.keys():assert z.read(name)==check.read(name)
        if digest(source)!=source_sha:raise ValueError('SOURCE_CHANGED: 写出时输入变化')
    result={'path':str(destination.resolve()),'sha256':digest(temporary),'material_rows':len(edits),'new_picture_rows':len(pic_edits),'non_target_differences':0}
    save_json(receipt,{'signature':signature,'temporary':str(temporary.resolve()),'result':result})
    temporary.replace(destination)
    return result
