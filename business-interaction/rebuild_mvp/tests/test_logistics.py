import copy,json,sqlite3,subprocess,sys,unittest,zipfile
from pathlib import Path
from fractions import Fraction as F
from unittest.mock import patch
from contextlib import closing
from xml.etree import ElementTree as ET
import test_pricing as PricingTest
from test_enrichment import book
from rebuild_mvp.service import handle,digest
from rebuild_mvp.logistics_math import expand,analyse_group,inventory,associate,reconcile,frac
from rebuild_mvp.logistics_sources import carton_cell,WeightEvidence,item_fact
from rebuild_mvp.logistics_conversion import read_logistics_source
from rebuild_mvp.xlsxio import read_book,Q

WH=['箱番','重さ','カートン個数','合計重量（KGS)','容積横(CM)','容積幅(CM)','容積高(CM)','容積重量（Ｍ3）']


def group(label='A1-3',count='3',weight='12',unit='4',**kw):
    return analyse_group({'id':label,'row':2,'sheet':'重さ','carton_raw':label,'raw':{'count':count,'total_weight':weight,'unit_weight':unit},'weight_unit':'KG','issues':[],**kw})


def item(label,row='r1'):
    return {'row_id':row,'row':2,'carton_raw':label,'scope':{'code':'SKU'},'issues':[]}


def run_math(items,groups,coverage='complete',source_issues=()):
    gs,index,total=inventory(groups,source_issues)
    rows=[associate(x,gs,index)for x in items]
    return rows,gs,reconcile(rows,gs,index,total,coverage,source_issues)


class LogisticsMath(unittest.TestCase):
    def test_bounded_prefix_and_leading_zero_range(self):self.assertEqual(expand('ZC001-003'),['ZC1','ZC2','ZC3'])
    def test_list_and_multiple_ranges(self):self.assertEqual(expand(' A01-A02, A4;B1、B3～4'),['A1','A2','A4','B1','B3','B4'])
    def test_fullwidth_normalization(self):self.assertEqual(expand('Ａ０１－０２'),['A1','A2'])
    def test_invalid_carton_is_not_partially_extracted(self):
        for value in ['A3-A1','A1-B3','0','A0','1.5','A1/A2','A1,,A2','箱号不明','A1 + 2',None,'']:
            with self.subTest(value=value),self.assertRaises(ValueError):expand(value)
    def test_overlap_inside_label_rejected(self):
        for value in ['A1,A01','A1-3,A2','1-2,2-3']:
            with self.assertRaises(ValueError):expand(value)
    def test_range_bound_and_list_bound(self):
        for value in ['A1-10001','A1-6000,A6001-12000']:
            with self.assertRaises(ValueError):expand(value)
    def test_same_carton_three_items_counted_once(self):
        rows,_,t=run_math([item('A1',str(i))for i in range(3)],[group('A1','1','4','4')]);self.assertEqual(t['required_unique_cartons'],1);self.assertEqual(frac(t['linked_weight_kg']['value']),4);self.assertTrue(t['linked_weight_kg']['complete']);self.assertFalse(any(r['weight_allocated_to_product']for r in rows))
    def test_same_sku_different_shipments_retained(self):
        rows,_,t=run_math([item('A1','one'),item('A2','two')],[group('A1-2','2','8','4')]);self.assertEqual(len(rows),2);self.assertEqual(frac(t['linked_weight_kg']['value']),8)
    def test_group_total_no_even_division(self):
        rows,gs,t=run_math([item('A1')],[group(unit='')],coverage='partial');self.assertIsNone(t['linked_weight_kg']['value']);self.assertEqual(frac(gs[0]['total_weight_kg']),12);self.assertFalse(t['linked_weight_kg']['complete'])
    def test_whole_group_without_per_carton_observation(self):
        _,_,t=run_math([item('A1-3')],[group(unit='')]);self.assertEqual(frac(t['linked_weight_kg']['value']),12);self.assertTrue(t['linked_weight_kg']['complete'])
    def test_subset_only_with_explicit_unit_weight(self):
        _,_,t=run_math([item('A1,A3')],[group()],coverage='partial');self.assertEqual(frac(t['linked_weight_kg']['value']),8);self.assertEqual(t['weight_contributions'][0]['basis'],'explicit_per_carton_observation')
    def test_overlap_excludes_whole_affected_groups(self):
        _,gs,t=run_math([item('A1-3'),item('B1')],[group('A1-2','2','8','4'),group('A2-3','2','8','4'),group('B1','1','5','5')]);self.assertEqual(t['inventory']['duplicate_cartons'],['A2']);self.assertEqual(frac(t['linked_weight_kg']['value']),5);self.assertFalse(t['linked_weight_kg']['complete']);self.assertEqual(gs[0]['field_states']['weight'],'conflict')
    def test_count_mismatch_is_local(self):
        _,_,t=run_math([item('A1-3'),item('B1')],[group(count='4'),group('B1','1','5','5')]);self.assertEqual(frac(t['linked_weight_kg']['value']),5)
    def test_negative_missing_nonfinite_weight_not_zero(self):
        for v in ['-1','','NaN','Infinity','#N/A',True,'0']:
            with self.subTest(v=v):self.assertNotIn(group(weight=v)['field_states']['weight'],{'source_checked','derived'})
    def test_invalid_count_not_inferred_from_range(self):
        for v in ['','0','-1','2.5','NaN',True]:
            g=group(dimension_unit='CM',raw={'count':v,'total_weight':'12','unit_weight':'4','width':'10','height':'20','depth':'30'})
            self.assertEqual(g['field_states']['count'],'pending');self.assertEqual(g['field_states']['volume'],'pending')
    def test_existing_total_conflict_retained(self):
        g=group(weight='13');self.assertEqual(frac(g['total_weight_kg']),13);self.assertEqual(g['raw']['total_weight'],'13');self.assertEqual(g['field_states']['weight'],'conflict')
    def test_grams_explicit_conversion(self):
        g=group(weight='12000',unit='4000',weight_unit='G');self.assertEqual(frac(g['total_weight_kg']),12)
    def test_volume_is_cubic_metres_not_chargeable_weight(self):
        g=group(dimension_unit='CM',raw={'count':'3','total_weight':'12','unit_weight':'4','width':'10','height':'20','depth':'30','volume':'0.018'});self.assertEqual(frac(g['volume_m3']),F('0.018'));self.assertEqual(frac(g['total_weight_kg']),12)
    def test_volume_conflict_does_not_destroy_weight(self):
        g=group(dimension_unit='CM',raw={'count':'3','total_weight':'12','unit_weight':'4','width':'10','height':'20','depth':'30','volume':'9'});self.assertEqual(g['field_states']['volume'],'conflict');self.assertEqual(g['field_states']['weight'],'source_checked')
    def test_missing_weight_does_not_destroy_carton_association(self):
        rows,_,t=run_math([item('A1-3')],[group(weight='',unit='')]);self.assertEqual(rows[0]['cartons'],['A1','A2','A3']);self.assertEqual(rows[0]['links'][0]['state'],'source_checked');self.assertEqual(t['inventory']['count']['value'],3)
    def test_missing_carton_other_rows_continue(self):
        rows,_,t=run_math([item('A1'),item('Z9')],[group()]);self.assertEqual(t['missing_cartons'],['Z9']);self.assertEqual(frac(t['linked_weight_kg']['value']),4)
    def test_partial_and_complete_inventory_coverage_separate(self):
        _,_,a=run_math([item('A1')],[group()],coverage='partial');_,_,b=run_math([item('A1')],[group()]);self.assertFalse(a['issues']);self.assertTrue(b['issues']);self.assertEqual(a['inventory']['count']['value'],3);self.assertEqual(a['required_unique_cartons'],1)
    def test_range_does_not_distribute_item_quantity(self):
        rows,_,_=run_math([item('A1-3')],[group()]);self.assertEqual(rows[0]['association'],'within_carton_set_unallocated');self.assertFalse(rows[0]['quantities_allocated'])
    def test_invalid_item_identity_prevents_complete_total(self):
        _,_,t=run_math([item('A1'),item('unknown')],[group()]);self.assertFalse(t['linked_weight_kg']['complete'])
    def test_math_inputs_not_mutated(self):
        inputs=[[item('A1')],[group()]];before=copy.deepcopy(inputs);run_math(*inputs);self.assertEqual(inputs,before)
    def test_carton_formula_does_not_become_identity(self):
        g=group(issues=[{'code':'WEIGHT_FORMULA_UNSUPPORTED','field':'identity'}]);self.assertEqual(g['field_states']['identity'],'pending')
    def test_unverified_unit_weight_does_not_conflict_with_independent_total(self):
        g=group(unit='99',issues=[{'code':'WEIGHT_FORMULA_UNSUPPORTED','field':'unit_weight'}]);self.assertEqual(g['field_states']['weight'],'source_checked');self.assertEqual(g['field_states']['unit_weight'],'pending')
    def test_merged_cell_only_inherits_within_declared_merge(self):
        sheet={'rows':[{'row':2,'values':{'A':'A1-3'},'formulas':{}},{'row':3,'values':{},'formulas':{}},{'row':4,'values':{},'formulas':{}}],'merges':['A2:A3']}
        self.assertEqual(carton_cell(sheet,3)[0],'A1-3');self.assertEqual(carton_cell(sheet,4)[0],'');self.assertEqual(carton_cell(sheet,3)[1]['source_row'],2)
    def test_excel_boolean_carton_is_not_numeric_box_one(self):
        sheet={'rows':[{'row':2,'values':{'A':'1'},'types':{'A':'b'},'formulas':{}}],'merges':[]}
        q={'row_id':'r1','row':2,'sheet':'invoice','scope':{'carton':'1'}};fact=item_fact(q,{},sheet,{'path':'test','sha256':'test'})
        rows,_,_=run_math([fact],[group('1','1','4','4')]);self.assertFalse(rows[0]['cartons']);self.assertTrue(rows[0]['issues'])


class LogisticsEntry(unittest.TestCase):
    def setUp(self):
        f=PricingTest.PricingEntry('test_entry_fills_only_blank_I');f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.root=f.root
        self.price,self.price_contract=f.result();self.quantity=self.price_contract['quantity_source']
        self.source=self.root/'weights.xlsx';self.records=[['箱1','2.5','1','2.5','10','20','30','0.006']];self.make_weight()
        self.binding=self.root/'weight-binding.json'
        self.data={'schema':'arrival-carton-weight-evidence/1','batch_id':'B','quantity_source_sha256':self.quantity['sha256'],'pricing_source_sha256':self.price['pricing_source']['sha256'],
                   'sources':[{'source_id':'weights','path':str(self.source),'sha256':digest(self.source),'role':'japanese_batch','version':'test-v1'}],
                   'sheet':'invoice (計算)','header_row':1,'detail_rows':[2,2],'summary_rows':[],'weight_unit':'KG','dimension_unit':'CM','coverage':'complete',
                   'columns':{k:{'column':chr(65+i),'header':WH[i]}for i,k in enumerate(['carton','unit_weight','count','total_weight','width','height','depth','volume'])}}
        self.write();self.req={'action':'prepare','mode':'carton_weight','batch_id':'B','quantity_source':self.quantity,'pricing_source':self.price['pricing_source'],'logistics_binding':str(self.binding),'output':str(self.root/'logistics')}
    def make_weight(self):book(self.source,headers=WH,records=self.records)
    def write(self):self.binding.write_text(json.dumps(self.data,ensure_ascii=False),encoding='utf8')
    def rebind(self):self.data['sources'][0]['sha256']=digest(self.source);self.write()
    def result(self):
        r=handle(self.req);self.assertEqual(r.get('step'),'exported',r);return r,read_logistics_source(r['logistics_source'])
    def formula(self,cell,text,cache):
        with zipfile.ZipFile(self.source)as z:parts={n:z.read(n)for n in z.namelist()}
        tree=ET.fromstring(parts['xl/worksheets/sheet1.xml']);c=next(c for c in tree.iter(Q+'c')if c.get('r')==cell);c.attrib.pop('t',None);c[:]=[];ET.SubElement(c,Q+'f').text=text
        if cache is not None:ET.SubElement(c,Q+'v').text=cache
        parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
        with zipfile.ZipFile(self.source,'w')as z:
            for n,p in parts.items():z.writestr(n,p)
        self.rebind()
    def boolean_cell(self,address):
        with zipfile.ZipFile(self.source)as z:parts={n:z.read(n)for n in z.namelist()}
        tree=ET.fromstring(parts['xl/worksheets/sheet1.xml']);c=next(c for c in tree.iter(Q+'c')if c.get('r')==address);c.set('t','b');c[:]=[];ET.SubElement(c,Q+'v').text='1'
        parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
        with zipfile.ZipFile(self.source,'w')as z:
            for n,p in parts.items():z.writestr(n,p)
        self.rebind()
    def test_unified_entry_uses_both_saved_results(self):
        r,d=self.result();self.assertEqual(d['quantity_source'],self.quantity);self.assertEqual(d['pricing_source'],self.price['pricing_source']);self.assertEqual(len(d['rows']),3);self.assertEqual(d['totals']['required_unique_cartons'],1);self.assertEqual(frac(d['totals']['linked_weight_kg']['value']),F('2.5'));self.assertEqual(r['status'],'completed')
    def test_byte_exact_copy_including_I_and_manual_values(self):
        r,_=self.result();self.assertEqual(digest(r['business_files'][0]),digest(self.price['business_files'][0]));self.assertTrue(r['summary']['preservation']['byte_identical'])
    def test_upstream_jobs_and_sources_unchanged(self):
        tasks=[Path(self.price['pricing_source']['path']).parent,Path(self.quantity['path']).parent];files=[p/n for p in tasks for n in ['job.json','candidate.sqlite3']]+[self.source,Path(self.price['business_files'][0])];before={str(p):digest(p)for p in files};self.result();self.assertEqual(before,{str(p):digest(p)for p in files})
    def test_repeat_current_resume_identical(self):
        r,_=self.result()
        for req in [self.req,{'action':'current','task_root':self.req['output']},{'action':'resume','task_root':self.req['output']}]:self.assertEqual(handle(req),r)
    def test_quantity_or_price_pending_does_not_block_cartons(self):
        _,d=self.result();self.assertEqual(d['rows'][2]['status'],'completed');self.assertEqual(d['rows'][2]['scope']['qty'],'bad')
    def test_unit_not_assumed(self):
        self.data['weight_unit']='unknown';self.write();self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_declared_unit_cannot_contradict_actual_kg_header(self):
        self.data['weight_unit']='G';self.write();self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_declared_dimension_cannot_contradict_actual_cm_header(self):
        self.data['dimension_unit']='MM';self.write();self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_explicit_unit_weight_grams_cannot_mix_with_kg_total(self):
        header=WH.copy();header[1]='重さ(G)';book(self.source,headers=header,records=self.records);self.data['columns']['unit_weight']['header']=header[1];self.rebind();self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_original_header_mapping_checked(self):
        self.data['columns']['total_weight']['header']='not the real header';self.write();self.assertEqual(handle(self.req)['error']['code'],'FIELD_MAPPING_AMBIGUOUS')
    def test_cannot_source_weight_from_product_card(self):
        self.data['sources'][0]['role']='product_card';self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_FORBIDDEN')
    def test_opening_lineage_rejected(self):
        self.data['sources'][0]['opening_derived']=True;self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_FORBIDDEN')
    def test_binding_pins_quantity_and_price(self):
        for field in ['quantity_source_sha256','pricing_source_sha256']:
            before=self.data[field];self.data[field]='0'*64;self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_CHANGED');self.data[field]=before
    def test_different_valid_quantity_version_not_mixed_with_price(self):
        other=self.f.make_quantity('999');self.req['quantity_source']=other['quantity_source'];self.assertEqual(handle(self.req)['error']['code'],'SOURCE_CHANGED')
    def test_wrong_batch_rejected(self):
        self.data['batch_id']='other';self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_CHANGED')
    def test_output_cannot_contain_source(self):
        self.assertEqual(handle({**self.req,'output':str(self.root)})['error']['code'],'TASK_CONFLICT')
    def test_changed_code_refuses_resume(self):
        self.result()
        with patch('rebuild_mvp.logistics_conversion.code_version',return_value={}):self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED')
    def test_changed_source_refuses_resume(self):
        self.result();self.source.write_bytes(b'changed');self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED')
    def test_changed_pricing_delivery_refuses_resume(self):
        self.result();Path(self.price['business_files'][0]).write_bytes(b'changed');self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED')
    def test_changed_output_not_overwritten(self):
        r,_=self.result();Path(r['business_files'][0]).write_bytes(b'manual edit');self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED');self.assertEqual(Path(r['business_files'][0]).read_bytes(),b'manual edit')
    def test_tampered_contract_totals_even_with_new_file_hash(self):
        r,d=self.result();p=Path(r['logistics_source']['path']);d['totals']['required_unique_cartons']=999;p.write_text(json.dumps(d),encoding='utf8');ref={**r['logistics_source'],'sha256':digest(p)}
        with self.assertRaisesRegex(ValueError,'语义'):read_logistics_source(ref)
    def test_checkpoint_tampering_rejected(self):
        from rebuild_mvp.logistics_conversion import associate as original
        calls=0
        def fail(*args):
            nonlocal calls;calls+=1
            if calls==2:raise RuntimeError('interrupted')
            return original(*args)
        with patch('rebuild_mvp.logistics_conversion.associate',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        with closing(sqlite3.connect(Path(self.req['output'])/'candidate.sqlite3'))as db:
            db.execute("UPDATE logistics_rows SET payload='{}'");db.commit()
        self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'TASK_CONFLICT')
    def test_interrupted_item_rows_only_resume_remaining(self):
        from rebuild_mvp.logistics_conversion import associate as original
        calls=0
        def fail(*args):
            nonlocal calls;calls+=1
            if calls==2:raise RuntimeError('interrupted')
            return original(*args)
        with patch('rebuild_mvp.logistics_conversion.associate',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        with patch('rebuild_mvp.logistics_conversion.associate',wraps=original)as counted:
            r=handle({'action':'resume','task_root':self.req['output']});self.assertEqual(r['step'],'exported');self.assertEqual(counted.call_count,2)
    def test_interrupted_weight_groups_resume(self):
        self.records.append(['箱2','5','1','5','10','20','30','0.006']);self.make_weight();self.data['detail_rows']=[2,3];self.data['coverage']='partial';self.rebind()
        from rebuild_mvp.logistics_conversion import analyse_group as original
        calls=0
        def fail(*args):
            nonlocal calls;calls+=1
            if calls==2:raise RuntimeError('interrupted')
            return original(*args)
        with patch('rebuild_mvp.logistics_conversion.analyse_group',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        with patch('rebuild_mvp.logistics_conversion.analyse_group',wraps=original)as counted:
            self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['step'],'exported');self.assertEqual(counted.call_count,1)
    def test_interrupted_export_recovers_existing_identical_copy(self):
        from rebuild_mvp.logistics_conversion import copy_preserved as original
        def fail(*args):original(*args);raise RuntimeError('after copy')
        with patch('rebuild_mvp.logistics_conversion.copy_preserved',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        output=Path(self.req['output'])/'箱号与重量核对.xlsx';sha=digest(output);r=handle({'action':'resume','task_root':self.req['output']});self.assertEqual(r['step'],'exported');self.assertEqual(digest(output),sha)
    def test_formula_cache_matches_independent_inputs(self):
        self.formula('D2','B2*C2','2.5');_,d=self.result();self.assertEqual(d['groups'][0]['field_states']['weight'],'source_checked')
    def test_formula_cache_conflict_preserved_pending(self):
        self.formula('D2','B2*C2','9');r,d=self.result();self.assertEqual(d['groups'][0]['raw']['total_weight'],'9');self.assertFalse(d['totals']['linked_weight_kg']['complete']);self.assertTrue(r['summary']['preservation']['byte_identical'])
    def test_missing_formula_cache_not_filled(self):
        self.formula('D2','B2*C2',None);_,d=self.result();self.assertEqual(d['groups'][0]['field_states']['weight'],'pending')
    def test_unrecognized_formula_not_executed(self):
        self.formula('D2','SUM(B2:C2)','2.5');_,d=self.result();self.assertEqual(d['groups'][0]['field_states']['weight'],'pending')
    def test_excel_boolean_count_weight_cells_not_numbers(self):
        with zipfile.ZipFile(self.source)as z:parts={n:z.read(n)for n in z.namelist()}
        tree=ET.fromstring(parts['xl/worksheets/sheet1.xml'])
        for c in tree.iter(Q+'c'):
            if c.get('r')in {'C2','D2'}:c.set('t','b');c[:]=[];ET.SubElement(c,Q+'v').text='1'
        parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
        with zipfile.ZipFile(self.source,'w')as z:
            for n,p in parts.items():z.writestr(n,p)
        self.rebind();_,d=self.result();self.assertEqual(d['groups'][0]['field_states']['count'],'pending');self.assertEqual(d['groups'][0]['field_states']['weight'],'pending')
    def test_extra_numeric_rows_cannot_silently_disappear(self):
        self.records.append(['','3','1','3']);self.make_weight();self.rebind();r,d=self.result();self.assertEqual(r['status'],'partial');self.assertFalse(d['totals']['inventory']['weight_kg']['complete']);self.assertTrue(any(x['code']=='WEIGHT_UNCLASSIFIED_SOURCE_ROW'for x in d['totals']['issues']))
    def test_declared_non_numeric_note_preserved_out_of_totals(self):
        self.records.append(['','備考：']);self.make_weight();self.data['note_rows']=[3];self.rebind();r,d=self.result();self.assertEqual(r['status'],'completed');self.assertEqual(d['excluded_rows'][0]['reason'],'declared_non_numeric_note')
    def test_cannot_hide_weight_as_note(self):
        self.records.append(['','3','1','3']);self.make_weight();self.data['note_rows']=[3];self.rebind();self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_auxiliary_count_reference_not_misread_as_weight(self):
        self.records.extend([['','','1','2.5','','','','0.006'],['','','合計','1','ctn']]);self.make_weight();self.data['summary_rows']=[3];self.data['auxiliary_rows']=[{'row':4,'reason':'count_reference_only','references':{'D':'C3'}}];self.rebind();self.formula('D4','C3','1');_,d=self.result();self.assertEqual(len(d['groups']),1);self.assertEqual(frac(d['totals']['inventory']['weight_kg']['value']),F('2.5'))
        self.boolean_cell('D4');self.formula('D4','C3','1')
        with zipfile.ZipFile(self.source)as z:parts={n:z.read(n)for n in z.namelist()}
        tree=ET.fromstring(parts['xl/worksheets/sheet1.xml']);next(c for c in tree.iter(Q+'c')if c.get('r')=='D4').set('t','b');parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
        with zipfile.ZipFile(self.source,'w')as z:
            for n,p in parts.items():z.writestr(n,p)
        self.rebind()
        with self.assertRaisesRegex(ValueError,'辅助汇总缓存'):WeightEvidence(self.binding,'B',self.quantity,self.price['pricing_source']).group_facts()
    def test_arbitrary_numeric_row_not_auxiliary_summary(self):
        self.records.append(['','3','1','3']);self.make_weight();self.data['auxiliary_rows']=[{'row':3,'reason':'try_hide','references':{'D':'D2'}}];self.rebind();self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_summaries_excluded_and_reconciled(self):
        self.records.append(['','','1','2.5','','','','0.006']);self.make_weight();self.data['summary_rows']=[3];self.rebind();self.formula('D3','SUM(D2:D2)','2.5');_,d=self.result();self.assertEqual(len(d['groups']),1);self.assertEqual(len(d['excluded_rows']),1);self.assertTrue(all(x['state']=='source_checked'for x in d['summary_checks']))
    def test_wrong_summary_not_counted_as_extra_weight(self):
        self.records.append(['','','1','9','','','','0.006']);self.make_weight();self.data['summary_rows']=[3];self.rebind();_,d=self.result();self.assertEqual(frac(d['totals']['inventory']['weight_kg']['value']),F('2.5'));self.assertTrue(d['totals']['issues'])
        self.boolean_cell('C3');checks,issues=WeightEvidence(self.binding,'B',self.quantity,self.price['pricing_source']).audit_summaries(d['totals']['inventory']);self.assertTrue(any(x['field']=='count'and x['state']=='pending'for x in checks))
    def test_actual_run_py_dispatch(self):
        request=self.root/'logistics-request.json';request.write_text(json.dumps({'workflow':'rebuild_mvp_v1',**self.req}),encoding='utf8');entry=Path(__file__).resolve().parents[2]/'run.py';p=subprocess.run([sys.executable,'-X','utf8','-B',str(entry),'--request',str(request)],capture_output=True,text=True,encoding='utf8');self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertEqual(json.loads(p.stdout)['step'],'exported')
