"""Deterministic candidate builders used only by the current staged tests.

The durable worker never imports this module. It contains source-grounded
fixtures for the T01 acceptance gate and current staged pipeline tests; all
coordinates, hashes, and acceptance receipts remain program-owned.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common import PersistenceError


def _require_text(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersistenceError(f"{description} must be a non-empty string")
    return value.strip()


CHAPTER_FIXTURE_SCHEMA = "chronicle.chapter-fixture-pack"
CHAPTER_FIXTURE_VERSION = "0.1"
CHAPTER_MODEL_SUFFIX = "chapter"

CHAPTER_REQUEST_START = "\nCHAPTER_REQUEST\n"
CHAPTER_REQUEST_END = "\n---END CHAPTER_REQUEST---"

_CHAPTER_ID_PATTERN = re.compile(r"ch_[0-9a-f]{24}")

# Production T05 prompt sections (chapter-production.md section 3): the
# joint renderer carries the whole chapter verbatim plus a JSON request
# header, so a development provider can rebuild the exact program-owned
# request without a second envelope.
_CHAPTER_T05_HEADER_MARKER = "CHAPTER REQUEST\n"
_CHAPTER_T05_REQUIRED_MARKER = (
    "REQUIRED BLOCKS (every listed block must be covered "
    "by translation source_block_ids)\n"
)
# Anchored to the renderer's exact section headers: bare "CHAPTER BLOCKS" /
# "FULL CHAPTER TEXT" also appear in the TRANSLATION_RULES prose, and
# ``str.find`` would otherwise match the rule sentence instead of the
# section (the fixture then reports zero blocks and fails closed).
_CHAPTER_T05_BLOCKS_MARKER = "CHAPTER BLOCKS (the whole chapter"
_CHAPTER_T05_TEXT_MARKER = "FULL CHAPTER TEXT (verbatim"
_CHAPTER_T05_TEXT_START = "---BEGIN CHAPTER---\n"
_CHAPTER_T05_TEXT_END = "\n---END CHAPTER---"
_CHAPTER_T05_BLOCK_RE = re.compile(
    r"\[(?P<block_id>[^\s\]]+) kind=(?P<kind>[^\s\]]+)"
    r" range=(?P<start>\d+):(?P<end>\d+)[^\]]*\]\n"
    r"(?P<content>.*?)\n---END (?P=block_id)---",
    re.DOTALL,
)

_CONTEXTUAL_ONLY_SURFACES = frozenset({"公", "王"})

_CHAPTER_ENTITY_TYPES = frozenset(
    {
        "person",
        "place",
        "polity",
        "organization",
        "army",
        "office",
        "group",
        "other",
    }
)

_CHAPTER_EVENT_TYPES = frozenset(
    {
        "political",
        "administrative",
        "military",
        "battle",
        "movement",
        "retreat",
        "death",
        "birth",
        "succession",
        "appointment",
        "surrender",
        "diplomatic",
        "epidemic",
        "territorial_change",
        "economic",
        "cultural",
        "other",
    }
)


def _chapter_request_fingerprint(request: dict[str, Any]) -> str | None:
    """Compute the T01 request fingerprint, or ``None`` when unavailable.

    The canonical implementation lives in T01 ``chapter_contract``; this
    helper resolves it lazily so fixture-only deployments never gain a hard
    import-time dependency on the persistence layout.
    """
    try:
        from chapter_contract import request_fingerprint
    except ImportError:
        try:
            from persistence.chapter_contract import (  # type: ignore[no-redef]
                request_fingerprint,
            )
        except ImportError:
            return None
    try:
        return str(request_fingerprint(request))
    except Exception:
        return None


def _load_chapter_pack(path: Path | str) -> dict[str, Any]:
    fixture_path = Path(path).expanduser()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistenceError(
            f"cannot read Chronicle chapter fixture pack {fixture_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PersistenceError("Chronicle chapter fixture pack must be a JSON object")
    if (
        payload.get("schema") != CHAPTER_FIXTURE_SCHEMA
        or payload.get("version") != CHAPTER_FIXTURE_VERSION
    ):
        raise PersistenceError(
            "unsupported Chronicle chapter fixture pack schema/version"
        )
    _require_text(payload.get("model_version"), "chapter fixture model_version")
    chapters = payload.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise PersistenceError("chapter fixture chapters must be a non-empty array")
    seen: set[str] = set()
    for index, spec in enumerate(chapters):
        if not isinstance(spec, dict):
            raise PersistenceError(f"chapter fixture entry {index} must be an object")
        chapter_id = _require_text(
            spec.get("chapter_id"), f"chapter fixture entry {index} chapter_id"
        )
        if not _CHAPTER_ID_PATTERN.fullmatch(chapter_id):
            raise PersistenceError(
                f"chapter fixture entry {index} chapter_id {chapter_id!r} "
                "must match ch_<24 hex>"
            )
        if chapter_id in seen:
            raise PersistenceError(
                f"duplicate chapter fixture chapter_id {chapter_id!r}"
            )
        seen.add(chapter_id)
        _require_text(
            spec.get("revision_id"), f"chapter fixture {chapter_id} revision_id"
        )
        _require_text(
            spec.get("source_title"), f"chapter fixture {chapter_id} source_title"
        )
        _require_text(
            spec.get("translation_text"),
            f"chapter fixture {chapter_id} translation_text",
        )
        entities = spec.get("entities")
        if not isinstance(entities, list) or not entities:
            raise PersistenceError(
                f"chapter fixture {chapter_id} entities must be a non-empty array"
            )
        for position, entity in enumerate(entities):
            if not isinstance(entity, dict):
                raise PersistenceError(
                    f"chapter fixture {chapter_id} entity {position} must be an object"
                )
            _require_text(entity.get("name"), f"chapter fixture {chapter_id} entity {position} name")
            entity_type = _require_text(
                entity.get("type"), f"chapter fixture {chapter_id} entity {position} type"
            )
            if entity_type not in _CHAPTER_ENTITY_TYPES:
                raise PersistenceError(
                    f"chapter fixture {chapter_id} entity {position} "
                    f"has unknown type {entity_type!r}"
                )
            _require_text(
                entity.get("mention"),
                f"chapter fixture {chapter_id} entity {position} mention",
            )
        event = spec.get("event")
        if not isinstance(event, dict):
            raise PersistenceError(f"chapter fixture {chapter_id} event must be an object")
        event_type = _require_text(event.get("type"), f"chapter fixture {chapter_id} event.type")
        if event_type not in _CHAPTER_EVENT_TYPES:
            raise PersistenceError(
                f"chapter fixture {chapter_id} has unknown event type {event_type!r}"
            )
        _require_text(event.get("title"), f"chapter fixture {chapter_id} event.title")
        predicate = spec.get("predicate", "affected")
        if not isinstance(predicate, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", predicate):
            raise PersistenceError(
                f"chapter fixture {chapter_id} predicate {predicate!r} "
                "must match ^[a-z][a-z0-9_]*$"
            )
        fingerprint = spec.get("request_fingerprint")
        if fingerprint is not None and (
            not isinstance(fingerprint, str) or not fingerprint.strip()
        ):
            raise PersistenceError(
                f"chapter fixture {chapter_id} request_fingerprint "
                "must be a non-empty string when present"
            )
    return payload


def _chapter_block_containing(
    blocks: list[dict[str, Any]], position: int
) -> dict[str, Any]:
    for block in blocks:
        if (
            isinstance(block, dict)
            and isinstance(block.get("start"), int)
            and isinstance(block.get("end"), int)
            and block["start"] <= position < block["end"]
        ):
            return block
    raise PersistenceError(
        f"fixture chapter quote at offset {position} falls outside every block"
    )


def _chapter_selection_for(
    *,
    quote: str,
    text: str,
    blocks: list[dict[str, Any]],
    owner: str,
) -> dict[str, Any]:
    """Build a verbatim-grounded selection for ``quote`` (fail closed)."""
    position = text.find(quote)
    if position < 0:
        raise PersistenceError(
            f"fixture chapter quote {quote!r} for {owner} "
            "is not present in the chapter text"
        )
    block = _chapter_block_containing(blocks, position)
    block_text = text[block["start"] : block["end"]]
    occurrence = block_text.count(quote)
    if occurrence < 1:  # pragma: no cover - defensive; find() already matched
        raise PersistenceError(
            f"fixture chapter quote {quote!r} for {owner} is unresolvable"
        )
    # First occurrence inside the containing block: deterministic and valid
    # because the quote verbatim occurs there exactly ``occurrence`` times.
    return {
        "first_block_id": block["block_id"],
        "last_block_id": block["block_id"],
        "quote": quote,
        "occurrence": 1,
    }


def _chapter_meta() -> dict[str, Any]:
    return {"method": "model", "job_id": None, "confidence": None}


def build_chapter_candidate(
    request: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic chapter candidate for one fixture chapter.

    ``request`` is the program-owned chapter request (chapter_id,
    normalized_text, blocks, required_block_ids); ``spec`` is one entry of
    a chapter fixture pack. The result carries only model-generatable
    fields and is meant to be checked by the T01 canonical validator.
    """
    if not isinstance(request, dict) or not isinstance(spec, dict):
        raise PersistenceError("fixture chapter request and spec must be objects")
    chapter_id = request.get("chapter_id")
    if chapter_id != spec.get("chapter_id"):
        raise PersistenceError(
            f"fixture chapter_id drift: request {chapter_id!r} vs "
            f"fixture {spec.get('chapter_id')!r}"
        )
    text = request.get("normalized_text")
    if not isinstance(text, str) or not text:
        raise PersistenceError("fixture chapter request normalized_text must be non-empty")
    blocks = request.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError("fixture chapter request blocks must be a non-empty array")
    required = request.get("required_block_ids")
    if not isinstance(required, list) or not required:
        raise PersistenceError(
            "fixture chapter request required_block_ids must be a non-empty array"
        )

    expected_fingerprint = spec.get("request_fingerprint")
    if expected_fingerprint is not None:
        actual = _chapter_request_fingerprint(request)
        if actual is None:
            raise PersistenceError(
                "fixture chapter records a request_fingerprint that cannot "
                "be verified here (chapter_contract unavailable); refusing "
                "to emit an unaudited candidate"
            )
        if actual != expected_fingerprint:
            raise PersistenceError(
                "fixture chapter request_fingerprint mismatch; refusing to emit "
                "a candidate for a different request"
            )

    entity_specs = spec["entities"]
    entities: list[dict[str, Any]] = []
    for position, entity_spec in enumerate(entity_specs):
        mention = str(entity_spec["mention"])
        if mention not in text:
            raise PersistenceError(
                f"fixture chapter entity mention {mention!r} "
                "is not present in the chapter text"
            )
        entities.append(
            {
                "temp_id": f"ent_{position + 1:03d}",
                "kind": "entity",
                "type": entity_spec["type"],
                "canonical_name": str(entity_spec["name"]),
                "aliases": [],
                "mentions": [
                    {"text": mention, "contextual": mention in _CONTEXTUAL_ONLY_SURFACES}
                ],
                "resolution": {"status": "unresolved"},
                "extraction": _chapter_meta(),
            }
        )
    entity_refs = [entity["temp_id"] for entity in entities]
    places = [
        entity["temp_id"] for entity in entities if entity["type"] == "place"
    ]
    event_spec = spec["event"]
    events = [
        {
            "temp_id": "evt_001",
            "kind": "event",
            "type": event_spec["type"],
            "title": str(event_spec["title"]),
            "time": None,
            "participants": [
                {"entity_ref": ref, "role": "subject" if index == 0 else "related"}
                for index, ref in enumerate(entity_refs)
            ],
            "places": places,
            "extraction": _chapter_meta(),
        }
    ]

    first_mention = str(entity_specs[0]["mention"])
    claims = [
        {
            "temp_id": "clm_001",
            "kind": "claim",
            "subject": {"kind": "entity", "ref": entity_refs[0]},
            "predicate": str(spec.get("predicate", "affected")),
            "object": None,
            "evidence": {
                "text": first_mention,
                "source_ref": "src_001",
                "locator": {"section": str(required[0])},
            },
            "assessment": {"status": "unassessed"},
            "extraction": _chapter_meta(),
        }
    ]

    translation_text = str(spec["translation_text"])
    translation = {
        "language": "zh-CN",
        "blocks": [
            {
                "block_id": "t_001",
                "text": translation_text,
                "source_block_ids": [str(block_id) for block_id in required],
                "entity_refs": [
                    {"kind": "entity", "ref": ref} for ref in entity_refs
                ],
                "event_refs": [{"kind": "event", "ref": "evt_001"}],
            }
        ],
    }

    mentions: list[dict[str, Any]] = []
    for position, entity_spec in enumerate(entity_specs):
        mention = str(entity_spec["mention"])
        contextual = mention in _CONTEXTUAL_ONLY_SURFACES
        selection = _chapter_selection_for(
            quote=mention, text=text, blocks=blocks, owner=f"mention m_{position + 1:03d}"
        )
        mentions.append(
            {
                "mention_id": f"m_{position + 1:03d}",
                "surface": mention,
                "contextual": contextual,
                "status": "unresolved" if contextual else "resolved",
                "target_ref": None if contextual else entity_refs[position],
                "candidate_refs": [],
                "selection": selection,
            }
        )

    record_sources: list[dict[str, Any]] = []
    for ref, kind in (
        [(ref, "entity") for ref in entity_refs]
        + [("evt_001", "event"), ("clm_001", "claim")]
    ):
        if kind == "claim":
            quote = first_mention
        elif kind == "event":
            quote = first_mention
        else:
            quote = str(entity_specs[entity_refs.index(ref)]["mention"])
        record_sources.append(
            {
                "record_ref": ref,
                "record_kind": kind,
                "selections": [
                    _chapter_selection_for(
                        quote=quote, text=text, blocks=blocks, owner=f"record {ref!r}"
                    )
                ],
            }
        )

    return {
        "schema": "chronicle.chapter-candidate",
        "version": "0.1",
        "chapter_id": chapter_id,
        "bundle": {
            "schema_version": "0.1",
            "source": {
                "temp_id": "src_001",
                "kind": "source",
                "source_type": "book",
                "title": str(spec["source_title"]),
                "language": "lzh",
                "extraction": _chapter_meta(),
            },
            "entities": entities,
            "events": events,
            "claims": claims,
            "warnings": [],
        },
        "translation": translation,
        "mentions": mentions,
        "record_sources": record_sources,
        "warnings": [],
    }


def _reading_block_for(
    base: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Build the 0.2 ``reading`` block over a fixture 0.1 base candidate.

    Every unit is grounded in the request text and the base candidate's own
    temp refs: narrative time, current events, (empty) event spans and
    context entities. Coordinates/IDs stay program-computed, so the model
    never writes them. The result is meant for the T01 reading validator.
    """
    text = _require_text(request.get("normalized_text"), "fixture reading chapter text")
    blocks = request.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError("fixture reading chapter request blocks must be non-empty")
    bundle = base["bundle"]
    events = bundle.get("events") or []
    if len(events) != 1:
        raise PersistenceError(
            "fixture reading candidate requires exactly one bundle event"
        )
    event = events[0]
    event_id = event["temp_id"]
    participants = event.get("participants") or []
    participant_index = {
        participant.get("entity_ref"): index
        for index, participant in enumerate(participants)
        if isinstance(participant, dict)
    }
    entity_mentions = {
        entity["temp_id"]: str(entity["mentions"][0]["text"])
        for entity in bundle.get("entities") or []
        if isinstance(entity, dict) and entity.get("mentions")
    }
    entity_refs = [entity["temp_id"] for entity in bundle.get("entities") or []]

    units: list[dict[str, Any]] = []
    for translation_block in base["translation"]["blocks"]:
        block_event_refs = {
            ref.get("ref")
            for ref in translation_block.get("event_refs") or []
            if isinstance(ref, dict)
        }
        has_event = event_id in block_event_refs
        time_selection = _chapter_selection_for(
            quote=entity_mentions[entity_refs[0]],
            text=text,
            blocks=blocks,
            owner="fixture reading narrative_time",
        )
        context_entities: list[dict[str, Any]] = []
        for position, entity_ref in enumerate(entity_refs):
            roles: list[dict[str, Any]] = []
            if has_event and entity_ref in participant_index:
                roles.append(
                    {
                        "event_ref": event_id,
                        "participant_index": participant_index[entity_ref],
                    }
                )
            context_entities.append(
                {
                    "entity_ref": entity_ref,
                    "importance": "primary" if position == 0 else "other",
                    "source_selections": [
                        _chapter_selection_for(
                            quote=entity_mentions[entity_ref],
                            text=text,
                            blocks=blocks,
                            owner=f"fixture reading context {entity_ref!r}",
                        )
                    ],
                    "event_roles": roles,
                }
            )
        if has_event:
            narrative_time = {
                "mode": "events",
                "event_refs": [event_id],
                "from_block_id": None,
                "source_selections": [time_selection],
            }
            current_event_refs = [event_id]
        else:
            narrative_time = {
                "mode": "unknown",
                "event_refs": [],
                "from_block_id": None,
                "source_selections": [],
            }
            current_event_refs = []
            context_entities = []
        units.append(
            {
                "block_id": translation_block["block_id"],
                "narrative_time": narrative_time,
                "current_event_refs": current_event_refs,
                "event_spans": [],
                "context_entities": context_entities,
            }
        )
    return {"units": units, "warnings": []}


def build_reading_chapter_candidate(
    request: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic 0.2 reading candidate for one fixture chapter.

    Reuses the frozen 0.1 builder for the joint product and adds the reading
    annotation block, so the first-round sub-document and the second-round
    annotations are generated together from one whole-chapter request.
    """
    base = build_chapter_candidate(request, spec)
    base["version"] = "0.2"
    base["reading"] = _reading_block_for(base, request)
    return base


def _person_state_block_for(
    base: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic 0.3 ``person_states`` block over a reading candidate.

    Source-grounded and shape-valid for any chapter fixture pack: one phase
    grounded on the first person entity's verbatim mention (when a person
    exists), one unit-phase binding per translation block in order, and one
    ``attest`` affiliation fact (with a supporting continuity) when a
    non-place target entity exists. When the pack has no person entity the
    block is a valid empty state with ``unknown`` unit bindings rather than a
    fabricated identity. Coordinates/IDs stay program-computed; the result is
    meant for the T01 ``person_state_contract`` validator.
    """
    text = _require_text(
        request.get("normalized_text"), "fixture person-state chapter text"
    )
    blocks = request.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError(
            "fixture person-state chapter request blocks must be non-empty"
        )
    bundle = base["bundle"]
    entities = [entity for entity in bundle.get("entities") or [] if isinstance(entity, dict)]
    persons = [entity for entity in entities if entity.get("type") == "person"]
    mentions = {
        entity["temp_id"]: str(entity["mentions"][0]["text"])
        for entity in entities
        if entity.get("mentions")
    }
    translation_blocks = base["translation"]["blocks"]

    phases: list[dict[str, Any]] = []
    unit_phases: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    continuities: list[dict[str, Any]] = []

    phase_selection: dict[str, Any] | None = None
    if persons:
        subject_ref = persons[0]["temp_id"]
        subject_mention = mentions.get(subject_ref)
        if not subject_mention:
            raise PersistenceError("fixture person-state subject has no mention")
        phase_selection = _chapter_selection_for(
            quote=subject_mention,
            text=text,
            blocks=blocks,
            owner="fixture person-state phase",
        )
        label = str(bundle["source"]["title"]).strip()[:120] or "章内階段"
        phases.append(
            {
                "phase_id": "ph_001",
                "label": label,
                "event_refs": [{"kind": "event", "ref": "evt_001"}],
                "source_selections": [phase_selection],
            }
        )
        target = next(
            (
                entity
                for entity in entities
                if entity.get("type") in ("polity", "organization")
                and entity["temp_id"] != subject_ref
            ),
            None,
        )
        if target is None:
            target = next(
                (
                    entity
                    for entity in entities
                    if entity.get("type") == "person" and entity["temp_id"] != subject_ref
                ),
                None,
            )
        if target is not None:
            facts.append(
                {
                    "fact_id": "pf_001",
                    "person_ref": {"kind": "entity", "ref": subject_ref},
                    "dimension": "affiliation",
                    "value_ref": None,
                    "relation": "serves",
                    "target_ref": {"kind": "entity", "ref": target["temp_id"]},
                    "operation": "attest",
                    "qualification": "ordinary",
                    "phase_ref": "ph_001",
                    "claim_refs": [],
                    "source_selections": [phase_selection],
                    "attribution": "narrator",
                }
            )
            continuities.append(
                {
                    "assertion_id": "pc_001",
                    "fact_ref": "pf_001",
                    "start_phase_ref": "ph_001",
                    "end_phase_ref": None,
                    "source_selections": [phase_selection],
                }
            )

    for translation_block in translation_blocks:
        event_refs = {
            ref.get("ref")
            for ref in translation_block.get("event_refs") or []
            if isinstance(ref, dict)
        }
        if phase_selection is not None and "evt_001" in event_refs:
            unit_phases.append(
                {
                    "block_id": translation_block["block_id"],
                    "mode": "single",
                    "phase_refs": ["ph_001"],
                    "source_selections": [phase_selection],
                }
            )
        else:
            unit_phases.append(
                {
                    "block_id": translation_block["block_id"],
                    "mode": "unknown",
                    "phase_refs": [],
                    "source_selections": [],
                }
            )
    return {
        "phases": phases,
        "phase_orders": [],
        "unit_phases": unit_phases,
        "facts": facts,
        "continuities": continuities,
        "disagreements": [],
    }


def build_person_state_chapter_candidate(
    request: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic 0.3 person-state candidate for one fixture chapter.

    Reuses the frozen 0.2 reading candidate and adds the third-round
    ``person_states`` block, so translation, C0 records, reading annotations
    and person-state facts are generated together from one whole-chapter
    request.
    """
    base = build_reading_chapter_candidate(request, spec)
    base["version"] = "0.3"
    base["person_states"] = _person_state_block_for(base, request)
    return base
