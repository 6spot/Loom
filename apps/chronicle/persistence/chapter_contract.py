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

#: Offset unit for every chapter/block/anchor coordinate.
OFFSET_UNIT = "chars-normalized-utf8"

#: Surfaces that must stay contextual mentions, never stable aliases.
CONTEXTUAL_ONLY_SURFACES = {"公", "王"}

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


@lru_cache(maxsize=3)
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
        if block_id not in by_id:
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
    if first not in blocks_by_id:
        return None, f"{owner} references unknown first_block {first!r}"
    if last not in blocks_by_id:
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
        return None, (
            f"{owner} quote occurs {len(positions)} time(s) in "
            f"[{first!r}..{last!r}] but occurrence={occurrence} was requested"
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


def validate_chapter_candidate(
    request: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Validate one chapter candidate against its program-owned request.

    Returns a deterministic report ``{schema, version, passed, count,
    errors}``. Every category must be empty for acceptance; any single
    failing part rejects the whole candidate.
    """
    schema_errors = _schema_errors(candidate) if isinstance(candidate, dict) else []
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
        )

    if candidate.get("schema") != CANDIDATE_SCHEMA or candidate.get("version") != CANDIDATE_VERSION:
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
        limits = ChapterLimits.from_dict(request.get("limits"))
        if len(text) > limits.max_source_chars:
            identity.append(
                f"chapter text ({len(text)} chars) exceeds "
                f"max_source_chars ({limits.max_source_chars})"
            )

    bundle = candidate.get("bundle") if isinstance(candidate.get("bundle"), dict) else {}
    entities = bundle.get("entities") if isinstance(bundle.get("entities"), list) else []
    events = bundle.get("events") if isinstance(bundle.get("events"), list) else []
    claims = bundle.get("claims") if isinstance(bundle.get("claims"), list) else []
    entity_ids = {e.get("temp_id") for e in entities if isinstance(e, dict)}
    event_ids = {e.get("temp_id") for e in events if isinstance(e, dict)}
    claim_ids = {c.get("temp_id") for c in claims if isinstance(c, dict)}
    all_refs = entity_ids | event_ids | claim_ids
    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    source_id = source.get("temp_id")

    # Bundle presence: a candidate must carry both translation and bundle
    # content; translation-only or bundle-only candidates are rejected.
    translation = candidate.get("translation") if isinstance(candidate.get("translation"), dict) else {}
    tblocks = translation.get("blocks") if isinstance(translation.get("blocks"), list) else []
    if translation.get("language") != "zh-CN":
        identity.append("translation.language must be zh-CN")
    if not tblocks:
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

    # Reference closure + kinds for translation refs, claim refs, participants.
    seen_tblock_ids: set[str] = set()
    covered_source_blocks: set[str] = set()
    for index, block in enumerate(tblocks, 1):
        if not isinstance(block, dict):
            continue
        owner = f"translation.blocks[{index}]"
        block_id = block.get("block_id")
        if block_id in seen_tblock_ids:
            references.append(f"{owner} duplicate block_id {block_id!r}")
        seen_tblock_ids.add(block_id)  # type: ignore[arg-type]
        for source_block_id in block.get("source_block_ids") or []:
            if source_block_id not in blocks_by_id:
                references.append(f"{owner} references unknown source block {source_block_id!r}")
            else:
                covered_source_blocks.add(source_block_id)
        for ref in (block.get("entity_refs") or []) + (block.get("event_refs") or []):
            if not isinstance(ref, dict):
                references.append(f"{owner} has a malformed typed reference")
                continue
            kind, target = ref.get("kind"), ref.get("ref")
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
        owner = str(event.get("temp_id") or "event")
        for participant in event.get("participants") or []:
            if isinstance(participant, dict) and participant.get("entity_ref") not in entity_ids:
                references.append(f"{owner} references missing entity {participant.get('entity_ref')!r}")
        for place in event.get("places") or []:
            if place not in entity_ids:
                references.append(f"{owner} references missing place entity {place!r}")
        parent = event.get("parent_event_ref")
        if parent is not None and parent not in event_ids:
            references.append(f"{owner} references missing parent event {parent!r}")
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        owner = str(claim.get("temp_id") or "claim")
        for field in ("subject", "object"):
            ref = claim.get(field)
            if ref is None or not isinstance(ref, dict):
                continue
            kind, target = ref.get("kind"), ref.get("ref")
            if kind == "entity" and target not in entity_ids:
                references.append(f"{owner}.{field} references missing entity {target!r}")
            elif kind == "event" and target not in event_ids:
                references.append(f"{owner}.{field} references missing event {target!r}")
            elif kind == "literal" and field == "subject":
                references.append(f"{owner}.subject must not be a literal")
            elif kind not in ("entity", "event", "literal"):
                references.append(f"{owner}.{field} has invalid ref kind {kind!r}")
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        if evidence.get("source_ref") != source_id:
            references.append(f"{owner} evidence references unknown source {evidence.get('source_ref')!r}")

    # record_sources: every Entity/Event/Claim resolves to non-empty
    # selections; Claim evidence text must equal its first selection quote.
    by_record: dict[str, dict[str, Any]] = {}
    for entry in candidate.get("record_sources") or []:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("record_ref")
        if ref in by_record:
            record_sources.append(f"duplicate record_sources entry for {ref!r}")
        by_record[str(ref)] = entry
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
        owner = str(claim.get("temp_id"))
        entry = by_record.get(owner)
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        if entry and isinstance(entry.get("selections"), list) and entry["selections"]:
            first = entry["selections"][0]
            if isinstance(first, dict) and first.get("quote") != evidence.get("text"):
                record_sources.append(
                    f"{owner} evidence text must equal first selection quote"
                )

    # Mentions: status discipline + surface==quote + resolvable anchors.
    seen_mentions: set[str] = set()
    for mention in candidate.get("mentions") or []:
        if not isinstance(mention, dict):
            continue
        mention_id = mention.get("mention_id")
        owner = f"mention {mention_id!r}"
        if mention_id in seen_mentions:
            mentions.append(f"duplicate {owner}")
        seen_mentions.add(mention_id)  # type: ignore[arg-type]
        status = mention.get("status")
        target = mention.get("target_ref")
        candidates_refs = mention.get("candidate_refs") or []
        if status == "resolved" and (not target or candidates_refs):
            mentions.append(f"{owner} resolved requires non-empty target_ref and empty candidate_refs")
        elif status == "ambiguous" and (target is not None or len(candidates_refs) < 2):
            mentions.append(f"{owner} ambiguous requires target_ref=null and >=2 candidate_refs")
        elif status == "unresolved" and target is not None:
            mentions.append(f"{owner} unresolved requires target_ref=null")
        elif status not in ("resolved", "ambiguous", "unresolved"):
            mentions.append(f"{owner} has invalid status {status!r}")
        for ref in ([target] if target else []) + list(candidates_refs):
            if ref not in entity_ids:
                mentions.append(f"{owner} references missing entity {ref!r}")
        selection = mention.get("selection")
        if isinstance(selection, dict) and selection.get("quote") != mention.get("surface"):
            mentions.append(f"{owner} surface must equal selection.quote")
        if not mention.get("contextual") and mention.get("surface") in CONTEXTUAL_ONLY_SURFACES:
            mentions.append(f"{owner} surface {mention.get('surface')!r} must stay contextual")
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

    # Translation coverage: every required (non-empty body) block appears.
    required = request.get("required_block_ids") or []
    if isinstance(required, list):
        missing = [b for b in required if b not in covered_source_blocks]
        if missing:
            coverage.append(
                "translation misses required source blocks: " + ", ".join(sorted(missing))
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
        owner = str(entity.get("temp_id"))
        for alias in entity.get("aliases") or []:
            if alias in CONTEXTUAL_ONLY_SURFACES:
                aliases.append(f"{owner} alias {alias!r} must not become a global alias")
            elif isinstance(text, str) and isinstance(alias, str) and alias and alias not in text:
                aliases.append(f"{owner} alias {alias!r} has no chapter-text support")

    return _report(
        schema_errors, identity, references, record_sources, mentions,
        coverage, anchors, time_precision, aliases,
    )


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
        "version": "0.1",
        "candidate_schema": CANDIDATE_SCHEMA,
        "candidate_version": CANDIDATE_VERSION,
        "passed": count == 0,
        "count": count,
        "errors": errors,
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
    for mention in candidate.get("mentions") or []:
        if isinstance(mention, dict) and isinstance(mention.get("selection"), dict):
            selections.append((f"mention {mention.get('mention_id')!r}", mention["selection"]))
    for entry in candidate.get("record_sources") or []:
        if not isinstance(entry, dict):
            continue
        for position, selection in enumerate(entry.get("selections") or [], 1):
            if isinstance(selection, dict):
                selections.append(
                    (f"record_sources {entry.get('record_ref')!r}[{position}]", selection)
                )
    # Translation source blocks map to whole-block-range anchors.
    text: str = request["normalized_text"]
    for block in candidate.get("translation", {}).get("blocks", []) or []:
        if not isinstance(block, dict):
            continue
        for source_block_id in block.get("source_block_ids") or []:
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
    checked = report if report is not None else validate_chapter_candidate(request, candidate)
    if not isinstance(checked, dict) or not checked.get("passed"):
        detail = "; ".join(flatten_validation_errors(checked)) if isinstance(checked, dict) else "no report"
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


def example_chapter_pair_context(
    *, left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    """Build the review-workflow chapter_pair evidence DTO example shape."""
    return {
        "review_mode": "chapter_pair",
        "left": left,
        "right": right,
    }


def example_public_chapter_response(
    *, artifact: dict[str, Any], translation_blocks: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the public chapter detail response example shape."""
    return {
        "publication_id": "00000000-0000-7000-8000-000000000000",
        "chapter_id": artifact.get("chapter_id"),
        "revision_id": artifact.get("revision_id"),
        "translation_blocks": list(translation_blocks),
        "note": "contract fixture example, not a historical answer",
    }


def example_review_page(*, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the studio-review-page/0.2 queue example shape."""
    return {
        "schema": "chronicle.studio-review-page",
        "version": "0.2",
        "query": {"status": "open", "limit": 50},
        "items": list(items),
        "next_cursor": None,
        "open_count": len(items),
    }


__all__ = [
    "ARTIFACT_SCHEMA",
    "ARTIFACT_VERSION",
    "CANDIDATE_SCHEMA",
    "CANDIDATE_VERSION",
    "ChapterLimits",
    "OFFSET_UNIT",
    "PLAN_VERSION",
    "RESOLUTION_SCHEMA",
    "RESOLUTION_VERSION",
    "accept_chapter_candidate",
    "anchor_id_for",
    "artifact_schema",
    "candidate_schema",
    "collect_anchors",
    "example_assembled_mapping",
    "example_chapter_pair_context",
    "example_public_chapter_response",
    "example_review_page",
    "flatten_validation_errors",
    "normalize_source_bytes",
    "request_fingerprint",
    "resolution_v02_schema",
    "resolve_selection",
    "sha256_text",
    "validate_chapter_candidate",
    "validate_resolution_v02",
]
