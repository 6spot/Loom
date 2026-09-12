"""Chronicle C2-R3-T01 person-state machine contract.

Pure deterministic validation/acceptance and DTO helpers for the
third-round person-state projection, with no database, network, model or
system-time access (Amendment 0006). Implements
``apps/chronicle/docs/person-state-reading.md`` sections 2-7 as
machine-checkable shared contracts consumed by T02-T15:

- :class:`PersonStateLimits` fixes the engineering envelope (phase /
  fact / assertion caps, per-unit phase bounds, page sizes).
- :func:`validate_person_state_candidate` validates a
  ``chronicle.chapter-candidate / 0.3``: it first reuses the frozen 0.2
  reading validator on the unchanged sub-document (so 0.1/0.2 semantics
  are not rewritten), then checks unit-phase coverage, local reference
  closure, phase DAG acyclicity, dimension/subject typing, continuity
  ordering and the canonical-ID/URL discipline.
- :func:`accept_person_state_candidate` accepts only passing candidates
  and emits a ``chronicle.chapter-artifact / 0.3`` with program-resolved
  reading units, the accepted ``person_states`` block, its hash and the
  stable ``person_state_candidates`` keys with resolved source anchors.
- :func:`remap_person_state_evidence` keeps one revision namespace and
  preserves origin chapter/local refs plus hashes.
- :func:`compile_person_state_projection` is the pre-publication pure
  compiler: it consumes only assessed facts and proven time order and
  emits immutable unit person summaries, full state items, changes and
  diagnostics. It never turns model confidence into certainty, never
  leaks a future title into the current identity and never lets a
  recommendation/posthumous attest become a current office.
- :func:`compile_person_state_disagreements` compiles a bounded
  immutable cross-source disagreement index.

``example_*`` builders and :func:`validate_person_state_dto` fix the
review/public read DTO shapes shared with ``person-state-types.ts``.
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
import reading_contract as _reading
from common import PersistenceError, canonical_json_bytes, sha256_json

#: Model-generatable candidate marker (third round).
CANDIDATE_SCHEMA = "chronicle.chapter-candidate"
CANDIDATE_VERSION = "0.3"

#: Program-accepted artifact marker (third round).
ARTIFACT_SCHEMA = "chronicle.chapter-artifact"
ARTIFACT_VERSION = "0.3"

#: Person-state machine contract version (enters fingerprints).
CONTRACT_VERSION = "person-state-contract/0.1"

#: Review + public read DTO bundle marker.
PERSON_STATE_SCHEMA = "chronicle.person-state"
PERSON_STATE_VERSION = "0.1"

#: Review package marker (chapter_state_evidence scope).
REVIEW_SCHEMA = "chronicle.person-state-review"
REVIEW_VERSION = "0.1"
REVIEW_MODE = "chapter_state_evidence"

#: Offset unit for every source coordinate.
OFFSET_UNIT = "chars-normalized-utf8"

PHASE_MODES = ("single", "process", "ambiguous", "unknown")
STATE_DIMENSIONS = ("office", "title", "affiliation")
PLACE_DIMENSIONS = ("administration", "control")
OPERATIONS = ("start", "end", "attest")
QUALIFICATIONS = ("ordinary", "recommendation", "self_designation", "posthumous", "reported")
ATTRIBUTIONS = ("narrator", "quotation", "annotation", "hearsay")
RELATIONS = ("serves", "attached_to")
CERTAINTIES = ("clear", "uncertain")
ASSESSMENTS = ("supported", "uncertain", "disputed", "rejected")
REASON_CODES = (
    "tenure_unproven",
    "order_unknown",
    "source_disagreement",
    "attribution_uncertain",
    "evidence_uncertain",
    "phase_not_reached",
    "phase_not_begun",
)
UNLIMITED_QUALIFICATIONS = ("recommendation", "posthumous")

#: Review scope contract (person-state-reading.md §5.1). The omitted
#: parameter keeps the legacy ``resolution`` default so the existing
#: review entry does not lose facts/prose when person_state is added.
REVIEW_SCOPES = ("resolution", "person_state", "all")
DEFAULT_REVIEW_SCOPE = "resolution"

#: Fixed HTTP statuses for the person-state read API.
PERSON_STATE_ERROR_CODES = {
    "bad_request": 400,
    "not_found": 404,
    "source_missing": 409,
    "source_mismatch": 409,
}

#: DTO names carried by ``chronicle-person-state-v0.1.schema.json``.
PERSON_STATE_DTO_NAMES = (
    "phase_summary",
    "source_fact_ref",
    "state_item",
    "state_change",
    "person_summary",
    "unit_people_page",
    "person_state_page",
    "evidence_descriptor",
    "state_evidence_page",
    "place_state_item",
    "place_state_page",
    "review_candidate",
    "review_package",
    "assessment_overlay",
)

#: Keys the model must never write inside ``person_states``.
FORBIDDEN_MODEL_KEYS = frozenset(
    {
        "supported",
        "certainty",
        "confidence",
        "canonical_id",
        "canonical_ids",
        "stream_id",
        "unit_id",
        "publication_id",
        "catalog_sha",
        "artifact_sha256",
        "state_manifest_sha",
        "item_id",
        "candidate_key",
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
CANDIDATE_V03_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-candidate-v0.3.schema.json"
ARTIFACT_V01_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.1.schema.json"
ARTIFACT_V02_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.2.schema.json"
ARTIFACT_V03_SCHEMA_PATH = SCHEMA_DIR / "chronicle-chapter-artifact-v0.3.schema.json"
PERSON_STATE_SCHEMA_PATH = SCHEMA_DIR / "chronicle-person-state-v0.1.schema.json"

CANDIDATE_V01_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.1.schema.json"
)
CANDIDATE_V02_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.2.schema.json"
)
CANDIDATE_V03_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-candidate-v0.3.schema.json"
)
ARTIFACT_V01_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.1.schema.json"
)
ARTIFACT_V02_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.2.schema.json"
)
ARTIFACT_V03_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-chapter-artifact-v0.3.schema.json"
)
PERSON_STATE_SCHEMA_ID = (
    "https://loom.local/chronicle/schemas/chronicle-person-state-v0.1.schema.json"
)


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PersonStateLimits:
    """Engineering envelope for person-state authoring and read responses.

    Defaults mirror ``person-state-reading.md`` §4/§7. They are
    resource-protection bounds, not model-capability guarantees.
    """

    max_phases: int = 512
    max_facts: int = 512
    max_assertions: int = 1024
    max_phases_per_unit: int = 8
    max_source_selections: int = 16
    summary_max_items: int = 3
    page_min_limit: int = 1
    page_max_limit: int = 50
    evidence_page_max_descriptors: int = 50
    summary_max_bytes: int = 128 * 1024
    detail_max_bytes: int = 128 * 1024
    evidence_max_bytes: int = 64 * 1024
    compiled_item_max_bytes: int = 64 * 1024
    json_max_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_phases",
            "max_facts",
            "max_assertions",
            "max_phases_per_unit",
            "max_source_selections",
            "summary_max_items",
            "page_min_limit",
            "page_max_limit",
            "evidence_page_max_descriptors",
            "summary_max_bytes",
            "detail_max_bytes",
            "evidence_max_bytes",
            "compiled_item_max_bytes",
            "json_max_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise PersistenceError(f"{name} must be a non-negative integer")
        if self.page_min_limit < 1:
            raise PersistenceError("page_min_limit must be at least 1")
        if self.page_max_limit < self.page_min_limit:
            raise PersistenceError("page_max_limit must be >= page_min_limit")
        if self.max_source_selections < 1:
            raise PersistenceError("max_source_selections must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


# ---------------------------------------------------------------------------
# Schema loading (0.3 reuses frozen 0.1/0.2 definitions by $ref)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _load_schema(path_str: str, expected_id: str) -> dict[str, Any]:
    path = Path(path_str)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PersistenceError(f"person-state schema unreadable at {path}: {exc}") from exc
    if not isinstance(schema, dict) or schema.get("$id") != expected_id:
        raise PersistenceError(
            f"person-state schema identity mismatch at {path}: expected $id {expected_id!r}"
        )
    return schema


@lru_cache(maxsize=8)
def _schema_bundle() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for path, schema_id in (
        (CANDIDATE_V01_SCHEMA_PATH, CANDIDATE_V01_SCHEMA_ID),
        (CANDIDATE_V02_SCHEMA_PATH, CANDIDATE_V02_SCHEMA_ID),
        (CANDIDATE_V03_SCHEMA_PATH, CANDIDATE_V03_SCHEMA_ID),
        (ARTIFACT_V01_SCHEMA_PATH, ARTIFACT_V01_SCHEMA_ID),
        (ARTIFACT_V02_SCHEMA_PATH, ARTIFACT_V02_SCHEMA_ID),
        (ARTIFACT_V03_SCHEMA_PATH, ARTIFACT_V03_SCHEMA_ID),
        (PERSON_STATE_SCHEMA_PATH, PERSON_STATE_SCHEMA_ID),
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


def candidate_v03_schema() -> dict[str, Any]:
    return _schema_bundle()[CANDIDATE_V03_SCHEMA_ID]


def artifact_v03_schema() -> dict[str, Any]:
    return _schema_bundle()[ARTIFACT_V03_SCHEMA_ID]


def person_state_schema() -> dict[str, Any]:
    return _schema_bundle()[PERSON_STATE_SCHEMA_ID]


def _iter_schema_errors(schema: Any, value: Any, *, registry: Any = None) -> list[str]:
    return _reading._iter_schema_errors(schema, value, registry=registry)


def validate_person_state_dto(name: str, value: Any) -> list[str]:
    """Validate one review/public DTO against ``chronicle-person-state / 0.1``."""
    if name not in PERSON_STATE_DTO_NAMES:
        raise PersistenceError(f"unknown person-state DTO {name!r}")
    schema = {
        "$defs": person_state_schema()["$defs"],
        "$ref": f"#/$defs/{name}",
    }
    return _iter_schema_errors(schema, value, registry=_registry())


# ---------------------------------------------------------------------------
# Ids and keys (program-owned, deterministic)
# ---------------------------------------------------------------------------


def item_id_for(*, chapter_id: str, fact_ref: str, dimension: str, phase_id: str,
                person_ref: str, operation: str) -> str:
    digest = sha256_json(
        {
            "contract": CONTRACT_VERSION,
            "chapter_id": chapter_id,
            "fact_ref": fact_ref,
            "dimension": dimension,
            "phase_id": phase_id,
            "person_ref": person_ref,
            "operation": operation,
        }
    )
    return "psi_" + digest[:24]


def candidate_key_for(*, kind: str, chapter_id: str, item_ref: str,
                      anchor_ids: list[str] | None = None) -> str:
    digest = sha256_json(
        {
            "contract": CONTRACT_VERSION,
            "kind": kind,
            "chapter_id": chapter_id,
            "item_ref": item_ref,
            "anchor_ids": sorted(anchor_ids or []),
        }
    )
    return "psc_" + digest[:24]


def disagreement_id_for(*, catalog_sha: str, fact_refs: list[str], topic: str) -> str:
    digest = sha256_json(
        {
            "contract": CONTRACT_VERSION,
            "catalog_sha": catalog_sha,
            "fact_refs": sorted(fact_refs),
            "topic": topic,
        }
    )
    return "psd_" + digest[:24]


def person_state_plan_fingerprint(
    *,
    accepted_artifact_hashes: list[str],
    assembled_hash: str,
    resolution_hashes: list[str],
    base_catalog_sha: str,
    candidate_keys: list[str],
) -> str:
    """The ``c2r3-person-state-review-plan-v1`` fingerprint input."""
    return sha256_json(
        {
            "contract": CONTRACT_VERSION,
            "plan": "c2r3-person-state-review-plan-v1",
            "accepted_artifact_hashes": sorted(accepted_artifact_hashes),
            "assembled_hash": assembled_hash,
            "resolution_hashes": sorted(resolution_hashes),
            "base_catalog_sha": base_catalog_sha,
            "candidate_keys": sorted(candidate_keys),
        }
    )


# ---------------------------------------------------------------------------
# Phase order (DAG)
# ---------------------------------------------------------------------------


def phase_topological_order(
    phases: list[dict[str, Any]], phase_orders: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Return ``(ordered_phase_ids, errors)`` for the supported precedence DAG.

    Only *proven* ``phase_orders`` edges order phases; unconnected phases
    keep a deterministic position. A cycle is a hard failure (the whole
    chapter is rejected) rather than an arbitrary tie-break.
    """
    phase_ids = sorted(p["phase_id"] for p in phases if isinstance(p, dict) and isinstance(p.get("phase_id"), str))
    known = set(phase_ids)
    edges: dict[str, set[str]] = {phase_id: set() for phase_id in phase_ids}
    indegree: dict[str, int] = {phase_id: 0 for phase_id in phase_ids}
    errors: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    for order in phase_orders:
        if not isinstance(order, dict):
            continue
        earlier = order.get("earlier_phase_ref")
        later = order.get("later_phase_ref")
        owner = f"phase_order {order.get('assertion_id')!r}"
        if earlier not in known or later not in known:
            errors.append(f"{owner} references an unknown phase")
            continue
        if earlier == later:
            errors.append(f"{owner} orders a phase relative to itself")
            continue
        pair = (earlier, later)
        if pair in seen_pairs:
            errors.append(f"{owner} duplicates a precedence edge")
            continue
        seen_pairs.add(pair)
        edges[earlier].add(later)
        indegree[later] += 1
    ready = sorted(phase_id for phase_id in phase_ids if indegree[phase_id] == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for neighbour in sorted(edges[current]):
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                ready.append(neighbour)
        ready.sort()
    if len(ordered) != len(phase_ids):
        cyclic = sorted(set(phase_ids) - set(ordered))
        errors.append(f"phase precedence forms a cycle: {cyclic}")
    return ordered, errors


def phase_ordinals(
    phases: list[dict[str, Any]], phase_orders: list[dict[str, Any]]
) -> dict[str, int]:
    ordered, _errors = phase_topological_order(phases, phase_orders)
    return {phase_id: index for index, phase_id in enumerate(ordered)}


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
                    f"{path}.{key} is program-owned; the model must not write "
                    "supported/certainty/canonical IDs/URLs/coordinates"
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


def _typed_ref(value: Any) -> tuple[str, str] | None:
    if isinstance(value, dict) and isinstance(value.get("kind"), str) and isinstance(value.get("ref"), str):
        return value["kind"], value["ref"]
    return None


def _ref_str(value: Any) -> str | None:
    parsed = _typed_ref(value)
    if parsed is None:
        return None
    return parsed[1]


def _selection_errors(
    selections: list[Any],
    request: dict[str, Any],
    request_blocks: dict[str, dict[str, Any]],
    owner: str,
    *,
    required: bool,
    limits: PersonStateLimits,
) -> list[str]:
    errors: list[str] = []
    if not selections:
        if required:
            errors.append(f"{owner} source_selections must have at least 1 entry")
        return errors
    if len(selections) > limits.max_source_selections:
        errors.append(
            f"{owner} source_selections has {len(selections)} entries above "
            f"max {limits.max_source_selections}"
        )
    for position, selection in enumerate(selections, 1):
        _anchor, error = _chapter.resolve_selection(
            selection,
            request=request,
            blocks_by_id=request_blocks,
            owner=f"{owner}.source_selections[{position}]",
        )
        if error:
            errors.append(error)
    return errors


def validate_person_state_candidate(
    request: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Validate a 0.3 candidate's ``person_states`` against its request.

    Reuses the frozen 0.2 reading validator on the unchanged sub-document
    first, then adds third-round coverage, reference, phase-graph,
    typing, continuity and canonical-ID checks. Any failing part rejects
    the whole candidate.
    """
    schema_errors: list[str] = []
    reading_errors: list[str] = []
    coverage: list[str] = []
    ref_errors: list[str] = []
    phase_errors: list[str] = []
    type_errors: list[str] = []
    continuity_errors: list[str] = []
    limit_errors: list[str] = []
    canonical_errors: list[str] = []

    limits = PersonStateLimits()

    if not isinstance(candidate, dict):
        schema_errors.append("candidate must be a JSON object")
        candidate = {}

    schema_errors.extend(
        _iter_schema_errors(candidate_v03_schema(), candidate, registry=_registry())
    )

    try:
        request_blocks = _chapter._require_request(request)
    except PersistenceError as exc:
        request_blocks = {}
        ref_errors.append(f"request: {exc}")

    # Reuse the frozen second-round semantics verbatim on the 0.2 subset.
    if isinstance(request, dict):
        subset = copy.deepcopy(candidate)
        subset.pop("person_states", None)
        subset["version"] = "0.2"
        try:
            reading_report = _reading.validate_reading_annotations(request, subset)
            reading_errors.extend(_reading.flatten_reading_errors(reading_report))
        except (TypeError, AttributeError, KeyError) as exc:  # fail closed
            reading_errors.append(f"second-round validation raised {type(exc).__name__}: {exc}")

    translation = candidate.get("translation") if isinstance(candidate.get("translation"), dict) else {}
    blocks = translation.get("blocks") if isinstance(translation.get("blocks"), list) else []
    block_by_id: dict[str, dict[str, Any]] = {}
    block_order: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("block_id"), str):
            block_id = block["block_id"]
            if block_id not in block_by_id:
                block_by_id[block_id] = block
                block_order.append(block_id)

    bundle = candidate.get("bundle") if isinstance(candidate.get("bundle"), dict) else {}
    entities = bundle.get("entities") if isinstance(bundle.get("entities"), list) else []
    events = bundle.get("events") if isinstance(bundle.get("events"), list) else []
    claims = bundle.get("claims") if isinstance(bundle.get("claims"), list) else []
    entity_by_id = {
        e["temp_id"]: e for e in entities if isinstance(e, dict) and isinstance(e.get("temp_id"), str)
    }
    event_ids = {e["temp_id"] for e in events if isinstance(e, dict) and isinstance(e.get("temp_id"), str)}
    claim_ids = {c["temp_id"] for c in claims if isinstance(c, dict) and isinstance(c.get("temp_id"), str)}

    person_states = candidate.get("person_states") if isinstance(candidate.get("person_states"), dict) else {}

    phases = _model_list(person_states.get("phases"), "person_states", "phases", coverage)
    phase_orders = _model_list(person_states.get("phase_orders"), "person_states", "phase_orders", coverage)
    unit_phases = _model_list(person_states.get("unit_phases"), "person_states", "unit_phases", coverage)
    facts = _model_list(person_states.get("facts"), "person_states", "facts", coverage)
    continuities = _model_list(person_states.get("continuities"), "person_states", "continuities", coverage)
    disagreements = _model_list(person_states.get("disagreements"), "person_states", "disagreements", coverage)

    if len(phases) > limits.max_phases:
        limit_errors.append(f"person_states has {len(phases)} phases above max {limits.max_phases}")
    if len(facts) > limits.max_facts:
        limit_errors.append(f"person_states has {len(facts)} facts above max {limits.max_facts}")
    for name, items in (
        ("phase_orders", phase_orders),
        ("continuities", continuities),
        ("disagreements", disagreements),
    ):
        if len(items) > limits.max_assertions:
            limit_errors.append(
                f"person_states has {len(items)} {name} above max {limits.max_assertions}"
            )

    phase_by_id: dict[str, dict[str, Any]] = {}
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        phase_id = phase.get("phase_id")
        if isinstance(phase_id, str):
            if phase_id in phase_by_id:
                coverage.append(f"duplicate phase_id {phase_id!r}")
            else:
                phase_by_id[phase_id] = phase
    fact_by_id: dict[str, dict[str, Any]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        fact_id = fact.get("fact_id")
        if isinstance(fact_id, str):
            if fact_id in fact_by_id:
                coverage.append(f"duplicate fact_id {fact_id!r}")
            else:
                fact_by_id[fact_id] = fact

    # Phase references close inside the chapter and use source evidence.
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        owner = f"person_states.phases[{index}]"
        for ref in _model_list(phase.get("event_refs"), owner, "event_refs", ref_errors):
            parsed = _typed_ref(ref)
            if parsed is None or parsed[0] != "event" or parsed[1] not in event_ids:
                ref_errors.append(f"{owner} event_ref {ref!r} is not a bundle event")
        ref_errors.extend(
            _selection_errors(
                _model_list(phase.get("source_selections"), owner, "source_selections", ref_errors),
                request, request_blocks, owner, required=True, limits=limits,
            )
        )

    ordered_phase_ids, order_errors = phase_topological_order(phases, phase_orders)
    phase_errors.extend(order_errors)

    bound_phases: set[str] = set()

    # Unit phase coverage: one binding per translation block, same order.
    if len(unit_phases) != len(blocks):
        coverage.append(
            f"person_states.unit_phases has {len(unit_phases)} entries but translation has "
            f"{len(blocks)} blocks"
        )
    for index, unit_phase in enumerate(unit_phases):
        owner = f"person_states.unit_phases[{index}]"
        if not isinstance(unit_phase, dict):
            coverage.append(f"{owner} must be an object")
            continue
        block_id = unit_phase.get("block_id")
        if index < len(block_order) and block_id != block_order[index]:
            coverage.append(
                f"{owner}.block_id {block_id!r} must match translation.blocks[{index}] "
                f"{block_order[index]!r} (order preserved)"
            )
        if not isinstance(block_id, str) or block_id not in block_by_id:
            ref_errors.append(f"{owner} references unknown translation block {block_id!r}")
        mode = unit_phase.get("mode")
        phase_refs = _model_list(unit_phase.get("phase_refs"), owner, "phase_refs", ref_errors)
        if len(phase_refs) > limits.max_phases_per_unit:
            limit_errors.append(
                f"{owner} has {len(phase_refs)} phase_refs above max {limits.max_phases_per_unit}"
            )
        for ref in phase_refs:
            if not isinstance(ref, str) or ref not in phase_by_id:
                ref_errors.append(f"{owner} references unknown phase {ref!r}")
            else:
                bound_phases.add(ref)
        if mode == "single" and len(phase_refs) != 1:
            phase_errors.append(f"{owner} single mode requires exactly one phase_ref")
        elif mode == "process" and len(phase_refs) < 2:
            phase_errors.append(f"{owner} process mode requires at least two phase_refs")
        elif mode == "ambiguous" and len(phase_refs) < 1:
            phase_errors.append(f"{owner} ambiguous mode requires at least one phase_ref")
        elif mode == "unknown" and phase_refs:
            phase_errors.append(f"{owner} unknown mode must not carry phase_refs")
        elif mode not in PHASE_MODES:
            phase_errors.append(f"{owner} has invalid mode {mode!r}")
        selections = _model_list(
            unit_phase.get("source_selections"), owner, "source_selections", ref_errors
        )
        if mode == "unknown" and selections:
            phase_errors.append(f"{owner} unknown mode must not carry source_selections")
        else:
            ref_errors.extend(
                _selection_errors(
                    selections, request, request_blocks, owner,
                    required=mode != "unknown", limits=limits,
                )
            )

    for phase_id in phase_by_id:
        if phase_id not in bound_phases:
            phase_errors.append(f"phase {phase_id!r} is not bound to any reading unit")

    # Facts: subject/dimension typing and closed local refs.
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            continue
        owner = f"person_states.facts[{index}]"
        fact_id = fact.get("fact_id")
        person = _typed_ref(fact.get("person_ref"))
        if person is None or person[0] != "entity" or person[1] not in entity_by_id:
            ref_errors.append(f"{owner} person_ref {fact.get('person_ref')!r} is not a bundle entity")
            person_entity = None
        else:
            person_entity = entity_by_id[person[1]]
        if person_entity is not None and person_entity.get("type") != "person":
            type_errors.append(
                f"{owner} person_ref {person[1]!r} is type {person_entity.get('type')!r}, not person"
            )
        dimension = fact.get("dimension")
        if dimension not in STATE_DIMENSIONS:
            type_errors.append(f"{owner} has invalid dimension {dimension!r}")
        value = _typed_ref(fact.get("value_ref"))
        target = _typed_ref(fact.get("target_ref"))
        if dimension in ("office", "title"):
            if value is None or value[0] != "entity" or value[1] not in entity_by_id:
                type_errors.append(f"{owner} {dimension} requires a bundle value_ref")
            else:
                value_entity = entity_by_id[value[1]]
                if value_entity.get("type") not in ("office", "other"):
                    type_errors.append(
                        f"{owner} {dimension} value {value[1]!r} is type "
                        f"{value_entity.get('type')!r}, not office/title"
                    )
            if fact.get("relation") is not None or target is not None:
                type_errors.append(f"{owner} {dimension} must not carry relation/target_ref")
        elif dimension == "affiliation":
            if fact.get("relation") not in RELATIONS:
                type_errors.append(f"{owner} affiliation requires relation serves|attached_to")
            if target is None or target[0] != "entity" or target[1] not in entity_by_id:
                type_errors.append(f"{owner} affiliation requires a bundle target_ref")
            else:
                target_entity = entity_by_id[target[1]]
                if target_entity.get("type") == "place":
                    type_errors.append(
                        f"{owner} affiliation target {target[1]!r} is a place, not a person/polity/organization"
                    )
            if value is not None:
                type_errors.append(f"{owner} affiliation must not carry value_ref")
        operation = fact.get("operation")
        if operation not in OPERATIONS:
            type_errors.append(f"{owner} has invalid operation {operation!r}")
        qualification = fact.get("qualification")
        if qualification not in QUALIFICATIONS:
            type_errors.append(f"{owner} has invalid qualification {qualification!r}")
        if qualification in UNLIMITED_QUALIFICATIONS and operation != "attest":
            type_errors.append(
                f"{owner} qualification {qualification!r} can only attest; it cannot start/end "
                "a current office"
            )
        attribution = fact.get("attribution")
        if attribution not in ATTRIBUTIONS:
            type_errors.append(f"{owner} has invalid attribution {attribution!r}")
        phase_ref = fact.get("phase_ref")
        if not isinstance(phase_ref, str) or phase_ref not in phase_by_id:
            ref_errors.append(f"{owner} references unknown phase {phase_ref!r}")
        for ref in _model_list(fact.get("claim_refs"), owner, "claim_refs", ref_errors):
            parsed = _typed_ref(ref)
            if parsed is None or parsed[0] != "claim" or parsed[1] not in claim_ids:
                ref_errors.append(f"{owner} claim_ref {ref!r} is not a bundle claim")
        ref_errors.extend(
            _selection_errors(
                _model_list(fact.get("source_selections"), owner, "source_selections", ref_errors),
                request, request_blocks, owner, required=True, limits=limits,
            )
        )
        if fact_id is None:
            continue

    # Continuities: fact + proven start-before-end, with source support.
    for index, continuity in enumerate(continuities):
        if not isinstance(continuity, dict):
            continue
        owner = f"person_states.continuities[{index}]"
        fact_ref = continuity.get("fact_ref")
        if not isinstance(fact_ref, str) or fact_ref not in fact_by_id:
            ref_errors.append(f"{owner} references unknown fact {fact_ref!r}")
        start = continuity.get("start_phase_ref")
        end = continuity.get("end_phase_ref")
        if not isinstance(start, str) or start not in phase_by_id:
            ref_errors.append(f"{owner} references unknown start phase {start!r}")
        if end is not None and (not isinstance(end, str) or end not in phase_by_id):
            ref_errors.append(f"{owner} references unknown end phase {end!r}")
        if isinstance(start, str) and start in phase_by_id and isinstance(end, str) and end in phase_by_id:
            ordinals = phase_ordinals(phases, phase_orders)
            if ordinals.get(start, 0) >= ordinals.get(end, 0):
                continuity_errors.append(
                    f"{owner} end phase {end!r} is not proven later than start phase {start!r}"
                )
        ref_errors.extend(
            _selection_errors(
                _model_list(continuity.get("source_selections"), owner, "source_selections", ref_errors),
                request, request_blocks, owner, required=True, limits=limits,
            )
        )

    # Disagreements: at least two facts on one comparable question.
    for index, disagreement in enumerate(disagreements):
        if not isinstance(disagreement, dict):
            continue
        owner = f"person_states.disagreements[{index}]"
        fact_refs = _model_list(disagreement.get("fact_refs"), owner, "fact_refs", ref_errors)
        if len(fact_refs) < 2:
            type_errors.append(f"{owner} requires at least two fact_refs")
        for fact_ref in fact_refs:
            if not isinstance(fact_ref, str) or fact_ref not in fact_by_id:
                ref_errors.append(f"{owner} references unknown fact {fact_ref!r}")
        for phase_ref in _model_list(disagreement.get("phase_refs"), owner, "phase_refs", ref_errors):
            if not isinstance(phase_ref, str) or phase_ref not in phase_by_id:
                ref_errors.append(f"{owner} references unknown phase {phase_ref!r}")
        ref_errors.extend(
            _selection_errors(
                _model_list(disagreement.get("source_selections"), owner, "source_selections", ref_errors),
                request, request_blocks, owner, required=True, limits=limits,
            )
        )

    if isinstance(person_states, dict):
        _scan_model_owned(person_states, "person_states", canonical_errors)

    errors = {
        "schema_validation": sorted(schema_errors),
        "reading": sorted(reading_errors),
        "person_state_coverage": sorted(coverage),
        "person_state_refs": sorted(ref_errors),
        "person_state_phase": sorted(phase_errors),
        "person_state_types": sorted(type_errors),
        "person_state_continuity": sorted(continuity_errors),
        "limits": sorted(limit_errors),
        "canonical_id": sorted(canonical_errors),
    }
    count = sum(len(values) for values in errors.values())
    return {
        "schema": "chronicle.person-state-validation",
        "version": PERSON_STATE_VERSION,
        "candidate_schema": CANDIDATE_SCHEMA,
        "candidate_version": CANDIDATE_VERSION,
        "contract_version": CONTRACT_VERSION,
        "passed": count == 0,
        "count": count,
        "errors": errors,
    }


def flatten_person_state_errors(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for category, messages in (report.get("errors") or {}).items():
        for message in messages or []:
            result.append(f"{category}: {message}")
    return result


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


def _resolve_item_anchors(
    item: dict[str, Any],
    request: dict[str, Any],
    request_blocks: dict[str, dict[str, Any]],
    owner: str,
) -> list[str]:
    anchor_ids: list[str] = []
    selections = item.get("source_selections")
    if not isinstance(selections, list):
        return anchor_ids
    for position, selection in enumerate(selections, 1):
        anchor, error = _chapter.resolve_selection(
            selection,
            request=request,
            blocks_by_id=request_blocks,
            owner=f"{owner}.source_selections[{position}]",
        )
        if error or anchor is None:
            raise PersistenceError(f"cannot resolve person-state anchor: {error}")
        anchor_ids.append(anchor["anchor_id"])
    return anchor_ids


def build_person_state_candidates(
    candidate: dict[str, Any], request: dict[str, Any]
) -> list[dict[str, Any]]:
    """Compute the stable review candidate keys for an accepted 0.3 candidate."""
    request_blocks = _chapter._require_request(request)
    person_states = candidate.get("person_states") if isinstance(candidate.get("person_states"), dict) else {}
    chapter_id = request["chapter_id"]
    candidates: list[dict[str, Any]] = []
    groups = (
        ("phase", "phases", "phase_id", ("phase_id",)),
        ("phase_order", "phase_orders", "assertion_id", ("earlier_phase_ref", "later_phase_ref")),
        ("unit_phase", "unit_phases", "block_id", ("phase_refs",)),
        ("fact", "facts", "fact_id", ("phase_ref",)),
        ("continuity", "continuities", "assertion_id", ("start_phase_ref", "end_phase_ref")),
        ("disagreement", "disagreements", "assertion_id", ("phase_refs",)),
    )
    for kind, key, id_field, phase_fields in groups:
        for index, item in enumerate(person_states.get(key) or []):
            if not isinstance(item, dict):
                continue
            item_ref = item.get(id_field)
            if not isinstance(item_ref, str):
                continue
            owner = f"person_states.{key}[{index}]"
            anchor_ids = _resolve_item_anchors(item, request, request_blocks, owner)
            phase_ids: list[str] = []
            for field in phase_fields:
                value = item.get(field)
                if isinstance(value, str):
                    phase_ids.append(value)
                elif isinstance(value, list):
                    phase_ids.extend(v for v in value if isinstance(v, str))
            source_fact_refs: list[str] = []
            if kind == "fact":
                source_fact_refs = [item_ref]
            elif kind == "continuity":
                source_fact_refs = [item["fact_ref"]] if isinstance(item.get("fact_ref"), str) else []
            elif kind == "disagreement":
                source_fact_refs = [r for r in item.get("fact_refs") or [] if isinstance(r, str)]
            candidates.append(
                {
                    "candidate_key": candidate_key_for(
                        kind=kind, chapter_id=chapter_id, item_ref=item_ref,
                        anchor_ids=sorted(set(anchor_ids)),
                    ),
                    "kind": kind,
                    "item_ref": item_ref,
                    "phase_ids": sorted(set(phase_ids)),
                    "anchor_ids": sorted(set(anchor_ids)),
                    "source_fact_refs": source_fact_refs,
                }
            )
    candidates.sort(key=lambda entry: (entry["kind"], entry["item_ref"], entry["candidate_key"]))
    return candidates


def accept_person_state_candidate(
    request: dict[str, Any],
    candidate: dict[str, Any],
    *,
    producing_run: dict[str, Any],
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept a passing 0.3 candidate and emit its bound 0.3 artifact.

    Validation is always recomputed; a caller-supplied ``report`` is only
    a consistency check and can never accept a bad candidate. Every
    program-bound value (hashes, offsets, unit IDs, candidate keys,
    anchors) is computed here, never read from the candidate.
    """
    if not isinstance(producing_run, dict):
        raise PersistenceError("producing_run must be a JSON object")
    for key in ("run_id", "model", "prompt_schema_version"):
        if not isinstance(producing_run.get(key), str) or not producing_run[key]:
            raise PersistenceError(f"producing_run requires non-empty {key!r}")
    fresh = validate_person_state_candidate(request, candidate)
    if report is not None:
        if not isinstance(report, dict):
            raise PersistenceError("supplied validation report must be a JSON object")
        if bool(report.get("passed")) != bool(fresh["passed"]) or set(
            flatten_person_state_errors(report)
        ) != set(flatten_person_state_errors(fresh)):
            raise PersistenceError(
                "supplied validation report does not match this request/candidate pair; "
                "refusing to accept (fail closed)"
            )
    if not fresh.get("passed"):
        detail = "; ".join(flatten_person_state_errors(fresh))
        raise PersistenceError(f"person-state candidate failed validation: {detail}")

    subset_v01 = copy.deepcopy(candidate)
    subset_v01.pop("person_states", None)
    subset_v01.pop("reading", None)
    subset_v01["version"] = "0.1"
    anchors = _chapter.collect_anchors(request, subset_v01)

    candidate_copy = copy.deepcopy(candidate)
    candidate_sha256 = sha256_json(candidate_copy)
    reading = copy.deepcopy(candidate_copy.get("reading"))
    reading_sha256 = sha256_json(reading)
    person_states = copy.deepcopy(candidate_copy.get("person_states"))
    person_states_sha256 = sha256_json(person_states)
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
        "person_states": person_states,
        "person_states_sha256": person_states_sha256,
    }
    artifact_sha256 = sha256_json(core)
    subset_v02 = copy.deepcopy(candidate)
    subset_v02.pop("person_states", None)
    subset_v02["version"] = "0.2"
    reading_units = _reading._resolve_reading_units(subset_v02, request, artifact_sha256)
    artifact = dict(core)
    artifact["artifact_sha256"] = artifact_sha256
    artifact["reading_units"] = reading_units
    artifact["person_state_candidates"] = build_person_state_candidates(
        candidate_copy, request
    )
    return artifact


# ---------------------------------------------------------------------------
# Remap: one revision namespace, preserved origin chapter/local refs + hash
# ---------------------------------------------------------------------------


def remap_person_state_evidence(
    chapter_artifacts: list[dict[str, Any]], revision_ref_map: dict[str, Any]
) -> list[dict[str, Any]]:
    """Remap accepted 0.3 artifacts into one revision namespace.

    Each returned evidence manifest keeps its origin chapter/local refs
    and content hashes; the caller's ``revision_ref_map`` may only relabel
    chapter/revision ids, never merge two chapters into one namespace or
    rewrite a local fact/phase ref. Output is stable for identical input.
    """
    if not isinstance(revision_ref_map, dict):
        raise PersistenceError("revision_ref_map must be a JSON object")
    manifests: list[dict[str, Any]] = []
    for artifact in chapter_artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("schema") != ARTIFACT_SCHEMA or artifact.get("version") != ARTIFACT_VERSION:
            raise PersistenceError("remap input must be chronicle.chapter-artifact / 0.3")
        chapter_id = artifact.get("chapter_id")
        mapping = revision_ref_map.get(chapter_id) if isinstance(chapter_id, str) else None
        mapping = mapping if isinstance(mapping, dict) else {}
        target_revision = mapping.get("revision_id", artifact.get("revision_id"))
        facts: list[dict[str, Any]] = []
        anchors_by_item = {
            entry.get("item_ref"): list(entry.get("anchor_ids") or [])
            for entry in artifact.get("person_state_candidates") or []
            if isinstance(entry, dict)
        }
        for fact in (artifact.get("person_states") or {}).get("facts") or []:
            if not isinstance(fact, dict):
                continue
            fact_ref = fact.get("fact_id")
            if not isinstance(fact_ref, str):
                continue
            facts.append(
                {
                    "origin_chapter_id": chapter_id,
                    "origin_revision_id": artifact.get("revision_id"),
                    "target_revision_id": target_revision,
                    "fact_ref": fact_ref,
                    "person_ref": fact.get("person_ref"),
                    "dimension": fact.get("dimension"),
                    "value_ref": fact.get("value_ref"),
                    "relation": fact.get("relation"),
                    "target_ref": fact.get("target_ref"),
                    "operation": fact.get("operation"),
                    "qualification": fact.get("qualification"),
                    "phase_ref": fact.get("phase_ref"),
                    "claim_refs": list(fact.get("claim_refs") or []),
                    "attribution": fact.get("attribution"),
                    "anchor_ids": anchors_by_item.get(fact_ref, []),
                    "artifact_sha256": artifact.get("artifact_sha256"),
                }
            )
        facts.sort(key=lambda entry: entry["fact_ref"])
        if facts:
            manifests.append(
                {
                    "chapter_id": chapter_id,
                    "origin_revision_id": artifact.get("revision_id"),
                    "target_revision_id": target_revision,
                    "artifact_sha256": artifact.get("artifact_sha256"),
                    "person_states_sha256": artifact.get("person_states_sha256"),
                    "facts": facts,
                }
            )
    manifests.sort(
        key=lambda entry: (
            entry["chapter_id"] or "",
            entry["origin_revision_id"] or "",
            entry["artifact_sha256"] or "",
        )
    )
    return manifests


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def _assessment_for(assessments: dict[str, Any], fact_ref: str) -> str:
    value = None
    if isinstance(assessments, dict):
        value = assessments.get(fact_ref)
    if value is None:
        return "uncertain"
    if value not in ASSESSMENTS:
        raise PersistenceError(f"unknown assessment {value!r} for {fact_ref!r}")
    return value


def compile_person_state_projection(
    evidence: dict[str, Any],
    assessments: dict[str, Any],
    canonical_map: dict[str, Any],
    reading_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compile the immutable person-state projection from assessed evidence.

    Only assessed facts participate. ``certainty`` is ``clear`` only for a
    supported fact whose phase is the current phase (or inside a proven
    continuity) with no applicable disagreement; anything else is
    ``uncertain`` with stable reason codes. A fact whose phase is after
    the current phase (``phase_not_reached``), an explicitly rejected
    fact, and a recommendation/posthumous attest never enter the current
    identity. Pure: no DB, network, model, UUID or system time.
    """
    if not isinstance(evidence, dict):
        raise PersistenceError("evidence must be a JSON object")
    if not isinstance(canonical_map, dict):
        raise PersistenceError("canonical_map must be a JSON object")
    if not isinstance(reading_manifest, dict):
        raise PersistenceError("reading_manifest must be a JSON object")

    phases = [p for p in evidence.get("phases") or [] if isinstance(p, dict)]
    phase_ordinal = {
        p["phase_id"]: index
        for index, p in enumerate(phases)
        if isinstance(p.get("phase_id"), str)
    }
    current_phase_id = reading_manifest.get("current_phase_id")
    current_ordinal = phase_ordinal.get(current_phase_id) if isinstance(current_phase_id, str) else None
    unit_phase = reading_manifest.get("unit_phase") if isinstance(reading_manifest.get("unit_phase"), dict) else {}
    manifest_phase = reading_manifest.get("phase_id")
    if current_ordinal is None and isinstance(manifest_phase, str):
        current_ordinal = phase_ordinal.get(manifest_phase)
        current_phase_id = manifest_phase

    continuities = [c for c in evidence.get("continuities") or [] if isinstance(c, dict)]
    disagreements = [d for d in evidence.get("disagreements") or [] if isinstance(d, dict)]
    disputed_facts: set[str] = set()
    for disagreement in disagreements:
        for ref in disagreement.get("fact_refs") or []:
            if isinstance(ref, str):
                disputed_facts.add(ref)

    items: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    people_items: dict[str, list[dict[str, Any]]] = {}
    place_items: list[dict[str, Any]] = []

    ordered_facts = sorted(
        (f for f in evidence.get("facts") or [] if isinstance(f, dict)),
        key=lambda f: (phase_ordinal.get(f.get("phase_ref"), 1 << 30), str(f.get("fact_ref"))),
    )

    for fact in ordered_facts:
        fact_ref = fact.get("fact_ref")
        if not isinstance(fact_ref, str):
            continue
        person_local = fact.get("person_ref")
        person_key, person_id = _resolve_canonical(person_local, canonical_map)
        if person_id is None:
            diagnostics.append({"fact_ref": fact_ref, "code": "unknown_person"})
            continue
        assessment = _assessment_for(assessments, fact_ref)
        if assessment == "rejected":
            diagnostics.append({"fact_ref": fact_ref, "code": "rejected", "person_id": person_id})
            continue
        phase_id = fact.get("phase_ref")
        fact_ordinal = phase_ordinal.get(phase_id)
        operation = fact.get("operation")
        qualification = fact.get("qualification")
        if current_ordinal is not None and fact_ordinal is not None:
            if fact_ordinal > current_ordinal:
                diagnostics.append(
                    {"fact_ref": fact_ref, "code": "phase_not_reached", "person_id": person_id}
                )
                continue

        reasons: list[str] = []
        current = False

        if operation == "end":
            # An end is a change, never a current identity.
            if assessment != "supported":
                reasons.append("source_disagreement" if assessment == "disputed" else "evidence_uncertain")
            changes.append(_change_record(fact, person_id, phase_id, assessment, reasons))
            continue

        if qualification in UNLIMITED_QUALIFICATIONS:
            # Recommendation/posthumous observe; they never establish a current office.
            reasons.append("attribution_uncertain")
            current = False
        elif assessment == "supported":
            covered = _covered_by_continuity(fact_ref, current_ordinal, continuities, phase_ordinal)
            if fact_ordinal is None or current_ordinal is None or fact_ordinal == current_ordinal or covered:
                current = True
            elif fact_ordinal < current_ordinal:
                reasons.append("tenure_unproven")
                current = False
        elif assessment == "disputed":
            reasons.append("source_disagreement")
        else:
            reasons.append("evidence_uncertain")

        if fact_ref in disputed_facts and "source_disagreement" not in reasons:
            reasons.append("source_disagreement")
        if fact.get("attribution") in ("quotation", "annotation", "hearsay"):
            if "attribution_uncertain" not in reasons:
                reasons.append("attribution_uncertain")
        if reasons:
            certainty = "uncertain"
        else:
            certainty = "clear"

        item = {
            "item_id": item_id_for(
                chapter_id=str(fact.get("chapter_id") or ""),
                fact_ref=fact_ref,
                dimension=str(fact.get("dimension")),
                phase_id=str(phase_id),
                person_ref=str(_ref_str(person_local)),
                operation=str(operation),
            ),
            "person_id": person_id,
            "dimension": fact.get("dimension"),
            "value": fact.get("value"),
            "relation": fact.get("relation"),
            "target": fact.get("target"),
            "target_id": _canonical_of(fact.get("target_ref"), canonical_map),
            "qualification": qualification,
            "certainty": certainty,
            "reason_codes": sorted(set(reasons)),
            "phase_ids": [phase_id] if isinstance(phase_id, str) else [],
            "current": current,
            "source_facts": [
                {
                    "chapter_publication_id": fact.get("chapter_publication_id"),
                    "chapter_id": fact.get("chapter_id"),
                    "revision_id": fact.get("revision_id"),
                    "fact_ref": fact_ref,
                    "claim_refs": [
                        _ref_str(r) for r in fact.get("claim_refs") or [] if _ref_str(r)
                    ],
                    "phase_id": phase_id,
                }
            ],
            "evidence_count": len(fact.get("anchor_ids") or []),
        }
        if certainty == "uncertain":
            item["reason_text"] = _reason_text(sorted(set(reasons)))
        else:
            item["reason_text"] = ""
        items.append(item)
        people_items.setdefault(person_id, []).append(item)

    compiled_people = {
        person_id: {
            "person_id": person_id,
            "items": sorted(
                people_items[person_id],
                key=lambda entry: (entry["dimension"], entry["item_id"]),
            ),
        }
        for person_id in sorted(people_items)
    }
    units = {
        unit_id: {
            "phase_mode": value.get("mode"),
            "phase_ids": list(value.get("phase_ids") or []),
            "people": [
                item["item_id"]
                for item in items
                if value.get("phase_ids") and item["phase_ids"] and item["phase_ids"][0] in (value.get("phase_ids") or [])
            ],
        }
        for unit_id, value in sorted(unit_phase.items())
        if isinstance(value, dict)
    }
    place_items.sort(key=lambda entry: entry["item_id"])

    return {
        "schema": "chronicle.person-state-projection",
        "version": PERSON_STATE_VERSION,
        "contract_version": CONTRACT_VERSION,
        "current_phase_id": current_phase_id,
        "people": compiled_people,
        "units": units,
        "items": items,
        "changes": changes,
        "places": place_items,
        "diagnostics": diagnostics,
        "counts": {
            "people": len(compiled_people),
            "items": len(items),
            "changes": len(changes),
            "places": len(place_items),
            "diagnostics": len(diagnostics),
        },
    }


def _resolve_canonical(
    local_ref: Any, canonical_map: dict[str, Any]
) -> tuple[str | None, str | None]:
    ref = _ref_str(local_ref)
    if ref is None:
        return None, None
    mapped = canonical_map.get(ref)
    if not isinstance(mapped, str) or not mapped:
        return ref, None
    return ref, mapped


def _canonical_of(local_ref: Any, canonical_map: dict[str, Any]) -> str | None:
    return _resolve_canonical(local_ref, canonical_map)[1]


def _covered_by_continuity(
    fact_ref: str,
    current_ordinal: int | None,
    continuities: list[dict[str, Any]],
    phase_ordinal: dict[str, int],
) -> bool:
    if current_ordinal is None:
        return False
    for continuity in continuities:
        if continuity.get("fact_ref") != fact_ref:
            continue
        start = phase_ordinal.get(continuity.get("start_phase_ref"))
        end = phase_ordinal.get(continuity.get("end_phase_ref"))
        if start is None:
            continue
        if end is None:
            if current_ordinal >= start:
                return True
        elif start <= current_ordinal < end:
            return True
    return False


def _reason_text(codes: list[str]) -> str:
    labels = {
        "tenure_unproven": "仅此前记载／任期未明",
        "order_unknown": "阶段先后不确定",
        "source_disagreement": "来源存在分歧",
        "attribution_uncertain": "引述／注文归属或限定未定",
        "evidence_uncertain": "有材料但结论仍不确定",
        "phase_not_reached": "属于当前阶段之后",
        "phase_not_begun": "尚未开始",
    }
    return "；".join(labels.get(code, code) for code in codes)


def _change_record(
    fact: dict[str, Any],
    person_id: str,
    phase_id: Any,
    assessment: str,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "item_id": item_id_for(
            chapter_id=str(fact.get("chapter_id") or ""),
            fact_ref=str(fact.get("fact_ref")),
            dimension=str(fact.get("dimension")),
            phase_id=str(phase_id),
            person_ref=str(_ref_str(fact.get("person_ref"))),
            operation=str(fact.get("operation")),
        ),
        "person_id": person_id,
        "dimension": fact.get("dimension"),
        "value": fact.get("value"),
        "relation": fact.get("relation"),
        "target": fact.get("target"),
        "operation": fact.get("operation"),
        "from_phase_id": fact.get("from_phase_id"),
        "to_phase_id": phase_id,
        "certainty": "uncertain" if reasons or assessment != "supported" else "clear",
        "reason_codes": sorted(set(reasons)),
        "source_facts": [],
    }


# ---------------------------------------------------------------------------
# Cross-source disagreement index
# ---------------------------------------------------------------------------


def compile_person_state_disagreements(
    base_index: list[dict[str, Any]],
    reviewed_links: list[dict[str, Any]],
    catalog_membership: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compile a bounded, immutable, deterministic disagreement index.

    Only reviewed links whose facts are members of the frozen catalog are
    selected. New links can add explanations and uncertain reasons; they
    can never promote a previously uncertain claim to clear on their own
    (the projection owns certainty). Output is sorted by disagreement id.
    """
    if not isinstance(catalog_membership, dict):
        raise PersistenceError("catalog_membership must be a JSON object")
    catalog_sha = catalog_membership.get("catalog_sha")
    if not isinstance(catalog_sha, str) or not catalog_sha:
        raise PersistenceError("catalog_membership requires catalog_sha")
    fact_members = catalog_membership.get("fact_refs") if isinstance(catalog_membership.get("fact_refs"), list) else None
    links: dict[str, dict[str, Any]] = {}
    for link in list(base_index) + list(reviewed_links):
        if not isinstance(link, dict):
            continue
        fact_refs = [r for r in link.get("fact_refs") or [] if isinstance(r, str)]
        if len(fact_refs) < 2:
            continue
        topic = link.get("topic") if isinstance(link.get("topic"), str) else " / ".join(sorted(fact_refs))
        if fact_members is not None and not set(fact_refs) <= set(fact_members):
            continue
        link_id = disagreement_id_for(catalog_sha=catalog_sha, fact_refs=fact_refs, topic=topic)
        candidate = {
            "disagreement_id": link_id,
            "catalog_sha": catalog_sha,
            "topic": topic,
            "fact_refs": sorted(set(fact_refs)),
            "phase_ids": sorted({r for r in link.get("phase_ids") or [] if isinstance(r, str)}),
            "reason_codes": sorted({r for r in link.get("reason_codes") or [] if r in REASON_CODES}),
        }
        existing = links.get(link_id)
        if existing is not None:
            candidate["reason_codes"] = sorted(
                set(existing["reason_codes"]) | set(candidate["reason_codes"])
            )
        links[link_id] = candidate
    return [links[key] for key in sorted(links)]


# ---------------------------------------------------------------------------
# Review scope (person-state-reading.md §5.1)
# ---------------------------------------------------------------------------


def normalize_review_scope(value: Any) -> str:
    """Map the omitted scope to ``resolution`` and reject unknown values.

    The current review entry keeps resolution (facts/prose) when no scope
    is given; ``all`` explicitly covers resolution + person_state +
    narrative. Unknown scopes fail closed as a 400-style error.
    """
    if value in (None, ""):
        return DEFAULT_REVIEW_SCOPE
    if not isinstance(value, str) or value not in REVIEW_SCOPES:
        raise PersistenceError(f"review_scope must be one of {REVIEW_SCOPES}, got {value!r}")
    return value


def review_scope_covers(scope: str, target: str) -> bool:
    scope = normalize_review_scope(scope)
    if scope == "all":
        return True
    return scope == target


def assert_link_kind_scope(scope: str, link_kind: Any) -> None:
    """``link_kind`` belongs to resolution only; mixing is a 400."""
    if link_kind in (None, ""):
        return
    if normalize_review_scope(scope) != "resolution":
        raise PersistenceError("link_kind can only be combined with review_scope=resolution")


# ---------------------------------------------------------------------------
# DTO example builders (contract examples, not historical answers)
# ---------------------------------------------------------------------------


def example_phase_summary(*, phase_id: str, label: str, ordinal: int, mode: str) -> dict[str, Any]:
    return {"phase_id": phase_id, "label": label, "ordinal": ordinal, "mode": mode}


def example_source_fact_ref(
    *,
    chapter_publication_id: str,
    chapter_id: str,
    revision_id: str,
    fact_ref: str,
    claim_refs: list[str] | None = None,
    phase_id: str,
) -> dict[str, Any]:
    return {
        "chapter_publication_id": chapter_publication_id,
        "chapter_id": chapter_id,
        "revision_id": revision_id,
        "fact_ref": fact_ref,
        "claim_refs": list(claim_refs or []),
        "phase_id": phase_id,
    }


def example_state_item(
    *,
    person_id: str,
    dimension: str,
    value: str | None,
    certainty: str,
    phase_ids: list[str],
    source_facts: list[dict[str, Any]],
    chapter_id: str,
    fact_ref: str,
    operation: str = "attest",
    person_ref: str | None = None,
    relation: str | None = None,
    target: str | None = None,
    target_id: str | None = None,
    qualification: str = "ordinary",
    reason_codes: list[str] | None = None,
    current: bool = False,
) -> dict[str, Any]:
    phase_id = phase_ids[0] if phase_ids else ""
    codes = sorted(set(reason_codes or []))
    return {
        "item_id": item_id_for(
            chapter_id=chapter_id,
            fact_ref=fact_ref,
            dimension=dimension,
            phase_id=phase_id,
            person_ref=person_ref or person_id,
            operation=operation,
        ),
        "person_id": person_id,
        "dimension": dimension,
        "value": value,
        "relation": relation,
        "target": target,
        "target_id": target_id,
        "qualification": qualification,
        "certainty": certainty,
        "reason_codes": codes,
        "reason_text": _reason_text(codes),
        "phase_ids": list(phase_ids),
        "current": current,
        "source_facts": list(source_facts),
        "evidence_count": sum(len(f.get("claim_refs") or []) for f in source_facts) or len(source_facts),
        "evidence_cursor": None,
    }


def example_state_change(
    *,
    person_id: str,
    dimension: str,
    value: str | None,
    operation: str,
    to_phase_id: str,
    chapter_id: str,
    fact_ref: str,
    certainty: str = "clear",
    person_ref: str | None = None,
    from_phase_id: str | None = None,
    relation: str | None = None,
    target: str | None = None,
    reason_codes: list[str] | None = None,
    source_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "item_id": item_id_for(
            chapter_id=chapter_id,
            fact_ref=fact_ref,
            dimension=dimension,
            phase_id=to_phase_id,
            person_ref=person_ref or person_id,
            operation=operation,
        ),
        "person_id": person_id,
        "dimension": dimension,
        "value": value,
        "relation": relation,
        "target": target,
        "operation": operation,
        "from_phase_id": from_phase_id,
        "to_phase_id": to_phase_id,
        "certainty": certainty,
        "reason_codes": sorted(set(reason_codes or [])),
        "source_facts": list(source_facts or []),
    }


def example_person_summary(
    *,
    person_id: str,
    name: str,
    identities: list[dict[str, Any]],
    changes: list[dict[str, Any]] | None = None,
    importance: str = "primary",
    phase_mode: str = "single",
    identity_count: int | None = None,
    change_count: int | None = None,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    identity_count = identity_count if isinstance(identity_count, int) else len(identities)
    changes = list(changes or [])
    change_count = change_count if isinstance(change_count, int) else len(changes)
    certainty = "uncertain" if any(item["certainty"] == "uncertain" for item in identities) else "clear"
    return {
        "person_id": person_id,
        "name": name,
        "importance": importance,
        "phase_mode": phase_mode,
        "certainty": certainty,
        "identities": identities[:3],
        "identity_count": identity_count,
        "has_more_identities": identity_count > len(identities[:3]),
        "identity_cursor": None,
        "changes": changes[:3],
        "change_count": change_count,
        "has_more_changes": change_count > len(changes[:3]),
        "change_cursor": None,
        "reason_codes": sorted(set(reason_codes or [])),
    }


def example_unit_people_page(
    *,
    stream_id: str,
    unit_id: str,
    catalog_sha: str,
    publication_id: str,
    state_manifest_sha: str,
    phase_mode: str,
    phases: list[dict[str, Any]],
    people: list[dict[str, Any]],
    limit: int = 6,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "stream_id": stream_id,
        "unit_id": unit_id,
        "catalog_sha": catalog_sha,
        "publication_id": publication_id,
        "state_manifest_sha": state_manifest_sha,
        "phase_mode": phase_mode,
        "phases": list(phases),
        "limit": limit,
        "people": list(people),
        "people_count": len(people),
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
    }


def example_person_state_page(
    *,
    stream_id: str,
    unit_id: str,
    catalog_sha: str,
    publication_id: str,
    state_manifest_sha: str,
    person_id: str,
    section: str,
    phase_id: str | None,
    phases: list[dict[str, Any]],
    items: list[dict[str, Any]] | None = None,
    changes: list[dict[str, Any]] | None = None,
    limit: int = 20,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    items = list(items or [])
    changes = list(changes or [])
    return {
        "stream_id": stream_id,
        "unit_id": unit_id,
        "catalog_sha": catalog_sha,
        "publication_id": publication_id,
        "state_manifest_sha": state_manifest_sha,
        "person_id": person_id,
        "section": section,
        "phase_id": phase_id,
        "phases": list(phases),
        "items": items,
        "changes": changes,
        "item_count": len(items) + len(changes),
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
    }


def example_evidence_descriptor(
    *,
    descriptor_id: str,
    source_publication_id: str,
    anchor_id: str,
    quote: str,
    source_title: str,
    phase_id: str,
    attribution: str = "narrator",
    relation: str = "support",
) -> dict[str, Any]:
    return {
        "descriptor_id": descriptor_id,
        "source_publication_id": source_publication_id,
        "anchor_id": anchor_id,
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        "attribution": attribution,
        "source_title": source_title,
        "phase_id": phase_id,
        "relation": relation,
    }


def example_state_evidence_page(
    *,
    stream_id: str,
    unit_id: str,
    catalog_sha: str,
    publication_id: str,
    state_manifest_sha: str,
    item_id: str,
    phase_id: str | None,
    descriptors: list[dict[str, Any]],
    limit: int = 50,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "stream_id": stream_id,
        "unit_id": unit_id,
        "catalog_sha": catalog_sha,
        "publication_id": publication_id,
        "state_manifest_sha": state_manifest_sha,
        "item_id": item_id,
        "section": "evidence",
        "phase_id": phase_id,
        "descriptors": list(descriptors),
        "descriptor_count": len(descriptors),
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
    }


def example_place_state_item(
    *,
    place_id: str,
    name: str,
    dimension: str,
    value: str | None,
    certainty: str,
    phase_ids: list[str],
    source_facts: list[dict[str, Any]],
    chapter_id: str,
    fact_ref: str,
    person_ref: str | None = None,
    controller: str | None = None,
    reason_codes: list[str] | None = None,
    current: bool = False,
) -> dict[str, Any]:
    phase_id = phase_ids[0] if phase_ids else ""
    codes = sorted(set(reason_codes or []))
    return {
        "item_id": item_id_for(
            chapter_id=chapter_id,
            fact_ref=fact_ref,
            dimension=dimension,
            phase_id=phase_id,
            person_ref=person_ref or place_id,
            operation="attest",
        ),
        "place_id": place_id,
        "name": name,
        "dimension": dimension,
        "value": value,
        "controller": controller,
        "certainty": certainty,
        "reason_codes": codes,
        "reason_text": _reason_text(codes),
        "phase_ids": list(phase_ids),
        "current": current,
        "source_facts": list(source_facts),
        "evidence_count": len(source_facts),
        "evidence_cursor": None,
    }


def example_place_state_page(
    *,
    stream_id: str,
    unit_id: str,
    catalog_sha: str,
    publication_id: str,
    state_manifest_sha: str,
    phases: list[dict[str, Any]],
    places: list[dict[str, Any]],
    limit: int = 20,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "stream_id": stream_id,
        "unit_id": unit_id,
        "catalog_sha": catalog_sha,
        "publication_id": publication_id,
        "state_manifest_sha": state_manifest_sha,
        "section": "places",
        "phases": list(phases),
        "places": list(places),
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
    }


def example_review_candidate(
    *,
    candidate_key: str,
    kind: str,
    chapter_id: str,
    item_ref: str,
    person_id: str | None,
    person_name: str | None,
    phase_refs: list[str],
    source_label: str,
    quote: str,
    predicted_effect: str,
    assessment_default: str = "uncertain",
    dimension: str | None = None,
    value: str | None = None,
    relation: str | None = None,
    target: str | None = None,
    operation: str | None = None,
    qualification: str | None = None,
    allowed_assessments: list[str] | None = None,
    attribution: str = "narrator",
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "candidate_key": candidate_key,
        "kind": kind,
        "chapter_id": chapter_id,
        "item_ref": item_ref,
        "person_id": person_id,
        "person_name": person_name,
        "dimension": dimension,
        "value": value,
        "relation": relation,
        "target": target,
        "operation": operation,
        "qualification": qualification,
        "phase_refs": list(phase_refs),
        "predicted_effect": predicted_effect,
        "assessment_default": assessment_default,
        "allowed_assessments": list(allowed_assessments or ["supported", "uncertain", "disputed", "rejected"]),
        "source_label": source_label,
        "quote": quote,
        "attribution": attribution,
        "reason_codes": sorted(set(reason_codes or [])),
    }


def example_review_package(
    *,
    review_id: str,
    plan_fingerprint: str,
    chapter_id: str,
    catalog_sha: str,
    candidates: list[dict[str, Any]],
    limit: int = 20,
    cursor: str | None = None,
    next_cursor: str | None = None,
    default_assessment: str = "uncertain",
) -> dict[str, Any]:
    return {
        "schema": REVIEW_SCHEMA,
        "version": REVIEW_VERSION,
        "review_id": review_id,
        "plan_fingerprint": plan_fingerprint,
        "scope": "person_state",
        "review_mode": REVIEW_MODE,
        "chapter_id": chapter_id,
        "catalog_sha": catalog_sha,
        "candidates": list(candidates),
        "candidate_count": len(candidates),
        "limit": limit,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
        "default_assessment": default_assessment,
    }


def example_assessment_overlay(
    *,
    plan_fingerprint: str,
    default_assessment: str,
    overrides: list[dict[str, Any]] | None = None,
    rationale: str = "",
) -> dict[str, Any]:
    return {
        "plan_fingerprint": plan_fingerprint,
        "default_assessment": default_assessment,
        "overrides": list(overrides or []),
        "rationale": rationale,
    }


def person_state_response_errors(name: str, value: Any) -> list[str]:
    """Schema errors plus the fixed byte/count budgets for one DTO."""
    errors = validate_person_state_dto(name, value)
    limits = PersonStateLimits()
    if name == "unit_people_page" and isinstance(value, dict):
        if len(canonical_json_bytes(value)) > limits.summary_max_bytes:
            errors.append(f"unit people page exceeds summary_max_bytes {limits.summary_max_bytes}")
        for person in value.get("people") or []:
            if not isinstance(person, dict):
                continue
            if len(person.get("identities") or []) > limits.summary_max_items:
                errors.append("person summary exposes more identities than summary_max_items")
            if len(person.get("changes") or []) > limits.summary_max_items:
                errors.append("person summary exposes more changes than summary_max_items")
    if name in ("person_state_page", "place_state_page") and isinstance(value, dict):
        if len(canonical_json_bytes(value)) > limits.detail_max_bytes:
            errors.append(f"person state page exceeds detail_max_bytes {limits.detail_max_bytes}")
        for item in (value.get("items") or []) + (value.get("changes") or []) + (value.get("places") or []):
            if isinstance(item, dict) and len(canonical_json_bytes(item)) > limits.compiled_item_max_bytes:
                errors.append("state item exceeds compiled_item_max_bytes")
    if name == "state_evidence_page" and isinstance(value, dict):
        if len(canonical_json_bytes(value)) > limits.evidence_max_bytes:
            errors.append(f"evidence page exceeds evidence_max_bytes {limits.evidence_max_bytes}")
        if len(value.get("descriptors") or []) > limits.evidence_page_max_descriptors:
            errors.append("evidence page has more descriptors than evidence_page_max_descriptors")
    if name == "review_package" and isinstance(value, dict):
        limit = value.get("limit")
        if isinstance(limit, int) and not (limits.page_min_limit <= limit <= limits.page_max_limit):
            errors.append(f"review package limit {limit} out of range")
    if len(canonical_json_bytes(value)) > limits.json_max_bytes:
        errors.append(f"DTO exceeds json_max_bytes {limits.json_max_bytes}")
    return errors


__all__ = [
    "ARTIFACT_SCHEMA",
    "ARTIFACT_VERSION",
    "ASSESSMENTS",
    "ATTRIBUTIONS",
    "CANDIDATE_SCHEMA",
    "CANDIDATE_VERSION",
    "CONTRACT_VERSION",
    "CERTAINTIES",
    "DEFAULT_REVIEW_SCOPE",
    "FORBIDDEN_MODEL_KEYS",
    "OFFSET_UNIT",
    "OPERATIONS",
    "PERSON_STATE_DTO_NAMES",
    "PERSON_STATE_ERROR_CODES",
    "PERSON_STATE_SCHEMA",
    "PERSON_STATE_VERSION",
    "PHASE_MODES",
    "PersonStateLimits",
    "QUALIFICATIONS",
    "REASON_CODES",
    "RELATIONS",
    "REVIEW_MODE",
    "REVIEW_SCHEMA",
    "REVIEW_SCOPES",
    "REVIEW_VERSION",
    "STATE_DIMENSIONS",
    "accept_person_state_candidate",
    "artifact_v03_schema",
    "assert_link_kind_scope",
    "build_person_state_candidates",
    "candidate_key_for",
    "candidate_v03_schema",
    "compile_person_state_disagreements",
    "compile_person_state_projection",
    "disagreement_id_for",
    "example_assessment_overlay",
    "example_evidence_descriptor",
    "example_person_state_page",
    "example_person_summary",
    "example_phase_summary",
    "example_place_state_item",
    "example_place_state_page",
    "example_review_candidate",
    "example_review_package",
    "example_source_fact_ref",
    "example_state_change",
    "example_state_evidence_page",
    "example_state_item",
    "example_unit_people_page",
    "flatten_person_state_errors",
    "item_id_for",
    "normalize_review_scope",
    "person_state_plan_fingerprint",
    "person_state_response_errors",
    "person_state_schema",
    "phase_ordinals",
    "phase_topological_order",
    "remap_person_state_evidence",
    "review_scope_covers",
    "validate_person_state_candidate",
    "validate_person_state_dto",
]
