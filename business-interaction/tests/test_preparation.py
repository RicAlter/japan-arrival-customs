import unittest
import sys
from pathlib import Path
from interaction.preparation import resolve
from interaction.preparation_sources import Index
from interaction.preparation_rules import material,packaging

def record(jan,**kwargs):return {'jan':jan,'source':{'kind':'procurement'},**kwargs}

class PreparationTests(unittest.TestCase):
    def test_complete_japanese_title_resolves_procurement_suffix_only(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'material-query-adapter'))
        from interaction.website_query import assess_page
        q={'jan':'1','name_ja':'公安局刑事課モチーフ ar-Unity 缶バッジ5個セット','spec':'吧唧5枚套组3'}
        c={'jan_on_page':'1','name_ja':'『作品』'+q['name_ja'],'match_status':'jan_only'}
        self.assertEqual(assess_page(q,c,lambda a,b:.9)['status'],'candidate_only')
        self.assertEqual(assess_page(q,{**c,'jan_on_page':'2'},lambda a,b:.9)['status'],'identity_conflict')
        self.assertEqual(assess_page(q,{**c,'name_ja':q['name_ja'].replace('5個','3個')},lambda a,b:.9)['status'],'identity_unresolved')
    def test_pcs_fallback_keeps_box_price_out_of_piece(self):
        registry=record('box',pcs='piece',yd='YD1',name='同一商品',spec='立牌整盒',source={'kind':'registry'})
        purchase=record('box',yd='YD1',price=100,currency='CNY',image='https://img.alicdn.com/box.jpg')
        result=resolve('piece',Index([registry,purchase]),{},[])
        self.assertIsNone(result['values']['price']);self.assertEqual(result['values']['yd'],'YD1')
        self.assertEqual(result['image_scope'],'box_reference');self.assertEqual(result['related_procurement'][1]['price'],100)
    def test_direct_cny_label_and_no_qty_inference(self):
        result=resolve('a',Index([record('a',yd='YD',price=165,currency='人民币',purchase_current=4)]),{},[])
        self.assertEqual(result['values']['price'],'165元');self.assertTrue(result['purchase_observations_shared_not_allocated'])
    def test_multiple_boxes_do_not_choose_one(self):
        result=resolve('p',Index([record('b1',pcs='p',yd='Y1'),record('b2',pcs='p',yd='Y2')]),{},[])
        self.assertEqual(result['status'],'box_code_conflict');self.assertIsNone(result['values']['yd']);self.assertIsNone(result['image'])
    def test_explicit_material_and_user_rule(self):
        self.assertEqual(material('立牌12','立板立牌：亚克力，卡套：ABS')['value'],'亚克力')
        self.assertEqual(material('拍立得整盒89','马口铁、纸、PET')['value'],'纸')
    def test_composite_kept_without_rule(self):
        self.assertEqual(material('贴纸','纸、PP')['value'],'纸、PP')
        self.assertEqual(material('吧唧','亚克力、马口铁')['status'],'unresolved')
        self.assertEqual(material('立牌和收纳套套组','亚克力、PU')['value'],'亚克力、PU')
    def test_pack_preserves_each_pack_clause(self):
        result=packaging('贴纸整盒20','吧唧整盒8个入，贴纸整盒7包，每包2枚')
        self.assertEqual(result['value'],'贴纸整盒7包，每包2枚');self.assertIsNone(result['calculated_count'])
    def test_reverse_link_does_not_copy_piece_price(self):
        result=resolve('box',Index([record('box',pcs='piece',yd='YD'),record('piece',yd='YD',price=2,currency='JPY',image='https://img.alicdn.com/p.jpg')]),{},[])
        self.assertIsNone(result['values']['price']);self.assertEqual(result['image_scope'],'piece_reference')

if __name__=='__main__':unittest.main()
