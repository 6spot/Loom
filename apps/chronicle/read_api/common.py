"""Deterministic helpers for Chronicle read-model presentation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


READ_SCHEMA_VERSION = "0.1"


class ReadModelError(RuntimeError):
    """Base Chronicle read-model error."""


class ReadModelNotFound(ReadModelError):
    """Requested canonical object does not exist."""


def display_surface(values: Iterable[Any]) -> str | None:
    """Choose a deterministic presentation surface without making it identity authority."""
    cleaned = [value for value in values if isinstance(value, str) and value]
    if not cleaned:
        return None
    counts = Counter(cleaned)
    return min(counts, key=lambda value: (-counts[value], len(value), value))


def normalized_year(payload: dict[str, Any]) -> int | None:
    time = payload.get("time")
    if not isinstance(time, dict):
        return None
    normalized = time.get("normalized")
    if not isinstance(normalized, dict):
        return None
    year = normalized.get("year")
    return year if isinstance(year, int) else None


def time_window(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    years = sorted({year for payload in payloads if (year := normalized_year(payload)) is not None})
    if not years:
        return {
            "start_year": None,
            "end_year": None,
            "status": "unknown",
        }
    return {
        "start_year": years[0],
        "end_year": years[-1],
        "status": "single_year" if len(years) == 1 else "source_range",
    }


def event_display(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(payloads)
    return {
        "title": display_surface(payload.get("title") for payload in materialized),
        "type": display_surface(payload.get("type") for payload in materialized),
    }


def entity_display(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(payloads)
    return {
        "name": display_surface(payload.get("canonical_name") for payload in materialized),
        "type": display_surface(payload.get("type") for payload in materialized),
    }


def ref_key(bundle: str, ref: str) -> tuple[str, str]:
    if not isinstance(bundle, str) or not bundle or not isinstance(ref, str) or not ref:
        raise ReadModelError("representation requires non-empty bundle/ref")
    return bundle, ref
