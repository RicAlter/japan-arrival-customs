import os,sys,tempfile,shutil,unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from separated.support import bootstrap,load,save,digest,check_hashes
bootstrap()
from separated.query import classify,number
from separated.service import Service,Base
from a_confirm.service import Service as Frozen

class PureTests(unittest.TestCase):
    def test_literal_difference_is_only_pending(self):
        self.assertEqual(classify(3,1),'原数值不同／单位待核')
        self.assertEqual(classify(3,3),'原数值相同／单位待核')
    def test_missing_purchase_is_not_filled_with_arrival(self):
        self.assertEqual(classify(None,99),'采购数量来源待核')
        self.assertEqual(classify(None,99,True),'重复来源未分配')
    def test_numeric_guard(self):
        for n in [None,'NaN','Infinity',True]:self.assertIsNone(number(n))
    def test_frozen_transaction_code_is_reused(self):
        self.assertEqual(Base.commit.__code__,Frozen.commit.__code__)
        self.assertEqual(Base.history.__code__,Frozen.history.__code__)

@unittest.skipUnless(os.environ.get('SEPARATED_WORKFLOW'),'provide a local real candidate workflow')
class RealSample(unittest.TestCase):
    def test_main_and_sidecars_and_synthetic_roundtrip(self):
        m=load(os.environ['SEPARATED_WORKFLOW']);out=Path(os.environ['SEPARATED_WORKFLOW']).parent
        plan=load(out/'technical/authoring-plan.json');old=load(m['prior_workflow']);checks=[]
        from native_copy.support import snapshot_root
        from native_copy.ooxml import parts,sheet_member
        from openpyxl import load_workbook
        def ok(name,condition):
            self.assertTrue(condition,name);checks.append({'test':name,'passed':True});print('PASS',name,flush=True)
        def reject(name,call):
            try:call()
            except ValueError:ok(name,True);return
            self.fail(name)
        oldparts=parts(Path(old['issued_file']).read_bytes());newparts=parts(Path(m['issued_file']).read_bytes());sheet=plan['sheet'];member=sheet_member(oldparts,sheet)
        ok('all_weight_styles_links_and_unrelated_parts_identical',all(oldparts[k]==newparts[k] for k in oldparts if k not in {member,'docProps/custom.xml'}))
        main=load_workbook(m['business_file']);s=main[sheet]
        ok('main_18_columns_without_three_procurement_helpers',s.max_column==18 and s['Q1'].value=='AI参考品类' and s['R1'].value=='AI参考材质')
        ok('human_material_and_reference_fields_remain_separate',not s['N2'].protection.locked and s['Q2'].protection.locked and s['R2'].protection.locked)
        ok('source_filter_and_box_unchanged',s.auto_filter.ref=='B1:R1313' and s['H2'].value is None and s['J2'].protection.locked)
        main.close()
        q=load_workbook(m['purchase_query_file']);qs=q.active;rows=plan['query']['rows']
        ok('query_all_1275_rows',qs.max_row-4==1275)
        ok('all_jan_exact_text',all(qs['B'+str(i+5)].value==r[1] and qs['B'+str(i+5)].data_type=='s' for i,r in enumerate(rows)))
        ok('independent_purchase_qty_blank_stays_blank',sum(qs['G'+str(i+5)].value is None for i in range(1275))==93)
        ok('all_purchase_quantity_and_arrival_values_preserved',all((qs['G'+str(i+5)].value is None if r[6] is None else Decimal(str(qs['G'+str(i+5)].value))==Decimal(str(r[6]))) and Decimal(str(qs['H'+str(i+5)].value))==Decimal(str(r[7])) for i,r in enumerate(rows)))
        ok('procurement_price_original_precision',all(r[5] is None or Decimal(str(qs['F'+str(i+5)].value))==Decimal(str(r[5])) for i,r in enumerate(rows)))
        q.close();d=load_workbook(m['quantity_check_file']);a,b=d.worksheets
        ok('80_literal_differences_and_93_source_pending',a.max_row-4==80 and b.max_row-4==93)
        ok('quantity_findings_not_approved_wrong_qty',plan['query']['counts']['confirmed_business_mismatches'] is None and '暂不判定错数' in a['A2'].value)
        ok('no_hidden_purchase_quantity_total_or_unit_conversion',plan['query']['purchase_quantity_sum'] is None and not plan['query']['unit_conversion_executed'])
        d.close()
        cached=load_workbook(m['quantity_check_file'],data_only=True)
        ok('all_difference_formula_caches_match_raw_values',all(Decimal(str(row[8].value))==Decimal(str(row[7].value))-Decimal(str(row[6].value)) for row in cached.worksheets[0].iter_rows(min_row=5)))
        cached.close()
        for file in [m['purchase_query_file'],m['quantity_check_file']]:
            book=load_workbook(file);ok('no_formula_error_'+Path(file).stem,not any(c.data_type=='e' for s in book for row in s for c in row));book.close()
        live=Service(m['a03_root']);before=live.read_current(m['batch_id']);protected={str(p):digest(p) for p in Path(m['a03_root']).rglob('*') if p.is_file()}
        import importlib.util
        helper=Path(__file__).resolve().parents[2]/'a-stage-first-phase/tests/test_roundtrip.py'
        spec=importlib.util.spec_from_file_location('old_technical_edit_helper',helper);fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)
        from native22 import pricing
        fail=lambda *a,**k:(_ for _ in ()).throw(AssertionError('forbidden'))
        with tempfile.TemporaryDirectory(prefix='purchase-layout-') as tmp,patch.object(pricing,'calculate',fail),patch.object(pricing,'analyze',fail),patch.object(pricing,'formula_plan',fail):
            tmp=Path(tmp);clone=tmp/'state';shutil.copytree(snapshot_root(Path(m['a03_root'])),snapshot_root(clone));svc=Service(clone);bid=m['batch_id'];v=svc.read_current(bid)
            unchanged=svc.preview_return(bid,m['issued_file'],expected_hash=v['current_hash']);ok('new_main_return_recognized',unchanged['modified_cells']==0)
            reject('old_21_column_version_rejected',lambda:svc.preview_return(bid,old['issued_file'],expected_hash=v['current_hash']))
            reject('query_is_not_a_main_confirmation_return',lambda:svc.preview_return(bid,m['purchase_query_file'],expected_hash=v['current_hash']))
            target=lambda c:sheet+'!'+c+'2'
            upload=fx.edit(m['issued_file'],[(sheet,'E2','text','SYNTHETIC layout name'),(sheet,'G2','number','123.4567')],tmp/'synthetic.xlsx')
            p=svc.preview_return(bid,upload,expected_hash=v['current_hash']);ok('editable_name_and_original_price_preview',p['modified_cells']==2)
            selection={'save_changes':[target('E'),target('G')],'confirm_fields':[target('E')],'adopt_candidates':[],'evidence':{}}
            pending=svc.prepare_confirmation(p['preview_id'],selection)
            reject('unit_unknown_price_cannot_confirm',lambda:svc.prepare_confirmation(p['preview_id'],{**selection,'confirm_fields':[target('E'),target('G')]}))
            for label,sh,c,kind,val in [('qty',sheet,'J2','number',999),('ai',sheet,'R507','text','SYNTHETIC'),('subtotal',sheet,'L2','formula','J2*K2+1'),('weight','重さとサイズ','B2','number',999)]:
                bad=fx.edit(m['issued_file'],[(sh,c,kind,val)],tmp/(label+'.xlsx'));reject('protected_'+label,lambda bad=bad:svc.preview_return(bid,bad,expected_hash=v['current_hash']))
            receipt=svc.commit(pending['plan_id'],confirmed_hash=pending['plan_id'],explicit_confirmation=True,reference='SYNTHETIC TECHNICAL TEST / NOT REAL HUMAN CONFIRMATION')
            after=svc.read_current(bid);ok('name_saved_price_pending_without_extra_main_columns',after['revision']==1 and after['fields'][target('E')]['confirmed'] and after['fields'][target('G')]['status']=='saved_pending')
            again=svc.commit(pending['plan_id'],confirmed_hash=pending['plan_id'],explicit_confirmation=True,reference='SYNTHETIC duplicate');ok('duplicate_save_idempotent',again['replayed'])
            p2=svc.preview_return(bid,upload,expected_hash=after['current_hash'])
            proof={'source_ref':'SYNTHETIC independently verified original purchase unit','unit':'盒'}
            plan2=svc.prepare_confirmation(p2['preview_id'],{'save_changes':[],'confirm_fields':[target('G')],'adopt_candidates':[],'evidence':{target('G'):proof}})
            svc.commit(plan2['plan_id'],confirmed_hash=plan2['plan_id'],explicit_confirmation=True,reference='SYNTHETIC explicit unit outside main')
            end=svc.read_current(bid);ctx=next(r for r in end['purchase_unit_contexts'] if r['row_id']==end['fields'][target('G')]['row_id'])
            ok('separate_unit_evidence_preserves_original_unit_semantics',ctx['original_unit_confirmed'] and not ctx['minimum_unit_price_confirmed'])
            ok('history_and_formal_gates_preserved',len(svc.history(bid))==3 and not end['can_enter_b'] and not end['formal_output'])
        check_hashes(protected);ok('actual_candidate_unchanged_and_unconfirmed',live.read_current(m['batch_id'])['current_hash']==before['current_hash'] and before['confirmed_field_count']==0)
        save(out/'technical/test-results.json',{'checks':checks,'checks_passed':len(checks),'synthetic_return_only':True,'actual_human_confirmation':False,'live_revision':0,'formal_output':False})

if __name__=='__main__':unittest.main()
