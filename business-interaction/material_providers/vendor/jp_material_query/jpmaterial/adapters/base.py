# -*- coding: utf-8 -*-
"""适配器基类：统一输入/输出、页面元信息、材质与身份核对。"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from ..identity import IdentityComparison, compare_identity
from ..jan import normalize_jan
from ..material import extract_material, material_status_from_extraction
from ..models import (
    AccessStatus,
    Evidence,
    MatchStatus,
    MaterialStatus,
    ProductQuery,
    ProductRef,
    SitePolicy,
)
from ..textutil import (
    html_to_text,
    looks_like_html,
    meta_content,
    now_iso,
    sha256_text,
    truncate,
    unique_keep_order,
)
from ..translate import translate_material


class ParseError(RuntimeError):
    pass


_NOT_FOUND_PATTERNS = [
    "商品が見つかりません", "商品が見つかりませんでした", "ページが見つかりません",
    "お探しの商品は見つかりません", "該当する商品はありません", "not found",
    "404 not found", "ページが存在しません",
]
_SIZE_ONLY_PATTERNS = ["サイズ", "商品サイズ", "本体サイズ"]


def detect_page_jan(text: str, url: str, query_jan: str = "") -> str:
    q = normalize_jan(query_jan)
    # 1) 标签后的 JAN
    for m in re.finditer(r"(?:JAN(?:コード)?|JANCode|jan_code)\s*[:：]?\s*(?:\|\s*)*(\d{13})", text, re.I):
        return m.group(1)
    # 2) URL 中的 13 位
    for m in re.finditer(r"(?<!\d)(\d{13})(?!\d)", url or ""):
        return m.group(1)
    # 3) 查询 JAN 出现在页面中
    if q and q in text:
        return q
    # 4) 页面里第一个 13 位
    m = re.search(r"(?<!\d)(\d{13})(?!\d)", text)
    return m.group(1) if m else ""


def detect_page_name(html: str, text: str) -> str:
    for key in ("og:title", "twitter:title"):
        value = meta_content(html, key)
        if value:
            return value.strip()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if m:
        name = html_to_text(m.group(1)).strip()
        if name:
            return name
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        return html_to_text(m.group(1)).strip()
    return ""


def detect_spec_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        if re.match(r"^商品仕様\s*$", line):
            return " / ".join(x for x in lines[i + 1:i + 12] if x)[:800]
    return ""


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "a":
            self._href = ""
            self._text = []
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self._href = value

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = ""
            self._text = []


class SiteAdapter:
    site_id = ""
    site_name = ""
    requires_search = False
    detail_url_template = ""
    search_url_template = ""

    def __init__(self, policy: SitePolicy, glossary: dict[str, str] | None = None):
        self.policy = policy
        self.glossary = glossary or {}

    # ---------- URL ----------
    def build_detail_url(self, jan_or_gcode: str) -> str:
        return self.detail_url_template.format(value=jan_or_gcode)

    def build_search_url(self, query: ProductQuery) -> str:
        return self.search_url_template.format(jan=query.jan, query=query.jan)

    # ---------- 统一证据 ----------
    def make_evidence(
        self,
        *,
        query: ProductQuery,
        url: str,
        name_ja: str,
        jan_on_page: str,
        spec_text: str,
        extraction,
        access_status: AccessStatus = AccessStatus.OK,
        match: IdentityComparison | None = None,
        extra_notes: list[str] | None = None,
    ) -> Evidence:
        comparison = match or compare_identity(
            query.jan, query.compare_name, query.spec, jan_on_page, name_ja, spec_text
        )
        translation = translate_material(extraction.original, self.glossary) if extraction.found else None
        material_status = material_status_from_extraction(extraction)
        notes: list[str] = []
        notes.extend(extraction.notes)
        notes.extend(comparison.reasons)
        if extra_notes:
            notes.extend(extra_notes)
        if material_status == MaterialStatus.SIZE_ONLY:
            notes.append("只找到尺寸字段，未把尺寸当作材质")
        if material_status == MaterialStatus.NO_MATERIAL:
            notes.append("页面未提供素材字段")
        if translation and translation.unknown_terms:
            notes.append("未翻译词保留原文：" + "、".join(translation.unknown_terms))

        error_code = ""
        if comparison.status == MatchStatus.NOT_FOUND:
            error_code = "not_found"
        elif comparison.status == MatchStatus.VERSION_MISMATCH:
            error_code = "version_mismatch"
        elif comparison.status == MatchStatus.NAME_MISMATCH:
            error_code = "name_mismatch"
        elif comparison.status == MatchStatus.JAN_MISMATCH:
            error_code = "jan_mismatch"
        elif comparison.status == MatchStatus.JAN_ONLY:
            error_code = "identity_uncertain"
        elif material_status == MaterialStatus.NO_MATERIAL:
            error_code = "no_material"
        elif material_status == MaterialStatus.SIZE_ONLY:
            error_code = "size_only"
        elif material_status == MaterialStatus.EXTRACT_FAILED:
            error_code = "extract_failed"

        content_basis = "|".join([name_ja or "", spec_text or "", extraction.original or "", jan_on_page or ""])
        return Evidence(
            site_id=self.site_id,
            site_name=self.site_name,
            source_type="website",
            product_url=url,
            jan_on_page=normalize_jan(jan_on_page),
            name_ja=name_ja or "",
            spec_text=spec_text or "",
            size_text=extraction.size_text or "",
            material_original=extraction.original if extraction.found else "",
            material_zh=translation.zh if translation else "",
            material_unknown_terms=translation.unknown_terms if translation else [],
            match_status=comparison.status,
            material_status=material_status,
            access_status=access_status,
            queried_at=now_iso(),
            fetched_at=now_iso(),
            from_cache=False,
            content_hash=sha256_text(content_basis),
            source_excerpt=extraction.excerpt,
            needs_review=True,
            error_code=error_code,
            notes="；".join(unique_keep_order(notes)),
            confidence=comparison.name_score or 0.0,
        )

    # ---------- 解析 ----------
    def parse_html(self, html: str, query: ProductQuery, url: str = "") -> Evidence:
        if not html or not html.strip():
            raise ParseError("页面内容为空")
        text = html_to_text(html)
        if not text:
            raise ParseError("页面无法转换为文本")
        not_found = any(p in text.lower() for p in _NOT_FOUND_PATTERNS)
        # 先不看 URL 中的 JAN（URL 可能是插件按查询 JAN 拼出来的），
        # 避免把“页面提示不存在”误判为 JAN 已核对。
        page_jan_text = detect_page_jan(text, "", "")
        if not_found and not page_jan_text:
            return make_not_found_evidence(self, query, url or self.build_detail_url(query.jan), "页面提示商品不存在")

        jan = detect_page_jan(text, url, query.jan)
        name = detect_page_name(html, text)
        if not jan and not name and not text.strip():
            return make_not_found_evidence(self, query, url, "页面没有商品信息")

        extraction = extract_material(html)
        spec_text = detect_spec_text(text)
        return self.make_evidence(
            query=query,
            url=url or self.build_detail_url(query.jan),
            name_ja=name,
            jan_on_page=jan,
            spec_text=spec_text,
            extraction=extraction,
        )

    def parse_search(self, payload: str, query: ProductQuery) -> list[ProductRef]:
        if not payload:
            return []
        parser = _LinkParser()
        try:
            parser.feed(payload)
        except Exception:
            return []
        refs: list[ProductRef] = []
        seen: set[str] = set()
        for href, text in parser.links:
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            absolute = urljoin(self.policy.base_url, href)
            low = absolute.lower()
            if not any(token in low for token in ("/product", "/item", "/shop/g/g", "/products/detail")):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            jan = ""
            m = re.search(r"(?<!\d)(\d{13})(?!\d)", absolute)
            if m:
                jan = m.group(1)
            refs.append(ProductRef(site_id=self.site_id, url=absolute, jan=jan, name_ja=text))
        return refs

    def parse_detail(self, payload: Any, query: ProductQuery, url: str = "", ref: ProductRef | None = None) -> Evidence:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        if not isinstance(payload, str):
            raise ParseError("该适配器需要 HTML 文本")
        return self.parse_html(payload, query, url or (ref.url if ref else ""))


def make_not_found_evidence(
    adapter: SiteAdapter,
    query: ProductQuery,
    url: str,
    reason: str,
) -> Evidence:
    return Evidence(
        site_id=adapter.site_id,
        site_name=adapter.site_name,
        source_type="website",
        product_url=url,
        jan_on_page="",
        name_ja="",
        spec_text="",
        material_original="",
        material_zh="",
        match_status=MatchStatus.NOT_FOUND,
        material_status=MaterialStatus.NOT_CHECKED,
        access_status=AccessStatus.OK,
        queried_at=now_iso(),
        fetched_at=now_iso(),
        content_hash=sha256_text(url + reason),
        source_excerpt="",
        needs_review=True,
        error_code="not_found",
        notes=reason,
    )


def strip_site_suffix(name: str) -> str:
    # 仅用于降低标题后缀对相似度的影响，不改写证据原文
    if "|" in name:
        return name.split("|", 1)[0].strip()
    if " - " in name and len(name) > 30:
        return name.split(" - ", 1)[0].strip()
    return name
