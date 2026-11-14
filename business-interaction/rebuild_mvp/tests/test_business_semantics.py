import unittest
from unittest.mock import patch
from rebuild_mvp.sources import _mapping,_link_departments,_iter_records
from rebuild_mvp.reviewed import enrich_reviewed
from test_reviewed import row,item


def detail(role,fields,number=1):
    return {'role':role,'source_id':role+str(number),'source_sha256':'f'*64,'sheet':'明细','row':number,
            'fields':fields,'columns':{'department':'L'},'scope':{}}


class BusinessSemantics(unittest.TestCase):
    def test_literal_unknown_origin_and_zero_quantity_preserved_for_row_identity(self):
        data=[{'row':1,'values':{'B':'Origin','C':'ProductCode(JANCode)','K':'Qty','H':'采购单价（原计价单位）'}},
              {'row':2,'values':{'B':'无','C':'00123','K':'0','H':'0'}}]
        with patch('rebuild_mvp.sources._sheet_names',return_value=['invoice']),patch('rebuild_mvp.sources._iter_sheet_rows',return_value=iter(data)):
            records=list(_iter_records({'role':'reviewed_basics','path':'fixture.xlsx'},
                         {'source_id':'checked','sha256':'checked'}, {'skipped_sheets':[],'field_maps':[]}))
        self.assertEqual(records[0]['fields']['origin'],'无')
        self.assertEqual(records[0]['fields']['qty'],'0')
        self.assertEqual(records[0]['fields']['reviewed_price'],'0')
    def test_missing_strict_flow_cannot_fall_back_to_old_rules(self):
        from rebuild_mvp.matching import match_batch
        from rebuild_mvp.sources import SourceError
        with patch('rebuild_mvp.matching.Path.read_text',return_value='{"flow":"legacy"}'):
            with self.assertRaises(SourceError) as caught:match_batch({'rows':[]},{'records':[]})
        self.assertEqual(caught.exception.code,'CONFIG_INVALID')
    def test_confirmed_zero_price_is_preserved(self):
        r=row();enrich_reviewed(r,[item(reviewed_price='0')],preserve_confirmed=True)
        self.assertEqual(r['values']['purchase_price'],'0')
    def test_dynamic_summary_columns_follow_business_meaning(self):
        actual=_mapping({'H':'jan code','K':'产品','P':'数量','R':'金额（日元','X':'渠道'},'business_summary')
        self.assertEqual(actual['specification'],['P']);self.assertEqual(actual['price'],['R'])
        self.assertEqual(actual['channel'],['X'])

    def test_model_department_is_bandai_only_with_user_mapping(self):
        purchase=detail('purchase_list',{'sku':'SKU1','yd':'YD1'})
        fact=detail('order_detail',{'sku':'SKU1','yd':'YD1','department':'模型部'})
        _link_departments([purchase,fact])
        self.assertEqual(purchase['fields']['department'],'模型部')
        self.assertEqual(purchase['scope']['canonical_department'],'万代部')
        self.assertEqual(purchase['scope']['department_evidence'][0]['column'],'L')

    def test_department_join_cannot_use_YD_or_order_alone(self):
        purchase=detail('purchase_list',{'sku':'SKU2','yd':'YD1','order_id':'PO1'})
        fact=detail('order_detail',{'sku':'SKU1','yd':'YD1','order_id':'PO1','department':'模型部'})
        _link_departments([purchase,fact])
        self.assertNotIn('department',purchase['fields'])

    def test_confirmed_name_spec_price_channel_remain_intact(self):
        current=row();current['values'].update(name='自动名',specification='自动规格',purchase_price='新价',channel='新渠道',yd='YDNEW')
        approved=item(name='已审核名',specification='已审核规格',reviewed_price='100.12345',channel='已核对渠道',yd='YDOLD')
        enrich_reviewed(current,[approved],preserve_confirmed=True)
        self.assertEqual(current['values']['name'],'已审核名');self.assertEqual(current['values']['specification'],'已审核规格')
        self.assertEqual(current['values']['purchase_price'],'100.12345');self.assertEqual(current['values']['channel'],'已核对渠道')
        self.assertEqual(current['values']['yd'],'YDOLD')
        self.assertIn('yd',current['superseded_automatic_values'])


if __name__=='__main__':unittest.main()
