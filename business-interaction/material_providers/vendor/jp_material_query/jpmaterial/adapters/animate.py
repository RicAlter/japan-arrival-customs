# -*- coding: utf-8 -*-
"""Animate 适配器（备用，默认关闭）。

历史入口：https://www.animate-onlineshop.jp/products/list.php?mode=search&smt=<JAN>
2026-10 起持续 403；保留独立模块与开关，未满足许可及可用性条件前不自动访问。
"""
from __future__ import annotations

from .base import SiteAdapter


class AnimateAdapter(SiteAdapter):
    site_id = "animate"
    site_name = "Animate"
    requires_search = True
    search_url_template = "https://www.animate-onlineshop.jp/products/list.php?mode=search&smt={jan}"
