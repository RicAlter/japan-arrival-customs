import unittest,tempfile
from pathlib import Path
from copy import deepcopy
from interaction.material_reference import enrich_material,apply_overlay,canonical_material_return,binding
from interaction import save
from openpyxl import Workbook,load_workbook

JAN='4550621772719';NAME='新网球王子 寝起 睡衣 吧唧徽章贴纸 DG周边'
def row(**kw):
    return {'jan':JAN,'status':'matched','values':{'name':NAME,'spec':'越前龙马贴纸9','yd':'Y1'},'material':{'value':None},'sources':[],**kw}
def rec(**kw):
    return {'jan':'DG'+JAN,'name':'模玩熊 '+NAME+'预定金','spec':'越前龙马贴纸','yd':'Y1','material':'马口铁,纸','source':{'kind':'catalogue','entry_id':'test'},**kw}
def linked(r):return row(dg_enrichment={'reason':'exact_DG_alias_product_and_specification_verified','alias':'DG'+JAN,'compatible_records':[r]})

class MaterialReferenceTests(unittest.TestCase):
    def test_prepare_resolver_revisits_material_after_DG_yd_enrichment(self):
        from interaction.preparation import resolve
        from interaction.preparation_sources import Index
        plain={'jan':JAN,'name':NAME,'spec':'越前龙马贴纸9','source':{'kind':'registry'}}
        order=rec(material=None,price=29,currency='人民币',status='已采购',order_id='TEST',source={'kind':'effective_purchase_order'})
        r=resolve(JAN,Index([plain,order,rec()]),{},[],{'name_ja':'ステッカー'})
        self.assertEqual(r['values']['yd'],'Y1');self.assertEqual(r['values']['price'],'29元')
        self.assertEqual(r['material']['value'],'马口铁,纸')
    def test_verified_dg_original_mixture_is_kept_whole(self):
        r=enrich_material(linked(rec()),{})
        self.assertEqual(r['material']['value'],'马口铁,纸');self.assertFalse(r['material']['confirmed'])
        r=linked(rec());r['dg_enrichment']['reason']='DG_order_product_or_specification_not_verified'
        self.assertEqual(enrich_material(r,{})['material']['value'],'马口铁,纸')
        r=linked(rec(yd='OTHER'));r['dg_enrichment']['reason']='DG_order_product_or_specification_not_verified'
        self.assertIsNone(enrich_material(r,{})['material']['value'])
    def test_verified_pcs_source_requires_same_product_and_spec(self):
        r=row(code_links=[{'jan':'4550621772726','pcs':JAN}],pcs_enrichment={'compatible_records':[rec(jan='4550621772726')]})
        self.assertEqual(enrich_material(r,{})['material']['value'],'马口铁,纸')
    def test_no_prefix_stripping_without_verified_alias(self):
        r=row(sources=[rec()]);self.assertIsNone(enrich_material(r,{})['material']['value'])
    def test_different_product_even_same_jan_and_spec_is_rejected(self):
        r=row(sources=[rec(jan=JAN,name='关于我在无意间被隔壁的天使变成废柴这事 亚克力杯垫 周边预定金')])
        self.assertIsNone(enrich_material(r,{})['material']['value'])
        self.assertEqual(r['material_reference_review']['rejected'][0]['reason'],'different_or_unverified_product_name')
    def test_different_spec_or_version_not_adopted(self):
        for s in ['不二周助贴纸','Vol2整盒']:
            self.assertIsNone(enrich_material(linked(rec(spec=s)),{})['material']['value'])
    def test_yd_product_name_is_verified_not_only_yd(self):
        card={'product_name':'其他商品','material_original':'纸'}
        self.assertIsNone(enrich_material(row(),{'Y1':[card]})['material']['value'])
    def test_full_labelled_yd_collection_preferred_without_assigning_components(self):
        r=linked(rec(material='马口铁,pp'))
        card={'product_name':'模玩熊 '+NAME+'预定金','material_original':'吧唧马口铁，透卡PP','material_cell':'B508'}
        self.assertEqual(enrich_material(r,{'Y1':[card]})['material']['value'],'吧唧马口铁，透卡PP')
    def test_incompatible_material_sources_stay_pending(self):
        r=linked(rec(material='亚克力'));card={'product_name':NAME,'material_original':'纸'}
        self.assertIsNone(enrich_material(r,{'Y1':[card]})['material']['value'])
    def test_existing_reference_or_manual_value_is_never_overwritten(self):
        r=linked(rec());r['material']['value']='人工原文'
        self.assertEqual(enrich_material(r,{})['material']['value'],'人工原文')
        r=linked(rec());r['material']={'value':'纸','raw':'马口铁,纸','status':'user_rule'}
        self.assertEqual(enrich_material(r,{},preserve_existing=False)['material']['value'],'马口铁,纸')
    def test_special_code_requires_context(self):
        r=linked(rec());r['status']='special_identity_requires_context'
        self.assertIsNone(enrich_material(r,{})['material']['value'])
        from interaction.preparation import resolve
        from interaction.preparation_sources import Index
        r=resolve(JAN,Index([rec(jan=JAN),rec(jan=JAN,name='另一个商品')]),{},[],{'name_ja':'特典'})
        self.assertTrue(r['material_reference_review']['executed']);self.assertEqual(r['material_reference_review']['status'],'pending')
    def test_overlay_is_reversible_for_a03_but_does_not_swallow_manual_S_change(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);f=root/'book.xlsx';w=Workbook();s=w.active;s.title='表';s.append([None]*20);s.append([None]*20)
            for a,v in [('C2',JAN),('F2',NAME),('G2','越前龙马贴纸9'),('J2','ステッカー'),('Q2','Y1'),('N2','人工品类'),('O2','人工材质'),('M2','=K2*L2')]:s[a]=v
            w.save(f);values=list(s.values)[1];cfg={'background':d,'sheet':'表'}
            save(root/'material-reference-overlay.json',{'rows':{'2':{'binding':binding(values),'value':'马口铁,纸','before':None}}})
            apply_overlay(cfg,f);book=load_workbook(f);self.assertEqual(book.active['S2'].value,'马口铁,纸');self.assertEqual(book.active['O2'].value,'人工材质');book.close()
            restored=canonical_material_return(cfg,f);book=load_workbook(restored);self.assertIsNone(book.active['S2'].value);self.assertEqual(book.active['M2'].value,'=K2*L2');book.close()
            from interaction.preparation_workbook import update_cells
            f.write_bytes(update_cells(f.read_bytes(),'表',[{'target':'S2','value':'用户新改原文'}]));self.assertEqual(canonical_material_return(cfg,f),f)

if __name__=='__main__':unittest.main()
