import copy,json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from fractions import Fraction as F
from contextlib import closing
from unittest.mock import patch
from xml.etree import ElementTree as ET
import test_logistics as LogisticsTest
from test_enrichment import book
from rebuild_mvp.service import handle,digest,load_json,save_json
from rebuild_mvp.quantity_math import calculate as quantities,parse_layers,exact
from rebuild_mvp.pricing_math import calculate as prices
from rebuild_mvp.projection_math import project_row,weight_cells,totals,excel_number
from rebuild_mvp.projection_sources import TEMPLATE,FIELDS
from rebuild_mvp.dual_projection import read_pair_source
from rebuild_mvp.projection_export import author_plan,export_customs
from rebuild_mvp.xlsxio import Q,read_book


RENDERER={'node':r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe','node_modules':r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'}


def fake_author(plan,renderer,path):
    """Test transport only. Real bundled Artifact execution is verified separately."""
    from xml.sax.saxutils import escape
    rows=[]
    for n,values in enumerate(plan['matrix'],1):
        cells=[]
        for i,v in enumerate(values):
            col=chr(65+i)if i<26 else'A'+chr(65+i-26);addr=col+str(n);f=plan['formulas'].get(addr);children=('<f>'+escape(f)+'</f>')if f else''
            if v is None:cells.append(f'<c r="{addr}">{children}</c>')
            elif isinstance(v,(int,float)):cells.append(f'<c r="{addr}" t="n">{children}<v>{v}</v></c>')
            else:cells.append(f'<c r="{addr}" t="inlineStr">{children}<is><t>{escape(v)}</t></is></c>')
        rows.append(f'<row r="{n}">'+''.join(cells)+'</row>')
    ns=Q[1:-1];merges='<mergeCells>'+''.join(f'<mergeCell ref="{m}"/>'for m in plan['merges'])+'</mergeCells>'
    with zipfile.ZipFile(plan['output'],'w')as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{plan["sheet"]}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns}"><dimension ref="A1:AG{len(rows)}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews><sheetData>'+''.join(rows)+'</sheetData>'+merges+'</worksheet>')
        z.writestr('xl/theme/theme1.xml',load_json(TEMPLATE)['theme_xml'])


def simple_row(row=2,qty='60',code='001234567890123456'):
    quantity=quantities(qty,{'qty_unit':{'unit':'pack'},'relations':parse_layers('每包3枚，1盒12包'),'v_unit':'box'})
    q={'row_id':'r'+str(row),'row':row,'sheet':'原表','scope':{'carton':'A1','code':code,'origin':'JP'},'quantity':quantity}
    p={'pricing':prices({'quantity':qty,'price':'202','amount':str(F(qty)*202),'currency':'JPY'},quantity,{'duty_rate':{'value':0},'vat_rate':{'value':'.13'}})}
    l={'cartons':['A1'],'carton_raw':'A1'}
    w={q['row_id']:{'owned_cartons':['A1'],'count':exact(F(1)),'weight_kg':exact(F('2.5')),'unit_weight_kg':exact(F('2.5')),'basis':[],'repeated_cartons':[],'unresolved_cartons':[]}}
    return q,p,l,w


class ProjectionMath(unittest.TestCase):
    def make(self,**kw):
        q,p,l,w=simple_row(**kw);return project_row(q,p,l,{},[],w,[])
    def test_exact_quantity_and_rounding_amount(self):
        r=self.make();self.assertEqual(r['values']['F'],180);self.assertEqual(r['values']['G'],67);self.assertEqual(r['values']['P'],12060);self.assertEqual(r['rounding_difference']['value'],exact(F(-60)))
    def test_ids_are_text_with_leading_zeros(self):self.assertEqual(self.make()['values']['B'],'001234567890123456')
    def test_no_internal_or_japanese_name_fallback(self):self.assertNotIn('C',self.make()['values']);self.assertNotIn('I',self.make()['values'])
    def test_unit_unknown_only_price_is_blocked(self):
        q,p,l,w=simple_row();q['quantity']['raw_unit']=None;p['pricing']['results'].pop('piece_price_round0');r=project_row(q,p,l,{},[],w,[]);self.assertIn('F',r['values']);self.assertNotIn('P',r['values'])
    def test_conflicting_quantity_not_filled_from_excel(self):
        q,p,l,w=simple_row();q['quantity']['field_states']['piece']='conflict';r=project_row(q,p,l,{},[],w,[]);self.assertNotIn('F',r['values']);self.assertNotIn('P',r['values'])
    def test_original_row_positions_do_not_become_output_formula_refs(self):
        q,p,l,w=simple_row(row=47);r=project_row(q,p,l,{},[],w,[],2);self.assertIn('G2*F2',r['formula']);self.assertEqual(r['row'],47);self.assertEqual(r['output_row'],2)
    def test_zero_price_and_amount_stay_zero(self):
        q,p,l,w=simple_row();p['pricing']['results']['piece_price_round0']['value']=exact(F(0));p['pricing']['results']['rounded_line_amount']['value']=exact(F(0));r=project_row(q,p,l,{},[],w,[]);self.assertEqual(r['values']['G'],0);self.assertEqual(r['values']['P'],0)
    def test_money_currency_or_unit_mismatch_only_blocks_dependent_cells(self):
        q,p,l,w=simple_row();p['pricing']['results']['piece_price_round0']['currency']='CNY';r=project_row(q,p,l,{},[],w,[]);self.assertNotIn('G',r['values']);self.assertNotIn('P',r['values']);self.assertIn('F',r['values'])
    def test_nonwhole_boxes_not_invented_as_whole_boxes(self):
        r=self.make(qty='61');self.assertNotIn('E',r['values']);self.assertEqual(r['values']['F'],183)
    def test_amount_mismatch_not_balanced(self):
        q,p,l,w=simple_row();p['pricing']['results']['rounded_line_amount']['value']=exact(F(12345));r=project_row(q,p,l,{},[],w,[]);self.assertNotIn('P',r['values']);self.assertTrue(any(i['code']=='PRICE_QUANTITY_CONFLICT'for i in r['issues']))
    def test_unknown_blind_not_inferred(self):self.assertNotIn('K',self.make()['values'])
    def test_no_material_or_speculation_without_licensed_field(self):self.assertNotIn('M',self.make()['values']);self.assertNotIn('O',self.make()['values'])
    def test_private_text_in_public_source_not_published(self):
        q,p,l,w=simple_row();r=project_row(q,p,l,{'customs_name':{'value':'内部专属名称 公示','state':'reviewed_value'}},[],w,['内部专属名称']);self.assertNotIn('C',r['values'])
    def test_long_counts_and_nonterminating_values_not_rounded_silently(self):
        for value in [F(1,3),F(10**16),F(10**400+1,10)]:self.assertIsNone(excel_number(exact(value)))
        self.assertEqual(excel_number(exact(F('2.5'))),2.5)
    def test_totals_partial_and_no_fake_zero_for_empty_column(self):
        a=self.make();b=copy.deepcopy(a);b['values'].pop('P');t=totals([a,b]);self.assertFalse(t['P']['complete']);self.assertEqual(t['P']['excel_value'],12060);a['values'].pop('E');self.assertIsNone(totals([a])['E']['value'])
    def test_missing_carton_incomplete_count_not_healthy_zero(self):
        q,p,l,w=simple_row();l['cartons']=[];w[q['row_id']].update(owned_cartons=[],count=None,weight_kg=None,unit_weight_kg=None);r=project_row(q,p,l,{},[],w,[]);self.assertFalse(totals([r])['Q']['complete'])
    def test_weight_first_owner_not_each_product(self):
        data={'rows':[{'row_id':'a','cartons':['A1']},{'row_id':'b','cartons':['A1']}],
              'groups':[{'id':'g','field_states':{'unit_weight':'source_checked'},'unit_weight_kg':exact(F(4))}],
              'totals':{'weight_contributions':[{'group_id':'g','cartons':['A1'],'weight_kg':exact(F(4)),'basis':'group_total_once'}]}}
        w=weight_cells(data);self.assertEqual(w['a']['weight_kg'],exact(F(4)));self.assertIsNone(w['b']['count']);self.assertFalse(w['a']['allocated_to_product'])
    def test_split_group_without_explicit_unit_weight_not_guessed(self):
        data={'rows':[{'row_id':'a','cartons':['A1']},{'row_id':'b','cartons':['A2']}],
              'groups':[{'id':'g','field_states':{'unit_weight':'pending'},'unit_weight_kg':None}],
              'totals':{'weight_contributions':[{'group_id':'g','cartons':['A1','A2'],'weight_kg':exact(F(9)),'basis':'group_total_once'}]}}
        w=weight_cells(data);self.assertIsNone(w['a']['weight_kg']);self.assertIsNone(w['b']['weight_kg']);self.assertEqual(w['a']['count'],exact(F(1)))
    def test_split_group_with_source_unit_weight_is_exact(self):
        data={'rows':[{'row_id':'a','cartons':['A1']},{'row_id':'b','cartons':['A2']}],
              'groups':[{'id':'g','field_states':{'unit_weight':'source_checked'},'unit_weight_kg':exact(F('4.5'))}],
              'totals':{'weight_contributions':[{'group_id':'g','cartons':['A1','A2'],'weight_kg':exact(F(9)),'basis':'group_total_once'}]}}
        w=weight_cells(data);self.assertEqual(w['a']['weight_kg'],exact(F('4.5')));self.assertEqual(w['b']['weight_kg'],exact(F('4.5')))
    def test_projection_does_not_mutate_upstream(self):
        q,p,l,w=simple_row();original=copy.deepcopy([q,p,l,w]);project_row(q,p,l,{},[],w,[]);self.assertEqual([q,p,l,w],original)


class ProjectionEntry(unittest.TestCase):
    def setUp(self):
        f=LogisticsTest.LogisticsEntry('test_unified_entry_uses_both_saved_results');f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.root=f.root
        self.logistics,self.logistics_data=f.result();self.qref=f.quantity;self.pref=f.price['pricing_source'];self.lref=self.logistics['logistics_source'];q=load_json(self.qref['path']);self.q=q
        template=load_json(TEMPLATE);r2=q['upstream'];self.binding=self.root/'projection-evidence.json'
        self.data={'schema':'arrival-projection-evidence/1','batch_id':'B','quantity_source_sha256':self.qref['sha256'],'pricing_source_sha256':self.pref['sha256'],'logistics_source_sha256':self.lref['sha256'],'reviewed_source_sha256':r2['sha256'],
                   'internal_template':template['internal_id'],'customs_template':template['customs_id'],'template_sha256':digest(TEMPLATE),'sources':[],'rows':[]}
        self.write();self.req={'action':'prepare','mode':'dual_projection','batch_id':'B','review_task_root':r2['task_root'],'reviewed_source':{'path':r2['path'],'sha256':r2['sha256'],'role':'reviewed_basics','version':'operator-return-'+str(r2['revision'])},
                               'quantity_source':self.qref,'pricing_source':self.pref,'logistics_source':self.lref,'projection_binding':str(self.binding),'renderer':RENDERER,'output':str(self.root/'pair')}
        self.patch=patch('rebuild_mvp.projection_export.run_author',side_effect=fake_author);self.mock=self.patch.start();self.addCleanup(self.patch.stop)
    def write(self):save_json(self.binding,self.data)
    def result(self):
        r=handle(self.req);self.assertEqual(r.get('step'),'saved',r);return r,read_pair_source(r['pair_source'])
    def public(self,value='公开申报品名'):
        source=self.root/'customs-fields.xlsx';headers=['商品编码','海关申报品名','材质','品类','品牌','对外商品名','尺寸','对外规格','是否需要打标签','原规格']
        records=[[r['scope']['code'],value,'PVC','玩具','公开品牌','公开商品','10cm','公开规格','否',r['scope']['specification']]for r in self.q['rows']]
        book(source,headers=headers,records=records)
        self.data['sources']=[{'source_id':'pub','path':str(source),'sha256':digest(source),'role':'reviewed_basics','version':'test-public-v1'}]
        def ref(n,col,v,**kw):return {'source_id':'pub','sheet':'invoice (計算)','row':n,'column':col,'value':v,**kw}
        fields=[('customs_name','B',1),('material','C',2),('category','D',3),('brand','E',4),('public_name','F',5),('size','G',6),('specification','H',7),('label_required','I',8)]
        self.data['rows']=[]
        for i,row in enumerate(self.q['rows']):
            n=i+2;facts={}
            for field,col,index in fields:
                facts[field]={'value':records[i][index],'state':'reviewed_reference','evidence':[ref(n,col,records[i][index])],'header_evidence':[ref(1,col,headers[index])],
                              'identity_evidence':[ref(n,'A',row['scope']['code'],field='code'),ref(n,'J',row['scope']['specification'],field='specification')]}
            self.data['rows'].append({'sheet':row['sheet'],'row':row['row'],'scope':row['scope'],'fields':facts})
        self.write();return source
    def test_unified_entry_both_files_and_receipt(self):
        r,d=self.result();self.assertEqual(len(r['business_files']),2);self.assertEqual(r['status'],'draft_with_gaps');self.assertTrue(load_json(Path(self.req['output'])/'pair-save-receipt.json')['committed']);self.assertFalse(d['formal_output'])
    def test_internal_byte_identical_all_formulas_images_retained(self):
        r,_=self.result();self.assertEqual(digest(r['business_files'][0]),digest(self.logistics['business_files'][0]))
    def test_customs_recognized_33_columns_and_merges(self):
        r,_=self.result();s=read_book(r['business_files'][1])['sheets'][0];self.assertEqual(s['name'],'图片处理');self.assertEqual([s['rows'][0]['values'].get(chr(65+i)if i<26 else'A'+chr(65+i-26),'')for i in range(33)],[x or''for x in load_json(TEMPLATE)['customs']['headers']]);self.assertIn('T1:X1',s['merges'])
    def test_missing_name_material_remain_blank_not_inferred(self):
        _,d=self.result();self.assertTrue(all('C'not in r['values']and'M'not in r['values']for r in d['rows']))
    def test_upstream_price_and_quantity_issues_remain_explicit(self):
        r,d=self.result();self.assertTrue(any(i['kind']=='price'and i['field']=='purchase_ratio'for i in d['upstream_issues']));self.assertGreater(r['summary']['upstream_pending_records'],0)
    def test_public_header_coordinates_and_sku_positive(self):
        self.public();_,d=self.result();self.assertEqual(d['rows'][0]['values']['C'],'公开申报品名');self.assertEqual(d['rows'][0]['values']['M'],'PVC');self.assertFalse(d['rows'][0]['professional_approved'])
    def test_internal_name_not_licensed_as_customs_name(self):
        self.public();self.data['rows'][0]['fields']['customs_name']['header_evidence'][0].update(column='A',value='商品编码');self.write();_,d=self.result();self.assertNotIn('C',d['rows'][0]['values']);self.assertEqual(d['rows'][1]['values']['C'],'公开申报品名')
    def test_wrong_public_scope_only_blocks_that_row(self):
        self.public();self.data['rows'][0]['scope']['specification']='wrong';self.write();_,d=self.result();self.assertNotIn('C',d['rows'][0]['values']);self.assertIn('C',d['rows'][1]['values'])
    def test_same_code_other_sku_evidence_rejected(self):
        self.public();fact=self.data['rows'][0]['fields']['customs_name'];fact['evidence'][0]['row']=3;fact['identity_evidence']=[{**r,'row':3,'value':self.q['rows'][1]['scope']['specification']if r['field']=='specification'else r['value']}for r in fact['identity_evidence']];self.write();_,d=self.result();self.assertNotIn('C',d['rows'][0]['values'])
    def test_internal_text_in_licensed_public_field_suppressed(self):
        self.public('人工已保存');_,d=self.result();self.assertNotIn('C',d['rows'][0]['values'])
    def test_literal_formula_like_text_never_executes(self):
        self.public('=HYPERLINK("https://invalid.example")');r,d=self.result();s=read_book(r['business_files'][1])['sheets'][0]['rows'][1];self.assertNotIn('C',s['formulas']);self.assertEqual(s['values']['C'],'=HYPERLINK("https://invalid.example")')
    def test_no_internal_hidden_sheets_or_private_strings(self):
        r,_=self.result();b=read_book(r['business_files'][1]);self.assertEqual(len(b['sheets']),1)
        with zipfile.ZipFile(r['business_files'][1])as z:self.assertFalse(any('YD1'in z.read(n).decode('utf8',errors='ignore')for n in z.namelist()if n.endswith('.xml')))
    def test_sources_jobs_not_modified(self):
        paths=[Path(ref['path']).parent/n for ref in [self.qref,self.pref,self.lref]for n in ['job.json','candidate.sqlite3']]+[Path(self.req['reviewed_source']['path'])];before={str(p):digest(p)for p in paths};self.result();self.assertEqual(before,{str(p):digest(p)for p in paths})
    def test_repeated_prepare_current_resume_identical(self):
        r,_=self.result()
        for req in [self.req,{'action':'current','task_root':self.req['output']},{'action':'resume','task_root':self.req['output']}]:self.assertEqual(r,handle(req))
        self.assertEqual(self.mock.call_count,1)
    def test_weight_only_first_product_row(self):
        _,d=self.result();self.assertEqual(d['rows'][0]['values']['Q'],1);self.assertEqual(d['rows'][0]['values']['S'],2.5);self.assertNotIn('Q',d['rows'][1]['values']);self.assertNotIn('S',d['rows'][1]['values'])
    def test_input_weight_page_mismatch_reported_not_replaced(self):
        r,d=self.result();self.assertFalse(d['internal_audit']['weight_page_matches_r3_source']);self.assertEqual(digest(r['business_files'][0]),d['delivery']['sha256']);self.assertTrue(any(i['field']=='weight_page'for i in d['internal_issues']))
    def test_r2_version_mismatch_rejected(self):
        self.req['reviewed_source']['version']='operator-return-0';self.assertEqual(handle(self.req)['error']['code'],'SOURCE_CHANGED')
    def test_upstream_different_valid_quantity_rejected(self):
        other=self.f.f.make_quantity('999');self.req['quantity_source']=other['quantity_source'];self.assertEqual(handle(self.req)['error']['code'],'SOURCE_CHANGED')
    def test_evidence_version_mismatch_rejected(self):
        self.data['logistics_source_sha256']='0'*64;self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_CHANGED')
    def test_unrecognized_template_rejected(self):
        self.data['customs_template']='historical-test19';self.write();self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_opening_source_cannot_reenter(self):
        self.public();self.data['sources'][0]['opening_derived']=True;self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_FORBIDDEN')
    def test_historical_completed_reference_not_public_fact(self):
        self.public();self.data['sources'][0]['role']='completed_reference';self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_FORBIDDEN')
    def test_layout_only_workbook_cannot_reenter_as_reviewed_business(self):
        source=self.public();template=load_json(TEMPLATE);template['layout_only_source_shas']=[digest(source)]
        from rebuild_mvp.projection_sources import load_json as original
        with patch('rebuild_mvp.projection_sources.load_json',side_effect=lambda path:template if Path(path)==TEMPLATE else original(path)):
            self.assertEqual(handle(self.req)['error']['code'],'SOURCE_FORBIDDEN')
    def test_unknown_global_override_rejected(self):self.assertEqual(handle({**self.req,'force_approval':True})['error']['code'],'CONFIG_INVALID')
    def test_source_changed_resume_refused(self):
        self.result();self.binding.write_text('{}',encoding='utf8');self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED')
    def test_program_changed_resume_refused(self):
        self.result()
        with patch('rebuild_mvp.dual_projection.code_version',return_value={}):self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED')
    def test_upstream_delivery_changed_refused(self):
        self.result();Path(self.logistics['business_files'][0]).write_bytes(b'edited');self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED')
    def test_output_changed_never_overwritten(self):
        r,_=self.result();target=Path(r['business_files'][1]);target.write_bytes(b'manual changes');self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'SOURCE_CHANGED');self.assertEqual(target.read_bytes(),b'manual changes')
    def test_contract_semantics_tampering_detected(self):
        r,d=self.result();path=Path(r['pair_source']['path']);d['totals']['Q']['excel_value']=999;save_json(path,d)
        with self.assertRaisesRegex(ValueError,'语义'):read_pair_source({**r['pair_source'],'sha256':digest(path)})
    def test_incomplete_receipt_not_saved_pair(self):
        r,_=self.result();p=Path(self.req['output'])/'pair-save-receipt.json';d=load_json(p);d['committed']=False;save_json(p,d)
        with self.assertRaisesRegex(ValueError,'回执'):read_pair_source(r['pair_source'])
    def test_output_inside_old_task_forbidden(self):
        self.assertEqual(handle({**self.req,'output':str(Path(self.lref['path']).parent/'new-pair')})['error']['code'],'CONFIG_INVALID')
    def test_missing_runtime_not_install_or_fallback(self):
        self.req['renderer']={**RENDERER,'node':'not-present-node'};self.assertEqual(handle(self.req)['error']['code'],'CONFIG_INVALID')
    def test_interrupted_projection_rows_resume_only_remaining(self):
        from rebuild_mvp.dual_projection import project_row as original
        count=0
        def fail(*args):
            nonlocal count;count+=1
            if count==2:raise RuntimeError('interrupt')
            return original(*args)
        with patch('rebuild_mvp.dual_projection.project_row',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        with patch('rebuild_mvp.dual_projection.project_row',wraps=original)as called:
            self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['step'],'saved');self.assertEqual(called.call_count,2)
    def test_checkpoint_corruption_not_reused(self):
        with patch('rebuild_mvp.projection_export.run_author',side_effect=RuntimeError('interrupt')):self.assertEqual(handle(self.req)['status'],'failed')
        with closing(sqlite3.connect(Path(self.req['output'])/'candidate.sqlite3'))as db:db.execute("UPDATE projection_rows SET payload='{}'");db.commit()
        self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['error']['code'],'TASK_CONFLICT')
    def test_failure_after_first_file_not_published_as_pair(self):
        with patch('rebuild_mvp.projection_export.run_author',side_effect=RuntimeError('interrupt')):r=handle(self.req);self.assertEqual(r['status'],'failed');self.assertEqual(r['business_files'],[])
        current=handle({'action':'current','task_root':self.req['output']});self.assertEqual(current['business_files'],[]);self.assertIsNone(current['pair_source']);self.assertEqual(handle({'action':'resume','task_root':self.req['output']})['step'],'saved')
    def test_recover_after_both_exports_without_reauthoring(self):
        from rebuild_mvp.dual_projection import save_json as original
        def fail(path,value):
            if Path(path).name=='pair-results.json':raise RuntimeError('before receipt')
            return original(path,value)
        with patch('rebuild_mvp.dual_projection.save_json',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        count=self.mock.call_count;r=handle({'action':'resume','task_root':self.req['output']});self.assertEqual(r['step'],'saved');self.assertEqual(self.mock.call_count,count)
    def test_projection_not_restore_paused_image_downloads(self):
        with patch('rebuild_mvp.purchase_images.download',side_effect=AssertionError('must not download'),create=True):r,_=self.result();self.assertTrue(r['summary']['internal_audit']['original_page_preserved'])
    def test_unchanged_non_target_parts_and_xml_headers(self):
        r,_=self.result()
        with zipfile.ZipFile(r['business_files'][0])as a,zipfile.ZipFile(self.logistics['business_files'][0])as b:self.assertEqual({n:a.read(n)for n in a.namelist()},{n:b.read(n)for n in b.namelist()})
        with zipfile.ZipFile(r['business_files'][1])as z:
            self.assertNotIn(b'ns0:Types',z.read('[Content_Types].xml'))
            self.assertNotIn(b'ns0:Relationships',z.read('xl/_rels/workbook.xml.rels'))
            tree=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            code=next(c for c in tree.findall(Q+'sheetData/'+Q+'row/'+Q+'c')if c.get('r')=='B2')
            self.assertEqual(code.get('t'),'inlineStr');self.assertEqual(''.join(code.itertext()),self.q['rows'][0]['scope']['code'])
