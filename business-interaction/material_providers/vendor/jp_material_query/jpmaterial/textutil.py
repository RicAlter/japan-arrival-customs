# -*- coding: utf-8 -*-
"""文本/HTML 工具。"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Iterable

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "dl", "dt", "dd",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "thead", "tfoot", "tr", "ul",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in _BLOCK_TAGS or tag == "br":
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.lower() == "br" and not self._skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data:
            self.parts.append(data)


def looks_like_html(text: str) -> bool:
    if not text:
        return False
    sample = text[:2000].lower()
    return ("<html" in sample or "<div" in sample or "<table" in sample
            or "<tr" in sample or "<td" in sample or "<span" in sample)


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    parser = _Extractor()
    try:
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    return normalize_text(text)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\u00a0", " ").strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def truncate(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def meta_content(html_text: str, key: str) -> str:
    pattern = re.compile(
        r'<meta[^>]+(?:property|name)\s*=\s*["\']' + re.escape(key) + r'["\'][^>]*content\s*=\s*["\']([^"\']*)',
        re.I,
    )
    m = pattern.search(html_text)
    if m:
        return html.unescape(m.group(1)).strip()
    pattern2 = re.compile(
        r'<meta[^>]+content\s*=\s*["\']([^"\']*)["\'][^>]*(?:property|name)\s*=\s*["\']' + re.escape(key) + r'["\']',
        re.I,
    )
    m = pattern2.search(html_text)
    return html.unescape(m.group(1)).strip() if m else ""
