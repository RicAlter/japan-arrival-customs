import json,sqlite3,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools'),str(Path(__file__).resolve().parents[1]/'interaction')]
from stage2_review import reviewed_cards,price_review,product_name,same_sku
from stage2_math import packaging

class YellowReviewTests(unittest.TestCase):
    def identity(self,**kw):return dict(code='shared',name='系列 吧唧 周边',spec='Ca整盒3',yd='YD1',database_sha256='db-v1',**kw)
    def test_name_alias_keeps_product_version(self):
        self.assertEqual(product_name('模玩熊 系列 第一季 DG周边预定金'),product_name('系列 第一季 周边'))
        self.assertNotEqual(product_name('系列 第一季 周边'),product_name('系列 剧场版 周边'))
        self.assertEqual(product_name('系列 DG周边（只有二维码到货要打印条码入库）'),product_name('模玩熊 系列 DG周边预定金'))
        self.assertEqual(product_name('系列 DG周边（不同产品只有一个编码，到货需要打印编码入库）'),product_name('系列 DG周边追定金'))
    def test_spec_quantity_tail_only(self):
        self.assertTrue(same_sku('海军蓝卡片尺寸4（45953192736661）','海军蓝卡片尺寸'))
        self.assertFalse(same_sku('Vol2整盒3','Vol1整盒'))
        self.assertFalse(same_sku('Ca整盒3','Cb整盒'))
    def test_multi_letter_version_lists(self):
        text='Aa、Ca、Cb、Da整盒8枚入；Ab、Ba、Db整盒7枚入；Bb整盒6枚入'
        for spec,c in [('Ca整盒1',8),('Da整盒3',8),('Db整盒2',7),('Bb整盒4',6)]:
            self.assertEqual([r['pieces_per_box']for r in packaging(text,identity_scoped=True,product_spec=spec)],[c])
        self.assertEqual(packaging(text,identity_scoped=True,product_spec='整盒1'),[])
    def test_badge_magnet_sticker_separate(self):
        text='贴纸1包2枚，1盒12包；冰箱贴整盒10枚，徽章整盒5枚入'
        for kind,c in [('贴纸',24),('冰箱贴',10),('徽章',5)]:
            self.assertEqual([r['pieces_per_box']for r in packaging(text,identity_scoped=True,product_kind=kind)],[c])
    def db(self,name='模玩熊 系列 吧唧 DG周边预定金',text='Ca整盒8枚入'):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('create table yd_product_card_details(source_sha256 text,source_row int,yd_key text,context_json text)')
        db.execute('insert into yd_product_card_details values(?,?,?,?)',('card-v1',12,'YD1',json.dumps(dict(source={'revision':91},product_card={'商品名称':name,'产品配件':text}))))
        return db
    def test_reviewed_accepted_parent_and_exact_variant(self):
        r=reviewed_cards(self.db(),self.identity())[0]
        self.assertEqual((r['pieces_per_box'],r['source_row'],r['identity']['code']),(8,12,'shared'))
    def test_parent_yd_or_box_scope_change_not_reused(self):
        db=self.db();i=self.identity()
        for change in [dict(name='系列2 吧唧 周边'),dict(yd='YD2'),dict(spec='Cb整盒1'),dict(spec='Ca角色')]:
            self.assertEqual(reviewed_cards(db,{**i,**change}),[])
    def test_generic_mixed_parent_stays_unresolved(self):
        db=self.db('系列 吧唧亚克力卡 周边','整盒10枚入')
        self.assertEqual(reviewed_cards(db,{**self.identity(),'name':'系列 吧唧亚克力卡 周边','spec':'亚克力卡整盒1'}),[])
    def test_variety_count_does_not_resolve_box(self):
        self.assertEqual(reviewed_cards(self.db(text='整盒全13种'),self.identity()),[])
    def price(self,*,price=250,currency='人民币',spec='Ca整盒',**kw):
        return dict(name='模玩熊 系列 吧唧 DG周边预定金',yd='YD1',spec=spec,price=price,currency=currency,**kw)
    def fact(self):return dict(quantity=3,total_pieces=24,reference_boxes=3,pack_candidates=[{'pieces_per_box':8}])
    def review(self,valid,ambiguous=None,fact=None,identity=None):
        return price_review(identity or self.identity(),fact or self.fact(),{'YD1':{'valid':valid,'ambiguous':ambiguous or []}})
    def test_currency_and_original_unit_reference(self):
        r=self.review([self.price()]);self.assertEqual(r['value'],'250元')
        self.assertEqual(self.review([self.price(currency='日元',price=4763.36)])['value'],'4763.36JPY')
    def test_missing_currency_zero_and_multiple_prices_not_first_pick(self):
        for items in [[self.price(currency=None)],[self.price(price=0)],[self.price(),self.price(price=251)],[self.price(price_export_conflict=True)]]:
            self.assertIsNone(self.review(items)['value'])
    def test_status_or_cut_conflict_not_approved(self):
        self.assertIsNone(self.review([self.price()],ambiguous=[self.price(status='已撤销')])['value'])
    def test_unit_conversion_missing_stays_unresolved(self):
        f=self.fact();f.update(quantity=24,pack_candidates=[])
        self.assertIsNone(self.review([self.price()],fact=f)['value'])
    def test_explicit_three_piece_packet_matches_I_factor(self):
        i={**self.identity(),'spec':'A随机3枚4'};f=self.fact();f.update(quantity=4,total_pieces=12)
        self.assertEqual(self.review([self.price(spec='A随机3枚')],fact=f,identity=i)['value'],'250元')
        f['total_pieces']=8
        self.assertIsNone(self.review([self.price(spec='A随机3枚')],fact=f,identity=i)['value'])

if __name__=='__main__':unittest.main()
