"""R3-02 exact reference arithmetic; never infers rates, units or exchange rates.

Reuses the documented original-unit tax basis and ROUND0 behavior from
interaction/stage2_math at aaa8731, without legacy approvals/column mappings.
"""
from fractions import Fraction
from .quantity_math import number, exact

POLICY = 'original-unit-price-reference-tax/1'


def rate(value):
    if isinstance(value,str) and value.strip().endswith('%'):
        n=number(value.strip()[:-1])
        return n/100 if n is not None else None
    return number(value)


def fraction(value):
    return Fraction(int(value['numerator']),int(value['denominator'])) if value else None


def round0(value):
    sign=-1 if value<0 else 1
    n=abs(value)
    return sign*((2*n.numerator+n.denominator)//(2*n.denominator))


def calculate(invoice, quantity, facts):
    """Only explicit invoice/quantity/facts inputs. No lookup or model calls."""
    results, states, issues, formulas = {}, {}, [], {}
    def problem(code,field):
        issues.append({'code':code,'field':field})
        states.setdefault(field,'pending')
    def put(field,value,unit='line',currency='JPY',formula=None,state='derived'):
        results[field]={'value':exact(value),'currency':currency,'per_unit':unit}
        states[field]=state
        if formula:formulas[field]=formula
    def usable(unit):
        if quantity['field_states'].get(unit) not in {'inherited','derived'}:
            return None
        return fraction(quantity['results'].get(unit))
    q,u,a=(number(invoice.get(k))for k in ['quantity','price','amount'])
    if invoice.get('currency')!='JPY':
        return {'original':invoice,'results':{},'field_states':{'original_price':'pending'},
                'formulas':{},'input_facts':facts,'issues':[{'code':'INVOICE_CURRENCY_UNSUPPORTED','field':'original_price'}],
                'status':'partial','professional_approved':False,'tax_basis':'unrounded_original_unit_price',
                'rounding':'piece price display only; no tax/amount balancing'}
    verified=invoice.get('source_fields',{'quantity':True,'price':True,'amount':True})
    valid_q=q is not None and q>0 and verified.get('quantity')is True
    valid_u=u is not None and u>=0 and verified.get('price')is True
    valid_a=a is not None and a>=0 and verified.get('amount')is True
    raw_unit=(quantity.get('raw_unit')or{}).get('unit')
    if not valid_q:problem('ORIGINAL_QUANTITY_INVALID','original_quantity')
    if not valid_u:problem('ORIGINAL_PRICE_INVALID','original_price')
    if not valid_a:problem('ORIGINAL_AMOUNT_INVALID','original_amount')
    if raw_unit is None:problem('INVOICE_UNIT_MISSING','original_unit')
    if valid_a:put('original_amount',a,state='inherited')
    if valid_u:put('original_price',u,raw_unit or 'source_qty',state='inherited')
    if valid_q and valid_u:
        recomputed=q*u
        put('recomputed_invoice_amount',recomputed,formula='q * original_unit_price')
        if valid_a:
            put('original_amount_difference',a-recomputed,formula='original_amount - q * original_unit_price')
            if a!=recomputed:
                problem('ORIGINAL_AMOUNT_CONFLICT','original_amount')
                states['original_amount']='conflict'

    s=usable('piece')
    raw_count=usable(raw_unit) if raw_unit else None
    can_convert=valid_q and valid_u and s is not None and s>0 and raw_count==q
    if can_convert:
        factor=s/q
        put('pieces_per_original_qty',factor,'source_qty',currency=None,formula='total_pieces / q')
        unit_price=u/factor
        rounded=Fraction(round0(unit_price))
        put('piece_price_exact',unit_price,'piece',formula='original_unit_price / (total_pieces / q)')
        put('piece_price_round0',rounded,'piece',formula='ROUND_HALF_AWAY_FROM_ZERO(piece_price_exact, 0)')
        rounded_amount=rounded*s
        put('rounded_line_amount',rounded_amount,formula='piece_price_round0 * total_pieces')
        put('rounding_difference',rounded_amount-q*u,formula='rounded_line_amount - recomputed_invoice_amount')
        if valid_a:put('difference_from_original_amount',rounded_amount-a,formula='rounded_line_amount - original_amount')
    else:
        problem('QUANTITY_CONVERSION_UNAVAILABLE','piece_price_exact')

    quote=facts.get('purchase_quote')
    if quote:
        p=number(quote.get('value'))
        currency=quote.get('currency');unit=quote.get('unit')
        if p is None or p<0:
            problem('PURCHASE_PRICE_INVALID','purchase_ratio')
        elif currency!='JPY':
            problem('CURRENCY_NOT_COMPARABLE','purchase_ratio')
        elif not raw_unit or unit!=raw_unit:
            problem('PRICE_UNIT_NOT_COMPARABLE','purchase_ratio')
        elif not valid_u or u==0:
            problem('PRICE_RATIO_DENOMINATOR_INVALID','purchase_ratio')
        elif not quote.get('matches_display'):
            problem('PURCHASE_DISPLAY_CONFLICT','purchase_ratio')
        else:
            put('purchase_ratio',p/u,'ratio',currency=None,formula='purchase_quote / original_unit_price')
            put('purchase_ratio_round0',Fraction(round0(p/u)),'ratio',currency=None,formula='ROUND_HALF_AWAY_FROM_ZERO(purchase_ratio, 0)')
    else:
        problem('PURCHASE_QUOTE_UNRESOLVED','purchase_ratio')

    rates={}
    for key in ['duty','vat']:
        fact=facts.get(key+'_rate')
        n=rate(fact.get('value')) if fact else None
        if n is None:problem('RATE_MISSING',key+'_rate')
        elif not 0<=n<=1:problem('RATE_INVALID',key+'_rate')
        else:
            rates[key]=n
            put(key+'_rate',n,'ratio',currency=None,state='source_reference')
    duty=vat=None
    if valid_u and 'duty'in rates:
        duty=u*rates['duty']
        put('duty_per_original_qty',duty,raw_unit or 'source_qty',formula='original_unit_price * duty_rate',state='reference')
        if valid_q:put('duty_line_reference',duty*q,formula='duty_per_original_qty * q',state='reference')
    if valid_u and 'duty'in rates and 'vat'in rates:
        vat=u*(1+rates['duty'])*rates['vat']
        put('vat_per_original_qty',vat,raw_unit or 'source_qty',formula='original_unit_price * (1 + duty_rate) * vat_rate',state='reference')
        if valid_q:put('vat_line_reference',vat*q,formula='vat_per_original_qty * q',state='reference')
    if duty is not None and vat is not None:
        tax=duty+vat
        put('tax_per_original_qty',tax,raw_unit or 'source_qty',formula='duty_per_original_qty + vat_per_original_qty',state='reference')
        if valid_q:put('tax_line_reference',tax*q,formula='tax_per_original_qty * q',state='reference')
        b=usable('box')
        if b is not None and b>0 and valid_q and raw_count==q:
            field='tax_per_box_reference' if quantity.get('pieces_per_box') else 'tax_per_reference_box_only'
            put(field,tax*q/b,'box',formula='tax_per_original_qty * q / equivalent_boxes',state='reference')
        else:
            problem('BOX_TAX_QUANTITY_UNAVAILABLE','tax_per_box_reference')
    return {'original':invoice,'results':results,'field_states':states,'formulas':formulas,
            'input_facts':facts,'issues':issues,'status':'partial'if issues else'completed',
            'professional_approved':False,'tax_basis':'unrounded_original_unit_price',
            'rounding':'piece price display only; no tax/amount balancing'}


def summarize(rows):
    fields=['original_amount','recomputed_invoice_amount','rounded_line_amount','rounding_difference',
            'difference_from_original_amount','duty_line_reference','vat_line_reference','tax_line_reference']
    totals={}
    for field in fields:
        included=[r['pricing']['results'][field]for r in rows if field in r['pricing']['results']
                  and r['pricing']['field_states'].get(field)!='conflict']
        totals[field]={'value':exact(sum((fraction(x['value'])for x in included),Fraction(0)))if included else None,
                       'currency':'JPY','covered_rows':len(included),'total_rows':len(rows),
                       'complete':len(included)==len(rows)}
    return totals
