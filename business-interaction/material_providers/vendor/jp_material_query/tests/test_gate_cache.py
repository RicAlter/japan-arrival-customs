# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jpmaterial.models import AccessStatus, MatchStatus, OverallStatus, ProductQuery
from jpmaterial.transport import HttpResponse
from tests.util import FakeTransport, build_engine, read_fixture


class GateTests(unittest.TestCase):
    def test_unauthorized_makes_no_network_call(self):
        with TemporaryDirectory() as tmp:
            transport = FakeTransport(fail_if_called=True)
            engine, *_ = build_engine(tmp, transport=transport)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(transport.calls, [])
            self.assertEqual(r.status, OverallStatus.NOT_AUTHORIZED)
            self.assertTrue(any(a.status == AccessStatus.NOT_AUTHORIZED for a in r.attempts))

    def test_authorized_can_query(self):
        with TemporaryDirectory() as tmp:
            transport = FakeTransport([HttpResponse(url="", status_code=200, text=read_fixture("historical", "anime_store", "detail.html"))])
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, transport=transport)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(r.status, OverallStatus.CANDIDATE_READY)
            self.assertEqual(r.recommended.material_zh, "纸、钢等")

    def test_403_blocks_site_until_reset(self):
        with TemporaryDirectory() as tmp:
            transport = FakeTransport([HttpResponse(url="", status_code=403, text="forbidden")])
            engine, _, _, access = build_engine(tmp, authorized={"anime_store"}, transport=transport)
            q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版")
            r1 = engine.query(q, allow_online=True)
            self.assertEqual(r1.status, OverallStatus.ERROR)
            self.assertTrue(any(a.status == AccessStatus.BLOCKED_403 for a in r1.attempts))
            self.assertEqual(len(transport.calls), 1)
            r2 = engine.query(q, allow_online=True)
            self.assertEqual(len(transport.calls), 1)
            self.assertTrue(any(a.status == AccessStatus.BLOCKED_403 for a in r2.attempts))
            access.reset("anime_store")
            transport.responses.append(HttpResponse(url="", status_code=200, text=read_fixture("historical", "anime_store", "detail.html")))
            r3 = engine.query(q, allow_online=True)
            self.assertEqual(r3.status, OverallStatus.CANDIDATE_READY)
            self.assertEqual(len(transport.calls), 2)

    def test_429_retry_then_success(self):
        with TemporaryDirectory() as tmp:
            transport = FakeTransport([
                HttpResponse(url="", status_code=429, text="slow down", headers={"Retry-After": "1"}),
                HttpResponse(url="", status_code=200, text=read_fixture("historical", "anime_store", "detail.html")),
            ])
            sleeps = []
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, transport=transport, sleeper=sleeps.append)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(r.status, OverallStatus.CANDIDATE_READY)
            self.assertEqual(len(transport.calls), 2)
            self.assertIn(1.0, sleeps)

    def test_network_error_is_not_no_material(self):
        with TemporaryDirectory() as tmp:
            transport = FakeTransport([HttpResponse(url="", status_code=None, error="network: boom")])
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, transport=transport)
            r = engine.query(ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版"), allow_online=True)
            self.assertEqual(r.status, OverallStatus.ERROR)
            self.assertNotEqual(r.status, OverallStatus.NO_MATERIAL)
            self.assertTrue(any(a.status == AccessStatus.NETWORK_ERROR for a in r.attempts))

    def test_cache_reuse(self):
        with TemporaryDirectory() as tmp:
            transport = FakeTransport([HttpResponse(url="", status_code=200, text=read_fixture("historical", "anime_store", "detail.html"))])
            engine, *_ = build_engine(tmp, authorized={"anime_store"}, transport=transport)
            q = ProductQuery(jan="4571608537527", name_ja="テスト フィギュア 通常版")
            r1 = engine.query(q, allow_online=True)
            self.assertEqual(r1.status, OverallStatus.CANDIDATE_READY)
            r2 = engine.query(q, allow_online=True)
            self.assertEqual(len(transport.calls), 1)
            self.assertTrue(r2.cache_hit)
            self.assertTrue(r2.recommended.from_cache)
