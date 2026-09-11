"""Chronicle C2-R2-T01 continuous-reading annotation contract.

Pure deterministic validation/acceptance and DTO helpers for the
second-round reading projection, with no database, network, or model
access (Amendment 0006). Implements ``continuous-reading.md`` sections
2-3 and 5-7 as machine-checkable shared contracts consumed by T03-T17:

- :class:`ReadingLimits` fixes the engineering envelope (block, span,
  context, page/preview sizes) used by the later API/publication tasks.
- :func:`validate_reading_annotations` validates a
  ``chronicle.chapter-candidate / 0.2``: it first reuses the frozen
  first-round validation on the unchanged sub-document (so 0.1
  semantics are not rewritten), then checks reading-unit coverage, source
  reference closure, narrative-time rules, translation-span coordinates,
  event roles, and the canonical-ID/URL discipline.
- :func:`accept_reading_candidate` accepts only passing candidates and
  emits a ``chronicle.chapter-artifact / 0.2`` with program-resolved
  translation spans, unit IDs, segments and reading annotations.
- :func:`compile_time_groups` is the pre-publication pure compiler for
  narrative-time axis groups.
- ``example_*`` builders and :func:`validate_reading_dto` fix the public
  DTO machine shape shared with ``reading-types.ts``.

Coordinates are ``chars-normalized-utf8``: Python ``str`` code-point
half-open intervals ``[start, end)``. The model never computes offsets or
canonical IDs; the program enumerates occurrences and remaps identities.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import chapter_contract as _chapter
from common import PersistenceError, canonical_json_bytes, sha256_json

#: Model-generatable candidate marker (second round).
CANDIDATE_SCHEMA = "chronicle.chapter-candidate"
CANDIDATE_VERSION = "0.2"

#: Program-accepted artifact marker (second round).
ARTIFACT_SCHEMA = "chronicle.chapter-artifact"
ARTIFACT_VERSION = "0.2"

#: Reading DTO bundle marker.
READING_SCHEMA = "chronicle.reading"
READING_VERSION = "0.1"

#: Offset unit for every translation/source coordinate.
OFFSET_UNIT = "chars-normalized-utf8"

NARRATIVE_MODES = ("events", "inherit", "mixed", "unknown")
SPAN_STATUSES = ("resolved", "ambiguous", "unresolved")
SPAN_RELATIONS = ("current", "retrospective", "foreshadow", "background", "uncertain")
CONTEXT_IMPORTANCE = ("primary", "other")
NON_CURRENT_RELATIONS = ("retrospective", "foreshadow", "background")

#: Error codes / HTTP statuses fixed for the read API (continuous-reading.md §6).
READING_ERROR_CODES = {
    "bad_request": 400,
    "not_found": 404,
    "source_missing": 409,
    "source_mismatch": 409,
}

#: Public DTO names carried by ``chronicle-reading-v0.1.schema.json``.
READING_DTO_NAMES = (
    "reading_locator",
    "time_observation",
    "narrative_time",
    "event_span_view",
    "context_entity_view",
    "reading_segment",
    "reading_unit",
    "stream_page",
    "time_group",
    "event_preview_source",
    "event_preview",
    "event_target",
    "event_target_page",
)

#: Keys the model must never write inside ``reading`` (canonical IDs/URLs).
FORBIDDEN_MODEL_KEYS = frozenset(
    {
        "id",
        "canonical_id",
        "canonical_ids",
        "stream_id",
        "unit_id",
        "publication_id",
        "catalog_sha",
        "artifact_sha256",
        "group_id",
        "url",
        "href",
    }
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_URL_RE = re.compile(r"^https?://")

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "ingestion" / "schemas"
CANDIDATE_V01_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-candidate-v0.1.schema.json"
CANDIDATE_V02_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-candidate-v0.2.schema.json"
ARTIFACT_V01_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.1.schema.json"
ARTIFACT_V02_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.2.schema.json"
READING_SCHEMA_PATH = SCHEMA_DIR / "chronicle-reading-v0.1.schema.json"

CANDIDATE_V01_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.1.schema.json"
)
CANDIDATE_V02_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.2.schema.json"
)
ARTIFACT_V01_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.1.schema.json"
)
ARTIFACT_V02_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.2.schema.json"
)
READING_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-reading-v0.1.schema.json"
)


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadingLimits:
    """Engineering envelope for reading annotations and read responses.

    Defaults mirror ``continuous-reading.md`` §2-3/§6. They are
    resource-protection bounds, not model-capability guarantees.
    """

    max_block_code_points: int = 8192
    max_event_spans: int = 64
    max_context_entities: int = 128
    min_source_selections: int = 1
    max_source_selections: int = 16
    page_min_limit: int = 1
    page_max_limit: int = 50
    group_max_limit: int = 100
    page_max_bytes: int = 2 * 1024 * 1024
    unit_max_bytes: int = 256 * 1024
    preview_max_bytes: int = 64 * 1024
    preview_max_sources: int = 8
    preview_excerpt_code_points: int = 160
    json_max_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_block_code_points",
            "max_event_spans",
            "max_context_entities",
            "min_source_selections",
            "max_source_selections",
            "page_min_limit",
            "page_max_limit",
            "group_max_limit",
            "page_max_bytes",
            "unit_max_bytes",
            "preview_max_bytes",
            "preview_max_sources",
            "preview_excerpt_code_points",
            "json_max_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise PersistenceError(f"{name} must be a non-negative integer")
        if self.min_source_selections < 1:
            raise PersistenceError("min_source_selections must be at least 1")
        if self.max_source_selections < self.min_source_selections:
            raise PersistenceError("max_source_selections must be >= min_source_selections")
        if self.page_min_limit < 1:
            raise PersistenceError("page_min_limit must be at least 1")
        if self.page_max_limit < self.page_min_limit:
            raise PersistenceError("page_max_limit must be >= page_min_limit")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ReadingLimits":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise PersistenceError("reading limits must be a JSON object")
        known = {k: value[k] for k in cls().to_dict() if k in value}
        try:
            return cls(**known)
        except TypeError as exc:
            raise PersistenceError(f"invalid reading limits: {exc}") from exc


# ---------------------------------------------------------------------------
# Schema loading (v0.2 reuses the frozen v0.1 definitions by $ref)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _load_schema(path_str: str, expected_id: str) -> dict[str, Any]:
    path = Path(path_str)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PersistenceError(f"reading schema unreadable at {path}: {exc}") from exc
    if not isinstance(schema, dict) or schema.get("$id") != expected_id:
        raise PersistenceError(
            f"reading schema identity mismatch at {path}: expected $id {expected_id!r}"
        )
    return schema


@lru_cache(maxsize=8)
def _schema_bundle() -> dict[str, dict[str, Any]]:
    """Load every schema needed to resolve the 0.2 cross-file $refs."""
    schemas: dict[str, dict[str, Any]] = {}
    for path, schema_id in (
        (CANDIDATE_V01_SCHEMA_PATH, CANDIDATE_V01_SCHEMA_ID),
        (CANDIDATE_V02_SCHEMA_PATH, CANDIDATE_V02_SCHEMA_ID),
        (ARTIFACT_V01_SCHEMA_PATH, ARTIFACT_V01_SCHEMA_ID),
        (ARTIFACT_V02_SCHEMA_PATH, ARTIFACT_V02_SCHEMA_ID),
        (READING_SCHEMA_PATH, READING_SCHEMA_ID),
    ):
        schema = _load_schema(str(path), schema_id)
        schemas[schema_id] = schema
    return schemas


@lru_cache(maxsize=1)
def _registry() -> Any:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for schema in _schema_bundle().values():
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)
        )
    return registry


def candidate_v02_schema() -> dict[str, Any]:
    return _schema_bundle()[CANDIDATE_V02_SCHEMA_ID]


def artifact_v02_schema() -> dict[str, Any]:
    return _schema_bundle()[ARTIFACT_V02_SCHEMA_ID]


def reading_schema() -> dict[str, Any]:
    return _schema_bundle()[READING_SCHEMA_ID]


def _iter_schema_errors(schema: Any, value: Any, *, registry: Any = None) -> list[str]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:  # pragma: no cover - declared dependency
        return ["jsonschema package is unavailable for reading validation"]
    kwargs: dict[str, Any] = {"format_checker": FormatChecker()}
    if registry is not None:
        kwargs["registry"] = registry
    validator = Draft202012Validator(schema, **kwargs)
    found = sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path))
    errors: list[str] = []
    for error in found:
        where = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{where}: {error.message}")
    return errors


def validate_reading_dto(name: str, value: Any) -> list[str]:
    """Validate one public reading DTO against ``chronicle-reading / 0.1``."""
    if name not in READING_DTO_NAMES:
        raise PersistenceError(f"unknown reading DTO {name!r}")
    schema = {
        "$defs": reading_schema()["$defs"],
        "$ref": f"#/$defs/{name}",
    }
    if not isinstance(value, (dict, list)) and name != "time_observation":
        # Scalars are never valid DTO roots here; schema would also reject.
        pass
    return _iter_schema_errors(schema, value)


# ---------------------------------------------------------------------------
# Coordinate + span helpers (translation text, code points)
# ---------------------------------------------------------------------------


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def find_occurrences(haystack: str, needle: str) -> list[int]:
    """Return every non-overlapping code-point start of ``needle``."""
    positions: list[int] = []
    start = 0
    step = max(len(needle), 1)
    while True:
        found = haystack.find(needle, start)
        if found < 0:
            return positions
        positions.append(found)
        start = found + step


def resolve_translation_span(
    block_text: str, selection: Any, *, owner: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a translation ``{quote, occurrence}`` to a code-point span.

    Quotes are matched exactly by code point inside the single owning
    translation block; ``occurrence`` counts from 1. Unlike the source
    selector this is a distinct shape, so the two coordinate systems can
    never be confused.
    """
    if not isinstance(selection, dict):
        return None, f"{owner} selection must be an object"
    quote = selection.get("quote")
    occurrence = selection.get("occurrence")
    if not isinstance(block_text, str) or block_text == "":
        return None, f"{owner} owning translation block text is missing"
    if not isinstance(quote, str) or quote == "":
        return None, f"{owner} quote must be a non-empty string"
    if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 1:
        return None, f"{owner} occurrence must be a positive integer"
    positions = find_occurrences(block_text, quote)
    if len(positions) < occurrence:
        return None, (
            f"{owner} quote {quote!r} occurs {len(positions)} time(s) in its "
            f"translation block but occurrence={occurrence} was requested"
        )
    start = positions[occurrence - 1]
    end = start + len(quote)
    return (
        {
            "quote": quote,
            "occurrence": occurrence,
            "start": start,
            "end": end,
            "quote_sha256": sha256_text(quote),
        },
        None,
    )


def spans_overlap(spans: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Return ``(True, detail)`` when two resolved spans overlap."""
    ordered = sorted(
        (s for s in spans if isinstance(s, dict)),
        key=lambda s: (int(s.get("start", -1)), int(s.get("end", -1))),
    )
    previous: dict[str, Any] | None = None
    for span in ordered:
        start = span.get("start")
        end = span.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            return True, f"malformed span range [{start},{end})"
        if previous is not None and start < previous["end"]:
            return True, (
                f"spans {previous.get('span_id')!r} [{previous['start']},{previous['end']}) "
                f"and {span.get('span_id')!r} [{start},{end}) overlap"
            )
        previous = span
    return False, None


def build_reading_segments(
    block_text: str, resolved_spans: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Slice a translation block into ordered text/event segments.

    Concatenating every segment ``text`` reproduces ``block_text``
    verbatim; the browser never re-splits or offsets the string itself.
    """
    overlap, detail = spans_overlap(resolved_spans)
    if overlap:
        raise PersistenceError(f"cannot build reading segments: {detail}")
    ordered = sorted(resolved_spans, key=lambda s: (s["start"], s["end"]))
    segments: list[dict[str, Any]] = []
    cursor = 0
    for span in ordered:
        start, end = span["start"], span["end"]
        if start < cursor or end > len(block_text):
            raise PersistenceError(
                f"span {span.get('span_id')!r} range [{start},{end}) is out of block bounds"
            )
        if start > cursor:
            segments.append({"kind": "text", "text": block_text[cursor:start]})
        segments.append(
            {
                "kind": "event",
                "text": block_text[start:end],
                "span_id": span.get("span_id"),
                "start": start,
                "end": end,
            }
        )
        cursor = end
    if cursor < len(block_text):
        segments.append({"kind": "text", "text": block_text[cursor:]})
    if not segments:
        segments.append({"kind": "text", "text": block_text})
    joined = "".join(segment["text"] for segment in segments)
    if joined != block_text:
        raise PersistenceError("reading segments do not reassemble the translation block text")
    return segments


def unit_id_for(
    *, revision_id: str, chapter_id: str, block_id: str, artifact_sha256: str
) -> str:
    digest = sha256_json(
        {
            "revision_id": revision_id,
            "chapter_id": chapter_id,
            "block_id": block_id,
            "artifact_sha256": artifact_sha256,
        }
    )
    return "ru_" + digest[:24]


def group_id_for(
    *, stream_id: str, catalog_sha: str, first_unit_id: str, period_key: str
) -> str:
    digest = sha256_json(
        {
            "stream_id": stream_id,
            "catalog_sha": catalog_sha,
            "first_unit_id": first_unit_id,
            "period_key": period_key,
        }
    )
    return "tg_" + digest[:16]


def detect_unit_id_collisions(units: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        unit_id = unit.get("unit_id")
        block_id = unit.get("block_id")
        if not isinstance(unit_id, str):
            continue
        if unit_id in seen and seen[unit_id] != block_id:
            errors.append(
                f"unit_id collision {unit_id!r} between blocks {seen[unit_id]!r} and {block_id!r}"
            )
        seen[unit_id] = block_id
    return errors


# ---------------------------------------------------------------------------
# Narrative time: pure observation keys and axis grouping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeKey:
    year_key: str
    period_key: str
    year_label: str | None
    period_label: str
    precision: str


def observation_time_key(observation: Any) -> TimeKey:
    """Derive the canonical (non-localized) grouping key of one observation.

    Identity never uses a localized label: exact Gregorian keys are
    ``gregorian:year:month``; regnal keys are ``regnal:era:era_year:month``
    (season allowed); unconverted/opaque observations keep their original
    text; unknown/mixed/range/approximate observations get their own key.
    """
    if not isinstance(observation, dict):
        return TimeKey("unknown", "unknown", None, "时间未明确", "unknown")
    precision = observation.get("precision")
    original = observation.get("original_text")
    original_text = original if isinstance(original, str) and original else "时间未明确"
    normalized = observation.get("normalized")
    calendar = observation.get("source_calendar")
    normalized = normalized if isinstance(normalized, dict) else None
    calendar = calendar if isinstance(calendar, dict) else None

    # Leap months and other non-convertible source dates keep an opaque
    # label; they must never merge with a same-numbered ordinary month.
    if "閏" in original_text or "闰" in original_text:
        key = f"opaque:{original_text}"
        return TimeKey(key, key, None, original_text, precision or "unknown")

    if precision in ("unknown", None) and normalized is None:
        return TimeKey("unknown", "unknown", None, "时间未明确", "unknown")

    if precision in ("range", "mixed", "approximate") or (
        normalized is not None and normalized.get("precision") in ("range",)
    ):
        key = f"{precision or 'mixed'}:{original_text}"
        return TimeKey(key, key, None, original_text, precision or "mixed")

    system = calendar.get("system") if calendar else None
    gregorian_year = normalized.get("year") if normalized else None

    # Exact/partial Gregorian conversion.
    if system == "proleptic_gregorian" or (
        normalized is not None and normalized.get("conversion_status") in ("exact", "year_only")
    ):
        if isinstance(gregorian_year, int):
            month = normalized.get("month")
            if precision in ("day", "month") and isinstance(month, int):
                period_label = f"{month}月" if precision == "month" else f"{month}月"
                year_key = f"gregorian:{gregorian_year}"
                period_key = f"gregorian:{gregorian_year}:{month}:{precision}"
                return TimeKey(year_key, period_key, f"{gregorian_year}年", period_label, precision)
            year_key = f"gregorian:{gregorian_year}"
            return TimeKey(
                year_key, f"gregorian:{gregorian_year}:year", f"{gregorian_year}年",
                "（月份未明确）", "year",
            )
        return TimeKey("unknown", "unknown", None, "时间未明确", "unknown")

    # Traditional / regnal source calendar without a verified conversion.
    if calendar and calendar.get("era") is not None and calendar.get("era_year") is not None:
        era = calendar["era"]
        era_year = calendar["era_year"]
        season = calendar.get("season")
        month = calendar.get("month")
        year_key = f"regnal:{era}:{era_year}"
        year_label = f"{era}{era_year}年"
        if isinstance(month, int):
            period_key = f"regnal:{era}:{era_year}:{month}"
            return TimeKey(year_key, period_key, year_label, f"{month}月", "month")
        if isinstance(season, str) and season:
            period_key = f"regnal:{era}:{era_year}:{season}"
            return TimeKey(year_key, period_key, year_label, season, "month")
        return TimeKey(
            year_key, f"{year_key}:year", year_label, "（月份未明确）", "year"
        )

    # Leap months and anything not formally convertible stay opaque.
    opaque = original_text
    key = f"opaque:{opaque}"
    return TimeKey(key, key, None, opaque, precision or "unknown")


def narrative_time_display(
    mode: str, observations: list[dict[str, Any]] | None, *,
    source_event_refs: list[str] | None = None,
    from_block_id: str | None = None,
) -> dict[str, Any]:
    """Build the per-unit display/grouping narrative-time object.

    The distinction is deliberate: ``observations``/``status`` carry raw
    source truth while ``year_key``/``period_key`` and the labels are the
    precomputed presentation the API and browser reuse.
    """
    observations = [o for o in (observations or []) if isinstance(o, dict)]
    status = {"events": "resolved", "inherit": "resolved", "mixed": "mixed", "unknown": "unknown"}.get(
        mode, "unknown"
    )
    if mode == "unknown" or not observations:
        display = TimeKey("unknown", "unknown", None, "时间未明确", "unknown")
    elif mode == "mixed":
        keys = sorted({observation_time_key(o).period_key for o in observations})
        joined = " / ".join(keys) or "mixed"
        display = TimeKey(f"mixed:{joined}", f"mixed:{joined}", None, "多个时间观察", "mixed")
    else:
        display = observation_time_key(observations[0])
    return {
        "mode": mode,
        "status": status,
        "event_refs": list(source_event_refs or []),
        "from_block_id": from_block_id,
        "observations": copy.deepcopy(observations),
        "year_key": display.year_key,
        "period_key": display.period_key,
        "year_label": display.year_label,
        "period_label": display.period_label,
        "precision": display.precision,
        "continues_previous": False,
    }


def compile_time_groups(
    units: list[dict[str, Any]], *, stream_id: str, catalog_sha: str
) -> list[dict[str, Any]]:
    """Compile order-preserving time-axis groups from reading units.

    Only *consecutive* units sharing the same ``period_key`` merge; a year
    title prints once per year run, a period title when the period key
    changes, and pagination continues an existing ``group_id``. The
    return value is stable for identical input.
    """
    ordered = sorted(
        (u for u in units if isinstance(u, dict)),
        key=lambda u: (u.get("ordinal") if isinstance(u.get("ordinal"), int) else 0),
    )
    groups: list[dict[str, Any]] = []
    previous_year_key: str | None = None
    previous_period_key: str | None = None
    for unit in ordered:
        narrative = unit.get("narrative_time")
        narrative = narrative if isinstance(narrative, dict) else {}
        year_key = narrative.get("year_key") or "unknown"
        period_key = narrative.get("period_key") or "unknown"
        first_locator = unit.get("locator")
        if not isinstance(first_locator, dict):
            first_locator = {
                "stream_id": stream_id,
                "catalog_sha": catalog_sha,
                "unit_id": unit.get("unit_id"),
            }
        if period_key != previous_period_key:
            year_label = narrative.get("year_label")
            if year_key == previous_year_key:
                year_label = None
            groups.append(
                {
                    "group_id": group_id_for(
                        stream_id=stream_id,
                        catalog_sha=catalog_sha,
                        first_unit_id=str(unit.get("unit_id")),
                        period_key=period_key,
                    ),
                    "ordinal": len(groups),
                    "year_key": year_key,
                    "period_key": period_key,
                    "year_label": year_label,
                    "period_label": narrative.get("period_label") or "时间未明确",
                    "precision": narrative.get("precision") or "unknown",
                    "observations": copy.deepcopy(narrative.get("observations") or []),
                    "continues_previous": bool(narrative.get("continues_previous")),
                    "first_locator": copy.deepcopy(first_locator),
                    "last_locator": copy.deepcopy(first_locator),
                    "unit_count": 1,
                }
            )
        else:
            group = groups[-1]
            group["observations"].extend(copy.deepcopy(narrative.get("observations") or []))
            group["last_locator"] = copy.deepcopy(first_locator)
            group["unit_count"] += 1
        previous_year_key = year_key
        previous_period_key = period_key
    return groups


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _model_list(value: Any, owner: str, field: str, errors: list[str]) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{owner} {field} must be an array")
        return []
    return value


def _scan_model_owned(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_MODEL_KEYS:
                errors.append(
                    f"{path}.{key} is program-owned; the model must not write canonical IDs/URLs/coordinates"
                )
            _scan_model_owned(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_model_owned(child, f"{path}[{index}]", errors)
    elif isinstance(value, str):
        if _URL_RE.match(value):
            errors.append(f"{path} carries a URL; the model must not write URLs")
        elif _UUID_RE.match(value):
            errors.append(f"{path} carries a canonical UUID; the model must not write canonical IDs")


def _typed_refs(block: Any, field: str) -> list[str]:
    result: list[str] = []
    refs = block.get(field) if isinstance(block, dict) else None
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict) and isinstance(ref.get("ref"), str):
                result.append(ref["ref"])
    return result


def validate_reading_annotations(
    request: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Validate a 0.2 candidate's reading annotations against its request.

    Reuses the frozen first-round validator on the unchanged 0.1
    sub-document first, then adds second-round coverage, reference,
    time, span, context and canonical-ID checks. Any single failing part
    rejects the whole candidate.
    """
    schema_errors: list[str] = []
    chapter_errors: list[str] = []
    coverage: list[str] = []
    ref_errors: list[str] = []
    time_errors: list[str] = []
    span_errors: list[str] = []
    context_errors: list[str] = []
    limit_errors: list[str] = []
    canonical_errors: list[str] = []

    limits = ReadingLimits()

    if not isinstance(candidate, dict):
        schema_errors.append("candidate must be a JSON object")
        candidate = {}

    schema_errors.extend(
        _iter_schema_errors(candidate_v02_schema(), candidate, registry=_registry())
    )

    try:
        request_blocks = _chapter._require_request(request)
    except PersistenceError as exc:
        request_blocks = {}
        ref_errors.append(f"request: {exc}")

    # First-round semantics are reused verbatim on the unchanged sub-document.
    if isinstance(request, dict) and isinstance(candidate, dict):
        subset = copy.deepcopy(candidate)
        subset.pop("reading", None)
        subset["version"] = "0.1"
        try:
            chapter_report = _chapter.validate_chapter_candidate(request, subset)
            chapter_errors.extend(_chapter.flatten_validation_errors(chapter_report))
        except (TypeError, AttributeError, KeyError) as exc:  # fail closed
            chapter_errors.append(f"first-round validation raised {type(exc).__name__}: {exc}")

    translation = candidate.get("translation") if isinstance(candidate.get("translation"), dict) else {}
    blocks = translation.get("blocks") if isinstance(translation.get("blocks"), list) else []
    block_by_id: dict[str, dict[str, Any]] = {}
    block_order: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = block.get("block_id")
        if isinstance(block_id, str) and block_id not in block_by_id:
            block_by_id[block_id] = block
            block_order.append(block_id)
        text = block.get("text")
        if isinstance(text, str) and len(text) > limits.max_block_code_points:
            limit_errors.append(
                f"translation block {block_id!r} is {len(text)} code points, "
                f"above max_block_code_points {limits.max_block_code_points}"
            )

    bundle = candidate.get("bundle") if isinstance(candidate.get("bundle"), dict) else {}
    entities = bundle.get("entities") if isinstance(bundle.get("entities"), list) else []
    events = bundle.get("events") if isinstance(bundle.get("events"), list) else []
    entity_by_id = {
        e["temp_id"]: e for e in entities if isinstance(e, dict) and isinstance(e.get("temp_id"), str)
    }
    event_by_id = {
        e["temp_id"]: e for e in events if isinstance(e, dict) and isinstance(e.get("temp_id"), str)
    }

    block_event_refs: dict[str, set[str]] = {}
    block_entity_refs: dict[str, set[str]] = {}
    for block_id in block_order:
        block = block_by_id[block_id]
        block_event_refs[block_id] = set(_typed_refs(block, "event_refs"))
        block_entity_refs[block_id] = set(_typed_refs(block, "entity_refs"))

    reading = candidate.get("reading") if isinstance(candidate.get("reading"), dict) else {}
    raw_units = reading.get("units")
    if not isinstance(raw_units, list):
        coverage.append("reading.units must be an array")
        raw_units = []

    # Coverage: one unit per translation block, same order, no dup/miss.
    if len(raw_units) != len(blocks):
        coverage.append(
            f"reading.units has {len(raw_units)} entries but translation has {len(blocks)} blocks"
        )
    seen_unit_block_ids: set[str] = set()
    unit_block_ids: list[Any] = []
    for index, unit in enumerate(raw_units):
        if not isinstance(unit, dict):
            coverage.append(f"reading.units[{index}] must be an object")
            unit_block_ids.append(None)
            continue
        block_id = unit.get("block_id")
        unit_block_ids.append(block_id)
        if not isinstance(block_id, str) or block_id not in block_by_id:
            ref_errors.append(
                f"reading.units[{index}] references unknown translation block {block_id!r}"
            )
        elif block_id in seen_unit_block_ids:
            coverage.append(f"reading.units[{index}] duplicates block {block_id!r}")
        else:
            seen_unit_block_ids.add(block_id)
    for position, block_id in enumerate(block_order):
        if position >= len(raw_units):
            coverage.append(f"missing reading unit for translation block {block_id!r}")
            continue
        unit = raw_units[position]
        if isinstance(unit, dict) and unit.get("block_id") != block_id:
            coverage.append(
                f"reading.units[{position}].block_id {unit.get('block_id')!r} must match "
                f"translation.blocks[{position}] {block_id!r} (order preserved)"
            )
    if isinstance(reading, dict):
        _scan_model_owned(reading, "reading", canonical_errors)

    # Narrative-time relation maps (validated after the unit pass).
    mode_by_block: dict[str, str] = {}
    from_by_block: dict[str, Any] = {}

    for index, unit in enumerate(raw_units):
        if not isinstance(unit, dict):
            continue
        block_id = unit.get("block_id")
        owner = f"reading.units[{index}]"
        if not isinstance(block_id, str) or block_id not in block_by_id:
            continue
        block = block_by_id[block_id]
        text = block.get("text") if isinstance(block.get("text"), str) else ""
        event_refs_allowed = block_event_refs.get(block_id, set())

        narrative = unit.get("narrative_time")
        narrative = narrative if isinstance(narrative, dict) else {}
        mode = narrative.get("mode")
        mode_by_block[block_id] = mode
        from_block_id = narrative.get("from_block_id")
        from_by_block[block_id] = from_block_id

        time_refs = _model_list(
            narrative.get("event_refs"), owner, "narrative_time.event_refs", time_errors
        )
        current_refs = _model_list(
            unit.get("current_event_refs"), owner, "current_event_refs", ref_errors
        )
        current_set = [r for r in current_refs if isinstance(r, str)]
        for ref in time_refs:
            if not isinstance(ref, str):
                time_errors.append(f"{owner} narrative_time.event_refs has a malformed ref")
        for ref in current_set:
            if ref not in event_by_id:
                ref_errors.append(f"{owner} references unknown event {ref!r}")
            elif ref not in event_refs_allowed:
                ref_errors.append(
                    f"{owner} current_event_refs {ref!r} is not in this block's event_refs"
                )
        for ref in (r for r in time_refs if isinstance(r, str)):
            if ref not in event_by_id:
                time_errors.append(f"{owner} time event {ref!r} is unknown")
            elif ref not in current_set:
                time_errors.append(
                    f"{owner} time event {ref!r} must belong to current_event_refs"
                )

        # mode-specific time rules
        if mode == "events":
            if not current_set:
                time_errors.append(f"{owner} events mode requires at least one current_event_ref")
            if not [r for r in time_refs if isinstance(r, str)]:
                time_errors.append(f"{owner} events mode requires non-empty narrative_time.event_refs")
            if from_block_id is not None:
                time_errors.append(f"{owner} events mode must not carry from_block_id")
        elif mode == "inherit":
            if not isinstance(from_block_id, str) or not from_block_id:
                time_errors.append(f"{owner} inherit mode requires from_block_id")
            if [r for r in time_refs if isinstance(r, str)]:
                time_errors.append(f"{owner} inherit mode must not carry time event_refs")
            if current_set:
                time_errors.append(f"{owner} inherit mode must not carry current_event_refs")
        elif mode == "mixed":
            if len(current_set) < 2:
                time_errors.append(f"{owner} mixed mode requires at least two current_event_refs")
            if {r for r in time_refs if isinstance(r, str)} != set(current_set):
                time_errors.append(
                    f"{owner} mixed mode narrative_time.event_refs must list every current_event_ref"
                )
            if from_block_id is not None:
                time_errors.append(f"{owner} mixed mode must not carry from_block_id")
        elif mode == "unknown":
            if current_set:
                time_errors.append(f"{owner} unknown mode must not carry current_event_refs")
            if [r for r in time_refs if isinstance(r, str)]:
                time_errors.append(f"{owner} unknown mode must not carry time event_refs")
            if from_block_id is not None:
                time_errors.append(f"{owner} unknown mode must not carry from_block_id")
        elif mode is not None:
            time_errors.append(f"{owner} has invalid narrative_time.mode {mode!r}")

        selections = _model_list(
            narrative.get("source_selections"), owner,
            "narrative_time.source_selections", time_errors,
        )
        if mode != "unknown":
            if not (limits.min_source_selections <= len(selections) <= limits.max_source_selections):
                time_errors.append(
                    f"{owner} narrative_time.source_selections must be "
                    f"{limits.min_source_selections}..{limits.max_source_selections}"
                )
        elif selections:
            time_errors.append(f"{owner} unknown mode must not carry source_selections")
        for position, selection in enumerate(selections, 1):
            _anchor, error = _chapter.resolve_selection(
                selection, request=request, blocks_by_id=request_blocks,
                owner=f"{owner} narrative_time.source_selections[{position}]",
            )
            if error:
                time_errors.append(error)

        # Event spans: exact code-point coordinates, non-overlap, status.
        resolved_spans: list[dict[str, Any]] = []
        spans = _model_list(unit.get("event_spans"), owner, "event_spans", span_errors)
        if len(spans) > limits.max_event_spans:
            limit_errors.append(
                f"{owner} has {len(spans)} event_spans above max {limits.max_event_spans}"
            )
        seen_span_ids: set[str] = set()
        span_target_by_id: dict[str, Any] = {}
        for span_index, span in enumerate(spans):
            span_owner = f"{owner}.event_spans[{span_index}]"
            if not isinstance(span, dict):
                span_errors.append(f"{span_owner} must be an object")
                continue
            span_id = span.get("span_id")
            if not isinstance(span_id, str) or not span_id:
                span_errors.append(f"{span_owner} span_id must be a non-empty string")
            elif span_id in seen_span_ids:
                span_errors.append(f"{span_owner} duplicate span_id {span_id!r}")
            else:
                seen_span_ids.add(span_id)
            status = span.get("status")
            target_ref = span.get("target_ref")
            candidate_refs = span.get("candidate_refs")
            candidate_refs = candidate_refs if isinstance(candidate_refs, list) else []
            if status == "resolved":
                if not isinstance(target_ref, str) or candidate_refs:
                    span_errors.append(
                        f"{span_owner} resolved requires a single target_ref and empty candidate_refs"
                    )
            elif status == "ambiguous":
                if target_ref is not None or len(candidate_refs) < 2:
                    span_errors.append(
                        f"{span_owner} ambiguous requires target_ref=null and >=2 candidate_refs"
                    )
            elif status == "unresolved":
                if target_ref is not None:
                    span_errors.append(f"{span_owner} unresolved requires target_ref=null")
            else:
                span_errors.append(f"{span_owner} has invalid status {status!r}")
            for ref in ([target_ref] if isinstance(target_ref, str) else []) + [
                r for r in candidate_refs if isinstance(r, str)
            ]:
                if ref not in event_by_id:
                    ref_errors.append(f"{span_owner} references unknown event {ref!r}")
                elif ref not in event_refs_allowed:
                    span_errors.append(
                        f"{span_owner} event {ref!r} is not in this block's event_refs"
                    )
            relation = span.get("relation")
            if relation not in SPAN_RELATIONS:
                span_errors.append(f"{span_owner} has invalid relation {relation!r}")
            span_selections = _model_list(
                span.get("source_selections"), span_owner, "source_selections", span_errors
            )
            if not (limits.min_source_selections <= len(span_selections) <= limits.max_source_selections):
                span_errors.append(
                    f"{span_owner} source_selections must be "
                    f"{limits.min_source_selections}..{limits.max_source_selections}"
                )
            for position, selection in enumerate(span_selections, 1):
                _anchor, error = _chapter.resolve_selection(
                    selection, request=request, blocks_by_id=request_blocks,
                    owner=f"{span_owner}.source_selections[{position}]",
                )
                if error:
                    span_errors.append(error)
            resolved, error = resolve_translation_span(
                text, span.get("selection"), owner=f"{span_owner}.selection"
            )
            if error:
                span_errors.append(error)
                continue
            resolved["span_id"] = span_id
            resolved_spans.append(resolved)
            span_target_by_id[str(span_id)] = target_ref
            # A non-current relation must never feed the segment time basis.
            if (
                relation in NON_CURRENT_RELATIONS
                and isinstance(target_ref, str)
                and target_ref in current_set
            ):
                time_errors.append(
                    f"{span_owner} relation {relation!r} event {target_ref!r} "
                    "cannot be a current time basis"
                )
        overlap, detail = spans_overlap(resolved_spans)
        if overlap:
            span_errors.append(f"{owner} {detail}")

        # Context entities: source-supported, role index must hit this entity.
        context_allowed: set[str] = set(block_entity_refs.get(block_id, set()))
        for ref in current_set:
            event = event_by_id.get(ref)
            if not isinstance(event, dict):
                continue
            participants = event.get("participants") if isinstance(event.get("participants"), list) else []
            for participant in participants:
                if isinstance(participant, dict) and isinstance(participant.get("entity_ref"), str):
                    context_allowed.add(participant["entity_ref"])
            places = event.get("places") if isinstance(event.get("places"), list) else []
            for place in places:
                if isinstance(place, str):
                    context_allowed.add(place)

        context_entities = _model_list(
            unit.get("context_entities"), owner, "context_entities", context_errors
        )
        if len(context_entities) > limits.max_context_entities:
            limit_errors.append(
                f"{owner} has {len(context_entities)} context_entities above "
                f"max {limits.max_context_entities}"
            )
        for context_index, context in enumerate(context_entities):
            context_owner = f"{owner}.context_entities[{context_index}]"
            if not isinstance(context, dict):
                context_errors.append(f"{context_owner} must be an object")
                continue
            entity_ref = context.get("entity_ref")
            if not isinstance(entity_ref, str) or entity_ref not in entity_by_id:
                ref_errors.append(f"{context_owner} references unknown entity {entity_ref!r}")
            elif entity_ref not in context_allowed:
                context_errors.append(
                    f"{context_owner} entity {entity_ref!r} is not in this block's entity_refs "
                    "nor a current-event participant/place"
                )
            if context.get("importance") not in CONTEXT_IMPORTANCE:
                context_errors.append(
                    f"{context_owner} has invalid importance {context.get('importance')!r}"
                )
            selections = _model_list(
                context.get("source_selections"), context_owner, "source_selections", context_errors
            )
            if not (limits.min_source_selections <= len(selections) <= limits.max_source_selections):
                context_errors.append(
                    f"{context_owner} source_selections must be "
                    f"{limits.min_source_selections}..{limits.max_source_selections}"
                )
            for position, selection in enumerate(selections, 1):
                _anchor, error = _chapter.resolve_selection(
                    selection, request=request, blocks_by_id=request_blocks,
                    owner=f"{context_owner}.source_selections[{position}]",
                )
                if error:
                    context_errors.append(error)
            roles = _model_list(context.get("event_roles"), context_owner, "event_roles", context_errors)
            for role_index, role in enumerate(roles):
                role_owner = f"{context_owner}.event_roles[{role_index}]"
                if not isinstance(role, dict):
                    context_errors.append(f"{role_owner} must be an object")
                    continue
                event_ref = role.get("event_ref")
                participant_index = role.get("participant_index")
                if not isinstance(event_ref, str) or event_ref not in event_by_id:
                    ref_errors.append(f"{role_owner} references unknown event {event_ref!r}")
                    continue
                if event_ref not in current_set:
                    context_errors.append(
                        f"{role_owner} event {event_ref!r} is not a current_event_ref of this unit"
                    )
                participants = event_by_id[event_ref].get("participants")
                participants = participants if isinstance(participants, list) else []
                if (
                    not isinstance(participant_index, int)
                    or isinstance(participant_index, bool)
                    or participant_index < 0
                    or participant_index >= len(participants)
                ):
                    context_errors.append(
                        f"{role_owner} participant_index {participant_index!r} is out of range"
                    )
                    continue
                participant = participants[participant_index]
                participant_entity = participant.get("entity_ref") if isinstance(participant, dict) else None
                if participant_entity != entity_ref:
                    context_errors.append(
                        f"{role_owner} participant_index {participant_index} belongs to "
                        f"{participant_entity!r}, not {entity_ref!r}"
                    )

    # Inheritance chains: same chapter, earlier block, acyclic, reaches events.
    for block_id, mode in mode_by_block.items():
        if mode != "inherit":
            continue
        owner = f"reading unit {block_id!r}"
        target = from_by_block.get(block_id)
        if not isinstance(target, str) or target not in block_order:
            time_errors.append(
                f"{owner} inherit from_block_id {target!r} is not a block of this chapter "
                "(cross-chapter inheritance is rejected)"
            )
            continue
        if block_order.index(target) >= block_order.index(block_id):
            time_errors.append(
                f"{owner} inherit from_block_id {target!r} is not earlier in the chapter"
            )
        visited = {block_id}
        cursor: Any = target
        while isinstance(cursor, str) and cursor in mode_by_block:
            if cursor in visited:
                time_errors.append(f"{owner} inheritance chain forms a cycle at {cursor!r}")
                break
            visited.add(cursor)
            if mode_by_block.get(cursor) != "inherit":
                if mode_by_block.get(cursor) != "events":
                    time_errors.append(
                        f"{owner} inheritance chain ends at {cursor!r} "
                        f"({mode_by_block.get(cursor)!r}); it must terminate at events"
                    )
                break
            cursor = from_by_block.get(cursor)

    errors = {
        "schema_validation": sorted(schema_errors),
        "chapter": sorted(chapter_errors),
        "reading_coverage": sorted(coverage),
        "reading_refs": sorted(ref_errors),
        "reading_time": sorted(time_errors),
        "reading_spans": sorted(span_errors),
        "reading_context": sorted(context_errors),
        "limits": sorted(limit_errors),
        "canonical_id": sorted(canonical_errors),
    }
    count = sum(len(values) for values in errors.values())
    return {
        "schema": "chronicle.reading-validation",
        "version": READING_VERSION,
        "candidate_schema": CANDIDATE_SCHEMA,
        "candidate_version": CANDIDATE_VERSION,
        "passed": count == 0,
        "count": count,
        "errors": errors,
    }


def flatten_reading_errors(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for category, messages in (report.get("errors") or {}).items():
        for message in messages or []:
            result.append(f"{category}: {message}")
    return result


# ---------------------------------------------------------------------------
# Acceptance: resolved spans, unit IDs, segments and annotations
# ---------------------------------------------------------------------------


def _resolve_reading_units(
    candidate: dict[str, Any], request: dict[str, Any], artifact_sha256: str
) -> list[dict[str, Any]]:
    translation = candidate.get("translation") if isinstance(candidate.get("translation"), dict) else {}
    blocks = translation.get("blocks") if isinstance(translation.get("blocks"), list) else []
    block_by_id = {
        b["block_id"]: b for b in blocks if isinstance(b, dict) and isinstance(b.get("block_id"), str)
    }
    bundle = candidate.get("bundle") if isinstance(candidate.get("bundle"), dict) else {}
    events = bundle.get("events") if isinstance(bundle.get("events"), list) else []
    event_by_id = {
        e["temp_id"]: e for e in events if isinstance(e, dict) and isinstance(e.get("temp_id"), str)
    }
    reading = candidate.get("reading") if isinstance(candidate.get("reading"), dict) else {}
    units = reading.get("units") if isinstance(reading.get("units"), list) else []
    resolved_units: list[dict[str, Any]] = []
    for ordinal, unit in enumerate(units):
        if not isinstance(unit, dict):
            continue
        block_id = unit.get("block_id")
        block = block_by_id.get(block_id) if isinstance(block_id, str) else None
        if block is None:
            raise PersistenceError(f"cannot resolve reading unit for unknown block {block_id!r}")
        text = block.get("text") if isinstance(block.get("text"), str) else ""
        resolved_spans: list[dict[str, Any]] = []
        for span in unit.get("event_spans") or []:
            if not isinstance(span, dict):
                continue
            resolved, error = resolve_translation_span(
                text, span.get("selection"), owner=f"unit {block_id!r} span {span.get('span_id')!r}"
            )
            if error or resolved is None:
                raise PersistenceError(f"cannot resolve translation span: {error}")
            resolved_spans.append(
                {
                    "span_id": span.get("span_id"),
                    "block_id": block_id,
                    "start": resolved["start"],
                    "end": resolved["end"],
                    "quote": resolved["quote"],
                    "quote_sha256": resolved["quote_sha256"],
                    "status": span.get("status"),
                    "relation": span.get("relation"),
                    "target_ref": span.get("target_ref"),
                    "candidate_refs": list(span.get("candidate_refs") or []),
                }
            )
        segments = build_reading_segments(text, resolved_spans)
        context_entities: list[dict[str, Any]] = []
        for context in unit.get("context_entities") or []:
            if not isinstance(context, dict):
                continue
            roles: list[dict[str, Any]] = []
            for role in context.get("event_roles") or []:
                if not isinstance(role, dict):
                    continue
                event = event_by_id.get(role.get("event_ref"))
                participants = event.get("participants") if isinstance(event, dict) else None
                index = role.get("participant_index")
                if not isinstance(participants, list) or not isinstance(index, int):
                    continue
                participant = participants[index]
                roles.append(
                    {
                        "event_ref": role.get("event_ref"),
                        "role": participant.get("role") if isinstance(participant, dict) else None,
                        "participant_index": index,
                    }
                )
            context_entities.append(
                {
                    "entity_ref": context.get("entity_ref"),
                    "importance": context.get("importance"),
                    "event_roles": roles,
                }
            )
        resolved_units.append(
            {
                "unit_id": unit_id_for(
                    revision_id=request["revision_id"],
                    chapter_id=request["chapter_id"],
                    block_id=block_id,
                    artifact_sha256=artifact_sha256,
                ),
                "ordinal": ordinal,
                "block_id": block_id,
                "text_hash": sha256_text(text),
                "artifact_sha256": artifact_sha256,
                "narrative_time": copy.deepcopy(unit.get("narrative_time")),
                "current_event_refs": list(unit.get("current_event_refs") or []),
                "resolved_spans": resolved_spans,
                "context_entities": context_entities,
                "segments": segments,
            }
        )
    collisions = detect_unit_id_collisions(resolved_units)
    if collisions:
        raise PersistenceError("; ".join(collisions))
    return resolved_units


def accept_reading_candidate(
    request: dict[str, Any],
    candidate: dict[str, Any],
    *,
    producing_run: dict[str, Any],
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept a passing 0.2 candidate and emit its bound 0.2 artifact.

    Validation is always recomputed; a caller-supplied ``report`` is only
    a consistency check and can never accept a bad candidate. Every
    program-bound value (hashes, offsets, unit IDs, segments) is computed
    here, never read from the candidate. ``artifact_sha256`` binds the
    artifact core; it deliberately excludes ``reading_units`` so unit IDs
    can be derived from it.
    """
    if not isinstance(producing_run, dict):
        raise PersistenceError("producing_run must be a JSON object")
    for key in ("run_id", "model", "prompt_schema_version"):
        if not isinstance(producing_run.get(key), str) or not producing_run[key]:
            raise PersistenceError(f"producing_run requires non-empty {key!r}")
    fresh = validate_reading_annotations(request, candidate)
    if report is not None:
        if not isinstance(report, dict):
            raise PersistenceError("supplied validation report must be a JSON object")
        if bool(report.get("passed")) != bool(fresh["passed"]) or set(
            flatten_reading_errors(report)
        ) != set(flatten_reading_errors(fresh)):
            raise PersistenceError(
                "supplied validation report does not match this request/candidate pair; "
                "refusing to accept (fail closed)"
            )
    if not fresh.get("passed"):
        detail = "; ".join(flatten_reading_errors(fresh))
        raise PersistenceError(f"reading candidate failed validation: {detail}")

    subset = copy.deepcopy(candidate)
    subset.pop("reading", None)
    subset["version"] = "0.1"
    anchors = _chapter.collect_anchors(request, subset)
    candidate_copy = copy.deepcopy(candidate)
    candidate_sha256 = sha256_json(candidate_copy)
    reading = copy.deepcopy(candidate_copy.get("reading"))
    reading_sha256 = sha256_json(reading)
    core: dict[str, Any] = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_sha256": request["source_sha256"],
        "normalized_sha256": request["normalized_sha256"],
        "candidate": candidate_copy,
        "candidate_sha256": candidate_sha256,
        "anchors": anchors,
        "request_fingerprint": _chapter.request_fingerprint(request),
        "producing_run": copy.deepcopy(producing_run),
        "reading": reading,
        "reading_sha256": reading_sha256,
    }
    artifact_sha256 = sha256_json(core)
    reading_units = _resolve_reading_units(candidate_copy, request, artifact_sha256)
    artifact = dict(core)
    artifact["artifact_sha256"] = artifact_sha256
    artifact["reading_units"] = reading_units
    return artifact


# ---------------------------------------------------------------------------
# Public DTO fixture builders (contract examples, not history answers)
# ---------------------------------------------------------------------------


def example_reading_locator(
    *, stream_id: str, catalog_sha: str, unit_id: str
) -> dict[str, Any]:
    return {"stream_id": stream_id, "catalog_sha": catalog_sha, "unit_id": unit_id}


def example_time_observation(
    *,
    event_ref: str | None = None,
    original_text: str,
    source_calendar: dict[str, Any] | None,
    normalized: dict[str, Any] | None,
    precision: str,
) -> dict[str, Any]:
    return {
        "event_ref": event_ref,
        "original_text": original_text,
        "source_calendar": source_calendar,
        "normalized": normalized,
        "precision": precision,
    }


def example_reading_unit(
    *,
    ordinal: int,
    stream_id: str,
    catalog_sha: str,
    publication_id: str,
    revision_id: str,
    chapter_id: str,
    block_id: str,
    artifact_sha256: str,
    block_text: str,
    observations: list[dict[str, Any]],
    mode: str = "events",
    event_refs: list[str] | None = None,
    from_block_id: str | None = None,
    spans: list[dict[str, Any]] | None = None,
    context_entities: list[dict[str, Any]] | None = None,
    continues_previous: bool = False,
) -> dict[str, Any]:
    """Build a public ReadingUnit DTO with program-sliced segments."""
    unit_id = unit_id_for(
        revision_id=revision_id,
        chapter_id=chapter_id,
        block_id=block_id,
        artifact_sha256=artifact_sha256,
    )
    resolved_spans: list[dict[str, Any]] = []
    for span in spans or []:
        start = span.get("start")
        end = span.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            resolved, error = resolve_translation_span(
                block_text, span.get("selection"), owner=f"span {span.get('span_id')!r}"
            )
            if error or resolved is None:
                raise PersistenceError(error or "cannot resolve span")
            start, end = resolved["start"], resolved["end"]
        resolved_spans.append(
            {
                "span_id": span.get("span_id"),
                "start": start,
                "end": end,
                "status": span.get("status", "resolved"),
                "relation": span.get("relation", "current"),
                "target_ref": span.get("target_ref"),
                "target_event_id": span.get("target_event_id"),
                "candidate_refs": list(span.get("candidate_refs") or []),
            }
        )
    segments: list[dict[str, Any]] = []
    cursor = 0
    for span in sorted(resolved_spans, key=lambda s: s["start"]):
        if span["start"] > cursor:
            segments.append({"kind": "text", "text": block_text[cursor:span["start"]]})
        segments.append(
            {
                "kind": "event",
                "text": block_text[span["start"]:span["end"]],
                "span": {
                    **span,
                    "text": block_text[span["start"]:span["end"]],
                },
            }
        )
        cursor = span["end"]
    if cursor < len(block_text):
        segments.append({"kind": "text", "text": block_text[cursor:]})
    if not segments:
        segments.append({"kind": "text", "text": block_text})
    narrative_time = narrative_time_display(
        mode, observations, source_event_refs=event_refs, from_block_id=from_block_id
    )
    narrative_time["continues_previous"] = continues_previous
    group_id = group_id_for(
        stream_id=stream_id,
        catalog_sha=catalog_sha,
        first_unit_id=unit_id,
        period_key=narrative_time["period_key"],
    )
    return {
        "unit_id": unit_id,
        "ordinal": ordinal,
        "stream_id": stream_id,
        "catalog_sha": catalog_sha,
        "publication_id": publication_id,
        "chapter_id": chapter_id,
        "block_id": block_id,
        "artifact_sha256": artifact_sha256,
        "text_hash": sha256_text(block_text),
        "source_anchor_ids": [f"anc_{block_id}"],
        "segments": segments,
        "narrative_time": narrative_time,
        "context_entities": [
            {
                "entity_ref": c.get("entity_ref"),
                "name": c.get("name"),
                "canonical_id": c.get("canonical_id"),
                "kind": c.get("kind", "person"),
                "importance": c.get("importance", "primary"),
                "source_anchor_ids": list(c.get("source_anchor_ids") or []),
                "event_roles": list(c.get("event_roles") or []),
            }
            for c in (context_entities or [])
        ],
        "group_id": group_id,
        "continues_previous": continues_previous,
    }


def example_stream_page(
    *,
    stream_id: str,
    catalog_sha: str,
    limit: int,
    units: list[dict[str, Any]],
    prev_cursor: str | None = None,
    next_cursor: str | None = None,
    has_previous: bool = False,
    has_next: bool = False,
    group_continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stream_id": stream_id,
        "catalog_sha": catalog_sha,
        "limit": limit,
        "units": list(units),
        "prev_cursor": prev_cursor,
        "next_cursor": next_cursor,
        "has_previous": has_previous,
        "has_next": has_next,
        "group_continuation": group_continuation,
    }


def example_event_preview(
    *,
    event_id: str,
    catalog_sha: str,
    name: str,
    sources: list[dict[str, Any]],
    source_count: int | None = None,
) -> dict[str, Any]:
    count = source_count if isinstance(source_count, int) else len(sources)
    return {
        "event_id": event_id,
        "catalog_sha": catalog_sha,
        "name": name,
        "sources": list(sources),
        "source_count": count,
        "has_more_sources": count > len(sources),
    }


def example_event_target_page(
    *,
    event_id: str,
    catalog_sha: str,
    targets: list[dict[str, Any]],
    next_cursor: str | None = None,
    current_count: int | None = None,
    mention_count: int | None = None,
) -> dict[str, Any]:
    current = current_count if isinstance(current_count, int) else sum(
        1 for t in targets if isinstance(t, dict) and t.get("relation") == "current"
    )
    mention = mention_count if isinstance(mention_count, int) else sum(
        1 for t in targets if isinstance(t, dict) and t.get("relation") == "mention"
    )
    return {
        "event_id": event_id,
        "catalog_sha": catalog_sha,
        "targets": list(targets),
        "current_count": current,
        "mention_count": mention,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
    }


# ---------------------------------------------------------------------------
# Response budgets (continuous-reading.md §6)
# ---------------------------------------------------------------------------


def reading_response_errors(name: str, value: Any) -> list[str]:
    """Return schema errors plus the fixed byte/count budgets for one DTO."""
    errors = validate_reading_dto(name, value)
    limits = ReadingLimits()
    if name == "stream_page" and isinstance(value, dict):
        if len(canonical_json_bytes(value)) > limits.page_max_bytes:
            errors.append(
                f"stream page exceeds page_max_bytes {limits.page_max_bytes}"
            )
        limit = value.get("limit")
        if isinstance(limit, int) and not (limits.page_min_limit <= limit <= limits.page_max_limit):
            errors.append(f"stream page limit {limit} out of range")
        for unit in value.get("units") or []:
            if len(canonical_json_bytes(unit)) > limits.unit_max_bytes:
                errors.append("reading unit exceeds unit_max_bytes")
    if name == "event_preview" and isinstance(value, dict):
        if len(canonical_json_bytes(value)) > limits.preview_max_bytes:
            errors.append(f"event preview exceeds preview_max_bytes {limits.preview_max_bytes}")
        sources = value.get("sources") or []
        if len(sources) > limits.preview_max_sources:
            errors.append(f"event preview has more than {limits.preview_max_sources} sources")
        for source in sources:
            excerpt = source.get("excerpt") if isinstance(source, dict) else None
            if isinstance(excerpt, str) and len(excerpt) > limits.preview_excerpt_code_points:
                errors.append("event preview excerpt above preview_excerpt_code_points")
    if len(canonical_json_bytes(value)) > limits.json_max_bytes:
        errors.append(f"DTO exceeds json_max_bytes {limits.json_max_bytes}")
    return errors


__all__ = [
    "ARTIFACT_SCHEMA",
    "ARTIFACT_VERSION",
    "CANDIDATE_SCHEMA",
    "CANDIDATE_VERSION",
    "CONTEXT_IMPORTANCE",
    "FORBIDDEN_MODEL_KEYS",
    "NARRATIVE_MODES",
    "NON_CURRENT_RELATIONS",
    "OFFSET_UNIT",
    "READING_DTO_NAMES",
    "READING_ERROR_CODES",
    "READING_SCHEMA",
    "READING_VERSION",
    "ReadingLimits",
    "SPAN_RELATIONS",
    "SPAN_STATUSES",
    "TimeKey",
    "accept_reading_candidate",
    "artifact_v02_schema",
    "build_reading_segments",
    "candidate_v02_schema",
    "compile_time_groups",
    "detect_unit_id_collisions",
    "example_event_preview",
    "example_event_target_page",
    "example_reading_locator",
    "example_reading_unit",
    "example_stream_page",
    "example_time_observation",
    "find_occurrences",
    "flatten_reading_errors",
    "group_id_for",
    "narrative_time_display",
    "observation_time_key",
    "reading_response_errors",
    "reading_schema",
    "resolve_translation_span",
    "sha256_text",
    "spans_overlap",
    "unit_id_for",
    "validate_reading_annotations",
    "validate_reading_dto",
]
