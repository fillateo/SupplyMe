"""Reading numbers out of what suppliers and models actually write.

A lead time comes back as `21`, `"21"`, `"10-14"`, `"21 hari kerja"` or
`"3-4 weeks"`. A price arrives as `8500`, `"Rp 8.500"` or `"8,500"`. The rest of
the system wants a float or nothing, and "nothing" has to be a real outcome —
guessing a magnitude from an ambiguous string is how a mission ends up
recommending a supplier on a number nobody quoted.

Ranges resolve to their upper bound. A buyer planning a first production run
against the optimistic end of "10-14 days" has mis-planned; against MOQ, the
upper bound is the quantity they might actually have to buy.
"""

from __future__ import annotations

import re
from typing import Any

# The dashes are deliberately ambiguous characters: suppliers type en and em
# dashes in ranges and the parser has to match what they actually wrote.
_RANGE = re.compile(r"^\s*([\d.,]+)\s*(?:-|–|—|to|s/d|sampai)\s*([\d.,]+)")  # noqa: RUF001
_FIRST_NUMBER = re.compile(r"[\d][\d.,]*")
_WEEKS = re.compile(r"\b(week|minggu|pekan)", re.I)
_MONTHS = re.compile(r"\b(month|bulan)", re.I)


def parse_decimal(text: str) -> float | None:
    """Read one number written in either thousands convention.

    `8.500` is eight and a half thousand in Indonesian and eight-point-five in
    English. The disambiguation is positional: a lone separator followed by
    exactly three digits is a thousands separator.
    """
    cleaned = text.strip().rstrip(".,")
    if not cleaned:
        return None
    if "." in cleaned and "," in cleaned:
        # Whichever appears last is the decimal separator.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        for separator in (".", ","):
            if separator not in cleaned:
                continue
            parts = cleaned.split(separator)
            if len(parts) > 2 or len(parts[-1]) == 3:
                cleaned = cleaned.replace(separator, "")     # thousands
            else:
                cleaned = cleaned.replace(separator, ".")    # decimal
    try:
        return float(cleaned)
    except ValueError:
        return None


def as_number(value: Any, *, unit: str = "") -> float | None:
    """Best-effort numeric reading. Returns None rather than guessing.

    `unit="days"` converts a value written in weeks or months, because a lead
    time of "3-4 weeks" compared against a 30-day target as the number 4 is
    worse than no answer at all.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    match = _RANGE.match(text)
    if match:
        low, high = parse_decimal(match.group(1)), parse_decimal(match.group(2))
        number = high if high is not None else low
    else:
        found = _FIRST_NUMBER.search(text)
        number = parse_decimal(found.group(0)) if found else None

    if number is None:
        return None
    if unit == "days":
        if _WEEKS.search(text):
            number *= 7
        elif _MONTHS.search(text):
            number *= 30
    return number


#: Fields the system stores as numbers, and the unit they are read in.
NUMERIC_FIELDS: dict[str, str] = {
    "moq": "",
    "unit_price": "",
    "lead_time_days": "days",
    "sample_lead_time_days": "days",
}


def normalize_field(field: str, value: Any) -> Any:
    """Coerce a numeric field, leaving text fields untouched."""
    if field not in NUMERIC_FIELDS:
        return value
    return as_number(value, unit=NUMERIC_FIELDS[field])
