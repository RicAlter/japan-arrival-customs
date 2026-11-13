# -*- coding: utf-8 -*-
"""命令行入口：查询、离线解析、批量、站点状态、缓存、自检。"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

from . import __version__
from .access import AccessRegistry
from .adapters import (
    AmiAmiAdapter,
    AmnibusAdapter,
    AnimateAdapter,
    AnimeStoreAdapter,
    HobbySearchAdapter,
    JumpCharacterStoreAdapter,
    LocalLibrary,
)
from .batch import run_batch
from .cache import CacheStore
from .config import DEFAULT_CONFIG_DIR, DEFAULT_FIXTURE_DIR, DEFAULT_OUTPUT_DIR, DEFAULT_STATE_DIR, PROJECT_ROOT, load_glossary, load_sites
from .engine import QueryEngine
from .input import InputError, read_input
from .models import OverallStatus, ProductQuery
from .output import build_summary, site_status_rows, write_excel, write_excel_simple, write_json
from .textutil import now_iso, sha256_file
from .transport import UrllibTransport

ADAPTERS = {
    "amnibus": AmnibusAdapter,
    "anime_store": AnimeStoreAdapter,
    "amiami": AmiAmiAdapter,
    "jumpcs": JumpCharacterStoreAdapter,
    "hobbysearch": HobbySearchAdapter,
    "animate": AnimateAdapter,
}


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _engine(args):
    config_dir = Path(args.config_dir) if args.config_dir else DEFAULT_CONFIG_DIR
    state_dir = Path(args.state_dir) if args.state_dir else DEFAULT_STATE_DIR
    policies = load_sites(config_dir / "sites.json")
    glossary = load_glossary(config_dir)
    adapters = {p.site_id: ADAPTERS[p.site_id](p, glossary) for p in policies if p.site_id in ADAPTERS}
    cache = CacheStore(state_dir / "cache.json")
    access = AccessRegistry(state_dir / "access_state.json")
    local_path = getattr(args, "local_index", None)
    local = LocalLibrary.load(local_path, glossary) if local_path else LocalLibrary({}, glossary)
    transport = UrllibTransport(timeout=getattr(args, "timeout", 20.0))
    return QueryEngine(policies, adapters, transport, cache, access, local), policies


def _site_status(policies, access: AccessRegistry | None = None):
    rows = site_status_rows(policies)
    if access:
        snap = access.snapshot().get("sites", {})
        for row in rows:
            state = snap.get(row["site_id"], {})
            row["blocked"] = bool(state.get("blocked"))
            row["block_reason"] = state.get("reason", "")
    return rows


def _print_result(result) -> None:
    print(f"JAN: {result.query.jan}")
    print(f"查询状态: {result.status.value}  ({result.reason})")
    print(f"匹配状态: {result.match_status.value} / 材质状态: {result.material_status.value}")
    if result.recommended:
        ev = result.recommended
        print(f"来源: {ev.site_name}  {ev.product_url}")
        print(f"日文材质: {ev.material_original}")
        print(f"中文参考: {ev.material_zh}")
        if ev.material_unknown_terms:
            print(f"未翻译: {'、'.join(ev.material_unknown_terms)}")
    else:
        print("未产生材质候选。")
    if result.attempts:
        print("站点尝试:")
        for a in result.attempts:
            print(f"  - {a.site_name}: {a.status.value} {a.message}")


def cmd_sites(args) -> int:
    _, policies = _engine(args)
    access = AccessRegistry((Path(args.state_dir) if args.state_dir else DEFAULT_STATE_DIR) / "access_state.json")
    if getattr(args, "reset", None):
        ok = access.reset(args.reset)
        print(("已重置 " if ok else "未找到状态 ") + args.reset)
        return 0 if ok else 1
    rows = _site_status(policies, access)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    print(f"{'站点':24} {'启用':4} {'授权':4} {'可联网':6} 说明")
    for r in rows:
        print(f"{r['site_id']:24} {str(r['enabled']):4} {str(r['authorized']):4} {str(r['live_ready']):6} {r['authorization_note']}")
        if r.get("blocked"):
            print(f"  ! 已熔断：{r.get('block_reason')}")
    return 0


def cmd_query(args) -> int:
    engine, _ = _engine(args)
    query = ProductQuery(
        jan=args.jan,
        name_zh=args.name_zh or "",
        name_ja=args.name_ja or "",
        spec=args.spec or "",
        description_ja=args.desc_ja or "",
        brand=args.brand or "",
    )
    if args.snapshot_dir:
        result = engine.query_snapshots(query, args.snapshot_dir, all_sites=args.all_sites)
        mode = "snapshot_local"
    elif args.offline_dir:
        result = engine.query_offline(query, args.offline_dir)
        mode = "offline_fixture"
    else:
        result = engine.query(query, allow_online=args.allow_online, all_sites=args.all_sites)
        mode = "online" if args.allow_online else "offline_no_network"
    _print_result(result)
    if args.json_out:
        summary = build_summary([result], 1, 0)
        write_json(args.json_out, [result], summary, mode=mode, site_status=_site_status(engine.policies))
        print(f"JSON: {args.json_out}")
    if args.excel_out:
        write_excel(args.excel_out, [result], build_summary([result], 1, 0), input_path="", mode=mode, site_status=_site_status(engine.policies))
        print(f"Excel: {args.excel_out}")
    return 0 if result.status not in (OverallStatus.INVALID_INPUT,) else 2


def cmd_parse(args) -> int:
    engine, _ = _engine(args)
    adapter = engine.adapters.get(args.site)
    if adapter is None:
        print(f"未知站点：{args.site}", file=sys.stderr)
        return 2
    query = ProductQuery(jan=args.jan, name_zh=args.name_zh or "", name_ja=args.name_ja or "", spec=args.spec or "", description_ja=args.desc_ja or "")
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    try:
        if args.kind == "search":
            refs = adapter.parse_search(text, query)
            data = [r.__dict__ for r in refs]
            if args.json_out:
                Path(args.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            else:
                print(json.dumps(data, ensure_ascii=False, indent=1))
            return 0
        evidence = adapter.parse_detail(text, query, args.url or adapter.build_detail_url(args.jan))
    except Exception as exc:
        print(f"解析失败：{exc}", file=sys.stderr)
        return 1
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(evidence.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON: {args.json_out}")
    else:
        print(json.dumps(evidence.to_dict(), ensure_ascii=False, indent=1))
    return 0


def cmd_batch(args) -> int:
    engine, policies = _engine(args)
    try:
        sheet = int(args.sheet) if args.sheet and str(args.sheet).isdigit() else args.sheet
        rows = read_input(args.input, sheet=sheet, limit=args.limit)
    except InputError as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 2
    print(f"读取 {len(rows)} 行，开始查询（同一 JAN 只查一次）…")
    last = [0]
    def progress(idx, total, jan):
        if idx == 1 or idx == total or idx - last[0] >= 50:
            last[0] = idx
            print(f"  [{idx}/{total}] {jan}")
    batch = run_batch(engine, rows, include_filled=args.include_filled, allow_online=args.allow_online, all_sites=args.all_sites, snapshot_dir=args.snapshot_dir, progress=progress, max_seconds=args.max_seconds)
    mode = "snapshot_local" if args.snapshot_dir else ("online" if args.allow_online else "offline_no_network")
    json_path = args.json_out or str(Path(args.output).with_suffix(".json"))
    write_json(
        json_path,
        batch.results,
        batch.summary,
        mode=mode,
        input_path=args.input,
        input_sha256=sha256_file(args.input),
        site_status=_site_status(policies),
        missing_rows=batch.missing_rows,
    )
    if getattr(args, "detailed", False):
        write_excel(args.output, batch.results, batch.summary, input_path=args.input, mode=mode, site_status=_site_status(policies), missing_rows=batch.missing_rows)
    else:
        write_excel_simple(args.output, batch.results, batch.summary, input_path=args.input, mode=mode, site_status=_site_status(policies), missing_rows=batch.missing_rows)
    print("\n汇总：")
    for key, value in batch.summary.items():
        print(f"  {key}: {value}")
    print(f"JSON: {json_path}")
    print(f"Excel: {args.output}")
    return 0


def cmd_cache(args) -> int:
    cache = CacheStore((Path(args.state_dir) if args.state_dir else DEFAULT_STATE_DIR) / "cache.json")
    if args.action == "clear":
        count = cache.clear(expired_only=args.expired_only)
        print(f"已清理 {count} 条缓存")
    else:
        print(json.dumps(cache.stats(), ensure_ascii=False, indent=1))
    return 0


def cmd_selftest(args) -> int:
    root = PROJECT_ROOT / "tests"
    suite = unittest.defaultTestLoader.discover(str(root), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jpmaterial", description="日本商品材质查询插件（离线优先、只读、可审计）")
    p.add_argument("--config-dir", help="配置目录（sites.json / glossary.json）")
    p.add_argument("--state-dir", help="状态目录（缓存、403/429 状态）")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("query", help="查询单个 JAN")
    q.add_argument("--jan", required=True)
    q.add_argument("--name-zh", default="")
    q.add_argument("--name-ja", default="")
    q.add_argument("--spec", default="")
    q.add_argument("--desc-ja", default="")
    q.add_argument("--brand", default="", help="品牌/渠道")
    q.add_argument("--allow-online", action="store_true", help="允许联网；仍需站点配置 authorized=true")
    q.add_argument("--all-sites", action="store_true", help="查询所有已授权站点，不只取第一个可靠来源")
    q.add_argument("--snapshot-dir", help="人工保存的页面快照根目录（不联网、不登录）")
    q.add_argument("--offline-dir", help="离线夹具目录（只解析已保存样本，不联网）")
    q.add_argument("--json-out")
    q.add_argument("--excel-out")
    q.add_argument("--timeout", type=float, default=20.0)
    q.set_defaults(func=cmd_query)

    pa = sub.add_parser("parse", help="离线解析单个样本（HTML/JSON）")
    pa.add_argument("--site", required=True, choices=sorted(ADAPTERS))
    pa.add_argument("--jan", required=True)
    pa.add_argument("--file", required=True)
    pa.add_argument("--kind", choices=["detail", "search"], default="detail")
    pa.add_argument("--url", default="")
    pa.add_argument("--name-zh", default="")
    pa.add_argument("--name-ja", default="")
    pa.add_argument("--spec", default="")
    pa.add_argument("--desc-ja", default="")
    pa.add_argument("--json-out")
    pa.set_defaults(func=cmd_parse)

    b = sub.add_parser("batch", help="批量读取原表并输出独立候选表")
    b.add_argument("--input", required=True)
    b.add_argument("--output", required=True)
    b.add_argument("--sheet", default=None)
    b.add_argument("--limit", type=int, default=None)
    b.add_argument("--allow-online", action="store_true")
    b.add_argument("--all-sites", action="store_true")
    b.add_argument("--snapshot-dir", default=None, help="人工保存的页面快照根目录（不联网、不登录）")
    b.add_argument("--local-index", default=None, help="本地商品资料库 JSON")
    b.add_argument("--include-filled", action="store_true", help="原表已有材质也重新查询（默认跳过）")
    b.add_argument("--json-out")
    b.add_argument("--max-seconds", type=float, default=None, help="整批超时秒数，超时后剩余商品标未查询（可断点续跑）")
    b.add_argument("--detailed", action="store_true", help="输出完整明细表（含匹配状态/备注/站点尝试等）；默认输出简化表")
    b.add_argument("--timeout", type=float, default=20.0)
    b.set_defaults(func=cmd_batch)

    s = sub.add_parser("sites", help="查看站点授权/熔断状态")
    s.add_argument("--json", action="store_true")
    s.add_argument("--reset", metavar="SITE_ID", help="人工重置某站 403 熔断")
    s.set_defaults(func=cmd_sites)

    c = sub.add_parser("cache", help="查看/清理缓存")
    c.add_argument("action", choices=["stats", "clear"])
    c.add_argument("--expired-only", action="store_true")
    c.set_defaults(func=cmd_cache)

    st = sub.add_parser("selftest", help="运行离线测试")
    st.set_defaults(func=cmd_selftest)
    return p


def main(argv=None) -> int:
    _force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
