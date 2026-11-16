"""Evidence-scoped quantity arithmetic; no price input and no workbook columns.

Fraction arithmetic and explicit layer parsing adapted from stage2_math at
980984e (fixed-sku-packaging/20261112). No calculate(), price guards or legacy
approval/state code is imported. Parsing is deliberately narrower than prose.
"""
from fractions import Fraction
import re
import unicodedata

POLICY = 'sku-quantity-layers/1'
UNITS = ('piece', 'pack', 'box', 'set', 'carton')
LABELS = {'piece': '个', 'pack': '包', 'box': '盒', 'set': '套', 'carton': '运输箱'}
PRODUCT_KINDS = ['姓名吧唧','文件夹','吧唧','冰箱贴','徽章','透卡','贴纸','明信片','立牌','拍立得','相卡','挂件','卡片','收藏卡','亚克力']
TOKENS = {'piece': r'枚|张|個|个|件|ピース', 'pack': r'包|袋|パック',
          'box': r'盒|BOX|ボックス', 'set': r'套|セット', 'carton': r'运输箱|外箱|カートン'}


def product_kinds(text):
    found = [k for k in PRODUCT_KINDS if k in str(text)]
    if any('吧唧' in k for k in found):
        found = [k for k in found if k != '徽章']
    return [k for k in found if not any(k != other and k in other for other in found)]


def title_key(text):
    """Historical SOP's fixed sales-label normalization; keep all SKU versions."""
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text)))
    text = re.sub(r'^模玩熊', '', text)
    return re.sub(r'(?:预定金|追定金|预金)$', '', text)


def number(value):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        return None
    try:
        return Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def exact(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def parse_layers(text):
    """Only explicit 1/每/整盒/1BOX relations, never varieties/components/tails."""
    text = unicodedata.normalize('NFKC', str(text))
    result = []
    for outer in UNITS[1:]:
        for inner in UNITS:
            if outer == inner:
                continue
            start = rf'(?:1\s*(?:{TOKENS[outer]})|每\s*(?:{TOKENS[outer]}))'
            if outer == 'box':
                start += r'|整盒'
            pattern = rf'(?:{start})\s*(?:に|あたり|[:：=])?\s*(\d+)\s*(?:{TOKENS[inner]})(?:入|入り)?'
            for match in re.finditer(pattern, text, re.I):
                count = int(match[1])
                if count > 0:
                    result.append({'outer': outer, 'inner': inner, 'count': str(count),
                                   'original': match[0]})
    return [dict(t) for t in sorted({tuple(sorted(x.items())) for x in result})]


def calculate(quantity, facts, existing=None):
    """facts are already coordinate/identity checked by quantity_sources.

    Returns field-local usable results; conflicting graph components alone are
    unusable. Existing explicit observations remain separate from derived values.
    """
    existing = existing or {}
    issues, accepted, rejected = [], [], []
    graph = {u: [] for u in UNITS}
    for relation in facts.get('relations', []):
        outer, inner, count = relation['outer'], relation['inner'], number(relation['count'])
        if outer not in UNITS or inner not in UNITS or outer == inner or not count or count <= 0 or count.denominator != 1:
            issues.append({'code': 'PACKAGING_INVALID', 'field': 'relations'})
            rejected.append(relation)
            continue
        accepted.append(dict(relation))
        graph[outer].append((inner, 1 / count))
        graph[inner].append((outer, count))
    # potential[node] is the number of reference-component units in one node.
    potentials, components, conflicts = {}, {}, set()
    for start in UNITS:
        if start in potentials:
            continue
        cid = start
        potentials[start] = Fraction(1)
        components[start] = cid
        queue = [start]
        while queue:
            outer = queue.pop(0)
            for inner, divisor in graph[outer]:
                expected = potentials[outer] * divisor
                if inner in potentials:
                    if potentials[inner] != expected:
                        conflicts.add(cid)
                else:
                    potentials[inner] = expected
                    components[inner] = cid
                    queue.append(inner)
    if conflicts:
        issues.append({'code': 'PACKAGING_CONFLICT', 'field': 'relations',
                       'components': sorted(conflicts)})

    def ratio(outer, inner):
        if components[outer] != components[inner] or components[outer] in conflicts:
            return None
        return potentials[outer] / potentials[inner]

    q = number(quantity)
    qty_unit = facts.get('qty_unit', {}).get('unit')
    valid_quantity = q is not None and q > 0
    if not valid_quantity:
        issues.append({'code': 'QUANTITY_ZERO' if q == 0 else 'QUANTITY_INVALID', 'field': 'raw_quantity'})
    elif q.denominator != 1 and not facts.get('allow_split_quantity'):
        valid_quantity = False
        issues.append({'code': 'QUANTITY_FRACTION_UNPROVEN', 'field': 'raw_quantity'})
    if qty_unit not in UNITS:
        qty_unit = None
        issues.append({'code': 'QUANTITY_UNIT_MISSING', 'field': 'raw_unit'})

    observations = {}
    for name, unit in [('total_pieces', 'piece'), ('box_count', 'box')]:
        observation = facts.get('observations', {}).get(name)
        if observation:
            n = number(observation['value'])
            if n is not None and n > 0 and (name != 'total_pieces' or n.denominator == 1):
                observations[name] = {**observation, 'unit': unit, 'exact': exact(n)}
            else:
                issues.append({'code': 'OBSERVATION_INVALID', 'field': name})

    seeds = []
    if valid_quantity and qty_unit:
        seeds.append((qty_unit, q, 'raw_quantity'))
    if 'total_pieces' in observations:
        seeds.append(('piece', number(observations['total_pieces']['value']), 'total_pieces'))
    if 'box_count' in observations:
        seeds.append(('box', number(observations['box_count']['value']), 'box_count'))
    for candidate in facts.get('observation_candidates', []):
        unit = {'total_pieces':'piece','box_count':'box'}.get(candidate['field'])
        n = number(candidate['value'])
        if unit and n is not None and n > 0:
            seeds.append((unit,n,'independent_observation'))
    results, states = {}, {}
    for unit in UNITS:
        values = {(n * factor) for source, n, _ in seeds if (factor := ratio(source, unit)) is not None}
        if len(values) > 1:
            states[unit] = 'conflict'
            issues.append({'code': 'QUANTITY_CONFLICT', 'field': unit})
        elif values:
            value = next(iter(values))
            if unit == 'piece' and value.denominator != 1:
                states[unit] = 'conflict'
                issues.append({'code': 'PIECES_NOT_INTEGER', 'field': unit})
            else:
                results[unit] = exact(value)
                states[unit] = 'inherited' if (unit == qty_unit or any(o['unit'] == unit for o in observations.values())) else 'derived'
        else:
            states[unit] = 'conflict' if components[unit] in conflicts else 'pending'
    # A contradictory protected value may not be silently bypassed downstream.
    for col, unit in [('U', 'box'), ('X', 'piece')]:
        if col in existing and existing[col] not in ('', None):
            old = number(existing[col])
            value = results.get(unit)
            if value and (old is None or old != Fraction(int(value['numerator']), int(value['denominator']))):
                results.pop(unit, None)
                states[unit] = 'conflict'
                issues.append({'code': 'PROTECTED_VALUE_CONFLICT', 'field': unit, 'column': col})

    pieces_per_box = ratio('box', 'piece')
    remainder = None
    if results.get('piece') and pieces_per_box and pieces_per_box.denominator == 1 and states['box'] != 'conflict':
        s = Fraction(int(results['piece']['numerator']), int(results['piece']['denominator']))
        boxes, rest = divmod(s, pieces_per_box)
        remainder = {'whole_boxes': str(boxes), 'remaining_pieces': exact(rest)}
    v_unit = facts.get('v_unit')
    v_size = ratio(v_unit, 'piece') if v_unit in UNITS[1:] else None
    if existing.get('V') not in ('', None) and v_size is not None and number(existing['V']) != v_size:
        # Remove only results relying on this protected conflicting packaging component.
        blocked = components[v_unit]
        for unit in list(results):
            if components[unit] == blocked and states[unit] == 'derived':
                results.pop(unit)
                states[unit] = 'conflict'
        issues.append({'code': 'PROTECTED_PACKAGING_CONFLICT', 'field': 'v_size'})
        v_size, remainder = None, None
        if pieces_per_box is not None and components['box'] == blocked:
            pieces_per_box = None
    if pieces_per_box is None:
        issues.append({'code': 'BOX_RULE_MISSING', 'field': 'pieces_per_box'})
    if v_unit is None and existing.get('V') not in ('', None):
        issues.append({'code': 'V_UNIT_MISSING', 'field': 'v_size'})
    for relation in accepted:
        relation['adoption_state'] = 'conflict' if components[relation['outer']] in conflicts else 'source_checked'
    return {'raw_quantity': quantity, 'raw_unit': facts.get('qty_unit'),
            'observations': observations, 'observation_candidates':facts.get('observation_candidates',[]),
            'relations': accepted, 'rejected_candidates': rejected,
            'results': results, 'field_states': states,
            'pieces_per_box': exact(pieces_per_box) if pieces_per_box is not None else None,
            'v_unit': v_unit, 'v_size': exact(v_size) if v_size is not None else None,
            'blind': facts.get('blind'), 'remainder': remainder, 'issues': issues,
            'status': 'partial' if issues else 'completed'}
