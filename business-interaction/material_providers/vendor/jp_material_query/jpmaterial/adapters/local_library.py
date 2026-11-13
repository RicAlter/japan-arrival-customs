# -*- coding: utf-8 -*-
"""本地商品资料库候选查询（只读）。

输入格式（JSON）：
{
  "records": [
    {"jan": "457...", "material_zh": "纸", "material_original": "紙",
     "name_ja": "...", "source": "历史报单汇总", "source_url": "...",
     "updated_at": "2026-01-01", "record_id": "..."}
  ]
}
也支持 { "<JAN>": [ {...}, ... ] } 的映射格式。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..jan import normalize_jan
from ..models import AccessStatus, Evidence, MatchStatus, MaterialStatus, ProductQuery
from ..textutil import now_iso, sha256_text, unique_keep_order
from ..translate import translate_material


class LocalLibrary:
    site_id = "local_library"
    site_name = "本地商品资料库"
    source_type = "local_business_record"

    def __init__(self, records: dict[str, list[dict]] | None = None, glossary: dict[str, str] | None = None):
        self.records = records or {}
        self.glossary = glossary or {}

    @classmethod
    def load(cls, path: str | Path | None, glossary: dict[str, str] | None = None) -> "LocalLibrary":
        if not path:
            return cls({}, glossary)
        p = Path(path)
        if not p.exists():
            return cls({}, glossary)
        data = json.loads(p.read_text(encoding="utf-8"))
        records: dict[str, list[dict]] = {}
        if isinstance(data, dict) and "records" in data:
            for rec in data.get("records", []):
                jan = normalize_jan(rec.get("jan"))
                if jan:
                    records.setdefault(jan, []).append(rec)
        elif isinstance(data, dict):
            for jan, recs in data.items():
                key = normalize_jan(jan)
                if not key:
                    continue
                if isinstance(recs, dict):
                    recs = [recs]
                for rec in recs:
                    if isinstance(rec, dict):
                        item = dict(rec)
                        item.setdefault("jan", key)
                        records.setdefault(key, []).append(item)
        elif isinstance(data, list):
            for rec in data:
                if isinstance(rec, dict):
                    jan = normalize_jan(rec.get("jan"))
                    if jan:
                        records.setdefault(jan, []).append(rec)
        return cls(records, glossary)

    def lookup(self, query: ProductQuery) -> list[Evidence]:
        jan = normalize_jan(query.jan)
        records = self.records.get(jan, [])
        out: list[Evidence] = []
        for rec in records:
            material_zh = str(rec.get("material_zh") or rec.get("material") or "").strip()
            material_original = str(rec.get("material_original") or "").strip()
            if not material_zh and material_original:
                material_zh = translate_material(material_original, self.glossary).zh
            if not material_zh:
                continue
            source = str(rec.get("source") or "本地商品资料库")
            source_url = str(rec.get("source_url") or "")
            notes = ["本地业务记录，仅供候选参考；不代表最终申报材质"]
            if not material_original:
                notes.append("本地记录仅有中文材质，无日文原文")
            out.append(Evidence(
                site_id=self.site_id,
                site_name=self.site_name,
                source_type=self.source_type,
                product_url=source_url,
                jan_on_page=jan,
                name_ja=str(rec.get("name_ja") or query.compare_name or ""),
                spec_text=str(rec.get("spec") or query.spec or ""),
                material_original=material_original,
                material_zh=material_zh,
                material_unknown_terms=[],
                match_status=MatchStatus.EXACT,
                material_status=MaterialStatus.FOUND,
                access_status=AccessStatus.OK,
                queried_at=now_iso(),
                fetched_at=str(rec.get("updated_at") or ""),
                from_cache=False,
                content_hash=sha256_text(jan + "|" + material_zh + "|" + source),
                source_excerpt=(material_original or material_zh)[:300],
                needs_review=True,
                error_code="",
                notes="；".join(unique_keep_order(notes)),
                confidence=1.0,
            ))
        return out
