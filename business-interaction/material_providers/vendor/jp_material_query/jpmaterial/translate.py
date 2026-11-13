# -*- coding: utf-8 -*-
"""日文/英文材质 -> 中文参考译文。

原则：
- 完整保留所有成分、比例、限定词；
- “等”必须保留；
- 无法可靠翻译的部分保留日文/英文原文；
- 不凭经验补充原文没有的成分；
- 不把尺寸翻译成材质。
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .models import TranslationResult
from .textutil import unique_keep_order

DEFAULT_GLOSSARY: dict[str, str] = {
    # 日文
    "アクリル樹脂": "亚克力树脂",
    "アクリル": "亚克力",
    "ポリエステル": "聚酯纤维",
    "ポリエチレンテレフタレート": "聚对苯二甲酸乙二醇酯",
    "ポリプロピレン": "聚丙烯",
    "ポリエチレン": "聚乙烯",
    "ポリカーボネート": "聚碳酸酯",
    "ポリウレタン": "聚氨酯",
    "ウレタン": "聚氨酯",
    "塩化ビニル": "聚氯乙烯",
    "塩ビ": "PVC",
    "綿": "棉",
    "コットン": "棉",
    "紙": "纸",
    "スチール": "钢",
    "ブリキ": "马口铁",
    "鉄": "铁",
    "ステンレス": "不锈钢",
    "アルミ": "铝",
    "真鍮": "黄铜",
    "銅": "铜",
    "ガラス": "玻璃",
    "陶器": "陶瓷",
    "磁器": "瓷器",
    "木材": "木材",
    "木製": "木制",
    "合皮": "合成皮革",
    "天然皮革": "天然皮革",
    "皮革": "皮革",
    "革": "皮革",
    "布": "布",
    "繊維": "纤维",
    "樹脂": "树脂",
    "カード": "卡片",
    "プラスチック": "塑料",
    "金属": "金属",
    "マグネット": "磁铁",
    "ホログラム": "全息",
    "ゴム": "橡胶",
    "シリコン": "硅胶",
    "ナイロン": "尼龙",
    "レーヨン": "人造丝",
    "ABS樹脂": "ABS树脂",
    "PVC樹脂": "PVC树脂",
    "PET樹脂": "PET树脂",
    "PP樹脂": "PP树脂",
    "PE樹脂": "PE树脂",
    "ABS": "ABS塑料",
    "PVC": "PVC",
    "PET": "PET塑料",
    "PP": "PP塑料",
    "PE": "PE",
    "PS": "PS",
    "PC": "PC",
    "EVA": "EVA",
    "PU": "PU",
    "本体": "主体",
    "等": "等",
    "など": "等",
    # 英文
    "Cotton": "棉",
    "Polyester": "聚酯纤维",
    "Paper": "纸",
    "Steel": "钢",
    "Iron": "铁",
    "Acrylic": "亚克力",
    "Nylon": "尼龙",
    "Rayon": "人造丝",
    "Rubber": "橡胶",
    "Silicone": "硅胶",
    "Aluminum": "铝",
    "Aluminium": "铝",
    "Brass": "黄铜",
    "Glass": "玻璃",
    "Ceramic": "陶瓷",
    "Wood": "木材",
    "Leather": "皮革",
    "Polyurethane": "聚氨酯",
    "Polypropylene": "聚丙烯",
    "Polyethylene": "聚乙烯",
    "Plastic": "塑料",
    "Metal": "金属",
}

_SEPARATOR_RE = re.compile(r"[、,，・/／]+")
_SPACE_RE = re.compile(r"\s+")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_LABEL_PREFIX_RE = re.compile(r"^(?:Material|素材|材質|材料|製品素材)\s*[:：]\s*", re.I)
_KNOWN_CHINESE_RE = re.compile(
    r"(纸|钢|铁|马口铁|亚克力|聚酯|棉|尼龙|橡胶|硅胶|铝|黄铜|玻璃|陶瓷|木材|皮革|纤维|树脂|塑料|金属|磁铁|主体)"
)
_KANA_RE = re.compile(r"[ぁ-んァ-ヶー]")


def load_glossary(path: str | Path | None = None) -> dict[str, str]:
    glossary = dict(DEFAULT_GLOSSARY)
    if path:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                glossary.update({str(k): str(v) for k, v in data.get("materials", data).items()})
    return glossary


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip()
    text = _LABEL_PREFIX_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def _is_chinese_material(text: str) -> bool:
    if _KANA_RE.search(text):
        return False
    if not _KNOWN_CHINESE_RE.search(text):
        return False
    # 纯英文 + 百分比的记录仍走翻译
    return True


def _unknown_token(token: str) -> bool:
    return bool(re.search(r"[A-Za-z一-龥ぁ-んァ-ヶ]", token)) and not re.fullmatch(r"[\d\s%.,，、・/／()（）:：\-]+", token)


def translate_material(original: str, glossary: dict[str, str] | None = None) -> TranslationResult:
    glossary = glossary or DEFAULT_GLOSSARY
    text = _normalize(original)
    if not text:
        return TranslationResult(zh="", method="empty")

    if _is_chinese_material(text):
        zh = _SEPARATOR_RE.sub("、", text)
        return TranslationResult(zh=zh, method="already_chinese")

    keys = sorted(glossary.keys(), key=len, reverse=True)
    # 英文按大小写不敏感匹配；日文按原文匹配
    key_patterns = [(k, re.compile(re.escape(k), re.I if re.search(r"[A-Za-z]", k) else 0)) for k in keys]

    pieces: list[str] = []
    unknown: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        matched = False
        for key, pattern in key_patterns:
            m = pattern.match(text, i)
            if m:
                pieces.append(glossary[key])
                i = m.end()
                matched = True
                break
        if matched:
            continue
        # 百分比整体保留
        m = _PERCENT_RE.match(text, i)
        if m:
            pieces.append(m.group(0).replace(" ", ""))
            i = m.end()
            continue
        ch = text[i]
        pieces.append(ch)
        if _unknown_token(ch):
            # 收集连续的未知片段
            j = i + 1
            while j < n:
                nxt = text[j]
                if _unknown_token(nxt):
                    j += 1
                else:
                    break
            token = text[i:j]
            unknown.append(token)
            pieces.extend(text[i + 1:j])
            i = j
        else:
            i += 1

    zh = "".join(pieces)
    # 英文“100% Cotton”->“棉100%”
    zh = re.sub(
        r"(\d+(?:\.\d+)?)%\s*(棉|聚酯纤维|纸|钢|铁|亚克力|尼龙|橡胶|硅胶|铝|黄铜|玻璃|陶瓷|木材|皮革|聚氨酯|聚丙烯|聚乙烯|塑料|金属)",
        r"\2\1%",
        zh,
    )
    # 统一中文分隔符
    zh = _SEPARATOR_RE.sub("、", zh)
    zh = re.sub(r"[ \t]+", " ", zh).strip()
    zh = re.sub(r"、{2,}", "、", zh)
    zh = zh.strip("、 ")
    # 括号与百分比中不必要的空格
    zh = re.sub(r"\s*([()（）])\s*", r"\1", zh)
    zh = re.sub(r"(\d)\s+%", r"\1%", zh)
    zh = re.sub(r"([\u4e00-\u9fff])\s+(\d+(?:\.\d+)?)%", r"\1\2%", zh)
    zh = re.sub(r"^(主体|材质|素材|材料):", r"\1：", zh)

    return TranslationResult(
        zh=zh,
        unknown_terms=unique_keep_order(unknown),
        method="glossary",
    )
