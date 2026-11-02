import hashlib
import json
import sys
from pathlib import Path

P1=Path(__file__).resolve().parents[2]/'product-library-p1'
sys.path.insert(0,str(P1))
from product_reference.core import Rejected,now
from product_reference.database import digest,read_only,working_copy,clone,require_b4
from product_reference.query import comparable,has_material

IDENTITY=('code_raw','code_type','japanese_name','version','specification')
BASIC=('internal_name','customs_name','brand','category','channel','yd')
FIELDS=set(IDENTITY+BASIC+('material_original','material_translation','material_url','series','packaging_label'))


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def key(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def text(value):
    if value is None:return None
    if isinstance(value,bool):raise Rejected('身份/基础资料不接受布尔值')
    if isinstance(value,float) and value.is_integer():value=int(value)
    return str(value).strip() or None
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def identity_key(identity):return key({f:identity.get(f) for f in IDENTITY})


def good_anchor(value):return value not in (None,'','0','未知','无','-','待确认')
