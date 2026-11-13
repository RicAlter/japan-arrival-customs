# -*- coding: utf-8 -*-
"""HobbySearch 适配器。

历史入口：https://www.1999.co.jp/search/?q=<JAN>
详情页需核对 JAN、商品名、版本、规格，再从商品说明/商品规格/素材提取。
"""
from __future__ import annotations

from .base import SiteAdapter


class HobbySearchAdapter(SiteAdapter):
    site_id = "hobbysearch"
    site_name = "HobbySearch"
    requires_search = True
    search_url_template = "https://www.1999.co.jp/search/?q={jan}"
