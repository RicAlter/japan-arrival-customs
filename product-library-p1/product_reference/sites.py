"""Future five-site boundary. This P1 performs no HTTP or browser operations."""
from .core import Rejected
from .b4_store import IDENTITY_FIELDS
from .query import normalize
from urllib.parse import urlparse
import re

SITES = {'anime-store': 'anime-store.jp', 'amiami': 'amiami.jp',
         'animate': 'animate-onlineshop.jp', '1999': '1999.co.jp', 'jumpcs': 'jumpcs.shueisha.co.jp'}
STATUSES = {'succeeded','no_match','no_data','permission_denied','rate_limited','network_error','unsupported_mapping','partial_failure'}


def requests_for(items):
    if not isinstance(items, list):
        raise Rejected('五站计划须为逐行身份数组')
    return [{'schema': 'product-site-query/1', 'site_id': site, 'domain': domain,
             'query_id': str(index), 'identity': normalize(q), 'status': 'not_connected',
             'authorization_required': True, 'network_enabled': False}
            for index, q in enumerate(items) for site, domain in SITES.items()]


def validate_response(value):
    if (not isinstance(value, dict) or set(value) != {'site_id','query_id','identity','status','references','approval'}
            or value['site_id'] not in SITES or value['status'] not in STATUSES or value['approval'] is not False):
        raise Rejected('五站响应合同无效或含批准状态')
    if not isinstance(value['references'], list):
        raise Rejected('来源引用必须为数组')
    if not isinstance(value['identity'], dict) or set(value['identity']) != set(IDENTITY_FIELDS):
        raise Rejected('五站响应必须保留五项身份，缺项显式null')
    if value['status'] == 'succeeded' and not value['references']:
        raise Rejected('成功响应须带原文、身份及证据，不能只给材质结论')
    for reference in value['references']:
        required = {'url','retrieved_at','content_sha256','identity_quote','material_original','material_translation','evidence_file'}
        if set(reference) != required or not all(reference[k] for k in required - {'material_translation'}):
            raise Rejected('五站引用证据缺失')
        parsed = urlparse(reference['url']); host = parsed.hostname or ''
        domain = SITES[value['site_id']]
        if parsed.scheme != 'https' or not (host == domain or host.endswith('.'+domain)):
            raise Rejected('五站引用URL与站点不符')
        if not re.fullmatch('[0-9a-f]{64}', reference['content_sha256']):
            raise Rejected('五站响应缺有效内容哈希')
        if '等' in reference['material_original'] and reference['material_translation'] and '等' not in reference['material_translation']:
            raise Rejected('材质译文遗漏“等”')
    return value
