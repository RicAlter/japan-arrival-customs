# -*- coding: utf-8 -*-
"""JAN + 日文商品名 + 版本/规格的身份核对。

规则：
- JAN 必须一致；仅名称相似不能认定同一商品。
- JAN 一致但版本不同，不能自动采用。
- 同 JAN 多候选保留冲突。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .jan import normalize_jan, validate_jan
from .models import MatchStatus

_EDITION_WORDS = [
    "通常版", "限定版", "初回版", "初回限定版", "再販", "復刻", "通常", "限定", "初回",
    "limited", "regular", "reissue", "exclusive",
]
_VERSION_PATTERNS: list[tuple[str, str]] = [
    (r"vol(?:ume)?\.?\s*\d+", "volume"),
    (r"第\s*\d+\s*(?:弾|期|部|話|章|陣)", "edition"),
    (r"ver(?:sion)?\.?\s*[a-z0-9]{1,12}", "version"),
    (r"(?:" + "|".join(re.escape(w) for w in _EDITION_WORDS) + r")", "edition"),
    (r"全\s*\d+\s*種", "count"),
    (r"単位\s*/?\s*box|\bbox\b", "box"),
    (r"\d+\s*(?:枚|個|種|セット)", "count"),
]
_VERSION_RE = [(re.compile(p, re.I), kind) for p, kind in _VERSION_PATTERNS]
_CN_SPEC_ALIASES = {"整盒": "box", "整箱": "box", "套装": "set", "套组": "set", "單品": "single", "单品": "single"}


@dataclass
class IdentityComparison:
    status: MatchStatus
    name_score: float | None = None
    version_conflicts: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.status != MatchStatus.EXACT


def _normalize_name(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[\[\]【】()（）<>《》「」『』'\"!@#$%^&*_+=|\\/?.,，。:：;；·・\-—–~]", "", text)
    return text


def name_similarity(a: str, b: str) -> float | None:
    a_norm, b_norm = _normalize_name(a), _normalize_name(b)
    if not a_norm or not b_norm:
        return None
    if a_norm == b_norm:
        return 1.0
    if a_norm in b_norm or b_norm in a_norm:
        return 0.9
    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()
    tokens_a = set(re.findall(r"[a-z0-9]+|[一-龥ぁ-んァ-ヶー]{2,}", a_norm))
    tokens_b = set(re.findall(r"[a-z0-9]+|[一-龥ぁ-んァ-ヶー]{2,}", b_norm))
    if tokens_a and tokens_b:
        jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        ratio = max(ratio, jaccard)
    return round(ratio, 4)


def version_tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text or "").lower()
    tokens: set[str] = set()
    for pattern, _kind in _VERSION_RE:
        for m in pattern.finditer(text):
            tokens.add(re.sub(r"\s+", "", m.group(0).lower()))
    for cn, alias in _CN_SPEC_ALIASES.items():
        if cn in text:
            tokens.add(alias)
    return tokens


def compare_identity(
    query_jan: str,
    query_name: str,
    query_spec: str,
    candidate_jan: str,
    candidate_name: str,
    candidate_spec: str = "",
) -> IdentityComparison:
    q_jan = normalize_jan(query_jan)
    c_jan = normalize_jan(candidate_jan)
    if not q_jan:
        return IdentityComparison(MatchStatus.INVALID_JAN, reasons=["查询 JAN 为空"])
    ok, why = validate_jan(q_jan)
    if not ok:
        return IdentityComparison(MatchStatus.INVALID_JAN, reasons=[why])
    if c_jan and c_jan != q_jan:
        return IdentityComparison(MatchStatus.JAN_MISMATCH, reasons=[f"页面 JAN {c_jan} 与查询 JAN {q_jan} 不一致"])
    if not c_jan:
        q_name = query_name or ""
        c_name = candidate_name or ""
        score = name_similarity(q_name, c_name) if (q_name and c_name) else None
        if score is not None:
            return IdentityComparison(
                MatchStatus.JAN_ONLY, name_score=score,
                reasons=[f"页面未提供可核对的 JAN；日文名相似度 {score:.2f}"],
            )
        return IdentityComparison(MatchStatus.JAN_ONLY, reasons=["页面未提供可核对的 JAN"])

    q_name = query_name or ""
    c_name = candidate_name or ""
    score = name_similarity(q_name, c_name)
    if score is None:
        return IdentityComparison(MatchStatus.JAN_ONLY, reasons=["缺少日文商品名，无法核对名称/版本"])
    if score < 0.42:
        return IdentityComparison(MatchStatus.NAME_MISMATCH, name_score=score, reasons=[f"商品名相似度过低（{score:.2f}）"])

    q_tokens = version_tokens(q_name + " " + (query_spec or ""))
    c_tokens = version_tokens(c_name + " " + (candidate_spec or ""))
    only_q = q_tokens - c_tokens
    only_c = c_tokens - q_tokens
    if only_q or only_c:
        conflicts = sorted(only_q | only_c)
        edition_conflict = any(
            any(w.lower() in token for w in _EDITION_WORDS) or token in ("volume", "version", "edition")
            for token in conflicts
        )
        if edition_conflict:
            return IdentityComparison(
                MatchStatus.VERSION_MISMATCH,
                name_score=score,
                version_conflicts=conflicts,
                reasons=["版本/规格字段不一致：" + "、".join(conflicts)],
            )
        return IdentityComparison(
            MatchStatus.JAN_ONLY,
            name_score=score,
            version_conflicts=conflicts,
            reasons=["JAN 和名称基本一致，但版本/规格标记无法完全核对：" + "、".join(conflicts)],
        )

    if score < 0.62:
        return IdentityComparison(
            MatchStatus.JAN_ONLY,
            name_score=score,
            reasons=[f"JAN 一致但名称相似度偏低（{score:.2f}），需人工核对"],
        )
    return IdentityComparison(MatchStatus.EXACT, name_score=score, reasons=["JAN、名称与版本/规格一致"])
