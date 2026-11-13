# -*- coding: utf-8 -*-
"""用已保存历史样本生成独立演示结果（不联网）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jpmaterial.access import AccessRegistry
from jpmaterial.cache import CacheStore
from jpmaterial.cli import ADAPTERS
from jpmaterial.config import load_glossary, load_sites
from jpmaterial.engine import QueryEngine
from jpmaterial.models import ProductQuery
from jpmaterial.output import build_summary, site_status_rows, write_excel, write_json
from jpmaterial.transport import UrllibTransport


class NoNetworkTransport:
    def get(self, url, headers=None):
        raise AssertionError("演示脚本不允许联网")


def main() -> int:
    policies = load_sites(ROOT / "config" / "sites.json")
    glossary = load_glossary(ROOT / "config")
    adapters = {p.site_id: ADAPTERS[p.site_id](p, glossary) for p in policies if p.site_id in ADAPTERS}
    state = ROOT / "state"
    state.mkdir(exist_ok=True)
    engine = QueryEngine(
        policies, adapters, NoNetworkTransport(),
        CacheStore(state / "demo_cache.json"), AccessRegistry(state / "demo_access.json"), None,
    )
    cases = json.loads((ROOT / "fixtures" / "historical_cases.json").read_text(encoding="utf-8"))["cases"]
    results = []
    failures = []
    for idx, case in enumerate(cases, 1):
        q = ProductQuery(jan=case["jan"], name_ja=case["name_ja"], name_zh=case.get("label") or case["case_id"])
        r = engine.query_offline(q, ROOT / "fixtures" / "historical", site_ids=[case["site_id"]])
        r.input_rows = [idx]
        results.append(r)
        if not r.recommended or r.recommended.material_original != case["material_original"] or r.recommended.material_zh != case["material_zh"]:
            failures.append(case["case_id"])
    summary = build_summary(results, len(cases), 0)
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    json_path = out / "historical_cases_results.json"
    xlsx_path = out / "historical_cases_results.xlsx"
    write_json(json_path, results, summary, mode="offline_fixture", site_status=site_status_rows(policies))
    write_excel(xlsx_path, results, summary, input_path="", mode="offline_fixture", site_status=site_status_rows(policies))

    lines = [
        "# 历史样本离线验证结果",
        "",
        "| 案例 | 站点 | JAN | 日文材质原文 | 中文参考 | 状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        ev = r.recommended
        lines.append(f"| {r.query.name_zh} | {ev.site_name if ev else ''} | {r.query.jan} | {ev.material_original if ev else ''} | {ev.material_zh if ev else ''} | {r.status.value} |")
    (out / "historical_cases_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n汇总：{json.dumps(summary, ensure_ascii=False)}")
    print(f"JSON: {json_path}")
    print(f"Excel: {xlsx_path}")
    if failures:
        print("失败案例：" + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
