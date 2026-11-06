"""User-approved specification heuristic; reference only, no quantity/unit math."""
import re,unicodedata
from pathlib import Path
from . import load,save,digest
RULE='USER:2026-11-06:规格含整盒/整套/套组/set等提示多商品；其他非空规格默认参考1'
MULTI=re.compile(r'整盒|整套|套组|套装|整袋|盒装|セット|(?<![a-z])(?:set|box)(?![a-z])',re.I)

def reference(spec,existing=None,context_current=True):
    raw=spec;text=unicodedata.normalize('NFKC',str(spec or '')).strip();markers=[m.group() for m in MULTI.finditer(text)]
    result={'raw_specification':raw,'multi_markers':markers,'reference_count':None,'basis':None,'rule':RULE,'automatic_confirmation':False,
        'original_qty_unit_inferred':False,'packs_per_box':None,'units_per_pack':None,'existing_reference_preserved':existing}
    if not context_current:
        result.update(status='identity_or_spec_changed_needs_source_review',basis='不沿用旧规格/YD的盒规来源');return result
    if existing not in (None,''):
        from fractions import Fraction
        try:
            n=Fraction(str(existing));assert n>0 and n.denominator==1
        except (ValueError,ZeroDivisionError,AssertionError):result.update(status='existing_reference_invalid_needs_review',basis='保留原值，不以默认1覆盖');return result
        result.update(status='existing_source_reference',reference_count=n.numerator,basis='原S已有参考优先；不新推定计价或数量单位');return result
    if not text or text.isdecimal():result.update(status='specification_missing_needs_review',basis='没有可判别的规格描述');return result
    if markers:result.update(status='likely_multiple_count_pending',basis='规格提示多商品，具体数量仍须来源');return result
    result.update(status='default_one_reference',reference_count=1,basis='本次用户授权的非多商品规格默认参考1');return result

def write_hints(service,background):
    from arrival_core import _p0_frozen as p0
    batch,baseline,_,_,fields,_=service.basics._state(service.bid);byrow={};old={}
    for f in fields.values():byrow.setdefault(f['row_id'],{})[f['field']]=f
    for f in baseline['fields'].values():old.setdefault(f['row_id'],{})[f['field']]=f
    file=Path(service.root/'objects'/(baseline['copy_sha256']+'.xlsx'));book=p0.Book(file.read_bytes(),'registered-reference.xlsx');sheet=next(s for s in book.sheets if s.name=='invoice (計算)')
    rows={}
    for rid,fs in byrow.items():
        if 'specification' not in fs:continue
        f=fs['specification'];n=int(re.search(r'\d+$',f['cell'])[0]);current=all(fs.get(k,{}).get('value')==old[rid].get(k,{}).get('value') for k in ['product_code','specification','yd'])
        rows[str(n)]={**reference(f['value']['value'],sheet.v(n,'S'),current),'source_cell':'S'+str(n),'specification_cell':f['cell'],'row_id':rid}
    from collections import Counter
    body={'rule':RULE,'registered_copy_sha256':baseline['copy_sha256'],'rows':rows,'counts':dict(Counter(r['status'] for r in rows.values())),
        'workbook_or_original_data_changed':False,'calculation_rules_changed':False,'original_qty_and_price_units_inferred':False}
    save(background/'规格盒规参考.json',body);return body
