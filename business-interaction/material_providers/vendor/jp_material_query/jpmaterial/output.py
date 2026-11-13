# -*- coding: utf-8 -*-
"""JSON / Excel 输出。输出永远是独立文件，不覆盖输入原表。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import __version__
from .models import AccessStatus, MatchStatus, MaterialStatus, OverallStatus, QueryResult
from .textutil import now_iso, sha256_file, unique_keep_order


class OutputError(RuntimeError):
    pass


STATUS_LABELS = {
    OverallStatus.CANDIDATE_READY: "候选待核对",
    OverallStatus.NEEDS_REVIEW: "需人工核对",
    OverallStatus.CONFLICT: "多来源冲突",
    OverallStatus.NOT_FOUND: "未找到商品",
    OverallStatus.NO_MATERIAL: "无材质字段",
    OverallStatus.NOT_AUTHORIZED: "未授权",
    OverallStatus.ERROR: "查询异常",
    OverallStatus.INVALID_INPUT: "JAN 异常",
    OverallStatus.EXISTING_MATERIAL: "原表已有材质",
    OverallStatus.NOT_CHECKED: "未查询",
}

SIMPLE_STATUS_LABELS = {
    OverallStatus.CANDIDATE_READY: "已查到",
    OverallStatus.NEEDS_REVIEW: "已查到",
    OverallStatus.CONFLICT: "多来源冲突",
    OverallStatus.NOT_FOUND: "未找到商品",
    OverallStatus.NO_MATERIAL: "无材质字段",
    OverallStatus.NOT_AUTHORIZED: "未授权",
    OverallStatus.ERROR: "查询异常",
    OverallStatus.INVALID_INPUT: "JAN异常",
    OverallStatus.EXISTING_MATERIAL: "原表已有",
    OverallStatus.NOT_CHECKED: "未查询",
}
MATCH_LABELS = {
    MatchStatus.EXACT: "JAN/名称/版本一致",
    MatchStatus.JAN_ONLY: "仅 JAN 一致",
    MatchStatus.VERSION_MISMATCH: "版本/规格不一致",
    MatchStatus.NAME_MISMATCH: "商品名不一致",
    MatchStatus.JAN_MISMATCH: "JAN 不一致",
    MatchStatus.MULTIPLE: "多候选",
    MatchStatus.NOT_FOUND: "未找到",
    MatchStatus.INVALID_JAN: "JAN 无效",
    MatchStatus.NOT_CHECKED: "未核对",
}
MATERIAL_LABELS = {
    MaterialStatus.FOUND: "找到材质",
    MaterialStatus.NO_MATERIAL: "无材质",
    MaterialStatus.SIZE_ONLY: "仅尺寸",
    MaterialStatus.EXTRACT_FAILED: "提取失败",
    MaterialStatus.NOT_CHECKED: "未查询",
}
ACCESS_LABELS = {
    AccessStatus.OK: "正常/已解析",
    AccessStatus.CACHED: "缓存命中",
    AccessStatus.NOT_AUTHORIZED: "未授权",
    AccessStatus.SITE_DISABLED: "站点关闭",
    AccessStatus.BLOCKED_403: "403 熔断",
    AccessStatus.RATE_LIMITED: "429 限流",
    AccessStatus.NETWORK_ERROR: "网络异常",
    AccessStatus.HTTP_ERROR: "HTTP 异常",
    AccessStatus.PARSE_ERROR: "解析异常",
    AccessStatus.SKIPPED: "未开启联网",
}


def action_label(result: QueryResult) -> str:
    if result.status == OverallStatus.EXISTING_MATERIAL:
        return "保留原表材质"
    if result.status == OverallStatus.CANDIDATE_READY:
        return "候选待人工核对"
    if result.status == OverallStatus.CONFLICT:
        return "多来源冲突，人工核对"
    if result.status == OverallStatus.NO_MATERIAL:
        return "页面无材质，人工补查"
    if result.status == OverallStatus.NOT_AUTHORIZED:
        return "等待站点授权"
    if result.status == OverallStatus.ERROR:
        return "查询异常，人工处理"
    if result.status == OverallStatus.NOT_FOUND:
        return "未找到商品"
    if result.status == OverallStatus.INVALID_INPUT:
        return "核对 JAN"
    return "人工判断"


def _error_code(result: QueryResult) -> str:
    if result.recommended and result.recommended.error_code:
        return result.recommended.error_code
    codes = unique_keep_order([c.error_code for c in result.candidates if c.error_code])
    if codes:
        return ",".join(codes)
    codes = unique_keep_order([
        a.status.value for a in result.attempts
        if a.status not in (AccessStatus.OK, AccessStatus.CACHED, AccessStatus.SKIPPED, AccessStatus.SITE_DISABLED)
    ])
    return ",".join(codes)


def _source(result: QueryResult):
    ev = result.recommended
    if ev is None:
        parsed = [c for c in result.candidates if c.access_status == AccessStatus.OK and (c.name_ja or c.material_original)]
        ev = parsed[0] if parsed else None
    if ev is None:
        return "", "", "", result.queried_at, ""
    return ev.site_name, ev.source_type, ev.product_url, ev.queried_at or result.queried_at, ev.content_hash


def _notes(result: QueryResult) -> str:
    parts = [result.reason]
    if result.recommended and result.recommended.notes:
        parts.append(result.recommended.notes)
    for c in result.candidates:
        if c is result.recommended:
            continue
        if c.match_status in (MatchStatus.EXACT, MatchStatus.JAN_ONLY) and c.notes:
            parts.append(f"{c.site_name}: {c.notes}")
    return "；".join(unique_keep_order([p for p in parts if p]))


def build_summary(results, input_rows: int, missing_rows: int):
    def count(status: OverallStatus) -> int:
        return sum(1 for r in results if r.status == status)

    summary = {
        "input_rows": input_rows,
        "unique_jan": len(results),
        "missing_jan": missing_rows,
        "existing_material": count(OverallStatus.EXISTING_MATERIAL),
        "candidate_ready": count(OverallStatus.CANDIDATE_READY),
        "needs_review": count(OverallStatus.NEEDS_REVIEW),
        "conflict": count(OverallStatus.CONFLICT),
        "no_material": count(OverallStatus.NO_MATERIAL),
        "not_authorized": count(OverallStatus.NOT_AUTHORIZED),
        "error": count(OverallStatus.ERROR),
        "not_found": count(OverallStatus.NOT_FOUND),
        "invalid_input": count(OverallStatus.INVALID_INPUT),
        "not_checked": count(OverallStatus.NOT_CHECKED),
        "with_candidate": sum(1 for r in results if r.recommended is not None),
        "duplicate_rows_reused": max(0, input_rows - missing_rows - len(results)),
    }
    if summary["not_authorized"] and not summary["with_candidate"]:
        summary["conclusion"] = "所有相关站点均未授权，未发出网络请求，因此没有新增材质候选；这不等于“没有材质”。"
    elif summary["with_candidate"]:
        summary["conclusion"] = "已生成材质候选，但均为候选参考，需人工核对后才能采用。"
    else:
        summary["conclusion"] = "本次没有生成可用候选，请按查询状态分类处理。"
    return summary


def write_json(
    path,
    results,
    summary,
    *,
    mode: str,
    input_path: str = "",
    input_sha256: str = "",
    site_status=None,
    missing_rows=None,
) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "plugin_version": __version__,
        "generated_at": now_iso(),
        "mode": mode,
        "input_path": input_path,
        "input_sha256": input_sha256,
        "disclaimer": "网站/本地记录中的材质仅为候选参考，不自动等于最终海关申报材质；采用前须人工核对。",
        "summary": summary,
        "site_status": site_status or [],
        "missing_rows": [
            {
                "row_number": r.row_number,
                "jan_raw": r.jan_raw,
                "jan": r.jan,
                "name_zh": r.name_zh,
                "spec": r.spec,
                "reason": r.jan_reason or "JAN 缺失",
            }
            for r in (missing_rows or [])
        ],
        "results": [r.to_dict() for r in results],
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _safe(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _style_sheet(ws, widths) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    thin = Side(style="thin", color="D9E2F3")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    if ws.max_row >= 1 and ws.max_column >= 1:
        ws.auto_filter.ref = "A1:" + get_column_letter(ws.max_column) + str(ws.max_row)
    ws.row_dimensions[1].height = 32


def _append(ws, values, hyperlink_idx=None) -> None:
    ws.append([_safe(v) for v in values])
    if hyperlink_idx is not None:
        cell = ws.cell(row=ws.max_row, column=hyperlink_idx)
        if isinstance(cell.value, str) and cell.value.startswith("http"):
            cell.hyperlink = cell.value
            cell.font = Font(color="0563C1", underline="single", size=10)


def write_excel(
    path,
    results,
    summary,
    *,
    input_path: str,
    mode: str,
    site_status=None,
    missing_rows=None,
) -> Path:
    out = Path(path)
    if input_path and os.path.abspath(str(out)) == os.path.abspath(str(input_path)):
        raise OutputError("输出路径不能与输入原表相同；插件不会覆盖原始业务表")
    out.parent.mkdir(parents=True, exist_ok=True)
    before_sha = sha256_file(input_path) if input_path and Path(input_path).exists() else ""

    wb = Workbook()
    ws = wb.active
    ws.title = "查询结果"
    headers = [
        "序号", "JAN", "商品名称(中文)", "日文描述", "规格/版本", "原表材质", "处理建议",
        "查询状态", "匹配状态", "材质状态", "日文材质原文", "中文材质参考", "未知词(保留日文)",
        "来源网站", "来源类型", "商品详情URL", "查询时间", "内容哈希",
        "来源商品名(日文)", "来源规格", "来源尺寸", "来源摘要", "是否需要人工核对",
        "错误码", "备注", "候选数", "出现行号", "状态码",
    ]
    ws.append(headers)
    for idx, result in enumerate(results, 1):
        source_name, source_type, url, qtime, chash = _source(result)
        recommended = result.recommended
        ws_rows = ",".join(str(x) for x in result.input_rows)
        _append(ws, [
            idx,
            result.query.jan,
            result.query.name_zh,
            result.query.description_ja or result.query.name_ja,
            result.query.spec,
            result.input_material,
            action_label(result),
            STATUS_LABELS.get(result.status, result.status.value),
            MATCH_LABELS.get(result.match_status, result.match_status.value),
            MATERIAL_LABELS.get(result.material_status, result.material_status.value),
            recommended.material_original if recommended else "",
            recommended.material_zh if recommended else "",
            "、".join(recommended.material_unknown_terms) if recommended else "",
            source_name,
            source_type,
            url,
            qtime,
            chash,
            recommended.name_ja if recommended else "",
            recommended.spec_text if recommended else "",
            recommended.size_text if recommended else "",
            recommended.source_excerpt if recommended else "",
            "是" if result.needs_review else "否",
            _error_code(result),
            _notes(result),
            len(result.candidates),
            ws_rows,
            result.status.value + "|" + result.match_status.value + "|" + result.material_status.value,
        ], hyperlink_idx=16)
    _style_sheet(ws, {
        "A": 6, "B": 16, "C": 30, "D": 40, "E": 14, "F": 14, "G": 18,
        "H": 14, "I": 16, "J": 12, "K": 30, "L": 24, "M": 18,
        "N": 18, "O": 14, "P": 42, "Q": 20, "R": 16, "S": 28,
        "T": 20, "U": 20, "V": 50, "W": 12, "X": 16, "Y": 44, "Z": 8, "AA": 14, "AB": 28,
    })

    # 站点尝试明细
    ws2 = wb.create_sheet("站点尝试")
    ws2.append(["JAN", "商品名称", "站点", "访问状态", "HTTP", "URL", "缓存", "耗时ms", "说明"])
    for result in results:
        for attempt in result.attempts:
            _append(ws2, [
                result.query.jan,
                result.query.name_zh,
                attempt.site_name,
                ACCESS_LABELS.get(attempt.status, attempt.status.value),
                attempt.http_status or "",
                attempt.url,
                "是" if attempt.cached else "否",
                attempt.elapsed_ms,
                attempt.message,
            ], hyperlink_idx=6)
    _style_sheet(ws2, {"A": 16, "B": 30, "C": 22, "D": 18, "E": 8, "F": 48, "G": 8, "H": 10, "I": 50})

    # 输入行映射（含重复 JAN）
    ws3 = wb.create_sheet("输入行映射")
    ws3.append(["行号", "JAN", "商品名称", "规格", "原表材质", "查询结果JAN", "处理建议"])
    for result in results:
        for row_no in result.input_rows:
            ws3.append([
                row_no,
                result.query.jan,
                result.query.name_zh,
                result.query.spec,
                result.input_material,
                result.query.jan,
                action_label(result),
            ])
    _style_sheet(ws3, {"A": 8, "B": 16, "C": 34, "D": 16, "E": 16, "F": 16, "G": 20})

    # 无法查询（JAN 缺失等）
    if missing_rows:
        ws5 = wb.create_sheet("无法查询")
        ws5.append(["行号", "原始JAN", "商品名称", "规格", "原因", "建议"])
        for r in missing_rows:
            ws5.append([r.row_number, r.jan_raw, r.name_zh, r.spec, r.jan_reason or "JAN 缺失", "人工补 JAN 后再查询"])
        _style_sheet(ws5, {"A": 8, "B": 20, "C": 34, "D": 16, "E": 24, "F": 24})

    # 说明
    ws4 = wb.create_sheet("说明")
    after_sha = sha256_file(input_path) if input_path and Path(input_path).exists() else ""
    info = [
        ("插件", "日本商品材质查询插件（离线优先 / 只读）"),
        ("版本", __version__),
        ("生成时间", now_iso()),
        ("运行模式", mode),
        ("输入文件", input_path),
        ("输入文件 SHA256（写入前）", before_sha),
        ("输入文件 SHA256（写入后）", after_sha),
        ("输入文件是否被修改", "否" if before_sha == after_sha else "是（异常，请检查）"),
        ("输出文件", str(out.resolve())),
        ("免责声明", "网站/本地记录中的材质仅为候选参考，不自动等于最终海关申报材质；采用前须人工核对。"),
        ("列位说明", "插件不写死 G/H/I 列；本表列位由输出模板决定，原表列位由输入表头自动识别。"),
        ("", ""),
        ("汇总", ""),
    ]
    for key, value in summary.items():
        info.append((key, value))
    info.append(("", ""))
    info.append(("站点授权状态", ""))
    for site in site_status or []:
        line = site.get("site_name", "") + " | 授权=" + str(site.get("authorized")) + " | 启用=" + str(site.get("enabled")) + " | " + site.get("authorization_note", "")
        info.append((site.get("site_id", ""), line))
    for key, value in info:
        ws4.append([key, value])
    ws4.column_dimensions["A"].width = 34
    ws4.column_dimensions["B"].width = 120
    for row in ws4.iter_rows(min_row=1):
        row[0].font = Font(bold=True)
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    wb.save(out)
    final_sha = sha256_file(input_path) if input_path and Path(input_path).exists() else ""
    if before_sha and final_sha and before_sha != final_sha:
        raise OutputError("检测到输入原表在输出过程中发生变化；插件不应修改原表，请立即检查")
    return out


def write_excel_simple(path, results, summary, *, input_path="", mode="", site_status=None, missing_rows=None) -> Path:
    """简化输出：单表直接给出材质结果，不标注“人工核对”，便于合并进主表。"""
    out = Path(path)
    if input_path and os.path.abspath(str(out)) == os.path.abspath(str(input_path)):
        raise OutputError("输出路径不能与输入原表相同；插件不会覆盖原始业务表")
    out.parent.mkdir(parents=True, exist_ok=True)
    before_sha = sha256_file(input_path) if input_path and Path(input_path).exists() else ""

    wb = Workbook()
    ws = wb.active
    ws.title = "查询结果"
    ws.append(["序号", "JAN", "商品名称(中文)", "规格/版本", "中文材质参考", "日文材质原文", "来源网站", "商品详情URL", "查询状态"])
    for idx, result in enumerate(results, 1):
        zh, ja, site, url = "", "", "", ""
        rec = result.recommended
        if rec and (rec.material_zh or rec.material_original):
            zh, ja, site, url = rec.material_zh, rec.material_original, rec.site_name, rec.product_url
        else:
            zhs = unique_keep_order([x.material_zh for x in result.candidates if x.material_zh])
            if len(zhs) > 1:
                zh = " / ".join(zhs)
            elif zhs:
                zh = zhs[0]
            for x in result.candidates:
                if x.material_zh:
                    ja = x.material_original or ja
                    site = x.site_name or site
                    url = x.product_url or url
                    break
        _append(ws, [
            idx, result.query.jan, result.query.name_zh, result.query.spec,
            zh, ja, site, url,
            SIMPLE_STATUS_LABELS.get(result.status, result.status.value),
        ], hyperlink_idx=8)
    _style_sheet(ws, {"A": 6, "B": 16, "C": 30, "D": 14, "E": 22, "F": 28, "G": 16, "H": 44, "I": 12})

    ws2 = wb.create_sheet("说明")
    channels = "、".join(unique_keep_order([str(s.get("site_name", "")) for s in (site_status or []) if s.get("authorized")]))
    info = [
        ("插件", "日本商品材质查询插件"),
        ("版本", __version__),
        ("生成时间", now_iso()),
        ("运行模式", mode or ""),
        ("输入文件", input_path or ""),
        ("来源渠道", channels),
        ("输出文件", str(out.resolve())),
        ("说明", "中文材质参考由网站原文翻译而来，供查漏补缺参考；正式申报前请人工核对实物与原文。"),
        ("", ""),
        ("汇总", ""),
    ]
    for key, value in (summary or {}).items():
        info.append((str(key), value))
    for key, value in info:
        ws2.append([key, value])
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 110
    for row in ws2.iter_rows(min_row=1):
        row[0].font = Font(bold=True)
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    wb.save(out)
    final_sha = sha256_file(input_path) if input_path and Path(input_path).exists() else ""
    if before_sha and final_sha and before_sha != final_sha:
        raise OutputError("检测到输入原表在输出过程中发生变化；插件不应修改原表，请立即检查")
    return out


def site_status_rows(policies):
    return [
        {
            "site_id": p.site_id,
            "site_name": p.site_name,
            "enabled": p.enabled,
            "authorized": p.authorized,
            "live_ready": p.live_ready,
            "authorization_note": p.authorization_note,
            "priority": p.priority,
        }
        for p in policies
    ]
