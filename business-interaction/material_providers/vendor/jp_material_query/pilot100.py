# -*- coding: utf-8 -*-
"""AMNIBUS(arma bianca) 100 商品试点查询：直接公开页面访问、保守限速、断点续跑。

用法:
  python pilot100.py --limit 100 --channel "arma bianca" [--state-dir state_pilot100] [--out-dir output/pilot100]
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from jpmaterial.config import load_sites, load_glossary
from jpmaterial.adapters import AmnibusAdapter
from jpmaterial.access import AccessRegistry
from jpmaterial.cache import CacheStore
from jpmaterial.engine import QueryEngine
from jpmaterial.transport import UrllibTransport
from jpmaterial.input import read_input
from jpmaterial.output import build_summary, write_json, write_excel_simple, site_status_rows
from jpmaterial.models import MaterialStatus, MatchStatus, OverallStatus, QueryResult

XLSX = r"C:\Users\Administrator\Downloads\KMT20261101_原表修改确认表_材质参考补充版.xlsx"
CRAWL_DELAY = 15.0  # 尊重 amnibus.com/robots.txt 的 Crawl-delay: 15


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--channel", default="arma bianca")
    ap.add_argument("--state-dir", default="state_pilot100")
    ap.add_argument("--out-dir", default="output/pilot100")
    args = ap.parse_args()

    out_dir = ROOT / args.out_dir
    state_dir = ROOT / args.state_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    prog_file = out_dir / "progress.jsonl"

    policy = [p for p in load_sites(ROOT / "config" / "sites.json") if p.site_id == "amnibus"][0]
    policy.rate_limit_seconds = CRAWL_DELAY
    glossary = load_glossary(ROOT / "config")
    cache = CacheStore(state_dir / "cache.json")
    access = AccessRegistry(state_dir / "access_state.json")
    engine = QueryEngine([policy], {"amnibus": AmnibusAdapter(policy, glossary)},
                         UrllibTransport(timeout=25), cache, access, None)

    rows = read_input(XLSX)
    ab = [r for r in rows if str(r.raw.get("渠道", "")).strip() == args.channel]
    uniq = {}
    for r in ab:
        if r.jan and r.jan not in uniq:
            uniq[r.jan] = r
    targets = list(uniq.values())[: args.limit]

    cached_already = sum(1 for r in targets if cache.get("amnibus", r.jan) is not None)
    print(f"渠道[{args.channel}] 唯一JAN {len(uniq)}，本次测 {len(targets)} 条，断点已缓存 {cached_already} 条", flush=True)

    results = []
    t0 = time.time()
    for i, r in enumerate(targets, 1):
        q = r.to_query()
        st = time.time()
        res = engine.query(q, allow_online=True)
        dt = round(time.time() - st, 1)
        res.input_rows = [r.row_number]
        results.append(res)
        rec = {
            "i": i, "jan": r.jan, "status": res.status.value,
            "match": res.match_status.value, "material_status": res.material_status.value,
            "elapsed_s": dt, "total_s": round(time.time() - t0, 1),
            "material_zh": res.recommended.material_zh if res.recommended else "",
            "material_original": res.recommended.material_original if res.recommended else "",
            "url": res.recommended.product_url if res.recommended else "",
            "reason": res.reason,
        }
        print(f"[{i}/{len(targets)}] {r.jan} {res.status.value}/{res.match_status.value} {dt}s {rec['material_zh']}", flush=True)
        with open(prog_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        snap = access.snapshot().get("sites", {}).get("amnibus", {})
        if snap.get("blocked") and snap.get("last_http_status") == 403:
            print("检测到 403 明确拒绝访问，停止后续请求。", flush=True)
            for rest in targets[i:]:
                rr = QueryResult(query=rest.to_query(), status=OverallStatus.ERROR,
                                 match_status=MatchStatus.NOT_CHECKED,
                                 material_status=MaterialStatus.NOT_CHECKED,
                                 reason="站点 403 明确拒绝访问，已停止后续查询")
                rr.input_rows = [rest.row_number]
                results.append(rr)
            break

    summary = build_summary(results, len(targets), 0)
    summary["elapsed_seconds"] = round(time.time() - t0, 1)
    summary["avg_seconds_per_jan"] = round((time.time() - t0) / max(len(targets), 1), 1)
    summary["material_extracted"] = sum(1 for x in results if x.material_status == MaterialStatus.FOUND)
    summary["reliable_identity_match"] = sum(1 for x in results if x.match_status == MatchStatus.EXACT)
    summary["needs_review"] = sum(1 for x in results if x.needs_review)

    write_json(out_dir / "results.json", results, summary, mode="online_direct",
               input_path=XLSX, site_status=site_status_rows([policy]))
    write_excel_simple(out_dir / "results.xlsx", results, summary, input_path=XLSX,
                mode="online_direct", site_status=site_status_rows([policy]))
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n==== 汇总 ====", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    print("输出目录:", out_dir, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
