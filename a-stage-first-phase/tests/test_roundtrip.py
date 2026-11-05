"""Opt-in real-layout technical replay; mutations/approvals only in a temp clone."""
from pathlib import Path
from decimal import Decimal
import io,json,os,re,shutil,sys,tempfile,unittest,zipfile
import xml.etree.ElementTree as ET
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage1.support import bootstrap,load,digest,Rejected,save
bootstrap()
from stage1.service import Service
from native_copy.support import snapshot_root
from native_copy.ooxml import parts,sheet_member,Q

def edit(source,changes,target):
    """Synthetic uploaded changes, never an authored business deliverable."""
    raw=Path(source).read_bytes();p=parts(raw)
    for sheet,addr,kind,value in changes:
        member=sheet_member(p,sheet);t=ET.fromstring(p[member]);sd=t.find(Q+'sheetData')
        row=next(r for r in sd if r.get('r')==re.search(r'\d+$',addr)[0])
        cell=next((c for c in row if c.get('r')==addr),None)
        if cell is None:cell=ET.SubElement(row,Q+'c',{'r':addr})
        for child in list(cell):cell.remove(child)
        cell.attrib.pop('t',None)
        if kind=='number':ET.SubElement(cell,Q+'v').text=str(value)
        elif kind=='formula':ET.SubElement(cell,Q+'f').text=value;ET.SubElement(cell,Q+'v').text='99999'
        else:cell.set('t','inlineStr');ET.SubElement(ET.SubElement(cell,Q+'is'),Q+'t').text=value
        p[member]=ET.tostring(t,encoding='utf-8',xml_declaration=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as src,zipfile.ZipFile(target,'w') as out:
        for info in src.infolist():out.writestr(info,p[info.filename])
    return target

def scope(save=(),confirm=(),adopt=()):
    return {'save_changes':list(save),'confirm_fields':list(confirm),'adopt_candidates':list(adopt),'evidence':{}}

@unittest.skipUnless(os.environ.get('STAGE1_WORKFLOW'),'set STAGE1_WORKFLOW for isolated real-layout replay')
class RealLayoutReplay(unittest.TestCase):
    def test_real_layout_synthetic_return_save_and_protection(self):
        m=load(os.environ['STAGE1_WORKFLOW']);out=Path(os.environ['STAGE1_WORKFLOW']).parent
        reg=load(out/'native-copy/technical/export-registration.json');plan=load(out/'technical/authoring-plan.json')
        refs=load(out/'technical/reference-snapshot.json');issued=Path(m['issued_file']);sheet=reg['row_map'][0]['source']['sheet'];checks=[]
        def ok(name,condition):
            self.assertTrue(condition,name);checks.append({'test':name,'passed':True});print('PASS',name,flush=True)
        def rejected(name,call):
            try:call()
            except Exception as exc:
                ok(name,isinstance(exc,ValueError));return
            self.fail(name+' was accepted')
        row2=lambda view,col:view['fields'][sheet+'!'+col+'2']
        target=lambda col,n=2:sheet+'!'+col+str(n)
        live=Service(m['a03_root']);before=live.read_current(m['batch_id']);livefiles={str(p):digest(p) for p in Path(m['a03_root']).rglob('*') if p.is_file()}
        import native22.pricing as pricing
        fail=lambda *a,**k:(_ for _ in ()).throw(AssertionError('forbidden phase-one math'))
        with tempfile.TemporaryDirectory(prefix='stage1-technical-') as temp,patch.object(pricing,'calculate',fail),patch.object(pricing,'analyze',fail),patch.object(pricing,'formula_plan',fail):
            temp=Path(temp);clone=temp/'state';shutil.copytree(snapshot_root(Path(m['a03_root'])),snapshot_root(clone));svc=Service(clone);bid=m['batch_id'];v=svc.read_current(bid)
            ok('real_1275_rows',len(reg['row_map'])==1275)
            ok('issued_revision0_and_no_real_confirmation',v['revision']==0 and v['confirmed_field_count']==0 and not m['human_return_received'])
            ok('no_box_or_price_difference_calls',v['pricing_deferred'] and v['calculated_cells']==[] and not v['box_confirmation_required'])
            ok('original_purchase_precision',Decimal(row2(v,'G')['value']['value'])==Decimal('2629.1265'))
            ok('price_not_automatically_minimum',all(not x['minimum_unit_price_confirmed'] for x in v['purchase_unit_contexts']))
            ok('purchase_quantity_is_not_arrival_fallback',row2(v,'Q')['value']['type']=='blank' and all(not r['metadata'].get('purchase_quantity',{}).get('arrival_qty_substituted') for r in refs['rows']))
            shared=[r for r in refs['rows'] if r['metadata'].get('purchase_quantity',{}).get('shared_observation')]
            ok('shared_procurement_observations_not_repeated',len(shared)==20 and all(r['values']['purchase_quantity'] is None for r in shared))
            ok('1182_independent_quantity_source_coordinates',sum(r['values']['purchase_quantity'] is not None for r in refs['rows'])==1182 and all(r['metadata']['purchase_quantity']['sources'][0]['cell'].startswith('D') for r in refs['rows'] if r['values']['purchase_quantity'] is not None))
            ok('manual_material_optional_and_ai_separate',all(f['value']['type']=='blank' for f in v['fields'].values() if f['field']=='material_reference') and reg['stage1_policy']['reference_columns']=={'category':'T','material':'U'})
            unchanged=svc.preview_return(bid,issued,expected_hash=v['current_hash'])
            ok('issued_copy_recognized_zero_changes',unchanged['modified_cells']==0)
            rejected('unknown_price_unit_cannot_be_confirmed',lambda:svc.prepare_confirmation(unchanged['preview_id'],scope(adopt=[target('G')])))
            rejected('unchanged_yellow_needs_explicit_adoption',lambda:svc.prepare_confirmation(unchanged['preview_id'],scope(confirm=[target('F')])))
            from a_confirm.service import Service as Frozen
            rejected('old_a04_a03_cannot_take_over_stage1_store',lambda:Frozen(clone))
            # All seven fields plus price/quantity units in one Excel return.
            values={'E':('text','SYNTHETIC 技术名称'),'F':('text','SYNTHETIC 技术规格'),'G':('number','12.3456'),'M':('text','SYNTHETIC 品类'),
                'O':('text','SYNTHETIC 渠道'),'P':('text','SYNTHETIC-YD'),'Q':('number','14'),'R':('text','个'),'S':('text','个')}
            upload=edit(issued,[(sheet,c+'2',k,x) for c,(k,x) in values.items()],temp/'synthetic-return.xlsx')
            p=svc.preview_return(bid,upload,expected_hash=v['current_hash']);ok('all_seven_fields_and_units_in_one_preview',p['modified_cells']==9)
            save(out/'technical/synthetic-preview.json',p)
            rejected('preview_does_not_save',lambda:svc.commit(p['preview_id'],confirmed_hash=p['preview_id'],explicit_confirmation=True,reference='SYNTHETIC'))
            ok('preview_state_unchanged',svc.read_current(bid)['current_hash']==v['current_hash'])
            for label,sh,addr,kind,value in [('arrival_qty',sheet,'J2','number','999'),('japanese_price',sheet,'K2','number','999'),('subtotal_formula',sheet,'L2','formula','J2*K2+1'),
                ('source_jan',sheet,'C2','text','SYNTHETIC'),('box',sheet,'H2','number','7'),('weight','重さとサイズ','B2','number','999'),('ai_reference',sheet,'U507','text','SYNTHETIC')]:
                bad=edit(issued,[(sh,addr,kind,value)],temp/(label+'.xlsx'))
                rejected('protected_'+label,lambda bad=bad:svc.preview_return(bid,bad,expected_hash=v['current_hash']))
            prior=load(out/'technical/request.json')['references']['prior_workbook']
            rejected('old_issue_version_rejected',lambda:svc.preview_return(bid,prior,expected_hash=v['current_hash']))
            partial=svc.prepare_confirmation(p['preview_id'],scope([target('E')],[target('E')]))
            full=svc.prepare_confirmation(p['preview_id'],scope([target(c) for c in values],[target(c) for c in values]))
            rejected('explicit_confirmation_required',lambda:svc.commit(full['plan_id'],confirmed_hash=full['plan_id'],explicit_confirmation=False,reference='SYNTHETIC'))
            receipt=svc.commit(full['plan_id'],confirmed_hash=full['plan_id'],explicit_confirmation=True,reference='SYNTHETIC TECHNICAL TEST / NOT REAL BUSINESS APPROVAL')
            after=Service(clone).read_current(bid);save(out/'technical/synthetic-receipt.json',receipt)
            ok('seven_fields_scoped_save_and_reload',after['revision']==1 and all(row2(after,c)['confirmed'] for c in values) and row2(after,'G')['value']['value']=='12.3456')
            ctx=next(x for x in after['purchase_unit_contexts'] if x['row_id']==row2(after,'G')['row_id'])
            ok('minimum_unit_requires_explicit_price_and_unit',ctx['minimum_unit_price_confirmed'] and ctx['minimum_unit_price']=='12.3456')
            ok('price_source_and_original_quote_retained',row2(after,'G')['stage1_source_metadata']['original_price']=='2629.1265' and row2(after,'G')['evidence']['unit']=='个' and row2(after,'G')['stage1_source_metadata']['sources'])
            ok('material_not_required_for_other_fields',not row2(after,'N')['confirmed'] and row2(after,'N')['value']['type']=='blank')
            again=svc.commit(full['plan_id'],confirmed_hash=full['plan_id'],explicit_confirmation=True,reference='SYNTHETIC duplicate')
            ok('repeat_commit_idempotent',again['replayed'] and again['revision']==1)
            rejected('stale_plan_cannot_overwrite',lambda:svc.commit(partial['plan_id'],confirmed_hash=partial['plan_id'],explicit_confirmation=True,reference='SYNTHETIC stale'))
            conflicting=edit(issued,[(sheet,'E2','text','SYNTHETIC stale overwrite')],temp/'stale.xlsx')
            rejected('stale_excel_edit_conflict',lambda:svc.preview_return(bid,conflicting,expected_hash=after['current_hash']))
            # Changing a previously confirmed price unit must not relabel the old price.
            unit_upload=edit(upload,[(sheet,'R2','text','盒')],temp/'unit-change.xlsx')
            pu=svc.preview_return(bid,upload,expected_hash=after['current_hash'],field_proposals=[{
                'sheet':sheet,'cell':'R2','value':{'type':'text','value':'盒'},'message_ref':'SYNTHETIC explicit unit correction'}])
            up=svc.prepare_confirmation(pu['preview_id'],scope([target('R')],[target('R')]))
            svc.commit(up['plan_id'],confirmed_hash=up['plan_id'],explicit_confirmation=True,reference='SYNTHETIC unit change')
            changed=svc.read_current(bid);cx=next(x for x in changed['purchase_unit_contexts'] if x['row_id']==row2(changed,'G')['row_id'])
            ok('unit_change_invalidates_minimum_price_context',not cx['original_unit_confirmed'] and not cx['minimum_unit_price_confirmed'] and not row2(changed,'G')['confirmed'])
            fresh=svc.preview_return(bid,unit_upload,expected_hash=changed['current_hash'])
            same_price=svc.prepare_confirmation(fresh['preview_id'],scope(confirm=[target('G')]))
            svc.commit(same_price['plan_id'],confirmed_hash=same_price['plan_id'],explicit_confirmation=True,reference='SYNTHETIC same price explicitly reconfirmed per box')
            changed=svc.read_current(bid);cx=next(x for x in changed['purchase_unit_contexts'] if x['row_id']==row2(changed,'G')['row_id'])
            ok('same_price_can_be_reconfirmed_with_new_original_unit',cx['original_unit_confirmed'] and not cx['minimum_unit_price_confirmed'] and row2(changed,'G')['value']['value']=='12.3456')
            badqty=edit(unit_upload,[(sheet,'Q3','number','-5')],temp/'invalid-qty.xlsx')
            pq=svc.preview_return(bid,badqty,expected_hash=changed['current_hash'])
            ok('invalid_qty_preview_keeps_pending',pq['proposals'][target('Q',3)]['needs_further_confirmation'])
            rejected('invalid_qty_not_confirmable',lambda:svc.prepare_confirmation(pq['preview_id'],scope([target('Q',3)],[target('Q',3)])))
            pending=svc.prepare_confirmation(pq['preview_id'],scope([target('Q',3)]))
            svc.commit(pending['plan_id'],confirmed_hash=pending['plan_id'],explicit_confirmation=True,reference='SYNTHETIC pending only')
            latest=svc.read_current(bid)
            ok('invalid_qty_can_save_pending_without_arrival_fallback',latest['fields'][target('Q',3)]['status']=='saved_pending' and not latest['fields'][target('Q',3)]['confirmed'])
            ok('history_is_append_only',len(svc.history(bid))==5 and latest['revision']==4)
            ok('all_stages_and_formal_gates_remain_closed',not latest['can_enter_b'] and not latest['formal_output'] and not latest['phase2_implemented'] and not latest['phase3_implemented'])
        ok('actual_candidate_store_untouched',all(digest(Path(p))==h for p,h in livefiles.items()) and live.read_current(m['batch_id'])['current_hash']==before['current_hash'])
        save(out/'technical/roundtrip-test-results.json',{'checks':checks,'checks_passed':len(checks),'real_batch_rows':1275,'test_return_and_confirmation':'synthetic_in_disposable_clone',
            'actual_human_return_received':False,'actual_business_confirmation':False,'business_loop_passed':False,'forbidden_calculation_calls':0,'live_revision':0})

if __name__=='__main__':unittest.main()
