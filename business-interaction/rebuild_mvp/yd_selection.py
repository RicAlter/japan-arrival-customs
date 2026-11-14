"""User-confirmed YD dates and field-local exceptions; no model decisions."""
from collections import defaultdict
from datetime import datetime
import re

from .sources import norm, known, code, _identity_keys
from .matching import _choose, _ref, _sku_specification


def yd_date(value):
    match = re.fullmatch(r'YD[A-Z]*((?:19|20)\d{6})\d*', norm(value).upper())
    if not match:
        return None
    try:
        return datetime.strptime(match[1], '%Y%m%d').date().isoformat()
    except ValueError:
        return None


def special_benefit(row, policy):
    text = ' '.join(norm(v) for v in [row['raw'].get('ja'), row['values'].get('name'), row['values'].get('category')])
    return next((term for term in policy.get('yd_selection', {}).get('optional_benefit_markers', []) if term in text), None)


def choose_yd(row, records, policy):
    """Latest dated reissue only within an evidenced same-code SKU descriptor."""
    if row['values'].get('yd'):
        return True
    candidates = [r for r in records if known(r['fields'].get('yd'))]
    groups = defaultdict(list)
    for record in candidates:
        groups[norm(record['fields']['yd'])].append(record)
    settings = policy.get('yd_selection', {})
    if len(groups) > 1 and settings.get('reissue_rule') == 'latest_valid_embedded_date_same_product_pack':
        dates = {yd: yd_date(yd) for yd in groups}
        incoming = code(row['raw'].get('code'))
        # Every YD must be anchored to the actual incoming code, not a YD group
        # name or an inferred SKU-prefix transformation.
        anchored = incoming and all(any(incoming in _identity_keys(r['fields'])[0] for r in group) for group in groups.values())
        descriptors = set()
        complete = True
        for group in groups.values():
            values = {norm(r['fields'].get('specification') or r['fields'].get('sku_name')) for r in group
                      if known(r['fields'].get('specification')) or _sku_specification(r)}
            if len(values) != 1:
                complete = False
            descriptors.update(values)
        packaging = {norm(r.get('scope', {}).get('packaging_unit')) for r in candidates if known(r.get('scope', {}).get('packaging_unit'))}
        if anchored and complete and len(descriptors) == 1 and len(packaging) <= 1 and all(dates.values()):
            newest = max(dates.values())
            newest_yds = [yd for yd, date in dates.items() if date == newest]
            if len(newest_yds) == 1:
                selected = newest_yds[0]
                text = ' '.join([norm(row['values'].get('name')), norm(row['raw'].get('ja'))] + [norm(r['fields'].get('name')) for r in groups[selected]])
                markers = [m for m in settings.get('reissue_markers', []) if m.lower() in text.lower()]
                if markers:
                    if _choose(row, 'yd', groups[selected], prefer_source_priority=False):
                        decision = {'rule': settings['reissue_rule'], 'authority': 'user: 再版取新的YD，YD内YYYYMMDD代表时间',
                                    'selected_yd': selected, 'selected_date': newest, 'sku_descriptor': next(iter(descriptors)),
                                    'reissue_markers': markers,
                                    'candidates': [{'yd': yd, 'date': dates[yd], 'sources': [_ref(r, 'yd') for r in group]} for yd, group in sorted(groups.items())]}
                        row['yd_selection'] = decision
                        for ref in row['evidence']['yd']:
                            ref['scope']['yd_selection_rule'] = decision['rule']
                            ref['scope']['yd_embedded_date'] = newest
                        return True
    return _choose(row, 'yd', candidates, prefer_source_priority=False)


def exempt_missing_benefit_yd(row, policy):
    marker = special_benefit(row, policy)
    if row['values'].get('yd') or not marker:
        return False
    row['yd_requirement'] = {'status': 'not_required', 'kind': 'special_benefit', 'marker': marker,
                             'authority': 'user: 特典类的没有YD可以排除',
                             'row_retained': True, 'raw_values_unchanged': True}
    row['issues'] = [issue for issue in row['issues'] if issue.get('field') != 'yd']
    return True
