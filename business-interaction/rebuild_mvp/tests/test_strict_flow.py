"""Strict flow regressions: main record authority and permitted fallback only."""
from copy import deepcopy
import unittest

from rebuild_mvp.strict_flow import run_strict


def record(role, number=1, priority=0, scope=None, **fields):
    return {'source_id': role + str(number), 'source_sha256': role + str(number),
            'role': role, 'sheet': 'source', 'row': number, 'fields': fields,
            'columns': {field: {'name': 'D', 'specification': 'E', 'price': 'F', 'channel': 'K'}.get(field, 'A') for field in fields},
            'scope': {'priority': priority, **(scope or {})}}


def batch(code='4573643350147', ja='日文具体商品名', carton='DA01', qty='80'):
    return {'source': {'sha256': 'raw', 'source_id': 'batch'}, 'sheet': 'invoice',
            'rows': [{'row_id': 'one', 'source_row': 18, 'sheet': 'invoice',
                      'raw': {'code': code, 'ja': ja, 'carton': carton, 'qty': qty,
                              'origin': 'JP', 'jpy_price': '4250', 'amount': '340000'},
                      'raw_cells': {'code': {'column': 'C', 'value': code}},
                      'values': {}, 'evidence': {}, 'issues': []}]}


POLICY = {'version': 'strict-test', 'department_aliases': {'模型部': '万代部', '万代部': '万代部', '手办部': '手办部'}}


def run(records, source=None, policy=None):
    return run_strict(source or batch(), {'records': records}, policy or POLICY)[0]


class StrictFlow(unittest.TestCase):
    def test_actual_purchase_without_department_can_supply_YD(self):
        result=run([record('purchase_list',code='4573643350147',name='未知部门候选',yd='YDFIG123')])
        self.assertEqual(result['values']['yd'],'YDFIG123')
        self.assertEqual(result['matching']['path'],'procurement_identity')
    def test_existing_main_category_is_retained_alongside_four_fields(self):
        source=batch()
        main=record('business_summary',code=source['rows'][0]['raw']['code'],name='业务名称',category='业务已填品类')
        result=run_strict(source,{'records':[main]},POLICY)[0]
        self.assertEqual(result['values']['category'],'业务已填品类')
    def test_real_main_record_price_channel_specification_win(self):
        row = run([record('business_summary', code='4573643350147', name='业务商品名', specification='拍立得整盒89', price='2629.1265', currency='JPY', unit='主表SKU原计价单位', channel='arma bianca'),
                   record('purchase_list', code='4573643350147', name='采购名字', specification='其他规格', price='2629.13', currency='JPY', unit='SKU', channel='千秋', yd='YD1')])
        self.assertEqual(row['values']['name'], '业务商品名')
        self.assertEqual(row['values']['specification'], '拍立得整盒89')
        self.assertEqual(row['values']['purchase_price'], '2629.1265日元')
        self.assertEqual(row['values']['channel'], 'arma bianca')
        self.assertEqual(row['evidence']['purchase_price'][0]['column'], 'F')
        self.assertEqual(row['evidence']['channel'][0]['role'], 'business_summary')
        self.assertEqual(row['values']['yd'], 'YD1')

    def test_pcs_uses_same_main_record_four_fields(self):
        row = run([record('business_summary', code='9999999999999', pcs=['4573643350147'], name='PCS名称', specification='套组5个入', price='50.1234', currency='JPY', channel='原渠道')])
        self.assertEqual(row['matching']['path'], 'business_pcs')
        self.assertEqual([row['values'][key] for key in ('name', 'specification', 'purchase_price', 'channel')], ['PCS名称', '套组5个入', '50.1234日元', '原渠道'])

    def test_japanese_name_price_only_purchase_list_cny(self):
        row = run([record('business_summary', code='日文具体商品名', lookup_text='日文具体商品名', name='代购名称', specification='代购规格3个入', price='888', currency='JPY', channel='主表代购渠道'),
                   record('purchase_list', ja='日文具体商品名', sku='SKU1', name='其他采购名', price='23.5', currency='CNY', unit='采购SKU原计价单位', channel='采购渠道'),
                   record('order_detail', ja='日文具体商品名', sku='SKU1', price='1', currency='CNY', unit='SKU', order_id='PO1', channel='订单渠道')])
        self.assertEqual(row['matching']['path'], 'business_japanese_name')
        self.assertEqual(row['values']['purchase_price'], '23.5元')
        self.assertEqual(row['values']['channel'], '主表代购渠道')
        self.assertEqual(row['evidence']['purchase_price'][0]['role'], 'purchase_list')

    def test_name_branch_no_purchase_list_cny_cannot_use_order_or_main(self):
        row = run([record('business_summary', code='日文具体商品名', lookup_text='日文具体商品名', name='代购', price='888', currency='JPY', channel='A'),
                   record('order_detail', ja='日文具体商品名', sku='SKU1', price='1', currency='CNY', unit='SKU', order_id='PO1')])
        self.assertNotIn('purchase_price', row['values'])

    def test_ascii_japanese_title_in_main_lookup_field_is_searched(self):
        row = run([record('business_summary', code='SPIDER MAN RENEWAL Ver.', name='英文官方标题商品', specification='整盒6个', channel='main'),
                   record('purchase_list', ja='SPIDER MAN RENEWAL Ver.', sku='SKU1', price='50', currency='CNY', unit='SKU')],
                  batch(code='UNKNOWN-CODE', ja='SPIDER MAN RENEWAL Ver.'))
        self.assertEqual(row['matching']['path'], 'business_japanese_name')
        self.assertEqual(row['values']['purchase_price'], '50元')
        self.assertEqual(row['matching']['basis'][0]['value'], 'SPIDER MAN RENEWAL Ver.')

    def test_main_explicit_zero_jpy_quote_is_valid(self):
        row = run([record('business_summary', code='4573643350147', name='零价', specification='特典', price='0', currency='JPY', channel='main')])
        self.assertEqual(row['values']['purchase_price'], '0日元')
        self.assertEqual(row['raw']['amount'], '340000')

    def test_main_hit_missing_fields_does_not_fall_through(self):
        row = run([record('business_summary', code='4573643350147', name='主表名'),
                   record('purchase_list', code='4573643350147', department='手办部', name='采购名', specification='采购规格', price='99', currency='CNY', unit='SKU', channel='采购渠道'),
                   record('product_catalog', code='4573643350147', specification='商品库规格')])
        self.assertEqual(row['values']['name'], '主表名')
        self.assertEqual(row['matching']['path'], 'business_code')
        for field in ('specification', 'purchase_price', 'channel'):
            self.assertNotIn(field, row['values'])

    def test_unknown_department_does_not_block_actual_matching_purchase(self):
        row = run([record('purchase_list', code='4573643350147', name='未知部门名', specification='整盒', yd='YDFIG1', brand='万代', price='10', currency='CNY', unit='SKU', channel='B')])
        self.assertEqual(row['values']['name'],'未知部门名')
        self.assertEqual(row['values']['channel'],'B')
        self.assertEqual(row['values']['purchase_price'],'10元')
        self.assertEqual(row['values']['yd'],'YDFIG1')
        self.assertEqual(row['matching']['path'], 'procurement_identity')

    def test_hand_figure_and_authorized_model_department_allowed(self):
        for department in ('手办部', '万代部', '模型部','周边部',''):
            row = run([record('purchase_list', code='4573643350147', name='部门商品', sku='SKU1', sku_name='订单A整盒6个入', department=department, price='60', currency='CNY', unit='SKU', channel='实际渠道')])
            self.assertEqual(row['values']['name'], '部门商品')
            self.assertEqual(row['values']['specification'], '订单A整盒6个入')
            self.assertEqual(row['matching']['path'], 'procurement_identity')
            self.assertEqual(row['matching']['basis'][0]['value'], '4573643350147')

    def test_department_alias_not_required_for_product_adoption(self):
        row = run([record('purchase_list', code='4573643350147', name='不能擅自映射', department='模型部')], policy={'version': 'no-alias'})
        self.assertEqual(row['values']['name'],'不能擅自映射')

    def test_real_department_evidence_allowed_without_named_department_cell(self):
        row = run([record('purchase_list', code='4573643350147', name='实际关联', scope={'department_evidence': [{'value': '手办部', 'column': 'L', 'row': 5}]})])
        self.assertEqual(row['values']['name'], '实际关联')

    def test_department_fallback_header_channel_requires_eligible_real_order(self):
        row = run([record('order_detail', code='4573643350147', sku='SKU1', name='手办商品', department='手办部', order_id='PO1'),
                   record('purchase_order', order_id='PO1', channel='真实订单渠道'),
                   record('purchase_order', 2, order_id='SKU1', channel='不能把SKU当订单号')])
        self.assertEqual(row['values']['channel'], '真实订单渠道')
        self.assertEqual(row['evidence']['channel'][0]['role'], 'purchase_order')

    def test_other_department_procurement_allowed_catalog_stays_reference(self):
        row = run([record('order_detail', code='4573643350147', name='周边采购', department='周边部'),
                   record('product_catalog', code='4573643350147', name='商品导出名', specification='商品导出规格')])
        self.assertEqual(row['values']['name'],'周边采购'); self.assertNotIn('specification', row['values'])
        self.assertEqual(len(row['unadopted_candidates']), 1)

    def test_purchase_list_title_not_confused_with_order_deposit_label(self):
        row=run([record('purchase_list',code='4573643350147',name='中文名'),record('order_detail',code='4573643350147',name='模玩熊 中文名预定金')])
        self.assertEqual(row['values']['name'],'中文名')

    def test_japanese_exact_title_in_main_name_column(self):
        row=run([record('business_summary',code='OTHER-CODE',name='日文具体商品名',specification='一套3个',channel='主表')])
        self.assertEqual(row['matching']['path'],'business_japanese_name')
        self.assertEqual(row['matching']['basis'][0]['source_field'],'name')

    def test_unrelated_purchase_not_adopted_without_department_gate(self):
        row=run([record('purchase_list',code='UNRELATED',name='不同商品',yd='YD2026010101')])
        self.assertNotIn('name',row['values'])
        self.assertEqual(row['matching']['path'],'unresolved')

    def test_same_version_ambiguous_main_preserves_only_common_fields(self):
        row = run([record('business_summary', code='4573643350147', name='同名', specification='套组3个', price='30', currency='JPY', channel='A'),
                   record('business_summary', 2, code='4573643350147', name='同名', specification='套组5个', price='50', currency='JPY', channel='A')])
        self.assertEqual(row['values']['name'], '同名'); self.assertEqual(row['values']['channel'], 'A')
        self.assertNotIn('specification', row['values']); self.assertNotIn('purchase_price', row['values'])

    def test_missing_cells_cannot_form_nonexistent_cross_row_tuple(self):
        row = run([record('business_summary', code='4573643350147', name='名', specification='', price='30', currency='JPY', channel=''),
                   record('business_summary', 2, code='4573643350147', name='', specification='规格', price='', currency='JPY', channel='B')])
        for field in ('name', 'specification', 'purchase_price', 'channel'):
            self.assertNotIn(field, row['values'])

    def test_reviewed_spec_selects_exact_main_record_and_preserves_manual(self):
        old = record('reviewed_basics', code='4573643350147', ja='日文具体商品名', carton='DA01', origin='JP', qty='80', name='已确认名称', specification='拍立得整盒89', yd='YDCONFIRMED', material='纸')
        row = run([old,
                   record('business_summary', code='4573643350147', name='自动名称', specification='拍立得整盒89', price='2629.1265', currency='JPY', channel='arma bianca'),
                   record('business_summary', 2, code='4573643350147', name='自动名称', specification='其他规格', price='100', currency='JPY', channel='其他渠道'),
                   record('purchase_list', code='4573643350147', yd='YDAUTO')])
        self.assertEqual(row['values']['name'], '已确认名称')
        self.assertEqual(row['values']['specification'], '拍立得整盒89')
        self.assertEqual(row['values']['yd'], 'YDCONFIRMED')
        self.assertEqual(row['values']['purchase_price'], '2629.1265日元')
        self.assertEqual(row['values']['channel'], 'arma bianca')
        self.assertEqual(row['values']['material'], '纸')

    def test_reviewed_different_shipment_cannot_select_main_spec(self):
        old = record('reviewed_basics', code='4573643350147', ja='日文具体商品名', carton='OTHER', origin='JP', qty='80', specification='甲规格')
        row = run([old, record('business_summary', code='4573643350147', specification='甲规格'),
                   record('business_summary', 2, code='4573643350147', specification='乙规格')])
        self.assertNotIn('specification', row['values'])
        self.assertIsNone(row['matching']['record_selection'])

    def test_reviewed_price_channel_kept_without_currency_reinterpretation(self):
        old = record('reviewed_basics', code='4573643350147', ja='日文具体商品名', carton='DA01', origin='JP', qty='80',
                     reviewed_price='2629.1265', channel='人工渠道')
        row = run([old, record('business_summary', code='4573643350147', name='主表', specification='规格', price='2629.13', currency='JPY', channel='主表渠道')])
        self.assertEqual(row['values']['purchase_price'], '2629.1265')
        self.assertEqual(row['values']['channel'], '人工渠道')
        self.assertEqual(row['evidence']['purchase_price'][0]['source_field'], 'reviewed_price')
        self.assertFalse(row['main_candidates_for_confirmed_fields']['purchase_price']['automatic_override'])
        self.assertEqual(row['main_candidates_for_confirmed_fields']['channel']['candidates'][0]['value'], '主表渠道')
        self.assertEqual(row['master_candidates'][0]['fields']['price'], '2629.13')
        self.assertEqual(row['master_candidates'][0]['evidence']['purchase_price']['column'], 'F')

    def test_confirmed_spec_selects_older_matching_record_before_version_rank(self):
        old = record('reviewed_basics', code='4573643350147', ja='日文具体商品名', carton='DA01', origin='JP', qty='80', specification='已确认规格')
        row = run([old,
                   record('business_summary', priority=0, code='4573643350147', specification='新版其他规格', price='99', currency='JPY', channel='新渠道'),
                   record('business_summary', 2, priority=10, code='4573643350147', specification='已确认规格', price='55', currency='JPY', channel='已对应渠道')])
        self.assertEqual(row['values']['specification'], '已确认规格')
        self.assertEqual(row['values']['purchase_price'], '55日元')
        self.assertEqual(row['values']['channel'], '已对应渠道')
        self.assertEqual(row['matching']['record_selection']['source_priority'], 10)
        self.assertEqual([record['selected'] for record in row['master_candidates']], [False, True])

    def test_conflicting_reviewed_field_cannot_be_silently_replaced_automatically(self):
        old = record('reviewed_basics', code='4573643350147', ja='日文具体商品名', carton='DA01', origin='JP', qty='80', specification='人工规格一')
        other = record('reviewed_basics', 2, code='4573643350147', ja='日文具体商品名', carton='DA01', origin='JP', qty='80', specification='人工规格二')
        row = run([old, other, record('business_summary', code='4573643350147', specification='自动规格', name='主表名')])
        self.assertNotIn('specification', row['values'])
        self.assertTrue(any(issue['code'] == 'REVIEWED_FIELD_CONFLICT' for issue in row['issues']))
        self.assertEqual(row['values']['name'], '主表名')

    def test_raw_and_record_order_determinism(self):
        source = batch(); before = deepcopy(source)
        records = [record('business_summary', code='4573643350147', name='同名', specification='规格', price='9', currency='JPY', channel='A'),
                   record('daily_material', code='4573643350147', material='亚克力')]
        self.assertEqual(run(records, source), run(list(reversed(records)), source))
        self.assertEqual(source, before)


if __name__ == '__main__':
    unittest.main()
