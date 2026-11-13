# -*- coding: utf-8 -*-
"""统一的数据模型：查询、证据、站点策略、批量结果。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class MatchStatus(str, Enum):
    EXACT = "exact"                       # JAN 一致，名称/版本/规格可核对
    JAN_ONLY = "jan_only"                 # JAN 一致，但缺少名称/版本核对信息
    VERSION_MISMATCH = "version_mismatch" # JAN 一致但版本/规格冲突
    NAME_MISMATCH = "name_mismatch"       # JAN 一致但名称差异过大
    JAN_MISMATCH = "jan_mismatch"         # 页面 JAN 与查询 JAN 不一致
    MULTIPLE = "multiple_candidates"      # 同站多个候选
    NOT_FOUND = "not_found"
    INVALID_JAN = "invalid_jan"
    NOT_CHECKED = "not_checked"


class MaterialStatus(str, Enum):
    FOUND = "found"
    NO_MATERIAL = "no_material"
    SIZE_ONLY = "size_only"
    EXTRACT_FAILED = "extract_failed"
    NOT_CHECKED = "not_checked"


class AccessStatus(str, Enum):
    OK = "ok"
    CACHED = "cached"
    NOT_AUTHORIZED = "not_authorized"
    SITE_DISABLED = "site_disabled"
    BLOCKED_403 = "blocked_403"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    HTTP_ERROR = "http_error"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"


class OverallStatus(str, Enum):
    CANDIDATE_READY = "candidate_ready"
    NEEDS_REVIEW = "needs_review"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    NO_MATERIAL = "no_material"
    NOT_AUTHORIZED = "not_authorized"
    ERROR = "error"
    INVALID_INPUT = "invalid_input"
    EXISTING_MATERIAL = "existing_material"
    NOT_CHECKED = "not_checked"


@dataclass
class SitePolicy:
    site_id: str
    site_name: str
    base_url: str
    priority: int = 100
    enabled: bool = True
    authorized: bool = False
    authorization_note: str = ""
    allowed_purpose: str = ""
    rate_limit_seconds: float = 5.0
    max_retries: int = 2
    ttl_seconds: int = 7 * 24 * 3600
    source_type: str = "website"

    @property
    def live_ready(self) -> bool:
        """只有同时启用并获得授权，才允许真实联网。"""
        return bool(self.enabled and self.authorized)


@dataclass
class ProductQuery:
    jan: str
    name_zh: str = ""
    name_ja: str = ""
    spec: str = ""
    description_ja: str = ""
    brand: str = ""
    source_row: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def compare_name(self) -> str:
        return self.name_ja or self.description_ja or ""


@dataclass
class ProductRef:
    site_id: str
    url: str
    jan: str = ""
    gcode: str = ""
    name_ja: str = ""
    spec: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MaterialExtraction:
    original: str = ""
    label: str = ""
    method: str = ""
    found: bool = False
    size_text: str = ""
    alternatives: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    excerpt: str = ""


@dataclass
class TranslationResult:
    zh: str = ""
    unknown_terms: list[str] = field(default_factory=list)
    method: str = ""


@dataclass
class Evidence:
    site_id: str
    site_name: str
    source_type: str = "website"
    product_url: str = ""
    jan_on_page: str = ""
    name_ja: str = ""
    spec_text: str = ""
    size_text: str = ""
    material_original: str = ""
    material_zh: str = ""
    material_unknown_terms: list[str] = field(default_factory=list)
    match_status: MatchStatus = MatchStatus.NOT_CHECKED
    material_status: MaterialStatus = MaterialStatus.NOT_CHECKED
    access_status: AccessStatus = AccessStatus.OK
    queried_at: str = ""
    fetched_at: str = ""
    from_cache: bool = False
    content_hash: str = ""
    source_excerpt: str = ""
    needs_review: bool = True
    error_code: str = ""
    notes: str = ""
    confidence: float = 0.0
    input_material: str = ""

    @property
    def evidence_id(self) -> str:
        import hashlib
        raw = "|".join([
            self.site_id, self.jan_on_page, self.product_url,
            self.material_original, self.material_zh,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key, value in list(d.items()):
            if isinstance(value, Enum):
                d[key] = value.value
        d["evidence_id"] = self.evidence_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        data = dict(data)
        data.pop("evidence_id", None)
        for key in ("match_status", "material_status", "access_status"):
            if key in data and data[key] is not None:
                try:
                    data[key] = {
                        "match_status": MatchStatus,
                        "material_status": MaterialStatus,
                        "access_status": AccessStatus,
                    }[key](data[key])
                except ValueError:
                    pass
        allowed = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class SiteAttempt:
    site_id: str
    site_name: str
    status: AccessStatus = AccessStatus.SKIPPED
    http_status: Optional[int] = None
    url: str = ""
    message: str = ""
    cached: bool = False
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, Enum) else self.status
        return d


@dataclass
class QueryResult:
    query: ProductQuery
    candidates: list[Evidence] = field(default_factory=list)
    attempts: list[SiteAttempt] = field(default_factory=list)
    status: OverallStatus = OverallStatus.NOT_CHECKED
    match_status: MatchStatus = MatchStatus.NOT_CHECKED
    material_status: MaterialStatus = MaterialStatus.NOT_CHECKED
    recommended: Optional[Evidence] = None
    needs_review: bool = True
    reason: str = ""
    queried_at: str = ""
    cache_hit: bool = False
    input_material: str = ""
    action: str = ""
    input_rows: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": asdict(self.query),
            "candidates": [c.to_dict() for c in self.candidates],
            "attempts": [a.to_dict() for a in self.attempts],
            "status": self.status.value,
            "match_status": self.match_status.value,
            "material_status": self.material_status.value,
            "recommended": self.recommended.to_dict() if self.recommended else None,
            "needs_review": self.needs_review,
            "reason": self.reason,
            "queried_at": self.queried_at,
            "cache_hit": self.cache_hit,
            "input_material": self.input_material,
            "action": self.action,
            "input_rows": self.input_rows,
        }
