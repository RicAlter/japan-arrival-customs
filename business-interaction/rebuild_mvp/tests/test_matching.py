"""Behavioral contracts, not business acceptance of synthetic records."""
import copy
import tempfile
import unittest
from pathlib import Path

from rebuild_mvp.matching import match_batch, _IdentityIndex, _linked, _summary_matches
from rebuild_mvp.sources import validate_source, SourceError, _mapping, ALLOWED, _identity_keys, FORBIDDEN_SOURCE_HASHES


def record(role, row=1, **fields):
    return {'source_id': role + str(row), 'source_sha256': role * 3, 'role': role, 'sheet': 's', 'row': row,
            'fields': fields, 'columns': {f: 'A' for f in fields}, 'scope': {'priority': 0}}


def batch(code='1234567890123', ja='日本名 バージョンA'):
    return {'source': {'sha256': 'rawsha'}, 'sheet': 'invoice', 'rows': [{'row_id': 'row1', 'source_row': 18, 'sheet': 'invoice',
            'raw': {'code': code, 'ja': ja, 'qty': '20', 'amount': '1200', 'jpy_price': '60', 'carton': 'DA01'},
            'raw_cells': {'code': {'column': 'C', 'value': code}}, 'values': {}, 'issues': [], 'evidence': {}}]}


def run(records, source=None):
    return match_batch(source or batch(), {'records': records})[0]


class MatchingContracts(unittest.TestCase):
    def test_product_summary_primary_but_channel_only_procurement(self):
        row = run([record('business_summary', code='1234567890123', name='业务名称', channel='非法渠道'),
                   record('purchase_list', code='1234567890123', name='采购名称', channel='实际渠道', yd='YD1')])
        self.assertEqual(row['values']['name'], '业务名称')
        self.assertEqual(row['values']['channel'], '实际渠道')
        self.assertEqual(row['evidence']['channel'][0]['role'], 'purchase_list')

    def test_pcs_identity_carries_name_without_box_inference(self):
        row = run([record('business_summary', code='9876543210123', pcs='1234567890123', name='盒装名')])
        self.assertEqual(row['matching']['path'], 'business_pcs')
        self.assertEqual(row['values']['name'], '盒装名')
        self.assertNotIn('box_size', row['values'])

    def test_japanese_name_branch_uses_cny_and_does_not_fabricate_jan(self):
        row = run([record('business_summary', code='日本名 バージョンA', lookup_text='日本名 バージョンA', name='中文名'),
                   record('purchase_list', ja='日本名 バージョンA', price='10', currency='人民币', unit='原SKU单位', sku='SKU1')], batch(code=''))
        self.assertEqual(row['matching']['path'], 'business_japanese_name')
        self.assertEqual(row['values']['purchase_price'], '10元')
        self.assertNotIn('jc', row['values'])

    def test_name_branch_does_not_take_jpy_quote(self):
        row = run([record('business_summary', code='日本名 バージョンA', lookup_text='日本名 バージョンA', name='中文名'),
                   record('purchase_list', ja='日本名 バージョンA', price='100', currency='日元', unit='原SKU单位', sku='SKU1')])
        self.assertNotIn('purchase_price', row['values'])

    def test_prior_material_only_and_version_name_mismatch_blocked(self):
        correct = record('prior_material', code='1234567890123', ja='日本名 バージョンA', material='纸', material_reference='纸、PET', name='旧名字', channel='旧渠道', yd='OLD')
        wrong = record('prior_material', 2, code='1234567890123', ja='日本名 バージョンB', material='铁')
        row = run([correct, wrong])
        self.assertEqual(row['values']['material'], '纸')
        self.assertEqual(row['values']['material_reference'], '纸、PET')
        self.assertEqual(row['evidence']['material'][0]['scope']['adoption_kind'], 'inherited_user_authorized_material')
        for field in ('name', 'yd', 'channel'):
            self.assertNotIn(field, row['values'])

    def test_reference_is_not_declaration_material(self):
        row = run([record('business_summary', code='1234567890123', material='亚克力、铁')])
        self.assertEqual(row['values']['material_reference'], '亚克力、铁')
        self.assertNotIn('material', row['values'])

    def test_yd_group_material_reference_cannot_supply_sku_spec(self):
        row = run([record('purchase_list', code='1234567890123', yd='YD1', sku='SKU1'),
                   record('product_card', yd='YD1', material='纸、铁、PET', specification='整盒8个')])
        self.assertEqual(row['values']['material_reference'], '纸、铁、PET')
        self.assertNotIn('specification', row['values'])
        self.assertEqual(row['evidence']['material_reference'][0]['scope']['adoption_scope'], 'yd_collection_reference')

    def test_yd_alone_does_not_mix_other_sku_channels(self):
        row = run([record('purchase_list', code='1234567890123', yd='YD1', sku='SKU1', channel='A'),
                   record('purchase_list', 2, code='9999999999999', yd='YD1', sku='SKU2', channel='B')])
        self.assertEqual(row['values']['channel'], 'A')

    def test_two_prices_or_channels_remain_conflicts(self):
        records = [record('purchase_list', code='1234567890123', yd='YD1', sku='SKU1', channel='A', price='10', currency='CNY', unit='原SKU单位'),
                   record('purchase_list', 2, code='1234567890123', yd='YD1', sku='SKU1', channel='B', price='12', currency='CNY', unit='原SKU单位')]
        row = run(records)
        self.assertNotIn('channel', row['values']); self.assertNotIn('purchase_price', row['values'])
        self.assertTrue(any(i['code'] == 'PROCUREMENT_CONFLICT' for i in row['issues']))

    def test_missing_price_basis_does_not_block_name(self):
        row = run([record('purchase_list', code='1234567890123', name='名称', price='10', currency='CNY')])
        self.assertEqual(row['values']['name'], '名称')
        self.assertNotIn('purchase_price', row['values'])
        self.assertTrue(any(i['code'] == 'PRICE_BASIS_MISSING' for i in row['issues']))

    def test_cancelled_order_not_adopted(self):
        row = run([record('order_detail', code='1234567890123', channel='取消渠道', status='已取消', price='5', currency='CNY', unit='SKU')])
        self.assertNotIn('channel', row['values']); self.assertNotIn('purchase_price', row['values'])

    def test_order_header_cancelled_by_real_id_blocks_quote(self):
        row = run([record('order_detail', code='1234567890123', order_id='PO1', price='5', currency='CNY', unit='SKU', channel='A'),
                   record('purchase_order', order_id='PO1', status='已取消')])
        self.assertNotIn('purchase_price', row['values'])
        self.assertNotIn('channel', row['values'])

    def test_order_header_joins_channel_only_by_actual_order_id(self):
        row = run([record('order_detail', code='1234567890123', order_id='PO1', sku='SKU1'),
                   record('purchase_order', order_id='PO1', channel='实际订单渠道'),
                   record('purchase_order', 2, order_id='SKU1', channel='不可误关联')])
        self.assertEqual(row['values']['channel'], '实际订单渠道')
        self.assertEqual(row['evidence']['channel'][0]['role'], 'purchase_order')

    def test_duplicate_header_aliases_capture_real_cancel_fields(self):
        mapping = _mapping({'I': '状态', 'AA': '是否砍单', 'AB': '砍单数'}, 'order_detail')
        self.assertEqual(mapping['status'], ['I'])
        self.assertEqual(mapping['cancelled'], ['AA'])
        self.assertEqual(mapping['cancelled_qty'], ['AB'])

    def test_input_immutable_and_deterministic_reordered_records(self):
        source = batch(); before = copy.deepcopy(source)
        records = [record('business_summary', name='名', code='1234567890123'), record('daily_material', code='1234567890123', material='纸')]
        self.assertEqual(run(records, source), run(list(reversed(records)), source))
        self.assertEqual(source, before)

    def test_opening_rejected_even_renamed_lineage(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'merged.xlsx'; p.touch()
            for config in ({'path': str(p), 'role': 'product_catalog', 'opening_derived': True},
                           {'path': str(p), 'role': 'product_catalog', 'lineage': '周边开定表2026.xlsx'}):
                with self.assertRaises(SourceError) as caught:
                    validate_source(config)
                self.assertEqual(caught.exception.code, 'SOURCE_FORBIDDEN')

    def test_opening_record_rejected_at_matcher(self):
        with self.assertRaises(SourceError):
            run([record('opening', code='1234567890123', name='不能取')])

    def test_renamed_known_opening_hash_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'renamed.xlsx'; p.touch()
            with self.assertRaises(SourceError) as caught:
                validate_source({'path': str(p), 'role': 'product_catalog', 'sha256': sorted(FORBIDDEN_SOURCE_HASHES)[0]})
            self.assertEqual(caught.exception.code, 'SOURCE_FORBIDDEN')

    def test_pcs_lists_flatten_each_explicit_cell(self):
        codes, _ = _identity_keys({'pcs': ['123,456', '789\n012', '345；678']})
        self.assertEqual(codes, {'123', '456', '789', '012', '345', '678'})

    def test_extraction_issues_preserved_but_stale_match_issues_replaced(self):
        source = batch()
        source['rows'][0]['issues'] = [{'code': 'CARTON_MISSING', 'field': 'carton'},
                                      {'code': 'QUANTITY_MISSING', 'field': 'qty'},
                                      {'code': 'PRODUCT_UNMATCHED', 'field': 'identity'}]
        row = run([record('business_summary', code='1234567890123', name='商品')], source)
        codes = [i['code'] for i in row['issues']]
        self.assertIn('CARTON_MISSING', codes); self.assertIn('QUANTITY_MISSING', codes)
        self.assertNotIn('PRODUCT_UNMATCHED', codes)

    def test_unknown_rule_override_rejected(self):
        with self.assertRaises(SourceError):
            match_batch(batch(), {'records': []}, policy={'fuzzy': True})

    def test_field_permission_excludes_summary_channel_and_card_price(self):
        self.assertNotIn('channel', ALLOWED['business_summary'])
        self.assertNotIn('channel', ALLOWED['product_card'])
        self.assertNotIn('price', ALLOWED['product_card'])
        self.assertEqual(_mapping({'C': '金额（日元', 'D': '数量', 'E': '产品'}, 'business_summary'), {'name': ['E']})

    def test_explicit_sku_catalog_complete_spec_kept(self):
        row = run([record('purchase_list', code='1234567890123', sku='SKU1', yd='YD1'),
                   record('product_catalog', code='SKU1', sku='SKU1', specification='整盒10包，每包3枚入，全35种')])
        self.assertEqual(row['values']['specification'], '整盒10包，每包3枚入，全35种')
        self.assertNotIn('total_pieces', row['values'])

    def test_identity_index_preserves_linear_candidate_semantics(self):
        records = [record('business_summary', code='1234567890123', name='A'),
                   record('business_summary', 2, code='OTHER', pcs=['1234567890123,SECOND'], name='B'),
                   record('business_summary', 3, code='日本名 バージョンA', lookup_text='日本名 バージョンA', name='C'),
                   record('purchase_list', 4, code='OTHER', ja='日本名 バージョンA', sku='SKU1')]
        records.append(copy.deepcopy(records[0]))  # evidence occurrences retained
        index = _IdentityIndex(records)
        for row in (batch()['rows'][0], batch('SECOND')['rows'][0], batch('MISSING')['rows'][0], batch('', 'MISSING')['rows'][0]):
            self.assertEqual(_summary_matches(row, index), _summary_matches(row, records))
            for related in (set(), {'OTHER'}, {'SKU1', 'SECOND'}):
                self.assertEqual(_linked(row, index, related), _linked(row, records, related))


if __name__ == '__main__':
    unittest.main()
