"""Pure contract for composing immutable Chronicle history editions.

An edition is an ordered manifest of already published narrative fragments.  It
does not copy or edit a second facts store: paragraph, phase, conclusion and
evidence values remain owned by the fragment that published them.  The module
only validates the references and emits deterministic, source-scoped mappings
for the later persistence and read layers.

The public functions deliberately have no database, clock, model or network
dependency.  A fragment is a ``chronicle.historical-publication / 0.1`` value
with ``publication_status == "published"`` and an explicit non-year coverage
range.  The range is a small ordering guard; it is not a historical date and
is never inferred from ``year``/``period`` fields.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from common import PersistenceError, sha256_json


HISTORY_EDITION_SCHEMA = "chronicle.history-edition"
HISTORY_EDITION_VERSION = "0.1"
CONTRACT_VERSION = f"{HISTORY_EDITION_SCHEMA}/{HISTORY_EDITION_VERSION}"
PUBLISHED_STATUS = "published"

# A fragment retains the existing narrative production limit.  The edition
# has no 256 paragraph cap: its purpose is to compose several such fragments.
MAX_FRAGMENT_PARAGRAPHS = 256
MAX_NAVIGATION_ENTRIES = 12
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# These are stable machine categories for T10/T11.  The pure contract does
# not assign HTTP statuses; an API may map these categories to its own status
# policy without changing the persisted manifest.
HISTORY_EDITION_ERROR_CODES = {
    "invalid_input": "malformed edition or fragment input",
    "fragment_not_published": "a selected fragment is not published",
    "duplicate_fragment": "the same fragment/publication is selected more than once",
    "fragment_capacity_exceeded": "one fragment exceeds its production capacity",
    "missing_reference": "a local paragraph/phase/conclusion/evidence reference is missing",
    "cross_fragment_reference": "content or evidence crosses a fragment boundary",
    "local_order_changed": "a fragment's published paragraph order was changed",
    "mapping_incomplete": "the edition mapping does not cover its source references",
    "anchor_out_of_bounds": "a navigation or boundary anchor is outside its fragment",
    "entry_unreachable": "a curated entry does not reach a readable paragraph/event",
    "boundary_review_missing": "an adjacent fragment seam has no review record",
    "boundary_review_required": "an overlap, gap, inversion or incoherent seam is pending",
    "boundary_review_invalid": "a boundary review does not match the supplied seam",
    "manifest_hash_mismatch": "the immutable manifest hash does not match its content",
    "baseline_changed": "the append/replace baseline is no longer current",
    "replacement_range_invalid": "a replacement does not name an exact fragment range",
    "replacement_version_reused": "a new fragment would silently reuse an old version",
}


class HistoryEditionError(PersistenceError):
    """A machine-classified history-edition contract failure."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        if code not in HISTORY_EDITION_ERROR_CODES:
            code = "invalid_input"
        self.code = code
        self.details = copy.deepcopy(details)
        super().__init__(f"history edition [{code}]: {message}")


# A short alias is useful to callers that use the product term rather than
# the implementation's full exception name.
EditionContractError = HistoryEditionError


def _fail(code: str, message: str, *, details: Any = None) -> None:
    raise HistoryEditionError(code, message, details=details)


def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _require_str(value: Any, field: str, *, code: str = "invalid_input") -> str:
    if not _is_str(value):
        _fail(code, f"{field} must be a non-empty string")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("invalid_input", f"{field} must be an array")
    return value


def _record_id(record: Any, field: str, *, fallback: str | None = None) -> str:
    if isinstance(record, str):
        return _require_str(record, field)
    if not isinstance(record, dict):
        _fail("invalid_input", f"{field} must contain an object or string id")
    value = record.get("id")
    if value is None:
        for key in ("paragraph_id", "phase_id", "conclusion_id", "evidence_id"):
            if key in record:
                value = record[key]
                break
    if value is None:
        value = fallback
    return _require_str(value, field, code="missing_reference")


def _records(value: Any, field: str) -> list[dict[str, Any]]:
    """Accept the list shape used by publications and a map shape in fixtures."""

    if value is None:
        return []
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                _fail("invalid_input", f"{field}[{index}] must be an object")
            result.append(copy.deepcopy(item))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            if not isinstance(item, dict):
                _fail("invalid_input", f"{field}[{key!r}] must be an object")
            record = copy.deepcopy(item)
            record.setdefault("id", key)
            result.append(record)
        return result
    _fail("invalid_input", f"{field} must be an array or object map")


def _record_map(value: Any, field: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(_records(value, field)):
        record_id = _record_id(record, f"{field}[{index}]")
        if record_id in result:
            _fail("mapping_incomplete", f"{field} contains duplicate id {record_id!r}")
        result[record_id] = record
    return result


def _scoped_value(record: Mapping[str, Any], expected_version: str, field: str) -> None:
    """Reject an input that explicitly claims a different fragment owner."""

    for key in ("fragment_version", "source_fragment_version"):
        if key in record and record[key] != expected_version:
            _fail(
                "cross_fragment_reference",
                f"{field} names fragment {record[key]!r}, expected {expected_version!r}",
            )
    source = record.get("source")
    if isinstance(source, dict) and "fragment_version" in source:
        if source["fragment_version"] != expected_version:
            _fail(
                "cross_fragment_reference",
                f"{field}.source names fragment {source['fragment_version']!r}, expected {expected_version!r}",
            )


def _fragment_version(fragment: Mapping[str, Any]) -> str:
    value = fragment.get("fragment_version", fragment.get("publication_version"))
    return _require_str(value, "fragment_version")


def _publication_id(fragment: Mapping[str, Any], version: str) -> str:
    return _require_str(fragment.get("publication_id", version), "publication_id")


def _published(fragment: Mapping[str, Any]) -> bool:
    return (
        fragment.get("publication_status") == PUBLISHED_STATUS
        or fragment.get("status") == PUBLISHED_STATUS
        or fragment.get("published") is True
    )


def _coverage(fragment: Mapping[str, Any], version: str) -> dict[str, Any]:
    raw = fragment.get("coverage")
    if not isinstance(raw, dict):
        _fail(
            "mapping_incomplete",
            f"fragment {version!r} requires explicit coverage start/end; years are not an ordering key",
        )
    scope = raw.get("scope", raw.get("scope_id", raw.get("stream_id")))
    scope = _require_str(scope, f"fragment {version}.coverage.scope")
    start, end = raw.get("start"), raw.get("end")
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        _fail(
            "mapping_incomplete",
            f"fragment {version!r}.coverage must be a non-empty half-open numeric range",
        )
    result = {"scope": scope, "start": start, "end": end}
    for key in ("start_anchor", "end_anchor"):
        if key in raw:
            result[key] = _require_str(raw[key], f"fragment {version}.coverage.{key}")
    # A range has explicit source geometry.  These fields are copied but never
    # used to invent a date or reorder a supplied fragment list.
    return result


def _content_hash(fragment: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(fragment))
    for key in ("content_sha256", "manifest_sha256", "edition_version"):
        payload.pop(key, None)
    try:
        return sha256_json(payload)
    except (TypeError, ValueError) as exc:
        _fail("invalid_input", f"fragment is not canonical JSON: {exc}")


def fragment_content_hash(fragment: Mapping[str, Any]) -> str:
    """Return the content hash recorded for a published fragment."""

    if not isinstance(fragment, dict):
        _fail("invalid_input", "fragment must be an object")
    return _content_hash(fragment)


def derive_scoped_id(kind: str, fragment_version: str, local_id: str) -> str:
    """Derive a stable ID from both its kind and its owning fragment.

    The fragment version is intentionally part of the input.  Therefore two
    fragments may both have ``p0``/``phase0``/``c0`` without colliding.
    """

    kind = _require_str(kind, "kind")
    fragment_version = _require_str(fragment_version, "fragment_version")
    local_id = _require_str(local_id, "local_id")
    prefix = {"paragraph": "hp", "phase": "hphase", "conclusion": "hcon", "event": "hevent"}.get(kind)
    if prefix is None:
        _fail("invalid_input", f"unsupported scoped id kind {kind!r}")
    return f"{prefix}_{sha256_json([kind, fragment_version, local_id])[:24]}"


def derive_global_paragraph_id(fragment_version: str, paragraph_id: str) -> str:
    """Derive the public ``hp_ID`` from a fragment version and local ID."""

    return derive_scoped_id("paragraph", fragment_version, paragraph_id)


def derive_global_phase_id(fragment_version: str, phase_id: str) -> str:
    return derive_scoped_id("phase", fragment_version, phase_id)


def derive_global_conclusion_id(fragment_version: str, conclusion_id: str) -> str:
    return derive_scoped_id("conclusion", fragment_version, conclusion_id)


def _source_locator(fragment_version: str, local_id: str, *, field: str = "id") -> dict[str, str]:
    return {"fragment_version": fragment_version, field: local_id}


def _normalise_phase_map(fragment: Mapping[str, Any], paragraphs: list[dict[str, Any]], conclusions: Mapping[str, Any], version: str) -> dict[str, dict[str, Any]]:
    raw = fragment.get("phases")
    phase_records = _records(raw, f"fragment {version}.phases") if raw is not None else []
    if not phase_records:
        seen: list[str] = []
        for paragraph in paragraphs:
            phase_id = paragraph.get("phase_id")
            if _is_str(phase_id) and phase_id not in seen:
                seen.append(phase_id)
        for conclusion in conclusions.values():
            for phase_id in conclusion.get("phase_ids", []) or []:
                if _is_str(phase_id) and phase_id not in seen:
                    seen.append(phase_id)
        phase_records = [{"id": phase_id} for phase_id in seen]
    result: dict[str, dict[str, Any]] = {}
    for index, phase in enumerate(phase_records):
        _scoped_value(phase, version, f"fragment {version}.phases[{index}]")
        phase_id = _record_id(phase, f"fragment {version}.phases[{index}]")
        if phase_id in result:
            _fail("mapping_incomplete", f"fragment {version!r} has duplicate phase {phase_id!r}")
        result[phase_id] = phase
    return result


def _normalise_evidence(fragment: Mapping[str, Any], version: str, publication_id: str) -> dict[str, dict[str, Any]]:
    result = _record_map(fragment.get("evidence"), f"fragment {version}.evidence")
    for evidence_id, evidence in result.items():
        _scoped_value(evidence, version, f"fragment {version}.evidence[{evidence_id}]")
        evidence_publication = evidence.get("publication_id")
        if evidence_publication is not None and evidence_publication != publication_id:
            _fail(
                "cross_fragment_reference",
                f"evidence {evidence_id!r} belongs to publication {evidence_publication!r}, not {publication_id!r}",
            )
    return result


def _evidence_id(value: Any, field: str) -> str:
    if isinstance(value, str):
        return _require_str(value, field)
    if isinstance(value, dict):
        return _record_id(value, field)
    _fail("invalid_input", f"{field} must be an evidence id or object")


def _phase_ids(value: Any, field: str) -> list[str]:
    values = _require_list(value, field)
    result = []
    for index, item in enumerate(values):
        result.append(_require_str(item, f"{field}[{index}]"))
    if len(set(result)) != len(result):
        _fail("mapping_incomplete", f"{field} contains duplicate phase references")
    return result


def _normalise_fragment(fragment: Any) -> dict[str, Any]:
    if not isinstance(fragment, dict):
        _fail("invalid_input", "each selected fragment must be an object")
    version = _fragment_version(fragment)
    if not _published(fragment):
        _fail("fragment_not_published", f"fragment {version!r} is not published")
    publication_id = _publication_id(fragment, version)
    coverage = _coverage(fragment, version)
    paragraphs = _records(fragment.get("paragraphs"), f"fragment {version}.paragraphs")
    if not paragraphs:
        _fail("mapping_incomplete", f"fragment {version!r} has no paragraphs")
    if len(paragraphs) > MAX_FRAGMENT_PARAGRAPHS:
        _fail(
            "fragment_capacity_exceeded",
            f"fragment {version!r} has {len(paragraphs)} paragraphs; maximum is {MAX_FRAGMENT_PARAGRAPHS}",
        )
    paragraph_map: dict[str, dict[str, Any]] = {}
    ordinals: list[int] = []
    for index, paragraph in enumerate(paragraphs):
        _scoped_value(paragraph, version, f"fragment {version}.paragraphs[{index}]")
        paragraph_id = _record_id(paragraph, f"fragment {version}.paragraphs[{index}]")
        if paragraph_id in paragraph_map:
            _fail("mapping_incomplete", f"fragment {version!r} has duplicate paragraph {paragraph_id!r}")
        ordinal = paragraph.get("ordinal", index)
        if type(ordinal) is not int or ordinal != index:
            _fail(
                "local_order_changed",
                f"fragment {version!r} paragraph {paragraph_id!r} has ordinal {ordinal!r}, expected {index}",
            )
        ordinals.append(ordinal)
        paragraph_map[paragraph_id] = paragraph
    if ordinals != list(range(len(paragraphs))):  # defensive for future changes
        _fail("local_order_changed", f"fragment {version!r} paragraph ordinals are not contiguous")

    conclusions = _record_map(fragment.get("conclusions"), f"fragment {version}.conclusions")
    evidence = _normalise_evidence(fragment, version, publication_id)
    phases = _normalise_phase_map(fragment, paragraphs, conclusions, version)

    for conclusion_id, conclusion in conclusions.items():
        _scoped_value(conclusion, version, f"fragment {version}.conclusions[{conclusion_id}]")
        phase_ids = _phase_ids(conclusion.get("phase_ids", []), f"fragment {version}.conclusions[{conclusion_id}].phase_ids")
        if not phase_ids:
            _fail("mapping_incomplete", f"conclusion {conclusion_id!r} has no phase scope")
        missing = [phase_id for phase_id in phase_ids if phase_id not in phases]
        if missing:
            _fail("missing_reference", f"conclusion {conclusion_id!r} references missing phases {missing}")
        evidence_values = _require_list(conclusion.get("evidence", []), f"fragment {version}.conclusions[{conclusion_id}].evidence")
        if not evidence_values:
            _fail("mapping_incomplete", f"conclusion {conclusion_id!r} has no evidence")
        seen_evidence: set[str] = set()
        for index, evidence_ref in enumerate(evidence_values):
            evidence_id = _evidence_id(evidence_ref, f"fragment {version}.conclusions[{conclusion_id}].evidence[{index}]")
            if evidence_id in seen_evidence:
                _fail("mapping_incomplete", f"conclusion {conclusion_id!r} repeats evidence {evidence_id!r}")
            seen_evidence.add(evidence_id)
            if evidence_id not in evidence:
                _fail("missing_reference", f"conclusion {conclusion_id!r} references missing evidence {evidence_id!r}")

    for index, paragraph in enumerate(paragraphs):
        paragraph_id = _record_id(paragraph, f"fragment {version}.paragraphs[{index}]")
        phase_id = paragraph.get("phase_id")
        if not _is_str(phase_id) or phase_id not in phases:
            _fail("missing_reference", f"paragraph {paragraph_id!r} references missing phase {phase_id!r}")
        segments = _require_list(paragraph.get("segments", []), f"fragment {version}.paragraphs[{index}].segments")
        if not segments:
            _fail("mapping_incomplete", f"paragraph {paragraph_id!r} has no narrative segments")
        paragraph_conclusions: set[str] = set()
        for segment_index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                _fail("invalid_input", f"fragment {version}.paragraphs[{index}].segments[{segment_index}] must be an object")
            _scoped_value(segment, version, f"fragment {version}.paragraphs[{index}].segments[{segment_index}]")
            ids = _require_list(segment.get("conclusion_ids", []), f"fragment {version}.paragraphs[{index}].segments[{segment_index}].conclusion_ids")
            if not ids:
                _fail("mapping_incomplete", f"paragraph {paragraph_id!r} has a segment without conclusions")
            for conclusion_id in ids:
                conclusion_id = _require_str(conclusion_id, "conclusion_id")
                paragraph_conclusions.add(conclusion_id)
                if conclusion_id not in conclusions:
                    _fail("missing_reference", f"paragraph {paragraph_id!r} references missing conclusion {conclusion_id!r}")
                if phase_id not in conclusions[conclusion_id].get("phase_ids", []):
                    _fail(
                        "mapping_incomplete",
                        f"paragraph {paragraph_id!r} uses conclusion {conclusion_id!r} outside its phase",
                    )
            event_id = segment.get("event_id")
            if event_id is not None:
                event_id = _require_str(event_id, "event_id")
                if not any(conclusions[conclusion_id].get("event_id") == event_id for conclusion_id in paragraph_conclusions):
                    _fail(
                        "cross_fragment_reference",
                        f"paragraph {paragraph_id!r} event {event_id!r} is not owned by its local conclusions",
                    )
                if segment.get("fragment_version") not in (None, version):
                    _fail("cross_fragment_reference", f"paragraph {paragraph_id!r} event is cross-fragment")
        entities = paragraph.get("entities", [])
        if not isinstance(entities, list):
            _fail("invalid_input", f"paragraph {paragraph_id!r}.entities must be an array")
        for entity_index, entity in enumerate(entities):
            if not isinstance(entity, dict):
                _fail("invalid_input", f"paragraph {paragraph_id!r}.entities[{entity_index}] must be an object")
            _scoped_value(entity, version, f"paragraph {paragraph_id!r}.entities[{entity_index}]")
            states = entity.get("states", [])
            if not isinstance(states, list):
                _fail("invalid_input", f"paragraph {paragraph_id!r}.entities[{entity_index}].states must be an array")
            for state_index, state in enumerate(states):
                if not isinstance(state, dict):
                    _fail("invalid_input", f"paragraph {paragraph_id!r}.states[{state_index}] must be an object")
                _scoped_value(state, version, f"paragraph {paragraph_id!r}.states[{state_index}]")
                state_id = state.get("id", state.get("conclusion_id"))
                if not _is_str(state_id):
                    _fail("missing_reference", f"paragraph {paragraph_id!r} has a state without a conclusion id")
                if state_id not in conclusions:
                    _fail("cross_fragment_reference", f"paragraph {paragraph_id!r} state {state_id!r} is not local")
                if phase_id not in conclusions[state_id].get("phase_ids", []):
                    _fail("mapping_incomplete", f"paragraph {paragraph_id!r} state {state_id!r} is outside its phase")

    fragment_hash = _content_hash(fragment)
    supplied_hash = fragment.get("content_sha256")
    if supplied_hash is not None:
        if not isinstance(supplied_hash, str) or not SHA256_RE.fullmatch(supplied_hash) or supplied_hash != fragment_hash:
            _fail("mapping_incomplete", f"fragment {version!r} content_sha256 does not match its published content")
    return {
        "version": version,
        "publication_id": publication_id,
        "coverage": coverage,
        "content_sha256": fragment_hash,
        "fragment": copy.deepcopy(fragment),
        "paragraphs": paragraphs,
        "paragraph_map": paragraph_map,
        "phases": phases,
        "conclusions": conclusions,
        "evidence": evidence,
    }


def validate_published_fragment(fragment: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a private normalized view of one published fragment."""

    return _normalise_fragment(fragment)


def _fragment_ref(info: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fragment_version": info["version"],
        "publication_id": info["publication_id"],
        "content_sha256": info["content_sha256"],
        "paragraph_count": len(info["paragraphs"]),
        "coverage": copy.deepcopy(info["coverage"]),
    }


def _ensure_unique_fragments(infos: Sequence[Mapping[str, Any]]) -> None:
    versions: set[str] = set()
    publications: set[str] = set()
    for info in infos:
        version = info["version"]
        publication_id = info["publication_id"]
        if version in versions or publication_id in publications:
            _fail(
                "duplicate_fragment",
                f"fragment {version!r} or publication {publication_id!r} is selected more than once",
            )
        versions.add(version)
        publications.add(publication_id)


def _boundary_geometry(left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    left_coverage, right_coverage = left["coverage"], right["coverage"]
    if left_coverage["scope"] != right_coverage["scope"]:
        return "different_scope"
    if right_coverage["start"] < left_coverage["start"]:
        return "inversion"
    if right_coverage["start"] < left_coverage["end"]:
        return "overlap"
    if right_coverage["start"] > left_coverage["end"]:
        return "gap"
    return "contiguous"


def _boundary_key(review: Mapping[str, Any]) -> tuple[str, str]:
    left = review.get("left_fragment_version", review.get("left"))
    right = review.get("right_fragment_version", review.get("right"))
    return (_require_str(left, "boundary.left_fragment_version"), _require_str(right, "boundary.right_fragment_version"))


def _local_paragraph_ids(info: Mapping[str, Any]) -> set[str]:
    return set(info["paragraph_map"])


def _normalise_review_basis(review: Mapping[str, Any], left: Mapping[str, Any], right: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = review.get("review_basis", review.get("basis"))
    if not isinstance(raw, list) or not raw:
        _fail("boundary_review_invalid", "accepted seam requires non-empty review_basis")
    result: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            _fail("boundary_review_invalid", f"review_basis[{index}] must be an object")
        version = item.get("fragment_version", item.get("source_fragment_version"))
        paragraph_id = item.get("paragraph_id", item.get("id"))
        version = _require_str(version, f"review_basis[{index}].fragment_version")
        paragraph_id = _require_str(paragraph_id, f"review_basis[{index}].paragraph_id")
        if version == left["version"]:
            owner = left
        elif version == right["version"]:
            owner = right
        else:
            _fail("cross_fragment_reference", f"boundary basis names non-adjacent fragment {version!r}")
        if paragraph_id not in _local_paragraph_ids(owner):
            _fail("anchor_out_of_bounds", f"boundary basis paragraph {paragraph_id!r} is not in fragment {version!r}")
        result.append({"fragment_version": version, "paragraph_id": paragraph_id})
    return result


def inspect_boundaries(
    fragments: Sequence[Mapping[str, Any]],
    boundary_reviews: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return seam geometry without concatenating or accepting pending seams."""

    infos = [_normalise_fragment(fragment) for fragment in fragments]
    _ensure_unique_fragments(infos)
    reviews = {_boundary_key(review): review for review in (boundary_reviews or [])}
    result: list[dict[str, Any]] = []
    for left, right in zip(infos, infos[1:]):
        key = (left["version"], right["version"])
        geometry = _boundary_geometry(left, right)
        review = reviews.get(key)
        status = review.get("status") if review else "pending"
        result.append({
            "left_fragment_version": left["version"],
            "right_fragment_version": right["version"],
            "geometry": geometry,
            "status": status,
        })
    return result


def _validate_boundaries(
    infos: Sequence[Mapping[str, Any]],
    boundary_reviews: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    reviews = list(boundary_reviews or [])
    by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            _fail("boundary_review_invalid", "each boundary review must be an object")
        key = _boundary_key(review)
        if key in by_key:
            _fail("boundary_review_invalid", f"duplicate boundary review for {key[0]!r} → {key[1]!r}")
        by_key[key] = review
    expected_keys = set()
    result: list[dict[str, Any]] = []
    for left, right in zip(infos, infos[1:]):
        key = (left["version"], right["version"])
        expected_keys.add(key)
        review = by_key.get(key)
        if review is None:
            _fail("boundary_review_missing", f"no review for seam {key[0]!r} → {key[1]!r}")
        geometry = _boundary_geometry(left, right)
        if geometry != "contiguous":
            _fail(
                "boundary_review_required",
                f"seam {key[0]!r} → {key[1]!r} has {geometry} coverage and must remain pending",
            )
        declared = review.get("geometry", review.get("kind"))
        if declared is not None and declared != geometry and not (declared == "coherent" and geometry == "contiguous"):
            _fail("boundary_review_invalid", f"seam {key[0]!r} → {key[1]!r} is {geometry}, not {declared!r}")
        status = review.get("status")
        if status != "accepted":
            _fail(
                "boundary_review_required",
                f"seam {key[0]!r} → {key[1]!r} remains {status or 'pending'} ({geometry}); it cannot be auto-concatenated",
            )
        if review.get("coherent") is False or review.get("seam_status") in {"incoherent", "pending"}:
            _fail("boundary_review_required", f"seam {key[0]!r} → {key[1]!r} is not coherent")
        basis = _normalise_review_basis(review, left, right)
        result.append({
            "left_fragment_version": left["version"],
            "right_fragment_version": right["version"],
            "geometry": geometry,
            "status": "accepted",
            "review_basis": basis,
            "note": review.get("note", ""),
        })
    extras = set(by_key) - expected_keys
    if extras:
        _fail("boundary_review_invalid", f"review names a non-adjacent seam {sorted(extras)!r}")
    return result


def _navigation_input(
    infos: Sequence[Mapping[str, Any]], navigation: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if navigation is None:
        # A fragment's already-reviewed entry_points are the only implicit
        # source.  We never turn every paragraph or event into a navigation
        # entry and never sort by year.
        raw_entries: list[dict[str, Any]] = []
        for info in infos:
            for entry in info["fragment"].get("entry_points", []) or []:
                if not isinstance(entry, dict):
                    _fail("invalid_input", f"fragment {info['version']!r}.entry_points contains a non-object")
                raw_entries.append({**entry, "fragment_version": info["version"]})
    else:
        raw_entries = []
        if not isinstance(navigation, list):
            _fail("invalid_input", "navigation must be an array")
        raw_entries = copy.deepcopy(navigation)
    if len(raw_entries) > MAX_NAVIGATION_ENTRIES:
        _fail("mapping_incomplete", f"curated navigation has more than {MAX_NAVIGATION_ENTRIES} entries")
    return raw_entries


def _compile_navigation(
    infos: Sequence[Mapping[str, Any]], navigation: Sequence[Mapping[str, Any]] | None,
    paragraph_ids: Mapping[tuple[str, str], str],
    conclusion_ids: Mapping[tuple[str, str], str],
) -> list[dict[str, Any]]:
    by_version = {info["version"]: info for info in infos}
    entries = _navigation_input(infos, navigation)
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    previous_ordinal = -1
    global_ordinals = {
        key: ordinal
        for ordinal, key in enumerate(
            (key for info in infos for key in ((info["version"], paragraph_id) for paragraph_id in info["paragraph_map"]))
        )
    }
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            _fail("invalid_input", f"navigation[{index}] must be an object")
        version = entry.get("fragment_version", entry.get("source_fragment_version"))
        version = _require_str(version, f"navigation[{index}].fragment_version")
        info = by_version.get(version)
        if info is None:
            _fail("cross_fragment_reference", f"navigation[{index}] names unknown fragment {version!r}")
        paragraph_id = entry.get("paragraph_id")
        paragraph_id = _require_str(paragraph_id, f"navigation[{index}].paragraph_id")
        if paragraph_id not in info["paragraph_map"]:
            _fail("anchor_out_of_bounds", f"navigation[{index}] paragraph {paragraph_id!r} is outside fragment {version!r}")
        kind = entry.get("kind")
        if kind not in {"event", "period"}:
            _fail("invalid_input", f"navigation[{index}].kind must be event or period")
        global_paragraph_id = paragraph_ids[(version, paragraph_id)]
        key = (kind, global_paragraph_id)
        if key in seen:
            _fail("mapping_incomplete", f"navigation repeats {global_paragraph_id!r}")
        seen.add(key)
        ordinal = global_ordinals[(version, paragraph_id)]
        if ordinal < previous_ordinal:
            _fail("local_order_changed", "curated navigation must follow the supplied paragraph order")
        previous_ordinal = ordinal
        event_id = entry.get("event_id")
        if kind == "event":
            event_id = _require_str(event_id, f"navigation[{index}].event_id")
            paragraph = info["paragraph_map"][paragraph_id]
            matches = [
                segment for segment in paragraph.get("segments", [])
                if isinstance(segment, dict)
                and segment.get("event_id") == event_id
                and segment.get("event_relation") == "current"
            ]
            if not matches:
                _fail("entry_unreachable", f"event entry {event_id!r} does not reach a current event in {paragraph_id!r}")
        elif event_id is not None:
            _fail("entry_unreachable", f"period entry {global_paragraph_id!r} cannot carry an event id")
        output = {
            "kind": kind,
            "label": _require_str(entry.get("label"), f"navigation[{index}].label"),
            "reason": _require_str(entry.get("reason"), f"navigation[{index}].reason"),
            "paragraph_id": global_paragraph_id,
            "source": _source_locator(version, paragraph_id, field="paragraph_id"),
            "fragment_version": version,
        }
        if event_id is not None:
            output["event_id"] = derive_scoped_id("event", version, event_id)
            output["source_event_id"] = event_id
        result.append(output)
    return result


def _manifest_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(manifest))
    payload.pop("version", None)
    payload.pop("manifest_sha256", None)
    return payload


def _manifest_hash(manifest: Mapping[str, Any]) -> str:
    return sha256_json(_manifest_payload(manifest))


def _compile_mappings(infos: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str], str], dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    paragraphs: list[dict[str, Any]] = []
    phases: list[dict[str, Any]] = []
    conclusions: list[dict[str, Any]] = []
    paragraph_ids: dict[tuple[str, str], str] = {}
    phase_ids: dict[tuple[str, str], str] = {}
    conclusion_ids: dict[tuple[str, str], str] = {}

    global_ordinal = 0
    for info in infos:
        version = info["version"]
        for phase_id, phase in info["phases"].items():
            global_id = derive_global_phase_id(version, phase_id)
            phase_ids[(version, phase_id)] = global_id
            mapped = {
                "phase_id": global_id,
                "id": global_id,
                "source": _source_locator(version, phase_id, field="phase_id"),
                "fragment_version": version,
                "source_phase_id": phase_id,
            }
            for key in ("label", "year", "period", "relation_to_previous"):
                if key in phase:
                    # None is meaningful for an unknown year and remains None.
                    mapped[key] = copy.deepcopy(phase[key])
            phases.append(mapped)
        for conclusion_id in info["conclusions"]:
            global_id = derive_global_conclusion_id(version, conclusion_id)
            conclusion_ids[(version, conclusion_id)] = global_id

    for info in infos:
        version = info["version"]
        for conclusion_id, conclusion in info["conclusions"].items():
            global_id = conclusion_ids[(version, conclusion_id)]
            mapped_evidence = []
            for evidence_ref in conclusion.get("evidence", []):
                evidence_id = _evidence_id(evidence_ref, "conclusion.evidence")
                mapped_evidence.append({
                    "fragment_version": version,
                    "evidence_id": evidence_id,
                    "source": _source_locator(version, evidence_id, field="evidence_id"),
                })
            mapped = {
                "conclusion_id": global_id,
                "id": global_id,
                "source": _source_locator(version, conclusion_id, field="conclusion_id"),
                "fragment_version": version,
                "source_conclusion_id": conclusion_id,
                "phase_ids": [phase_ids[(version, phase_id)] for phase_id in conclusion.get("phase_ids", [])],
                "source_phase_ids": list(conclusion.get("phase_ids", [])),
                "evidence": mapped_evidence,
            }
            if conclusion.get("event_id") is not None:
                event_id = _require_str(conclusion["event_id"], f"conclusion {conclusion_id}.event_id")
                mapped["event_id"] = derive_scoped_id("event", version, event_id)
                mapped["source_event_id"] = event_id
            conclusions.append(mapped)

        for index, paragraph in enumerate(info["paragraphs"]):
            paragraph_id = _record_id(paragraph, f"fragment {version}.paragraphs[{index}]")
            global_id = derive_global_paragraph_id(version, paragraph_id)
            paragraph_ids[(version, paragraph_id)] = global_id
            phase_id = paragraph["phase_id"]
            source_conclusions: list[str] = []
            for segment in paragraph.get("segments", []):
                source_conclusions.extend(segment.get("conclusion_ids", []))
            # Preserve first-reference order while making the mapping complete.
            source_conclusions = list(dict.fromkeys(source_conclusions))
            paragraphs.append({
                "paragraph_id": global_id,
                "id": global_id,
                "ordinal": global_ordinal,
                "source": _source_locator(version, paragraph_id, field="paragraph_id"),
                "fragment_version": version,
                "source_paragraph_id": paragraph_id,
                "source_ordinal": paragraph.get("ordinal", index),
                "phase_id": phase_ids[(version, phase_id)],
                "source_phase_id": phase_id,
                "conclusion_ids": [conclusion_ids[(version, conclusion_id)] for conclusion_id in source_conclusions],
                "source_conclusion_ids": source_conclusions,
                "content_ref": _source_locator(version, paragraph_id, field="paragraph_id"),
            })
            global_ordinal += 1
    return paragraphs, phases, conclusions, paragraph_ids, phase_ids, conclusion_ids


def compile_history_edition(
    fragments: Sequence[Mapping[str, Any]],
    *,
    boundary_reviews: Sequence[Mapping[str, Any]] | None = None,
    navigation: Sequence[Mapping[str, Any]] | None = None,
    lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a deterministic edition from ordered published fragments.

    ``fragments`` order is authoritative.  The function never sorts by year,
    fills unknown dates, or auto-resolves an overlap/gap/inversion.  A valid
    edition requires an accepted, evidence-backed review for each contiguous
    seam.
    """

    if not isinstance(fragments, (list, tuple)) or not fragments:
        _fail("invalid_input", "fragments must be a non-empty ordered array")
    infos = [_normalise_fragment(fragment) for fragment in fragments]
    _ensure_unique_fragments(infos)
    boundaries = _validate_boundaries(infos, boundary_reviews)
    paragraphs, phases, conclusions, paragraph_ids, _phase_ids, conclusion_ids = _compile_mappings(infos)
    nav = _compile_navigation(infos, navigation, paragraph_ids, conclusion_ids)
    fragment_refs = [_fragment_ref(info) for info in infos]
    content_sha256 = sha256_json({
        "fragments": [ref["content_sha256"] for ref in fragment_refs],
        "paragraphs": paragraphs,
        "phases": phases,
        "conclusions": conclusions,
        "navigation": nav,
    })
    manifest: dict[str, Any] = {
        "schema": HISTORY_EDITION_SCHEMA,
        "contract_version": HISTORY_EDITION_VERSION,
        "version": "",
        "fragments": fragment_refs,
        "boundaries": boundaries,
        "paragraphs": paragraphs,
        "phases": phases,
        "conclusions": conclusions,
        "navigation": nav,
        "paragraph_count": len(paragraphs),
        "fragment_count": len(fragment_refs),
        "content_sha256": content_sha256,
    }
    if lineage is not None:
        if not isinstance(lineage, dict):
            _fail("invalid_input", "lineage must be an object")
        manifest["lineage"] = copy.deepcopy(lineage)
    version = _manifest_hash(manifest)
    manifest["version"] = version
    manifest["manifest_sha256"] = version
    return manifest


def validate_history_edition(
    edition: Mapping[str, Any],
    fragments: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate an immutable manifest, optionally against current fragments."""

    if not isinstance(edition, dict):
        _fail("invalid_input", "edition must be an object")
    if edition.get("schema") != HISTORY_EDITION_SCHEMA or edition.get("contract_version") != HISTORY_EDITION_VERSION:
        _fail("invalid_input", "unsupported history-edition schema/version")
    for field in ("version", "manifest_sha256", "content_sha256"):
        if not isinstance(edition.get(field), str) or not SHA256_RE.fullmatch(edition[field]):
            _fail("manifest_hash_mismatch", f"edition.{field} must be a SHA-256")
    expected_hash = _manifest_hash(edition)
    if edition["manifest_sha256"] != expected_hash or edition["version"] != expected_hash:
        _fail("manifest_hash_mismatch", "edition version/manifest_sha256 does not match its immutable payload")
    fragment_refs = _require_list(edition.get("fragments"), "edition.fragments")
    if not fragment_refs:
        _fail("mapping_incomplete", "edition has no fragment references")
    versions: set[str] = set()
    publications: set[str] = set()
    paragraph_ids: set[str] = set()
    phase_ids: set[str] = set()
    conclusion_ids: set[str] = set()
    source_paragraphs: set[tuple[str, str]] = set()
    for index, fragment in enumerate(fragment_refs):
        if not isinstance(fragment, dict):
            _fail("invalid_input", f"edition.fragments[{index}] must be an object")
        version = _require_str(fragment.get("fragment_version"), f"edition.fragments[{index}].fragment_version")
        publication_id = _require_str(fragment.get("publication_id"), f"edition.fragments[{index}].publication_id")
        if version in versions or publication_id in publications:
            _fail("duplicate_fragment", f"edition repeats fragment {version!r} or publication {publication_id!r}")
        versions.add(version)
        publications.add(publication_id)
        count = fragment.get("paragraph_count")
        if type(count) is not int or count < 1 or count > MAX_FRAGMENT_PARAGRAPHS:
            _fail("fragment_capacity_exceeded", f"edition fragment {version!r} has invalid paragraph_count")
        coverage = fragment.get("coverage")
        if not isinstance(coverage, dict):
            _fail("mapping_incomplete", f"edition fragment {version!r} has no coverage")
        if not isinstance(fragment.get("content_sha256"), str) or not SHA256_RE.fullmatch(fragment["content_sha256"]):
            _fail("manifest_hash_mismatch", f"edition fragment {version!r} has an invalid content hash")
    expected_paragraph_count = sum(item["paragraph_count"] for item in fragment_refs)
    if edition.get("paragraph_count") != expected_paragraph_count:
        _fail("mapping_incomplete", "edition paragraph_count does not cover every fragment paragraph")
    if type(edition.get("paragraph_count")) is not int or edition["paragraph_count"] != len(edition.get("paragraphs", [])):
        _fail("mapping_incomplete", "edition paragraph_count does not cover paragraph mapping")
    if type(edition.get("fragment_count")) is not int or edition["fragment_count"] != len(fragment_refs):
        _fail("mapping_incomplete", "edition fragment_count does not cover fragment references")
    for index, paragraph in enumerate(_require_list(edition.get("paragraphs"), "edition.paragraphs")):
        if not isinstance(paragraph, dict):
            _fail("invalid_input", f"edition.paragraphs[{index}] must be an object")
        global_id = _require_str(paragraph.get("paragraph_id"), f"edition.paragraphs[{index}].paragraph_id")
        if global_id in paragraph_ids:
            _fail("mapping_incomplete", f"edition repeats global paragraph id {global_id!r}")
        paragraph_ids.add(global_id)
        source = paragraph.get("source")
        if not isinstance(source, dict):
            _fail("mapping_incomplete", f"edition.paragraphs[{index}] has no source locator")
        version = _require_str(source.get("fragment_version"), "paragraph.source.fragment_version")
        local_id = _require_str(source.get("paragraph_id"), "paragraph.source.paragraph_id")
        if version not in versions:
            _fail("cross_fragment_reference", f"paragraph {global_id!r} names unknown fragment {version!r}")
        if global_id != derive_global_paragraph_id(version, local_id):
            _fail("mapping_incomplete", f"paragraph {global_id!r} is not the derived scoped id")
        if paragraph.get("fragment_version", version) != version:
            _fail("cross_fragment_reference", f"paragraph {global_id!r} has a different top-level fragment owner")
        if paragraph.get("content_ref") != source:
            _fail("mapping_incomplete", f"paragraph {global_id!r} content_ref is not its source locator")
        if paragraph.get("ordinal") != index or paragraph.get("source_ordinal") is None:
            _fail("local_order_changed", f"edition paragraph {global_id!r} is not in global order")
        source_paragraphs.add((version, local_id))
        phase_id = _require_str(paragraph.get("phase_id"), f"edition.paragraphs[{index}].phase_id")
        if phase_id not in phase_ids and not any(
            isinstance(item, dict) and item.get("phase_id") == phase_id for item in edition.get("phases", [])
        ):
            _fail("missing_reference", f"paragraph {global_id!r} references missing global phase {phase_id!r}")
    for index, phase in enumerate(_require_list(edition.get("phases"), "edition.phases")):
        if not isinstance(phase, dict):
            _fail("invalid_input", f"edition.phases[{index}] must be an object")
        global_id = _require_str(phase.get("phase_id"), f"edition.phases[{index}].phase_id")
        if global_id in phase_ids:
            _fail("mapping_incomplete", f"edition repeats global phase id {global_id!r}")
        phase_ids.add(global_id)
        source = phase.get("source")
        if not isinstance(source, dict):
            _fail("mapping_incomplete", f"edition.phases[{index}] has no source locator")
        version = _require_str(source.get("fragment_version"), "phase.source.fragment_version")
        local_id = _require_str(source.get("phase_id"), "phase.source.phase_id")
        if version not in versions or global_id != derive_global_phase_id(version, local_id):
            _fail("mapping_incomplete", f"phase {global_id!r} is not a complete scoped mapping")
        if phase.get("fragment_version", version) != version:
            _fail("cross_fragment_reference", f"phase {global_id!r} has a different top-level fragment owner")
    for index, conclusion in enumerate(_require_list(edition.get("conclusions"), "edition.conclusions")):
        if not isinstance(conclusion, dict):
            _fail("invalid_input", f"edition.conclusions[{index}] must be an object")
        global_id = _require_str(conclusion.get("conclusion_id"), f"edition.conclusions[{index}].conclusion_id")
        if global_id in conclusion_ids:
            _fail("mapping_incomplete", f"edition repeats global conclusion id {global_id!r}")
        conclusion_ids.add(global_id)
        source = conclusion.get("source")
        if not isinstance(source, dict):
            _fail("mapping_incomplete", f"edition.conclusions[{index}] has no source locator")
        version = _require_str(source.get("fragment_version"), "conclusion.source.fragment_version")
        local_id = _require_str(source.get("conclusion_id"), "conclusion.source.conclusion_id")
        if version not in versions or global_id != derive_global_conclusion_id(version, local_id):
            _fail("mapping_incomplete", f"conclusion {global_id!r} is not a complete scoped mapping")
        if conclusion.get("fragment_version", version) != version:
            _fail("cross_fragment_reference", f"conclusion {global_id!r} has a different top-level fragment owner")
        for phase_id in _require_list(conclusion.get("phase_ids"), f"conclusion {global_id}.phase_ids"):
            if phase_id not in phase_ids:
                _fail("missing_reference", f"conclusion {global_id!r} references missing phase {phase_id!r}")
        for evidence in _require_list(conclusion.get("evidence"), f"conclusion {global_id}.evidence"):
            if not isinstance(evidence, dict) or evidence.get("fragment_version") != version:
                _fail("cross_fragment_reference", f"conclusion {global_id!r} has cross-fragment evidence")
            _require_str(evidence.get("evidence_id"), f"conclusion {global_id}.evidence_id")
    # The paragraph phase check is repeated after the phase map is collected.
    for paragraph in edition["paragraphs"]:
        if paragraph["phase_id"] not in phase_ids:
            _fail("missing_reference", f"paragraph {paragraph['paragraph_id']!r} references missing phase")
        paragraph_conclusion_ids = _require_list(
            paragraph.get("conclusion_ids"),
            f"paragraph {paragraph['paragraph_id']}.conclusion_ids",
        )
        if not paragraph_conclusion_ids:
            _fail("mapping_incomplete", f"paragraph {paragraph['paragraph_id']!r} has no conclusion mapping")
        for conclusion_id in paragraph_conclusion_ids:
            if conclusion_id not in conclusion_ids:
                _fail("missing_reference", f"paragraph {paragraph['paragraph_id']!r} references missing conclusion")
    expected_content_hash = sha256_json({
        "fragments": [item["content_sha256"] for item in fragment_refs],
        "paragraphs": edition["paragraphs"],
        "phases": edition["phases"],
        "conclusions": edition["conclusions"],
        "navigation": edition["navigation"],
    })
    if edition["content_sha256"] != expected_content_hash:
        _fail("manifest_hash_mismatch", "edition content_sha256 does not match its mappings")
    navigation = _require_list(edition.get("navigation"), "edition.navigation")
    if len(navigation) > MAX_NAVIGATION_ENTRIES:
        _fail("mapping_incomplete", "edition navigation exceeds its curated limit")
    for index, entry in enumerate(navigation):
        if not isinstance(entry, dict) or entry.get("paragraph_id") not in paragraph_ids:
            _fail("entry_unreachable", f"edition.navigation[{index}] does not reach a paragraph")
        source = entry.get("source")
        if not isinstance(source, dict) or (source.get("fragment_version"), source.get("paragraph_id")) not in source_paragraphs:
            _fail("anchor_out_of_bounds", f"edition.navigation[{index}] has an invalid source anchor")
    boundaries = _require_list(edition.get("boundaries"), "edition.boundaries")
    if len(boundaries) != max(0, len(fragment_refs) - 1):
        _fail("boundary_review_missing", "edition does not record every adjacent seam")
    for index, boundary in enumerate(boundaries):
        if not isinstance(boundary, dict) or boundary.get("status") != "accepted" or boundary.get("geometry") != "contiguous":
            _fail("boundary_review_required", f"edition.boundaries[{index}] is not an accepted contiguous seam")
        left_ref, right_ref = fragment_refs[index], fragment_refs[index + 1]
        if (
            boundary.get("left_fragment_version") != left_ref["fragment_version"]
            or boundary.get("right_fragment_version") != right_ref["fragment_version"]
        ):
            _fail("boundary_review_invalid", f"edition.boundaries[{index}] does not name adjacent fragments")
        left_coverage, right_coverage = left_ref["coverage"], right_ref["coverage"]
        if (
            left_coverage.get("scope") != right_coverage.get("scope")
            or left_coverage.get("end") != right_coverage.get("start")
        ):
            _fail("boundary_review_required", f"edition.boundaries[{index}] is not a contiguous coverage seam")
        for basis in _require_list(boundary.get("review_basis"), f"edition.boundaries[{index}].review_basis"):
            if not isinstance(basis, dict) or (basis.get("fragment_version"), basis.get("paragraph_id")) not in source_paragraphs:
                _fail("anchor_out_of_bounds", f"edition.boundaries[{index}] has an invalid review anchor")
    if fragments is not None:
        infos = [_normalise_fragment(fragment) for fragment in fragments]
        _ensure_unique_fragments(infos)
        if [info["version"] for info in infos] != [item["fragment_version"] for item in fragment_refs]:
            _fail("mapping_incomplete", "provided fragments do not match edition order")
        for info, ref in zip(infos, fragment_refs):
            if info["content_sha256"] != ref.get("content_sha256"):
                _fail("manifest_hash_mismatch", f"fragment {info['version']!r} content changed under an immutable edition")
    return copy.deepcopy(dict(edition))


def _baseline_hash(edition: Mapping[str, Any]) -> str:
    value = edition.get("manifest_sha256", edition.get("version"))
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail("baseline_changed", "baseline edition has no valid manifest hash")
    return value


def _check_baseline(previous: Mapping[str, Any], supplied: str) -> None:
    expected = _baseline_hash(previous)
    if supplied != expected:
        _fail("baseline_changed", f"expected baseline {expected}, received {supplied}")
    validate_history_edition(previous)


def _versions(edition: Mapping[str, Any]) -> list[str]:
    return [item["fragment_version"] for item in _require_list(edition.get("fragments"), "edition.fragments")]


def append_history_edition(
    previous_edition: Mapping[str, Any],
    fragments: Sequence[Mapping[str, Any]],
    *,
    baseline_manifest_sha256: str,
    boundary_reviews: Sequence[Mapping[str, Any]] | None = None,
    navigation: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new immutable edition by appending to an exact old snapshot.

    ``fragments`` is the complete ordered post-append snapshot, not just a
    delta.  This makes the caller's read/compile/write transaction explicit and
    prevents an omitted old fragment from being silently dropped.
    """

    _check_baseline(previous_edition, baseline_manifest_sha256)
    incoming_versions = [_fragment_version(fragment) for fragment in fragments]
    old_versions = _versions(previous_edition)
    if incoming_versions[: len(old_versions)] != old_versions or len(incoming_versions) <= len(old_versions):
        _fail("mapping_incomplete", "append snapshot must preserve every old fragment and add at least one new fragment")
    result = compile_history_edition(
        fragments,
        boundary_reviews=boundary_reviews,
        navigation=navigation,
        lineage={"operation": "append", "parent_version": previous_edition["version"], "baseline_manifest_sha256": baseline_manifest_sha256},
    )
    if result["fragments"][: len(previous_edition["fragments"])] != previous_edition["fragments"]:
        _fail("replacement_version_reused", "append would alter an existing fragment reference")
    return result


def _replacement_indexes(previous: Mapping[str, Any], replacement_range: Mapping[str, Any]) -> tuple[int, int]:
    if not isinstance(replacement_range, dict):
        _fail("replacement_range_invalid", "replacement_range must name exact fragment versions")
    start_version = replacement_range.get("start_fragment_version")
    end_version = replacement_range.get("end_fragment_version")
    if not _is_str(start_version) or not _is_str(end_version):
        _fail("replacement_range_invalid", "replacement_range requires start_fragment_version and end_fragment_version")
    versions = _versions(previous)
    try:
        start, end = versions.index(start_version), versions.index(end_version)
    except ValueError as exc:
        _fail("replacement_range_invalid", "replacement range names an unknown old fragment")
    if start > end:
        _fail("replacement_range_invalid", "replacement range is reversed")
    return start, end


def replace_history_edition(
    previous_edition: Mapping[str, Any],
    fragments: Sequence[Mapping[str, Any]],
    *,
    replacement_range: Mapping[str, Any],
    baseline_manifest_sha256: str,
    boundary_reviews: Sequence[Mapping[str, Any]] | None = None,
    navigation: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new edition replacing an exact old fragment range.

    The post-replacement ``fragments`` value is a complete ordered snapshot.
    Prefix and suffix references must be byte-for-byte unchanged; the range is
    addressed by fragment versions, never by a year-only guess.
    """

    _check_baseline(previous_edition, baseline_manifest_sha256)
    start, end = _replacement_indexes(previous_edition, replacement_range)
    new_versions = [_fragment_version(fragment) for fragment in fragments]
    old_versions = _versions(previous_edition)
    if not new_versions:
        _fail("replacement_range_invalid", "replacement snapshot cannot be empty")
    if new_versions[:start] != old_versions[:start] or new_versions[len(new_versions) - (len(old_versions) - end - 1):] != old_versions[end + 1:]:
        _fail("replacement_range_invalid", "replacement changed a fragment outside the exact range")
    replaced_versions = set(old_versions[start : end + 1])
    replacement_versions = set(new_versions) - set(old_versions[:start]) - set(old_versions[end + 1:])
    if not replacement_versions or replaced_versions & replacement_versions:
        _fail("replacement_version_reused", "replacement must use new fragment versions")
    result = compile_history_edition(
        fragments,
        boundary_reviews=boundary_reviews,
        navigation=navigation,
        lineage={"operation": "replace", "parent_version": previous_edition["version"], "baseline_manifest_sha256": baseline_manifest_sha256, "replacement_range": copy.deepcopy(dict(replacement_range))},
    )
    if result["fragments"][:start] != previous_edition["fragments"][:start] or result["fragments"][len(result["fragments"]) - (len(previous_edition["fragments"]) - end - 1):] != previous_edition["fragments"][end + 1:]:
        _fail("replacement_range_invalid", "replacement altered immutable prefix/suffix references")
    return result


# Concise aliases used by T10/T11 planning examples and by callers that use
# "manifest"/"hp" terminology for the same pure operations.
EDITION_ERROR_CODES = HISTORY_EDITION_ERROR_CODES
MAX_PARAGRAPHS_PER_FRAGMENT = MAX_FRAGMENT_PARAGRAPHS
compile_edition = compile_history_edition
build_history_edition = compile_history_edition
build_edition_manifest = compile_history_edition
validate_edition = validate_history_edition
append_edition = append_history_edition
replace_edition = replace_history_edition
derive_hp_id = derive_global_paragraph_id
validate_fragment = validate_published_fragment


def contract_fixture(*, paragraphs_per_fragment: int = 96, fragment_count: int = 3) -> dict[str, Any]:
    """Return the deterministic normal/negative fixture shared by T10/T11.

    Every fragment intentionally reuses local IDs (``p0``, ``phase0``,
    ``c0`` and ``e0``).  The scoped mapping is therefore exercised rather than
    hidden by globally unique fixture identifiers.
    """

    if type(paragraphs_per_fragment) is not int or paragraphs_per_fragment < 1 or paragraphs_per_fragment > MAX_FRAGMENT_PARAGRAPHS:
        _fail("invalid_input", "paragraphs_per_fragment must fit one fragment's capacity")
    if type(fragment_count) is not int or fragment_count < 1:
        _fail("invalid_input", "fragment_count must be positive")
    fragments: list[dict[str, Any]] = []
    for fragment_index in range(fragment_count):
        version = f"fixture-fragment-{fragment_index + 1:03}"
        paragraphs: list[dict[str, Any]] = []
        phases: list[dict[str, Any]] = []
        conclusions: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        for index in range(paragraphs_per_fragment):
            phase_id = f"phase{index}"
            conclusion_id = f"c{index}"
            evidence_id = f"e{index}"
            phases.append({"id": phase_id, "label": f"fixture phase {fragment_index + 1}/{index}", "year": None, "period": None})
            evidence.append({"id": evidence_id, "publication_id": f"fixture-publication-{fragment_index + 1:03}", "quote": f"fixture evidence {fragment_index + 1}/{index}"})
            conclusions.append({"id": conclusion_id, "phase_ids": [phase_id], "event_id": None, "evidence": [evidence_id]})
            paragraphs.append({
                "id": f"p{index}",
                "ordinal": index,
                "phase_id": phase_id,
                "segments": [{"text": f"fixture paragraph {fragment_index + 1}/{index}", "conclusion_ids": [conclusion_id], "event_id": None, "event_relation": None}],
                "entities": [],
            })
        fragments.append({
            "schema": "chronicle.historical-publication",
            "version": "0.1",
            "publication_status": PUBLISHED_STATUS,
            "publication_version": version,
            "publication_id": f"fixture-publication-{fragment_index + 1:03}",
            "coverage": {"scope": "fixture-history", "start": fragment_index * paragraphs_per_fragment, "end": (fragment_index + 1) * paragraphs_per_fragment, "start_anchor": f"source-{fragment_index * paragraphs_per_fragment:04}", "end_anchor": f"source-{(fragment_index + 1) * paragraphs_per_fragment - 1:04}"},
            "phases": phases,
            "paragraphs": paragraphs,
            "conclusions": conclusions,
            "evidence": evidence,
            "entry_points": [{"kind": "period", "label": f"fixture period {fragment_index + 1}", "paragraph_id": "p0", "event_id": None, "reason": "fixture keeps only one curated entry for this fragment"}],
        })
    boundaries = [
        {
            "left_fragment_version": fragments[index]["publication_version"],
            "right_fragment_version": fragments[index + 1]["publication_version"],
            "geometry": "contiguous",
            "status": "accepted",
            "review_basis": [
                {"fragment_version": fragments[index]["publication_version"], "paragraph_id": f"p{paragraphs_per_fragment - 1}"},
                {"fragment_version": fragments[index + 1]["publication_version"], "paragraph_id": "p0"},
            ],
            "note": "fixture seam was reviewed in supplied narrative order",
        }
        for index in range(fragment_count - 1)
    ]
    navigation = [
        {"fragment_version": fragment["publication_version"], "kind": "period", "label": f"fixture period {index + 1}", "paragraph_id": "p0", "event_id": None, "reason": "fixture selects a small curated entry"}
        for index, fragment in enumerate(fragments)
    ]
    edition = compile_history_edition(fragments, boundary_reviews=boundaries, navigation=navigation)
    return {
        "fragments": fragments,
        "boundary_reviews": boundaries,
        "navigation": navigation,
        "edition": edition,
        "negative_inputs": {
            "unpublished": {**copy.deepcopy(fragments[0]), "publication_status": "draft"},
            "duplicate_fragment": [copy.deepcopy(fragments[0]), copy.deepcopy(fragments[0])],
            "out_of_bounds_anchor": [{**copy.deepcopy(navigation[0]), "paragraph_id": "missing"}],
            "reversed_boundary": [dict(boundaries[0], geometry="inversion")] if boundaries else [],
        },
    }


history_edition_fixture = contract_fixture


__all__ = [
    "CONTRACT_VERSION",
    "EDITION_ERROR_CODES",
    "EditionContractError",
    "HISTORY_EDITION_ERROR_CODES",
    "HISTORY_EDITION_SCHEMA",
    "HISTORY_EDITION_VERSION",
    "HistoryEditionError",
    "MAX_FRAGMENT_PARAGRAPHS",
    "MAX_PARAGRAPHS_PER_FRAGMENT",
    "MAX_NAVIGATION_ENTRIES",
    "PUBLISHED_STATUS",
    "append_edition",
    "append_history_edition",
    "build_edition_manifest",
    "build_history_edition",
    "compile_edition",
    "compile_history_edition",
    "contract_fixture",
    "derive_global_conclusion_id",
    "derive_global_paragraph_id",
    "derive_global_phase_id",
    "derive_hp_id",
    "derive_scoped_id",
    "fragment_content_hash",
    "history_edition_fixture",
    "inspect_boundaries",
    "replace_edition",
    "replace_history_edition",
    "validate_edition",
    "validate_history_edition",
    "validate_fragment",
    "validate_published_fragment",
]
