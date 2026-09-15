"""Contract and prompt adapter for independently produced person histories.

The source-corroboration narrative contract is intentionally not extended for
this product.  A person history has a different subject boundary, two
independently accepted products (summary and prose), and an explicit optional
mapping to the already-published main history.  This module owns those
differences while keeping the T04/T05 model-node vocabulary reusable.

Canonical IDs, evidence IDs, approved-source-conclusion IDs and main-history
position IDs are program-owned handles.  Models see temporary handles in the
prompt; the adapter restores the persisted canonical values and validates
every reference before a candidate can reach the acceptance boundary.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from jsonschema import Draft202012Validator

from common import PersistenceError, canonical_json_bytes, sha256_json
from reader_language import narrative_text

VERSION = "0.1"
SCHEMA = "chronicle.person-history"
CONTEXT_SCHEMA = "chronicle.person-history-context"
PLAN_SCHEMA = "chronicle.person-history-plan"
MAX_SOURCES = 16
MAX_BYTES = 2 * 1024 * 1024
MAX_PROMPT_CHARS = 180_000

# The logical names deliberately retain facts/prose's generate/compare shape.
# The worker maps them to the configured T04/T05 model slots, so a separate
# scheduler or provider protocol is not introduced for this product.
PERSON_HISTORY_STEPS = (
    "summary_generate",
    "summary_compare",
    "prose_generate",
    "prose_compare",
)
NARRATIVE_STEPS = PERSON_HISTORY_STEPS
STEP_ALIASES = {
    "facts_generate": "summary_generate",
    "facts_compare": "summary_compare",
    "prose_generate": "prose_generate",
    "prose_compare": "prose_compare",
}

STATE_DIMENSIONS = ("office", "title", "allegiance")
CONCLUSION_DIMENSIONS = (*STATE_DIMENSIONS, "action", "related_person", "related_place")
QUALIFICATIONS = ("ordinary", "recommendation", "self_designation", "posthumous", "reported")


def _obj(properties: dict[str, Any], required: tuple[str, ...] | None = None) -> dict[str, Any]:
    required = tuple(properties) if required is None else required
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _text(maximum: int = 4096) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _array(items: dict[str, Any], minimum: int = 0, maximum: int = 256) -> dict[str, Any]:
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _enum(*values: str) -> dict[str, Any]:
    return {"enum": list(values)}


LOCAL_ID = {"type": "string", "pattern": "^[a-z][a-zA-Z0-9_-]{0,63}$"}
REF = _text(160)
SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
EVIDENCE = _obj(
    {
        "id": REF,
        "relation": _enum("support", "supplement", "contradict", "background"),
        "attribution": _text(300),
        "note": _text(1200),
    }
)

COVERAGE_SCHEMA = _obj(
    {
        "statement": _text(300),
        "exhaustive": {"const": False},
        "source_ids": _array(REF, 1, MAX_SOURCES),
        "publication_ids": _array(REF, 1, MAX_SOURCES),
    }
)

DATE_SCHEMA = _obj(
    {
        "text": _text(300),
        "certainty": _enum("clear", "uncertain"),
        "evidence": _array(EVIDENCE, 1, 32),
        "approved_conclusion_ids": _array(LOCAL_ID, 1, 64),
    }
)

PHASE_SCHEMA = _obj(
    {
        "id": LOCAL_ID,
        "label": _text(160),
        "year": _nullable({"type": "integer", "minimum": -9999, "maximum": 9999, "not": {"const": 0}}),
        "period": _nullable(_text(120)),
        "basis": _array(REF, 1, 64),
        "relation_to_previous": _enum("after", "contemporary", "uncertain"),
        "mapping_status": _enum("mapped", "ambiguous", "unmapped"),
        "mapping_position_ids": _array(LOCAL_ID, 0, 64),
        "mapping_reason": _text(1200),
    }
)

CONCLUSION_SCHEMA = _obj(
    {
        "id": LOCAL_ID,
        "person_id": REF,
        "dimension": _enum(*CONCLUSION_DIMENSIONS),
        "phase_ids": _array(LOCAL_ID, 1, 64),
        "text": _text(5000),
        "value": _nullable(_text(300)),
        "certainty": _enum("clear", "uncertain"),
        "qualification": _enum(*QUALIFICATIONS),
        "event_id": _nullable(REF),
        "related_entity_ids": _array(REF, 0, 32),
        "evidence": _array(EVIDENCE, 1, 64),
        "approved_conclusion_ids": _array(LOCAL_ID, 1, 64),
    }
)

SUMMARY_SCHEMA = _obj(
    {
        "schema": {"const": f"{SCHEMA}-summary"},
        "version": {"const": VERSION},
        "person_id": REF,
        "title": _text(240),
        "overview": _text(5000),
        "birth": _nullable(DATE_SCHEMA),
        "death": _nullable(DATE_SCHEMA),
        "coverage": COVERAGE_SCHEMA,
        "phases": _array(PHASE_SCHEMA, 1, 128),
        "conclusions": _array(CONCLUSION_SCHEMA, 1, 512),
    }
)

SEGMENT_SCHEMA = _obj(
    {
        "text": _text(8192),
        "conclusion_ids": _array(LOCAL_ID, 1, 64),
        "event_id": _nullable(REF),
        "related_entity_ids": _array(REF, 0, 32),
    }
)

PARAGRAPH_SCHEMA = _obj(
    {
        "id": LOCAL_ID,
        "phase_id": LOCAL_ID,
        "segments": _array(SEGMENT_SCHEMA, 1, 64),
    }
)

PROSE_SCHEMA = _obj(
    {
        "schema": {"const": f"{SCHEMA}-prose"},
        "version": {"const": VERSION},
        "person_id": REF,
        "summary_sha256": SHA,
        "coverage": COVERAGE_SCHEMA,
        "paragraphs": _array(PARAGRAPH_SCHEMA, 1, 512),
    }
)

COMPARISON_SCHEMA = _obj(
    {
        "schema": {"const": f"{SCHEMA}-comparison"},
        "version": {"const": VERSION},
        "product": _enum("summary", "prose"),
        "candidate_set_sha256": SHA,
        "selected_sha256": SHA,
        "selection_rationale": _text(3000),
        "differences": _array(
            _obj(
                {
                    "candidate_sha256": SHA,
                    "assessment": _enum("selected", "compatible", "rejected", "disputed"),
                    "rationale": _text(2400),
                    "evidence": _array(REF, 1, 64),
                }
            ),
            1,
            8,
        ),
        "disagreements": _array(
            _obj(
                {
                    "id": LOCAL_ID,
                    "message": _text(2000),
                    "evidence": _array(REF, 1, 64),
                }
            ),
            0,
            128,
        ),
    }
)


class PromptLimitExceeded(PersistenceError):
    """The complete fixed person/source context exceeds its input budget."""

    def __init__(self, step: str, prompt_chars: int, max_chars: int):
        self.step = step
        self.prompt_chars = prompt_chars
        self.max_chars = max_chars
        super().__init__(
            f"{step} complete context exceeds input budget "
            f"({prompt_chars} > {max_chars} characters); choose a smaller production scope, never truncate"
        )


def _fail(message: str) -> None:
    raise PersistenceError(f"person history: {message}")


def _structure(value: Any, schema: dict[str, Any]) -> None:
    if len(canonical_json_bytes(value)) > MAX_BYTES:
        _fail("candidate exceeds 2 MiB")
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: str(error.path))
    if errors:
        error = errors[0]
        _fail(f"{'/'.join(map(str, error.path))}: {error.message}")


def _unique(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result = {item["id"]: item for item in items}
    if len(result) != len(items):
        _fail(f"duplicate {label} id")
    return result


def _target(context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    target = context.get("target")
    if not isinstance(target, dict) or not isinstance(target.get("person_id"), str):
        _fail("context has no fixed canonical person")
    person_id = target["person_id"]
    entity = context.get("entities", {}).get(person_id)
    if not isinstance(entity, dict) or entity.get("kind") != "person":
        _fail("target person is not a published canonical person")
    return person_id, entity


def _source_indexes(context: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
    sources = context.get("sources")
    if not isinstance(sources, list) or not sources or len(sources) > MAX_SOURCES:
        _fail("context must contain 1–16 complete sources")
    source_by_id = {}
    evidence_by_id: dict[str, dict[str, Any]] = {}
    publication_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("source_id"), str):
            _fail("context source is invalid")
        source_id = source["source_id"]
        if source_id in source_by_id:
            _fail("context repeats a source id")
        source_by_id[source_id] = source
        publication_id = source.get("publication_id")
        if not isinstance(publication_id, str) or not publication_id:
            _fail("context source has no publication id")
        publication_ids.add(publication_id)
        evidence = source.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            _fail("each source must retain complete evidence anchors")
        for item in evidence:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                _fail("context evidence is invalid")
            if item["id"] in evidence_by_id:
                _fail("context repeats an evidence id")
            evidence_by_id[item["id"]] = {**item, "source_id": source_id, "publication_id": publication_id}
    return source_by_id, evidence_by_id, publication_ids


def _context_indexes(context: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    approved = context.get("approved_conclusions")
    if not isinstance(approved, list):
        _fail("context has no approved source conclusions")
    approved_by_id = {}
    for item in approved:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            _fail("approved source conclusion is invalid")
        if item["id"] in approved_by_id:
            _fail("context repeats an approved conclusion id")
        approved_by_id[item["id"]] = item
    positions = context.get("main_history_positions")
    if not isinstance(positions, list):
        _fail("context main-history positions must be an array")
    position_by_id = {}
    for item in positions:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            _fail("main-history position is invalid")
        if item["id"] in position_by_id:
            _fail("context repeats a main-history position id")
        position_by_id[item["id"]] = item
    entities = context.get("entities")
    events = context.get("events")
    if not isinstance(entities, dict) or not isinstance(events, dict):
        _fail("context canonical entity/event indexes are missing")
    return approved_by_id, position_by_id, entities


def evidence_index(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _source_indexes(context)[1]


def model_reference_maps(context: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return deterministic program-owned handles for the model prompt."""
    person_id, _ = _target(context)
    forward: dict[str, str] = {person_id: "person_001"}
    reverse: dict[str, str] = {"person_001": person_id}
    counters = {"person": 1, "place": 0, "entity": 0, "event": 0, "evidence": 0, "approved": 0, "history": 0}
    for canonical_id, entity in sorted((context.get("entities") or {}).items()):
        if canonical_id == person_id:
            continue
        kind = entity.get("kind") if isinstance(entity, dict) else None
        prefix = kind if kind in ("person", "place") else "entity"
        counters[prefix] += 1
        handle = f"{prefix}_{counters[prefix]:03}"
        forward[canonical_id] = handle
        reverse[handle] = canonical_id
    for event_id in sorted((context.get("events") or {})):
        counters["event"] += 1
        handle = f"event_{counters['event']:03}"
        forward[event_id] = handle
        reverse[handle] = event_id
    for evidence_id in sorted(evidence_index(context)):
        counters["evidence"] += 1
        handle = f"evidence_{counters['evidence']:03}"
        forward[evidence_id] = handle
        reverse[handle] = evidence_id
    for item in context.get("approved_conclusions") or []:
        value = item.get("id") if isinstance(item, dict) else None
        if not isinstance(value, str):
            continue
        counters["approved"] += 1
        handle = f"approved_{counters['approved']:03}"
        forward[value] = handle
        reverse[handle] = value
    for item in context.get("main_history_positions") or []:
        value = item.get("id") if isinstance(item, dict) else None
        if not isinstance(value, str):
            continue
        counters["history"] += 1
        handle = f"history_{counters['history']:03}"
        forward[value] = handle
        reverse[handle] = value
    return forward, reverse


def _map(value: Any, mapping: dict[str, str]) -> Any:
    return mapping.get(value, value) if isinstance(value, str) else value


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def map_candidate_references(value: Any, mapping: dict[str, str]) -> Any:
    """Map only typed reference fields; prose and local IDs stay untouched."""
    result = copy.deepcopy(value)
    if not isinstance(result, dict):
        return result
    for key in ("person_id", "summary_sha256"):
        # summary_sha256 is content, not an entity handle.
        if key == "person_id":
            result[key] = _map(result.get(key), mapping)
    for date in (result.get("birth"), result.get("death")):
        if isinstance(date, dict):
            for ref in _records(date.get("evidence")):
                ref["id"] = _map(ref.get("id"), mapping)
            date["approved_conclusion_ids"] = [_map(item, mapping) for item in date.get("approved_conclusion_ids", [])]
    for phase in _records(result.get("phases")):
        phase["basis"] = [_map(item, mapping) for item in phase.get("basis", [])]
        phase["mapping_position_ids"] = [_map(item, mapping) for item in phase.get("mapping_position_ids", [])]
    for conclusion in _records(result.get("conclusions")):
        conclusion["person_id"] = _map(conclusion.get("person_id"), mapping)
        conclusion["event_id"] = _map(conclusion.get("event_id"), mapping)
        conclusion["related_entity_ids"] = [_map(item, mapping) for item in conclusion.get("related_entity_ids", [])]
        conclusion["approved_conclusion_ids"] = [_map(item, mapping) for item in conclusion.get("approved_conclusion_ids", [])]
        for ref in _records(conclusion.get("evidence")):
            ref["id"] = _map(ref.get("id"), mapping)
    for paragraph in _records(result.get("paragraphs")):
        for segment in _records(paragraph.get("segments")):
            segment["event_id"] = _map(segment.get("event_id"), mapping)
            segment["related_entity_ids"] = [_map(item, mapping) for item in segment.get("related_entity_ids", [])]
    return result


def map_comparison_references(value: Any, mapping: dict[str, str]) -> Any:
    result = copy.deepcopy(value)
    if not isinstance(result, dict):
        return result
    for item in _records(result.get("differences")) + _records(result.get("disagreements")):
        item["evidence"] = [_map(ref, mapping) for ref in item.get("evidence", [])]
    return result


def model_context(context: dict[str, Any], forward: dict[str, str]) -> dict[str, Any]:
    result = copy.deepcopy(context)
    result["target"]["person_id"] = _map(result["target"]["person_id"], forward)
    result["entities"] = {forward[key]: value for key, value in context["entities"].items()}
    result["events"] = {forward[key]: value for key, value in context["events"].items()}
    result["approved_conclusions"] = []
    for item in context.get("approved_conclusions", []):
        if not isinstance(item, dict):
            continue
        mapped = {
            **item,
            "id": _map(item.get("id"), forward),
            "person_id": _map(item.get("person_id"), forward),
            "event_id": _map(item.get("event_id"), forward),
            "related_entity_ids": [_map(value, forward) for value in item.get("related_entity_ids", [])],
        }
        result["approved_conclusions"].append(mapped)
    result["main_history_positions"] = [
        {
            **item,
            "id": _map(item.get("id"), forward),
            "person_id": _map(item.get("person_id"), forward),
        }
        for item in context.get("main_history_positions", [])
        if isinstance(item, dict)
    ]
    for source in result.get("sources", []):
        source["canonical_refs"] = {
            kind: {key: _map(value, forward) for key, value in refs.items()}
            for kind, refs in source.get("canonical_refs", {}).items()
        }
        source["evidence"] = [
            {**item, "id": _map(item.get("id"), forward)} for item in source.get("evidence", [])
        ]
        source["reviewed_person_states"] = [
            {
                **state,
                "person_id": _map(state.get("person_id"), forward),
                "target": (
                    {**state["target"], "ref": _map(state["target"].get("ref"), forward)}
                    if isinstance(state.get("target"), dict) else state.get("target")
                ),
            }
            for state in source.get("reviewed_person_states", [])
            if isinstance(state, dict)
        ]
    return result


def _coverage_errors(candidate: dict[str, Any], context: dict[str, Any], errors: list[str]) -> None:
    selection = context.get("source_selection") or {}
    expected_sources = [source.get("source_id") for source in context.get("sources", [])]
    expected_publications = [source.get("publication_id") for source in context.get("sources", [])]
    coverage = candidate.get("coverage")
    if coverage.get("exhaustive") is not False:
        errors.append("coverage must explicitly be non-exhaustive")
    if coverage.get("statement") != "根据当前收录资料整理的经历":
        errors.append("coverage must say 根据当前收录资料整理的经历")
    if coverage.get("source_ids") != expected_sources or coverage.get("publication_ids") != expected_publications:
        errors.append("coverage must name every selected complete source in order")
    if selection.get("publication_ids") != expected_publications:
        errors.append("context source selection and complete source descriptors differ")


def _approved_source_ids(
    ids: set[str], approved_by_id: dict[str, dict[str, Any]], *, label: str, errors: list[str]
) -> set[str]:
    source_ids: set[str] = set()
    for approved_id in ids:
        item = approved_by_id.get(approved_id)
        if item is None:
            continue
        source_id = item.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{label} cites an approved conclusion without a source binding")
            continue
        source_ids.add(source_id)
    return source_ids


def _source_binding_errors(
    *, label: str, approved_ids: set[str], evidence_ids: set[str],
    approved_by_id: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    approved_sources = _approved_source_ids(
        approved_ids, approved_by_id, label=label, errors=errors
    )
    evidence_sources = {
        evidence[evidence_id]["source_id"]
        for evidence_id in evidence_ids
        if evidence_id in evidence
    }
    if approved_sources - evidence_sources:
        errors.append(f"{label} approved conclusions are not bound to its cited source evidence")


def _date_errors(
    value: Any, name: str, approved_by_id: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]], errors: list[str],
) -> None:
    if value is None:
        return
    refs = {item.get("id") for item in value.get("evidence", [])}
    if not refs <= set(evidence):
        errors.append(f"{name} cites evidence outside the frozen context")
    approved_ids = set(value.get("approved_conclusion_ids", []))
    if not approved_ids <= set(approved_by_id):
        errors.append(f"{name} cites an unknown approved conclusion")
    _source_binding_errors(
        label=name, approved_ids=approved_ids, evidence_ids=refs,
        approved_by_id=approved_by_id, evidence=evidence, errors=errors,
    )


def validate_summary(candidate: Any, context: dict[str, Any]) -> dict[str, Any]:
    _structure(candidate, SUMMARY_SCHEMA)
    if narrative_text(candidate) != candidate:
        _fail("reader-visible title, overview, phases and conclusions must use simplified Chinese")
    person_id, _ = _target(context)
    source_by_id, evidence, _publications = _source_indexes(context)
    approved_by_id, positions, entities = _context_indexes(context)
    errors: list[str] = []
    if candidate["person_id"] != person_id:
        errors.append("summary person_id is not the fixed canonical person")
    _coverage_errors(candidate, context, errors)
    phases = _unique(candidate["phases"], "phase")
    conclusions = _unique(candidate["conclusions"], "conclusion")
    previous_year: int | None = None
    for phase in phases.values():
        if set(phase["basis"]) - set(evidence):
            errors.append(f"phase {phase['id']} cites evidence outside the frozen context")
        if phase["mapping_status"] == "unmapped" and phase["mapping_position_ids"]:
            errors.append(f"phase {phase['id']} marked unmapped but carries a main-history position")
        if phase["mapping_status"] in ("mapped", "ambiguous") and not phase["mapping_position_ids"]:
            errors.append(f"phase {phase['id']} declares a mapping without a position")
        if set(phase["mapping_position_ids"]) - set(positions):
            errors.append(f"phase {phase['id']} cites an unknown main-history position")
        if phase["year"] is not None and previous_year is not None and phase["year"] < previous_year:
            errors.append("phases must be in chronological order")
        if phase["year"] is not None:
            previous_year = phase["year"]
    for date_name in ("birth", "death"):
        _date_errors(candidate[date_name], date_name, approved_by_id, evidence, errors)
    entity_kinds = {key: (value.get("kind") if isinstance(value, dict) else None) for key, value in entities.items()}
    for conclusion in conclusions.values():
        if conclusion["person_id"] != person_id:
            errors.append(f"conclusion {conclusion['id']} changes the fixed person identity")
        if set(conclusion["phase_ids"]) - set(phases):
            errors.append(f"conclusion {conclusion['id']} cites an unknown phase")
        refs = {item.get("id") for item in conclusion["evidence"]}
        if not refs <= set(evidence):
            errors.append(f"conclusion {conclusion['id']} cites evidence outside the frozen context")
        if not any(item.get("relation") in ("support", "supplement") for item in conclusion["evidence"]):
            errors.append(f"conclusion {conclusion['id']} has no supporting source evidence")
        approved_ids = set(conclusion["approved_conclusion_ids"])
        if not approved_ids <= set(approved_by_id):
            errors.append(f"conclusion {conclusion['id']} cites an unknown approved conclusion")
        _source_binding_errors(
            label=f"conclusion {conclusion['id']}",
            approved_ids=approved_ids,
            evidence_ids=refs,
            approved_by_id=approved_by_id,
            evidence=evidence,
            errors=errors,
        )
        if conclusion["dimension"] in STATE_DIMENSIONS and not conclusion["value"]:
            errors.append(f"state conclusion {conclusion['id']} must carry a value")
        if conclusion["dimension"] == "action" and conclusion["value"] is not None:
            errors.append(f"action conclusion {conclusion['id']} must keep state value null")
        related = conclusion["related_entity_ids"]
        if conclusion["dimension"] == "related_person" and not any(entity_kinds.get(item) == "person" for item in related):
            errors.append(f"related-person conclusion {conclusion['id']} has no canonical person link")
        if conclusion["dimension"] == "related_place" and not any(entity_kinds.get(item) == "place" for item in related):
            errors.append(f"related-place conclusion {conclusion['id']} has no canonical place link")
        if set(related) - set(entity_kinds):
            errors.append(f"conclusion {conclusion['id']} cites an unknown canonical related entity")
        if conclusion["event_id"] is not None and conclusion["event_id"] not in context.get("events", {}):
            errors.append(f"conclusion {conclusion['id']} cites an unknown canonical event")
    if errors:
        _fail("; ".join(errors))
    return copy.deepcopy(candidate)


def validate_prose(candidate: Any, context: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    _structure(candidate, PROSE_SCHEMA)
    if narrative_text(candidate) != candidate:
        _fail("reader-visible person prose must use simplified Chinese")
    person_id, _ = _target(context)
    source_by_id, evidence, _publications = _source_indexes(context)
    approved_by_id, positions, entities = _context_indexes(context)
    validate_summary(summary, context)
    errors: list[str] = []
    if candidate["person_id"] != person_id:
        errors.append("prose person_id is not the fixed canonical person")
    if candidate["summary_sha256"] != sha256_json(summary):
        errors.append("prose is not bound to the accepted summary")
    _coverage_errors(candidate, context, errors)
    phases = {item["id"]: item for item in summary["phases"]}
    conclusions = {item["id"]: item for item in summary["conclusions"]}
    paragraphs = _unique(candidate["paragraphs"], "paragraph")
    seen_phases: list[str] = []
    for paragraph in candidate["paragraphs"]:
        phase_id = paragraph["phase_id"]
        if phase_id not in phases:
            errors.append(f"paragraph {paragraph['id']} cites an unknown phase")
        if seen_phases and phase_id != seen_phases[-1]:
            seen_phases.append(phase_id)
        elif not seen_phases:
            seen_phases.append(phase_id)
        for segment in paragraph["segments"]:
            cited = set(segment["conclusion_ids"])
            if not cited <= set(conclusions):
                errors.append(f"paragraph {paragraph['id']} contains an unreviewed conclusion")
                continue
            if phase_id in phases and any(phase_id not in conclusions[item]["phase_ids"] for item in cited):
                errors.append(f"paragraph {paragraph['id']} cites a conclusion outside its phase")
            if segment["event_id"] is not None:
                matching = [conclusions[item].get("event_id") for item in cited]
                if segment["event_id"] not in matching:
                    errors.append(f"paragraph {paragraph['id']} event is not carried by its cited conclusion")
            related = {
                related_id
                for conclusion_id in cited
                for related_id in conclusions[conclusion_id].get("related_entity_ids", [])
            }
            if set(segment["related_entity_ids"]) - related:
                errors.append(f"paragraph {paragraph['id']} related entity is not carried by its cited conclusion")
            if set(segment["related_entity_ids"]) - set(entities):
                errors.append(f"paragraph {paragraph['id']} cites an unknown canonical related entity")
    if set(phases) - {item["phase_id"] for item in candidate["paragraphs"]}:
        errors.append("prose must represent every ordered life phase")
    # A non-contiguous phase order would allow a later state to leak backwards.
    order = {phase_id: index for index, phase_id in enumerate(phases)}
    numeric = [order[item["phase_id"]] for item in candidate["paragraphs"] if item["phase_id"] in order]
    if numeric != sorted(numeric):
        errors.append("prose paragraphs must follow the summary phase order")
    if errors:
        _fail("; ".join(errors))
    return copy.deepcopy(candidate)


def validate_comparison(candidate: Any, context: dict[str, Any], product: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    _structure(candidate, COMPARISON_SCHEMA)
    if candidate["product"] != product:
        _fail("comparison product does not match the fixed step")
    if not isinstance(candidates, list) or not candidates or len(candidates) > 4:
        _fail("comparison requires 1–4 fixed complete candidates")
    expected = sha256_json(candidates)
    if candidate["candidate_set_sha256"] != expected:
        _fail("comparison changed its fixed candidate set")
    hashes = {item.get("candidate_sha256") for item in candidates}
    if candidate["selected_sha256"] not in hashes:
        _fail("comparison selected a candidate outside the fixed set")
    differences = candidate["differences"]
    if {item["candidate_sha256"] for item in differences} != hashes or len(differences) != len(hashes):
        _fail("comparison must describe every fixed candidate exactly once")
    if sum(item["assessment"] == "selected" for item in differences) != 1:
        _fail("comparison must mark exactly one selected candidate")
    if not any(item["candidate_sha256"] == candidate["selected_sha256"] and item["assessment"] == "selected" for item in differences):
        _fail("comparison selected hash and selected assessment differ")
    evidence = set(evidence_index(context))
    if any(set(item["evidence"]) - evidence for item in differences):
        _fail("comparison cites evidence outside the frozen context")
    if any(set(item["evidence"]) - evidence for item in candidate.get("disagreements", [])):
        _fail("comparison disagreement cites evidence outside the frozen context")
    return copy.deepcopy(candidate)


def step_schema(step: str) -> dict[str, Any]:
    step = STEP_ALIASES.get(step, step)
    if step == "summary_generate":
        return copy.deepcopy(SUMMARY_SCHEMA)
    if step == "prose_generate":
        return copy.deepcopy(PROSE_SCHEMA)
    if step in ("summary_compare", "prose_compare"):
        return copy.deepcopy(COMPARISON_SCHEMA)
    _fail(f"unknown person-history step {step!r}")


def _prompt_input(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    context = data.get("context")
    if not isinstance(context, dict):
        _fail("step requires the frozen person-history context")
    forward, reverse = model_reference_maps(context)
    return context, forward, reverse


def build_step_prompt(step: str, data: dict[str, Any], *, max_chars: int = MAX_PROMPT_CHARS) -> str:
    step = STEP_ALIASES.get(step, step)
    context, forward, _reverse = _prompt_input(data)
    schema = step_schema(step)
    instructions = (
        "你是史料编辑。只根据 INPUT 中完整已发布原章、原文证据、已批准来源结论和固定人物身份生产 JSON。"
        "person_id、evidence、approved_conclusion_ids、main-history position 和 canonical entity/event 只能抄 INPUT 的程序句柄，不能新造或按姓名合并。"
        "生卒只有明确证据才填写；没有证据必须为 null，不得用首次或末次出现推定。"
        "coverage 必须逐字使用‘根据当前收录资料整理的经历’，exhaustive 必须为 false，不得声称穷尽一生。"
        "状态只写 office/title/allegiance，行动只写 action；不要把行动变成官职、效力或地点控制。"
        "每条结论必须引用 evidence 和 approved_conclusion_ids；同名但未判同的 canonical person 不得混入。"
        "主历史对应只能选择给定 history position 句柄；没有可靠对应写 unmapped，存在多个候选写 ambiguous，不能用姓名或年份猜唯一对应。"
    )
    if step == "prose_generate":
        summary = data.get("summary")
        if not isinstance(summary, dict):
            _fail("prose_generate requires accepted summary")
        instructions += "概况与经历正文是独立产物；正文每段只属于一个 phase，必须覆盖全部 phase，并逐段引用已批准结论。"
    prompt = (
        instructions
        + "\nSTAGE=" + step
        + "\nSCHEMA=" + canonical_json_bytes(schema).decode()
        + "\nINPUT=" + canonical_json_bytes(model_context(context, forward)).decode()
    )
    if step == "prose_generate":
        # The accepted summary is shown with temporary handles, so its
        # canonical digest cannot be recomputed from the model view. Supply
        # the program-owned binding separately; the model must copy it into
        # the prose envelope.
        prompt += "\nAPPROVED_SUMMARY_SHA256=" + sha256_json(data["summary"])
        prompt += "\nAPPROVED_SUMMARY=" + canonical_json_bytes(map_candidate_references(data["summary"], forward)).decode()
    if len(prompt) > max_chars:
        raise PromptLimitExceeded(step, len(prompt), max_chars)
    return prompt


def build_compare_prompt(step: str, data: dict[str, Any], *, max_chars: int = MAX_PROMPT_CHARS) -> str:
    step = STEP_ALIASES.get(step, step)
    if step not in ("summary_compare", "prose_compare"):
        _fail(f"unknown person-history comparison step {step!r}")
    context, forward, _reverse = _prompt_input(data)
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        _fail("comparison requires fixed candidates")
    expected = sha256_json(candidates)
    candidate_set_sha = data.get("candidate_set_sha256", expected)
    if candidate_set_sha != expected:
        _fail("comparison candidate set hash does not match fixed candidates")
    supplied = []
    for item in candidates:
        supplied.append({**item, "content": map_candidate_references(item.get("content"), forward)})
    prompt = (
        "你是历史内容审核编辑。只比较 CANDIDATES 中固定完整候选，不重新生成内容。"
        "逐项说明取舍和 evidence；来源矛盾无法消解时标记 disputed，不得按模型数量投票。"
        "selected_sha256 只能抄 CANDIDATE_SET 中的 hash，CANDIDATE_SET_SHA256 只能抄程序给出的值。"
        "\nSTAGE=" + step
        + "\nSCHEMA=" + canonical_json_bytes(COMPARISON_SCHEMA).decode()
        + "\nINPUT=" + canonical_json_bytes(model_context(context, forward)).decode()
        + "\nCANDIDATE_SET_SHA256=" + candidate_set_sha
        + "\nCANDIDATES=" + canonical_json_bytes(supplied).decode()
    )
    if len(prompt) > max_chars:
        raise PromptLimitExceeded(step, len(prompt), max_chars)
    return prompt


def parse_step(step: str, raw: str, context: dict[str, Any]) -> tuple[Any, list[str]]:
    step = STEP_ALIASES.get(step, step)
    if not isinstance(raw, str):
        return None, ["model response is not text"]
    if len(raw.encode("utf-8")) > MAX_BYTES:
        return None, ["model response exceeds the 2 MiB candidate envelope"]
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return None, [f"model response is not valid JSON ({type(exc).__name__})"]
    if not isinstance(value, dict):
        return None, ["model response must be a JSON object"]
    _forward, reverse = model_reference_maps(context)
    if step in ("summary_generate", "prose_generate"):
        return narrative_text(map_candidate_references(value, reverse)), []
    if step in ("summary_compare", "prose_compare"):
        return narrative_text(map_comparison_references(value, reverse)), []
    return None, [f"unknown person-history step {step!r}"]


def retry_prompt(prompt: str, previous: dict[str, Any], *, max_chars: int = MAX_PROMPT_CHARS) -> str:
    raw = previous.get("raw_text") if isinstance(previous.get("raw_text"), str) else ""
    errors = previous.get("validation_errors")
    if not isinstance(errors, list):
        errors = [previous.get("validation_error")] if previous.get("validation_error") else []
    value = (
        "CORRECTION: previous complete candidate was rejected; preserve all valid content and return complete JSON.\n"
        + "具体诊断：" + "；".join(str(item) for item in errors if item)
        + "\nPREVIOUS_CANDIDATE=" + raw + "\n" + prompt
    )
    if len(value) > max_chars:
        raise PromptLimitExceeded(str(previous.get("step") or "person_history"), len(value), max_chars)
    return value


def compile_publication(context: dict[str, Any], summary: dict[str, Any], prose: dict[str, Any]) -> dict[str, Any]:
    """Compile two accepted products without adding unsupported facts."""
    validate_summary(summary, context)
    validate_prose(prose, context, summary)
    person_id, person = _target(context)
    version = sha256_json({
        "schema": SCHEMA,
        "version": VERSION,
        "context_sha256": sha256_json(context),
        "summary": summary,
        "prose": prose,
    })
    phases = {item["id"]: item for item in summary["phases"]}
    conclusions = {item["id"]: item for item in summary["conclusions"]}
    paragraphs = []
    for ordinal, paragraph in enumerate(prose["paragraphs"]):
        phase = phases[paragraph["phase_id"]]
        paragraphs.append({
            "id": "pp_" + sha256_json([version, paragraph["id"]])[:24],
            "source_paragraph_id": paragraph["id"],
            "ordinal": ordinal,
            "phase_id": paragraph["phase_id"],
            "phase": {
                "label": phase["label"],
                "year": phase["year"],
                "period": phase["period"],
                "mapping_status": phase["mapping_status"],
                "mapping_position_ids": phase["mapping_position_ids"],
            },
            "segments": paragraph["segments"],
            "conclusion_ids": sorted({
                conclusion_id
                for segment in paragraph["segments"]
                for conclusion_id in segment["conclusion_ids"]
            }),
        })
    return {
        "schema": f"{SCHEMA}-publication",
        "version": VERSION,
        "publication_version": version,
        "person_id": person_id,
        "person": {"id": person_id, "name": person.get("name"), "kind": "person"},
        "catalog_sha": context["source_selection"]["catalog_sha"],
        "context_sha256": sha256_json(context),
        "source_publication_ids": list(context["source_selection"]["publication_ids"]),
        "coverage": copy.deepcopy(summary["coverage"]),
        "birth": copy.deepcopy(summary["birth"]),
        "death": copy.deepcopy(summary["death"]),
        "overview": summary["overview"],
        "phases": copy.deepcopy(summary["phases"]),
        "paragraphs": paragraphs,
        "conclusions": copy.deepcopy(summary["conclusions"]),
        "evidence": evidence_index(context),
        "main_history_positions": copy.deepcopy(context.get("main_history_positions", [])),
    }


__all__ = [
    "COMPARISON_SCHEMA",
    "CONCLUSION_DIMENSIONS",
    "CONTEXT_SCHEMA",
    "MAX_BYTES",
    "MAX_PROMPT_CHARS",
    "MAX_SOURCES",
    "NARRATIVE_STEPS",
    "PERSON_HISTORY_STEPS",
    "PLAN_SCHEMA",
    "PROSE_SCHEMA",
    "PromptLimitExceeded",
    "SCHEMA",
    "SUMMARY_SCHEMA",
    "VERSION",
    "build_compare_prompt",
    "build_step_prompt",
    "compile_publication",
    "evidence_index",
    "map_candidate_references",
    "map_comparison_references",
    "model_context",
    "model_reference_maps",
    "parse_step",
    "retry_prompt",
    "step_schema",
    "validate_comparison",
    "validate_prose",
    "validate_summary",
]
