"""Read explicitly mapped local purchase/order exports as reference evidence."""
from __future__ import annotations

import datetime as dt
import re

from .common import BASE, ORDER, read_mapped, run

# Excel date/time cells are part of the raw-row snapshot but have no JSON form.
# The shared contract cannot be edited from this branch, so the adapter keeps
# them as ISO text inside the evidence snapshot only. No value is invented,
# converted semantically or promoted to a mapped field.
_DATETIME_TYPES = (dt.datetime, dt.date, dt.time)

# Real order sheets store dates as text: '2026-10-22', '2026/8/15', '2026/12' or
# '2026/12\n到货时间：预计27年1-2月'. V1 has no date field, so extraction stays a
# reported helper rather than a record value; unknown shapes yield None.
_FULL_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_MONTH_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})$")


def _json_safe(value):
    if isinstance(value, _DATETIME_TYPES):
        return value.isoformat()
    return value


def extract_text_date(value):
    """Return an ISO date/month for a text or Excel date cell, else None.

    Only the leading line is read, so shipping notes such as '到货时间：预计…'
    never leak into the date. Month-level text stays month-level ('2026-12');
    nothing is padded to a day and nothing is inferred from surrounding text.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    head = value.split("\n")[0].strip()
    full = _FULL_DATE.match(head)
    if full:
        return "{}-{:02d}-{:02d}".format(*(int(part) for part in full.groups()))
    month = _MONTH_DATE.match(head)
    if month:
        return "{}-{:02d}".format(*(int(part) for part in month.groups()))
    return None


def collect(request):
    """Preserve each source row; identity matching and approval stay downstream."""
    records = list(read_mapped(request, BASE | ORDER))
    for record in records:
        for field in record["fields"].values():
            field["reference_type"] = "purchase_reference"
        for snapshot in record.get("_evidence", {}).values():
            snapshot["values"] = {key: _json_safe(value)
                                  for key, value in snapshot.get("values", {}).items()}
    return records


if __name__ == "__main__":
    raise SystemExit(run("order", collect))
