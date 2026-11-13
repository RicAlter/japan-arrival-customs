# -*- coding: utf-8 -*-
"""交付自检：授权默认关闭、历史案例通过、目标表未被修改、测试通过。"""
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

from jpmaterial.config import load_sites
from jpmaterial.textutil import sha256_file

TARGET = Path(r"C:\Users\Administrator\Downloads\KMT20261101_原表修改确认表_材质参考补充版.xlsx")


def main() -> int:
    failures = []
    policies = load_sites(ROOT / "config" / "sites.json")
    for pol in policies:
        if pol.enabled and not pol.authorized:
            failures.append(f"站点 {pol.site_id} 已启用但未批准直接访问")
    animate = next((p for p in policies if p.site_id == "animate"), None)
    if animate is None or animate.enabled:
        failures.append("Animate 未保持默认关闭")

    hist = json.loads((ROOT / "output" / "historical_cases_results.json").read_text(encoding="utf-8"))
    if hist["summary"]["candidate_ready"] != 5:
        failures.append("历史案例不是 5/5 candidate_ready")
    if hist["summary"]["with_candidate"] != 5:
        failures.append("历史案例候选数不是 5")

    target_json = ROOT / "output" / "KMT20261101_材质候选_离线预览.json"
    if target_json.exists() and TARGET.exists():
        data = json.loads(target_json.read_text(encoding="utf-8"))
        if data.get("input_sha256") != sha256_file(TARGET):
            failures.append("目标表 SHA256 与输出记录不一致（原表可能被修改）")
        if data["summary"].get("with_candidate") != 0:
            failures.append("未授权状态下不应产生新增候选")
        if data["summary"].get("not_authorized", 0) <= 0:
            failures.append("未授权站点计数异常")

    report = json.loads((ROOT / "output" / "test_report.json").read_text(encoding="utf-8"))
    if not report.get("success"):
        failures.append("测试报告不是成功状态")

    print("站点授权：" + ", ".join(f"{p.site_id}={p.authorized}" for p in policies))
    print(f"历史案例：{hist['summary']['candidate_ready']}/{hist['summary']['input_rows']} candidate_ready")
    print(f"测试：{report['tests_run']} tests, success={report['success']}")
    print(f"目标表 SHA256：{sha256_file(TARGET) if TARGET.exists() else 'N/A'}")
    if failures:
        print("FAIL:")
        for f in failures:
            print(" - " + f)
        return 1
    print("交付自检通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
