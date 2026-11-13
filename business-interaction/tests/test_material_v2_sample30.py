"""Real material regressions plus explicitly offline fault-injection cases."""
from pathlib import Path
import copy, hashlib, io, json, sys, tempfile, unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'material_providers'))
import fast_material_batch as provider
from quality import material_quality
FIXTURES=Path(__file__).parent/'fixtures/material-v2-sample30'
DATA=json.loads((FIXTURES/'cases.json').read_text(encoding='utf8'))

class Sample30Tests(unittest.TestCase):
    def test_nine_real_responses_preserve_only_complete_material_fields(self):
        for c in DATA['cases']:
            with self.subTest(sample=c['sample_id']):
                raw=(FIXTURES/c['file']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),c['sha256'])
                if c['api_json']:
                    def records(value):
                        if isinstance(value,dict):
                            if 'spec' in value:yield value
                            for x in value.values():yield from records(x)
                        elif isinstance(value,list):
                            for x in value:yield from records(x)
                    product=next(records(json.loads(raw)))
                    body=str(product['spec'])+'\n'+str(product.get('memo',''))
                else:body=raw.decode(c['encoding'])
                material,method=provider.extract(body)
                self.assertEqual(provider.norm(material),provider.norm(c['expected']))
                self.assertTrue(material_quality(material))
                self.assertTrue(material_quality(provider.translate(material)))
                if c['sample_id']==26:self.assertIn('贴纸',provider.translate(material))
                if c['sample_id']==19:
                    self.assertIn('背面',provider.translate(material));self.assertIn('オーロラホロ',provider.translate(material))
    def test_components_and_percentage_survive(self):
        original='本体：ポリエステル・鉄・PVC\nボールチェーン（金属）\n綿100%'
        translated=provider.translate(original)
        for value in ['PVC','100%','金属','铁']:
            self.assertIn(value,translated)
        self.assertIn('珠链',translated)
    def test_noise_in_cached_material_is_rejected(self):
        for value in ['Cotton 100%\nColor: BLACK','Acrylic\nFeatures: Base',
                      'PVC\n商品仕様種類数 全6種','纸；@context：Product']:
            self.assertFalse(material_quality(value),value)
    def test_unit_wrapper_is_not_a_new_product_but_requires_identity_chain(self):
        row=copy.deepcopy(DATA['amnibus_chain']['row'])
        row['identity_chain']['snapshot']=str(FIXTURES/'amnibus-jan-chain.raw')
        candidate=DATA['amnibus_chain']['candidate']
        self.assertEqual(provider.identity(row,candidate),
                         (True,'cached_exact_JAN_chain_and_official_name_scope'))
        without=dict(row);without.pop('identity_chain')
        self.assertFalse(provider.identity(without,candidate)[0])
    def test_wrong_chain_hash_or_jan_cannot_confirm_name_fallback(self):
        row=copy.deepcopy(DATA['amnibus_chain']['row'])
        row['identity_chain']['snapshot']=str(FIXTURES/'amnibus-jan-chain.raw')
        candidate=DATA['amnibus_chain']['candidate']
        row['identity_chain']['content_sha256']='0'*64
        self.assertFalse(provider.identity(row,candidate)[0])
        row['jan']='0000000000000'
        self.assertFalse(provider.identity(row,candidate)[0])
    def test_chain_title_must_be_in_the_actual_structured_source(self):
        row=copy.deepcopy(DATA['amnibus_chain']['row'])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'wrong.json'
            p.write_text(json.dumps({'janCode':row['jan'],'name':'different real product'}),encoding='utf8')
            row['identity_chain'].update(snapshot=str(p),content_sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertFalse(provider.identity(row,DATA['amnibus_chain']['candidate'])[0])
    def test_cached_official_evidence_also_validates_the_secondary_jan_snapshot(self):
        from interaction.material_review import read_evidence
        candidate=copy.deepcopy(DATA['amnibus_evidence'])
        candidate['snapshot']=str(FIXTURES/'amnibus-live-detail.raw')
        candidate['identity_chain']['snapshot']=str(FIXTURES/'amnibus-jan-chain.raw')
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'candidate.json'
            file.write_text(json.dumps({'candidates':[candidate]}),encoding='utf8')
            good,bad=read_evidence([file]);self.assertTrue(good);self.assertFalse(bad)
            candidate['identity_chain']['content_sha256']='0'*64
            file.write_text(json.dumps({'candidates':[candidate]}),encoding='utf8')
            good,bad=read_evidence([file]);self.assertFalse(good)
            self.assertEqual(bad[0]['reason'],'raw_snapshot_hash_mismatch')
    def test_403_429_stop_only_that_client_and_preserve_response_evidence(self):
        # Fault injection uses HTTP codes observed in the historical error log.
        # These are not reported as newly observed website failures.
        for code,status in [(403,'blocked_403'),(429,'rate_limited_429')]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                body=b'OFFLINE ERROR HANDLER FIXTURE'
                error=HTTPError('https://example.invalid/product',code,'offline',
                                {'Retry-After':'60'},io.BytesIO(body))
                with patch.object(provider,'REPORT',Path(tmp)),patch('urllib.request.urlopen',side_effect=error) as get:
                    client=provider.Client('anime_store')
                    record=client.get('https://example.invalid/product')
                    self.assertEqual(record['error'],status)
                    self.assertEqual(client.get('https://example.invalid/second')['error'],status)
                    self.assertEqual(get.call_count,1)
                    p=Path(record['snapshot'])
                    self.assertEqual(p.read_bytes(),body)
                    self.assertEqual(record['content_sha256'],hashlib.sha256(body).hexdigest())
                    self.assertEqual(record['retry_after'],'60')
                    self.assertFalse(provider.Client('colleize').stopped)
    def test_local_permission_failure_is_not_a_website_failure(self):
        with patch('urllib.request.urlopen',side_effect=URLError(PermissionError(13,'offline denied'))):
            result=provider.Client('jumpcs').get('https://example.invalid/product')
        self.assertEqual(result['error'],'environment_permission_blocked')
        self.assertNotIn('status',result)
    def test_no_material_and_parse_failure_are_different(self):
        self.assertEqual(provider.extract('<p>サイズ：20mm</p>')[1],'no_material')
        self.assertEqual(provider.extract('素材：アクリル\nお気に入り作品一覧')[1],'parse_error')
    def test_matching_page_failure_is_not_reported_as_no_search_result(self):
        raw=(FIXTURES/'13.raw').read_text(encoding='utf8')
        class CapturedDetail:
            def get(self,url):
                return {'url':url,'status':200,'text':raw if '/detail/' in url else '<a href="/products/detail/121311">captured link</a>'}
        row={'jan':'4573643361693','name_ja':'別商品・別のキャラクター','spec':''}
        result=provider.query('amnibus',CapturedDetail(),row['jan'],row)
        self.assertEqual(result['status'],'identity_unresolved')
        class EmptySearch:
            def get(self,url):return {'url':url,'status':200,'data':{'goodsList':[]}}
        self.assertEqual(provider.query('colleize',EmptySearch(),row['jan'],row)['status'],'not_found')
    def test_jan_mismatch_is_not_silently_merged(self):
        row=DATA['amnibus_chain']['row']
        self.assertEqual(provider.identity(row,{'jan':'0000000000000','title':row['name_ja']})[1],'jan_mismatch')

if __name__=='__main__':unittest.main()
