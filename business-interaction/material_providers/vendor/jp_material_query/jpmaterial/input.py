# -*- coding: utf-8 -*-
"""读取到货原表：只读，不修改输入文件。

列位不写死：通过表头别名自动识别 JAN / 商品名 / 规格 / 日文描述 / 材质。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import openpyxl

from .jan import normalize_jan, validate_jan
from .models import ProductQuery
from .textutil import clean_cell

JAN_ALIASES = [
    "ProductCode(JANCode)", "ProductCode", "JANCode", "JANコード", "JAN", "jan code",
    "JAN码", "商品コード", "商品编码", "JC",
]
NAME_ZH_ALIASES = ["商品名称", "商品名", "品名", "产品", "品名（中文）", "中文品名"]
NAME_JA_ALIASES = ["DescriptionofGoods", "Description", "商品説明", "日文描述", "日文品名", "英文描述"]
SPEC_ALIASES = ["规格", "規格", "版本", "仕様", "规格/版本", "款式"]
MATERIAL_ALIASES = ["材质", "素材", "已确认材质", "已確認材質", "材质参考"]
BRAND_ALIASES = ["品牌", "渠道", "ブランド", "Brand", "Channel", "メーカー"]


class InputError(RuntimeError):
    pass


@dataclass
class InputRow:
    row_number: int
    jan_raw: str
    jan: str
    name_zh: str = ""
    name_ja: str = ""
    spec: str = ""
    description_ja: str = ""
    brand: str = ""
    input_material: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def valid_jan(self) -> bool:
        return validate_jan(self.jan)[0]

    @property
    def jan_reason(self) -> str:
        return validate_jan(self.jan)[1]

    def to_query(self) -> ProductQuery:
        return ProductQuery(
            jan=self.jan,
            name_zh=self.name_zh,
            name_ja=self.name_ja,
            spec=self.spec,
            description_ja=self.description_ja,
            brand=self.brand,
            source_row=self.row_number,
            raw=self.raw,
        )


def _norm_header(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean_cell(value))
    text = re.sub(r"[\s_\-()（）\[\]【】/\\]+", "", text).lower()
    return text


def _find_col(headers: list[str], aliases: Iterable[str]) -> int | None:
    normalized = [_norm_header(h) for h in headers]
    normalized_aliases = [_norm_header(a) for a in aliases]
    for alias in normalized_aliases:
        if alias in normalized:
            return normalized.index(alias)
    for alias in normalized_aliases:
        for i, header in enumerate(normalized):
            if header and (alias in header or header in alias):
                return i
    return None


def _detect_header(ws, max_scan: int = 10) -> tuple[int, list[str]]:
    best_row = 1
    best_score = -1
    best_values: list[str] = []
    for row_no, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), 1):
        values = [clean_cell(v) for v in row]
        joined = " ".join(values).lower()
        score = 0
        if re.search(r"jan", joined):
            score += 3
        if any(a.lower() in joined for a in ("商品名称", "商品名", "descriptionofgoods", "品名")):
            score += 2
        if any(a.lower() in joined for a in ("材质", "素材", "规格", "規格")):
            score += 1
        if score > best_score:
            best_score = score
            best_row = row_no
            best_values = values
    return best_row, best_values


def read_input(
    path: str | Path,
    *,
    sheet: str | int | None = None,
    limit: int | None = None,
    header_row: int | None = None,
) -> list[InputRow]:
    p = Path(path)
    if not p.exists():
        raise InputError(f"输入文件不存在：{p}")
    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    if sheet is None:
        ws = wb.worksheets[0]
    elif isinstance(sheet, int):
        ws = wb.worksheets[sheet]
    else:
        if sheet not in wb.sheetnames:
            raise InputError(f"工作表不存在：{sheet}")
        ws = wb[sheet]

    it = ws.iter_rows(values_only=True)
    if header_row is None:
        header_row, header_values = _detect_header(ws)
        for _ in range(header_row - 1):
            next(it, None)
        header = next(it, None) or []
    else:
        for _ in range(header_row - 1):
            next(it, None)
        header = next(it, None) or []
        header_values = [clean_cell(v) for v in header]

    headers = [clean_cell(v) for v in header]
    jan_col = _find_col(headers, JAN_ALIASES)
    if jan_col is None:
        raise InputError("未识别到 JAN 列；请检查表头或使用 --jan-column 指定（当前版本按表头自动识别）")
    name_col = _find_col(headers, NAME_ZH_ALIASES)
    name_ja_col = _find_col(headers, NAME_JA_ALIASES)
    spec_col = _find_col(headers, SPEC_ALIASES)
    material_col = _find_col(headers, MATERIAL_ALIASES)
    brand_col = _find_col(headers, BRAND_ALIASES)

    rows: list[InputRow] = []
    for row_no, raw in enumerate(it, header_row + 1):
        if raw is None:
            continue
        values = list(raw)
        def cell(idx: int | None) -> str:
            if idx is None or idx >= len(values):
                return ""
            return clean_cell(values[idx])

        jan_raw = cell(jan_col)
        jan = normalize_jan(jan_raw)
        name_zh = cell(name_col)
        name_ja = cell(name_ja_col)
        spec = cell(spec_col)
        description = cell(name_ja_col)
        material = cell(material_col)
        brand = cell(brand_col)
        if not any([jan_raw, name_zh, name_ja, spec, material]):
            continue
        rows.append(InputRow(
            row_number=row_no,
            jan_raw=jan_raw,
            jan=jan,
            name_zh=name_zh,
            name_ja="",
            spec=spec,
            description_ja=description,
            brand=brand,
            input_material=material,
            raw={headers[i]: clean_cell(values[i]) for i in range(min(len(headers), len(values)))},
        ))
        if limit is not None and len(rows) >= limit:
            break

    wb.close()
    return rows


def group_rows(rows: Iterable[InputRow]) -> dict[str, list[InputRow]]:
    groups: dict[str, list[InputRow]] = {}
    for row in rows:
        key = row.jan if row.jan else f"__missing__:{row.row_number}"
        groups.setdefault(key, []).append(row)
    return groups
