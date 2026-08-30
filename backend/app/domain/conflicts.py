"""Conflict detection between sources.

The website says MOQ 500, the email says 1,000. Both are "evidence". This module
decides that they disagree, which one to prefer meanwhile, and what action would
settle it — that last part is what turns a detected conflict into the next step
of the workflow rather than a warning label.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .evidence import DIRECT_SOURCES, SOURCE_WEIGHT
from .models import Conflict, ConflictStatus, Evidence
from .numbers import as_number

#: Relative tolerance below which two numbers are the same claim, not a conflict.
#: Lead times get a wider band on purpose: a site that advertises "25-30 working
#: days" and an email that says 28 are agreeing, and treating that as a
#: contradiction would spend a phone call resolving nothing. Money and minimum
#: quantities get a tight band, because there the difference is the decision.
DEFAULT_TOLERANCE = 0.05
FIELD_TOLERANCE: dict[str, float] = {
    "lead_time_days": 0.25,
    "sample_lead_time_days": 0.35,
    "moq": 0.05,
    "unit_price": 0.05,
}

#: Fields worth interrupting the workflow over.
MATERIAL_FIELDS = ("moq", "unit_price", "lead_time_days", "payment_terms", "customization")


@dataclass(frozen=True)
class Disagreement:
    field: str
    values: list[dict[str, Any]]
    preferred_value: Any
    preferred_reason: str
    action: str
    question: str


def _comparable(value: Any, field: str = "") -> Any:
    """Reduce a value to something two sources can be compared on.

    A string that states a number is compared as that number, so "MOQ 500" from
    a page and 500 from an email agree instead of being reported as a conflict.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        number = as_number(value, unit="days" if "lead_time" in field else "")
        if number is not None:
            return number
        return value.strip().lower()
    return value


def _same(a: Any, b: Any, field: str = "") -> bool:
    ca, cb = _comparable(a, field), _comparable(b, field)
    if isinstance(ca, float) and isinstance(cb, float):
        if ca == cb:
            return True
        largest = max(abs(ca), abs(cb))
        tolerance = FIELD_TOLERANCE.get(field, DEFAULT_TOLERANCE)
        return largest > 0 and abs(ca - cb) / largest <= tolerance
    return ca == cb


def _rank(evidence: Evidence) -> tuple[float, float]:
    """Direct supplier statements outrank published ones; recency breaks ties."""
    return (SOURCE_WEIGHT.get(evidence.source_type, 0.2), evidence.retrieved_at.timestamp())


def detect(field: str, items: Sequence[Evidence]) -> Disagreement | None:
    """Return a disagreement for `field`, or None when the sources agree."""
    valued = [e for e in items if e.field == field and e.value is not None]
    if len(valued) < 2:
        return None

    groups: list[list[Evidence]] = []
    for item in valued:
        for group in groups:
            if _same(group[0].value, item.value, field):
                group.append(item)
                break
        else:
            groups.append([item])

    if len(groups) < 2:
        return None

    best = max(valued, key=_rank)
    is_direct = best.source_type in DIRECT_SOURCES

    values = [
        {
            "value": group[0].value,
            "source_type": group[0].source_type.value,
            "source_url": group[0].source_url,
            "evidence_id": group[0].id,
            "excerpt": group[0].evidence_excerpt[:280],
        }
        for group in groups
    ]

    reason = (
        "direct supplier response outranks published sources"
        if is_direct
        else f"highest-weighted source is {best.source_type.value}"
    )
    return Disagreement(
        field=field,
        values=values,
        preferred_value=best.value,
        preferred_reason=reason,
        action="email",
        question=_question_for(field, groups),
    )


def _question_for(field: str, groups: list[list[Evidence]]) -> str:
    """The exact question that would settle this disagreement.

    Writing is the only way to ask, so the question has to do the work a second
    channel would otherwise do: name both values back to the supplier and ask
    which applies, rather than repeating what they already answered.
    """
    values = [g[0].value for g in groups]

    if field == "moq":
        low = min(v for v in values if isinstance(v, (int, float)))
        high = max(v for v in values if isinstance(v, (int, float)))
        question = (
            f"Your published minimum order is {low:g} but we were quoted {high:g}. "
            f"Can you confirm whether {low:g} units is possible as a pilot order?"
        )
    elif field == "unit_price":
        question = (
            "We have two different unit prices on file "
            f"({', '.join(f'{v:g}' for v in values if isinstance(v, (int, float)))}). "
            "Which applies at our quantity?"
        )
    elif field == "lead_time_days":
        question = (
            "We have conflicting production lead times "
            f"({', '.join(str(v) for v in values)} days). Which is current?"
        )
    else:
        question = f"Our sources disagree on {field.replace('_', ' ')}. Could you confirm?"

    return question


def detect_all(mission_id: str, vendor_id: str, items: Sequence[Evidence]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    fields = {e.field for e in items if e.field}
    for field in sorted(f for f in fields if f in MATERIAL_FIELDS):
        found = detect(field, items)
        if found is None:
            continue
        conflicts.append(
            Conflict(
                mission_id=mission_id,
                vendor_id=vendor_id,
                field=found.field,
                values=found.values,
                preferred_value=found.preferred_value,
                preferred_reason=found.preferred_reason,
                resolution_action=found.action,
                status=ConflictStatus.OPEN,
            )
        )
    return conflicts
