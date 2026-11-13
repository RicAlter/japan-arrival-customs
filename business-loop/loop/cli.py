from pathlib import Path
import argparse,json,subprocess,sys
from .support import load,save,get,key,ROOT,Rejected,writer
from .updates import Service as Updates
from . import review
def export_review(root,output,node):
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    p=review.prepare(root);technical=output.parent/'后台';technical.mkdir(exist_ok=True)
    p['draft_file']=str(technical/(p['plan_id']+'-authored.xlsx'));plan=technical/(p['plan_id']+'-plan.json');save(plan,p)
    subprocess.run([str(node),str(ROOT/'review-author.mjs'),str(plan)],check=True,capture_output=True,text=True,encoding='utf-8')
    return review.finalize_export(p,p['draft_file'],output)
def confirm_review(root,preview_id,*,confirmed_hash,explicit_confirmation,reference):
    if explicit_confirmation is not True or confirmed_hash!=preview_id or not reference:raise Rejected('须明确确认当前重算预览及范围')
    from .compute import Service
    parent=Updates(root);p=get(parent.root,preview_id)
    with writer(parent.root,parent.bid):
        if key(parent.store.load(parent.bid))!=p['base_hash']:raise Rejected('上游版本已变化')
        pointer=parent.root/'current-computation.json';current=load(pointer) if pointer.exists() else None
        current_id=current['review_preview'] if current and current.get('parent_hash')==p['base_hash'] else None
        if current_id!=preview_id and current_id!=p.get('previous_computation'):raise Rejected('已有更新的计算确认，旧重算预览不能覆盖')
        destination=parent.root/'calculations'/preview_id[:16]
        svc=Service(destination) if destination.exists() else Service.create(root,preview_id,destination)
        if svc.owner['review_preview']!=preview_id:raise Rejected('计算目录来源预览不符')
        file=destination/'first-confirmation-plan.json'
        if file.exists():plan=load(file)
        else:
            plan=svc.preview_basis(svc.bid,business_file=p['upload'],groups=svc.default_groups());save(file,plan)
        receipt=svc.commit_basis(plan['plan_id'],confirmed_hash=plan['plan_id'],explicit_confirmation=True,reference=reference)
        prepared=svc.preflight(svc.bid)
        from arrival_core.storage import atomic_json
        atomic_json(pointer,{'schema':'loop-current-computation/1','review_preview':preview_id,'compute_root':str(destination),
            'parent_hash':p['base_hash'],'compute_hash':prepared['a_hash'],'mode':parent.owner['mode'],'formal_output':False})
        return {'compute_root':str(destination),'receipt':receipt,'preflight':prepared}
def main():
    p=argparse.ArgumentParser(description='独立闭环候选；正式Skill和海关外发均不开放')
    p.add_argument('action',choices=['status','fork','basics-preview','basics-plan','basics-commit','update-preview','update-commit','review-export','review-preview','review-confirm','render'])
    for name in ['root','workflow','file','role','reference','price-basis-reference','preview','plan','selection','export-id','output','node','mode','confirmed-hash','result-file']:p.add_argument('--'+name)
    p.add_argument('--explicit-confirmation',action='store_true');a=p.parse_args()
    if a.action=='fork':
        s=Updates.fork(a.workflow,a.root,mode=a.mode);result={'root':str(s.root),'mode':s.owner['mode']}
    elif a.action=='render':
        from .delivery import render
        result=render(a.root,a.output)
    else:
        svc=Updates(a.root)
        if a.action=='status':
            b=svc.store.load(svc.bid);v=svc.basics.read_current(svc.bid)
            active=get(svc.root,b['loop']['active_update']) if b['loop']['active_update'] else None
            qualified=bool(active and active['actual_price_qualified'])
            result={'mode':svc.owner['mode'],'current_hash':key(b),'basic_confirmed_fields':v['confirmed_field_count'],'active_file_version':b['loop']['active_update'],
                'actual_price_update':b['loop']['active_update'] if qualified else None,
                'waiting_for_real_japanese_update':svc.owner['mode']!='business' or not qualified,'formal_output':False,'professional_approvals':0}
        elif a.action=='basics-preview':result=svc.basics.preview_return(svc.bid,a.file,expected_hash=svc.basics.read_current(svc.bid)['current_hash'])
        elif a.action=='basics-plan':result=svc.basics.prepare_confirmation(a.preview,load(a.selection))
        elif a.action=='basics-commit':result=svc.basics.commit(a.plan,confirmed_hash=a.confirmed_hash,explicit_confirmation=a.explicit_confirmation,reference=a.reference)
        elif a.action=='update-preview':result=svc.preview_update(a.file,role=a.role,reference=a.reference,links=load(a.selection) if a.selection else None)
        elif a.action=='update-commit':result=svc.commit_update(a.preview,confirmed_hash=a.confirmed_hash,explicit_confirmation=a.explicit_confirmation,reference=a.reference)
        elif a.action=='review-export':result=export_review(a.root,a.output,a.node)
        elif a.action=='review-preview':result=review.preview_return(a.root,a.export_id,a.file,reference=a.reference,price_basis_reference=a.price_basis_reference)
        else:result=confirm_review(a.root,a.preview,confirmed_hash=a.confirmed_hash,explicit_confirmation=a.explicit_confirmation,reference=a.reference)
    if a.result_file:
        save(a.result_file,result);summary={k:result[k] for k in ['preview_id','export_id','file','compute_root','mode','blocked_rows','price_comparability_pending','professional_approvals','formal_output'] if k in result}
        print(json.dumps({'result_file':a.result_file,**summary},ensure_ascii=False,default=str))
    else:print(json.dumps(result,ensure_ascii=False,default=str))
