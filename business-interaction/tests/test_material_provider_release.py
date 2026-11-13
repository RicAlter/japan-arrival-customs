"""Release guards for the verified V2 multi-site material provider bundle."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / 'material_providers'
sys.path.insert(0, str(PROVIDER))
import fast_material_batch as provider


class MaterialProviderReleaseTests(unittest.TestCase):
    def test_v2_sop_and_multi_site_provider_are_packaged(self):
        sop = ROOT / 'workbuddy/japan-arrival-customs-trial/references/material-query-sop-v2.md'
        self.assertTrue(sop.is_file())
        self.assertIn('缓存复用 → JAN 快速查询 → 渠道官方页 → 日文名精确回退 → 允许访问的其他零售来源', sop.read_text(encoding='utf-8'))
        self.assertEqual(provider.SITES, ['anime_store', 'colleize', 'amiami', 'jumpcs', 'amnibus'])
        self.assertTrue((PROVIDER / 'vendor/jp_material_query/jpmaterial/engine.py').is_file())

    def test_429_stops_only_its_own_site(self):
        anime = provider.Client('anime_store')
        colleize = provider.Client('colleize')
        with patch('urllib.request.urlopen', side_effect=HTTPError('https://test.invalid', 429, 'fixture', {}, None)):
            self.assertEqual(anime.get('https://test.invalid/a')['error'], 'rate_limited_429')
        self.assertEqual(anime.get('https://test.invalid/a')['error'], 'rate_limited_429')
        self.assertEqual(colleize.stopped, '')


if __name__ == '__main__':
    unittest.main()
