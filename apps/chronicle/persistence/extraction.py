"""Chronicle C1-T6 context-aware chunk extraction (application-owned product logic).

Pure deterministic request/validation/history logic with no database, model,
or network access (Architecture Amendment 0006). The durable worker path
lives in ``apps/chronicle/worker/ingestion_worker.py`` (``extract`` stage)
on the C1-T1 control-plane tables behind ``CHRONICLE_DATABASE_URL``.

Contract summary (GitHub Issue #495):

- Reuses the C0 Source/Entity/Event/Claim contract (``CONTRACT_VERSION``)
  and the bounded validate-then-repair direction instead of a new ontology
  for book ingestion. No canonical identity is assigned inside a chunk:
  a candidate carrying a canonical ``id`` fails validation.
- For each chunk, one bounded model request is built from the current
  chunk text, section/document metadata, the inherited C1-T5 ContextState
  input, and bounded boundary strings. The rendered prompt is gated
  against ``max_prompt_chars`` (fail closed).
- Every model attempt is recorded verbatim (prompt, raw response,
  validation report, candidate) in an append-only attempt history. The
  history plus the request metadata form the ``ChunkRun`` checkpoint:
  replaying validation over the stored pairs reproduces the stored
  reports (see :func:`verify_history`).
- Exact evidence: every Claim evidence text must be an exact substring
  of the *current chunk text*. Context summaries never substitute for
  source evidence. Chunk coordinates (offsets/hashes/revision) travel in
  the run envelope, not in the candidate: the C0
  ``evidence.locator`` shape is unchanged.
- ``ContextStateNext`` is carried forward only as model-processing
  context. It is stored beside the candidate, never merged into it, and
  every extraction checkpoint carries ``authoritative: False``.
- Extraction confidence (``extraction.confidence``) stays separate from
  historical assessment (``assessment.status`` starts ``unassessed``).
- Invalid output uses bounded correction re-asks
  (``max_repair_attempts``) and then fails closed: no candidate is
  accepted, the failure is recorded, and nothing is silently coerced.
- Normalized calendar precision is never invented: normalized
  month/day must stay null, and a normalized year is accepted only when
  the document metadata supplies the exact verified mapping.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from common import PersistenceError

try:
    from segmentation import CONTEXT_VERSION as EXPECTED_CONTEXT_VERSION
    from segmentation import OFFSET_UNIT
except ImportError:  # pragma: no cover - standalone import without sibling
    EXPECTED_CONTEXT_VERSION = "c1t5-ctx-v2"
    OFFSET_UNIT = "chars-normalized-utf8"

#: Version of this chunk-extraction pipeline step.
EXTRACTION_VERSION = "c1t6-v1"

#: Reused C0 contract-first extraction contract (contract_v0 / repair_v0).
CONTRACT_VERSION = "0.2"

#: Version of the chunk prompt template rendered here.
PROMPT_VERSION = "c1t6-prompt-v2"

#: Marker proving chunk candidates are processing output, never authority.
NON_AUTHORITATIVE_NOTE = (
    "chunk extraction candidate is model-processing output over one "
    "chunk, not historical authority; canonical identity remains owned "
    "by the C0 staged/resolution/canonical path"
)

#: Warning type a candidate must carry for an entity grounded only in
#: inherited context surfaces (never as a silent resolution decision).
INHERITED_ENTITY_WARNING = "inherited_entity_context"

#: Canonical staged-bundle contract reused by C1-T6 (C0, unchanged).
#: Resolved relative to this module so the worker binds it independent
#: of the process working directory; it ships alongside this module in
#: every deployment (whole ``apps/chronicle`` tree).
CANONICAL_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "ingestion"
    / "schemas"
    / "chronicle-v0.1.schema.json"
)

#: Identity marker the canonical schema must carry (fail closed on drift).
CANONICAL_SCHEMA_ID = "https://loom.local/chronicle/schemas/chronicle-v0.1.schema.json"


@lru_cache(maxsize=1)
def canonical_schema() -> dict[str, Any]:
    """Load the canonical Chronicle staged-bundle JSON Schema.

    C1-T6 reuses the C0 contract without modification (replacing it is
    an explicit non-goal): this is the single schema chunk candidates
    are validated against.
    """
    try:
        schema = json.loads(CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PersistenceError(
            f"canonical Chronicle schema is unreadable at {CANONICAL_SCHEMA_PATH}: {exc}"
        ) from exc
    if not isinstance(schema, dict) or schema.get("$id") != CANONICAL_SCHEMA_ID:
        raise PersistenceError(
            "canonical Chronicle schema failed its identity check "
            f"(expected $id {CANONICAL_SCHEMA_ID!r}); refusing to validate "
            "against an unrecognized contract"
        )
    return schema


def require_canonical_schema(value: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the effective validation schema, fail-closed.

    ``None`` binds the canonical schema. A supplied dict must equal the
    canonical schema exactly — a permissive dictionary such as ``{}``
    would accept malformed candidates, so anything but the canonical
    contract is rejected. Schema evolution goes through contract
    versioning (a code change), never per-call dictionaries.
    """
    canonical = canonical_schema()
    if value is None:
        return canonical
    if not isinstance(value, dict) or value != canonical:
        raise PersistenceError(
            "extraction_schema must be the canonical Chronicle "
            f"staged-bundle schema ({CANONICAL_SCHEMA_ID}); refusing a "
            "non-canonical schema that could accept malformed candidates "
            "(fail closed)"
        )
    return canonical

_TOP_LEVEL_KEYS = ("schema_version", "source", "entities", "events", "claims", "warnings")


class ChunkModelProvider(Protocol):
    """Vendor-neutral model boundary for one chunk extraction request."""

    name: str

    def complete(self, prompt: str) -> str:
        """Return the raw model response text for a prompt."""


class ChunkModelError(RuntimeError):
    """Raised when a model response cannot be parsed or the call fails."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionConfig:
    """Tunable knobs for one chunk-extraction run; persisted in run history."""

    max_repair_attempts: int = 1
    max_prompt_chars: int = 8000
    # R6 of the C1-T17 real-machine gate measured a schema-shaped response
    # of 26,706 chars for a ~2K-char classical-Chinese chunk. 16K was an
    # uncalibrated development guard, not a contract limit. Keep a hard,
    # deterministic bound while leaving enough room for real staged bundles.
    max_response_chars: int = 32768

    def __post_init__(self) -> None:
        for name in (
            "max_repair_attempts",
            "max_prompt_chars",
            "max_response_chars",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise PersistenceError(f"{name} must be a non-negative integer")
        if self.max_prompt_chars < 1:
            raise PersistenceError("max_prompt_chars must be a positive integer")
        if self.max_response_chars < 1:
            raise PersistenceError("max_response_chars must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_repair_attempts": self.max_repair_attempts,
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_chars": self.max_response_chars,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExtractionConfig":
        if not isinstance(value, dict):
            raise PersistenceError("extraction config must be a JSON object")
        try:
            known = {k: value[k] for k in cls().to_dict() if k in value}
            return cls(**known)
        except TypeError as exc:
            raise PersistenceError(f"invalid extraction config: {exc}") from exc


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------


def _require_text(value: Any, description: str) -> str:
    if not isinstance(value, str) or value == "":
        raise PersistenceError(f"{description} must be a non-empty string")
    return value


def build_extraction_prompt(
    *,
    chunk_text: str,
    section: dict[str, Any],
    document: dict[str, Any],
    context_input: dict[str, Any],
    boundary_head: str,
    boundary_tail: str,
    validation_errors: list[str] | None = None,
    previous_candidate: dict[str, Any] | None = None,
) -> str:
    """Render the contract-first chunk prompt (initial or bounded correction).

    A correction re-ask appends the deterministic validator errors plus the
    previous candidate and requires a complete corrected bundle; every
    attempt is recorded verbatim, so corrections stay auditable and no
    silent coercion happens inside the harness.
    """
    _require_text(chunk_text, "chunk text")
    if not isinstance(section, dict) or not section.get("label"):
        raise PersistenceError("section must carry a non-empty label")
    if not isinstance(document, dict):
        raise PersistenceError("document metadata must be a JSON object")
    if not isinstance(context_input, dict):
        raise PersistenceError("context input must be a JSON object")
    if context_input.get("version") != EXPECTED_CONTEXT_VERSION:
        raise PersistenceError(
            "context input version mismatch: expected "
            f"{EXPECTED_CONTEXT_VERSION}, got {context_input.get('version')!r}"
        )
    if not isinstance(boundary_head, str) or not isinstance(boundary_tail, str):
        raise PersistenceError("boundary context must be strings")

    correction = ""
    if validation_errors is not None:
        if previous_candidate is None:
            raise PersistenceError("a correction re-ask requires the previous candidate")
        correction = f"""
CORRECTION RE-ASK
Your previous bundle failed deterministic validation with exactly these errors.
Return one complete corrected bundle satisfying every rule below. Change only
what the errors require; do not add unrelated facts and do not delete
unrelated records. Do not invent evidence or precision to silence an error:
if a fact cannot be grounded, drop the ungrounded record and emit a warning.

VALIDATION ERRORS
{json.dumps(validation_errors, ensure_ascii=False, indent=2)}

PREVIOUS CANDIDATE
{json.dumps(previous_candidate, ensure_ascii=False, indent=2, sort_keys=True)}
"""

    return f"""You are Chronicle chunk-extraction contract-v{CONTRACT_VERSION}, a source-grounded historical data extraction agent.

TASK
Read the CHUNK SOURCE TEXT below and produce one complete staged bundle
(source/entities/events/claims/warnings) following the SEMANTIC, TIME, and
IDENTITY rules. Extract only what this chunk asserts; use INHERITED CONTEXT
solely to interpret references (pronouns, inherited year), never as evidence.

SEMANTIC RULES
1. Use only CHUNK SOURCE TEXT plus explicit SECTION/DOCUMENT metadata and INHERITED CONTEXT. Never add outside historical knowledge.
2. Extract source-grounded Entity records needed by the facts you represent.
3. Create an Event for a distinct historical occurrence in this chunk. Do not merge independent actions merely because they share a sentence.
4. Create Claims for explicit factual assertions only when a faithful predicate expresses the source meaning. If no predicate fits, emit an `ontology_gap` warning instead of forcing one.
5. Event and Claim are different layers: Event models the occurrence; Claim models what this source asserts.
6. Every Claim.evidence.text must be an exact CHUNK SOURCE TEXT substring. Inherited context text is never evidence.
7. Use job-local temp IDs (`src_001`, `ent_001`, `evt_001`, `clm_001`). Never invent canonical UUIDs: a record carrying `id` is rejected.
8. Avoid duplicate Entity/Event/Claim records for the same chunk assertion.
9. Set every Claim assessment status to `unassessed`. Extraction confidence is not historical truth confidence.

TIME RULES
10. Preserve explicit and safely inherited traditional/regnal source time.
11. An Event/Claim time whose expression appears verbatim in this chunk is explicit. A time carried from INHERITED CONTEXT must list the inherited calendar fields in `inherited_fields` and keep the inherited expression verbatim in `original_text`.
12. Never convert a traditional month/day into normalized Gregorian month/day: normalized month/day stay null. A normalized year is allowed only when DOCUMENT metadata supplies the verified mapping; otherwise normalized year stays null too.
13. If this chunk gives no safe time context, time may remain null. Never guess.

IDENTITY / PROVENANCE RULES
14. Names and titles are attributes, never identity. Keep ambiguous references unresolved with a warning rather than guessing.
15. An Entity with no mention in this chunk is allowed only when its name appears in INHERITED CONTEXT surfaces AND the bundle carries an `inherited_entity_context` warning naming it. Such hints stay uncertain until resolution.
16. Warnings must describe the final bundle you return.
17. Return exactly one JSON object with keys schema_version, source, entities, events, claims, warnings. No prose or Markdown.
18. Keep the JSON compact: avoid decorative whitespace, redundant aliases/mentions, and semantically duplicate records. Compactness must never remove a distinct source-grounded fact or weaken exact evidence.
{correction}
SECTION
{json.dumps(section, ensure_ascii=False, indent=2, sort_keys=True)}

DOCUMENT
{json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)}

INHERITED CONTEXT (processing aid, not historical authority, not evidence)
{json.dumps(context_input, ensure_ascii=False, indent=2, sort_keys=True)}

BOUNDARY CONTEXT (bounded neighbor strings for interpretation only, not evidence)
{json.dumps({"boundary_head": boundary_head, "boundary_tail": boundary_tail}, ensure_ascii=False, indent=2, sort_keys=True)}

CHUNK SOURCE TEXT
---BEGIN CHUNK---
{chunk_text}
---END CHUNK---
"""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_chunk_request(
    *,
    chunk_text: str,
    section: dict[str, Any],
    document: dict[str, Any],
    context_input: dict[str, Any],
    boundary_head: str,
    boundary_tail: str,
    locator: dict[str, Any],
    config: ExtractionConfig | None = None,
) -> dict[str, Any]:
    """Build one bounded extraction request plus its audit metadata.

    ``locator`` is the exact C1-T5 chunk locator (job/revision/offsets/
    hashes); it is bound into the request metadata and every later run
    record, never injected into the candidate bundle (the C0
    ``evidence.locator`` shape is unchanged).
    """
    config = config or ExtractionConfig()
    if not isinstance(locator, dict) or locator.get("chunk_index") is None:
        raise PersistenceError("locator must carry at least the chunk index")
    prompt = build_extraction_prompt(
        chunk_text=chunk_text,
        section=section,
        document=document,
        context_input=context_input,
        boundary_head=boundary_head,
        boundary_tail=boundary_tail,
    )
    if len(prompt) > config.max_prompt_chars:
        raise PersistenceError(
            f"chunk extraction prompt ({len(prompt)} chars) exceeds "
            f"max_prompt_chars ({config.max_prompt_chars}); refusing to "
            "truncate context (fail closed)"
        )
    context_chars = len(json.dumps(context_input, ensure_ascii=False, sort_keys=True))
    return {
        "prompt": prompt,
        "request_meta": {
            "extraction_version": EXTRACTION_VERSION,
            "contract_version": CONTRACT_VERSION,
            "prompt_version": PROMPT_VERSION,
            "context_version": context_input.get("version"),
            "offset_unit": OFFSET_UNIT,
            "locator": copy.deepcopy(locator),
            "section": copy.deepcopy(section),
            "document": copy.deepcopy(document),
            "chunk_chars": len(chunk_text),
            "chunk_sha256": sha256_text(chunk_text),
            "context_chars": context_chars,
            "boundary_head_chars": len(boundary_head),
            "boundary_tail_chars": len(boundary_tail),
            "prompt_chars": len(prompt),
            "prompt_sha256": sha256_text(prompt),
            "config": config.to_dict(),
        },
    }


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_candidate_response(text: str) -> dict[str, Any]:
    """Parse plain JSON or one Markdown-fenced JSON object (C0 direction)."""
    if not isinstance(text, str) or not text.strip():
        raise ChunkModelError("model response is empty")
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise ChunkModelError("model response has an unterminated Markdown fence")
        first = lines[0].strip().lower()
        if first not in {"```", "```json", "```jsonc"}:
            raise ChunkModelError(f"unsupported model response fence: {lines[0].strip()}")
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ChunkModelError(
            f"model response is not valid JSON at line {exc.lineno} "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise ChunkModelError("model response must be one JSON object")
    return value


# ---------------------------------------------------------------------------
# Validation (mechanical only; mirrors the C0 validator direction)
# ---------------------------------------------------------------------------


def _items(bundle: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = bundle.get(name)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _identity(item: dict[str, Any], fallback: str) -> str:
    value = item.get("temp_id") or item.get("id")
    return str(value) if value is not None else fallback


def _inherited_time_texts(context_input: dict[str, Any]) -> set[str]:
    texts: set[str] = set()
    inherited = context_input.get("inherited_time")
    if isinstance(inherited, list):
        for item in inherited:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.add(item["text"])
    return texts


def _inherited_surfaces(context_input: dict[str, Any]) -> set[str]:
    surfaces: set[str] = set()
    for key in ("active_entities", "active_places"):
        items = context_input.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    surfaces.add(item["text"])
    return surfaces


def _warning_messages(bundle: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    warnings = bundle.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, dict):
                result.append(
                    (str(warning.get("type") or ""), str(warning.get("message") or ""))
                )
    return result


def _check_time(
    owner: str,
    value: Any,
    *,
    chunk_text: str,
    inherited_texts: set[str],
    verified_year: int | None,
    errors: list[str],
) -> None:
    if value is None:
        return  # Uncertainty preserved, not an error.
    if not isinstance(value, dict):
        errors.append(f"{owner} time must be an object or null")
        return
    original = value.get("original_text")
    if not isinstance(original, str) or not original:
        errors.append(f"{owner} time.original_text must be a non-empty string")
        return
    source_calendar = value.get("source_calendar")
    normalized = value.get("normalized")
    if not isinstance(source_calendar, dict):
        errors.append(f"{owner} time.source_calendar must be an object")
        return
    if not isinstance(normalized, dict):
        errors.append(f"{owner} time.normalized must be an object")
        return
    # Normalized precision is never invented at the chunk layer.
    if normalized.get("month") is not None:
        errors.append(f"{owner} fabricates normalized month from traditional calendar")
    if normalized.get("day") is not None:
        errors.append(f"{owner} fabricates normalized day from traditional calendar")
    year = normalized.get("year")
    if year is not None and (verified_year is None or year != verified_year):
        errors.append(
            f"{owner} normalized year {year!r} is not the document-verified year"
        )
    inherited_fields = source_calendar.get("inherited_fields")
    if original in chunk_text:
        return  # Explicit local time marker.
    if original in inherited_texts:
        if not isinstance(inherited_fields, list) or not inherited_fields:
            errors.append(
                f"{owner} time {original!r} is inherited but lists no inherited_fields"
            )
        return
    errors.append(
        f"{owner} time.original_text {original!r} is neither chunk text nor inherited time"
    )


def validate_chunk_candidate(
    bundle: dict[str, Any],
    *,
    chunk_text: str,
    context_input: dict[str, Any],
    section_label: str,
    document: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    allowed_predicates: list[str] | None = None,
) -> dict[str, Any]:
    """Return a deterministic validation report (no semantic gold layer).

    Categories mirror the C0 ``validation_report`` direction
    (schema/grounding/references/time_precision/predicate/assessment/
    authority), scoped to one chunk: evidence must be an exact substring
    of the current chunk text, and inherited time must stay verbatim
    without invented precision.
    """
    if not isinstance(bundle, dict):
        raise PersistenceError("candidate bundle must be a JSON object")
    _require_text(chunk_text, "chunk text")
    if not isinstance(context_input, dict):
        raise PersistenceError("context input must be a JSON object")
    if not isinstance(section_label, str) or not section_label:
        raise PersistenceError("section label must be a non-empty string")
    document = document or {}

    schema_errors: list[str] = []
    if schema is not None:
        from jsonschema import Draft202012Validator, FormatChecker

        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        found = sorted(validator.iter_errors(bundle), key=lambda e: list(e.absolute_path))
        for error in found:
            where = "/".join(str(part) for part in error.absolute_path) or "$"
            schema_errors.append(f"{where}: {error.message}")

    structural: list[str] = []
    for key in _TOP_LEVEL_KEYS:
        if key not in bundle:
            structural.append(f"bundle is missing required key {key!r}")
    if bundle.get("authoritative") is True:
        structural.append("candidate must never claim historical authority")
    if "context_state_next" in bundle or "context_state" in bundle:
        structural.append(
            "ContextState must travel beside the candidate, never inside it"
        )

    seen: set[str] = set()
    for collection in ("entities", "events", "claims"):
        records = bundle.get(collection)
        if records is not None and not isinstance(records, list):
            structural.append(f"bundle {collection} must be an array")
            continue
        for record in _items(bundle, collection):
            if "id" in record:
                structural.append(
                    f"{collection} record must not carry canonical identity "
                    f"({record.get('id')!r}); temp IDs only"
                )
            temp_id = record.get("temp_id")
            if not isinstance(temp_id, str) or not temp_id:
                structural.append(f"{collection} record requires a temp_id")
            elif temp_id in seen:
                structural.append(f"duplicate temp_id {temp_id!r} in bundle")
            else:
                seen.add(temp_id)

    grounding: list[str] = []
    references: list[str] = []
    entity_ids = {_identity(e, "") for e in _items(bundle, "entities")}
    event_ids = {_identity(e, "") for e in _items(bundle, "events")}
    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    source_id = _identity(source, "")

    inherited_surfaces = _inherited_surfaces(context_input)
    warning_texts = [
        message for kind, message in _warning_messages(bundle)
        if kind == INHERITED_ENTITY_WARNING
    ]

    for index, entity in enumerate(_items(bundle, "entities"), 1):
        owner = _identity(entity, f"entity[{index}]")
        canonical = str(entity.get("canonical_name") or "")
        mentions = entity.get("mentions") if isinstance(entity.get("mentions"), list) else []
        mention_texts = [
            str(m.get("text")) for m in mentions if isinstance(m, dict) and m.get("text")
        ]
        if canonical in chunk_text or any(t in chunk_text for t in mention_texts):
            continue
        names = [canonical, *mention_texts]
        if (
            canonical in inherited_surfaces
            or any(t in inherited_surfaces for t in mention_texts)
        ) and any(
            name and any(name in text for text in warning_texts) for name in names
        ):
            continue
        grounding.append(
            f"{owner} {canonical!r} has no mention in this chunk and no "
            f"{INHERITED_ENTITY_WARNING} warning"
        )

    for index, event in enumerate(_items(bundle, "events"), 1):
        event_id = _identity(event, f"event[{index}]")
        for participant in event.get("participants") or []:
            if isinstance(participant, dict):
                ref = str(participant.get("entity_ref"))
                if ref not in entity_ids:
                    references.append(f"{event_id} references missing entity {ref}")
        for ref in event.get("places") or []:
            if str(ref) not in entity_ids:
                references.append(f"{event_id} references missing place entity {ref}")
        parent = event.get("parent_event_ref")
        if parent is not None and str(parent) not in event_ids:
            references.append(f"{event_id} references missing parent event {parent}")

    for index, claim in enumerate(_items(bundle, "claims"), 1):
        claim_id = _identity(claim, f"claim[{index}]")
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        evidence_text = str(evidence.get("text") or "")
        if not evidence_text or evidence_text not in chunk_text:
            grounding.append(
                f"{claim_id} evidence is not an exact chunk-text substring: "
                f"{evidence_text!r}"
            )
        if source_id and str(evidence.get("source_ref")) != source_id:
            references.append(
                f"{claim_id} references unknown source {evidence.get('source_ref')}"
            )
        locator = evidence.get("locator") if isinstance(evidence.get("locator"), dict) else {}
        if locator.get("section") != section_label:
            grounding.append(
                f"{claim_id} evidence locator section {locator.get('section')!r} "
                f"does not match chunk section {section_label!r}"
            )
        for field in ("subject", "object"):
            ref = claim.get(field)
            if not isinstance(ref, dict):
                continue
            kind, identity = ref.get("kind"), str(ref.get("ref"))
            if kind == "entity_ref" and identity not in entity_ids:
                references.append(
                    f"{claim_id}.{field} references missing entity {identity}"
                )
            if kind == "event_ref" and identity not in event_ids:
                references.append(
                    f"{claim_id}.{field} references missing event {identity}"
                )

    time_precision: list[str] = []
    inherited_texts = _inherited_time_texts(context_input)
    verified_year = document.get("verified_normalized_year")
    if verified_year is not None and (
        not isinstance(verified_year, int) or isinstance(verified_year, bool)
    ):
        structural.append("document verified_normalized_year must be an integer or null")
        verified_year = None
    for index, event in enumerate(_items(bundle, "events"), 1):
        _check_time(
            _identity(event, f"event[{index}]"), event.get("time"),
            chunk_text=chunk_text, inherited_texts=inherited_texts,
            verified_year=verified_year, errors=time_precision,
        )
    for index, claim in enumerate(_items(bundle, "claims"), 1):
        _check_time(
            _identity(claim, f"claim[{index}]"), claim.get("time"),
            chunk_text=chunk_text, inherited_texts=inherited_texts,
            verified_year=verified_year, errors=time_precision,
        )

    predicate_errors: list[str] = []
    if allowed_predicates is not None:
        allowed = set(allowed_predicates)
        for index, claim in enumerate(_items(bundle, "claims"), 1):
            predicate = claim.get("predicate")
            if predicate not in allowed:
                predicate_errors.append(
                    f"{_identity(claim, f'claim[{index}]')} uses predicate "
                    f"outside configured vocabulary: {predicate}"
                )

    assessment: list[str] = []
    for index, claim in enumerate(_items(bundle, "claims"), 1):
        status = (
            (claim.get("assessment") or {}).get("status")
            if isinstance(claim.get("assessment"), dict)
            else None
        )
        if status != "unassessed":
            assessment.append(
                f"{_identity(claim, f'claim[{index}]')} assessment must start "
                f"unassessed, got {status!r}"
            )

    try:
        calendar_note = _check_calendar_note(bundle, chunk_text)
    except PersistenceError:  # pragma: no cover - defensive; helper is total
        calendar_note = []
    categories = {
        "schema_validation": list(schema_errors),
        "structural": list(structural),
        "grounding": list(grounding),
        "references": list(references),
        "time_precision": list(time_precision) + calendar_note,
        "predicate_vocabulary": list(predicate_errors),
        "assessment": list(assessment),
    }
    count = sum(len(values) for values in categories.values())
    return {
        "schema": "chronicle.chunk-extraction-validation",
        "version": "0.1",
        "extraction_version": EXTRACTION_VERSION,
        "contract_version": CONTRACT_VERSION,
        "passed": count == 0,
        "count": count,
        "errors": categories,
    }


def _check_calendar_note(bundle: dict[str, Any], chunk_text: str) -> list[str]:
    """Reject source-calendar months that contradict exact chunk evidence.

    A declared traditional source month is rejected only when the exact
    evidence/title surface occurs in the chunk under one different month
    marker (C0 validator direction, scoped to the chunk).
    """
    import re

    month_values = {
        "正": 1, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
    }
    month_re = re.compile(r"(?:春|夏|秋|冬)?(?:闰)?(?P<month>正|十一|十二|十|[一二三四五六七八九])月")

    def month_at(position: int) -> int | None:
        current: int | None = None
        for match in month_re.finditer(chunk_text, 0, max(position + 1, 0)):
            current = month_values[match.group("month")]
        return current

    def grounded_months(text: str) -> set[int]:
        months: set[int] = set()
        start = 0
        while True:
            position = chunk_text.find(text, start)
            if position < 0:
                break
            month = month_at(position)
            if month is not None:
                months.add(month)
            start = position + max(len(text), 1)
        return months

    def declared_month(value: Any) -> int | None:
        if not isinstance(value, dict):
            return None
        calendar = value.get("source_calendar")
        if not isinstance(calendar, dict):
            return None
        if calendar.get("system") != "chinese_lunisolar_regnal":
            return None
        month = calendar.get("month")
        return month if isinstance(month, int) and not isinstance(month, bool) else None

    errors: list[str] = []
    for index, event in enumerate(_items(bundle, "events"), 1):
        declared = declared_month(event.get("time"))
        if declared is None:
            continue
        months = grounded_months(str(event.get("title") or ""))
        if len(months) == 1 and declared != next(iter(months)):
            errors.append(
                f"{_identity(event, f'event[{index}]')} source month conflicts "
                f"with exact chunk title: expected {next(iter(months))}, got {declared}"
            )
    for index, claim in enumerate(_items(bundle, "claims"), 1):
        declared = declared_month(claim.get("time"))
        if declared is None:
            continue
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        months = grounded_months(str(evidence.get("text") or ""))
        if len(months) == 1 and declared != next(iter(months)):
            errors.append(
                f"{_identity(claim, f'claim[{index}]')} source month conflicts "
                f"with exact evidence: expected {next(iter(months))}, got {declared}"
            )
    return errors


def flatten_validation_errors(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for category, messages in (report.get("errors") or {}).items():
        for message in messages or []:
            result.append(f"{category}: {message}")
    return result


def _bounded_correction_prompt(
    *,
    chunk_text: str,
    request: dict[str, Any],
    document: dict[str, Any],
    context_input: dict[str, Any],
    validation_errors: list[str],
    previous_candidate: dict[str, Any],
    config: ExtractionConfig,
) -> str | None:
    """Build a correction prompt without ever widening the input budget.

    The preferred correction includes the prior candidate. Real long-form
    extraction can legitimately produce a candidate larger than the 8K input
    budget; in that case the prior candidate is omitted and the model is asked
    to regenerate the complete bundle from the immutable source plus exact
    deterministic errors. This keeps repair bounded without truncating either
    source or candidate and keeps every original raw response in attempt history.
    """
    prompt = build_extraction_prompt(
        chunk_text=chunk_text,
        section=request["request_meta"]["section"],
        document=document,
        context_input=context_input,
        boundary_head="",
        boundary_tail="",
        validation_errors=validation_errors,
        previous_candidate=previous_candidate,
    )
    if len(prompt) <= config.max_prompt_chars:
        return prompt
    fallback = build_extraction_prompt(
        chunk_text=chunk_text,
        section=request["request_meta"]["section"],
        document=document,
        context_input=context_input,
        boundary_head="",
        boundary_tail="",
        validation_errors=validation_errors,
        previous_candidate={
            "note": (
                "previous candidate omitted to keep this correction bounded; "
                "regenerate the complete bundle from CHUNK SOURCE TEXT and the "
                "deterministic validation errors"
            )
        },
    )
    if len(fallback) <= config.max_prompt_chars:
        return fallback
    return None


# ---------------------------------------------------------------------------
# Bounded extraction with replayable attempt history
# ---------------------------------------------------------------------------


def extract_chunk(
    provider: ChunkModelProvider,
    request: dict[str, Any],
    *,
    chunk_text: str,
    context_input: dict[str, Any],
    section_label: str,
    document: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    allowed_predicates: list[str] | None = None,
    config: ExtractionConfig | None = None,
) -> dict[str, Any]:
    """Run bounded extraction for one chunk; fail closed when ungroundable.

    Returns ``{"accepted": bool, "candidate": dict|None, "attempts": [...],
    "error": str|None}``. ``attempts`` holds one entry per model call
    (``kind`` initial/correction, prompt, raw response, validation
    report, candidate or parse error); at most
    ``1 + max_repair_attempts`` calls are ever made. A failed extraction
    records the failure instead of manufacturing a valid-looking result.

    ``schema`` selects the validation depth: with the Chronicle staged
    JSON Schema dict, candidates must be fully schema-valid; with
    ``schema=None`` only the structural/mechanical checks run. The
    production worker path always binds the schema and fails closed
    without it — ``schema=None`` exists for focused unit tests, never
    for production extraction.
    """
    config = config or ExtractionConfig()
    if not isinstance(request, dict) or not isinstance(request.get("prompt"), str):
        raise PersistenceError("request must carry the rendered prompt")
    document = document or {}
    attempts: list[dict[str, Any]] = []
    prompt = request["prompt"]
    candidate: dict[str, Any] | None = None

    for attempt_no in range(1 + config.max_repair_attempts):
        kind = "initial" if attempt_no == 0 else "correction"
        try:
            raw_response = provider.complete(prompt)
        except Exception as exc:
            attempts.append(
                {
                    "kind": kind,
                    "prompt": prompt,
                    "prompt_sha256": sha256_text(prompt),
                    "raw_response": None,
                    "raw_response_sha256": None,
                    "parse_error": f"model call failed: {exc}",
                    "validation": None,
                    "candidate": None,
                }
            )
            break
        if not isinstance(raw_response, str):
            raise PersistenceError("provider must return response text")
        if len(raw_response) > config.max_response_chars:
            size_error = (
                f"model response ({len(raw_response)} chars) exceeds "
                f"max_response_chars ({config.max_response_chars}); "
                "refusing to truncate (fail closed)"
            )
            attempts.append(
                {
                    "kind": kind,
                    "prompt": prompt,
                    "prompt_sha256": sha256_text(prompt),
                    "raw_response": raw_response,
                    "raw_response_sha256": sha256_text(raw_response),
                    "parse_error": size_error,
                    "validation": None,
                    "candidate": None,
                }
            )
            if attempt_no < config.max_repair_attempts:
                prompt = _bounded_correction_prompt(
                    chunk_text=chunk_text,
                    request=request,
                    document=document,
                    context_input=context_input,
                    validation_errors=[
                        "response_size: previous response exceeded the bounded "
                        f"response budget; return one complete compact JSON bundle "
                        f"under {config.max_response_chars} characters without "
                        "dropping distinct source-grounded facts"
                    ],
                    previous_candidate={
                        "note": (
                            "previous response omitted because it exceeded the "
                            "bounded response budget"
                        )
                    },
                    config=config,
                )
                if prompt is not None:
                    continue
                attempts.append(
                    {
                        "kind": "correction-skipped",
                        "prompt": None,
                        "prompt_sha256": None,
                        "raw_response": None,
                        "raw_response_sha256": None,
                        "parse_error": (
                            "correction prompt exceeds max_prompt_chars; "
                            "refusing to truncate (fail closed)"
                        ),
                        "validation": None,
                        "candidate": None,
                    }
                )
            break
        try:
            candidate = parse_candidate_response(raw_response)
            parse_error: str | None = None
        except ChunkModelError as exc:
            candidate = None
            parse_error = str(exc)
        if parse_error is not None:
            attempts.append(
                {
                    "kind": kind,
                    "prompt": prompt,
                    "prompt_sha256": sha256_text(prompt),
                    "raw_response": raw_response,
                    "raw_response_sha256": sha256_text(raw_response),
                    "parse_error": parse_error,
                    "validation": None,
                    "candidate": None,
                }
            )
            prompt = build_extraction_prompt(
                chunk_text=chunk_text,
                section=request["request_meta"]["section"],
                document=document,
                context_input=context_input,
                boundary_head="",
                boundary_tail="",
                validation_errors=[f"response_parse: {parse_error}"],
                previous_candidate={"note": "no parseable candidate was returned"},
            )
            continue
        report = validate_chunk_candidate(
            candidate,
            chunk_text=chunk_text,
            context_input=context_input,
            section_label=section_label,
            document=document,
            schema=schema,
            allowed_predicates=allowed_predicates,
        )
        attempts.append(
            {
                "kind": kind,
                "prompt": prompt,
                "prompt_sha256": sha256_text(prompt),
                "raw_response": raw_response,
                "raw_response_sha256": sha256_text(raw_response),
                "parse_error": None,
                "validation": report,
                "candidate": copy.deepcopy(candidate),
            }
        )
        if report["passed"]:
            return {
                "accepted": True,
                "candidate": candidate,
                "attempts": attempts,
                "error": None,
            }
        if attempt_no < config.max_repair_attempts:
            prompt = _bounded_correction_prompt(
                chunk_text=chunk_text,
                request=request,
                document=document,
                context_input=context_input,
                validation_errors=flatten_validation_errors(report),
                previous_candidate=candidate,
                config=config,
            )
            if prompt is None:
                attempts.append(
                    {
                        "kind": "correction-skipped",
                        "prompt": None,
                        "prompt_sha256": None,
                        "raw_response": None,
                        "raw_response_sha256": None,
                        "parse_error": (
                            "correction prompt exceeds max_prompt_chars; "
                            "refusing to truncate (fail closed)"
                        ),
                        "validation": None,
                        "candidate": None,
                    }
                )
                break

    last = attempts[-1] if attempts else None
    detail = "model call failed before any response"
    if last is not None:
        if last.get("parse_error"):
            detail = last["parse_error"]
        elif last.get("validation") is not None:
            detail = "; ".join(flatten_validation_errors(last["validation"]))
    return {
        "accepted": False,
        "candidate": None,
        "attempts": attempts,
        "error": (
            f"chunk extraction failed closed after {len(attempts)} attempt(s): {detail}"
        ),
    }


def build_chunk_run(
    *,
    request: dict[str, Any],
    provider_name: str,
    result: dict[str, Any],
    context_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the replayable ChunkRun checkpoint for ``ingestion_chunk_runs``.

    ``context_output`` (the forwarded ContextState) is stored beside the
    candidate under its own key, never merged into it.
    """
    if not isinstance(request, dict) or "request_meta" not in request:
        raise PersistenceError("request metadata is required for the run record")
    if not isinstance(provider_name, str) or not provider_name:
        raise PersistenceError("provider name must be a non-empty string")
    if not isinstance(result, dict) or "attempts" not in result:
        raise PersistenceError("extraction result with attempt history is required")
    if context_output is not None and (
        not isinstance(context_output, dict)
        or context_output.get("version") != EXPECTED_CONTEXT_VERSION
    ):
        raise PersistenceError(
            "forwarded context output must carry the current context version"
        )
    return {
        "extraction_version": EXTRACTION_VERSION,
        "contract_version": CONTRACT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model_version": provider_name,
        "request_meta": copy.deepcopy(request["request_meta"]),
        "attempts": copy.deepcopy(result["attempts"]),
        "attempt_count": len(result["attempts"]),
        "accepted": bool(result.get("accepted")),
        "candidate": copy.deepcopy(result.get("candidate")),
        "context_output": copy.deepcopy(context_output),
        "error": result.get("error"),
        "authoritative": False,
        "authority_note": NON_AUTHORITATIVE_NOTE,
    }


def build_accepted_checkpoint(
    *,
    candidate: dict[str, Any],
    run_attempt: int,
    locator: dict[str, Any],
    context_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the idempotent accepted-output layer for a chunk checkpoint.

    ``run_attempt`` names the producing ``ingestion_chunk_runs`` attempt so
    resume can prove a completed chunk already holds accepted output
    without re-running the model.
    """
    if not isinstance(candidate, dict):
        raise PersistenceError("accepted candidate must be a JSON object")
    if not isinstance(run_attempt, int) or run_attempt < 1:
        raise PersistenceError("run attempt must be a positive integer")
    if not isinstance(locator, dict):
        raise PersistenceError("locator must be a JSON object")
    return {
        "extraction_version": EXTRACTION_VERSION,
        "contract_version": CONTRACT_VERSION,
        "accepted": True,
        "candidate": copy.deepcopy(candidate),
        "produced_by_run_attempt": run_attempt,
        "locator": copy.deepcopy(locator),
        "context_output": copy.deepcopy(context_output),
        "authoritative": False,
        "authority_note": NON_AUTHORITATIVE_NOTE,
    }


def verify_history(
    run: dict[str, Any],
    *,
    chunk_text: str,
    context_input: dict[str, Any],
    section_label: str,
    document: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    allowed_predicates: list[str] | None = None,
) -> list[str]:
    """Replay validation over a stored run; return mismatches (empty = OK).

    For every attempt carrying both a raw response and a stored
    validation report, re-parse and re-validate and compare the
    pass/fail outcome plus the flattened error set. A mismatch means
    the history is not replayable and must fail closed downstream.
    """
    mismatches: list[str] = []
    attempts = run.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return ["run carries no attempt history"]
    for position, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict):
            mismatches.append(f"attempt {position} is not a JSON object")
            continue
        stored = attempt.get("validation")
        raw = attempt.get("raw_response")
        if stored is None or raw is None:
            continue  # Transport-failure attempts have nothing to replay.
        try:
            candidate = parse_candidate_response(raw)
        except ChunkModelError as exc:
            mismatches.append(f"attempt {position} no longer parses: {exc}")
            continue
        try:
            report = validate_chunk_candidate(
                candidate,
                chunk_text=chunk_text,
                context_input=context_input,
                section_label=section_label,
                document=document,
                schema=schema,
                allowed_predicates=allowed_predicates,
            )
        except PersistenceError as exc:
            mismatches.append(f"attempt {position} no longer validates: {exc}")
            continue
        if bool(report["passed"]) != bool(stored.get("passed")):
            mismatches.append(
                f"attempt {position} replay disagrees on outcome: stored "
                f"{stored.get('passed')!r} vs replay {report['passed']!r}"
            )
            continue
        if set(flatten_validation_errors(report)) != set(
            flatten_validation_errors(stored)
        ):
            mismatches.append(f"attempt {position} replay disagrees on error set")
    accepted = run.get("accepted")
    if accepted and not any(
        isinstance(a, dict)
        and a.get("validation") is not None
        and a["validation"].get("passed")
        for a in attempts
    ):
        mismatches.append("run claims accepted output with no passing attempt")
    if not accepted and any(
        isinstance(a, dict)
        and a.get("validation") is not None
        and a["validation"].get("passed")
        for a in attempts
    ):
        mismatches.append("run rejects output despite a passing attempt")
    return mismatches
