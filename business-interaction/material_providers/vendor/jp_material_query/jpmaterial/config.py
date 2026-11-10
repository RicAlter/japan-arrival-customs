# -*- coding: utf-8 -*-
"""配置加载：站点授权、翻译词表、本地资料库。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import SitePolicy

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_STATE_DIR = PROJECT_ROOT / "state"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_FIXTURE_DIR = PROJECT_ROOT / "fixtures"

DEFAULT_SITES: dict[str, dict[str, Any]] = {
    "amnibus": {
        "site_name": "AMNIBUS",
        "base_url": "https://amnibus.com/",
        "priority": 5,
        "enabled": True,
        "authorized": True,
        "authorization_note": "官方通贩，直接公开页面访问（无需登录/API）；页面不展示 JAN，结果按名称核对、需人工复核。",
        "allowed_purpose": "日本到货商品材质核对",
        "rate_limit_seconds": 2.0,
        "max_retries": 1,
        "ttl_seconds": 604800,
    },
    "anime_store": {
        "site_name": "Anime Store",
        "base_url": "https://anime-store.jp/",
        "priority": 10,
        "enabled": True,
        "authorized": False,
        "authorization_note": "历史记录仅用于离线解析；未取得站方书面许可，禁止联网。",
        "allowed_purpose": "",
        "rate_limit_seconds": 5.0,
        "max_retries": 2,
        "ttl_seconds": 604800,
    },
    "amiami": {
        "site_name": "AmiAmi",
        "base_url": "https://www.amiami.jp/",
        "priority": 20,
        "enabled": True,
        "authorized": False,
        "authorization_note": "历史 API 记录不是当前 API 合同；未取得站方许可，禁止自动请求。",
        "allowed_purpose": "",
        "rate_limit_seconds": 5.0,
        "max_retries": 2,
        "ttl_seconds": 604800,
    },
    "jumpcs": {
        "site_name": "Jump Character Store",
        "base_url": "https://jumpcs.shueisha.co.jp/",
        "priority": 30,
        "enabled": True,
        "authorized": False,
        "authorization_note": "历史曾出现 403；未取得集英社/站方许可，禁止联网。",
        "allowed_purpose": "",
        "rate_limit_seconds": 8.0,
        "max_retries": 1,
        "ttl_seconds": 604800,
    },
    "hobbysearch": {
        "site_name": "HobbySearch",
        "base_url": "https://www.1999.co.jp/",
        "priority": 40,
        "enabled": True,
        "authorized": False,
        "authorization_note": "历史存在 403；未取得站方许可，禁止联网，也不得使用代理绕过限制。",
        "allowed_purpose": "",
        "rate_limit_seconds": 8.0,
        "max_retries": 1,
        "ttl_seconds": 604800,
    },
    "animate": {
        "site_name": "Animate",
        "base_url": "https://www.animate-onlineshop.jp/",
        "priority": 50,
        "enabled": False,
        "authorized": False,
        "authorization_note": "2026-10 起持续 403，默认关闭；未满足许可及可用性条件前不自动重试。",
        "allowed_purpose": "",
        "rate_limit_seconds": 10.0,
        "max_retries": 0,
        "ttl_seconds": 604800,
    },
}


def load_sites(config_path: str | Path | None = None) -> list[SitePolicy]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_DIR / "sites.json"
    data: dict[str, Any] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = raw.get("sites", raw)
    policies: list[SitePolicy] = []
    for site_id, default in DEFAULT_SITES.items():
        merged = dict(default)
        merged.update(data.get(site_id, {}) or {})
        policies.append(
            SitePolicy(
                site_id=site_id,
                site_name=str(merged.get("site_name", site_id)),
                base_url=str(merged.get("base_url", "")),
                priority=int(merged.get("priority", 100)),
                enabled=bool(merged.get("enabled", True)),
                authorized=bool(merged.get("authorized", False)),
                authorization_note=str(merged.get("authorization_note", "")),
                allowed_purpose=str(merged.get("allowed_purpose", "")),
                rate_limit_seconds=float(merged.get("rate_limit_seconds", 5.0)),
                max_retries=int(merged.get("max_retries", 2)),
                ttl_seconds=int(merged.get("ttl_seconds", 604800)),
                source_type=str(merged.get("source_type", "website")),
            )
        )
    policies.sort(key=lambda p: p.priority)
    return policies


def load_glossary(config_dir: str | Path | None = None) -> dict[str, str]:
    from .translate import load_glossary as _load
    path = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    return _load(path / "glossary.json")


def load_local_index(path: str | Path | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
