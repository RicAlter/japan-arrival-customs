# -*- coding: utf-8 -*-
"""AMNIBUS 适配器（官方通贩，直接公开页面访问，无需登录/API）。

搜索：https://amnibus.com/products/list?search_words=<商品名>
详情：https://amnibus.com/products/detail/<id>
素材位于 <div class="detailSpec"> 的「素材：…」，与「サイズ：…」分开。

注意：详情页不展示 JAN，因此身份核对只能按“日文名 + 版本/规格”进行，
结果一律标记需要人工复核，不会自动判定为 JAN 一致。
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from ..models import Evidence, ProductQuery, ProductRef
from .base import SiteAdapter, strip_site_suffix


class AmnibusAdapter(SiteAdapter):
    site_id = "amnibus"
    site_name = "AMNIBUS"
    requires_search = True
    search_url_template = "https://amnibus.com/products/list?search_words={query}"

    @staticmethod
    def _search_terms(query: ProductQuery) -> str:
        name = (query.name_ja or query.description_ja or "").strip()
        # 去掉规格/盒型括注，如 (単位/BOX)、（全N種）等，避免干扰检索
        name = re.sub(r"[（(【\[].*?[）)】\]]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name or query.jan

    def build_search_url(self, query: ProductQuery) -> str:
        return "https://amnibus.com/products/list?search_words=" + quote(self._search_terms(query))

    def parse_detail(self, payload: Any, query: ProductQuery, url: str = "", ref: ProductRef | None = None) -> Evidence:
        evidence = super().parse_detail(payload, query, url, ref)
        # 标题常带「｜AMNIBUS」站点后缀，去掉以提高名称相似度
        evidence.name_ja = strip_site_suffix(evidence.name_ja)
        notes = [evidence.notes] if evidence.notes else []
        notes.append("AMNIBUS 页面不展示 JAN，身份仅按日文名/版本核对，需人工复核")
        evidence.notes = "；".join(x for x in notes if x)
        return evidence
