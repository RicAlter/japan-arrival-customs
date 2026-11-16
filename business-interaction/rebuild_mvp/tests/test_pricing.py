import copy,json,sqlite3,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from fractions import Fraction as F
from contextlib import closing
from unittest.mock import patch
from xml.etree import ElementTree as ET
import test_quantity as QTest
from test_enrichment import book
from rebuild_mvp.service import handle,digest
from rebuild_mvp.review_return import overlay
from rebuild_mvp.quantity_math import calculate as quantities,parse_layers,exact
from rebuild_mvp.pricing_math import calculate,round0,summarize
from rebuild_mvp.pricing_sources import PricingEvidence
from rebuild_mvp.pricing_conversion import read_pricing_source
from rebuild_mvp.xlsxio import read_book,Q


def qty(q='60',total=None):
    facts={'qty_unit':{'unit':'pack'},'relations':parse_layers('每包3枚，1盒12包'),'v_unit':'box'}
    if total is not None:facts['observations']={'total_pieces':{'value':str(total)}}
    return quantities(q,facts)


def invoice(**kw):return {'quantity':'60','price':'202','amount':'12120','currency':'JPY',**kw}
def rates(**kw):return {'duty_rate':{'value':'0'},'vat_rate':{'value':'.13'},**kw}
def value(row,key):
    v=row['results'][key]['value'];return F(int(v['numerator']),int(v['denominator']))


class PricingMath(unittest.TestCase):
    def test_real_1010_original_tax_base(self):
        r=calculate(invoice(),qty(),rates())
        self.assertEqual(value(r,'piece_price_exact'),F(202,3));self.assertEqual(value(r,'piece_price_round0'),67)
        self.assertEqual(value(r,'rounded_line_amount'),12060);self.assertEqual(value(r,'rounding_difference'),-60)
        self.assertEqual(value(r,'tax_per_box_reference'),F('315.12'));self.assertEqual(value(r,'tax_line_reference'),F('1575.6'))
        self.assertNotEqual(value(r,'tax_per_box_reference'),F('313.56'))
    def test_real_790_same_box_tax(self):
        r=calculate(invoice(quantity='144',amount='29088'),qty('144'),rates())
        self.assertEqual(value(r,'tax_per_box_reference'),F('315.12'));self.assertEqual(value(r,'tax_line_reference'),F('3781.44'))
    def test_zero_rates_are_valid(self):
        r=calculate(invoice(),qty(),rates(vat_rate={'value':'0'}));self.assertEqual(value(r,'tax_line_reference'),0)
    def test_missing_rate_not_zero(self):
        r=calculate(invoice(),qty(),{'duty_rate':{'value':0}})
        self.assertEqual(value(r,'duty_line_reference'),0);self.assertNotIn('vat_line_reference',r['results']);self.assertIn('piece_price_round0',r['results'])
    def test_missing_duty_does_not_approve_vat(self):
        r=calculate(invoice(),qty(),{'vat_rate':{'value':'.13'}});self.assertNotIn('vat_line_reference',r['results'])
    def test_invalid_rates(self):
        for rate in ['-1','1.1','not','NaN',True]:
            r=calculate(invoice(),qty(),rates(duty_rate={'value':rate}));self.assertNotIn('tax_line_reference',r['results'])
    def test_explicit_percent(self):
        self.assertEqual(value(calculate(invoice(),qty(),rates(vat_rate={'value':'13%'})),'vat_line_reference'),F('1575.6'))
    def test_half_away_rounding(self):
        for n,expected in [('2.5',3),('-2.5',-3),('0.5',1),('2.49',2)]:self.assertEqual(round0(F(n)),expected)
    def test_zero_price_and_amount_are_not_missing(self):
        r=calculate(invoice(price='0',amount='0'),qty(),rates());self.assertEqual(value(r,'piece_price_round0'),0);self.assertEqual(value(r,'tax_line_reference'),0)
    def test_invalid_original_price(self):
        for p in ['-1','#N/A','NaN',True]:
            r=calculate(invoice(price=p),qty(),rates());self.assertNotIn('piece_price_exact',r['results']);self.assertNotIn('tax_line_reference',r['results'])
    def test_original_amount_conflict_is_not_balanced(self):
        r=calculate(invoice(amount='12100'),qty(),rates());self.assertEqual(value(r,'original_amount_difference'),-20);self.assertEqual(value(r,'rounding_difference'),-60);self.assertEqual(value(r,'difference_from_original_amount'),-40)
        self.assertEqual(r['field_states']['original_amount'],'conflict')
    def test_missing_amount_does_not_block_unit_arithmetic(self):
        r=calculate(invoice(amount=''),qty(),rates());self.assertIn('piece_price_round0',r['results']);self.assertNotIn('difference_from_original_amount',r['results'])
    def test_missing_quantity_unit_blocks_piece_conversion(self):
        q=qty();q['raw_unit']=None
        r=calculate(invoice(),q,rates());self.assertNotIn('piece_price_exact',r['results'])
    def test_conflicting_total_not_used_for_piece_price(self):
        r=calculate(invoice(),qty(total=90),rates());self.assertNotIn('piece_price_exact',r['results'])
    def test_partial_box_retains_exact_tax(self):
        r=calculate(invoice(quantity='61',amount='12322'),qty('61'),rates());self.assertEqual(value(r,'tax_per_box_reference'),F('315.12'))
    def test_procurement_not_required_for_original_price(self):
        self.assertIn('piece_price_exact',calculate(invoice(),qty(),rates())['results'])
    def quote(self,**kw):return {'value':'404','currency':'JPY','unit':'pack','matches_display':True,**kw}
    def test_comparable_price_ratio(self):
        r=calculate(invoice(),qty(),rates(purchase_quote=self.quote()));self.assertEqual(value(r,'purchase_ratio'),2)
    def test_zero_purchase_quote_is_valid(self):
        self.assertEqual(value(calculate(invoice(),qty(),rates(purchase_quote=self.quote(value='0'))),'purchase_ratio'),0)
    def test_other_currency_never_converted(self):
        r=calculate(invoice(),qty(),rates(purchase_quote=self.quote(currency='CNY')));self.assertNotIn('purchase_ratio',r['results']);self.assertIn('piece_price_exact',r['results'])
    def test_different_price_unit_not_compared(self):
        self.assertNotIn('purchase_ratio',calculate(invoice(),qty(),rates(purchase_quote=self.quote(unit='box')))['results'])
    def test_display_mismatch_is_conflict(self):
        self.assertNotIn('purchase_ratio',calculate(invoice(),qty(),rates(purchase_quote=self.quote(matches_display=False)))['results'])
    def test_zero_denominator_not_divided(self):
        self.assertNotIn('purchase_ratio',calculate(invoice(price='0',amount='0'),qty(),rates(purchase_quote=self.quote()))['results'])
    def test_partial_totals_do_not_claim_full_coverage(self):
        rows=[{'pricing':calculate(invoice(),qty(),rates())},{'pricing':calculate(invoice(),qty(),{})}]
        total=summarize(rows)['tax_line_reference'];self.assertFalse(total['complete']);self.assertEqual(total['covered_rows'],1)
    def test_math_is_pure(self):
        i,q,f=invoice(),qty(),rates();before=copy.deepcopy([i,q,f]);calculate(i,q,f);self.assertEqual(before,[i,q,f])
    def test_foreign_invoice_not_mislabeled_JPY(self):
        self.assertFalse(calculate(invoice(currency='CNY'),qty(),rates())['results'])


class PricingEntry(unittest.TestCase):
    def setUp(self):
        f=QTest.QuantityEntry('test_entry_and_following_stage_contract');f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.root=f.root
        self.quantity=self.make_quantity()
        self.source=self.root/'price-evidence.xlsx';self.header=['商品','币种','报价单位','报价','关税率','增值税率']
        book(self.source,headers=self.header,records=[['code','JPY','包','200','0','13%'],['code','JPY','套','200','0','13%'],['bad','JPY','个','200','0','13%']])
        self.binding=self.root/'pricing-evidence.json'
        from rebuild_mvp.quantity_conversion import read_quantity_source
        contract=read_quantity_source(self.quantity['quantity_source']);self.rows=contract['rows']
        sources=[{'source_id':name,'path':str(self.source),'sha256':digest(self.source),'role':role,'version':'test-v1'}for name,role in [('quote','reviewed_basics'),('rate','tax_reference')]]
        source_book=read_book(self.quantity['business_files'][0]);source_rows={r['row']:r['values']for r in source_book['sheets'][0]['rows']}
        sources.append({'source_id':'invoice','path':self.quantity['business_files'][0],'sha256':digest(self.quantity['business_files'][0]),'role':'japanese_batch','version':'synthetic-preserved-raw-fields'})
        records=[]
        for index,row in enumerate(self.rows):
            n=index+2;record={'sheet':row['sheet'],'row':row['row'],'scope':row['scope'],
                            'duty_rate':{'value':'0','evidence':[self.ref('rate',n,'E','0')]},
                            'vat_rate':{'value':'13%','evidence':[self.ref('rate',n,'F','13%')]}}
            record['invoice_evidence']={'basis':'preserved_japanese_original','currency':'JPY',
                                        'identity_evidence':[{**self.ref('invoice',n,'C',row['scope']['code']),'field':'code'}],
                                        'quantity':[self.ref('invoice',n,'K',source_rows[n]['K'])],
                                        'price':[self.ref('invoice',n,'L',source_rows[n]['L'])],
                                        'amount':[self.ref('invoice',n,'M',source_rows[n]['M'])],
                                        'currency_evidence':[self.ref('invoice',1,'L',source_rows[1]['L'])]}
            if index==0:record['purchase_quote']={'value':'200','currency':'JPY','unit':'pack','unit_basis':'原报价单位格明确为包',
                                                'identity_evidence':[{**self.ref('quote',n,'A',row['scope']['code']),'field':'code'}],
                                                'evidence':[self.ref('quote',n,'D','200')],'currency_evidence':[self.ref('quote',n,'B','JPY')],'unit_evidence':[self.ref('quote',n,'C','包')]}
            records.append(record)
        self.data={'schema':'arrival-price-tax-evidence/1','quantity_source_sha256':self.quantity['quantity_source']['sha256'],'sources':sources,'rows':records};self.write()
        self.req={'action':'prepare','mode':'price_tax','batch_id':'B','quantity_source':self.quantity['quantity_source'],'pricing_binding':str(self.binding),'output':str(self.root/'price')}
    def ref(self,sid,row,col,value):return {'source_id':sid,'sheet':'invoice (計算)','row':row,'column':col,'value':value}
    def write(self):self.binding.write_text(json.dumps(self.data,ensure_ascii=False),encoding='utf8')
    def make_quantity(self,ratio=''):
        index=len(list(self.root.glob('price-input*')));initial=self.root/f'price-input-{index}.xlsx'
        overlay(self.f.ref['path'],initial,'invoice (計算)',{'H2':'200','I2':ratio if ratio!='formula'else'2'})
        if ratio=='formula':
            with zipfile.ZipFile(initial)as z:parts={n:z.read(n)for n in z.namelist()}
            tree=ET.fromstring(parts['xl/worksheets/sheet1.xml']);c=next(c for c in tree.iter(Q+'c')if c.get('r')=='I2');c.attrib.pop('t',None);c[:]=[];ET.SubElement(c,Q+'f').text='H2/L2';ET.SubElement(c,Q+'v').text='2';parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
            with zipfile.ZipFile(initial,'w')as z:
                for n,data in parts.items():z.writestr(n,data)
        r2=self.root/f'price-r2-{index}';p=handle(dict(action='prepare',mode='review_return',batch_id='B',input_file=str(initial),output=str(r2)));s=handle(dict(action='resume',task_root=str(r2),submitted_file=str(initial),expected_revision=0,expected_reference_sha256=p['reference_sha256']));self.assertEqual(s['status'],'saved',s)
        return handle({**self.f.req,'review_task_root':str(r2),'reviewed_source':s['reviewed_source'],'output':str(self.root/f'price-quantity-{index}')})
    def result(self):
        result=handle(self.req);self.assertEqual(result.get('step'),'exported',result);return result,read_pricing_source(result['pricing_source'])
    def test_entry_fills_only_blank_I(self):
        before=digest(self.quantity['business_files'][0]);r,data=self.result();row=data['rows'][0];self.assertEqual(value(row['pricing'],'purchase_ratio'),2)
        output=read_book(r['business_files'][0])['sheets'][0]['rows'][1];self.assertEqual(output['values']['I'],'2');self.assertEqual(output['values']['K'],'60');self.assertEqual(output['values']['L'],'100');self.assertEqual(output['values']['M'],'6000');self.assertEqual(before,digest(self.quantity['business_files'][0]))
    def test_old_quantity_database_and_jobs_not_modified(self):
        task=Path(self.quantity['pricing_source']['path']).parent if 'pricing_source'in self.quantity else Path(self.quantity['quantity_source']['path']).parent
        files=[task/'job.json',task/'candidate.sqlite3',Path(self.quantity['quantity_source']['path']),Path(self.quantity['business_files'][0])];before={str(p):digest(p)for p in files};self.result();self.assertEqual(before,{str(p):digest(p)for p in files})
    def test_current_repeat_resume_identical(self):
        r,_=self.result();self.assertEqual(r,handle(self.req));self.assertEqual(r,handle(dict(action='resume',task_root=self.req['output'])));self.assertEqual(r,handle(dict(action='current',task_root=self.req['output'])))
    def test_manual_I_is_retained_and_flagged(self):
        q=self.make_quantity('999');self.req['quantity_source']=q['quantity_source'];self.data['quantity_source_sha256']=q['quantity_source']['sha256'];self.write();r,data=self.result();self.assertEqual(read_book(r['business_files'][0])['sheets'][0]['rows'][1]['values']['I'],'999');self.assertEqual(data['rows'][0]['pricing']['field_states']['purchase_ratio_round0'],'conflict')
    def test_formula_and_cache_are_retained(self):
        q=self.make_quantity('formula');self.req['quantity_source']=q['quantity_source'];self.data['quantity_source_sha256']=q['quantity_source']['sha256'];self.write();r,_=self.result();row=read_book(r['business_files'][0])['sheets'][0]['rows'][1];self.assertEqual(row['formulas']['I'],'H2/L2');self.assertEqual(row['values']['I'],'2')
    def test_currency_conflict_is_local(self):
        self.data['rows'][0]['purchase_quote']['currency']='CNY';self.write();r,data=self.result();self.assertNotIn('purchase_ratio',data['rows'][0]['pricing']['results']);self.assertIn('piece_price_exact',data['rows'][0]['pricing']['results'])
    def test_currency_cannot_be_borrowed_from_another_quote_row(self):
        self.data['rows'][0]['purchase_quote']['currency_evidence']=[self.ref('quote',3,'B','JPY')];self.write();_,data=self.result();self.assertNotIn('purchase_ratio',data['rows'][0]['pricing']['results'])
    def test_wrong_product_quote_with_same_price_rejected(self):
        self.data['rows'][0]['purchase_quote']['identity_evidence']=[{**self.ref('quote',4,'A','bad'),'field':'code'}];self.write();_,data=self.result();self.assertNotIn('purchase_ratio',data['rows'][0]['pricing']['results'])
    def test_original_price_identity_required(self):
        self.data['rows'][0]['invoice_evidence']['identity_evidence']=[];self.write();_,data=self.result();self.assertFalse(data['rows'][0]['pricing']['results'])
    def test_official_product_price_rejected(self):
        self.data['sources'][0]['role']='product_card';self.write();r,data=self.result();self.assertNotIn('purchase_ratio',data['rows'][0]['pricing']['results']);self.assertTrue(any(i['code']=='SOURCE_FORBIDDEN'for i in data['rows'][0]['pricing']['issues']))
    def test_missing_rates_leave_unit_arithmetic(self):
        for record in self.data['rows']:record.pop('duty_rate');record.pop('vat_rate')
        self.write();r,data=self.result();p=data['rows'][0]['pricing'];self.assertIn('piece_price_exact',p['results']);self.assertNotIn('tax_line_reference',p['results'])
    def test_cannot_inject_global_vat_default(self):
        self.assertEqual(handle({**self.req,'vat_rate':'.13'})['error']['code'],'CONFIG_INVALID')
    def test_bad_source_coordinate_is_local(self):
        self.data['rows'][0]['vat_rate']['evidence'][0]['value']='12%';self.write();r,data=self.result();p=data['rows'][0]['pricing'];self.assertNotIn('tax_line_reference',p['results']);self.assertIn('piece_price_exact',p['results'])
    def test_wrong_sku_scope_not_used(self):
        self.data['rows'][0]['scope']['specification']='other';self.write();r,data=self.result();self.assertNotIn('tax_line_reference',data['rows'][0]['pricing']['results']);self.assertIn('tax_line_reference',data['rows'][1]['pricing']['results'])
    def test_opening_derived_source_rejected(self):
        self.data['sources'][0]['opening_derived']=True;self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_FORBIDDEN')
    def test_changed_quantity_output_rejected(self):
        self.result();Path(self.quantity['business_files'][0]).write_bytes(b'changed');self.assertEqual(handle(dict(action='current',task_root=self.req['output']))['error']['code'],'SOURCE_CHANGED')
    def test_changed_pricing_binding_rejected(self):
        self.result();self.binding.write_text('{}',encoding='utf8');self.assertEqual(handle(dict(action='resume',task_root=self.req['output']))['error']['code'],'SOURCE_CHANGED')
    def test_changed_code_rejected(self):
        self.result()
        with patch('rebuild_mvp.pricing_conversion.code_version',return_value={}):self.assertEqual(handle(dict(action='resume',task_root=self.req['output']))['error']['code'],'SOURCE_CHANGED')
    def test_price_binding_pins_quantity_version(self):
        self.data['quantity_source_sha256']='0'*64;self.write();self.assertEqual(handle(self.req)['error']['code'],'SOURCE_CHANGED')
    def test_cancelled_purchase_quote_not_used(self):
        self.data['sources'][0]['role']='purchase_list';self.data['rows'][0]['purchase_quote']['record_state']='cancelled';self.write();r,data=self.result();self.assertNotIn('purchase_ratio',data['rows'][0]['pricing']['results'])
    def test_effective_procurement_status_with_coordinates(self):
        newfile=self.root/'status-source.xlsx';overlay(self.source,newfile,'invoice (計算)',{'G2':'有效'})
        for source in self.data['sources']:
            if source['source_id']in {'quote','rate'}:source['path']=str(newfile);source['sha256']=digest(newfile)
        self.data['sources'][0]['role']='purchase_list';quote=self.data['rows'][0]['purchase_quote'];quote.update(record_state='effective',status_evidence=[self.ref('quote',2,'G','有效')]);self.write();_,data=self.result();self.assertEqual(value(data['rows'][0]['pricing'],'purchase_ratio'),2)
    def test_formula_multiplier_rate_checked_against_actual_formula(self):
        with zipfile.ZipFile(self.source)as z:parts={n:z.read(n)for n in z.namelist()}
        tree=ET.fromstring(parts['xl/worksheets/sheet1.xml']);c=next(c for c in tree.iter(Q+'c')if c.get('r')=='F2');c.attrib.pop('t',None);c[:]=[];ET.SubElement(c,Q+'f').text='D2*(1+E2)*0.13';ET.SubElement(c,Q+'v').text='26';parts['xl/worksheets/sheet1.xml']=ET.tostring(tree)
        with zipfile.ZipFile(self.source,'w')as z:
            for n,data in parts.items():z.writestr(n,data)
        for s in self.data['sources']:
            if s['source_id']in {'quote','rate'}:s['sha256']=digest(self.source)
        self.data['rows'][0]['vat_rate']={'value':'.13','basis':'formula_multiplier','formula':'D2*(1+E2)*0.13','evidence':[self.ref('rate',2,'F','26')]};self.write();r,data=self.result();self.assertEqual(value(data['rows'][0]['pricing'],'vat_rate'),F('.13'))
    def test_interrupted_rows_resume(self):
        from rebuild_mvp.pricing_conversion import calculate as original
        count=0
        def fail(*a,**k):
            nonlocal count
            count+=1
            if count==2:raise RuntimeError('injected interruption')
            return original(*a,**k)
        with patch('rebuild_mvp.pricing_conversion.calculate',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        self.assertEqual(handle(dict(action='current',task_root=self.req['output']))['status'],'failed');r=handle(dict(action='resume',task_root=self.req['output']));self.assertEqual(r['step'],'exported',r)
    def test_interrupted_publication_recovers(self):
        from rebuild_mvp.pricing_conversion import export as original
        def fail(*a,**k):original(*a,**k);raise RuntimeError('after output')
        with patch('rebuild_mvp.pricing_conversion.export',side_effect=fail):self.assertEqual(handle(self.req)['status'],'failed')
        output=Path(self.req['output'])/'价格金额与税金核对.xlsx';before=digest(output);r=handle(dict(action='resume',task_root=self.req['output']));self.assertEqual(r['step'],'exported',r);self.assertEqual(before,digest(output))
    def test_corrupt_checkpoint_not_reused(self):
        with patch('rebuild_mvp.pricing_conversion.export',side_effect=RuntimeError('pause')):handle(self.req)
        with closing(sqlite3.connect(Path(self.req['output'])/'candidate.sqlite3'))as db,db:db.execute("update pricing_rows set payload='{}'")
        self.assertEqual(handle(dict(action='resume',task_root=self.req['output']))['error']['code'],'TASK_CONFLICT')
    def test_original_media_and_weight_parts_equal(self):
        r,_=self.result()
        with zipfile.ZipFile(self.quantity['business_files'][0])as a,zipfile.ZipFile(r['business_files'][0])as b:
            for n in a.namelist():
                if n!='xl/worksheets/sheet1.xml':self.assertEqual(a.read(n),b.read(n))
    def test_actual_run_py(self):
        req=self.root/'actual-request.json';req.write_text(json.dumps({'workflow':'rebuild_mvp_v1',**self.req}),encoding='utf8');entry=Path(__file__).resolve().parents[2]/'run.py';p=subprocess.run([sys.executable,'-X','utf8','-B',str(entry),'--request',str(req)],capture_output=True,text=True,encoding='utf8');self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertEqual(json.loads(p.stdout)['step'],'exported')
    def test_contract_tampering_detected_even_with_updated_hash(self):
        r,_=self.result();ref=r['pricing_source'];p=Path(ref['path']);d=json.loads(p.read_text(encoding='utf8'));d['rows'][0]['pricing']['results']['rounded_line_amount']['value']['numerator']='999';p.write_text(json.dumps(d),encoding='utf8')
        with self.assertRaises(ValueError):read_pricing_source({**ref,'sha256':digest(p)})
    def test_contract_totals_tampering_detected(self):
        r,_=self.result();ref=r['pricing_source'];p=Path(ref['path']);d=json.loads(p.read_text(encoding='utf8'));d['totals']['tax_line_reference']['value']['numerator']='999';p.write_text(json.dumps(d),encoding='utf8')
        with self.assertRaises(ValueError):read_pricing_source({**ref,'sha256':digest(p)})
    def test_original_price_source_not_assumed_from_header(self):
        self.data['rows'][0]['invoice_evidence']['price']=[self.ref('quote',2,'D','200')];self.write();_,data=self.result();self.assertNotIn('piece_price_exact',data['rows'][0]['pricing']['results']);self.assertNotIn('tax_line_reference',data['rows'][0]['pricing']['results'])
    def test_missing_original_evidence_not_used_as_original_quote(self):
        self.data['rows'][0].pop('invoice_evidence');self.write();_,data=self.result();self.assertFalse(data['rows'][0]['pricing']['results'])


if __name__=='__main__':unittest.main()
