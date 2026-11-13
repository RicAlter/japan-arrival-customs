"""Create a display-only workbook revision by changing explicit R-column cells."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path


def replace_cell(xml: str, address: str, value: str) -> str:
    # Excel sheet XML may use a default namespace (``<c>``) or a namespace
    # prefix (``<x:c>``).  Accept both forms; the prior expression only
    # handled the latter and could not update blank cells in normal XLSX XML.
    pattern = rf'<(?:(?P<prefix>[^:<>]+):)?c\b[^>]*\br="{re.escape(address)}"[^>]*>'
    match = re.search(pattern, xml)
    if not match:
        raise ValueError(f"Cell not found: {address}")
    prefix = match.group("prefix")
    escaped = (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    tag = match.group(0)
    opening = tag[:-1].rstrip().rstrip("/").rstrip()
    opening = re.sub(r'\s+t="[^"]*"', "", opening)
    if tag.rstrip().endswith("/>"):
        end = match.end()
    else:
        closing = f"</{prefix + ':' if prefix else ''}c>"
        closing_at = xml.find(closing, match.end())
        if closing_at < 0:
            raise ValueError(f"Unclosed cell: {address}")
        end = closing_at + len(closing)
    tag_prefix = f"{prefix}:" if prefix else ""
    replacement = f'{opening} t="inlineStr"><{tag_prefix}is><{tag_prefix}t>{escaped}</{tag_prefix}t></{tag_prefix}is></{tag_prefix}c>'
    return xml[:match.start()] + replacement + xml[end:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", payload) if isinstance(payload, dict) else payload
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.source) as source:
        xml = source.read("xl/worksheets/sheet1.xml").decode("utf-8")
        for item in candidates:
            xml = replace_cell(xml, item["target"], item["material_zh"])

        # Do not extract/repack XLSX files: a workbook can deliberately carry
        # duplicate ZIP members for drawings/media, and extraction collapses
        # those members. Copy every original ZipInfo entry in order instead.
        with zipfile.ZipFile(args.output, "w", allowZip64=True) as target:
            for info in source.infolist():
                payload = xml.encode("utf-8") if info.filename == "xl/worksheets/sheet1.xml" else source.read(info)
                target.writestr(info, payload)


if __name__ == "__main__":
    main()
