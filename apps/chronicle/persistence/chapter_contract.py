"""Chronicle C2-R1-T01 chapter joint-product contract (application-owned).

Pure deterministic validation/acceptance for one natural chapter, with no
database, network, or model access (Amendment 0006). Implements
``chapter-production.md`` sections 2-6 and ``review-workflow.md``
sections 2/4 as machine-checkable shared contracts for T03-T07/T15:

- :class:`ChapterLimits` fixes the engineering envelope and enters the
  request fingerprint.
- :func:`validate_chapter_candidate` checks schema, identity binding,
  reference closure, kinds, record_sources coverage, Claim evidence,
  mention consistency, translation required-block coverage, anchor
  resolution (block + quote + occurrence), hash/chapter binding, time
  precision, and alias discipline.
- :func:`accept_chapter_candidate` accepts only passing candidates and
  emits a ``chronicle.chapter-artifact / 0.1`` with resolved anchors,
  request fingerprint, and producing-run binding.
- :func:`validate_resolution_v02` structurally validates
  ``chronicle.resolution-links / 0.2`` scope documents without
  auto-deriving same-links (business check belongs to T08).

Coordinates use ``chars-normalized-utf8``: Python ``str`` code-point
half-open intervals ``[start, end)`` over the normalized chapter text.
The model never computes offsets; the program enumerates occurrences.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from common import PersistenceError, canonical_json_bytes, sha256_json

#: Model-generatable candidate marker.
CANDIDATE_SCHEMA = "chronicle.chapter-candidate"
CANDIDATE_VERSION = "0.1"

#: Program-accepted artifact marker.
ARTIFACT_SCHEMA = "chronicle.chapter-artifact"
ARTIFACT_VERSION = "0.1"

#: Resolution scope marker.
RESOLUTION_SCHEMA = "chronicle.resolution-links"
RESOLUTION_VERSION = "0.2"

#: Chapter plan version bound into requests.
PLAN_VERSION = "c2r1-chapters-v1"

# ---------------------------------------------------------------------------
# Production version registration (C2-R2-T03, extended C2-R3-T02)
# ---------------------------------------------------------------------------
# chapter_contract owns only the version *registry* after the first round:
# which candidate/artifact schema/version pairs exist and which one the
# production chain must emit. The 0.1 pair stays frozen and is validated by
# this module's first-round validator; the 0.2 pair adds reading annotations
# and its pure validator/acceptance live in the T01 ``reading_contract``
# module; the 0.3 pair adds ``person_states`` and its pure
# validator/acceptance live in the T01 ``person_state_contract`` module.
# The 0.4 pair adds staged production scope and a content-acceptance receipt;
# ``staged_chapter_contract`` validates its unchanged 0.3 sub-document.
# Consumers dispatch to those validators rather than re-implementing checks.
# This remains the single candidate/artifact version registry.

#: Candidate versions registered for the production chain (frozen first).
CANDIDATE_VERSIONS = ("0.1", "0.2", "0.3", "0.4")
#: Artifact versions registered for the production chain (frozen first).
ARTIFACT_VERSIONS = ("0.1", "0.2", "0.3", "0.4")

#: Version new staged production emits. Explicit frozen fixtures retain their
#: own versions; new production never silently downgrades.
PRODUCTION_CANDIDATE_VERSION = "0.4"
PRODUCTION_ARTIFACT_VERSION = "0.4"

#: Offset unit for every chapter/block/anchor coordinate.
OFFSET_UNIT = "chars-normalized-utf8"

#: Surfaces that must stay contextual mentions, never stable aliases.
CONTEXTUAL_ONLY_SURFACES = {"公", "王"}

#: Temp-ID numeric range mirrored from the assembler's revision-scoped
#: remapping (`assembly._remapped_id` / `_remapped_chapter_id`): the
#: numeric part must fit in 3 digits (0-999). Validation rejects larger
#: numbers fail-fast so a bad id dies here, not one stage later at
#: assemble (live C2-R1-T19: model emitted ent_1001, passed validation,
#: killed the whole job at assemble).
_TEMP_ID_NUMBER_RE = re.compile(r"^(?:src|ent|evt|clm)_(\d+)$")
_MAX_TEMP_ID_NUMBER = 999

#: Max characters of each compared value rendered into a repair diagnostic.
#: Equality diagnostics must show both sides so the correction re-ask can
#: copy the verbatim value; the per-diagnostic char budget in
#: chapter_prompt.compact_validation_errors still bounds the total.
_DIAGNOSTIC_VALUE_CHARS = 60


def _diagnostic_value(value: Any) -> str:
    """Render one compared value for a model-facing repair diagnostic.

    Live evidence (C2-R1-T19, candidate 0410b15d): every mention of a
    corrected chapter failed ``surface must equal selection.quote`` with a
    value-free message, so the model could not see which side to copy and
    the whole correction round was wasted. The contract is unchanged —
    only the diagnostic carries both sides, truncated.
    """
    text = value if isinstance(value, str) else repr(value)
    if len(text) > _DIAGNOSTIC_VALUE_CHARS:
        text = text[: _DIAGNOSTIC_VALUE_CHARS - 1] + "…"
    return repr(text)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "ingestion" / "schemas"
CANDIDATE_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-candidate-v0.1.schema.json"
ARTIFACT_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.1.schema.json"
RESOLUTION_V02_SCHEMA_PATH = SCHEMA_DIR / "chronicle-resolution-v0.2.schema.json"

CANDIDATE_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.1.schema.json"
)
ARTIFACT_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.1.schema.json"
)
RESOLUTION_V02_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-resolution-v0.2.schema.json"
)

# 0.2 schema locations are registered here by filename/$id only; their
# cross-file $ref resolution belongs to the T01 ``reading_contract`` loader.
CANDIDATE_V02_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-candidate-v0.2.schema.json"
ARTIFACT_V02_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.2.schema.json"
CANDIDATE_V02_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.2.schema.json"
)
ARTIFACT_V02_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.2.schema.json"
)

# 0.3 schema locations are registered here by filename/$id only; their
# cross-file $ref resolution belongs to the T01 ``person_state_contract``
# loader (which resolves the frozen 0.1/0.2 definitions 0.3 reuses).
CANDIDATE_V03_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-candidate-v0.3.schema.json"
ARTIFACT_V03_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.3.schema.json"
CANDIDATE_V03_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.3.schema.json"
)
ARTIFACT_V03_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.3.schema.json"
)

# 0.4 uses the frozen base definitions, with program-owned source scope and
# a content-acceptance receipt. Its owner is ``staged_chapter_contract``.
CANDIDATE_V04_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-candidate-v0.4.schema.json"
ARTIFACT_V04_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.4.schema.json"
CANDIDATE_V04_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.4.schema.json"
)
ARTIFACT_V04_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.4.schema.json"
)

#: Registry mapping each production version to its schema file/$id.
_CANDIDATE_SCHEMA_REGISTRY: dict[str, tuple[Path, str]] = {
    "0.1": (CANDIDATE_SCHEMA_PATH, CANDIDATE_SCHEMA_ID),
    "0.2": (CANDIDATE_V02_SCHEMA_PATH, CANDIDATE_V02_SCHEMA_ID),
    "0.3": (CANDIDATE_V03_SCHEMA_PATH, CANDIDATE_V03_SCHEMA_ID),
    "0.4": (CANDIDATE_V04_SCHEMA_PATH, CANDIDATE_V04_SCHEMA_ID),
}
_ARTIFACT_SCHEMA_REGISTRY: dict[str, tuple[Path, str]] = {
    "0.1": (ARTIFACT_SCHEMA_PATH, ARTIFACT_SCHEMA_ID),
    "0.2": (ARTIFACT_V02_SCHEMA_PATH, ARTIFACT_V02_SCHEMA_ID),
    "0.3": (ARTIFACT_V03_SCHEMA_PATH, ARTIFACT_V03_SCHEMA_ID),
    "0.4": (ARTIFACT_V04_SCHEMA_PATH, ARTIFACT_V04_SCHEMA_ID),
}


@lru_cache(maxsize=8)
def _load_schema(path_str: str, expected_id: str) -> dict[str, Any]:
    path = Path(path_str)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PersistenceError(f"chapter schema unreadable at {path}: {exc}") from exc
    if not isinstance(schema, dict) or schema.get("$id") != expected_id:
        raise PersistenceError(
            f"chapter schema identity mismatch at {path}: "
            f"expected $id {expected_id!r}"
        )
    return schema


def candidate_schema() -> dict[str, Any]:
    """Return the canonical chapter-candidate JSON Schema."""
    return _load_schema(str(CANDIDATE_SCHEMA_PATH), CANDIDATE_SCHEMA_ID)


def artifact_schema() -> dict[str, Any]:
    """Return the canonical chapter-artifact JSON Schema."""
    return _load_schema(str(ARTIFACT_SCHEMA_PATH), ARTIFACT_SCHEMA_ID)


def resolution_v02_schema() -> dict[str, Any]:
    """Return the canonical resolution-links v0.2 JSON Schema."""
    return _load_schema(str(RESOLUTION_V02_SCHEMA_PATH), RESOLUTION_V02_SCHEMA_ID)


def candidate_schema_for(version: str) -> dict[str, Any]:
    """Return the registered chapter-candidate schema for ``version``.

    Only shape is resolved here (no cross-file 0.2 ``$ref`` binding); the
    T01 ``reading_contract`` owns the 0.2 $ref registry used to validate a
    real candidate.
    """
    entry = _CANDIDATE_SCHEMA_REGISTRY.get(version)
    if entry is None:
        raise PersistenceError(
            f"unregistered chapter-candidate version {version!r}; "
            f"known: {list(CANDIDATE_VERSIONS)}"
        )
    path, schema_id = entry
    return _load_schema(str(path), schema_id)


def artifact_schema_for(version: str) -> dict[str, Any]:
    """Return the registered chapter-artifact schema for ``version``."""
    entry = _ARTIFACT_SCHEMA_REGISTRY.get(version)
    if entry is None:
        raise PersistenceError(
            f"unregistered chapter-artifact version {version!r}; "
            f"known: {list(ARTIFACT_VERSIONS)}"
        )
    path, schema_id = entry
    return _load_schema(str(path), schema_id)


def candidate_schema_registry() -> dict[str, str]:
    """Return ``{version: schema $id}`` for every registered candidate."""
    return {version: schema_id for version, (_p, schema_id) in _CANDIDATE_SCHEMA_REGISTRY.items()}


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChapterLimits:
    """Engineering envelope for one chapter execution.

    Defaults are resource-protection bounds from chapter-production.md
    section 3, not model-capability guarantees. They enter the request
    fingerprint; the correction-round count is fixed at 1.
    """

    max_source_chars: int = 32768
    max_prompt_chars: int = 262144
    max_response_chars: int = 524288
    max_response_bytes: int = 4 * 1024 * 1024
    max_output_tokens: int = 65536
    max_correction_rounds: int = 1

    def __post_init__(self) -> None:
        for name in (
            "max_source_chars",
            "max_prompt_chars",
            "max_response_chars",
            "max_response_bytes",
            "max_output_tokens",
            "max_correction_rounds",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise PersistenceError(f"{name} must be a positive integer")
        if self.max_correction_rounds != 1:
            raise PersistenceError("max_correction_rounds is fixed at 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_source_chars": self.max_source_chars,
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_chars": self.max_response_chars,
            "max_response_bytes": self.max_response_bytes,
            "max_output_tokens": self.max_output_tokens,
            "max_correction_rounds": self.max_correction_rounds,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ChapterLimits":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise PersistenceError("chapter limits must be a JSON object")
        try:
            known = {k: value[k] for k in cls().to_dict() if k in value}
            return cls(**known)
        except TypeError as exc:
            raise PersistenceError(f"invalid chapter limits: {exc}") from exc

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ChapterLimits":
        """Build limits honoring the documented CHRONICLE_CHAPTER_* overrides."""
        source = env if env is not None else os.environ
        mapping = {
            "max_source_chars": "CHRONICLE_CHAPTER_MAX_SOURCE_CHARS",
            "max_prompt_chars": "CHRONICLE_CHAPTER_MAX_PROMPT_CHARS",
            "max_response_chars": "CHRONICLE_CHAPTER_MAX_RESPONSE_CHARS",
            "max_response_bytes": "CHRONICLE_CHAPTER_MAX_RESPONSE_BYTES",
            "max_output_tokens": "CHRONICLE_CHAPTER_MAX_OUTPUT_TOKENS",
        }
        overrides: dict[str, Any] = {}
        for field, var in mapping.items():
            raw = source.get(var)
            if raw is None or raw == "":
                continue
            try:
                overrides[field] = int(raw)
            except ValueError as exc:
                raise PersistenceError(f"{var} must be an integer, got {raw!r}") from exc
        return cls.from_dict(overrides or None)


# ---------------------------------------------------------------------------
# Normalization + hashing helpers
# ---------------------------------------------------------------------------


def normalize_source_bytes(raw: bytes) -> tuple[str, str, str]:
    """Decode controlled txt/md bytes into normalized chapter text.

    Returns ``(normalized_text, source_sha256, normalized_sha256)``.
    Strips one BOM, folds CRLF/CR to LF. Offsets are code points of the
    returned text.
    """
    source_sha256 = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, source_sha256, normalized_sha256


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_fingerprint(request: dict[str, Any]) -> str:
    """Fingerprint binding model, prompt/schema/plan/limits versions."""
    if (request.get("schema_versions") or {}).get("candidate") == "0.4":
        # Staged reuse and content decisions bind every input byte, including
        # source scope and revision coordinates. Older hashes stay frozen.
        return sha256_json(request)
    payload = {
        "chapter_id": request.get("chapter_id"),
        "revision_id": request.get("revision_id"),
        "source_sha256": request.get("source_sha256"),
        "normalized_sha256": request.get("normalized_sha256"),
        "plan_version": request.get("plan_version"),
        "limits": request.get("limits"),
        "schema_versions": request.get("schema_versions"),
        "blocks": request.get("blocks"),
    }
    return sha256_json(payload)


def anchor_id_for(
    *, revision_id: str, chapter_id: str, start: int, end: int, quote_sha256: str
) -> str:
    digest = sha256_json(
        {
            "revision_id": revision_id,
            "chapter_id": chapter_id,
            "start": start,
            "end": end,
            "quote_sha256": quote_sha256,
        }
    )
    return "anc_" + digest[:16]


# ---------------------------------------------------------------------------
# Internal request/block helpers
# ---------------------------------------------------------------------------


def _require_request(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(request, dict):
        raise PersistenceError("chapter request must be a JSON object")
    for key in (
        "chapter_id",
        "revision_id",
        "source_sha256",
        "normalized_sha256",
        "normalized_text",
        "blocks",
        "required_block_ids",
    ):
        if request.get(key) in (None, ""):
            raise PersistenceError(f"chapter request is missing {key!r}")
    text = request["normalized_text"]
    if not isinstance(text, str) or text == "":
        raise PersistenceError("chapter request normalized_text must be non-empty")
    blocks = request["blocks"]
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError("chapter request blocks must be a non-empty array")
    by_id: dict[str, dict[str, Any]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            raise PersistenceError("chapter request block must be an object")
        block_id = block.get("block_id")
        if not isinstance(block_id, str) or not block_id:
            raise PersistenceError("chapter request block requires block_id")
        if block_id in by_id:
            raise PersistenceError(f"duplicate request block_id {block_id!r}")
        try:
            start, end = int(block["start"]), int(block["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(
                f"request block {block_id!r} requires integer start/end"
            ) from exc
        if not (0 <= start < end <= len(text)):
            raise PersistenceError(
                f"request block {block_id!r} range [{start},{end}) "
                f"outside normalized text ({len(text)} chars)"
            )
        by_id[block_id] = {"start": start, "end": end, "kind": block.get("kind")}
    required = request["required_block_ids"]
    if not isinstance(required, list) or not required:
        raise PersistenceError("required_block_ids must be a non-empty array")
    for block_id in required:
        if not isinstance(block_id, str) or block_id not in by_id:
            raise PersistenceError(f"required_block_id {block_id!r} has no block")
    if request.get("plan_version", PLAN_VERSION) != PLAN_VERSION:
        raise PersistenceError(
            f"plan_version must be {PLAN_VERSION!r}, "
            f"got {request.get('plan_version')!r}"
        )
    ChapterLimits.from_dict(request.get("limits"))
    return by_id


def _find_occurrences(haystack: str, needle: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while True:
        found = haystack.find(needle, start)
        if found < 0:
            return positions
        positions.append(found)
        start = found + max(len(needle), 1)


def _anchor_miss_hint(
    text: str,
    quote: str,
    blocks_by_id: dict[str, dict[str, Any]],
    *,
    first: str,
    last: str,
) -> str:
    """Explain a 0-hit anchor as misattribution or fabrication.

    Returns a short model-facing suffix: when the quote occurs elsewhere
    in the chapter, name the chapter-wide count and the first enclosing
    block so the correction can re-point first/last_block_id and recount;
    when it occurs nowhere, say so explicitly so the correction replaces
    the quote instead of shuffling block ids. Pure hint — the contract
    decision is unchanged.
    """
    try:
        total = _find_occurrences(text, quote)
    except (TypeError, ValueError):
        return ""
    if not total:
        return "; quote not found anywhere in chapter text: replace it with a verbatim-copied quote"
    offset = total[0]
    holder = ""
    for block_id, block in blocks_by_id.items():
        try:
            start, end = block["start"], block["end"]
        except (KeyError, TypeError):
            continue
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and start <= offset < end
        ):
            holder = block_id
            break
    where = f" first in block {holder!r}" if holder else ""
    return (
        f"; quote occurs {len(total)} time(s) chapter-wide,"
        f"{where}: re-point first/last_block_id to the enclosing block(s) and recount"
    )


def resolve_selection(
    selection: dict[str, Any],
    *,
    request: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
    owner: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve one selection to a hash-bound anchor, or return an error.

    The quote must occur verbatim inside the window
    ``[first_block.start, last_block.end)``; ``occurrence`` counts from 1
    within that window. Cross-block quotes are supported because the
    window spans whole blocks.
    """
    if not isinstance(selection, dict):
        return None, f"{owner} selection must be an object"
    first = selection.get("first_block_id")
    last = selection.get("last_block_id")
    quote = selection.get("quote")
    occurrence = selection.get("occurrence")
    if not isinstance(first, str) or first not in blocks_by_id:
        return None, f"{owner} references unknown first_block {first!r}"
    if not isinstance(last, str) or last not in blocks_by_id:
        return None, f"{owner} references unknown last_block {last!r}"
    if not isinstance(quote, str) or not quote:
        return None, f"{owner} quote must be a non-empty string"
    if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 1:
        return None, f"{owner} occurrence must be a positive integer"
    first_block = blocks_by_id[first]
    last_block = blocks_by_id[last]
    if first_block["start"] > last_block["start"]:
        return None, f"{owner} block order is reversed ({first!r} after {last!r})"
    text: str = request["normalized_text"]
    window_start: int = first_block["start"]
    window_end: int = last_block["end"]
    if window_end <= window_start:
        return None, f"{owner} block window is empty"
    window = text[window_start:window_end]
    positions = _find_occurrences(window, quote)
    if len(positions) < occurrence:
        # Live regression (C2-R1-T19, 先主传 chunk 0 across v4/v5): every
        # surviving correction error is a 0-hit anchor, but the diagnostic
        # never says whether the quote exists elsewhere (re-point the
        # blocks) or nowhere in the chapter (replace the quote). The
        # contract is unchanged; the diagnostic now carries that fork.
        hint = _anchor_miss_hint(
            text, quote, blocks_by_id, first=first, last=last,
        )
        return None, (
            f"{owner} quote occurs {len(positions)} time(s) in "
            f"[{first!r}..{last!r}] but occurrence={occurrence} was requested"
            f"{hint}"
        )
    start = window_start + positions[occurrence - 1]
    end = start + len(quote)
    quote_sha256 = sha256_text(quote)
    anchor = {
        "anchor_id": anchor_id_for(
            revision_id=request["revision_id"],
            chapter_id=request["chapter_id"],
            start=start,
            end=end,
            quote_sha256=quote_sha256,
        ),
        "revision_id": request["revision_id"],
        "chapter_id": request["chapter_id"],
        "source_sha256": request["source_sha256"],
        "normalized_sha256": request["normalized_sha256"],
        "first_block_id": first,
        "last_block_id": last,
        "quote": quote,
        "quote_sha256": quote_sha256,
        "occurrence": occurrence,
        "start": start,
        "end": end,
    }
    return anchor, None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _schema_errors(candidate: dict[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:  # pragma: no cover - dependency is declared
        return ["jsonschema package is unavailable for candidate validation"]
    validator = Draft202012Validator(candidate_schema(), format_checker=FormatChecker())
    found = sorted(validator.iter_errors(candidate), key=lambda e: list(e.absolute_path))
    errors = []
    for error in found:
        where = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{where}: {error.message}")
    return errors


def _model_list(value: Any, owner: str, field: str, errors: list[str]) -> list[Any]:
    """Return a model-controlled collection fail-closed.

    Non-array values (objects, strings, numbers) are recorded as errors
    and treated as empty so validation always returns a failed report
    instead of raising ``TypeError``.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{owner} {field} must be an array")
        return []
    return value


def validate_chapter_candidate(
    request: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Validate one chapter candidate against its program-owned request.

    Returns a deterministic report ``{schema, version, passed, count,
    errors}``. Every category must be empty for acceptance; any single
    failing part rejects the whole candidate.
    """
    return _validate_chapter_components(request, candidate, include_translation=True)


def chapter_extraction_errors(request: dict[str, Any], extraction: dict[str, Any]) -> list[str]:
    """Check extraction semantics before translation/linking exist.

    The staged step schema owns the partial document's shape. This returns
    diagnostics only; it is never a chapter acceptance report. Full candidates
    still require their unchanged schema, translation and coverage checks.
    """
    return flatten_validation_errors(
        _validate_chapter_components(request, extraction, include_translation=False)
    )


def _validate_chapter_components(
    request: dict[str, Any], candidate: dict[str, Any], *, include_translation: bool
) -> dict[str, Any]:
    schema_errors = _schema_errors(candidate) if include_translation and isinstance(candidate, dict) else []
    identity: list[str] = []
    references: list[str] = []
    record_sources: list[str] = []
    mentions: list[str] = []
    coverage: list[str] = []
    anchors: list[str] = []
    time_precision: list[str] = []
    aliases: list[str] = []

    blocks_by_id: dict[str, dict[str, Any]] = {}
    try:
        blocks_by_id = _require_request(request)
    except PersistenceError as exc:
        identity.append(f"request: {exc}")
        blocks_by_id = {}

    if not isinstance(candidate, dict):
        identity.append("candidate must be a JSON object")
        return _report(
            schema_errors, identity, references, record_sources, mentions,
            coverage, anchors, time_precision, aliases,
            bundle_recall_observations(request, candidate),
        )

    if include_translation and (candidate.get("schema") != CANDIDATE_SCHEMA or candidate.get("version") != CANDIDATE_VERSION):
        identity.append("candidate schema/version must be chronicle.chapter-candidate/0.1")
    if candidate.get("chapter_id") != request.get("chapter_id"):
        identity.append(
            f"chapter_id drift: request {request.get('chapter_id')!r} vs "
            f"candidate {candidate.get('chapter_id')!r}"
        )
    # Hash binding: normalized text must hash to the request claim.
    text = request.get("normalized_text")
    if isinstance(text, str) and isinstance(request.get("normalized_sha256"), str):
        if sha256_text(text) != request["normalized_sha256"]:
            identity.append("normalized_sha256 does not match normalized_text (hash drift)")
    if isinstance(text, str):
        try:
            limits = ChapterLimits.from_dict(request.get("limits"))
        except PersistenceError as exc:
            identity.append(f"request limits: {exc}")
            limits = None
        if limits is not None and len(text) > limits.max_source_chars:
            identity.append(
                f"chapter text ({len(text)} chars) exceeds "
                f"max_source_chars ({limits.max_source_chars})"
            )

    bundle = candidate.get("bundle") if isinstance(candidate.get("bundle"), dict) else {}
    entities = bundle.get("entities") if isinstance(bundle.get("entities"), list) else []
    events = bundle.get("events") if isinstance(bundle.get("events"), list) else []
    claims = bundle.get("claims") if isinstance(bundle.get("claims"), list) else []
    entity_ids = {e.get("temp_id") for e in entities if isinstance(e, dict) and isinstance(e.get("temp_id"), str)}
    event_ids = {e.get("temp_id") for e in events if isinstance(e, dict) and isinstance(e.get("temp_id"), str)}
    claim_ids = {c.get("temp_id") for c in claims if isinstance(c, dict) and isinstance(c.get("temp_id"), str)}
    all_refs = entity_ids | event_ids | claim_ids
    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    source_id = source.get("temp_id") if isinstance(source.get("temp_id"), str) else None
    if isinstance(source, dict) and source and not isinstance(source.get("temp_id"), str):
        references.append("source temp_id must be a string")

    # Global temporary-ID discipline: these IDs are the downstream
    # reference/assembly keys, so every record temp_id must be unique
    # across the whole bundle (including the source) and carry the
    # prefix of its record type. Non-string temp_ids fail closed here
    # (schema_validation reports them too) instead of raising TypeError.
    seen_temp_ids: dict[str, str] = {}
    source_temp_id = source.get("temp_id")
    if isinstance(source_temp_id, str):
        if not source_temp_id.startswith("src_"):
            references.append("source temp_id must carry the 'src_' prefix")
        seen_temp_ids[source_temp_id] = "source"
    for collection_name, collection, prefix in (
        ("entities", entities, "ent_"),
        ("events", events, "evt_"),
        ("claims", claims, "clm_"),
    ):
        for record in collection:
            if not isinstance(record, dict):
                continue
            temp_id = record.get("temp_id")
            owner = str(temp_id) if isinstance(temp_id, str) else collection_name
            if not isinstance(temp_id, str) or not temp_id:
                references.append(f"{collection_name} record requires a string temp_id")
                continue
            if not temp_id.startswith(prefix):
                references.append(
                    f"{owner} temp_id must carry the {prefix!r} {collection_name} prefix"
                )
            id_match = _TEMP_ID_NUMBER_RE.match(temp_id)
            if id_match and int(id_match.group(1)) > _MAX_TEMP_ID_NUMBER:
                references.append(
                    f"{owner} temp_id number must be within 000-{_MAX_TEMP_ID_NUMBER} "
                    f"(assembly remaps into revision-scoped {prefix}_NNN); "
                    "renumber sequentially from 001"
                )
            if temp_id in seen_temp_ids:
                references.append(
                    f"duplicate temp_id {temp_id!r} "
                    f"({seen_temp_ids[temp_id]} vs {collection_name})"
                )
            else:
                seen_temp_ids[temp_id] = collection_name

    # Bundle presence: a candidate must carry both translation and bundle
    # content; translation-only or bundle-only candidates are rejected.
    translation = candidate.get("translation") if include_translation and isinstance(candidate.get("translation"), dict) else {}
    tblocks = translation.get("blocks") if isinstance(translation.get("blocks"), list) else []
    if include_translation and translation.get("language") != "zh-CN":
        identity.append("translation.language must be zh-CN")
    if include_translation and not tblocks:
        coverage.append("translation.blocks must be a non-empty array")
    if not entities and not events and not claims:
        references.append("bundle carries no entities/events/claims (bundle-only structure required)")

    # Canonical-ID discipline: nothing model-generated may carry canonical IDs.
    for collection_name, collection in (("entities", entities), ("events", events), ("claims", claims)):
        for record in collection:
            if not isinstance(record, dict):
                continue
            owner = str(record.get("temp_id") or collection_name)
            if "id" in record:
                references.append(f"{owner} must not carry canonical id")
            resolution = record.get("resolution") if isinstance(record.get("resolution"), dict) else {}
            if resolution.get("canonical_id") not in (None,):
                references.append(f"{owner} must not carry canonical_id")
            if resolution.get("candidate_ids"):
                references.append(f"{owner} must not carry candidate_ids")
            if (
                collection_name == "entities"
                and isinstance(record.get("resolution"), dict)
                and resolution.get("status") != "unresolved"
            ):
                # Live regression (C2-R1-T19, candidate 26eb34c1): the guide
                # said resolution:{status} without pinning the value, the
                # model emitted status 'new', validation passed it, and the
                # whole job died one stage later at assemble. Fail fast here
                # with both sides shown, mirroring the assembler's
                # entities-only status rule (the candidate schema already
                # requires the resolution object itself).
                references.append(
                    f"{owner} resolution status {_diagnostic_value(resolution.get('status'))} "
                    'must be "unresolved"; identity is decided in Studio review, '
                    "never in this chapter product"
                )

    # Reference closure + kinds for translation refs, claim refs, participants.
    # Every membership test is type-guarded: schema-invalid model output
    # (arrays/objects where IDs belong) must fail closed as a rejected
    # candidate, never raise TypeError.
    seen_tblock_ids: set[str] = set()
    covered_source_blocks: set[str] = set()
    source_order: list[str] = []
    for index, block in enumerate(tblocks, 1):
        if not isinstance(block, dict):
            references.append(f"translation.blocks[{index}] must be an object")
            continue
        owner = f"translation.blocks[{index}]"
        block_id = block.get("block_id")
        if not isinstance(block_id, str) or not block_id:
            references.append(f"{owner} block_id must be a non-empty string")
        else:
            if block_id in seen_tblock_ids:
                references.append(f"{owner} duplicate block_id {block_id!r}")
            seen_tblock_ids.add(block_id)
        source_block_ids = block.get("source_block_ids")
        if not isinstance(source_block_ids, list):
            references.append(f"{owner} source_block_ids must be an array")
        else:
            for source_block_id in source_block_ids:
                if not isinstance(source_block_id, str):
                    references.append(
                        f"{owner} references malformed source block {source_block_id!r}"
                    )
                    continue
                if source_block_id not in blocks_by_id:
                    references.append(f"{owner} references unknown source block {source_block_id!r}")
                else:
                    covered_source_blocks.add(source_block_id)
                    source_order.append(source_block_id)
        for ref in _model_list(
            block.get("entity_refs"), owner, "entity_refs", references
        ) + _model_list(block.get("event_refs"), owner, "event_refs", references):
            if not isinstance(ref, dict):
                references.append(f"{owner} has a malformed typed reference")
                continue
            kind, target = ref.get("kind"), ref.get("ref")
            if not isinstance(target, str):
                references.append(f"{owner} has a malformed typed reference")
                continue
            if kind == "entity" and target not in entity_ids:
                references.append(f"{owner} references missing entity {target!r}")
            elif kind == "event" and target not in event_ids:
                references.append(f"{owner} references missing event {target!r}")
            elif kind not in ("entity", "event"):
                references.append(f"{owner} has invalid ref kind {kind!r}")
    for record in entities:
        if not isinstance(record, dict):
            continue
    for event in events:
        if not isinstance(event, dict):
            continue
        owner = str(event.get("temp_id") or "event") if isinstance(event.get("temp_id"), str) else "event"
        for participant in _model_list(
            event.get("participants"), owner, "participants", references
        ):
            if not isinstance(participant, dict):
                references.append(f"{owner} has a malformed participant")
                continue
            entity_ref = participant.get("entity_ref")
            if not isinstance(entity_ref, str) or entity_ref not in entity_ids:
                references.append(f"{owner} references missing entity {entity_ref!r}")
        for place in _model_list(event.get("places"), owner, "places", references):
            if not isinstance(place, str) or place not in entity_ids:
                references.append(f"{owner} references missing place entity {place!r}")
        parent = event.get("parent_event_ref")
        if parent is not None and (not isinstance(parent, str) or parent not in event_ids):
            references.append(f"{owner} references missing parent event {parent!r}")
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        owner = str(claim.get("temp_id")) if isinstance(claim.get("temp_id"), str) else "claim"
        for field in ("subject", "object"):
            ref = claim.get(field)
            if ref is None or not isinstance(ref, dict):
                continue
            kind = ref.get("kind")
            if kind == "literal":
                # Literal shape follows the frozen candidate schema and the
                # C0 LITERAL convention ({"kind": "literal", "value": ...}).
                # Live evidence (C2-R1-T19) proved the API-enforced schema
                # guides the model to value-shape while this check demanded
                # ref-shape, so no literal object could ever pass both
                # gates. Subjects still must not be literals.
                if field == "subject":
                    references.append(f"{owner}.subject must not be a literal")
                elif "value" not in ref:
                    references.append(f"{owner}.{field} has a malformed reference")
                continue
            target = ref.get("ref")
            if not isinstance(target, str):
                references.append(f"{owner}.{field} has a malformed reference")
                continue
            if kind == "entity" and target not in entity_ids:
                references.append(f"{owner}.{field} references missing entity {target!r}")
            elif kind == "event" and target not in event_ids:
                references.append(f"{owner}.{field} references missing event {target!r}")
            elif kind not in ("entity", "event"):
                references.append(f"{owner}.{field} has invalid ref kind {kind!r}")
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        if evidence.get("source_ref") != source_id:
            references.append(f"{owner} evidence references unknown source {evidence.get('source_ref')!r}")

    # record_sources: every Entity/Event/Claim resolves to non-empty
    # selections; Claim evidence text must equal its first selection quote.
    by_record: dict[str, dict[str, Any]] = {}
    for entry in _model_list(
        candidate.get("record_sources"), "candidate", "record_sources", record_sources
    ):
        if not isinstance(entry, dict):
            record_sources.append("record_sources entry must be an object")
            continue
        ref = entry.get("record_ref")
        if not isinstance(ref, str) or not ref:
            record_sources.append(f"record_sources entry has malformed record_ref {ref!r}")
            continue
        if ref in by_record:
            record_sources.append(f"duplicate record_sources entry for {ref!r}")
        by_record[ref] = entry
        kind = entry.get("record_kind")
        expected_kind = None
        if ref in entity_ids:
            expected_kind = "entity"
        elif ref in event_ids:
            expected_kind = "event"
        elif ref in claim_ids:
            expected_kind = "claim"
        else:
            record_sources.append(f"record_sources entry references unknown record {ref!r}")
            continue
        if kind != expected_kind:
            record_sources.append(
                f"record_sources {ref!r} kind {kind!r} does not match bundle kind {expected_kind!r}"
            )
        selections = entry.get("selections")
        if not isinstance(selections, list) or not selections:
            record_sources.append(f"record_sources {ref!r} requires non-empty selections")
    for ref in all_refs:
        if ref not in by_record:
            record_sources.append(f"record {ref!r} has no record_sources entry")
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        owner = str(claim.get("temp_id")) if isinstance(claim.get("temp_id"), str) else "claim"
        entry = by_record.get(owner) if isinstance(claim.get("temp_id"), str) else None
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        if entry and isinstance(entry.get("selections"), list) and entry["selections"]:
            first = entry["selections"][0]
            if isinstance(first, dict) and first.get("quote") != evidence.get("text"):
                record_sources.append(
                    f"{owner} evidence text {_diagnostic_value(evidence.get('text'))} "
                    f"must equal first selection quote {_diagnostic_value(first.get('quote'))}"
                )

    # Mentions: status discipline + surface==quote + resolvable anchors.
    seen_mentions: set[str] = set()
    for mention in _model_list(candidate.get("mentions"), "candidate", "mentions", mentions):
        if not isinstance(mention, dict):
            mentions.append("mention entry must be an object")
            continue
        mention_id = mention.get("mention_id")
        if not isinstance(mention_id, str) or not mention_id:
            mentions.append(f"mention entry has malformed mention_id {mention_id!r}")
            continue
        owner = f"mention {mention_id!r}"
        if mention_id in seen_mentions:
            mentions.append(f"duplicate {owner}")
        seen_mentions.add(mention_id)
        status = mention.get("status")
        target = mention.get("target_ref")
        candidates_refs = mention.get("candidate_refs") or []
        if not isinstance(candidates_refs, list):
            mentions.append(f"{owner} candidate_refs must be an array")
            candidates_refs = []
        if status == "resolved" and (not target or candidates_refs):
            mentions.append(f"{owner} resolved requires non-empty target_ref and empty candidate_refs")
        elif status == "ambiguous" and (target is not None or len(candidates_refs) < 2):
            mentions.append(f"{owner} ambiguous requires target_ref=null and >=2 candidate_refs")
        elif status == "unresolved" and target is not None:
            mentions.append(f"{owner} unresolved requires target_ref=null")
        elif status not in ("resolved", "ambiguous", "unresolved"):
            mentions.append(f"{owner} has invalid status {status!r}")
        for ref in ([target] if target else []) + list(candidates_refs):
            if not isinstance(ref, str) or ref not in entity_ids:
                mentions.append(f"{owner} references missing entity {ref!r}")
        selection = mention.get("selection")
        surface = mention.get("surface")
        if not isinstance(surface, str) or not surface:
            mentions.append(f"{owner} surface must be a non-empty string")
        else:
            if isinstance(selection, dict) and selection.get("quote") != surface:
                mentions.append(
                    f"{owner} surface {_diagnostic_value(surface)} must equal "
                    f"selection.quote {_diagnostic_value(selection.get('quote'))}"
                )
            if not mention.get("contextual") and surface in CONTEXTUAL_ONLY_SURFACES:
                mentions.append(f"{owner} surface {surface!r} must stay contextual")
        if blocks_by_id and isinstance(selection, dict):
            _anchor, error = resolve_selection(
                selection, request=request, blocks_by_id=blocks_by_id, owner=owner
            )
            if error:
                anchors.append(error)

    # record_sources selections resolve to anchors as well.
    for ref, entry in by_record.items():
        selections = entry.get("selections") if isinstance(entry.get("selections"), list) else []
        for position, selection in enumerate(selections, 1):
            if blocks_by_id and isinstance(selection, dict):
                _anchor, error = resolve_selection(
                    selection, request=request, blocks_by_id=blocks_by_id,
                    owner=f"record_sources {ref!r}[{position}]",
                )
                if error:
                    anchors.append(error)

    # Translation coverage and order: every required (non-empty body)
    # block appears, and translation blocks are ordered. Array order is
    # meaningful (chapter-production.md section 4): the flattened
    # source_block_ids sequence must follow request block order, so a
    # reversed chapter cannot validate.
    required = request.get("required_block_ids") or []
    if include_translation and isinstance(required, list):
        missing = [b for b in required if b not in covered_source_blocks]
        if missing:
            coverage.append(
                "translation misses required source blocks: " + ", ".join(sorted(str(b) for b in missing))
            )
    if blocks_by_id and source_order:
        order_index = {
            block["block_id"]: position
            for position, block in enumerate(request["blocks"])
            if isinstance(block, dict) and isinstance(block.get("block_id"), str)
        }
        indices = [order_index[b] for b in source_order if b in order_index]
        if indices != sorted(indices):
            coverage.append(
                "translation source_block_ids order does not follow chapter block order"
            )

    # Time precision: normalized month/day are never invented; original
    # text must be grounded in the chapter text when present.
    for collection_name, collection in (("event", events), ("claim", claims)):
        for record in collection:
            if not isinstance(record, dict):
                continue
            owner = str(record.get("temp_id") or collection_name)
            moment = record.get("time")
            if moment is None:
                continue
            if not isinstance(moment, dict):
                time_precision.append(f"{owner} time must be an object or null")
                continue
            original = moment.get("original_text")
            if not isinstance(original, str) or not original:
                time_precision.append(f"{owner} time.original_text must be non-empty")
                continue
            if isinstance(text, str) and original not in text:
                time_precision.append(
                    f"{owner} time.original_text {original!r} is not grounded in chapter text"
                )
            normalized = moment.get("normalized")
            if isinstance(normalized, dict):
                if normalized.get("month") is not None:
                    time_precision.append(f"{owner} fabricates normalized month from traditional calendar")
                if normalized.get("day") is not None:
                    time_precision.append(f"{owner} fabricates normalized day from traditional calendar")

    # Alias discipline: stable aliases need textual support; 公/王 stay contextual.
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        owner = str(entity.get("temp_id")) if isinstance(entity.get("temp_id"), str) else "entity"
        for alias in _model_list(entity.get("aliases"), owner, "aliases", aliases):
            if not isinstance(alias, str) or not alias:
                aliases.append(f"{owner} alias must be a non-empty string")
            elif alias in CONTEXTUAL_ONLY_SURFACES:
                aliases.append(f"{owner} alias {alias!r} must not become a global alias")
            elif isinstance(text, str) and alias not in text:
                aliases.append(f"{owner} alias {alias!r} has no chapter-text support")

    return _report(
        schema_errors, identity, references, record_sources, mentions,
        coverage, anchors, time_precision, aliases,
        bundle_recall_observations(request, candidate),
    )


def bundle_recall_observations(request: Any, candidate: Any) -> dict[str, Any]:
    """Count-only recall observability for one chapter candidate.

    Live finding (C2-R1-T19, 先主傳 chunk 0): the validator is purely
    structural, so a skeletal-but-valid bundle (1 entity / 1 event /
    1 claim / 2 mentions over 12591 chapter chars, while the translation
    names 曹操 37× and 孫權 19×) passes while demonstrating almost no
    identity/source linkage. A hard count floor is deliberately NOT a
    contract rule — it is gameable by padding and false-positives on
    genuinely sparse chapters (see the T19 acceptance record §13 for the
    recorded decision). This function therefore OBSERVES ONLY: it never
    affects ``passed``/``count``. Operators and independent reviewers
    read these numbers (surfaced in the validation report, hence in
    Studio attempt evidence) to judge recall per chapter.
    """
    text = request.get("normalized_text") if isinstance(request, dict) else None
    chapter_chars = len(text) if isinstance(text, str) else None
    bundle = (
        candidate.get("bundle")
        if isinstance(candidate, dict) and isinstance(candidate.get("bundle"), dict)
        else {}
    )

    def _count(key: str) -> int:
        values = bundle.get(key)
        return len(values) if isinstance(values, list) else 0

    entities = _count("entities")
    events = _count("events")
    claims = _count("claims")
    raw_mentions = candidate.get("mentions") if isinstance(candidate, dict) else None
    mention_list = raw_mentions if isinstance(raw_mentions, list) else []
    mentions = len(mention_list)
    resolved = sum(1 for m in mention_list if isinstance(m, dict) and m.get("status") == "resolved")
    raw_sources = candidate.get("record_sources") if isinstance(candidate, dict) else None
    record_sources_entries = len(raw_sources) if isinstance(raw_sources, list) else 0
    translation = candidate.get("translation") if isinstance(candidate, dict) else None
    tblocks = (
        translation.get("blocks")
        if isinstance(translation, dict) and isinstance(translation.get("blocks"), list)
        else []
    )
    translation_chars = sum(
        len(b.get("text")) for b in tblocks if isinstance(b, dict) and isinstance(b.get("text"), str)
    )
    densities: dict[str, float] | None = None
    if isinstance(chapter_chars, int) and chapter_chars > 0:
        densities = {
            key: round(count / chapter_chars * 1000, 2)
            for key, count in (
                ("entities", entities),
                ("events", events),
                ("claims", claims),
                ("mentions", mentions),
            )
        }
    return {
        "chapter_chars": chapter_chars,
        "translation_chars": translation_chars,
        "translation_blocks": len(tblocks),
        "entities": entities,
        "events": events,
        "claims": claims,
        "mentions": mentions,
        "mentions_resolved": resolved,
        "mentions_unresolved": mentions - resolved,
        "record_sources_entries": record_sources_entries,
        "per_1000_chars": densities,
    }


def _report(
    schema_errors: list[str],
    identity: list[str],
    references: list[str],
    record_sources: list[str],
    mentions: list[str],
    coverage: list[str],
    anchors: list[str],
    time_precision: list[str],
    aliases: list[str],
    recall: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = {
        "schema_validation": sorted(schema_errors),
        "identity_binding": sorted(identity),
        "references": sorted(references),
        "record_sources": sorted(record_sources),
        "mentions": sorted(mentions),
        "translation_coverage": sorted(coverage),
        "anchors": sorted(anchors),
        "time_precision": sorted(time_precision),
        "aliases": sorted(aliases),
    }
    count = sum(len(values) for values in errors.values())
    return {
        "schema": "chronicle.chapter-validation",
        "version": "0.2",
        "candidate_schema": CANDIDATE_SCHEMA,
        "candidate_version": CANDIDATE_VERSION,
        "passed": count == 0,
        "count": count,
        "errors": errors,
        # Count-only recall observability (see bundle_recall_observations):
        # never affects passed/count; operators judge recall from it.
        "recall": recall if isinstance(recall, dict) else {},
    }


def flatten_validation_errors(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for category, messages in (report.get("errors") or {}).items():
        for message in messages or []:
            result.append(f"{category}: {message}")
    return result


def collect_anchors(
    request: dict[str, Any], candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    """Resolve every mention/record_sources selection into anchors."""
    blocks_by_id = _require_request(request)
    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    selections: list[tuple[str, dict[str, Any]]] = []
    mentions_value = candidate.get("mentions")
    for mention in mentions_value if isinstance(mentions_value, list) else []:
        if isinstance(mention, dict) and isinstance(mention.get("selection"), dict):
            selections.append((f"mention {mention.get('mention_id')!r}", mention["selection"]))
    record_sources_value = candidate.get("record_sources")
    for entry in record_sources_value if isinstance(record_sources_value, list) else []:
        if not isinstance(entry, dict):
            continue
        selections_value = entry.get("selections")
        for position, selection in enumerate(
            selections_value if isinstance(selections_value, list) else [], 1
        ):
            if isinstance(selection, dict):
                selections.append(
                    (f"record_sources {entry.get('record_ref')!r}[{position}]", selection)
                )
    # Translation source blocks map to whole-block-range anchors.
    text: str = request["normalized_text"]
    translation_value = candidate.get("translation")
    translation_blocks = (
        translation_value.get("blocks")
        if isinstance(translation_value, dict)
        else None
    )
    for block in translation_blocks if isinstance(translation_blocks, list) else []:
        if not isinstance(block, dict):
            continue
        source_ids = block.get("source_block_ids")
        for source_block_id in source_ids if isinstance(source_ids, list) else []:
            if not isinstance(source_block_id, str):
                continue
            info = blocks_by_id.get(source_block_id)
            if info is None:
                continue
            quote = text[info["start"]:info["end"]]
            quote_sha256 = sha256_text(quote)
            key = (source_block_id, quote_sha256)
            if key in seen:
                continue
            seen.add(key)
            anchors.append(
                {
                    "anchor_id": anchor_id_for(
                        revision_id=request["revision_id"],
                        chapter_id=request["chapter_id"],
                        start=info["start"],
                        end=info["end"],
                        quote_sha256=quote_sha256,
                    ),
                    "revision_id": request["revision_id"],
                    "chapter_id": request["chapter_id"],
                    "source_sha256": request["source_sha256"],
                    "normalized_sha256": request["normalized_sha256"],
                    "first_block_id": source_block_id,
                    "last_block_id": source_block_id,
                    "quote": quote,
                    "quote_sha256": quote_sha256,
                    "occurrence": 1,
                    "start": info["start"],
                    "end": info["end"],
                }
            )
    for owner, selection in selections:
        anchor, error = resolve_selection(
            selection, request=request, blocks_by_id=blocks_by_id, owner=owner
        )
        if error or anchor is None:
            raise PersistenceError(f"cannot collect anchors: {error}")
        key = (anchor["start"], anchor["end"], anchor["quote_sha256"])
        if key in seen:
            continue
        seen.add(key)
        anchors.append(anchor)
    anchors.sort(key=lambda a: (a["start"], a["end"], a["anchor_id"]))
    # Detect anchor ID collisions with different content (fail closed).
    by_id: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        other = by_id.get(anchor["anchor_id"])
        if other is not None and (
            other["start"] != anchor["start"] or other["end"] != anchor["end"]
        ):
            raise PersistenceError(
                f"anchor id collision for {anchor['anchor_id']!r} (fail closed)"
            )
        by_id[anchor["anchor_id"]] = anchor
    return anchors


def accept_chapter_candidate(
    request: dict[str, Any],
    candidate: dict[str, Any],
    *,
    producing_run: dict[str, Any],
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept a passing candidate and emit its bound artifact.

    Validation is always recomputed for this exact request/candidate
    pair. A caller-supplied ``report`` is accepted only as a
    consistency check: it must agree with the recomputed report on both
    outcome and error set, otherwise acceptance fails closed. A forged
    ``{"passed": True}`` can therefore never accept a bad candidate.
    Raises :class:`PersistenceError` when the candidate does not pass.
    The model-generatable candidate is embedded verbatim; every
    program-bound value (hashes, offsets, fingerprint, run) is computed
    here, never read from the candidate.
    """
    if not isinstance(producing_run, dict):
        raise PersistenceError("producing_run must be a JSON object")
    for key in ("run_id", "model", "prompt_schema_version"):
        if not isinstance(producing_run.get(key), str) or not producing_run[key]:
            raise PersistenceError(f"producing_run requires non-empty {key!r}")
    fresh = validate_chapter_candidate(request, candidate)
    if report is not None:
        if not isinstance(report, dict):
            raise PersistenceError("supplied validation report must be a JSON object")
        if bool(report.get("passed")) != bool(fresh["passed"]) or set(
            flatten_validation_errors(report)
        ) != set(flatten_validation_errors(fresh)):
            raise PersistenceError(
                "supplied validation report does not match this "
                "request/candidate pair; refusing to accept (fail closed)"
            )
    checked = fresh
    if not checked.get("passed"):
        detail = "; ".join(flatten_validation_errors(checked))
        raise PersistenceError(f"chapter candidate failed validation: {detail}")
    anchors = collect_anchors(request, candidate)
    fingerprint = request_fingerprint(request)
    candidate_copy = copy.deepcopy(candidate)
    artifact = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_sha256": request["source_sha256"],
        "normalized_sha256": request["normalized_sha256"],
        "candidate": candidate_copy,
        "candidate_sha256": sha256_json(candidate_copy),
        "anchors": anchors,
        "request_fingerprint": fingerprint,
        "producing_run": copy.deepcopy(producing_run),
    }
    return artifact


# ---------------------------------------------------------------------------
# Resolution v0.2 structural validation
# ---------------------------------------------------------------------------


def validate_resolution_v02(document: dict[str, Any]) -> dict[str, Any]:
    """Structurally validate a resolution-links v0.2 document.

    Keeps the v0.1 candidate vocabulary; only the ``scope`` envelope is
    new. Same-bundle cross-chapter business rules belong to T08: this
    function never auto-derives same-links.
    """
    schema_errors: list[str] = []
    structural: list[str] = []
    if isinstance(document, dict):
        try:
            from jsonschema import Draft202012Validator, FormatChecker

            validator = Draft202012Validator(
                resolution_v02_schema(), format_checker=FormatChecker()
            )
            found = sorted(
                validator.iter_errors(document), key=lambda e: list(e.absolute_path)
            )
            for error in found:
                where = "/".join(str(part) for part in error.absolute_path) or "$"
                schema_errors.append(f"{where}: {error.message}")
        except ImportError:  # pragma: no cover
            schema_errors.append("jsonschema package is unavailable")
    else:
        structural.append("resolution document must be a JSON object")
        document = {}
    if document.get("schema") != RESOLUTION_SCHEMA or document.get("version") != RESOLUTION_VERSION:
        structural.append("resolution schema/version must be chronicle.resolution-links/0.2")
    if document.get("scope") not in ("within_revision", "cross_source"):
        structural.append("resolution scope must be within_revision|cross_source")
    if document.get("scope") == "cross_source" and isinstance(
        document.get("left_bundle"), dict
    ) and isinstance(document.get("right_bundle"), dict):
        if document["left_bundle"].get("label") == document["right_bundle"].get("label"):
            structural.append(
                "cross_source resolution requires distinct left/right bundle labels"
            )
    seen: set[str] = set()
    for collection, prefix in (("entity_links", "ec_"), ("event_links", "vc_")):
        for link in document.get(collection) or []:
            if not isinstance(link, dict):
                continue
            candidate_id = link.get("candidate_id")
            if candidate_id in seen:
                structural.append(f"duplicate candidate_id {candidate_id!r}")
            seen.add(str(candidate_id))
            if not isinstance(candidate_id, str) or not candidate_id.startswith(prefix):
                structural.append(f"{collection} candidate_id {candidate_id!r} has wrong prefix")
            left, right = link.get("left"), link.get("right")
            if (
                isinstance(left, dict)
                and isinstance(right, dict)
                and left.get("bundle") == right.get("bundle")
                and left.get("ref") == right.get("ref")
            ):
                structural.append(f"{candidate_id!r} links a record to itself")
    errors = {
        "schema_validation": sorted(schema_errors),
        "structural": sorted(structural),
    }
    count = len(schema_errors) + len(structural)
    return {
        "schema": "chronicle.resolution-validation",
        "version": "0.2",
        "passed": count == 0,
        "count": count,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Shared DTO fixture builders (contract examples, not history answers)
# ---------------------------------------------------------------------------


#: Evidence kinds for review SourceContext descriptors (review-workflow.md §4).
EVIDENCE_KINDS = (
    "direct_claim",
    "mention",
    "record_source",
    "event_context",
    "translation",
)

#: Batch audit vocabulary (Amendment 0007 §4/§8).
REVIEW_SUBJECT_VERSION = "0.2"
ENTITY_REVIEW_DECISIONS = ("same_entity", "not_same", "uncertain")
EVENT_REVIEW_DECISIONS = (
    "same_occurrence",
    "related_occurrence",
    "not_same",
    "uncertain",
)


def example_assembled_mapping(
    *, revision_refs: dict[str, str], chapter_by_ref: dict[str, str]
) -> dict[str, Any]:
    """Build the T07-consumable local-to-revision mapping example shape."""
    return {
        "schema": "chronicle.chapter-assembly-mapping-example",
        "version": "0.1",
        "chapter_by_ref": dict(chapter_by_ref),
        "local_to_revision": dict(revision_refs),
    }


def example_source_descriptor(
    *,
    context_id: str,
    bundle: str,
    bundle_sha256: str,
    record_ref: str,
    job_id: str,
    revision_id: str,
    chapter_id: str,
    artifact_sha256: str,
    source_title: str,
    chapter_title: str,
    available: bool = True,
    anchors: list[dict[str, Any]] | None = None,
    evidence_kind: str = "record_source",
) -> dict[str, Any]:
    """Build one review SourceContext descriptor (review-workflow.md §4)."""
    if not isinstance(job_id, str) or not job_id:
        raise PersistenceError("source descriptor job_id must be a non-empty string")
    return {
        "context_id": context_id,
        "bundle": bundle,
        "bundle_sha256": bundle_sha256,
        "record_ref": record_ref,
        "job_id": job_id,
        "revision_id": revision_id,
        "chapter_id": chapter_id,
        "artifact_sha256": artifact_sha256,
        "source_title": source_title,
        "chapter_title": chapter_title,
        "available": available,
        "anchors": list(anchors or []),
        "evidence_kind": evidence_kind,
    }


def validate_source_descriptor(descriptor: dict[str, Any]) -> list[str]:
    """Return required-field errors for one SourceContext descriptor."""
    errors: list[str] = []
    if not isinstance(descriptor, dict):
        return ["source descriptor must be an object"]
    for field in (
        "context_id",
        "bundle",
        "bundle_sha256",
        "record_ref",
        "job_id",
        "revision_id",
        "chapter_id",
        "artifact_sha256",
        "source_title",
        "chapter_title",
        "available",
        "anchors",
        "evidence_kind",
    ):
        if field not in descriptor:
            errors.append(f"source descriptor is missing {field!r}")
    if "job_id" in descriptor and (
        not isinstance(descriptor["job_id"], str) or not descriptor["job_id"]
    ):
        errors.append("source descriptor job_id must be a non-empty string")
    if descriptor.get("evidence_kind") not in EVIDENCE_KINDS:
        errors.append(
            f"source descriptor evidence_kind must be one of {list(EVIDENCE_KINDS)}"
        )
    if "anchors" in descriptor and not isinstance(descriptor["anchors"], list):
        errors.append("source descriptor anchors must be an array")
    return errors


def example_chapter_pair_context(
    *, left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    """Build the review-workflow chapter_pair evidence DTO example shape.

    Both sides are SourceContext descriptors; chapter_pair carries no
    published canonical side and never borrows a batch identifier.
    """
    return {
        "review_mode": "chapter_pair",
        "left": dict(left),
        "right": dict(right),
    }


def validate_chapter_pair_context(context: dict[str, Any]) -> list[str]:
    """Return required-field errors for a chapter_pair evidence DTO."""
    errors: list[str] = []
    if not isinstance(context, dict):
        return ["chapter_pair context must be an object"]
    if context.get("review_mode") != "chapter_pair":
        errors.append("chapter_pair context review_mode must be 'chapter_pair'")
    for side in ("left", "right"):
        if side not in context:
            errors.append(f"chapter_pair context is missing {side!r}")
            continue
        for error in validate_source_descriptor(context[side]):
            errors.append(f"{side}: {error}")
    return errors


def example_batch_context(
    *,
    review_subject_id: str,
    link_kind: str,
    canonical_id: str,
    groups: list[dict[str, Any]],
    members: list[dict[str, Any]],
    signals: list[str] | None = None,
) -> dict[str, Any]:
    """Build the published_batch evidence DTO example shape (Am. 0007 §4).

    Batching is question organization only, never an identity conclusion:
    the DTO retains every incoming review group with its deterministic
    group ID and proven component root, all underlying candidate keys
    and member bundle/ref pairs, the default decision, and per-group
    overrides.
    """
    if link_kind == "entity":
        allowed = list(ENTITY_REVIEW_DECISIONS)
    elif link_kind == "event":
        allowed = list(EVENT_REVIEW_DECISIONS)
    else:
        raise PersistenceError(f"unknown batch link kind {link_kind!r}")
    return {
        "review_mode": "published_batch",
        "review_subject_id": review_subject_id,
        "review_subject_version": REVIEW_SUBJECT_VERSION,
        "link_kind": link_kind,
        "published_canonical_id": canonical_id,
        "left_subject": {
            "component_kind": "published_canonical",
            "canonical_id": canonical_id,
        },
        "right_subject": {
            "component_kind": "operator_review_batch",
        },
        "groups": [dict(group) for group in groups],
        "group_count": len(groups),
        "members": [dict(member) for member in members],
        "member_count": len(members),
        "signals": list(signals or []),
        "default_decision": "uncertain",
        "group_overrides": [],
        "allowed_decisions": allowed,
        "note": "contract fixture example, not a historical answer",
    }


def validate_batch_context(context: dict[str, Any]) -> list[str]:
    """Return required-field errors for a published_batch evidence DTO."""
    errors: list[str] = []
    if not isinstance(context, dict):
        return ["batch context must be an object"]
    for field in (
        "review_mode",
        "review_subject_id",
        "review_subject_version",
        "link_kind",
        "published_canonical_id",
        "left_subject",
        "right_subject",
        "groups",
        "group_count",
        "members",
        "member_count",
        "signals",
        "default_decision",
        "group_overrides",
        "allowed_decisions",
    ):
        if field not in context:
            errors.append(f"batch context is missing {field!r}")
    if context.get("review_mode") != "published_batch":
        errors.append("batch context review_mode must be 'published_batch'")
    if context.get("link_kind") not in ("entity", "event"):
        errors.append("batch context link_kind must be entity|event")
    groups = context.get("groups")
    if isinstance(groups, list):
        if context.get("group_count") != len(groups):
            errors.append("batch context group_count must match groups")
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                errors.append(f"batch context groups[{index}] must be an object")
                continue
            for field in (
                "review_group_id",
                "component_root",
                "members",
                "member_count",
                "candidate_keys",
            ):
                if field not in group:
                    errors.append(f"batch context groups[{index}] is missing {field!r}")
    members = context.get("members")
    if isinstance(members, list) and context.get("member_count") != len(members):
        errors.append("batch context member_count must match members")
    return errors


def example_public_chapter_response(
    *,
    artifact: dict[str, Any],
    translation_blocks: list[dict[str, Any]],
    source_overview: dict[str, Any] | None = None,
    references: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the public chapter detail response example shape.

    Detail responses carry the complete ordered translation blocks plus
    a source overview and the precomputed object/event references; they
    never generate content dynamically.
    """
    return {
        "publication_id": "00000000-0000-7000-8000-000000000000",
        "chapter_id": artifact.get("chapter_id"),
        "revision_id": artifact.get("revision_id"),
        "translation_blocks": list(translation_blocks),
        "source_overview": dict(source_overview or {}),
        "references": dict(references or {}),
        "note": "contract fixture example, not a historical answer",
    }


def validate_public_chapter_response(response: dict[str, Any]) -> list[str]:
    """Return required-field errors for a public chapter detail response."""
    errors: list[str] = []
    if not isinstance(response, dict):
        return ["public chapter response must be an object"]
    for field in (
        "publication_id",
        "chapter_id",
        "revision_id",
        "translation_blocks",
        "source_overview",
        "references",
    ):
        if field not in response:
            errors.append(f"public chapter response is missing {field!r}")
    overview = response.get("source_overview")
    if isinstance(overview, dict):
        for field in ("source_title", "chapter_title", "revision_id"):
            if field not in overview:
                errors.append(f"public chapter source_overview is missing {field!r}")
    refs = response.get("references")
    if isinstance(refs, dict):
        for field in ("entities", "events"):
            if field not in refs:
                errors.append(f"public chapter references is missing {field!r}")
    return errors


def example_review_page(
    *,
    items: list[dict[str, Any]],
    open_count: int,
    observed_at: str,
    query: dict[str, Any] | None = None,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    """Build the studio-review-page/0.2 queue example shape.

    ``open_count`` is the read-transaction observation over the whole
    job/link_kind scope, independent of the current page; it is never
    derived from ``len(items)``.
    """
    if not isinstance(open_count, int) or isinstance(open_count, bool) or open_count < 0:
        raise PersistenceError("review page open_count must be a non-negative integer")
    if not isinstance(observed_at, str) or not observed_at:
        raise PersistenceError("review page observed_at must be a non-empty string")
    return {
        "schema": "chronicle.studio-review-page",
        "version": "0.2",
        "query": dict(query or {"status": "open", "limit": 50}),
        "items": list(items),
        "next_cursor": next_cursor,
        "open_count": open_count,
        "observed_at": observed_at,
    }


def validate_review_page(page: dict[str, Any]) -> list[str]:
    """Return required-field errors for a studio-review-page/0.2 DTO."""
    errors: list[str] = []
    if not isinstance(page, dict):
        return ["review page must be an object"]
    for field in (
        "schema",
        "version",
        "query",
        "items",
        "next_cursor",
        "open_count",
        "observed_at",
    ):
        if field not in page:
            errors.append(f"review page is missing {field!r}")
    if page.get("schema") != "chronicle.studio-review-page" or page.get("version") != "0.2":
        errors.append("review page schema/version must be chronicle.studio-review-page/0.2")
    if "open_count" in page and (
        not isinstance(page["open_count"], int)
        or isinstance(page["open_count"], bool)
        or page["open_count"] < 0
    ):
        errors.append("review page open_count must be a non-negative integer")
    if "observed_at" in page and (
        not isinstance(page["observed_at"], str) or not page["observed_at"]
    ):
        errors.append("review page observed_at must be a non-empty string")
    items = page.get("items")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"review page items[{index}] must be an object")
                continue
            for field in ("review_id", "status", "plan_fingerprint"):
                if field not in item:
                    errors.append(f"review page items[{index}] is missing {field!r}")
    return errors


__all__ = [
    "ARTIFACT_SCHEMA",
    "ARTIFACT_VERSIONS",
    "ARTIFACT_VERSION",
    "CANDIDATE_SCHEMA",
    "CANDIDATE_VERSIONS",
    "CANDIDATE_VERSION",
    "PRODUCTION_ARTIFACT_VERSION",
    "PRODUCTION_CANDIDATE_VERSION",
    "ChapterLimits",
    "ENTITY_REVIEW_DECISIONS",
    "EVENT_REVIEW_DECISIONS",
    "EVIDENCE_KINDS",
    "OFFSET_UNIT",
    "PLAN_VERSION",
    "RESOLUTION_SCHEMA",
    "RESOLUTION_VERSION",
    "REVIEW_SUBJECT_VERSION",
    "accept_chapter_candidate",
    "anchor_id_for",
    "artifact_schema",
    "artifact_schema_for",
    "candidate_schema",
    "candidate_schema_for",
    "candidate_schema_registry",
    "collect_anchors",
    "example_assembled_mapping",
    "example_batch_context",
    "example_chapter_pair_context",
    "example_public_chapter_response",
    "example_review_page",
    "example_source_descriptor",
    "flatten_validation_errors",
    "normalize_source_bytes",
    "request_fingerprint",
    "resolution_v02_schema",
    "resolve_selection",
    "sha256_text",
    "validate_batch_context",
    "validate_chapter_candidate",
    "validate_chapter_pair_context",
    "validate_public_chapter_response",
    "validate_resolution_v02",
    "validate_review_page",
    "validate_source_descriptor",
]
