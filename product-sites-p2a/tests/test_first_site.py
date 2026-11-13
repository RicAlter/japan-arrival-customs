"""All HTTP here is synthetic. No test assertion is a real-site success claim."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

from site_reference.client import AnimeStore, Transport, Redirect, scope_check, sha
from site_reference.parser import parse,translate
from site_reference.batch import run,metrics
from site_reference.bundle import export
from site_reference.compat import Rejected
from product_reference.b4_store import verify_bundle


def item(**changes):
    q={'row_id':'synthetic-row','code_raw':'00123','code_type':'source_identifier',
       'japanese_name':'テスト商品','version':'v1','specification':'red'}
    q.update(changes);return q


def product(**changes):
    p={'@type':'Product','sku':'00123','name':'テスト商品',
       'description':'■素材：紙、スチール等\n■サイズ：10cm',
       'additionalProperty':[{'name':'version','value':'v1'},{'name':'specification','value':'red'}]}
    p.update(changes);return p


def page(p=None):
    encoded=json.dumps(p or product(),ensure_ascii=False).replace('</','<\\/')
    return ('<html><title>Synthetic product</title><script type="application/ld+json">'+encoded+'</script></html>').encode()


class Clock:
    def __init__(self):self.value=1000;self.waits=[]
    def time(self):return self.value
    def sleep(self,value):self.waits.append(value);self.value+=value


class Fake:
    def __init__(self,responses=None,robots=b'User-agent: *\nAllow: /\n'):
        self.responses=list(responses or [(200,page(),{},'https://anime-store.jp/products/00123')]);self.robots=robots;self.calls=[]
    def __call__(self,url):
        self.calls.append(url)
        if url.endswith('/robots.txt'):return 200,self.robots,{},url
        value=self.responses.pop(0)
        if isinstance(value,Exception):raise value
        return value


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.clock=Clock()
        self.permission=self.root/'permission.txt';self.permission.write_text('SYNTHETIC TEST ONLY, NOT SITE AUTHORIZATION',encoding='utf-8')
        self.scope=self.root/'scope.json';self.scope.write_text(json.dumps({
            'schema':'product-site-access-scope/1','site_id':'anime-store','purpose':'internal_product_reference',
            'authorization_reference':'SYNTHETIC-ONLY','operator_review_reference':'SYNTHETIC-ONLY',
            'evidence_file':str(self.permission),'evidence_sha256':sha(self.permission.read_bytes()),
            'reviewed_terms_sha256':'a'*64,'expires_at':'2099-01-01T00:00:00+00:00',
            'allowed_path_prefixes':['/products/']}),encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def client(self,transport=None,scope=True):
        self.fake=transport or Fake()
        return AnimeStore(self.root/'runtime',access_scope=self.scope if scope else None,
                          transport=self.fake,sleep=self.clock.sleep,clock=self.clock.time)

    def test_no_site_permission_means_zero_network_and_no_runtime_write(self):
        c=self.client(scope=False);r=c.query(item())
        self.assertEqual(r['status'],'permission_denied');self.assertEqual(c.network_calls,0)
        self.assertFalse(self.fake.calls);self.assertFalse((self.root/'runtime').exists())

    def test_expired_or_tampered_permission_is_denied(self):
        data=json.loads(self.scope.read_text());data['expires_at']='2020-01-01T00:00:00+00:00';self.scope.write_text(json.dumps(data))
        self.assertIsNone(scope_check(self.scope)[0]);c=self.client();self.assertEqual(c.query(item())['status'],'permission_denied');self.assertFalse(self.fake.calls)
        data['expires_at']='2099-01-01T00:00:00+00:00';self.scope.write_text(json.dumps(data));self.permission.write_text('CHANGED')
        self.assertIn('hash_mismatch',scope_check(self.scope)[1])

    def test_code_only_never_confirms_identity(self):
        r=self.client().query(item(japanese_name=None,version=None,specification=None))
        self.assertTrue(r['product_hit']);self.assertEqual(r['identity_status'],'pending');self.assertFalse(r['automatic_approval'])

    def test_full_identity_agreement_is_separate_from_formal_approval(self):
        r=self.client().query(item());self.assertEqual(r['identity_status'],'confirmed')
        self.assertEqual(r['material_original'],'紙、スチール等');self.assertEqual(r['material_translation'],'纸、钢等')
        self.assertFalse(r['site_response']['approval']);self.assertEqual(r['query_mode'],'synthetic_transport')

    def test_same_code_wrong_name_is_rejected(self):
        r=self.client().query(item(japanese_name='別の商品'))
        self.assertEqual(r['identity_status'],'conflict');self.assertFalse(r['site_response']['references'])

    def test_same_code_wrong_version_or_spec_is_rejected(self):
        for key in ('version','specification'):
            r=parse('00123',page().decode(),item(**{key:'different'}));self.assertEqual(r['identity_status'],'conflict')

    def test_url_slug_is_not_product_code_evidence(self):
        r=parse('00123',page(product(sku='00999')).decode(),item())
        self.assertEqual(r['status'],'unsupported_mapping');self.assertFalse(r['product_hit'])

    def test_multiple_same_code_products_do_not_select_first(self):
        r=parse('00123',page([product(),product(name='Different')]).decode(),item())
        self.assertEqual(r['identity_status'],'conflict');self.assertEqual(r['reason'],'multiple_products_with_same_code')

    def test_full_multiline_material_and_qualifier_preserved(self):
        description='<p>素材：</p><p>本体：アクリル</p><p>金具：鉄・亜鉛合金等</p><p>サイズ：10cm</p>'
        r=parse('00123',page(product(description=description)).decode(),item())
        self.assertEqual(r['material_original'],'本体：アクリル\n金具：鉄・亜鉛合金等')
        self.assertEqual(r['material_translation'],'主体：亚克力\n金属配件：铁・锌合金等')

    def test_unknown_translation_keeps_complete_original_and_null_translation(self):
        original='アクリル・セルロイド等';translated,unknown=translate(original)
        self.assertIsNone(translated);self.assertTrue(unknown)
        r=parse('00123',page(product(description='素材：'+original)).decode(),item())
        self.assertEqual(r['material_original'],original);self.assertIsNone(r['material_translation'])

    def test_missing_material_and_missing_version_are_not_invented(self):
        r=parse('00123',page(product(description='サイズ：10cm',additionalProperty=[])).decode(),item())
        self.assertEqual(r['status'],'no_data');self.assertIsNone(r['observed_identity']['version']);self.assertIsNone(r['material_original'])

    def test_script_text_and_related_product_are_not_material_evidence(self):
        p=product(description='<script>素材：偽の情報</script><p>素材：紙</p>')
        r=parse('00123',page([p,product(sku='00999',description='素材：金属')]).decode(),item())
        self.assertEqual(r['material_original'],'紙')

    def test_malformed_structured_identity_stays_pending_without_crash(self):
        p=product(name={'unexpected':'object'},description=['not','text'],additionalProperty=[{'name':{},'value':[]}])
        r=parse('00123',page(p).decode(),item())
        self.assertEqual(r['status'],'no_data');self.assertEqual(r['identity_status'],'pending');self.assertIsNone(r['observed_identity']['japanese_name'])

    def test_structured_property_conflict_is_not_hidden_by_fallback(self):
        props=product()['additionalProperty']+[{'name':'version','value':'v2'}]
        r=parse('00123',page(product(additionalProperty=props,description='バージョン：v1\n素材：紙')).decode(),item())
        self.assertEqual(r['identity_status'],'conflict')

    def test_jan_namespace_needs_gtin_evidence(self):
        q=item(code_raw='1234567890128',code_type='JAN')
        p=product(sku='1234567890128')
        self.assertEqual(parse(q['code_raw'],page(p).decode(),q)['identity_status'],'pending')
        p['gtin13']=q['code_raw'];self.assertEqual(parse(q['code_raw'],page(p).decode(),q)['identity_status'],'confirmed')

    def test_robots_disallow_stops_product_request(self):
        fake=Fake(robots=b'User-agent: *\nDisallow: /products/\n');c=self.client(fake)
        self.assertEqual(c.query(item())['status'],'permission_denied');self.assertEqual(len(fake.calls),1)

    def test_robots_crawl_delay_is_respected_without_long_blocking_sleep(self):
        fake=Fake(robots=b'User-agent: *\nAllow: /\nCrawl-delay: 60\n');c=self.client(fake)
        self.assertEqual(c.query(item())['status'],'rate_limited');self.assertEqual(len(fake.calls),1)
        self.clock.value+=60
        self.assertEqual(c.query(item())['status'],'succeeded');self.assertEqual(len(fake.calls),2)

    def test_403_is_not_retried_and_opens_circuit(self):
        fake=Fake([(403,b'',{},'https://anime-store.jp/products/00123')]);c=self.client(fake)
        self.assertEqual(c.query(item())['status'],'permission_denied');count=len(fake.calls)
        self.assertEqual(c.query(item(code_raw='00999'))['status'],'permission_denied');self.assertEqual(len(fake.calls),count)

    def test_429_long_retry_after_keeps_cooldown_and_is_not_no_match(self):
        fake=Fake([(429,b'',{'Retry-After':'120'},'https://anime-store.jp/products/00123')]);c=self.client(fake)
        self.assertEqual(c.query(item())['status'],'rate_limited');self.assertEqual(len(fake.calls),2)
        self.assertEqual(c.query(item())['status'],'rate_limited');self.assertEqual(len(fake.calls),2)

    def test_429_bounded_retry_respects_delay(self):
        fake=Fake([(429,b'',{'Retry-After':'6'},'https://anime-store.jp/products/00123'),(200,page(),{},'https://anime-store.jp/products/00123')]);c=self.client(fake)
        self.assertEqual(c.query(item())['status'],'succeeded');self.assertIn(6,self.clock.waits);self.assertEqual(len(fake.calls),3)

    def test_network_error_has_one_retry_and_no_negative_product_cache(self):
        fake=Fake([URLError('offline'),URLError('offline')]);c=self.client(fake)
        self.assertEqual(c.query(item())['status'],'network_error');self.assertEqual(len(fake.calls),3)

    def test_cache_reparses_each_expected_identity(self):
        c=self.client();self.assertEqual(c.query(item())['status'],'succeeded');calls=len(self.fake.calls)
        self.assertEqual(c.query(item(version='v2'))['identity_status'],'conflict')
        self.assertEqual(len(self.fake.calls),calls);self.assertGreaterEqual(c.cache_hits,2)

    def test_tampered_cache_is_rejected(self):
        c=self.client();r=c.query(item());(self.root/'runtime'/r['fetch']['evidence_file']).write_bytes(b'changed')
        self.assertEqual(c.query(item())['reason'],'cached_evidence_hash_mismatch')

    def test_404_is_a_route_miss_and_uses_short_negative_cache(self):
        fake=Fake([(404,b'',{},'https://anime-store.jp/products/00123')]);c=self.client(fake)
        r=c.query(item());self.assertEqual(r['reason'],'product_route_http_404');calls=len(fake.calls)
        self.assertEqual(c.query(item())['status'],'no_match');self.assertEqual(len(fake.calls),calls)

    def test_external_redirect_is_rejected_before_sending(self):
        with self.assertRaises(Rejected):Redirect().redirect_request(Request('https://anime-store.jp/products/00123'),None,302,'',{},'https://invalid.example/private')

    def test_metrics_are_null_when_real_queries_have_not_run(self):
        c=self.client(scope=False);r=run({'items':[item()]},self.root/'out',self.root/'runtime',client=c)
        m=r['metrics'];self.assertIsNone(m['product_hit_rate']);self.assertIsNone(m['identity_confirmation_rate']);self.assertIsNone(m['false_association_rate'])
        self.assertEqual(m['network_calls'],0)

    def test_no_credential_fields_and_no_overwrite(self):
        with self.assertRaises(Rejected):run({'items':[dict(item(),token='PRIVATE')]},self.root/'out',self.root/'runtime')
        (self.root/'out').mkdir()
        with self.assertRaises(Rejected):run({'items':[]},self.root/'out',self.root/'runtime')

    def test_denied_or_synthetic_results_cannot_export_as_live_sources(self):
        for name,scope in [('denied',False),('synthetic',True)]:
            c=self.client(scope=scope);out=self.root/name;run({'items':[item()]},out,self.root/'runtime',client=c)
            with self.assertRaises(Rejected):export(out/'candidates.json',self.root/'runtime',self.root/(name+'-bundle'),authorization_reference='TEST:fixture',source_id='synthetic')

    def test_mocked_live_contract_exports_hash_checked_v1_bundle(self):
        fake=Fake();transport=Transport()
        with patch.object(Transport,'__call__',side_effect=fake):
            c=AnimeStore(self.root/'runtime',access_scope=self.scope,transport=transport,sleep=self.clock.sleep,clock=self.clock.time)
            run({'items':[item()]},self.root/'out',self.root/'runtime',client=c)
        export(self.root/'out/candidates.json',self.root/'runtime',self.root/'bundle',authorization_reference='TEST:fixture',source_id='synthetic')
        verified=verify_bundle(self.root/'bundle');self.assertEqual(len(verified['records']),1)
        self.assertFalse(verified['records'][0]['approval']);self.assertEqual(verified['records'][0]['fields']['material_original']['value'],'紙、スチール等')

    def test_candidate_source_and_identity_state_tamper_rejected_before_export(self):
        fake=Fake();transport=Transport()
        with patch.object(Transport,'__call__',side_effect=fake):
            c=AnimeStore(self.root/'runtime',access_scope=self.scope,transport=transport,sleep=self.clock.sleep,clock=self.clock.time)
            run({'items':[item(version=None)]},self.root/'out',self.root/'runtime',client=c)
        path=self.root/'out/candidates.json';data=json.loads(path.read_text(encoding='utf-8'))
        data['results'][0]['identity_status']='confirmed';path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(Rejected,'身份确认状态'):export(path,self.root/'runtime',self.root/'bad-bundle',authorization_reference='TEST:fixture',source_id='synthetic')
        data['results'][0]['identity_status']='pending';data['results'][0]['site_response']['references'][0]['url']='https://anime-store.jp/products/OTHER';path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(Rejected,'引用与抓取来源'):export(path,self.root/'runtime',self.root/'bad-bundle',authorization_reference='TEST:fixture',source_id='synthetic')


if __name__=='__main__':unittest.main()
