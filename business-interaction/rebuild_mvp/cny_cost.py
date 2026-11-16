"""CNY procurement-cost comparison only; no exchange or packaging conversion."""
from decimal import Decimal, InvalidOperation
import re, unicodedata

RULE='highest-comparable-cny-cost/20261116'

def decimal_text(value):
    try:
        n=Decimal(str(value).strip())
    except (InvalidOperation,ValueError):return None
    if not n.is_finite() or n<0:return None
    text=format(n,'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text

def normalize_options(options):
    """Options carry price, currency and explicit same-SKU unit provenance."""
    if not options:return None
    currencies={str(o.get('currency','')).strip().upper()for o in options}
    if not currencies <= {'CNY','RMB','人民币'}:return None
    units={str(o.get('unit') or '').strip()for o in options}
    if len(units)!=1 or not next(iter(units)):return None
    packaging={str(o.get('packaging') or '').strip()for o in options if o.get('packaging')}
    if len(packaging)>1:return None
    groups={}
    for option in options:
        value=decimal_text(option['value'])
        if value is None:return None
        groups.setdefault(value,[]).append(option)
    highest=max(groups,key=Decimal)
    return {'rule':RULE,'currency':'CNY','unit':next(iter(units)),'value':highest,
            'selected':groups[highest], 'groups':groups,'options':options}

def display_selection(choices):
    """Read explicit CNY candidate labels, retaining each original option/ref."""
    options=[]
    for value,evidence in choices:
        refs=evidence if isinstance(evidence,list)else[evidence]
        text=unicodedata.normalize('NFKC',str(value)).strip()
        text=re.sub(r'\s*\((?:待选|采购候选|待确认)\)\s*$','',text)
        price=text.split(' / ',1)[0].strip()
        match=re.fullmatch(r'([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:元|人民币|CNY|RMB)',price,re.I)
        if not match:return None
        units={str(r.get('unit')or'').strip()for r in refs}
        currencies={str(r.get('currency')or'CNY').strip().upper()for r in refs}
        if not currencies <= {'CNY','RMB','人民币'} or len(units)!=1:return None
        options.append({'value':match[1],'currency':'CNY','unit':next(iter(units)),
                        'packaging':next((r.get('packaging_unit')for r in refs if r.get('packaging_unit')),None),
                        'original_display':str(value),'evidence':refs})
    return normalize_options(options)


def existing_cell_selection(text, *, same_original_cost_field=False):
    """User-authorized same-row H alternatives; does not infer a physical unit."""
    if not same_original_cost_field:return None
    lines=[line.strip()for line in str(text).splitlines()if line.strip()]
    if len(lines)<2:return None
    choices=[]
    for line in lines:
        line=re.sub(r'^\d+[.、]\s+', '', line)
        choices.append((line,{'currency':'CNY','unit':'existing_H_original_quote_field',
                              'physical_unit_inferred':False,'original_line':line}))
    result=display_selection(choices)
    if result:
        result['comparison_scope']='existing_same_row_H_procurement_cost'
        result['physical_unit_inferred']=False
    return result
