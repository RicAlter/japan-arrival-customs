# -*- coding: utf-8 -*-
"""查询引擎：本地资料库优先、站点授权门禁、缓存、错误分类、聚合。"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

from .access import AccessRegistry
from .adapters.base import ParseError, SiteAdapter, make_not_found_evidence
from .cache import CacheStore
from .identity import name_similarity
from .jan import normalize_jan, validate_jan
from .models import (
    AccessStatus,
    Evidence,
    MatchStatus,
    MaterialStatus,
    OverallStatus,
    ProductQuery,
    ProductRef,
    QueryResult,
    SiteAttempt,
    SitePolicy,
)
from .textutil import now_iso, unique_keep_order


@dataclass
class FetchOutcome:
    status: AccessStatus
    response: Any = None
    message: str = ""
    http_status: int | None = None
    elapsed_ms: int = 0


def _parse_retry_after(value: str) -> float:
    if not value:
        return 0.0
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return 0.0


def _material_key(evidence: Evidence) -> str:
    text = evidence.material_zh or evidence.material_original
    text = re.sub(r"[\s、,，・/／|:：()（）\[\]【】]+", "", text or "").lower()
    return text


class QueryEngine:
    def __init__(
        self,
        policies: list[SitePolicy],
        adapters: dict[str, SiteAdapter],
        transport,
        cache: CacheStore,
        access: AccessRegistry,
        local_library=None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.policies = sorted(policies, key=lambda p: p.priority)
        self.adapters = adapters
        self.transport = transport
        self.cache = cache
        self.access = access
        self.local_library = local_library
        self.clock = clock or time.time
        self.sleeper = sleeper or time.sleep
        self._last_request: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------
    def query(
        self,
        query: ProductQuery,
        *,
        allow_online: bool = False,
        all_sites: bool = False,
        input_material: str = "",
    ) -> QueryResult:
        result = QueryResult(query=query, queried_at=now_iso(), input_material=input_material or "")
        if input_material:
            result.status = OverallStatus.EXISTING_MATERIAL
            result.match_status = MatchStatus.EXACT
            result.material_status = MaterialStatus.FOUND
            result.needs_review = False
            result.action = "keep_existing"
            result.reason = "原表已有材质，插件不覆盖、不重复查询"
            return result

        ok, why = validate_jan(query.jan)
        if not ok:
            result.status = OverallStatus.INVALID_INPUT
            result.match_status = MatchStatus.INVALID_JAN
            result.reason = why
            result.needs_review = True
            return result

        # 1) 本地商品资料库优先
        local_found = False
        if self.local_library is not None:
            local_candidates = self.local_library.lookup(query)
            result.candidates.extend(local_candidates)
            keys = {_material_key(c) for c in local_candidates if c.material_status == MaterialStatus.FOUND}
            if local_candidates and len(keys) == 1 and not all_sites:
                local_found = True
                self._aggregate(result)
                return result

        # 2) 站点
        for policy in self.policies:
            decision = self.access.check(policy)
            if not decision.allowed:
                result.attempts.append(SiteAttempt(
                    site_id=policy.site_id,
                    site_name=policy.site_name,
                    status=decision.status,
                    message=decision.reason,
                ))
                continue
            if not allow_online:
                result.attempts.append(SiteAttempt(
                    site_id=policy.site_id,
                    site_name=policy.site_name,
                    status=AccessStatus.SKIPPED,
                    message="在线查询开关未开启（--allow-online）；未发出网络请求",
                ))
                continue

            cached = self.cache.get(policy.site_id, query.jan)
            if cached and isinstance(cached.get("data"), dict):
                evidence = Evidence.from_dict(cached["data"])
                evidence.from_cache = True
                evidence.access_status = AccessStatus.OK
                result.candidates.append(evidence)
                result.attempts.append(SiteAttempt(
                    site_id=policy.site_id,
                    site_name=policy.site_name,
                    status=AccessStatus.CACHED,
                    http_status=200,
                    url=cached.get("url", ""),
                    message=f"缓存命中，抓取时间 {cached.get('fetched_at', '')}",
                    cached=True,
                ))
                result.cache_hit = True
                if not all_sites and evidence.match_status == MatchStatus.EXACT and evidence.material_status == MaterialStatus.FOUND:
                    break
                continue

            evidence, attempts = self._run_site(policy, query, all_sites=all_sites)
            result.attempts.extend(attempts)
            if evidence is not None:
                result.candidates.append(evidence)
                if evidence.access_status == AccessStatus.OK and evidence.match_status in (MatchStatus.EXACT, MatchStatus.JAN_ONLY) and evidence.material_status == MaterialStatus.FOUND:
                    self._cache_evidence(policy, query, evidence)
                if not all_sites and evidence.match_status == MatchStatus.EXACT and evidence.material_status == MaterialStatus.FOUND:
                    break

        self._aggregate(result)
        return result

    def query_offline(self, query: ProductQuery, fixture_root: str | Path, site_ids: list[str] | None = None) -> QueryResult:
        """离线解析已保存样本；不检查授权、不联网。"""
        allowed_sites = set(site_ids) if site_ids else None
        result = QueryResult(query=query, queried_at=now_iso())
        ok, why = validate_jan(query.jan)
        if not ok:
            result.status = OverallStatus.INVALID_INPUT
            result.match_status = MatchStatus.INVALID_JAN
            result.reason = why
            return result
        root = Path(fixture_root)
        for policy in self.policies:
            if allowed_sites is not None and policy.site_id not in allowed_sites:
                continue
            adapter = self.adapters.get(policy.site_id)
            if adapter is None:
                continue
            site_dir = root / policy.site_id
            if not site_dir.exists():
                continue
            try:
                evidence = self._parse_fixture_dir(adapter, query, site_dir)
            except Exception as exc:
                result.candidates.append(self._parse_error_evidence(policy, query, "", f"离线样本解析失败：{exc}"))
                result.attempts.append(SiteAttempt(
                    site_id=policy.site_id, site_name=policy.site_name,
                    status=AccessStatus.PARSE_ERROR, message=str(exc),
                ))
                continue
            if evidence is None:
                continue
            result.candidates.append(evidence)
            result.attempts.append(SiteAttempt(
                site_id=policy.site_id,
                site_name=policy.site_name,
                status=AccessStatus.OK,
                http_status=None,
                url=evidence.product_url,
                message="离线样本解析；未联网",
            ))
        self._aggregate(result)
        return result

    def query_snapshots(
        self,
        query: ProductQuery,
        snapshot_root: str | Path,
        site_ids: list[str] | None = None,
        all_sites: bool = False,
    ) -> QueryResult:
        """解析人工保存的本地页面快照；不联网、不需要登录、不检查站方授权。

        目录结构（推荐）：
        snapshots/<site_id>/<JAN>/detail.html
        snapshots/<site_id>/<JAN>/search.html + detail.html
        snapshots/<site_id>/<JAN>.html
        snapshots/<site_id>/<JAN>.json

        注意：快照必须由使用者自行在浏览器中打开并保存；插件不发起站点请求。
        """
        allowed_sites = set(site_ids) if site_ids else None
        result = QueryResult(query=query, queried_at=now_iso())
        ok, why = validate_jan(query.jan)
        if not ok:
            result.status = OverallStatus.INVALID_INPUT
            result.match_status = MatchStatus.INVALID_JAN
            result.reason = why
            result.needs_review = True
            return result

        if self.local_library is not None:
            local_candidates = self.local_library.lookup(query)
            result.candidates.extend(local_candidates)
            keys = {_material_key(c) for c in local_candidates if c.material_status == MaterialStatus.FOUND}
            if local_candidates and len(keys) == 1 and not all_sites:
                self._aggregate(result)
                return result

        root = Path(snapshot_root)
        for policy in self.policies:
            if allowed_sites is not None and policy.site_id not in allowed_sites:
                continue
            adapter = self.adapters.get(policy.site_id)
            if adapter is None:
                continue
            try:
                evidence = self._parse_snapshot(adapter, query, root / policy.site_id)
            except Exception as exc:
                result.candidates.append(self._parse_error_evidence(policy, query, "", f"本地快照解析失败：{exc}"))
                result.attempts.append(SiteAttempt(
                    site_id=policy.site_id, site_name=policy.site_name,
                    status=AccessStatus.PARSE_ERROR, message=str(exc),
                ))
                continue
            if evidence is None:
                continue
            result.candidates.append(evidence)
            result.attempts.append(SiteAttempt(
                site_id=policy.site_id,
                site_name=policy.site_name,
                status=AccessStatus.OK,
                http_status=None,
                url=evidence.product_url,
                message="本地快照解析；未联网、未登录",
            ))
            if not all_sites and evidence.match_status == MatchStatus.EXACT and evidence.material_status == MaterialStatus.FOUND:
                break

        if not result.attempts and not result.candidates:
            result.status = OverallStatus.NOT_CHECKED
            result.match_status = MatchStatus.NOT_CHECKED
            result.material_status = MaterialStatus.NOT_CHECKED
            result.reason = "未找到本地快照；请在浏览器中人工保存商品页后放入 snapshots/<site>/<JAN>/"
            result.action = "manual_snapshot"
            result.needs_review = True
            return result

        self._aggregate(result)
        return result

    def _parse_snapshot(self, adapter: SiteAdapter, query: ProductQuery, site_dir: Path):
        if not site_dir.exists():
            return None
        sub = site_dir / query.jan
        if sub.is_dir():
            return self._parse_fixture_dir(adapter, query, sub)
        for name in (f"{query.jan}.html", f"{query.jan}.htm", f"{query.jan}.json"):
            p = site_dir / name
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
                return adapter.parse_detail(text, query, adapter.build_detail_url(query.jan))
        return None

    # ------------------------------------------------------------------
    # 站点执行
    # ------------------------------------------------------------------
    def _run_site(self, policy: SitePolicy, query: ProductQuery, all_sites: bool) -> tuple[Evidence | None, list[SiteAttempt]]:
        adapter = self.adapters.get(policy.site_id)
        if adapter is None:
            return None, [SiteAttempt(policy.site_id, policy.site_name, AccessStatus.PARSE_ERROR, message="未注册适配器")]

        attempts: list[SiteAttempt] = []
        if adapter.requires_search:
            search_url = adapter.build_search_url(query)
            search_out = self._fetch_with_retries(policy, search_url)
            attempts.append(SiteAttempt(
                policy.site_id, policy.site_name, search_out.status,
                search_out.http_status, search_url, search_out.message, False, search_out.elapsed_ms,
            ))
            if search_out.status != AccessStatus.OK:
                return self._access_failure_evidence(policy, query, search_url, search_out), attempts

            try:
                refs = adapter.parse_search(search_out.response.text, query)
            except Exception as exc:
                attempts.append(SiteAttempt(policy.site_id, policy.site_name, AccessStatus.PARSE_ERROR, search_out.http_status, search_url, f"搜索页解析失败：{exc}"))
                return self._parse_error_evidence(policy, query, search_url, f"搜索页解析失败：{exc}"), attempts
            if not refs:
                return make_not_found_evidence(adapter, query, search_url, "搜索页未找到商品链接"), attempts
            ref = self._choose_ref(refs, query)
            detail_url = ref.url
            detail_out = self._fetch_with_retries(policy, detail_url)
            attempts.append(SiteAttempt(
                policy.site_id, policy.site_name, detail_out.status,
                detail_out.http_status, detail_url, detail_out.message, False, detail_out.elapsed_ms,
            ))
            if detail_out.status != AccessStatus.OK:
                return self._access_failure_evidence(policy, query, detail_url, detail_out), attempts
            try:
                return adapter.parse_detail(detail_out.response.text, query, detail_url, ref), attempts
            except Exception as exc:
                return self._parse_error_evidence(policy, query, detail_url, f"详情页解析失败：{exc}"), attempts

        detail_url = adapter.build_detail_url(query.jan)
        out = self._fetch_with_retries(policy, detail_url)
        attempts.append(SiteAttempt(
            policy.site_id, policy.site_name, out.status,
            out.http_status, detail_url, out.message, False, out.elapsed_ms,
        ))
        if out.status != AccessStatus.OK:
            return self._access_failure_evidence(policy, query, detail_url, out), attempts
        # 404/410 作为“找不到商品”，不是网络错误
        if out.http_status in (404, 410):
            return make_not_found_evidence(adapter, query, detail_url, f"HTTP {out.http_status}：商品页不存在"), attempts
        try:
            return adapter.parse_detail(out.response.text, query, detail_url), attempts
        except Exception as exc:
            return self._parse_error_evidence(policy, query, detail_url, f"详情页解析失败：{exc}"), attempts

    def _choose_ref(self, refs: list[ProductRef], query: ProductQuery) -> ProductRef:
        exact = [r for r in refs if r.jan and normalize_jan(r.jan) == query.jan]
        if exact:
            return exact[0]
        if refs:
            return refs[0]
        raise ParseError("没有候选商品")

    def _fetch_with_retries(self, policy: SitePolicy, url: str) -> FetchOutcome:
        attempt = 0
        last_message = ""
        while True:
            self._throttle(policy)
            resp = self.transport.get(url)
            if resp is None:
                return FetchOutcome(AccessStatus.NETWORK_ERROR, message="传输层无响应")
            if resp.error and resp.status_code is None:
                return FetchOutcome(AccessStatus.NETWORK_ERROR, resp, resp.error, None, resp.elapsed_ms)
            status = resp.status_code or 0
            if status == 403:
                self.access.record_403(policy.site_id, url)
                return FetchOutcome(AccessStatus.BLOCKED_403, resp, "HTTP 403：已停止该站自动访问", status, resp.elapsed_ms)
            if status == 429:
                retry_after = _parse_retry_after(resp.header("Retry-After"))
                self.access.record_429(policy.site_id, retry_after, policy.max_retries, url)
                decision = self.access.check(policy)
                if attempt < policy.max_retries and decision.allowed:
                    self.sleeper(min(max(retry_after, 1.0), 120.0))
                    attempt += 1
                    last_message = f"HTTP 429：按 Retry-After 退避后重试（第 {attempt} 次）"
                    continue
                return FetchOutcome(AccessStatus.RATE_LIMITED, resp, last_message or "HTTP 429：限流，已停止重试", status, resp.elapsed_ms)
            if 200 <= status < 300:
                self.access.record_success(policy.site_id)
                return FetchOutcome(AccessStatus.OK, resp, "", status, resp.elapsed_ms)
            if status in (404, 410):
                return FetchOutcome(AccessStatus.OK, resp, f"HTTP {status}", status, resp.elapsed_ms)
            return FetchOutcome(AccessStatus.HTTP_ERROR, resp, f"HTTP {status}", status, resp.elapsed_ms)

    def _throttle(self, policy: SitePolicy) -> None:
        last = self._last_request.get(policy.site_id)
        now = self.clock()
        if last is not None:
            wait = policy.rate_limit_seconds - (now - last)
            if wait > 0:
                self.sleeper(wait)
        self._last_request[policy.site_id] = self.clock()

    # ------------------------------------------------------------------
    # 证据
    # ------------------------------------------------------------------
    def _cache_evidence(self, policy: SitePolicy, query: ProductQuery, evidence: Evidence) -> None:
        if not evidence.product_url:
            return
        ttl = policy.ttl_seconds
        if evidence.match_status != MatchStatus.EXACT:
            ttl = min(ttl, 86400)
        if evidence.material_status != MaterialStatus.FOUND:
            ttl = min(ttl, 3600)
        self.cache.put(policy.site_id, query.jan, evidence.product_url, evidence.to_dict(), ttl)

    def _access_failure_evidence(self, policy: SitePolicy, query: ProductQuery, url: str, out: FetchOutcome) -> Evidence:
        return Evidence(
            site_id=policy.site_id,
            site_name=policy.site_name,
            source_type="website",
            product_url=url,
            jan_on_page="",
            name_ja="",
            spec_text="",
            material_original="",
            material_zh="",
            match_status=MatchStatus.NOT_CHECKED,
            material_status=MaterialStatus.NOT_CHECKED,
            access_status=out.status,
            queried_at=now_iso(),
            fetched_at=now_iso(),
            content_hash="",
            source_excerpt="",
            needs_review=True,
            error_code={
                AccessStatus.BLOCKED_403: "access_denied",
                AccessStatus.RATE_LIMITED: "rate_limited",
                AccessStatus.NETWORK_ERROR: "network_error",
                AccessStatus.HTTP_ERROR: "http_error",
                AccessStatus.PARSE_ERROR: "parse_error",
            }.get(out.status, "access_error"),
            notes=out.message,
        )

    def _parse_error_evidence(self, policy: SitePolicy, query: ProductQuery, url: str, message: str) -> Evidence:
        return Evidence(
            site_id=policy.site_id,
            site_name=policy.site_name,
            source_type="website",
            product_url=url,
            jan_on_page="",
            name_ja="",
            spec_text="",
            material_original="",
            material_zh="",
            match_status=MatchStatus.NOT_CHECKED,
            material_status=MaterialStatus.NOT_CHECKED,
            access_status=AccessStatus.PARSE_ERROR,
            queried_at=now_iso(),
            fetched_at=now_iso(),
            content_hash="",
            source_excerpt="",
            needs_review=True,
            error_code="parse_error",
            notes=message,
        )

    # ------------------------------------------------------------------
    # 离线夹具
    # ------------------------------------------------------------------
    def _parse_fixture_dir(self, adapter: SiteAdapter, query: ProductQuery, site_dir: Path) -> Evidence | None:
        def read(name: str) -> str | None:
            p = site_dir / name
            if p.exists():
                return p.read_text(encoding="utf-8", errors="replace")
            return None

        detail = read("detail.html") or read("detail.json")
        search = read("search.html") or read("search.json")
        if adapter.requires_search and search:
            refs = adapter.parse_search(search, query)
            if not refs:
                return make_not_found_evidence(adapter, query, adapter.build_search_url(query), "离线搜索样本未找到商品链接")
            ref = self._choose_ref(refs, query)
            if detail:
                return adapter.parse_detail(detail, query, ref.url, ref)
            return make_not_found_evidence(adapter, query, ref.url, "离线样本缺少详情页")
        if detail:
            url = adapter.build_detail_url(query.jan)
            return adapter.parse_detail(detail, query, url)
        return None

    # ------------------------------------------------------------------
    # 聚合
    # ------------------------------------------------------------------
    def _aggregate(self, result: QueryResult) -> None:
        found = [
            c for c in result.candidates
            if c.material_status == MaterialStatus.FOUND
            and c.match_status in (MatchStatus.EXACT, MatchStatus.JAN_ONLY)
            and (c.material_zh or c.material_original)
        ]
        keys: list[str] = []
        for c in found:
            k = _material_key(c)
            if k and k not in keys:
                keys.append(k)

        if len(keys) > 1:
            result.status = OverallStatus.CONFLICT
            result.match_status = MatchStatus.MULTIPLE
            result.material_status = MaterialStatus.FOUND
            result.recommended = None
            result.needs_review = True
            result.reason = "不同来源给出不同材质，保留冲突，需人工核对：" + " / ".join(
                unique_keep_order([f"{c.site_name}:{c.material_zh or c.material_original}" for c in found])
            )
            result.action = "manual_review"
            return

        if found:
            # 选最可靠的一条：EXACT 优先，其次来源优先级（本地优先）
            def score(c: Evidence):
                match_rank = {
                    MatchStatus.EXACT: 0,
                    MatchStatus.JAN_ONLY: 1,
                    MatchStatus.VERSION_MISMATCH: 2,
                    MatchStatus.NAME_MISMATCH: 3,
                    MatchStatus.JAN_MISMATCH: 4,
                }.get(c.match_status, 9)
                source_rank = 0 if c.site_id == "local_library" else 1
                return (match_rank, source_rank, -c.confidence)

            best = sorted(found, key=score)[0]
            result.recommended = best
            result.match_status = best.match_status
            result.material_status = MaterialStatus.FOUND
            result.needs_review = True
            if best.match_status == MatchStatus.EXACT:
                result.status = OverallStatus.CANDIDATE_READY
                result.reason = f"找到唯一材质候选，来源：{best.site_name}；仍需人工核对后采用"
                result.action = "candidate_review"
            else:
                result.status = OverallStatus.NEEDS_REVIEW
                result.reason = f"找到材质，但商品身份未完全确认（{best.match_status.value}），需人工核对"
                result.action = "manual_review"
            return

        # 没有可用的材质候选
        statuses = {a.status for a in result.attempts}
        candidate_matches = {c.match_status for c in result.candidates}
        has_blocked = AccessStatus.BLOCKED_403 in statuses
        has_rate = AccessStatus.RATE_LIMITED in statuses
        has_network = AccessStatus.NETWORK_ERROR in statuses
        has_http = AccessStatus.HTTP_ERROR in statuses
        has_parse = AccessStatus.PARSE_ERROR in statuses
        has_no_material = any(c.material_status in (MaterialStatus.NO_MATERIAL, MaterialStatus.SIZE_ONLY, MaterialStatus.EXTRACT_FAILED) for c in result.candidates)
        has_identity_mismatch = any(c.match_status in (
            MatchStatus.VERSION_MISMATCH, MatchStatus.NAME_MISMATCH, MatchStatus.JAN_MISMATCH
        ) and c.material_status == MaterialStatus.FOUND for c in result.candidates)
        has_not_found = MatchStatus.NOT_FOUND in candidate_matches
        has_unauth = AccessStatus.NOT_AUTHORIZED in statuses
        has_skipped = AccessStatus.SKIPPED in statuses

        result.material_status = MaterialStatus.NO_MATERIAL if has_no_material else MaterialStatus.NOT_CHECKED
        if has_blocked or has_rate or has_network or has_http or has_parse:
            result.status = OverallStatus.ERROR
            result.match_status = MatchStatus.NOT_CHECKED
            result.reason = "查询未完成：存在访问受限、网络或解析错误，不能当作“无材质”"
            result.action = "manual_review"
        elif has_identity_mismatch:
            result.status = OverallStatus.NEEDS_REVIEW
            result.match_status = MatchStatus.NOT_CHECKED
            result.material_status = MaterialStatus.NOT_CHECKED
            result.reason = "找到材质字段，但 JAN/名称/版本不一致，不能采用；需人工核对"
            result.action = "manual_review"
        elif has_unauth:
            details = []
            if has_no_material:
                details.append("已查询站点无材质")
            if has_not_found:
                details.append("已查询站点未找到商品")
            result.status = OverallStatus.NOT_AUTHORIZED
            result.match_status = MatchStatus.NOT_CHECKED
            result.material_status = MaterialStatus.NOT_CHECKED
            result.reason = "仍有站点尚未取得授权，未发出网络请求；不能据此判定“无材质”或“商品不存在”"
            if details:
                result.reason += "（" + "；".join(details) + "）"
            result.action = "wait_authorization"
        elif has_no_material:
            result.status = OverallStatus.NO_MATERIAL
            result.match_status = MatchStatus.NOT_CHECKED
            result.reason = "已查询的页面没有材质字段（不等同于商品不存在）"
            result.action = "manual_review"
        elif has_not_found:
            result.status = OverallStatus.NOT_FOUND
            result.match_status = MatchStatus.NOT_FOUND
            result.reason = "已查询来源未找到商品"
            result.action = "manual_review"
        elif has_skipped:
            result.status = OverallStatus.NOT_CHECKED
            result.match_status = MatchStatus.NOT_CHECKED
            result.reason = "在线查询开关未开启"
            result.action = "wait_online"
        else:
            result.status = OverallStatus.NOT_CHECKED
            result.match_status = MatchStatus.NOT_CHECKED
            result.reason = "没有可用查询来源"
            result.action = "manual_review"
        result.needs_review = True
