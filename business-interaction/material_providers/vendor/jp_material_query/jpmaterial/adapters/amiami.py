# -*- coding: utf-8 -*-
"""AmiAmi 适配器。

历史技术记录：
- 搜索：https://api.amiami.com/api/v1.0/items?s_keywords=<JAN>&pagecnt=1&pagemax=30&lang=eng
- 详情：https://api.amiami.com/api/v1.0/item?gcode=<gcode>&lang=ja

注意：历史 API 记录不是当前已取得授权的公开 API 合同。未授权时本适配器只做离线解析。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ..identity import compare_identity
from ..material import extract_material
from ..models import AccessStatus, Evidence, MaterialStatus, ProductQuery, ProductRef
from ..textutil import html_to_text, now_iso, sha256_text, truncate
from ..translate import translate_material
from .base import ParseError, SiteAdapter, make_not_found_evidence


def _iter_dicts(obj: Any) -> Iterable[dict]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def _first(d: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = d.get(key)
        if value not in (None, "", []):
            if isinstance(value, (list, tuple)):
                return " / ".join(str(x) for x in value)
            return str(value)
    return ""


def spec_to_text(spec: Any) -> str:
    if spec is None:
        return ""
    if isinstance(spec, str):
        return spec
    if isinstance(spec, (list, tuple)):
        return "\n".join(spec_to_text(x) for x in spec if x not in (None, ""))
    if isinstance(spec, dict):
        return "\n".join(f"{k}: {spec_to_text(v)}" for k, v in spec.items() if v not in (None, ""))
    return str(spec)


def load_json(payload: Any) -> Any:
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if not isinstance(payload, str):
        raise ParseError("AmiAmi 适配器需要 JSON 或 HTML 文本")
    text = payload.lstrip()
    if not text.startswith(("{", "[")):
        raise ParseError("不是 JSON")
    return json.loads(text)


class AmiAmiAdapter(SiteAdapter):
    site_id = "amiami"
    site_name = "AmiAmi"
    requires_search = True
    search_url_template = (
        "https://api.amiami.com/api/v1.0/items?s_keywords={jan}&pagecnt=1&pagemax=30&lang=eng"
    )
    detail_url_template = "https://api.amiami.com/api/v1.0/item?gcode={value}&lang=ja"

    def parse_search(self, payload: Any, query: ProductQuery) -> list[ProductRef]:
        try:
            data = load_json(payload)
        except Exception:
            return super().parse_search(payload, query)

        refs: list[ProductRef] = []
        seen: set[str] = set()
        for d in _iter_dicts(data):
            gcode = _first(d, ("gcode", "g_code", "code"))
            jan = _first(d, ("jancode", "jan", "JAN", "jan_code"))
            if not gcode and not jan:
                continue
            name = _first(d, ("name", "itemname", "item_name", "title"))
            spec = _first(d, ("spec", "specification", "specs"))
            if not gcode:
                continue
            if gcode in seen:
                continue
            seen.add(gcode)
            refs.append(ProductRef(
                site_id=self.site_id,
                url=self.build_detail_url(gcode),
                jan=jan,
                gcode=gcode,
                name_ja=name,
                spec=spec,
                extra={"raw": d},
            ))
        return refs

    def parse_detail(self, payload: Any, query: ProductQuery, url: str = "", ref: ProductRef | None = None) -> Evidence:
        try:
            data = load_json(payload)
        except Exception:
            return super().parse_detail(payload, query, url, ref)

        candidates: list[dict] = []
        for d in _iter_dicts(data):
            spec = d.get("spec") or d.get("specification") or d.get("specs")
            gcode = _first(d, ("gcode", "g_code", "code"))
            jan = _first(d, ("jancode", "jan", "JAN", "jan_code"))
            if spec is not None or gcode or jan:
                candidates.append(d)
        if not candidates:
            return make_not_found_evidence(self, query, url or self.build_detail_url(ref.gcode if ref else ""), "AmiAmi 响应中没有商品对象")

        chosen: dict | None = None
        for d in candidates:
            jan = _first(d, ("jancode", "jan", "JAN", "jan_code"))
            if jan and jan == query.jan:
                chosen = d
                break
        if chosen is None:
            # 详情接口通常返回单个 item；搜索响应则取第一个有 gcode 的对象
            chosen = next((d for d in candidates if _first(d, ("gcode", "g_code", "code"))), candidates[0])

        gcode = _first(chosen, ("gcode", "g_code", "code")) or (ref.gcode if ref else "")
        jan = _first(chosen, ("jancode", "jan", "JAN", "jan_code"))
        name = _first(chosen, ("name", "itemname", "item_name", "title"))
        spec_text = spec_to_text(chosen.get("spec") or chosen.get("specification") or chosen.get("specs"))
        extraction = extract_material(spec_text)
        translation = translate_material(extraction.original, self.glossary) if extraction.found else None
        match = compare_identity(query.jan, query.compare_name, query.spec, jan, name, spec_text)
        error_code = ""
        if match.status.value in ("jan_only", "version_mismatch", "name_mismatch", "jan_mismatch"):
            error_code = {
                "jan_only": "identity_uncertain",
                "version_mismatch": "version_mismatch",
                "name_mismatch": "name_mismatch",
                "jan_mismatch": "jan_mismatch",
            }[match.status.value]
        elif not extraction.found:
            error_code = "no_material"
        notes = list(extraction.notes)
        notes.extend(match.reasons)
        if translation and translation.unknown_terms:
            notes.append("未翻译词保留原文：" + "、".join(translation.unknown_terms))
        product_url = url or (self.build_detail_url(gcode) if gcode else (ref.url if ref else ""))
        content_basis = "|".join([name, spec_text, extraction.original, jan])
        return Evidence(
            site_id=self.site_id,
            site_name=self.site_name,
            source_type="website",
            product_url=product_url,
            jan_on_page=jan,
            name_ja=name,
            spec_text=spec_text,
            size_text=extraction.size_text,
            material_original=extraction.original,
            material_zh=translation.zh if translation else "",
            material_unknown_terms=translation.unknown_terms if translation else [],
            match_status=match.status,
            material_status=MaterialStatus.FOUND if extraction.found else MaterialStatus.NO_MATERIAL,
            access_status=AccessStatus.OK,
            queried_at=now_iso(),
            fetched_at=now_iso(),
            from_cache=False,
            content_hash=sha256_text(content_basis),
            source_excerpt=extraction.excerpt or truncate(spec_text, 300),
            needs_review=True,
            error_code=error_code,
            notes="；".join(x for x in notes if x),
            confidence=match.name_score or 0.0,
        )
