# -*- coding: utf-8 -*-
"""从已有业务表生成只读本地材质索引（可选，第三阶段使用）。

示例：
python scripts/build_local_index.py \
  --input "C:\\path\\报单汇总.xlsx" \
  --jan-column "jan code" --material-column "材质" \
  --source "历史报单汇总" --out data/local_index.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import openpyxl

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jpmaterial.jan import normalize_jan


def norm(value) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def find_col(headers, name):
    target = re.sub(r"[\s_\-()（）/\\]+", "", name).lower()
    for i, h in enumerate(headers):
        if re.sub(r"[\s_\-()（）/\\]+", "", h).lower() == target:
            return i
    for i, h in enumerate(headers):
        if target and target in re.sub(r"[\s_\-()（）/\\]+", "", h).lower():
            return i
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--sheet", default=None)
    p.add_argument("--jan-column", default="JAN")
    p.add_argument("--material-column", default="材质")
    p.add_argument("--name-column", default=None)
    p.add_argument("--source", default="本地业务表")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    wb = openpyxl.load_workbook(args.input, data_only=True, read_only=True)
    ws = wb[args.sheet] if args.sheet else wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    headers = [norm(v) for v in next(it)]
    jan_i = find_col(headers, args.jan_column)
    mat_i = find_col(headers, args.material_column)
    name_i = find_col(headers, args.name_column) if args.name_column else None
    if jan_i is None or mat_i is None:
        print(f"找不到列：JAN={args.jan_column} 材质={args.material_column}", file=sys.stderr)
        return 2
    records = []
    seen = set()
    for row in it:
        jan = normalize_jan(row[jan_i] if jan_i < len(row) else "")
        mat = norm(row[mat_i] if mat_i < len(row) else "")
        if not jan or not mat:
            continue
        name = norm(row[name_i]) if name_i is not None and name_i < len(row) else ""
        key = (jan, mat)
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "jan": jan,
            "material_zh": mat,
            "name_ja": name,
            "source": args.source,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "record_id": f"{args.source}:{jan}:{len(records) + 1}",
        })
    data = {"schema_version": 1, "source": args.source, "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "records": records}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写入 {len(records)} 条记录：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
