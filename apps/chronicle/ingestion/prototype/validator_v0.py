"""Deterministic production validator for Chronicle staged ingestion.

This module validates only mechanically provable contract violations. It does
not judge semantic completeness against human gold and does not decide what the
source *should* have been extracted into.
"""

from __future__ import annotations

import re
from typing import Any

from evaluator_v2 import hard_checks

_CN_MONTH_VALUES = {
    "正": 1,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}
_MONTH_RE = re.compile(r"(?:春|夏|秋|冬)?(?:闰)?(?P<month>正|十一|十二|十|[一二三四五六七八九])月")


def _items(bundle: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = bundle.get(name)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _identity(item: dict[str, Any], fallback: str) -> str:
    value = item.get("temp_id") or item.get("id")
    return str(value) if value is not None else fallback


def _source_month_at(raw: str, position: int) -> int | None:
    """Return the latest explicit traditional month marker before position."""
    current: int | None = None
    for match in _MONTH_RE.finditer(raw, 0, max(position + 1, 0)):
        current = _CN_MONTH_VALUES[match.group("month")]
    return current


def _grounded_months(raw: str, text: str) -> set[int]:
    """Return unambiguous inherited source months for exact text occurrences."""
    if not text:
        return set()
    months: set[int] = set()
    start = 0
    while True:
        position = raw.find(text, start)
        if position < 0:
            break
        month = _source_month_at(raw, position)
        if month is not None:
            months.add(month)
        start = position + max(len(text), 1)
    return months


def _declared_source_month(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    source_calendar = value.get("source_calendar")
    if not isinstance(source_calendar, dict):
        return None
    if source_calendar.get("system") != "chinese_lunisolar_regnal":
        return None
    month = source_calendar.get("month")
    return month if isinstance(month, int) and not isinstance(month, bool) else None


def source_calendar_consistency(bundle: dict[str, Any], raw: str) -> list[str]:
    """Check source-calendar months only when both sides are mechanically known.

    Missing time is not an error here; JSON Schema owns requiredness. A declared
    traditional source month is rejected only when an exact source surface can
    be located and all occurrences imply one different month.
    """
    errors: list[str] = []

    for index, event in enumerate(_items(bundle, "events"), 1):
        declared = _declared_source_month(event.get("time"))
        if declared is None:
            continue
        title = str(event.get("title") or "")
        months = _grounded_months(raw, title)
        if len(months) == 1:
            expected = next(iter(months))
            if declared != expected:
                owner = _identity(event, f"event[{index}]")
                errors.append(
                    f"{owner} source month conflicts with exact source title: expected {expected}, got {declared}"
                )

    for index, claim in enumerate(_items(bundle, "claims"), 1):
        declared = _declared_source_month(claim.get("time"))
        if declared is None:
            continue
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        text = str(evidence.get("text") or "")
        months = _grounded_months(raw, text)
        if len(months) == 1:
            expected = next(iter(months))
            if declared != expected:
                owner = _identity(claim, f"claim[{index}]")
                errors.append(
                    f"{owner} source month conflicts with exact evidence: expected {expected}, got {declared}"
                )

    return errors


def validation_report(
    bundle: dict[str, Any],
    raw: str,
    config: dict[str, Any],
    schema_errors: list[str],
) -> dict[str, Any]:
    """Return a production validation report with no human-gold semantics."""
    hard = hard_checks(bundle, raw, config)
    calendar = source_calendar_consistency(bundle, raw)
    categories = {
        "schema_validation": list(schema_errors),
        **hard,
        "source_calendar_consistency": calendar,
    }
    count = sum(len(values) for values in categories.values())
    return {
        "schema": "chronicle.ingestion-validation",
        "version": "0.1",
        "passed": count == 0,
        "count": count,
        "errors": categories,
    }


def flatten_validation_errors(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for category, messages in (report.get("errors") or {}).items():
        for message in messages or []:
            result.append(f"{category}: {message}")
    return result
