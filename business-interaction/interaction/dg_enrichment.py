"""Verified DG+JAN purchase references; never globally strip source prefixes."""
from decimal import Decimal
import re
from .preparation_sources import code, unique


def dg_alias(jan):
    if not re.fullmatch(r'\d{13}', jan):
        return None
    digits = [int(c) for c in jan]
    if (sum(digits[::2]) + 3 * sum(digits[1::2])) % 10:
        return None
    return 'DG' + jan


def name_key(value):
    from .matching_repair import norm
    text = norm(value)
    if text.startswith('模玩熊'):
        text = text[len('模玩熊'):]
    text = re.sub(r'(?:预定金|预订金|定金)$', '', text)
    # DG is a sourcing marker here only in the documented trailing DG周边.
    return re.sub(r'dg周边$', '周边', text)


def enrich_dg(result, index, context=None):
    from .matching_repair import spec_same, select_price, norm, currency
    context = context or {}
    jan = result['jan']; alias = dg_alias(jan)
    audit = {'executed': True, 'filled_fields': [], 'replaced_automatic_references': {},
             'quantity_conversion': False, 'automatic_confirmation': False}
    result['dg_enrichment'] = audit
    if not alias:
        audit['reason'] = 'not_a_valid_plain_JAN13'
        return result
    candidates = [r for r in index.lookup(alias)['records']
                  if alias in {code(r.get('jan')), code(r.get('sku'))}]
    audit.update(alias=alias, candidates=candidates)
    if not candidates:
        audit['reason'] = 'no_exact_DG_plus_JAN_source'
        return result
    fields = result['values']
    for field, source in [('channel','source_channel'),('yd','source_yd'),('price','source_purchase_unit_price')]:
        if context.get(source) not in (None, ''):
            fields[field] = context[source]
            audit.setdefault('preserved_source_fields', []).append(field)
    name = context.get('source_internal_name') or fields.get('name')
    spec = context.get('source_specification') or fields.get('spec')
    if result.get('status') in {'special_identity_requires_context', 'special_reference', 'substantive_identity_conflict'} or any(t in str(context.get('name_ja') or '') + str(name or '') for t in ['特典','自编','自編']):
        audit['reason'] = 'special_or_conflicting_identity_requires_review'
        return result
    if not name or not spec:
        audit['reason'] = 'missing_independent_plain_JAN_product_or_specification'
        return result
    compatible = [r for r in candidates if r.get('name') and r.get('spec')
                  and name_key(name) == name_key(r['name']) and spec_same(spec, r['spec'])]
    audit['identity_checks'] = {'reference_name': name, 'reference_spec': spec,
                               'product_name_checked': True, 'specification_checked': True}
    audit['compatible_records'] = compatible
    # An existing alias can itself be reused incorrectly. Do not select an old
    # matching quote while silently ignoring incompatible order observations.
    mismatched_orders = [r for r in candidates
                         if r.get('source', {}).get('kind') == 'effective_purchase_order' and r not in compatible]
    if not compatible or mismatched_orders:
        audit.update(reason='DG_order_product_or_specification_not_verified', rejected_order_records=mismatched_orders)
        return result
    value, review = select_price(alias, compatible, spec)
    audit['order_price_review'] = review
    selected = review.get('selected', {})
    yd = selected.get('yd') if value is not None else unique(compatible, 'yd')
    if not yd:
        audit['reason'] = 'DG_reference_YD_not_uniquely_applicable'
        return result
    if fields.get('yd') not in (None, '', yd):
        audit['reason'] = 'existing_YD_preserved_different_reference'
        return result
    audit.update(reason='exact_DG_alias_product_and_specification_verified', selected_yd=yd)
    if fields.get('yd') in (None, ''):
        fields['yd'] = yd; audit['filled_fields'].append('yd')
    # Prefer the corresponding actual purchase channel for new purchase fills.
    # Source-workbook/manual values take priority over all automatic references.
    needs_purchase_fill = fields.get('price') in (None, '') or 'yd' in audit['filled_fields']
    channel = selected.get('channel') if value is not None else unique([r for r in compatible if r.get('yd') == yd and r.get('status') == '已采购'], 'channel')
    source_channel = context.get('source_channel')
    if needs_purchase_fill and channel and source_channel in (None, ''):
        if fields.get('channel') not in (None, '', channel):
            audit['replaced_automatic_references']['channel'] = fields['channel']
        if fields.get('channel') != channel:
            fields['channel'] = channel; audit['filled_fields'].append('channel')
    if fields.get('price') not in (None, ''):
        audit['existing_price_preserved'] = str(fields['price']) if isinstance(fields['price'], Decimal) else fields['price']
        return result
    if value is not None:
        unit = selected.get('price_unit')
        if not unit and re.search(r'整盒|盒装|盒裝|\bbox\b', str(selected.get('spec') or ''), re.I):
            unit = '盒'
        cur = currency(selected.get('currency'))
        if cur == 'CNY':
            value = format(Decimal(str(selected['price'])).normalize(), 'f') + '元' + ('/盒' if unit == '盒' else '')
        fields['price'] = value
        review.update(category='safe_dg_order_quote', query_jan=jan, source_alias=alias,
                      purchase_unit=unit, quantity_conversion=False, automatic_confirmation=False)
        result['price_review'] = review
        audit['filled_fields'].append('price')
    elif review.get('category') in {'true_price_conflict','unit_or_currency','substantive_identity_conflict'}:
        result['price_review'] = {**review, 'query_jan': jan, 'source_alias': alias}
    return result
