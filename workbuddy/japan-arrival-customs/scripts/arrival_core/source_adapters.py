"""Read-only source adapters. Explicit mapping and identity evidence are mandatory.

No credentials are embedded, no fuzzy/name-only identity join is performed, and
official descriptions never replace a B2 human declaration choice.
"""
import json, os
from pathlib import Path
from urllib.parse import urlsplit, quote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .core import Rejected, digest, now
from .storage import atomic_json

KINDS=('feishu_product','feishu_purchase','official_web')

def status(config=None):
    config=config or {}
    result={'local_excel':{'state':'available','read_only':True}}
    for kind in KINDS:
        result[kind]={'state':'configured_unverified' if config.get(kind) else 'not_configured','read_only':True}
    result['notice']='配置或离线契约测试不代表实机接通；来源仅提供独立参考'
    return result

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise Rejected('来源重定向须重新核验域名与权限')

def request_bytes(url,headers):
    request=Request(url,headers=headers,method='GET')
    with build_opener(NoRedirect()).open(request,timeout=30) as response:
        raw=response.read(5*1024*1024+1)
        if len(raw)>5*1024*1024: raise Rejected('来源响应超过5MiB，未作截断导入')
        return raw

def authorize_source(config):
    if config.get('read_authorized') is not True or not config.get('authorization_reference'):
        raise Rejected('来源读取权限尚未核验')

def scalar(value):
    # Preserve full rich-text material compositions, including qualifiers and 等.
    if isinstance(value,str): return value
    if isinstance(value,list) and all(isinstance(x,dict) and isinstance(x.get('text'),str) for x in value):
        return ''.join(x['text'] for x in value)
    if value is None: return None
    raise Rejected('来源字段类型未确认；保留原始响应，禁止猜测转换')

def normalize_records(kind,records,fields,mapping,*,mapping_reference,source,identity_binding,collected_at):
    """Offline contract also used by live reads. Field IDs come from actual metadata."""
    if kind not in ('feishu_product','feishu_purchase') or not mapping_reference:
        raise Rejected('缺少已确认字段映射依据')
    required={'identity','version','specification'}
    if not required<=set(mapping) or any(k not in {'identity','version','specification','description','complete_composition','purchase_quantity','purchase_unit','order_id'} for k in mapping):
        raise Rejected('映射缺少商品身份/版本/规格或存在未确认字段')
    schema={f['field_id']:f for f in fields}
    if any(v not in schema for v in mapping.values()): raise Rejected('映射引用的字段不在实际接口元数据中')
    if not isinstance(identity_binding,dict) or not identity_binding.get('reference') or not identity_binding.get('source_field_id')==mapping['identity']:
        raise Rejected('缺少商品身份字段含义和对应依据')
    rows=[];seen=set()
    for record in records:
        if record['record_id'] in seen: raise Rejected('来源记录ID重复，拒绝不明确分页')
        seen.add(record['record_id']); values={}
        for semantic,field_id in mapping.items():
            field=schema[field_id]
            # Feishu returns record fields by name, while mapping is bound to stable
            # field IDs and verified metadata; never assume a label's business meaning.
            values[semantic]=scalar(record.get('fields',{}).get(field['field_name']))
        rows.append({'record_id':record['record_id'],'values':values,'source':source,
                     'collected_at':collected_at,'original_record':record,
                     'raw_hash':digest(record),'mapping_reference':mapping_reference,
                     'identity_evidence':identity_binding,'approval':False,'layer':'source_reference_only'})
    return rows

def read_feishu(kind,config,*,transport=request_bytes):
    authorize_source(config)
    base=config.get('base_url','https://open.feishu.cn')
    if base not in ('https://open.feishu.cn','https://open.larksuite.com'): raise Rejected('飞书API域名未授权')
    for key in ('app_token','table_id','token_env','mapping','mapping_reference','identity_binding'):
        if not config.get(key): raise Rejected('来源缺少配置：'+key)
    token=os.environ.get(config['token_env'])
    if not token: raise Rejected('飞书访问令牌未注入可信环境')
    path=base+'/open-apis/bitable/v1/apps/'+quote(config['app_token'],safe='')+'/tables/'+quote(config['table_id'],safe='')
    headers={'Authorization':'Bearer '+token}; raw_pages=[]
    def fetch(endpoint):
        raw=transport(endpoint,headers)
        try: body=json.loads(raw)
        except (ValueError,UnicodeError) as exc: raise Rejected('飞书响应不是有效JSON') from exc
        if body.get('code')!=0 or not isinstance(body.get('data'),dict): raise Rejected('飞书接口未成功，不能视为无资料')
        raw_pages.append({'endpoint':endpoint,'original':body,'collected_at':now(),'sha256':__import__('hashlib').sha256(raw).hexdigest()})
        return body['data']
    def pages(endpoint):
        items=[]; page_token=None; tokens=set()
        for _ in range(1000):
            data=fetch(endpoint+'?'+urlencode({'page_size':100,**({'page_token':page_token} if page_token else {})}))
            if not isinstance(data.get('items',[]),list): raise Rejected('来源分页结构未知')
            items.extend(data.get('items',[]))
            if not data.get('has_more'): return items
            page_token=data.get('page_token')
            if not page_token or page_token in tokens: raise Rejected('来源分页游标无效或循环')
            tokens.add(page_token)
        raise Rejected('来源分页超限，未作部分成功导入')
    fields=pages(path+'/fields'); records=pages(path+'/records')
    rows=normalize_records(kind,records,fields,config['mapping'],mapping_reference=config['mapping_reference'],
                           source={'kind':kind,'app_token':config['app_token'],'table_id':config['table_id']},
                           identity_binding=config['identity_binding'],collected_at=now())
    return {'kind':kind,'state':'read_succeeded','real_connection_verified':transport is request_bytes,
            'rows':rows,'metadata':fields,'raw_pages':raw_pages,'read_only':True,'approval':False}

def read_official(url,config,*,identity_evidence,transport=request_bytes):
    authorize_source(config); parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.hostname not in config.get('official_hosts',[]) or parsed.username or
        parsed.password or parsed.port not in (None,443) or parsed.fragment):
        raise Rejected('必须使用明确授权的官方HTTPS商品页')
    if not identity_evidence or not all(identity_evidence.get(k) for k in ('code','version','specification','reference')):
        raise Rejected('官方页面须有明确商品身份/版本/规格匹配依据')
    raw=transport(url,{'User-Agent':'JapanArrivalEvidence/0.7.0'})
    # Store the entire original response; material extraction is an explicit
    # quoted-evidence operation, never guessed from HTML or the product name.
    text=raw.decode(config.get('encoding','utf-8'),errors='strict')
    return {'kind':'official_web','state':'read_succeeded','real_connection_verified':transport is request_bytes,
            'url':url,'collected_at':now(),'original_content':text,'content_sha256':__import__('hashlib').sha256(raw).hexdigest(),
            'identity_evidence':identity_evidence,'complete_composition':None,
            'notice':'待提取完整材料原文及译文；官方资料不改变人工最终申报选择','approval':False}

def quote_composition(evidence,original,translation):
    if not original or original not in evidence['original_content'] or not translation:
        raise Rejected('材料引用必须对应原始页面且保留完整译文')
    return {**evidence,'complete_composition':{'original':original,'translation':translation},
            'translation_review':'pending','approval':False}

def archive_evidence(directory,evidence):
    path=Path(directory).resolve(); path.mkdir(parents=True,exist_ok=True)
    target=path/(digest(evidence)+'.json')
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8'))!=evidence: raise Rejected('证据对象冲突')
    else: atomic_json(target,evidence)
    return {'file':str(target),'sha256':digest(evidence),'approval':False}

def official_payload(batch,evidences):
    """Bind official quotations to stable B2 row IDs without changing final choices."""
    payload={};unmatched=[]
    for evidence in evidences:
        if evidence.get('kind')!='official_web' or not evidence.get('complete_composition'):
            unmatched.append({'hash':digest(evidence),'reason':'missing_official_composition'});continue
        identity=evidence['identity_evidence']; matched=[]
        for row in batch['rows']:
            if all(row['identity'][k]==identity.get(k) for k in ('code','version','specification')):
                material=evidence['complete_composition']
                payload.setdefault(row['id'],[]).append({'original':material['original'],'translation':material['translation'],
                    'source_ref':evidence['url'],'source_sha256':evidence['content_sha256'],
                    'collected_at':evidence['collected_at'],'identity_evidence':identity,'review_status':'reference_only'})
                matched.append(row['id'])
        if not matched: unmatched.append({'hash':digest(evidence),'reason':'identity_version_specification_not_matched'})
    return {'official_materials':payload,'unmatched':unmatched,'final_choices_modified':False}
