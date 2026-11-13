# -*- coding: utf-8 -*-
"""Anime Store 适配器。

历史入口：https://anime-store.jp/products/<JAN>
重点：支持“■素材”，并严格排除“サイズ”。
"""
from __future__ import annotations

from .base import SiteAdapter


class AnimeStoreAdapter(SiteAdapter):
    site_id = "anime_store"
    site_name = "Anime Store"
    requires_search = False
    detail_url_template = "https://anime-store.jp/products/{value}"
