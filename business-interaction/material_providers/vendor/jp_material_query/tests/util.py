# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jpmaterial.access import AccessRegistry
from jpmaterial.adapters import (
    AmiAmiAdapter, AmnibusAdapter, AnimateAdapter, AnimeStoreAdapter,
    HobbySearchAdapter, JumpCharacterStoreAdapter, LocalLibrary,
)
from jpmaterial.cache import CacheStore
from jpmaterial.config import load_glossary, load_sites
from jpmaterial.engine import QueryEngine
from jpmaterial.models import SitePolicy
from jpmaterial.transport import HttpResponse

ADAPTER_CLASSES = {
    "amnibus": AmnibusAdapter,
    "anime_store": AnimeStoreAdapter,
    "amiami": AmiAmiAdapter,
    "jumpcs": JumpCharacterStoreAdapter,
    "hobbysearch": HobbySearchAdapter,
    "animate": AnimateAdapter,
}


class FakeTransport:
    def __init__(self, responses=None, fail_if_called=False):
        self.responses = list(responses or [])
        self.calls = []
        self.fail_if_called = fail_if_called

    def get(self, url, headers=None):
        self.calls.append(url)
        if self.fail_if_called:
            raise AssertionError(f"不应发出网络请求，但请求了：{url}")
        if self.responses:
            resp = self.responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp
        return HttpResponse(url=url, status_code=200, text="", headers={})


def build_policies(authorized=(), enabled=None):
    policies = load_sites(ROOT / "config" / "sites.json")
    authorized = set(authorized)
    for p in policies:
        p.authorized = p.site_id in authorized
        if enabled is not None:
            p.enabled = bool(enabled.get(p.site_id, p.enabled))
    return policies


def build_engine(tmp_path, authorized=(), enabled=None, transport=None, local=None, clock=None, sleeper=None):
    policies = build_policies(authorized, enabled)
    glossary = load_glossary(ROOT / "config")
    adapters = {p.site_id: ADAPTER_CLASSES[p.site_id](p, glossary) for p in policies}
    cache = CacheStore(Path(tmp_path) / "cache.json", clock=clock)
    access = AccessRegistry(Path(tmp_path) / "access.json", clock=clock)
    engine = QueryEngine(
        policies, adapters, transport or FakeTransport(fail_if_called=True),
        cache, access, local, clock=clock, sleeper=sleeper,
    )
    return engine, policies, cache, access


def fixture(*parts):
    return ROOT / "fixtures" / Path(*parts)


def read_fixture(*parts):
    return fixture(*parts).read_text(encoding="utf-8", errors="replace")
