import copy
import inspect
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from test_enrichment import book
from rebuild_mvp.quantity_math import calculate, parse_layers, exact, title_key
from rebuild_mvp.quantity_sources import Evidence, read_upstream, extract_reviewed
from rebuild_mvp.quantity_conversion import read_quantity_source
from rebuild_mvp.service import handle, digest, code_version
from rebuild_mvp.review_return import overlay
from rebuild_mvp.xlsxio import Q, read_book


def facts(unit='pack', layers='每包3枚，1盒12包', **extra):
    return {'qty_unit':{'unit':unit,'label':unit,'evidence':[{'test':'explicit'}]},
            'relations':parse_layers(layers),'v_unit':'box',**extra}


class QuantityMath(unittest.TestCase):
    def test_real_1010_arithmetic(self):
        r=calculate('60',facts())
        self.assertEqual(r['results']['piece'],exact(Fraction(180)))
        self.assertEqual(r['results']['box'],exact(Fraction(5)))
    def test_real_790_arithmetic(self):
        self.assertEqual(calculate('144',facts())['results']['box'],exact(Fraction(12)))
    def test_real_759_three_by_seventeen(self):
        r=calculate(13,facts('box','1包3枚，1盒17包'))
        self.assertEqual(r['results']['piece'],exact(Fraction(663)))
    def test_direct_box_does_not_invent_packet(self):
        r=calculate(60,facts('box','整盒10枚入'))
        self.assertEqual(r['results']['piece'],exact(Fraction(600)))
        self.assertNotIn('pack',r['results'])
    def test_single_item_needs_no_box(self):
        r=calculate(7,facts('piece',''))
        self.assertEqual(r['results']['piece'],exact(Fraction(7)))
        self.assertNotIn('box',r['results'])
    def test_set_is_not_box(self):
        r=calculate(3,facts('set','1套5枚',v_unit='set'))
        self.assertEqual(r['results']['piece'],exact(Fraction(15)))
        self.assertNotIn('box',r['results'])
    def test_carton_is_distinct(self):
        r=calculate(2,facts('carton','每运输箱4盒，1盒12包，每包3枚'))
        self.assertEqual(r['results']['piece'],exact(Fraction(288)))
    def test_partial_box_exact_and_remainder(self):
        r=calculate(61,facts())
        self.assertEqual(r['results']['box'],exact(Fraction(61,12)))
        self.assertEqual(r['remainder'],{'whole_boxes':'5','remaining_pieces':exact(Fraction(3))})
    def test_nonterminating_fraction_retained(self):
        r=calculate(1,facts('piece','每盒3枚'))
        self.assertEqual(r['results']['box'],exact(Fraction(1,3)))
    def test_bad_original_quantities(self):
        for q in ['',None,False,'NaN','Infinity',-1,0]:
            r=calculate(q,facts())
            self.assertNotIn('piece',r['results'])
    def test_fractional_original_requires_evidence(self):
        self.assertNotIn('piece',calculate('.5',facts('box'))['results'])
        self.assertEqual(calculate('.5',facts('box',allow_split_quantity=[{'ref':1}]))['results']['piece'],exact(Fraction(18)))
    def test_unknown_unit_no_guess(self):
        self.assertNotIn('piece',calculate(60,{'relations':parse_layers('1包3枚，1盒12包')})['results'])
    def test_quantity_observation_works_without_original_unit(self):
        r=calculate('60',{'relations':parse_layers('1盒36枚'),
                         'observations':{'total_pieces':{'value':'180','evidence':['X']}}})
        self.assertEqual(r['results']['box'],exact(Fraction(5)))
        self.assertIsNone(r['raw_unit'])
    def test_conflicting_graph_not_usable(self):
        r=calculate(1,facts('box','1盒10枚；1盒12枚'))
        self.assertNotIn('piece',r['results'])
        self.assertTrue(any(x['code']=='PACKAGING_CONFLICT' for x in r['issues']))
    def test_conflict_does_not_block_independent_component(self):
        r=calculate(7,facts('piece','每运输箱4盒；每运输箱5盒'))
        self.assertEqual(r['results']['piece'],exact(Fraction(7)))
    def test_conflicting_observations_not_bypassed(self):
        r=calculate(60,facts(observations={'total_pieces':{'value':'181'}}))
        self.assertNotIn('piece',r['results'])
    def test_manual_total_is_not_overwritten(self):
        r=calculate(60,facts(),{'X':'181'})
        self.assertEqual(r['field_states']['piece'],'conflict')
    def test_manual_v_conflict_removes_dependent_total(self):
        r=calculate(1,facts('box','1盒12枚'),{'V':'10'})
        self.assertNotIn('piece',r['results'])
    def test_varieties_suffix_and_accessories_not_packaging(self):
        for text in ['全24种','整盒158','本体1个、底座1个','2枚套组','价格比12','1盒12包']:
            self.assertFalse(any(x['inner']=='piece' for x in parse_layers(text)))
    def test_price_free_interface(self):
        self.assertNotIn('price',inspect.signature(calculate).parameters)
        self.assertEqual(calculate(60,facts()),calculate(60,{**facts(),'I':'999','price':'0'}))
    def test_title_normalization_is_fixed_and_version_preserving(self):
        self.assertEqual(title_key('模玩熊 商品 Vol.2 周边预定金'),title_key('商品 Vol.2 周边'))
        self.assertNotEqual(title_key('商品 Vol.2 周边'),title_key('商品 Vol.1 周边'))
    def test_independent_source_total_conflict_with_saved_count(self):
        f={'observations':{'total_pieces':{'value':'90'}},
           'observation_candidates':[{'field':'total_pieces','value':'600'}]}
        self.assertNotIn('piece',calculate(60,f)['results'])
    def test_math_does_not_mutate_source_facts(self):
        f=facts();before=copy.deepcopy(f);calculate(60,f);self.assertEqual(before,f)


class QuantityEntry(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.src=self.root/'original.xlsx'
        records=[]
        for code,q,spec,text in [('code','60','三枚包','每包3枚，1盒12包'),('code','2','五枚套','1套5枚'),('bad','bad','未知','全12种')]:
            values=['箱1','JP',code,'','','人工名称',spec,'','999','日文原文',q,'100','6000','','','','YD1','','',text]
            records.append(values)
        book(self.src,records=records)
        with zipfile.ZipFile(self.src) as z:parts={n:z.read(n) for n in z.namelist()}
        tree=ET.fromstring(parts['xl/worksheets/sheet1.xml'])
        for r in tree.find(Q+'sheetData'):
            for c in list(r):
                if c.get('r','').startswith('X') and r.get('r')!='1':r.remove(c)
        parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
        parts['xl/media/existing.png']=b'original-media-preserved'
        with zipfile.ZipFile(self.src,'w') as z:
            for n,data in parts.items():z.writestr(n,data)
        self.r2=self.root/'r2'
        initial=handle(dict(action='prepare',mode='review_return',batch_id='B',input_file=str(self.src),output=str(self.r2)))
        submitted=self.root/'return.xlsx';overlay(self.src,submitted,'invoice (計算)',{'F2':'人工已保存'})
        saved=handle(dict(action='resume',task_root=str(self.r2),submitted_file=str(submitted),expected_revision=0,expected_reference_sha256=initial['reference_sha256']))
        self.assertEqual(saved['status'],'saved',saved)
        self.ref=saved['reviewed_source'];self.binding=self.root/'quantity-evidence.json'
        upstream=read_upstream(self.r2,self.ref);rows=extract_reviewed(upstream)
        source={'source_id':'s','path':str(self.src),'sha256':digest(self.src),'role':'reviewed_basics','version':'test-source-v1'}
        bindingrows=[]
        for i,row in enumerate(rows):
            ref={'source_id':'s','sheet':row['sheet'],'row':row['row'],'column':'T','value':records[i][19]}
            record={'sheet':row['sheet'],'row':row['row'],'scope':row['scope'],
                    'packaging':[{'excerpt':records[i][19],'scope':'exact_sku','evidence':[ref]}]}
            if i<2:record.update(qty_unit={'unit':['pack','set'][i],'label':['包','套'][i],'basis':'explicit audited SKU quantity mapping','evidence':[ref]},v_unit=['box','set'][i])
            bindingrows.append(record)
        self.data={'schema':'arrival-quantity-evidence/1','sources':[source],'rows':bindingrows}
        self.write_binding();self.req=dict(action='prepare',mode='quantity_conversion',batch_id='B',review_task_root=str(self.r2),reviewed_source=self.ref,quantity_binding=str(self.binding),output=str(self.root/'quantity'))
    def write_binding(self):self.binding.write_text(json.dumps(self.data,ensure_ascii=False),encoding='utf8')
    def test_entry_and_following_stage_contract(self):
        before=digest(self.src);r=handle(self.req);self.assertEqual(r['step'],'exported',r)
        out=read_quantity_source(r['quantity_source']);self.assertEqual(out['rows'][0]['quantity']['results']['piece'],exact(Fraction(180)))
        self.assertEqual(out['rows'][1]['quantity']['results']['piece'],exact(Fraction(10)))
        self.assertNotIn('box',out['rows'][1]['quantity']['results'])
        self.assertEqual(r['status'],'partial');self.assertEqual(before,digest(self.src))
        bookout=read_book(r['business_files'][0]);values=bookout['sheets'][0]['rows'][1]['values']
        self.assertEqual((values['U'],values['V'],values['X']),('5','36','180'));self.assertEqual(values['I'],'999')
    def test_repeated_and_current_are_identical(self):
        a=handle(self.req);b=handle(self.req);c=handle(dict(action='current',task_root=self.req['output']))
        self.assertEqual(a,b);self.assertEqual(a,c)
    def test_upstream_database_read_only(self):
        files=[self.r2/'candidate.sqlite3',self.r2/'job.json',Path(self.ref['path'])]
        before={str(p):digest(p) for p in files};handle(self.req)
        self.assertEqual(before,{str(p):digest(p) for p in files})
    def test_malformed_same_code_records_not_merged(self):
        r=handle(self.req);rows=read_quantity_source(r['quantity_source'])['rows']
        self.assertNotEqual(rows[0]['row_id'],rows[1]['row_id'])
        self.assertEqual(rows[1]['quantity']['v_unit'],'set')
    def test_wrong_scope_is_row_local(self):
        self.data['rows'][0]['scope']['specification']='other';self.write_binding();r=handle(self.req)
        self.assertEqual(r['step'],'exported',r);rows=read_quantity_source(r['quantity_source'])['rows']
        self.assertNotIn('piece',rows[0]['quantity']['results']);self.assertIn('piece',rows[1]['quantity']['results'])
    def test_bad_coordinate_never_becomes_fact(self):
        self.data['rows'][0]['packaging'][0]['evidence'][0]['value']='invented';self.write_binding();r=handle(self.req)
        rows=read_quantity_source(r['quantity_source'])['rows'];self.assertNotIn('piece',rows[0]['quantity']['results'])
    def test_forbidden_lineage_rejected(self):
        self.data['sources'][0]['opening_derived']=True;self.write_binding();r=handle(self.req)
        self.assertEqual(r['error']['code'],'SOURCE_FORBIDDEN')
    def test_upstream_revision_change_rejected(self):
        r=handle(self.req);sub=self.root/'second.xlsx';overlay(self.ref['path'],sub,'invoice (計算)',{'F2':'第二次保存'})
        saved=handle(dict(action='resume',task_root=str(self.r2),submitted_file=str(sub),expected_revision=1,expected_reference_sha256=self.ref['sha256']))
        self.assertEqual(saved['status'],'saved')
        self.assertEqual(handle(dict(action='resume',task_root=self.req['output']))['error']['code'],'SOURCE_CHANGED')
        with self.assertRaises(ValueError):read_quantity_source(r['quantity_source'])
    def test_evidence_changed_rejected_on_current(self):
        handle(self.req);self.binding.write_text('{}',encoding='utf8')
        self.assertEqual(handle(dict(action='current',task_root=self.req['output']))['error']['code'],'SOURCE_CHANGED')
    def test_code_changed_rejected(self):
        handle(self.req)
        with patch('rebuild_mvp.quantity_conversion.code_version',return_value={'sha256':'changed'}):
            self.assertEqual(handle(dict(action='resume',task_root=self.req['output']))['error']['code'],'SOURCE_CHANGED')
    def test_interrupted_rows_resume(self):
        from rebuild_mvp.quantity_conversion import calculate as original
        count=0
        def fail(*args,**kw):
            nonlocal count
            count+=1
            if count==2:raise RuntimeError('injected process interruption')
            return original(*args,**kw)
        with patch('rebuild_mvp.quantity_conversion.calculate',side_effect=fail):r=handle(self.req)
        self.assertEqual(r['status'],'failed')
        self.assertEqual(handle(dict(action='current',task_root=self.req['output']))['status'],'failed')
        r=handle(dict(action='resume',task_root=self.req['output']));self.assertEqual(r['step'],'exported',r)
        with closing(sqlite3.connect(Path(self.req['output'])/'candidate.sqlite3')) as db:self.assertEqual(db.execute('select count(*) from quantity_rows').fetchone()[0],3)
    def test_interrupted_publication_recovers_without_overwrite(self):
        from rebuild_mvp.quantity_conversion import export as original
        def fail(*args):original(*args);raise RuntimeError('after export before job commit')
        with patch('rebuild_mvp.quantity_conversion.export',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        out=Path(self.req['output'])/'数量与包装换算.xlsx';before=digest(out)
        r=handle(dict(action='resume',task_root=self.req['output']));self.assertEqual(r['step'],'exported',r);self.assertEqual(before,digest(out))
    def test_tampered_checkpoint_rejected(self):
        from rebuild_mvp.quantity_conversion import export
        with patch('rebuild_mvp.quantity_conversion.export',side_effect=RuntimeError('stop')):handle(self.req)
        with closing(sqlite3.connect(Path(self.req['output'])/'candidate.sqlite3')) as db, db:db.execute("update quantity_rows set payload='{}'")
        self.assertEqual(handle(dict(action='resume',task_root=self.req['output']))['error']['code'],'TASK_CONFLICT')
    def test_target_formula_and_manual_values_preserved(self):
        pictured=self.root/'manual-formula.xlsx'
        with zipfile.ZipFile(self.ref['path']) as z:parts={n:z.read(n)for n in z.namelist()}
        tree=ET.fromstring(parts['xl/worksheets/sheet1.xml']);r=tree.find(Q+'sheetData')[1]
        for col,value in [('U','11'),('V','999')]:
            c=ET.SubElement(r,Q+'c',{'r':col+'2','t':'n'});ET.SubElement(c,Q+'v').text=value
        c=ET.SubElement(r,Q+'c',{'r':'X2'});ET.SubElement(c,Q+'f').text='K2*2';ET.SubElement(c,Q+'v').text='120'
        parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
        with zipfile.ZipFile(pictured,'w')as z:
            for n,data in parts.items():z.writestr(n,data)
        other=self.root/'other-r2';prepared=handle(dict(action='prepare',mode='review_return',batch_id='B',input_file=str(pictured),output=str(other)))
        saved=handle(dict(action='resume',task_root=str(other),submitted_file=str(pictured),expected_revision=0,expected_reference_sha256=prepared['reference_sha256']))
        req={**self.req,'review_task_root':str(other),'reviewed_source':saved['reviewed_source']}
        result=handle(req);self.assertEqual(result['step'],'exported',result)
        out=Path(result['business_files'][0]);before=read_book(out);row=before['sheets'][0]['rows'][1]
        self.assertEqual(row['formulas']['X'],'K2*2');self.assertEqual(row['values']['X'],'120')
        self.assertEqual((row['values']['U'],row['values']['V']),('11','999'))
        self.assertEqual(row['values']['F'],'人工已保存')
        with zipfile.ZipFile(out) as z:self.assertEqual(z.read('xl/media/existing.png'),b'original-media-preserved')
    def test_missing_r2_receipt_is_not_saved(self):
        with closing(sqlite3.connect(self.r2/'candidate.sqlite3')) as db, db:db.execute('delete from review_submissions')
        self.assertEqual(handle(self.req)['error']['code'],'INPUT_INVALID')
    def test_actual_run_py_entry(self):
        request=self.root/'request.json';request.write_text(json.dumps({'workflow':'rebuild_mvp_v1',**self.req}),encoding='utf8')
        run=Path(__file__).resolve().parents[2]/'run.py'
        process=subprocess.run([sys.executable,'-X','utf8','-B',str(run),'--request',str(request)],capture_output=True,text=True,encoding='utf8')
        self.assertEqual(process.returncode,0,process.stdout+process.stderr);self.assertEqual(json.loads(process.stdout)['step'],'exported')
    def test_unknown_config_and_wrong_batch_rejected(self):
        self.assertEqual(handle({**self.req,'tax_rate':'.13'})['error']['code'],'CONFIG_INVALID')
        self.assertEqual(handle({**self.req,'batch_id':'OTHER'})['error']['code'],'INPUT_INVALID')
    def test_product_card_mixed_group_not_applied_to_single(self):
        card=self.root/'card.json';card.write_text(json.dumps({'sheets':[{'name':'卡','data':[['商品名称','产品配件'],['混合吧唧立牌','整盒8枚入']]}]},ensure_ascii=False),encoding='utf8')
        self.data['sources'].append({'source_id':'card','path':str(card),'sha256':digest(card),'version':'v1','role':'product_card'})
        row=self.data['rows'][0];row['scope']['name']='混合吧唧立牌';row['scope']['specification']='立牌角色A'
        row['packaging']=[{'scope':'exact_sku','excerpt':'整盒8枚入','evidence':[{'source_id':'card','sheet':'卡','row':2,'column':'B','value':'整盒8枚入'}],
                           'identity_evidence':[{'source_id':'card','sheet':'卡','row':2,'column':'A','value':'混合吧唧立牌'}]}]
        self.write_binding();reader=Evidence(self.binding)
        target=extract_reviewed(read_upstream(self.r2,self.ref))[0];target['scope']=row['scope']
        f,issues,rejected=reader.facts(target)
        self.assertFalse(f['relations']);self.assertTrue(rejected);self.assertIn('混合商品',issues[0]['message'])
    def test_variety_does_not_set_blind_flag(self):
        self.data['rows'][2]['blind']={'value':True,'evidence':[{'source_id':'s','sheet':'invoice (計算)','row':4,'column':'T','value':'全12种'}]}
        self.write_binding();r=handle(self.req);row=read_quantity_source(r['quantity_source'])['rows'][2]
        self.assertIsNone(row['quantity']['blind'])
    def test_r3_reader_rejects_changed_semantics_even_with_new_file_hash(self):
        r=handle(self.req);ref=r['quantity_source'];path=Path(ref['path']);data=json.loads(path.read_text(encoding='utf8'));data['rows'][0]['quantity']['results']['piece']['numerator']='999'
        path.write_text(json.dumps(data),encoding='utf8')
        with self.assertRaises(ValueError):read_quantity_source({**ref,'sha256':digest(path)})


if __name__=='__main__':unittest.main()
