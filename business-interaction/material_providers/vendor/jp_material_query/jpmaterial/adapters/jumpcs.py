# -*- coding: utf-8 -*-
"""Jump Character Store 适配器。

历史入口：https://jumpcs.shueisha.co.jp/shop/g/g<JAN>/
JAN 前缀 4530430 只是筛选线索，不作为商品身份批准条件。
"""
from __future__ import annotations

from typing import Any

from ..models import Evidence, ProductQuery, ProductRef
from .base import SiteAdapter


class JumpCharacterStoreAdapter(SiteAdapter):
    site_id = "jumpcs"
    site_name = "Jump Character Store"
    requires_search = False
    detail_url_template = "https://jumpcs.shueisha.co.jp/shop/g/g{value}/"

    def parse_detail(self, payload: Any, query: ProductQuery, url: str = "", ref: ProductRef | None = None) -> Evidence:
        evidence = super().parse_detail(payload, query, url, ref)
        notes = [evidence.notes] if evidence.notes else []
        if not query.jan.startswith("4530430"):
            notes.append("JAN 前缀不是 4530430，前缀仅作筛选线索，不构成身份认定")
        evidence.notes = "；".join(x for x in notes if x)
        return evidence
