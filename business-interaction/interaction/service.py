"""Stage file delivery and explicit review scopes. No calculation rules here."""
from pathlib import Path
from copy import deepcopy
import subprocess,shutil,xml.etree.ElementTree as ET
from . import rt,ROOT,load,save,key,digest,put,get,path,Rejected
from .workbook import main_copy
from . import manual_pack  # Version-scoped manual packaging input policy.

class Service:
    def __init__(self,config):
        self.config=load(config) if not isinstance(config,dict) else deepcopy(config)
        self.engine=rt.updates.Service(self.config['root']);self.root=self.engine.root
        if self.config['mode']!=self.engine.owner['mode']:raise Rejected('业务/隔离配置不符')
        self.background=Path(self.config['background']).resolve();self.public=Path(self.config['business_directory']).resolve()
        if self.background==self.public or self.background.is_relative_to(self.public):raise Rejected('后台资产不能放进日常交付目录')
        self.background.mkdir(parents=True,exist_ok=True);self.public.mkdir(parents=True,exist_ok=True)
    def _publish(self,source,filename):
        source=Path(source);destination=self.public/filename
        if self.config['mode']=='synthetic':filename='SYNTHETIC_'+filename;destination=self.public/filename
        if destination.exists() and digest(destination)!=digest(source):
            old=self.background/'retained-editable-copies'/(digest(destination)+'.xlsx');old.parent.mkdir(exist_ok=True)
            if not old.exists():shutil.copyfile(destination,old)
        if not destination.exists() or digest(destination)!=digest(source):shutil.copyfile(source,destination)
        return str(destination)
    def _retain_inactive(self,files):
        known=set()
        for name in ['current-business-delivery.json','last-main-display.json','last-audit-display.json']:
            record=self.background/name
            if not record.exists():continue
            value=load(record);known.update(value.get('business_files',[]))
            if value.get('file'):known.add(value['file'])
        for name in known-set(files):
            source=Path(name).resolve()
            if not source.exists():continue
            if source.parent!=self.public:raise Rejected('旧交付文件不在本批公开目录，拒绝移动')
            folder=self.background/'past-stage-files'/digest(source);folder.mkdir(parents=True,exist_ok=True);target=folder/source.name
            counter=1
            while target.exists():target=folder/(str(counter)+'-'+source.name);counter+=1
            if not target.resolve().is_relative_to(self.background):raise Rejected('历史保留路径越界')
            source.rename(target)
    def status(self):
        b=self.engine.store.load(self.engine.bid);update=get(self.root,b['loop']['active_update']) if b['loop']['active_update'] else None
        calc=self.root/'current-computation.json';current=load(calc) if calc.exists() else None
        qualified=bool(update and update['actual_price_qualified'])
        computation=bool(current and current.get('parent_hash')==key(b))
        if computation:
            s=rt.compute.Service(current['compute_root']);rt.compute.Bridge(s.root).current_input(s.preflight(s.bid))
            stage='drafts'
        else:stage='calculation' if qualified else 'basics'
        return {'stage':stage,'head':key(b),'mode':self.config['mode'],'actual_price_update_received':qualified,'calculation_confirmed':computation,'formal_output':False}
    def deliver(self):
        state=self.status();stage=state['stage']
        if stage=='basics':
            from .pack_reference import write_hints
            write_hints(self.engine,self.background)
            record=self.background/'last-main-display.json'
            if record.exists() and load(record)['head']==state['head'] and Path(load(record)['file']).exists():file=load(record)['file']
            else:
                source,counts=main_copy(self.engine,self.background);file=self._publish(source,'KMT20261101_基础资料.xlsx');save(record,{'head':state['head'],'file':file,'source_sha256':digest(source)})
            layout=load(self.engine.owner['workflow']);columns=layout.get('display_columns',{'manual_category':'M','category_reference':'Q','material_reference':'R','pack_reference':'S'})
            files=[file];message=f"请修改这一份基础资料表后直接回传。{columns['manual_category']}品类只留人工填写，{columns['category_reference']}品类仅供参考；{columns['material_reference']}保留材质原文，{columns['pack_reference']}提供盒规原文供人工判断，不自动计算或默认1。红色为待核或缺项，黄色为参考，可按颜色筛选。"
        elif stage=='calculation':
            record=self.background/'current-review-export.json';e=load(record) if record.exists() else None
            if not e or e['head']!=state['head']:
                p=rt.review.prepare(self.root);folder=self.background/'calculation-exports'/p['plan_id'];folder.mkdir(parents=True,exist_ok=True)
                p['draft_file']=str(folder/'authored.xlsx');plan=folder/'plan.json';save(plan,p)
                subprocess.run([self.config['node'],str(rt.cli.ROOT/'review-author.mjs'),str(plan)],check=True,capture_output=True,text=True,encoding='utf-8')
                e=rt.review.finalize_export(p,p['draft_file'],folder/'issued.xlsx');e['head']=state['head'];save(record,e)
            # Keep an edited same-filename audit copy until upstream version changes.
            public_record=self.background/'last-audit-display.json'
            if public_record.exists() and load(public_record)['export_id']==e['export_id'] and Path(load(public_record)['file']).exists():file=load(public_record)['file']
            else:
                file=self._publish(e['file'],'KMT20261101_计算审核.xlsx');save(public_record,{'file':file,'export_id':e['export_id']})
            files=[file];message='请修改这一份计算审核表后回传；系统重算并展示确认范围，确认通过后才交付双表草稿。'
        else:
            current=load(self.root/'current-computation.json');destination=self.background/'draft-pairs'/current['review_preview'][:16]
            pair=rt.delivery.render(current['compute_root'],destination)
            files=[self._publish(f,'内部到货表_草稿.xlsx' if '内部' in Path(f).name else '海关报关单_草稿.xlsx') for f in pair['files']]
            message='计算已按明确范围确认，以下两份为受控草稿，正式海关外发仍关闭。'
        # Authoritative daily list, not a recursive directory listing.
        self._retain_inactive(files)
        result={**state,'business_files':files,'message':message,'requires_explicit_confirmation':False}
        save(self.background/'current-business-delivery.json',result);return result
    def upload(self,file,*,kind=None,reference,price_basis_reference=None,purchase_evidence=None,confirm_material=False,selection=None,links=None):
        file=Path(file).resolve(strict=True)
        if not reference:raise Rejected('上传须绑定本次用户消息，不从Excel推定确认')
        if kind is None:
            from native_copy.ooxml import parts
            p=parts(file.read_bytes())
            if 'docProps/custom.xml' in p and b'CustomsAStageExportVersion' in p['docProps/custom.xml']:kind='basics'
            else:
                from openpyxl import load_workbook
                w=load_workbook(file,read_only=True);kind='calculation' if '计算审核' in w.sheetnames else 'update';w.close()
        batch=self.engine.store.load(self.engine.bid);head=key(batch)
        if kind=='basics':
            v=self.engine.basics.read_current(self.engine.bid);p=self.engine.basics.preview_return(self.engine.bid,file,expected_hash=v['current_hash'])
            requested_selection=selection
            selection={'save_changes':list(p['proposals']),'confirm_fields':[],'adopt_candidates':[],'evidence':{}}
            evidence=purchase_evidence or {};names={'internal_name','specification','category','channel','yd'}|({'material_reference'} if confirm_material else set())
            deferred_prices=0
            for target,f in v['fields'].items():
                name=f['field'];value=p['proposals'].get(target,{}).get('after',f['value'])['value']
                if value in (None,'') or f['confirmed'] and target not in p['proposals']:continue
                if name=='purchase_unit_price':
                    if target not in evidence:deferred_prices+=1;continue
                    selection['evidence'][target]=evidence[target]
                elif name not in names:continue
                else:
                    from separated import model
                    candidate=deepcopy(f);candidate['value']=p['proposals'].get(target,{}).get('after',f['value'])
                    try:model.eligibility(candidate,{}, {},{target:candidate})
                    except ValueError:continue  # Keep original validation: save pending, never auto-confirm invalid text.
                if p['proposals'].get(target,{}).get('needs_further_confirmation'):continue
                selection['adopt_candidates' if f['status']=='candidate' and target not in p['proposals'] else 'confirm_fields'].append(target)
            if requested_selection is not None:selection=deepcopy(requested_selection)
            if not any(selection[k] for k in ['save_changes','confirm_fields','adopt_candidates']):return {**self.deliver(),'message':'未发现新的修改或可确认范围，没有新增保存。'}
            plan=self.engine.basics.prepare_confirmation(p['preview_id'],selection)
            confirming=set(selection['confirm_fields'])|set(selection['adopt_candidates'])
            deferred_prices=sum(f['field']=='purchase_unit_price' and not f['confirmed'] and t not in confirming and p['proposals'].get(t,{}).get('after',f['value'])['value'] not in (None,'') for t,f in v['fields'].items())
            body={'kind':'basics','head':head,'plan_id':plan['plan_id'],'summary':plan['summary'],'proposed_changes':p['modified_cells'],'purchase_prices_deferred':deferred_prices,'selection':selection,
                'field_counts':{name:sum(v['fields'][t]['field']==name for t in selection['confirm_fields']+selection['adopt_candidates']) for name in names|{'purchase_unit_price'}}}
            body['message']=f"检测到修改{p['modified_cells']}格。拟保存{len(selection['save_changes'])}格、明确确认{plan['summary']['confirmed_fields']}格；采购价中{deferred_prices}格因来源/单位未明确继续待核。请确认本次展示范围。"
        elif kind=='update':
            # File shape cannot establish whether a Japanese price is actual.
            role='synthetic_actual_price_update' if self.config['mode']=='synthetic' else 'actual_price_update'
            p=self.engine.preview_update(file,role=role,reference=reference,links=links);body={'kind':'update','head':head,'preview_id':p['preview_id'],
                'new_unlinked_rows':p['new_unlinked_rows'],'issues':p['issues'],'changed_price_quantity_rows':p['changed_price_quantity_rows'],
                'message':'已预览日方新文件。请明确确认这是实际采购价格更新及所展示变化；基础资料中未变化的已确认范围将继承。'}
        elif kind=='calculation':
            if self.status()['stage'] not in {'calculation','drafts'}:raise Rejected('尚未收到实际价格更新，不接受计算审核回传')
            e=load(self.background/'current-review-export.json');p=rt.review.preview_return(self.root,e['export_id'],file,reference=reference,price_basis_reference=price_basis_reference)
            body={'kind':'calculation','head':head,'preview_id':p['preview_id'],'blocked_rows':p['blocked_rows'],'price_comparability_pending':p['price_comparability_pending'],
                'new_identity_rows_pending':p['new_identity_rows_pending'],'message':f"已重算，{p['blocked_rows']}行仍有阻断；价格口径待核={p['price_comparability_pending']}。通过后可一次明确确认当前范围。"}
        else:raise Rejected('未知附件角色')
        body['confirmation_required']=True;body['technical_mode']=self.config['mode'];token=put(self.background,body);return {**body,'confirmation_id':token,'business_files':[]}
    def confirm(self,confirmation_id,*,explicit_confirmation,reference):
        if explicit_confirmation is not True or not reference:raise Rejected('须有用户针对所展示范围的明确确认')
        p=get(self.background,confirmation_id)
        if p['technical_mode']!=self.config['mode']:raise Rejected('确认与目录模式不一致')
        # Underlying services enforce CAS, source hashes, and idempotency.
        if p['kind']=='basics':r=self.engine.basics.commit(p['plan_id'],confirmed_hash=p['plan_id'],explicit_confirmation=True,reference=reference)
        elif p['kind']=='update':r=self.engine.commit_update(p['preview_id'],confirmed_hash=p['preview_id'],explicit_confirmation=True,reference=reference)
        else:r=rt.cli.confirm_review(self.root,p['preview_id'],confirmed_hash=p['preview_id'],explicit_confirmation=True,reference=reference)
        result=self.deliver();result['saved']=True;result['receipt_replayed']=r.get('replayed',r.get('receipt',{}).get('replayed',False));save(self.background/('confirmation-'+confirmation_id+'.json'),{'receipt':r,'delivery':result});return result
