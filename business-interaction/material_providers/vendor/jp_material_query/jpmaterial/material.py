# -*- coding: utf-8 -*-
"""从网页/规格文本中提取“素材”，并严格与“サイズ”分开。"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .models import MaterialExtraction
from .textutil import html_to_text, looks_like_html, normalize_text, truncate, unique_keep_order

LABELS = ("製品素材", "本体素材", "素材", "材質", "材料", "Material")
_LABEL_ALT = "|".join(re.escape(x) for x in sorted(LABELS, key=len, reverse=True))
_BULLET = r"[■□●○◆◇★☆※\-\*・]"
_LABEL_RE = re.compile(
    r"^(?:\s*" + _BULLET + r"\s*)?(" + _LABEL_ALT + r")\s*(?:[:：])?\s*(.*)$",
    re.I,
)
_STOP_RE = re.compile(
    r"^(?:サイズ|商品サイズ|本体サイズ|パッケージサイズ|JAN(?:コード)?|型番|品番|"
    r"対象年齢|原産国|販売元|発売元|製造元|注意|備考|セット内容|付属品|"
    r"商品仕様|商品説明|商品名|ブランド|メーカー|シリーズ|重量|材質|素材)\s*(?:[:：|])",
    re.I,
)
_INLINE_RE = re.compile(
    r"(?:^|[\s|])(?:" + _BULLET + r"\s*)?(" + _LABEL_ALT + r")\s*[:：]\s*([^|\n]{1,240})",
    re.I,
)
_BODY_RE = re.compile(r"^本体\s*[:：]\s*(.+)$", re.I)
_SIZE_RE = re.compile(
    r"(?:サイズ|約?\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|g|kg)|"
    r"[WHD]\s*[×xX]\s*\d|\d+\s*[×xX]\s*\d+)",
    re.I,
)
_MATERIAL_HINTS = [
    "紙", "スチール", "鉄", "ブリキ", "PET", "PVC", "ABS", "アクリル", "ポリ",
    "綿", "コットン", "ナイロン", "レーヨン", "ゴム", "シリコン", "アルミ",
    "真鍮", "ガラス", "陶器", "木材", "木製", "合皮", "皮革", "革", "布",
    "繊維", "樹脂", "カード", "プラ", "金属", "マグネット", "ホログラム",
    "PP", "PE", "PS", "PC", "EVA", "PU", "ウレタン", "スポンジ",
    "纸", "钢", "铁", "马口铁", "亚克力", "聚酯", "棉", "尼龙", "橡胶",
    "硅胶", "铝", "黄铜", "玻璃", "陶瓷", "木材", "皮革", "纤维", "树脂",
    "塑料", "金属", "磁铁",
]
_MATERIAL_HINTS_LOWER = [h.lower() for h in _MATERIAL_HINTS]
_ENGLISH_MATERIAL_RE = re.compile(
    r"(?i)\b(?:cotton|polyester|paper|steel|iron|acrylic|nylon|rayon|rubber|"
    r"silicone|aluminum|aluminium|brass|glass|ceramic|wood|leather|"
    r"polyurethane|polypropylene|polyethylene|pvc|abs|pet|pp|pe|ps|pc|eva|pu)\b"
)
_CHINESE_MATERIAL_RE = re.compile(
    r"(纸|钢|铁|马口铁|亚克力|聚酯|棉|尼龙|橡胶|硅胶|铝|黄铜|玻璃|陶瓷|木材|皮革|纤维|树脂|塑料|金属|磁铁)"
)
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")


def _norm_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"[\s,，、・/／|:：()（）\[\]【】]+", "", value)


def looks_like_material(value: str) -> bool:
    if not value:
        return False
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return False
    if _SIZE_RE.search(text) and not any(h in text.lower() for h in _MATERIAL_HINTS_LOWER):
        if not _ENGLISH_MATERIAL_RE.search(text):
            return False
    lower = text.lower()
    if any(h in lower for h in _MATERIAL_HINTS_LOWER):
        return True
    if _ENGLISH_MATERIAL_RE.search(text):
        return True
    if _CHINESE_MATERIAL_RE.search(text):
        return True
    if _PERCENT_RE.search(text) and re.search(r"[A-Za-z一-龥ぁ-んァ-ヶ]", text):
        return True
    if re.fullmatch(r"[A-Z]{2,8}(?:\s*[・,、/]\s*[A-Z]{2,8})*", text):
        return True
    return False


def is_size_only(value: str) -> bool:
    if not value:
        return False
    if looks_like_material(value):
        return False
    return bool(_SIZE_RE.search(value))


def _clean_value(value: str) -> str:
    value = (value or "").strip()
    value = value.lstrip("|:：・-— ")
    value = value.split("|", 1)[0].strip()
    value = value.split("\n", 1)[0].strip()
    value = re.sub(
        r"\s+(?:サイズ|商品サイズ|本体サイズ|JAN(?:コード)?|型番|対象年齢|原産国|販売元|注意)\s*[:：].*$",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(r"^[■□●○◆◇★☆※\-\*・\s]+", "", value)
    value = re.sub(r"^(本体|素材|材質|材料|製品素材):", r"\1：", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip("。；; ")


def _find_size_text(lines: Iterable[str]) -> str:
    lines = list(lines)
    for i, line in enumerate(lines):
        line = line.strip().strip("|").strip()
        m = re.match(r"^\s*(?:商品サイズ|本体サイズ|サイズ|Size)\s*[:：]?\s*(.*)$", line, re.I)
        if m:
            if m.group(1).strip():
                return _clean_value(m.group(1))
            for nxt in lines[i + 1:i + 3]:
                if nxt.strip() and not _LABEL_RE.match(nxt):
                    return _clean_value(nxt)
    return ""


def _excerpt(text: str, needle: str, width: int = 140) -> str:
    if not needle:
        return ""
    idx = text.find(needle)
    if idx < 0:
        return truncate(text, width * 2)
    start = max(0, idx - width)
    end = min(len(text), idx + len(needle) + width)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


def extract_material(raw: str) -> MaterialExtraction:
    """从 HTML 或纯文本提取完整素材原文。

    支持：
    - ■素材 / 素材 / 材質 / 材料 / 製品素材 / Material
    - 表格 th/td、标签换行、正文内联
    - 本体：PVC・ABS
    绝不把“サイズ”当作素材。
    """
    if not raw:
        return MaterialExtraction(notes=["空内容"])
    text = html_to_text(raw) if looks_like_html(raw) else normalize_text(raw)
    lines = [line.strip() for line in text.splitlines()]

    candidates: list[tuple[str, str, str]] = []  # label, value, method

    def add(label: str, value: str, method: str) -> None:
        value = _clean_value(value)
        if not value:
            return
        if _STOP_RE.match(value):
            return
        if is_size_only(value):
            return
        if not looks_like_material(value) and label.lower() not in ("素材", "材質", "材料", "製品素材", "本体素材", "material"):
            return
        candidates.append((label, value, method))

    for i, line in enumerate(lines):
        if not line:
            continue

        # 表格行 / 用 | 分隔的单元格
        if "|" in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            for j, cell in enumerate(cells):
                m = _LABEL_RE.match(cell)
                if m and j + 1 < len(cells):
                    nxt = cells[j + 1]
                    if nxt and not _STOP_RE.match(nxt):
                        add(m.group(1), nxt, "table")

        # 行首标签
        m = _LABEL_RE.match(line)
        if m:
            label, rest = m.group(1), m.group(2).strip()
            rest = rest.lstrip("|:： ").strip()
            if rest and not _LABEL_RE.match(rest) and not _STOP_RE.match(rest):
                add(label, rest, "label")
            else:
                for nxt in lines[i + 1:i + 4]:
                    nxt = nxt.strip()
                    if not nxt:
                        continue
                    if _LABEL_RE.match(nxt) or _STOP_RE.match(nxt):
                        break
                    add(label, nxt, "label_next_line")
                    break

        # 本体：PVC・ABS（必须确认值里有材质词，避免抓到“本体サイズ”）
        b = _BODY_RE.match(line)
        if b and looks_like_material(b.group(1)):
            candidates.append(("本体", _clean_value(line), "body"))

        # 正文内联“素材：...”
        for im in _INLINE_RE.finditer(line):
            add(im.group(1), im.group(2), "inline")

    # 去重并保持顺序
    seen: set[str] = set()
    unique: list[tuple[str, str, str]] = []
    for label, value, method in candidates:
        key = _norm_key(value)
        if key and key not in seen:
            seen.add(key)
            unique.append((label, value, method))

    size_text = _find_size_text(lines)
    if not unique:
        notes = []
        if "素材" in text or "材質" in text or "Material" in text:
            notes.append("存在素材字段但未解析出有效值")
        if size_text:
            notes.append("仅找到尺寸字段")
        return MaterialExtraction(
            found=False,
            size_text=size_text,
            notes=notes,
            excerpt=truncate(text, 300),
        )

    # 优先选择非“本体”的明确素材字段
    preferred = [c for c in unique if c[0].lower() not in ("本体",)]
    chosen = (preferred or unique)[0]
    values = unique_keep_order([c[1] for c in unique])
    notes = []
    if len(values) > 1:
        notes.append("存在多个素材字段，已保留首选并记录备选：" + " / ".join(values[1:]))
    if chosen[0] == "本体":
        notes.append("素材值来自本体字段")

    original = chosen[1]
    if chosen[0].lower() == "material":
        # 保留 AmiAmi 规格行中的字段名，便于追溯完整原文；翻译时会剥离该前缀
        original = chosen[0] + ": " + chosen[1]
    return MaterialExtraction(
        original=original,
        label=chosen[0],
        method=chosen[2],
        found=True,
        size_text=size_text,
        alternatives=values[1:],
        notes=notes,
        excerpt=_excerpt(text, chosen[1]),
    )


def material_status_from_extraction(extraction: MaterialExtraction):
    from .models import MaterialStatus
    if extraction.found:
        return MaterialStatus.FOUND
    if extraction.size_text:
        return MaterialStatus.SIZE_ONLY
    if any("未解析出有效值" in n for n in extraction.notes):
        return MaterialStatus.EXTRACT_FAILED
    return MaterialStatus.NO_MATERIAL
