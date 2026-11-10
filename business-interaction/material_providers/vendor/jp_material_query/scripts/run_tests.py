# -*- coding: utf-8 -*-
"""运行离线测试并写出 output/test_report.txt / .json。"""
from __future__ import annotations

import io
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)
    text = stream.getvalue()
    out_dir = ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "test_report.txt").write_text(text, encoding="utf-8")
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "success": result.wasSuccessful(),
    }
    (out_dir / "test_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text[-4000:])
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
