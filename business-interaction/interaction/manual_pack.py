"""Scoped daily policy: original packaging text and explicit human inputs.

Reuse the unchanged calculation review and quantity/ROUND0 engines. Legacy
workflows retain their old behavior; only newly registered manual-text versions
disable price-ratio inference and automatic packaging field population.
"""
from types import FunctionType,SimpleNamespace
import inspect
from pathlib import Path
from . import rt,load,put,digest
from .pack_reference import source_rows

def no_price_inference(minimum,maximum,*,purchase_confirmed=False,minimum_unit_confirmed=False,actual_price=False,comparable=False):
    from native22.pricing import decimal
    result={'status':'manual_input_only','pieces_per_box':None,'exact_ratio':None,'legacy_display':None,'reason':None,'automatic_approval':False}
    if not actual_price:result['reason']='actual_japanese_price_unconfirmed'
    elif not purchase_confirmed or not minimum_unit_confirmed:result['reason']='purchase_minimum_price_unconfirmed'
    elif not comparable:result['reason']='currency_product_or_price_basis_not_comparable'
    elif any(decimal(v) is None or decimal(v)<=0 for v in [minimum,maximum]):result['reason']='missing_or_nonpositive_price'
    return result

original_prepare=rt.review.prepare
original_recalculate=rt.review.recalculate
base_prepare=rt.review.base.prepare
manual_base_prepare=FunctionType(base_prepare.__code__,{**base_prepare.__globals__,'candidate':no_price_inference},base_prepare.__name__,base_prepare.__defaults__,base_prepare.__closure__)
pack_prepare=FunctionType(original_prepare.__code__,{**original_prepare.__globals__,'base':SimpleNamespace(prepare=manual_base_prepare)},original_prepare.__name__,original_prepare.__defaults__,original_prepare.__closure__)

# One fail-closed adaptation of the existing packaging checker. All unit,
# positive-integer, source, amount, quantity and ROUND0 checks stay in that code.
text=inspect.getsource(original_recalculate)
old='if not ratio or Fraction(ratio)!=expected_price_ratio:'
if text.count(old)!=1:raise RuntimeError('现有包装检查接口已变，拒绝静默适配')
scope=dict(original_recalculate.__globals__)
exec(compile(text.replace(old,'if ratio is not None and Fraction(ratio)!=expected_price_ratio:'),str(Path(__file__)), 'exec'),scope)
manual_recalculate=scope['recalculate']

def prepare(root):
    svc=rt.updates.Service(root);workflow=load(svc.owner['workflow'])
    if not workflow.get('manual_packaging_original_text_only'):return original_prepare(root)
    p=pack_prepare(root);sources=source_rows(workflow)
    p['headers'][12]='盒规自动推导（停用）';p['headers'][13]='人工每原Qty申报数';p['headers'][27]='盒规原文参考／检查'
    p['headers'][34]='人工每盒包数';p['headers'][35]='人工每包申报张/件数';p['headers'][38]='人工包装层级确认依据'
    for row in p['rows']:
        source=sources.get(str(row['source_row']),{})
        row['values'][12]=None;row['values'][13]=None
        row['values'][34]=None;row['values'][35]=None
        row['packaging_input_policy']='manual_original_text';row['packaging_original_source']=source
        row['values'][27]=(source.get('display_text') or '无盒规原文，待人工判断')+'\n'+(row['price_check']['reason'] or '盒规由人工填写，未计算或默认数量')
    p['manual_packaging_original_text_only']=True
    p['code']={**p['code'],str(Path(__file__)):digest(__file__),str(Path(__file__).with_name('pack_reference.py')):digest(Path(__file__).with_name('pack_reference.py'))}
    body={k:v for k,v in p.items() if k not in {'plan_id','version_token'}};pid=put(svc.root,body)
    return {**body,'plan_id':pid,'version_token':pid}

def recalculate(row,values,reference):
    if row.get('packaging_input_policy')!='manual_original_text':return original_recalculate(row,values,reference)
    return manual_recalculate(row,values,reference)

rt.review.prepare=prepare
rt.review.recalculate=recalculate
rt.review.base.recalculate=recalculate
