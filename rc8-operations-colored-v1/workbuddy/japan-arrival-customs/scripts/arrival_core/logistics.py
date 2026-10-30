"""Reuse P0 carton expansion; compare physical cartons and group total weight, never allocate by guess."""
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from . import _p0_frozen as p0
from .core import Rejected, decimal


def read_weights(path, sheet_name):
    path = Path(path).resolve(strict=True)
    book = p0.Book(path.read_bytes(), str(path))
    sheet = next((s for s in book.sheets if s.name == sheet_name), None)
    if sheet is None:
        raise Rejected("指定箱重工作表不存在")
    if not (p0.clean(sheet.v(1, "A")) == "箱番" and "KGS" in p0.clean(sheet.v(1, "D"))):
        raise Rejected("箱重表头不匹配KMT模板")
    groups, issues = [], []
    for ri in sorted(sheet.rows):
        if ri < 2 or not p0.present(sheet.v(ri, "A")):
            continue
        carton = p0.text(sheet.v(ri, "A"))
        # A labelled detail cannot disappear merely because a required number is missing.
        entities = p0.expand(carton)
        if not entities:
            if p0.numeric_text(sheet.v(ri, "C")) is not None or p0.numeric_text(sheet.v(ri, "D")) is not None:
                issues.append({"row": ri, "reason": "unparsed_carton", "carton": carton})
            continue
        count = p0.numeric_text(sheet.v(ri, "C")); weight = p0.numeric_text(sheet.v(ri, "D"))
        valid = (count is not None and weight is not None and count.is_finite() and weight.is_finite()
                 and count > 0 and count == count.to_integral_value() and weight >= 0)
        if not valid:
            issues.append({"row": ri, "reason": "missing_or_invalid_count_weight"})
        elif len(entities) != count:
            issues.append({"row": ri, "reason": "range_count_mismatch"})
        groups.append({"carton_raw": carton, "entities": entities,
                       "count": p0.text(count) if count is not None else None,
                       "total_kg": p0.text(weight) if weight is not None else None,
                       "unit_weight_observed": p0.text(sheet.v(ri, "B")),
                       "source": {"path": str(path), "sha256": book.sha256, "sheet": sheet.name, "row": ri}})
    if not groups:
        raise Rejected("箱重表没有可识别的物理箱组")
    return {"groups": groups, "issues": issues, "unit": "KG", "source_sha256": book.sha256}


def reconcile_logistics(rows, weights):
    required, bad_rows = set(), []
    for row in rows:
        entities = p0.expand(row["logistics"]["carton_raw"])
        if entities:
            required.update(entities)
        else:
            bad_rows.append(row["id"])
    counts = Counter(e for group in weights["groups"] for e in group["entities"])
    observed = set(counts)
    duplicate = sorted(e for e, count in counts.items() if count > 1)
    issues = list(weights["issues"])
    total_weight = Fraction(0); total_count = 0; invalid_totals = False
    for group in weights["groups"]:
        try:
            count = decimal(group["count"]); weight = decimal(group["total_kg"])
            if count != count.to_integral_value() or count <= 0 or weight < 0:
                raise Rejected("invalid group")
            total_count += int(count); total_weight += Fraction(weight)
        except Rejected:
            invalid_totals = True
            issues.append({"reason": "invalid_group_totals", "row": group["source"]["row"]})
    missing = sorted(required - observed); extra = sorted(observed - required)
    passed = not (issues or duplicate or missing or extra or bad_rows) and total_count == len(observed)
    return {"passed": passed, "physical_cartons": len(observed), "declared_cartons": None if invalid_totals else total_count,
            "total_weight_kg": None if invalid_totals else str(total_weight), "required_cartons": len(required),
            "missing_cartons": missing, "extra_cartons": extra, "duplicate_cartons": duplicate,
            "unparsed_item_rows": bad_rows, "issues": issues,
            "per_carton_weight_allocated": False, "human_approved": False}
