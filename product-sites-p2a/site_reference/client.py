"""Scope-gated HTTP with bounded retry, cache and per-site request spacing."""
import hashlib
import json
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

from .compat import normalize, validate_response, Rejected
from .parser import parse

UA = 'JapanArrivalProductReference/0.1 (public product reference validation)'
ORIGIN = 'https://anime-store.jp'


def utc():return datetime.now(timezone.utc).isoformat()
def sha(raw):return hashlib.sha256(raw).hexdigest()


def valid_url(url):
    parsed=urlparse(url)
    return (parsed.scheme=='https' and parsed.hostname in {'anime-store.jp','www.anime-store.jp'}
            and parsed.port in (None,443) and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and (parsed.path=='/robots.txt' or parsed.path.startswith('/products/')))


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not valid_url(newurl):raise Rejected('redirect_outside_allowed_product_scope')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Transport:
    network_capable=True
    def __init__(self):self.opener=build_opener(Redirect())
    def __call__(self,url):
        if not valid_url(url):raise Rejected('url_outside_allowed_scope')
        request=Request(url,headers={'User-Agent':UA,'Accept':'text/html,text/plain;q=0.8'})
        try:
            with self.opener.open(request,timeout=20) as response:
                raw=response.read(2*1024*1024+1)
                if len(raw)>2*1024*1024:raise Rejected('response_too_large')
                if not valid_url(response.geturl()):raise Rejected('redirect_outside_allowed_scope')
                return response.status,raw,dict(response.headers),response.geturl()
        except HTTPError as exc:
            status=exc.code;headers=dict(exc.headers);exc.close()
            return status,b'',headers,url


def scope_check(path):
    if path is None:return None,'site_permission_not_provided'
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        required={'schema','site_id','purpose','authorization_reference','operator_review_reference',
                  'evidence_file','evidence_sha256','reviewed_terms_sha256','expires_at','allowed_path_prefixes'}
        if set(data)!=required or data['schema']!='product-site-access-scope/1' or data['site_id']!='anime-store':
            raise Rejected('invalid_site_permission_structure')
        if data['purpose']!='internal_product_reference' or data['allowed_path_prefixes']!=['/products/']:
            raise Rejected('site_permission_scope_mismatch')
        for field in ('authorization_reference','operator_review_reference'):
            if not isinstance(data[field],str) or not data[field].strip() or data[field].startswith('TEST:'):
                raise Rejected('site_permission_reference_missing')
        if not re.fullmatch('[0-9a-f]{64}',data['reviewed_terms_sha256']):raise Rejected('terms_review_hash_missing')
        if datetime.fromisoformat(data['expires_at'])<=datetime.now(timezone.utc):raise Rejected('site_permission_expired')
        evidence_path=Path(data['evidence_file'])
        if not evidence_path.is_absolute():evidence_path=Path(path).resolve().parent/evidence_path
        if sha(evidence_path.read_bytes())!=data['evidence_sha256']:raise Rejected('site_permission_evidence_hash_mismatch')
        return data,None
    except (OSError,ValueError,KeyError,TypeError,Rejected) as exc:
        return None,str(exc)


class AnimeStore:
    def __init__(self,runtime,*,access_scope=None,transport=None,interval=3,retries=1,sleep=time.sleep,clock=time.time):
        if interval<3 or retries not in (0,1):raise Rejected('minimum_interval_3_seconds_and_at_most_one_retry')
        self.runtime=Path(runtime).resolve();self.access_scope=access_scope
        self.transport=transport if transport is not None else Transport()
        self.interval=interval;self.retries=retries;self.sleep=sleep;self.clock=clock
        self.network_calls=0;self.cache_hits=0;self.circuit=None

    @contextmanager
    def lease(self):
        self.runtime.mkdir(parents=True,exist_ok=True);path=self.runtime/'site.lock'
        try:
            with path.open('x',encoding='utf-8') as f:f.write(utc())
        except FileExistsError as exc:raise Rejected('site_runtime_busy') from exc
        try:yield
        finally:path.unlink()

    def _state(self):
        p=self.runtime/'rate-state.json'
        if not p.exists():return {}
        return json.loads(p.read_text(encoding='utf-8'))

    def _set_state(self,data):
        p=self.runtime/'rate-state.json';tmp=p.with_suffix('.tmp')
        tmp.write_text(json.dumps(data),encoding='utf-8');tmp.replace(p)

    def _wait(self):
        state=self._state();delay=state.get('next_allowed_at',0)-self.clock()
        if delay>30:raise Rejected('site_cooldown_active')
        if delay>0:self.sleep(delay)
        self._set_state({'last_request_at':self.clock(),'next_allowed_at':self.clock()+self.interval})

    def _get(self,url,*,ttl=86400):
        mode='live_http' if isinstance(self.transport,Transport) else 'synthetic_transport'
        key=sha((mode+url).encode());entry=self.runtime/'cache'/(key+'.json')
        if entry.exists():
            value=json.loads(entry.read_text(encoding='utf-8'));raw_path=self.runtime/value['evidence_file']
            if (not re.fullmatch('[0-9a-f]{64}',value.get('content_sha256',''))
                    or value['evidence_file']!='evidence/'+value['content_sha256']+'.body'):
                raise Rejected('invalid_cache_evidence_path')
            if self.clock()-value['cached_at']<value['ttl']:
                raw=raw_path.read_bytes()
                if sha(raw)!=value['content_sha256']:raise Rejected('cached_evidence_hash_mismatch')
                if value['url']!=url or not valid_url(value['final_url']):raise Rejected('cached_url_mismatch')
                self.cache_hits+=1;return {**value,'raw':raw,'from_cache':True}
        last=None
        for attempt in range(self.retries+1):
            self._wait();self.network_calls+=1
            try:status,raw,headers,final=self.transport(url)
            except (URLError,OSError,TimeoutError) as exc:
                last={'status':'network_error','reason':type(exc).__name__,'url':url,'retrieved_at':utc()}
                # A local socket permission failure is not a missing product.
                if getattr(exc,'winerror',None)==10013:break
                if attempt<self.retries:self.sleep(3)
                continue
            if not valid_url(final):raise Rejected('redirect_outside_allowed_scope')
            if status in (401,403):
                self.circuit='site_http_'+str(status)
                return {'status':'permission_denied','reason':self.circuit,'url':url,'retrieved_at':utc()}
            if status==429:
                retry=headers.get('Retry-After') or headers.get('retry-after')
                wait=30
                try:wait=max(3,float(retry))
                except (TypeError,ValueError):
                    try:wait=max(3,parsedate_to_datetime(retry).timestamp()-self.clock())
                    except (TypeError,ValueError,OverflowError):pass
                self._set_state({'last_request_at':self.clock(),'next_allowed_at':self.clock()+wait})
                last={'status':'rate_limited','reason':'http_429','url':url,'retrieved_at':utc()}
                if attempt<self.retries and wait<=30:continue
                return last
            if status>=500:
                last={'status':'network_error','reason':'http_'+str(status),'url':url,'retrieved_at':utc()}
                if attempt<self.retries:continue
                return last
            if status not in (200,404):return {'status':'unsupported_mapping','reason':'http_'+str(status),'url':url,'retrieved_at':utc()}
            fetched=utc();content_hash=sha(raw)
            relative='evidence/'+content_hash+'.body';target=self.runtime/relative;target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and sha(target.read_bytes())!=content_hash:raise Rejected('evidence_file_tampered')
            if not target.exists():target.write_bytes(raw)
            value={'url':url,'final_url':final,'http_status':status,'retrieved_at':fetched,'content_sha256':content_hash,
                   'evidence_file':relative,'cached_at':self.clock(),'ttl':900 if status==404 else ttl,'transport_mode':mode}
            entry.parent.mkdir(parents=True,exist_ok=True);tmp=entry.with_suffix('.tmp');tmp.write_text(json.dumps(value),encoding='utf-8');tmp.replace(entry)
            return {**value,'raw':raw,'from_cache':False}
        return last

    def query(self,item):
        expected=normalize(item);code=item.get('jan') or expected['code_raw']
        if item.get('jan'):expected.update(code_raw=str(item['jan']),code_type='JAN')
        result={'schema':'product-site-candidate/1','query_id':item.get('row_id',''),
                'query_identity':expected,'site_id':'anime-store','queried_at':utc(),
                'query_mode':'live_http' if isinstance(self.transport,Transport) else 'synthetic_transport',
                'product_hit':False,'identity_status':'pending','approval':False,
                'automatic_approval':False,'d1_accessed':False,'formal_output':False}
        core={'site_id':'anime-store','query_id':str(item.get('row_id','')),'identity':expected,
              'status':'permission_denied','references':[],'approval':False}
        scope,error=scope_check(self.access_scope)
        if error:
            result.update(status='permission_denied',reason=error,site_response=core,network_attempted=False)
            return result
        if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',code):
            core['status']='unsupported_mapping';result.update(status=core['status'],reason='unsupported_product_code',site_response=core,network_attempted=False);return result
        if self.circuit:
            result.update(status='permission_denied',reason='site_circuit_open:'+self.circuit,site_response=core,network_attempted=False);return result
        url=ORIGIN+'/products/'+quote(code,safe='')
        try:
            with self.lease():
                robots=self._get(ORIGIN+'/robots.txt',ttl=3600)
                if robots.get('http_status')!=200:
                    core['status']=robots.get('status','permission_denied')
                    result.update(status=core['status'],reason='robots_unavailable',site_response=core,network_attempted=True);return result
                rp=RobotFileParser();rp.parse(robots['raw'].decode('utf-8',errors='strict').splitlines())
                if not rp.can_fetch(UA,url):
                    result.update(status='permission_denied',reason='robots_disallow',site_response=core,network_attempted=True);return result
                delay=rp.crawl_delay(UA) or rp.crawl_delay('*') or 0
                rate=rp.request_rate(UA) or rp.request_rate('*')
                if rate:delay=max(delay,rate.seconds/rate.requests)
                if delay>self.interval:
                    self.interval=delay;state=self._state()
                    state['next_allowed_at']=max(state.get('next_allowed_at',0),state.get('last_request_at',0)+delay)
                    self._set_state(state)
                page=self._get(url)
            if 'http_status' not in page:
                core['status']=page['status'];result.update(status=core['status'],reason=page['reason'],site_response=core,network_attempted=True);return result
            if page['http_status']==404:
                core['status']='no_match';result.update(status='no_match',reason='product_route_http_404',site_response=core,network_attempted=True,fetch={k:v for k,v in page.items() if k!='raw'});return result
            parsed=parse(code,page['raw'].decode('utf-8',errors='strict'),expected)
            result.update(parsed);core['status']=parsed['status']
            if parsed['status']=='permission_denied':self.circuit=parsed['reason']
            result['fetch']={k:v for k,v in page.items() if k!='raw'}
            result['query_mode']=page['transport_mode']
            result['access_scope']={'authorization_reference':scope['authorization_reference'],'evidence_sha256':scope['evidence_sha256'],'reviewed_terms_sha256':scope['reviewed_terms_sha256']}
            if parsed.get('material_original') and parsed['identity_status']!='conflict':
                core['references']=[{'url':page['final_url'],'retrieved_at':page['retrieved_at'],'content_sha256':page['content_sha256'],
                    'identity_quote':parsed.get('identity_quote') or code,'material_original':parsed['material_original'],
                    'material_translation':parsed['material_translation'],'evidence_file':page['evidence_file']}]
            validate_response(core)
            result.update(site_response=core,network_attempted=True)
            return result
        except (Rejected,OSError,UnicodeError,ValueError) as exc:
            core.update(status='rate_limited' if str(exc)=='site_cooldown_active' else 'unsupported_mapping',references=[])
            result.update(status=core['status'],reason=str(exc),site_response=core,network_attempted=True)
            return result
