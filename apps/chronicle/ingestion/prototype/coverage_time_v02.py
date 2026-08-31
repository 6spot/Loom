"""Deterministic source-time hydration for Chronicle coverage additions.

This module may fill *missing* source-calendar time fields from machine-derived
audit-unit context plus explicit document chronology. It never overwrites a
conflicting model value and never invents Gregorian month/day precision.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from model_v0 import ModelV0Error, parse_model_response


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
_MONTH_RE = re.compile(
    r"(?P<marker>(?:春|夏|秋|冬)?(?:闰)?(?P<month>正|十一|十二|十|[一二三四五六七八九])月)"
)


def _coverage_units(raw: str) -> list[dict[str, str]]:
    parts = re.split(r"[，。；！？\n]+", raw)
    result: list[dict[str, str]] = []
    for part in parts:
        text = part.strip()
        if text:
            result.append({"unit_id": f"u{len(result) + 1:03d}", "text": text})
    return result


def _unit_contexts(raw: str) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    current_month: int | None = None
    current_marker: str | None = None
    for unit in _coverage_units(raw):
        match = _MONTH_RE.search(unit["text"])
        explicit = match is not None
        if match:
            current_month = _CN_MONTH_VALUES[match.group("month")]
            current_marker = match.group("marker")
        contexts[unit["unit_id"]] = {
            "text": unit["text"],
            "source_month_hint": current_month,
            "source_month_marker": current_marker,
            "month_explicit_in_unit": explicit,
        }
    return contexts


def _chronology(context: dict[str, Any]) -> dict[str, Any]:
    value = context.get("chronology")
    return value if isinstance(value, dict) else {}


def _safe_time(
    unit_context: dict[str, Any], document_context: dict[str, Any]
) -> dict[str, Any]:
    month = unit_context.get("source_month_hint")
    marker = unit_context.get("source_month_marker")
    if not isinstance(month, int) or not isinstance(marker, str) or not marker:
        raise ModelV0Error("cannot hydrate coverage time without a source-month marker")

    chronology = _chronology(document_context)
    era = chronology.get("default_era")
    era_year = chronology.get("current_era_year")
    normalized_year = chronology.get("normalized_year")
    source_system = chronology.get("source_calendar") or "chinese_lunisolar_regnal"
    if source_system != "chinese_lunisolar_regnal":
        raise ModelV0Error(
            "coverage source-time hydration requires chinese_lunisolar_regnal document context"
        )

    inherited_fields: list[str] = []
    if era is not None:
        inherited_fields.append("era")
    if era_year is not None:
        inherited_fields.append("era_year")
    if not unit_context.get("month_explicit_in_unit"):
        inherited_fields.append("month")

    source_calendar: dict[str, Any] = {
        "system": "chinese_lunisolar_regnal",
        "month": month,
    }
    if era is not None:
        source_calendar["era"] = era
    if era_year is not None:
        source_calendar["era_year"] = era_year
    if inherited_fields:
        source_calendar["inherited_fields"] = inherited_fields

    normalized = {
        "calendar": "proleptic_gregorian",
        "year": normalized_year if isinstance(normalized_year, int) else None,
        "month": None,
        "day": None,
        "precision": "year" if isinstance(normalized_year, int) else "unknown",
        "conversion_status": "year_only" if isinstance(normalized_year, int) else "unresolved",
        "approximate": False,
    }
    return {
        "original_text": marker,
        "source_calendar": source_calendar,
        "normalized": normalized,
    }


def hydrate_missing_source_times(
    response_text: str,
    raw: str,
    document_context: dict[str, Any],
) -> tuple[str, list[str]]:
    """Fill only missing source-time values for additions referenced by audit units.

    Existing conflicting time values are deliberately preserved so the normal
    coverage validator can reject them. The returned JSON remains a model
    response object and is reparsed by the normal coverage protocol afterwards.
    """

    value = parse_model_response(response_text)
    audit = value.get("audit")
    if not isinstance(audit, list):
        return response_text, []

    contexts = _unit_contexts(raw)
    ref_units: dict[str, set[str]] = {}
    for row in audit:
        if not isinstance(row, dict):
            continue
        unit_id = str(row.get("unit_id") or "")
        context = contexts.get(unit_id)
        if not context or context.get("source_month_hint") is None:
            continue
        refs = list(row.get("addition_refs") or [])
        if row.get("claim_status") == "gap":
            refs.extend(row.get("claim_refs") or [])
        for ref in refs:
            if isinstance(ref, str):
                ref_units.setdefault(ref, set()).add(unit_id)

    hydrated: list[str] = []
    for collection in ("events", "claims"):
        items = value.get(collection)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            identity = item.get("temp_id") or item.get("id")
            if not isinstance(identity, str) or identity not in ref_units:
                continue
            unit_ids = ref_units[identity]
            if len(unit_ids) != 1:
                # Let the strict validator report conflicting multi-unit months.
                continue
            unit_context = contexts[next(iter(unit_ids))]
            expected_month = unit_context.get("source_month_hint")
            time = item.get("time")

            if time is None:
                item["time"] = _safe_time(unit_context, document_context)
                hydrated.append(identity)
                continue
            if not isinstance(time, dict):
                continue

            source_calendar = time.get("source_calendar")
            if source_calendar is None:
                safe = _safe_time(unit_context, document_context)
                time["source_calendar"] = safe["source_calendar"]
                time.setdefault("original_text", safe["original_text"])
                time.setdefault("normalized", safe["normalized"])
                hydrated.append(identity)
                continue
            if not isinstance(source_calendar, dict):
                continue

            actual_month = source_calendar.get("month")
            if actual_month is None and isinstance(expected_month, int):
                source_calendar["month"] = expected_month
                marker = unit_context.get("source_month_marker")
                if not time.get("original_text") and isinstance(marker, str):
                    time["original_text"] = marker
                if "normalized" not in time or time.get("normalized") is None:
                    time["normalized"] = _safe_time(unit_context, document_context)["normalized"]
                hydrated.append(identity)
            # If actual_month conflicts, do nothing: strict validation must fail.

    return json.dumps(value, ensure_ascii=False), sorted(set(hydrated))
