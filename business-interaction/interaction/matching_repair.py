"""Identity and source-order reference selection; no unit conversion or approval."""
import re,unicodedata
from decimal import Decimal,InvalidOperation
from copy import deepcopy
from .preparation_sources import Index,code

def norm(v):return re.sub(r'[\s：:，,、。·・（）()【】\[\]「」『』_－-]+','',unicodedata.normalize('NFKC',str(v or '')).lower())
def spec_same(a,b):
 raw_a,raw_b=str(a or ''),str(b or '')
 def clean(v):
  v=re.sub(r'[（(]差[0-9]+[）)]$','',v)
  if not any(x in v for x in ['每盒','每包','入','全']):v=re.sub(r'[0-9]+[→>][0-9]+$','',v)
  return re.sub(r'数量[0-9]+$','',v)
 raw_a,raw_b=clean(raw_a),clean(raw_b)
 # Circled style IDs remain distinct from an appended procurement count.
 for x,y in [(raw_a,raw_b),(raw_b,raw_a)]:
  if y and y[-1] in '①②③④⑤⑥⑦⑧⑨⑩' and x.startswith(y) and x[len(y):].isdigit():return True
 a,b=norm(raw_a),norm(raw_b)
 if a and b and ((a.startswith(b) and not b[-1:].isdigit() and a[len(b):].isdigit()) or (b.startswith(a) and not a[-1:].isdigit() and b[len(a):].isdigit())):return True
 labels=['心吧唧','吧唧','徽章','立牌','贴纸','挂件','掛件']
 ta=next((x for x in labels if a.startswith(x)),None);tb=next((x for x in labels if b.startswith(x)),None)
 if ta and tb and ta!=tb and {ta,tb}!={'心吧唧','吧唧'} and {ta,tb}!={'吧唧','徽章'} and {ta,tb}!={'挂件','掛件'}:return False
 if ta:a=a[len(ta):]
 if tb:b=b[len(tb):]
 for label in ['立牌','挂件','掛件']:
  if a.endswith(label):a=a[:-len(label)]
  if b.endswith(label):b=b[:-len(label)]
 if a==b:return True
 if a and b and ((a.startswith(b) and not b[-1:].isdigit() and a[len(b):].isdigit()) or (b.startswith(a) and not a[-1:].isdigit() and b[len(a):].isdigit())):return True
 # Same JAN with omitted Chinese surname/product type is a textual alias,
 # provided no explicit costume, version or packaging/count contrast is lost.
 aa=re.sub(r'[0-9]+$','',a);bb=re.sub(r'[0-9]+$','',b)
 if re.fullmatch(r'[一-龥]{2,}',aa) and re.fullmatch(r'[一-龥]{2,}',bb):
  if not any((x in aa)!=(x in bb) for x in ['私服','幼少','水着','泳装','制服']):
   if abs(len(aa)-len(bb))<=2 and (aa.endswith(bb) or bb.endswith(aa)):return True
 # Tiny trailing text differences are accepted only for a long identical
 # SKU label, with no added unit, count, version or private/costume marker.
 for x,y in [(a,b),(b,a)]:
  core=re.sub(r'[0-9]+$','',x)
  if len(core)>=4 and y.startswith(core) and len(y)==len(core)+1 and y[-1] not in '私服枚张張个個盒包套种種体體' and not y[-1].isdigit():return True
 return False
def currency(v):return {'日元':'JPY','円':'JPY','人民币':'CNY','RMB':'CNY'}.get(str(v),str(v or ''))
def select_price(jan,records,spec='',special=False):
 observed=[r for r in records if r.get('source',{}).get('kind')=='effective_purchase_order' and jan in {code(r.get('jan')),code(r.get('sku'))}]
 def identity(r):return (r.get('order_id'),norm(r.get('spec')))
 blocked={identity(r) for r in observed if r.get('status')!='已采购' or str(r.get('cancelled') or '') in {'是','true','True','1'}}
 orders=[r for r in observed if identity(r) not in blocked and r.get('status')=='已采购']
 reasons=[]
 if special:return None,{'category':'special_identity_requires_context','candidates':orders,'reason':'bonus_or_internal_code_not_merged_by_code'}
 applicable=[r for r in orders if not spec or r.get('spec') and spec_same(spec,r['spec'])]
 if orders and not applicable:return None,{'category':'substantive_identity_conflict','candidates':orders,'reason':'order_specification_not_applicable'}
 priced=[r for r in applicable if r.get('price') not in (None,'')]
 if not priced:
  states={}
  for r in observed:states.setdefault(identity(r),set()).add(r.get('status'))
  if any('已采购' in v and len(v)>1 for v in states.values()):
   return None,{'category':'order_status_conflict','candidates':observed,'reason':'same_order_spec_has_effective_and_non_effective_status'}
  return None,{'category':'source_missing','candidates':observed,'reason':'no_applicable_effective_order_quote_or_status_not_effective'}
 currencies={currency(r.get('currency')) for r in priced};units={norm(r.get('price_unit')) for r in priced if r.get('price_unit')}
 if len(currencies)!=1 or not currencies<={'JPY','CNY'}:return None,{'category':'unit_or_currency','candidates':priced,'reason':'currency_missing_or_different'}
 if len(units)>1:return None,{'category':'unit_or_currency','candidates':priced,'reason':'different_explicit_pricing_units'}
 try:values={Decimal(str(r['price'])) for r in priced}
 except InvalidOperation:return None,{'category':'source_missing','candidates':priced,'reason':'invalid_order_quote'}
 if any(not v.is_finite() or v<0 for v in values):return None,{'category':'source_missing','candidates':priced,'reason':'invalid_order_quote'}
 precision_only=False
 if len(values)>1:
  precision_only=bool(all(r.get('precision_basis_reference') for r in priced) and len(units)==1 and all(r.get('price_unit') for r in priced) and len({v.quantize(Decimal('.01')) for v in values})==1)
  if not precision_only:return None,{'category':'true_price_conflict' if len(units)==1 and all(r.get('price_unit') for r in priced) else 'unit_or_currency','candidates':priced,'reason':'different_effective_order_quotes' if units else 'different_order_quotes_with_unestablished_unit'}
 selected=priced[0];value=Decimal(str(selected['price']));cur=next(iter(currencies))
 return (str(value)+'元' if cur=='CNY' else value),{'category':'safe_order_quote','selected':selected,'candidates':priced,'precision_only':precision_only,'unit_status':'explicit' if units else 'source_SKU_quote_reference_only_no_conversion','history_not_competing':True}

def resolve_repaired(jan,index,cards,history,legacy,context=None):
 context=context or {};hit=index.lookup(jan);allrecords=hit['records']+hit['related'];direct=hit['records']
 special=not re.fullmatch(r'\d{8,14}',jan) or any(t in str(context.get('name_ja') or '') for t in ['特典','自编','自編'])
 registry=[r for r in direct if r.get('source',{}).get('kind')=='registry'];reference=next((r for r in registry if r.get('name') or r.get('spec')),None) or next((r for r in direct if r.get('name') and r.get('spec')),None)
 contexts={(norm(r.get('name')),norm(r.get('spec')),r.get('yd')) for r in direct if r.get('name')}
 if special and len(contexts)>1:
  result={'jan':jan,'status':'special_identity_requires_context','values':{},'sources':allrecords,'price_review':{'category':'special_identity_requires_context','reason':'repeated_special_code_requires_product_spec_order_YD'},'confirmed':False}
  from .material_reference import enrich_material
  return enrich_material(result,cards,context,preserve_existing=False)
 spec=context.get('spec') or (reference or {}).get('spec') or ''
 yd=(reference or {}).get('yd') or next((r.get('yd') for r in sorted(direct,key=lambda r:r.get('priority',100)) if r.get('yd')),None);primary=[r for r in allrecords if not r.get('yd') or r.get('yd')==yd]
 # Legacy resolver supplies material, packaging and image scope for the selected
 # source identity. Full multi-YD/other-order evidence remains separate, intact.
 result=legacy(jan,Index(primary),cards,history) if primary else legacy(jan,index,cards,history)
 result.setdefault('values',{})
 if reference:
  for field in ['name','spec','channel','yd']:
   if reference.get(field) not in (None,''):result['values'][field]=reference[field]
 def versions(text):return set(re.findall(r'(?:vol[. ]*|第)([0-9]+)(?:[弹弾])?',norm(text)))
 expected=versions(context.get('name_ja') or '') or versions(spec)
 price_records=[r for r in direct if not expected or not versions(r.get('spec') or r.get('name_ja') or '') or versions(r.get('spec') or r.get('name_ja') or '')==expected]
 value,review=select_price(jan,price_records,spec,special)
 if expected and any(r.get('source',{}).get('kind')=='effective_purchase_order' for r in direct) and not any(r.get('source',{}).get('kind')=='effective_purchase_order' for r in price_records):
  value=None;review={'category':'substantive_identity_conflict','reason':'explicit_product_version_conflict','candidates':direct}
 if value is None and review['category']=='source_missing' and not review.get('candidates') and result['values'].get('price') is not None:
  value=result['values']['price'];review['category']='safe_auxiliary_reference';review['reason']='unique_legacy_reference_no_effective_order_quote'
 if value is None and review['category']=='source_missing' and not review.get('candidates'):
  refs=[r for r in price_records if r.get('price_scope')!='order_total' and r.get('price') not in (None,'') and jan in {code(r.get('jan')),code(r.get('sku'))}]
  pairs={(Decimal(str(r['price'])),currency(r.get('currency'))) for r in refs}
  if len(pairs)>1:review={'category':'true_price_conflict','candidates':refs,'reason':'different_auxiliary_reference_quotes_no_effective_order'}
 result['values']['price']=value;result['price_review']=review;result['all_identity_candidates']=allrecords
 result['ordinary_multiple_YD_is_conflict']=False
 result['identity_YDs']=sorted({r['yd'] for r in allrecords if r.get('yd')})
 result['sources']=allrecords;result['status']='special_reference' if special else 'matched'
 if review['category']=='substantive_identity_conflict':result['status']='substantive_identity_conflict'
 from .pcs_enrichment import enrich_linked
 result=enrich_linked(result,hit,context)
 from .dg_enrichment import enrich_dg
 result=enrich_dg(result,index,context)
 from .material_reference import enrich_material
 return enrich_material(result,cards,context,preserve_existing=False)
