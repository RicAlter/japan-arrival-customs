"""Complete references through a sourced, unique pcs-to-main JAN relationship.

This is reference enrichment only. No arrival-quantity conversion or approval.
"""
from copy import deepcopy
import re
from .preparation_sources import code, unique


def enrich_linked(result, hit, context=None):
    from .matching_repair import select_price, spec_same, norm
    jan = result['jan']
    audit = {'executed': True, 'filled_fields': [], 'quantity_conversion': False,
             'automatic_confirmation': False}
    result['pcs_enrichment'] = audit
    links = [r for r in hit['links'] if code(r.get('pcs')) == jan
             and code(r.get('jan')) not in ('', jan)]
    if not links:
        audit['reason'] = 'no_sourced_pcs_to_main_relationship'
        return result
    mains = {code(r['jan']) for r in links}
    if len(mains) != 1 or hit['status'] == 'box_code_conflict':
        audit['reason'] = 'multiple_main_codes_require_review'
        return result
    if result.get('status') in {'special_identity_requires_context', 'special_reference',
                                 'substantive_identity_conflict'}:
        audit['reason'] = 'identity_requires_review'
        return result
    main = next(iter(mains))
    fields = result['values']
    spec = (context or {}).get('spec') or fields.get('spec') or unique(links, 'spec')
    if not spec:
        audit['reason'] = 'missing_product_specification'
        return result
    related = [r for r in hit['related']
               if main in {code(r.get('jan')), code(r.get('sku'))}
               and r.get('spec') and spec_same(spec, r['spec'])]
    audit.update(main_jan=main, link_sources=links, compatible_records=related)
    if not related:
        audit['reason'] = 'no_specification_compatible_main_record'
        return result
    # Same-code reorders are normal. Choose one traceable reference identity;
    # preserve every other identity in the audit, without mixing their pictures.
    yd = fields.get('yd') or unique(related, 'yd')
    if not yd:
        audit['reason'] = 'multiple_related_YDs_without_unique_applicable_reference'
        return result
    compatible = [r for r in related if r.get('yd') == yd]
    audit.update(selected_yd=yd, reason='unique_sourced_pcs_main_and_matching_specification')
    for field in ('name', 'spec', 'channel', 'yd'):
        value = yd if field == 'yd' else unique(compatible, field)
        if fields.get(field) in (None, '') and value not in (None, ''):
            fields[field] = value
            audit['filled_fields'].append(field)
    # Use a related image only for this concrete JAN/spec/YD, never a YD-wide image.
    image = unique(compatible, 'image')
    if not result.get('image') and image:
        result.update(image=image, box_image=True, image_scope='box_reference')
        audit['filled_fields'].append('image')
        audit['image_sources'] = [r for r in compatible if r.get('image') == image]
    if fields.get('price') not in (None, ''):
        return result
    orders = []
    for record in related:
        if record.get('source', {}).get('kind') != 'effective_purchase_order':
            continue
        r = deepcopy(record)
        explicit = norm(r.get('price_unit'))
        if explicit in {'盒', 'box'}:
            r['price_unit'] = '盒'
            r['price_unit_evidence'] = {'field': 'price_unit', 'source': r['source']}
        elif not explicit and re.search(r'整盒|盒装|盒裝|\bbox\b', str(r.get('spec') or ''), re.I):
            r['price_unit'] = '盒'
            r['price_unit_evidence'] = {'field': 'spec', 'text': r['spec'], 'source': r['source']}
        orders.append(r)
    value, review = select_price(main, orders, spec)
    audit['linked_order_price_review'] = review
    # A sourced code relationship is not itself evidence for a pricing unit.
    selected = review.get('selected', {})
    if value is not None and selected.get('price_unit') == '盒':
        review.update(category='safe_linked_box_order_quote', query_pcs_jan=jan,
                      main_jan=main, purchase_unit='盒', quantity_conversion=False,
                      automatic_confirmation=False)
        fields['price'] = value + '/盒' if isinstance(value, str) else value
        result['price_review'] = review
        audit['filled_fields'].append('price')
    else:
        audit['price_not_filled_reason'] = review.get('reason') if value is None else 'linked_order_pricing_unit_not_explicit_box'
        if review.get('category') in {'true_price_conflict', 'substantive_identity_conflict', 'unit_or_currency'}:
            result['price_review'] = {**review, 'query_pcs_jan': jan, 'main_jan': main}
    return result
