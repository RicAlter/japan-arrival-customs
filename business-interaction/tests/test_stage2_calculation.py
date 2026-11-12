import importlib.util
from pathlib import Path
import unittest
from fractions import Fraction as F

file=Path(__file__).resolve().parents[1]/'interaction/stage2_math.py'
spec=importlib.util.spec_from_file_location('stage2_math_fixture',file)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class CalculationTests(unittest.TestCase):
    def fact(self,**kw):
        return dict(quantity=60,price=202,amount=12120,total_pieces=180,reference_boxes=5,
            duty_rate=0,vat_rate='.13',pack_candidates=[dict(units_per_pack=3,packs_per_box=12,pieces_per_box=36)],**kw)
    def test_real_1010_layer_and_tax(self):
        r=m.calculate(self.fact());self.assertEqual(r['errors'],[])
        self.assertEqual(r['values'][:7],[3,12,36,5,3,12,F(202,3)])
        self.assertEqual((r['rounded_price'],r['values'][13],r['values'][14]),(67,F('315.12'),F('1575.60')))
    def test_real_790_matches_same_geometry(self):
        f=self.fact();f.update(quantity=144,amount=29088,total_pieces=432,reference_boxes=12)
        self.assertEqual(m.calculate(f)['values'][2:6],[36,12,3,12])
    def test_source_box_price(self):
        f=self.fact();f.update(quantity=60,price=3094,amount=185640,total_pieces=600,reference_boxes=60,
            pack_candidates=[dict(units_per_pack=None,packs_per_box=None,pieces_per_box=10)])
        r=m.calculate(f);self.assertEqual(r['values'][:6],[None,None,10,60,10,1]);self.assertEqual(r['rounded_price'],309)
    def test_direct_10_does_not_invent_packet(self):
        self.assertEqual(m.packaging('吧唧整盒10枚入',identity_scoped=True,product_kind='吧唧'),[dict(units_per_pack=None,packs_per_box=None,pieces_per_box=10)])
    def test_real_1010_parse(self):
        self.assertEqual(m.packaging('全24种，普通22种+特殊2种；1包3枚，整盒12包',identity_scoped=True)[0]['pieces_per_box'],36)
    def test_real_759_parse(self):
        self.assertEqual(m.packaging('全51种，1包3枚，1盒17包',identity_scoped=True)[0]['pieces_per_box'],51)
    def test_mixed_yd_specific_kind(self):
        r=m.packaging('透卡整盒12枚入，吧唧整盒10枚入',identity_scoped=True,product_kind='吧唧')
        self.assertEqual([x['pieces_per_box']for x in r],[10])
    def test_unscoped_generic_rejected(self):self.assertEqual(m.packaging('1包3枚，整盒12包'),[])
    def test_no_kind_yd_mixture_rejected(self):self.assertEqual(m.packaging('透卡整盒12枚入，吧唧整盒10枚入',identity_scoped=True),[])
    def test_no_spec_suffix_variety_body_or_ratio(self):
        for t in ['全24种','本体','整盒158','比价12','20枚套组','1盒12包']:
            self.assertEqual(m.packaging(t,identity_scoped=True),[],t)
    def test_conflict_retained(self):
        r=m.packaging('1包3枚，整盒12包；1包2枚，整盒12包',identity_scoped=True);self.assertEqual(len(r),2)
        f=self.fact();f['pack_candidates']=r;self.assertIn('同SKU盒规来源冲突',m.calculate(f)['errors'])
    def test_multiple_sizes_in_one_clause_are_not_first_match(self):
        self.assertEqual({x['pieces_per_box']for x in m.packaging('整盒10枚入，整盒12枚入',identity_scoped=True)},{10,12})
    def test_layer_and_direct_conflict_both_retained(self):
        self.assertEqual({x['pieces_per_box']for x in m.packaging('1包3枚，1盒12包，整盒10枚',identity_scoped=True)},{10,36})
    def test_real_121_458_mixed_types(self):
        for text,c in [('吧唧收藏卡整盒10枚入，挂件整盒5枚入',10),('吧唧整盒8枚入，卡片整盒10枚入',8)]:
            self.assertEqual([x['pieces_per_box']for x in m.packaging(text,identity_scoped=True,product_kind='吧唧')],[c])
    def test_real_237_238_shared_code_A_B(self):
        for spec,c in [('A整盒18',7),('B整盒11',6)]:
            self.assertEqual([x['pieces_per_box']for x in m.packaging('A整盒7个入，B整盒6个入',identity_scoped=True,product_spec=spec)],[c])
    def test_real_670_671_volume_selection(self):
        for spec,c in [('Vol.1整盒47',12),('Vol.2整盒11',15)]:
            self.assertEqual([x['pieces_per_box']for x in m.packaging('vol1整盒12枚入，vol2整盒15枚入',identity_scoped=True,product_spec=spec)],[c])
    def test_missing_volume_does_not_adopt(self):
        self.assertEqual(m.packaging('vol1整盒12枚入，vol2整盒15枚入',identity_scoped=True),[])
    def test_real_773_only_sticker_layers(self):
        self.assertEqual([x['pieces_per_box']for x in m.packaging('挂件整盒8个入；贴纸整盒12包，每包2枚入',identity_scoped=True,product_kind='贴纸')],[24])
    def test_fractional_boxes_not_rounded(self):
        f=self.fact();f.update(total_pieces=183,reference_boxes=None)
        r=m.calculate(f);self.assertEqual(r['values'][3],F(61,12));self.assertIn('总单个数不能整除固定盒规',r['errors'])
    def test_reference_conflict(self):
        f=self.fact();f['reference_boxes']=12;r=m.calculate(f)
        self.assertIn('推导盒数与参考盒数冲突',r['errors']);self.assertIsNone(r['values'][13])
    def test_missing_card_reference_boxes_do_not_approve_c(self):
        f=self.fact();f['pack_candidates']=[];r=m.calculate(f)
        self.assertIsNone(r['values'][2]);self.assertEqual(r['values'][3],5);self.assertEqual(r['values'][13],F('315.12'));self.assertEqual(r['values'][16],'部分计算')
    def test_zero_duty_valid(self):self.assertEqual(m.calculate(self.fact())['values'][11],0)
    def test_missing_duty_not_zero(self):
        f=self.fact();f['duty_rate']=None;r=m.calculate(f);self.assertIsNone(r['values'][11]);self.assertIsNone(r['values'][14])
    def test_invalid_total_cannot_substitute_old(self):
        for t in [0,-1,'not numeric','3.5',True]:self.assertIn('总单个数须为正整数',m.calculate(self.fact(),total=t)['errors'])
    def test_source_amount_preservation_failure(self):
        f=self.fact();f['amount']=12060;self.assertIn('原金额与原Qty×原价不符',m.calculate(f)['errors'])
    def test_procurement_not_used_to_force_total(self):
        f=self.fact();f['purchase_note']='17盒；砍单3待核';r=m.calculate(f)
        self.assertEqual(r['values'][15],f['purchase_note']);self.assertEqual(r['values'][3],5)
    def test_no_procurement_price_required_for_arithmetic(self):self.assertEqual(m.calculate(self.fact())['rounded_price'],67)
    def row(self,**kw):
        r=dict(carton='EB53',code='4582770137637',origin='JP',japanese_name='name',quantity=60,price=202,amount=12120,source_row=1010);r.update(kw);return r
    def test_same_jan_distinct_cartons_one_to_one(self):
        a=self.row();b=self.row(carton='EB47',quantity=144,amount=29088,source_row=790)
        self.assertEqual([s['source_row']for _,s in m.unique_match([a,b],[b,a])],[1010,790])
    def test_duplicate_full_keys_rejected(self):
        with self.assertRaises(ValueError):m.unique_match([self.row()],[self.row(),self.row(source_row=9)])
    def test_two_targets_cannot_reuse_source(self):
        with self.assertRaises(ValueError):m.unique_match([self.row(),self.row()],[self.row()])
    def test_different_variant_name_not_matched(self):
        with self.assertRaises(ValueError):m.unique_match([self.row(japanese_name='blue')],[self.row(japanese_name='red')])

if __name__=='__main__':unittest.main()

class IdentityScopeTests(unittest.TestCase):
    def setUp(self):
        import sys,sqlite3,json
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
        import bind_stage2
        self.b=bind_stage2;self.json=json;self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('create table catalogue_entries(descriptor_json text)')
        self.db.execute('create table yd_product_card_details(source_sha256 text,source_row int,yd_key text,context_json text)')
        self.db.execute('insert into catalogue_entries values(?)',(json.dumps(dict(code_raw='shared',yd='YD1',specification='吧唧整盒',internal_name='商品A')) ,))
        self.db.execute('insert into yd_product_card_details values(?,?,?,?)',('source-v1',12,'YD1',json.dumps(dict(source={'revision':1},product_card={'商品名称':'商品A','产品配件':'透卡整盒12枚入，吧唧整盒10枚入'}))))
        self.identity=dict(code='shared',yd='YD1',spec='吧唧整盒69',name='商品A',database_sha256='fixed-database-version')
        self.addCleanup(self.b.descriptors.cache_clear)
    def test_specific_shared_code_scope(self):
        self.assertEqual([c['pieces_per_box']for c in self.b.card_candidates(self.db,self.identity)],[10])
    def test_shared_code_different_spec_rejected(self):
        self.assertEqual(self.b.card_candidates(self.db,{**self.identity,'spec':'透卡整盒'}),[])
    def test_yd_change_invalidates(self):
        self.assertEqual(self.b.card_candidates(self.db,{**self.identity,'yd':'YD2'}),[])
    def test_different_product_same_yd_not_adopted(self):
        self.db.execute('update yd_product_card_details set context_json=?',(self.json.dumps(dict(source={'revision':2},product_card={'商品名称':'商品B','产品配件':'吧唧整盒10枚入'})),))
        self.assertEqual(self.b.card_candidates(self.db,self.identity),[])
    def test_source_version_and_identity_bound(self):
        c=self.b.card_candidates(self.db,self.identity)[0]
        self.assertEqual((c['source_sha256'],c['source_version']['revision'],c['identity']['spec']),('source-v1',1,'吧唧整盒69'))
    def test_conflicting_versions_remain_candidates(self):
        self.db.execute('insert into yd_product_card_details values(?,?,?,?)',('source-v2',13,'YD1',self.json.dumps(dict(source={'revision':2},product_card={'商品名称':'商品A','产品配件':'吧唧整盒8枚入'}))))
        self.assertEqual({c['pieces_per_box']for c in self.b.card_candidates(self.db,self.identity)},{8,10})
