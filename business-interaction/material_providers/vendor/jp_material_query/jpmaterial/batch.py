# -*- coding: utf-8 -*-
"""批量查询：同一 JAN 只查一次，输入行只做映射，避免重复业务记录。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from .input import InputRow
from .models import MatchStatus, MaterialStatus, OverallStatus, QueryResult
from .output import build_summary


@dataclass
class BatchResult:
    results: list[QueryResult] = field(default_factory=list)
    rows: list[InputRow] = field(default_factory=list)
    missing_rows: list[InputRow] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def run_batch(
    engine,
    rows: list[InputRow],
    *,
    include_filled: bool = False,
    allow_online: bool = False,
    all_sites: bool = False,
    snapshot_dir: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    max_seconds: float | None = None,
) -> BatchResult:
    import time as _time

    groups: dict[str, list[InputRow]] = {}
    missing: list[InputRow] = []
    for row in rows:
        if not row.jan:
            missing.append(row)
            continue
        groups.setdefault(row.jan, []).append(row)

    results: list[QueryResult] = []
    total = len(groups)
    started = _time.time()
    timed_out = False
    for idx, (jan, group) in enumerate(groups.items(), 1):
        if max_seconds is not None and (_time.time() - started) > max_seconds:
            timed_out = True
        first = group[0]
        query = first.to_query()
        if timed_out:
            result = QueryResult(
                query=query, status=OverallStatus.NOT_CHECKED,
                match_status=MatchStatus.NOT_CHECKED, material_status=MaterialStatus.NOT_CHECKED,
                reason="整批超时退出，剩余商品未查询（可断点续跑，已完成请求不重复）",
            )
            result.input_rows = [r.row_number for r in group]
            results.append(result)
            continue
        try:
            materials = [r.input_material for r in group if r.input_material]
            all_have_material = all(r.input_material for r in group)
            if materials and all_have_material and not include_filled:
                result = engine.query(query, input_material=materials[0])
                result.reason = "原表已有材质，插件不覆盖、不重复查询"
            elif snapshot_dir:
                result = engine.query_snapshots(query, snapshot_dir, all_sites=all_sites)
                if result.status.value == "not_checked" and allow_online:
                    result = engine.query(query, allow_online=True, all_sites=all_sites)
            else:
                result = engine.query(query, allow_online=allow_online, all_sites=all_sites)
        except Exception as exc:  # 单个商品失败不阻断整批
            result = QueryResult(
                query=query, status=OverallStatus.ERROR,
                match_status=MatchStatus.NOT_CHECKED, material_status=MaterialStatus.NOT_CHECKED,
                reason=f"查询异常（不阻断整批）：{exc}",
            )
        result.input_rows = [r.row_number for r in group]
        if len(group) > 1:
            result.reason = (result.reason + "；" if result.reason else "") + f"同 JAN 共 {len(group)} 行，已复用同一次查询"
        results.append(result)
        if progress:
            progress(idx, total, jan)

    results.sort(key=lambda r: min(r.input_rows) if r.input_rows else 10**9)
    summary = build_summary(results, len(rows), len(missing))
    return BatchResult(results=results, rows=rows, missing_rows=missing, summary=summary)
