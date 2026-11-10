# -*- coding: utf-8 -*-
"""接口验收（CLI 级，离线，不联网）：校验 query 命令的输入输出契约。"""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]

KNOWN_STATUS = {
    "candidate_ready", "needs_review", "conflict", "no_material", "not_found",
    "error", "not_authorized", "invalid_input", "existing_material", "not_checked",
}


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "r.json"
        cmd = [
            sys.executable, "run.py", "query",
            "--jan", "4571608537527",
            "--name-zh", "测试商品",
            "--name-ja", "テスト フィギュア 通常版",
            "--spec", "通常版",
            "--brand", "arma bianca",
            "--offline-dir", "fixtures/historical",
            "--json-out", str(out),
        ]
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print("FAIL: query 命令退出码", r.returncode, r.stderr)
            return 1
        data = json.loads(out.read_text(encoding="utf-8"))
        res = data["results"][0]
        q = res["query"]
        rec = res.get("recommended") or {}
        checks = {
            "schema_version=1": data.get("schema_version") == 1,
            "query.jan 为 13 位": len(q.get("jan", "")) == 13,
            "query.brand 透传": q.get("brand") == "arma bianca",
            "query.spec 透传": q.get("spec") == "通常版",
            "status 在标准集合": res.get("status") in KNOWN_STATUS,
            "recommended.material_zh 存在": bool(rec.get("material_zh")),
            "recommended.site_name 存在": bool(rec.get("site_name")),
            "recommended.product_url 存在": bool(rec.get("product_url")),
        }
        for name, ok in checks.items():
            print(("PASS " if ok else "FAIL ") + name)
            if not ok:
                failures.append(name)
    if failures:
        print("接口验收失败：" + "、".join(failures))
        return 1
    print("接口验收通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
