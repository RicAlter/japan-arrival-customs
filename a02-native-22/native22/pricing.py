"""Port of the authorized rounding example; never a B-stage pricing engine."""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from .support import Rejected, key


def decimal(value):
    if value is None or isinstance(value, bool) or str(value).strip() == '': return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def price(value):
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate(g, n, h, inferred):
    """Same order and half-up behavior as the approved v2 example."""
    if g is None or n is None or g < 0 or n <= 0 or price(n) <= 0:
        return None, None, 'price_input_unavailable'
    candidate = (price(g)/price(n)).quantize(Decimal(1), rounding=ROUND_HALF_UP) if inferred else h
    if candidate is None or candidate <= 0 or candidate != candidate.to_integral_value():
        return candidate, None, 'rounded_packaging_not_positive_integer'
    difference = price(price(g)-price(n)*candidate)
    return candidate, difference, 'exceeds_100_jpy' if abs(difference) > 100 else 'within_100_jpy'


def mapping(source):
    if source['profile_id'] == 'kmt-native-22-v1': return {'purchase': 'G', 'comparison': 'N', 'box': 'H', 'difference': 'U'}
    if source['profile_id'] == 'kmt-native-16-v1': return {'purchase': 'G', 'comparison': 'K', 'box': 'H', 'difference': None}
    return None


def bind_basis(config, source):
    if config is None: return {'status': 'not_bound', 'reason': '价格口径未绑定，本批不做价格通过判断'}
    columns = mapping(source)
    required = {'schema', 'source_sha256', 'currency', 'purchase_column', 'comparison_column',
                'purchase_role', 'comparison_role', 'evidence_ref'}
    if not isinstance(config, dict) or set(config) != required or columns is None:
        raise Rejected('价格口径须明确绑定支持格式的原件、列角色、币种和真实依据')
    if (config['schema'] != 'a-price-basis/1' or config['source_sha256'] != source['book'].sha256
            or config['currency'] != 'JPY' or config['purchase_column'] != columns['purchase']
            or config['comparison_column'] != columns['comparison']
            or config['purchase_role'] != 'purchase_price_reference'
            or config['comparison_role'] != 'source_business_unit_price'
            or not isinstance(config['evidence_ref'], str) or not config['evidence_ref'].strip()):
        raise Rejected('价格口径/原件绑定不符；禁止将零售价、最终金额或日方价冒充采购价')
    return {'status': 'bound_to_dialogue_basis', 'binding': config, 'approval': False, 'local_host_identity_verified': False}


def normalized(formula):
    return re.sub(r'[\s$]', '', formula or '').upper()


def analyze(source, sheet, fields, basis, *, manual=None, box_proposals=None):
    columns = mapping(source); manual = manual or {}; box_proposals = box_proposals or {}
    report = {'schema': 'a-box-price-check/1', 'profile_id': source['profile_id'], 'basis': basis,
              'rows': [], 'groups': [], 'program_groups': [], 'counts': {}, 'display_marks': [],
              'actual_human_actions': None, 'business_exception_total': None,
              'confirmed': False, 'can_enter_b': False, 'qty_unit_inferred': False}
    if columns is None: return report
    if basis['status'] != 'bound_to_dialogue_basis':
        report['groups'] = [{'kind': 'batch_price_basis_missing', 'group_count': 1,
                             'affected_rows': len(source['rows']), 'row_ids': [r['row_id'] for r in source['rows']]}]
        return report
    fs = {(f['row_id'], f['field']): f for f in fields}; issues = defaultdict(list); handled = defaultdict(list)
    counts = Counter()
    for row in source['rows']:
        n = row['source_row']; rid = row['row_id']; gaddr = columns['purchase']+str(n)
        paddr = columns['comparison']+str(n); haddr = columns['box']+str(n)
        uaddr = columns['difference']+str(n) if columns['difference'] else None
        original = source['sheet'].cells.get(haddr, {}); old_formula = original.get('f')
        inferred = bool(old_formula); hf = normalized(old_formula)
        supported = not inferred or hf == f'={gaddr}/{paddr}'
        get = lambda address: sheet.cells.get(address, {}).get('v')
        original_values = {'g': get(gaddr), 'n': get(paddr), 'h': get(haddr)}
        changed = manual.get(rid, {})
        # Monetary source text/blanks are not silently coerced to guessed prices.
        g = decimal(changed['purchase_unit_price']) if 'purchase_unit_price' in changed else (
            original_values['g'] if isinstance(original_values['g'], Decimal) else None)
        np = original_values['n'] if isinstance(original_values['n'], Decimal) else None
        h = decimal(changed.get('pieces_per_box', original_values['h']))
        if rid in box_proposals: h = decimal(box_proposals[rid]); inferred_for_calc = False
        else: inferred_for_calc = inferred and 'pieces_per_box' not in changed
        reason = None
        if not supported: reason = 'unsupported_original_packaging_formula'
        uold = source['sheet'].cells.get(uaddr, {}).get('f') if uaddr else None
        if uold and normalized(uold) not in (f'={gaddr}-{paddr}', f'={gaddr}-{paddr}*{haddr}'):
            reason = 'unsupported_original_difference_formula'
        if uaddr and not uold and source['sheet'].cells.get(uaddr, {}).get('v') not in (None, ''):
            reason = 'unsupported_original_difference_value'
        candidate = difference = None
        if reason is None:
            candidate, difference, status = calculate(g, np, h, inferred_for_calc)
        else: status = reason
        pending = None
        if fs.get((rid, 'purchase_unit_price'), {}).get('status') == 'candidate': pending = 'purchase_price_candidate_not_adopted'
        if fs.get((rid, 'pieces_per_box'), {}).get('status') == 'candidate': pending = 'packaging_candidate_not_adopted'
        if 'purchase_unit_price' in changed: pending = 'manual_purchase_price_pending_source'
        if any(k in changed for k in ('product_code', 'specification')): pending = 'identity_context_changed_pending_basis'
        if 'pieces_per_box' in changed or rid in box_proposals: pending = 'manual_packaging_pending_confirmation'
        if pending:
            status = pending
        record = {'row_id': rid, 'source_row': n, 'g_cell': gaddr, 'comparison_cell': paddr,
                  'h_cell': haddr, 'u_cell': uaddr, 'mode': 'inferred' if inferred else 'literal',
                  'status': status, 'pieces_per_box': str(candidate) if candidate is not None else None,
                  'difference_jpy': str(difference) if difference is not None else None,
                  'source_purchase_observation': str(original_values['g']),
                  'source_comparison_observation': str(original_values['n']),
                  'g_calculation_price': str(price(g)) if g is not None else None,
                  'comparison_calculation_price': str(price(np)) if np is not None else None,
                  'formula_rewrite_allowed': supported and reason is None and not pending,
                  'reference_preview_only': True, 'confirmed': False, 'hypothetical_only': bool(pending)}
        report['rows'].append(record); counts[status] += 1
        if status == 'within_100_jpy':
            handled['rounded_inference_with_price_check' if inferred else 'literal_packaging_price_check'].append(rid)
        else:
            issues[status].append(rid)
            report['display_marks'].append({'row_id': rid, 'cell': uaddr or haddr, 'color': 'red', 'reason': status})
            if status != 'exceeds_100_jpy' and uaddr:
                report['display_marks'].append({'row_id': rid, 'cell': haddr, 'color': 'red', 'reason': status})
    report['counts'] = dict(counts)
    report['groups'] = [{'kind': kind, 'group_id': key([source['book'].sha256, kind]),
                         'affected_rows': len(ids), 'row_ids': ids} for kind, ids in issues.items()]
    report['program_groups'] = [{'kind': kind, 'affected_rows': len(ids), 'row_ids': ids} for kind, ids in handled.items()]
    report['affected_price_rows'] = sum(v for k, v in counts.items() if k != 'within_100_jpy')
    return report


def formula_plan(report):
    result = {}
    for r in report['rows']:
        if not r['formula_rewrite_allowed']: continue
        g, p, h, u = (r[k] for k in ('g_cell', 'comparison_cell', 'h_cell', 'u_cell'))
        prices_ok = f'ISNUMBER({g}),ISNUMBER({p}),{g}>=0,ROUND({p},2)>0'
        if r['mode'] == 'inferred':
            result[h] = {'formula': f'=IFERROR(IF(AND({prices_ok}),ROUND(ROUND({g},2)/ROUND({p},2),0),""),"")',
                         'value': decimal(r['pieces_per_box'])}
        if u:
            result[u] = {'formula': f'=IFERROR(IF(AND({prices_ok},{h}*1>0,{h}*1=ROUND({h}*1,0)),ROUND(ROUND({g},2)-ROUND({p},2)*{h},2),""),"")',
                         'value': decimal(r['difference_jpy'])}
    return result
