"""New role/precision guard for the existing price helper; never tax/output math."""
from fractions import Fraction
from native22.pricing import decimal,calculate
def candidate(minimum,maximum,*,purchase_confirmed=False,minimum_unit_confirmed=False,actual_price=False,comparable=False):
    result={'status':'manual','pieces_per_box':None,'exact_ratio':None,'legacy_display':None,'reason':None,'automatic_approval':False}
    if not actual_price:result['reason']='actual_japanese_price_unconfirmed';return result
    if not purchase_confirmed or not minimum_unit_confirmed:result['reason']='purchase_minimum_price_unconfirmed';return result
    if not comparable:result['reason']='currency_product_or_price_basis_not_comparable';return result
    lo,hi=decimal(minimum),decimal(maximum)
    if lo is None or hi is None or lo<=0 or hi<=0:result['reason']='missing_or_nonpositive_price';return result
    ratio=Fraction(hi)/Fraction(lo);result['exact_ratio']=str(ratio)
    if ratio.denominator!=1:result['reason']='noninteger_price_ratio_no_rounding';return result
    h=ratio.numerator
    result.update(status='candidate',pieces_per_box=str(h),reason=None)
    # Preserve the old display/residual helper with reversed roles and explicit H.
    # Its 2-decimal output never decides whether a box ratio is an exact integer.
    ch,diff,status=calculate(hi,lo,decimal(h),False)
    result['legacy_display']={'pieces':str(ch) if ch is not None else None,'difference_jpy':str(diff) if diff is not None else None,'status':status,'approval_basis':False}
    return result
