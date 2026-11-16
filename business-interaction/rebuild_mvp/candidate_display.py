"""Business-approved candidate presentation, independent of fact adoption."""
import re

RULE = 'candidate-display/20261116'
ORANGE = '#FCE4D6'

def candidate_text(field, values, note):
    """A name lookup alone is not a warning suffix on a unique YD."""
    if len(values) == 1:
        return values[0] if field == 'yd' and note == '按名称补' else values[0] + '（' + note + '）'
    return '\n'.join(f'{i}. {value}' for i, value in enumerate(values, 1)) + '（待选）'

def export_marks(rows, offset):
    """Keep the highest-priority cell mark; orange must survive missing notes."""
    marks = []
    for row in rows:
        number = row['source_row'] + offset
        marks.extend({'row': number, 'field': issue.get('field'), 'code': issue.get('code')}
                     for issue in row.get('issues', []))
        selection=row.get('purchase_price_selection',{})
        if selection.get('rule')=='highest-comparable-cny-cost/20261116':
            from .cny_cost import decimal_text
            prices={decimal_text(quote.get('value'))for quote in selection.get('all_quotes',[])}-{None}
            if len(prices)>1:
                marks.append({'row':number,'field':'purchase_price','code':'CNY_SOURCE_PRICE_CONFLICT'})
        for field, data in row.get('review_candidates', {}).items():
            distinct = {str(option.get('value', '')).strip() for option in data.get('options', [])}
            distinct.discard('')
            if len(distinct) > 1:
                marks.append({'row': number, 'field': field, 'code': 'CANDIDATE_AMBIGUOUS'})
    marks.sort(key=lambda item: not bool(re.search('CONFLICT|AMBIGU', item.get('code') or '')))
    result = []; seen = set()
    for mark in marks:
        key = (mark['row'], mark['field'])
        if key not in seen:
            result.append(mark); seen.add(key)
    return result
