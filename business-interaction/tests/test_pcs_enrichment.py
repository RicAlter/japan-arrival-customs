import unittest
from interaction.preparation import _legacy_resolve
from interaction.preparation_sources import Index
from interaction.matching_repair import resolve_repaired

PCS='4580822004159'
MAIN='4580822004166'

def records(spec='亚克力卡整盒', **kw):
    link={'jan':MAIN,'pcs':PCS,'name':'黄泉使者 亚克力卡','spec':spec+'1',
          'channel':'Hobby Stock','source':{'kind':'registry','row':16514}}
    item={'jan':MAIN,'name':'黄泉使者 亚克力卡','spec':spec,'yd':'Y1',
          'image':'https://img.example/box.jpg','channel':'采购渠道','source':{'kind':'procurement'}}
    order={'jan':MAIN,'name':'黄泉使者 亚克力卡','spec':spec,'yd':'Y1',
           'price':4330.33,'currency':'JPY','status':'已采购','order_id':'PO1',
           'source':{'kind':'effective_purchase_order'}, **kw}
    return [link,item,order]

def resolve(rs, **context):
    return resolve_repaired(PCS,Index(rs),{},[],_legacy_resolve,context)

class PcsEnrichmentTests(unittest.TestCase):
    def test_related_yd_and_specific_box_picture_are_carried_through(self):
        r=resolve(records());self.assertEqual(r['values']['yd'],'Y1')
        self.assertEqual(r['values']['spec'],'亚克力卡整盒1')
        self.assertEqual(r['values']['channel'],'Hobby Stock')
        self.assertEqual(r['image'],'https://img.example/box.jpg')
        self.assertEqual(r['image_scope'],'box_reference')

    def test_explicit_box_reference_keeps_price_and_unit_without_division(self):
        r=resolve(records());self.assertEqual(str(r['values']['price']),'4330.33')
        p=r['price_review'];self.assertEqual(p['purchase_unit'],'盒')
        self.assertEqual(p['selected']['price_unit_evidence']['field'],'spec')
        self.assertFalse(p['quantity_conversion']);self.assertFalse(p['automatic_confirmation'])

    def test_unknown_linked_unit_does_not_supply_piece_price(self):
        r=resolve(records('款式A'));self.assertEqual(r['values']['yd'],'Y1');self.assertIsNone(r['values']['price'])

    def test_explicit_piece_unit_not_overridden_by_box_word(self):
        self.assertIsNone(resolve(records(price_unit='件'))['values']['price'])

    def test_cancelled_order_cannot_supply_linked_price(self):
        self.assertIsNone(resolve(records(status='已撤销'))['values']['price'])

    def test_multiple_boxes_not_merged(self):
        rs=records();rs.append({**rs[0],'jan':'4580822004999'});r=resolve(rs)
        self.assertIsNone(r['values'].get('yd'));self.assertIsNone(r.get('image'));self.assertIsNone(r['values'].get('price'))

    def test_incompatible_variant_and_multiple_yd_pictures_not_selected(self):
        rs=records('Vol1整盒');rs[1]['spec']='Vol2整盒';rs[2]['spec']='Vol2整盒';r=resolve(rs)
        self.assertIsNone(r['values']['yd']);self.assertIsNone(r.get('image'))
        rs=records();rs.append({**rs[1],'yd':'Y2','image':'https://img.example/other.jpg'});r=resolve(rs)
        self.assertIsNone(r['values']['yd']);self.assertIsNone(r.get('image'))

    def test_bonus_requires_context_even_with_pcs_relationship(self):
        r=resolve(records(),name_ja='特典');self.assertIsNone(r['values'].get('yd'));self.assertIsNone(r.get('image'))

    def test_different_applicable_box_quotes_stay_pending(self):
        rs=records();rs.append({**rs[2],'order_id':'PO2','price':5000});r=resolve(rs)
        self.assertIsNone(r['values']['price'])
        self.assertEqual(r['pcs_enrichment']['linked_order_price_review']['category'],'true_price_conflict')
        self.assertEqual(r['price_review']['category'],'true_price_conflict')

    def test_cny_box_reference_is_labelled_and_never_converted(self):
        self.assertEqual(resolve(records(currency='CNY'))['values']['price'],'4330.33元/盒')

if __name__=='__main__':unittest.main()
