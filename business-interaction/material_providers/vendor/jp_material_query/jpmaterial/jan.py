# -*- coding: utf-8 -*-
"""JAN-13 规范化与校验。"""
from __future__ import annotations

import re
import unicodedata


def normalize_jan(value) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    digits = re.sub(r"\D", "", text)
    return digits


def is_valid_jan13(value: str) -> bool:
    jan = normalize_jan(value)
    if len(jan) != 13 or not jan.isdigit():
        return False
    digits = [int(c) for c in jan]
    total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    check = (10 - total % 10) % 10
    return check == digits[12]


def validate_jan(value) -> tuple[bool, str]:
    jan = normalize_jan(value)
    if not jan:
        return False, "JAN 缺失"
    if len(jan) != 13:
        return False, f"JAN 长度不是 13 位（实际 {len(jan)} 位）"
    if not jan.isdigit():
        return False, "JAN 含非数字字符"
    if not is_valid_jan13(jan):
        return False, "JAN 校验位不正确"
    return True, ""


def jan_prefix(jan: str, length: int = 7) -> str:
    return normalize_jan(jan)[:length]
