"""Chronicle C2-R3-T03 cross-chapter person-state evidence assembly.

Pure, deterministic, DB-free/model-free assembly (Architecture Amendment
0006) that lifts the ``person_states`` block of every accepted
``chronicle.chapter-artifact / 0.3`` into one revision namespace. It is
the T03 owner beside :mod:`assembly`; the durable worker/publish path
only calls the assembly result and never re-implements the mapping.

Contract (``apps/chronicle/docs/person-state-reading.md`` sections 3-4):

- The phase / fact / order / continuity / disagreement local IDs are bound
  to their origin chapter (``ph_001`` in chapter 0 -> ``ph_000001``, in
  chapter 1 -> ``ph_001001``) so the same local ID in two chapters can
  never collide. Entity, event and Claim references are rewritten through
  the *same* ``(chapter_index, local_ref) -> revision_ref`` map that every
  other chapter reference uses.
- ``unit_phases`` keep pointing at the original translation block through
  the assembly block map. Prose is never re-sorted by year and no
  cross-chapter adjacency is used to infer time.
- Every item keeps its origin chapter/local ref, artifact/source hashes,
  resolved anchors and source selections in the evidence manifest. No
  canonical ID is assigned, no name-based merge happens and no same-link is
  introduced: same-name entities stay distinct and are never joined here.
- Missing/duplicate/dangling references or keys and unresolvable
  phase/entity/claim refs fail the whole assembly closed; identical input
  yields a byte-identical result.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from common import PersistenceError, sha256_json

#: Version of the person-state assembly step (enters the report).
PERSON_STATE_ASSEMBLY_VERSION = "c2r3-person-state-assembly-v1"

#: Marker for the per-chapter evidence manifest.
EVIDENCE_MANIFEST_SCHEMA = "chronicle.person-state-evidence-manifest"
EVIDENCE_MANIFEST_VERSION = "0.1"

#: Marker for the person-state assembly report.
PERSON_STATE_REPORT_SCHEMA = "chronicle.person-state-assembly-report"
PERSON_STATE_REPORT_VERSION = "0.1"

#: Collections whose local IDs receive a chapter-bound revision namespace.
#: ``(collection, id field, revision prefix, review kind)``.
_ID_COLLECTIONS = (
    ("phases", "phase_id", "ph", "phase"),
    ("phase_orders", "assertion_id", "po", "phase_order"),
    ("facts", "fact_id", "pf", "fact"),
    ("continuities", "assertion_id", "pc", "continuity"),
    ("disagreements", "assertion_id", "pd", "disagreement"),
)

#: Every state collection carried by one assembled ``person_states`` block.
#: Public so the assembly owner can shape an empty 0.1/0.2 result too.
STATE_COLLECTIONS = tuple(name for name, *_ in _ID_COLLECTIONS) + ("unit_phases",)
_STATE_COLLECTIONS = STATE_COLLECTIONS

#: Typed reference kind expected per field group.
_ENTITY_KIND = "entity"
_EVENT_KIND = "event"
_CLAIM_KIND = "claim"

_REQUIRED_PERSON_STATE_COLLECTIONS = (
    "phases",
    "phase_orders",
    "unit_phases",
    "facts",
    "continuities",
    "disagreements",
)


def _require_artifact_person_states(artifact: dict[str, Any]) -> dict[str, Any]:
    person_states = artifact.get("person_states")
    if not isinstance(person_states, dict):
        raise PersistenceError(
            "person-state assembly input must be an accepted chronicle.chapter-artifact / 0.3"
        )
    for name in _REQUIRED_PERSON_STATE_COLLECTIONS:
        if not isinstance(person_states.get(name), list):
            raise PersistenceError(f"person_states.{name} must be an array")
    return person_states


def _namespace_id(
    prefix: str, chapter_index: int, local: Any, position: int, owner: str
) -> str:
    """Deterministic chapter-bound revision ID (``ph_001`` -> ``ph_000001``)."""
    match = (
        re.match(r"^" + re.escape(prefix) + r"_(\d+)$", local)
        if isinstance(local, str)
        else None
    )
    number = int(match.group(1)) if match else position + 1
    if chapter_index < 0 or chapter_index > 999 or number < 1 or number > 999:
        raise PersistenceError(
            f"{owner} record {local!r} exceeds the chapter-bound person-state ID space"
        )
    return f"{prefix}_{chapter_index:03d}{number:03d}"


def _typed_ref(value: Any) -> tuple[str, str] | None:
    if (
        isinstance(value, dict)
        and isinstance(value.get("kind"), str)
        and isinstance(value.get("ref"), str)
    ):
        return value["kind"], value["ref"]
    return None


def _map_typed_ref(
    value: Any,
    *,
    chapter_index: int,
    ref_map: dict[tuple[int, str], str],
    expected_kind: str,
    expected_prefix: str,
    known_ids: set[str],
    owner: str,
    allow_none: bool = False,
) -> dict[str, Any] | None:
    """Rewrite one typed chapter-local ref into its revision ref (fail closed)."""
    if value is None:
        if allow_none:
            return None
        raise PersistenceError(f"{owner} requires a typed {expected_kind} reference")
    parsed = _typed_ref(value)
    if parsed is None or parsed[0] != expected_kind:
        raise PersistenceError(
            f"{owner} must be a typed {expected_kind} reference, got {value!r}"
        )
    mapped = ref_map.get((chapter_index, parsed[1]))
    if not isinstance(mapped, str) or not mapped.startswith(expected_prefix) or mapped not in known_ids:
        raise PersistenceError(
            f"{owner} references unknown {expected_kind} {parsed[1]!r}"
        )
    out = dict(value)
    out["ref"] = mapped
    return out


def _map_plain_ref(
    value: Any,
    *,
    mapping: dict[str, str],
    owner: str,
    description: str,
    allow_none: bool = False,
) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise PersistenceError(f"{owner} requires a {description}")
    if not isinstance(value, str) or value not in mapping:
        raise PersistenceError(f"{owner} references unknown {description} {value!r}")
    return mapping[value]


def assemble_person_state_evidence(
    *,
    artifacts: list[dict[str, Any]],
    chapter_index_by_id: dict[str, int],
    ref_map: dict[tuple[int, str], str],
    block_map: dict[tuple[int, str], str],
    entity_ids: set[str],
    event_ids: set[str] | None = None,
    claim_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Lift every accepted 0.3 artifact's ``person_states`` into one namespace.

    ``ref_map`` is the assembly ``(chapter_index, local_ref) -> revision_ref``
    map;     ``block_map`` is the matching translation block map. Returns
    ``{"person_states", "evidence_manifests", "local_to_revision", "report"}``.
    Any dangling/duplicate reference or unknown chapter raises
    :class:`PersistenceError` instead of returning a partial result.
    """
    if not isinstance(artifacts, list) or not artifacts:
        raise PersistenceError("person-state assembly requires at least one 0.3 artifact")
    if not isinstance(chapter_index_by_id, dict):
        raise PersistenceError("chapter_index_by_id must be a JSON object")
    if not isinstance(ref_map, dict):
        raise PersistenceError("ref_map must be a JSON object")
    if not isinstance(block_map, dict):
        raise PersistenceError("block_map must be a JSON object")
    known_entity_ids = set(entity_ids or ())
    known_event_ids = set(event_ids or ())
    known_claim_ids = set(claim_ids or ())

    ordered: list[tuple[int, str, dict[str, Any], dict[str, Any]]] = []
    seen_chapters: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise PersistenceError("person-state assembly artifacts must be JSON objects")
        chapter_id = artifact.get("chapter_id")
        if not isinstance(chapter_id, str) or not chapter_id:
            raise PersistenceError("person-state assembly artifact requires a chapter_id")
        if chapter_id in seen_chapters:
            raise PersistenceError(
                f"duplicate person-state artifact for chapter {chapter_id!r} (fail closed)"
            )
        seen_chapters.add(chapter_id)
        chapter_index = chapter_index_by_id.get(chapter_id)
        if (
            not isinstance(chapter_index, int)
            or isinstance(chapter_index, bool)
            or chapter_index < 0
        ):
            raise PersistenceError(
                f"chapter {chapter_id!r} has no non-negative chapter_index"
            )
        person_states = _require_artifact_person_states(artifact)
        ordered.append((chapter_index, chapter_id, artifact, person_states))
    ordered.sort(key=lambda item: item[0])

    # -- pass 1: chapter-bound namespaces for every state local ID ----------
    maps_by_chapter: dict[str, dict[str, dict[str, str]]] = {}
    owner_by_revision_id: dict[str, tuple[int, str, str]] = {}
    anchors_by_item: dict[str, dict[tuple[str, str], list[str]]] = {}
    local_to_revision: dict[str, str] = {}

    for chapter_index, chapter_id, artifact, person_states in ordered:
        chapter_maps: dict[str, dict[str, str]] = {
            name: {} for name, *_ in _ID_COLLECTIONS
        }
        chapter_maps["unit_phases"] = {}
        anchors_by_item[chapter_id] = _anchor_ids_by_item(artifact)
        for name, id_field, prefix, _kind in _ID_COLLECTIONS:
            for position, record in enumerate(person_states[name]):
                if not isinstance(record, dict):
                    raise PersistenceError(
                        f"chapter {chapter_id!r} person_states.{name} must hold JSON objects"
                    )
                local = record.get(id_field)
                if not isinstance(local, str) or not local:
                    raise PersistenceError(
                        f"chapter {chapter_id!r} person_states.{name}[{position}] "
                        f"requires {id_field}"
                    )
                if local in chapter_maps[name]:
                    raise PersistenceError(
                        f"chapter {chapter_id!r} repeats {name} local id {local!r} "
                        "(fail closed)"
                    )
                revision_ref = _namespace_id(
                    prefix,
                    chapter_index,
                    local,
                    position,
                    f"chapter {chapter_id!r} person_states.{name}",
                )
                owner = (chapter_index, name, local)
                previous = owner_by_revision_id.get(revision_ref)
                if previous is not None and previous != owner:
                    raise PersistenceError(
                        f"person-state id collision at {revision_ref!r} between "
                        f"{previous!r} and {owner!r} (fail closed)"
                    )
                owner_by_revision_id[revision_ref] = owner
                chapter_maps[name][local] = revision_ref
                local_to_revision[f"({chapter_index},{local})"] = revision_ref
        maps_by_chapter[chapter_id] = chapter_maps

    # -- pass 2: rewrite every reference through the shared maps ------------
    assembled: dict[str, list[dict[str, Any]]] = {
        name: [] for name in _STATE_COLLECTIONS
    }
    evidence_manifests: list[dict[str, Any]] = []

    for chapter_index, chapter_id, artifact, person_states in ordered:
        chapter_maps = maps_by_chapter[chapter_id]
        phase_map = chapter_maps["phases"]
        fact_map = chapter_maps["facts"]
        order_map = chapter_maps["phase_orders"]
        continuity_map = chapter_maps["continuities"]
        disagreement_map = chapter_maps["disagreements"]
        chapter_anchors = anchors_by_item[chapter_id]
        origin_revision_id = artifact.get("revision_id")
        artifact_sha256 = artifact.get("artifact_sha256")
        manifest_items: list[dict[str, Any]] = []

        def _origin(kind: str, local: str) -> dict[str, Any]:
            return {
                "chapter_id": chapter_id,
                "chapter_index": chapter_index,
                "origin_revision_id": origin_revision_id,
                "origin_ref": local,
                "artifact_sha256": artifact_sha256,
                "anchor_ids": list(chapter_anchors.get((kind, local), [])),
            }

        # phases ---------------------------------------------------------
        for position, record in enumerate(person_states["phases"]):
            local = record["phase_id"]
            owner = f"chapter {chapter_id!r} person_states.phases[{position}]"
            event_refs = [
                _map_typed_ref(
                    ref,
                    chapter_index=chapter_index,
                    ref_map=ref_map,
                    expected_kind=_EVENT_KIND,
                    expected_prefix="evt_",
                    known_ids=known_event_ids,
                    owner=owner,
                )
                for ref in record.get("event_refs") or []
            ]
            revision_ref = phase_map[local]
            assembled["phases"].append(
                {
                    "phase_id": revision_ref,
                    "label": record.get("label"),
                    "event_refs": event_refs,
                    "source_selections": copy.deepcopy(record.get("source_selections") or []),
                    "origin": _origin("phase", local),
                }
            )
            manifest_items.append(_manifest_item("phase", local, revision_ref, chapter_anchors))

        # phase orders ---------------------------------------------------
        for position, record in enumerate(person_states["phase_orders"]):
            local = record["assertion_id"]
            owner = f"chapter {chapter_id!r} person_states.phase_orders[{position}]"
            revision_ref = order_map[local]
            assembled["phase_orders"].append(
                {
                    "assertion_id": revision_ref,
                    "earlier_phase_ref": _map_plain_ref(
                        record.get("earlier_phase_ref"),
                        mapping=phase_map,
                        owner=owner,
                        description="earlier phase",
                    ),
                    "later_phase_ref": _map_plain_ref(
                        record.get("later_phase_ref"),
                        mapping=phase_map,
                        owner=owner,
                        description="later phase",
                    ),
                    "source_selections": copy.deepcopy(record.get("source_selections") or []),
                    "origin": _origin("phase_order", local),
                }
            )
            manifest_items.append(
                _manifest_item("phase_order", local, revision_ref, chapter_anchors)
            )

        # unit phases (block-bound, never re-sorted) ---------------------
        for position, record in enumerate(person_states["unit_phases"]):
            local_block = record.get("block_id")
            owner = f"chapter {chapter_id!r} person_states.unit_phases[{position}]"
            revision_block = block_map.get((chapter_index, local_block))
            if not isinstance(revision_block, str) or not revision_block:
                raise PersistenceError(
                    f"{owner} references unknown translation block {local_block!r}"
                )
            phase_refs = [
                _map_plain_ref(
                    ref, mapping=phase_map, owner=owner, description="phase"
                )
                for ref in record.get("phase_refs") or []
            ]
            assembled["unit_phases"].append(
                {
                    "block_id": revision_block,
                    "chapter_block_id": local_block,
                    "mode": record.get("mode"),
                    "phase_refs": phase_refs,
                    "source_selections": copy.deepcopy(record.get("source_selections") or []),
                    "origin": _origin("unit_phase", local_block),
                }
            )
            manifest_items.append(
                _manifest_item("unit_phase", local_block, revision_block, chapter_anchors)
            )

        # facts ----------------------------------------------------------
        for position, record in enumerate(person_states["facts"]):
            local = record["fact_id"]
            owner = f"chapter {chapter_id!r} person_states.facts[{position}]"
            revision_ref = fact_map[local]
            assembled["facts"].append(
                {
                    "fact_id": revision_ref,
                    "person_ref": _map_typed_ref(
                        record.get("person_ref"),
                        chapter_index=chapter_index,
                        ref_map=ref_map,
                        expected_kind=_ENTITY_KIND,
                        expected_prefix="ent_",
                        known_ids=known_entity_ids,
                        owner=owner,
                    ),
                    "dimension": record.get("dimension"),
                    "value_ref": _map_typed_ref(
                        record.get("value_ref"),
                        chapter_index=chapter_index,
                        ref_map=ref_map,
                        expected_kind=_ENTITY_KIND,
                        expected_prefix="ent_",
                        known_ids=known_entity_ids,
                        owner=owner,
                        allow_none=True,
                    ),
                    "relation": record.get("relation"),
                    "target_ref": _map_typed_ref(
                        record.get("target_ref"),
                        chapter_index=chapter_index,
                        ref_map=ref_map,
                        expected_kind=_ENTITY_KIND,
                        expected_prefix="ent_",
                        known_ids=known_entity_ids,
                        owner=owner,
                        allow_none=True,
                    ),
                    "operation": record.get("operation"),
                    "qualification": record.get("qualification"),
                    "phase_ref": _map_plain_ref(
                        record.get("phase_ref"),
                        mapping=phase_map,
                        owner=owner,
                        description="phase",
                    ),
                    "claim_refs": [
                        _map_typed_ref(
                            ref,
                            chapter_index=chapter_index,
                            ref_map=ref_map,
                            expected_kind=_CLAIM_KIND,
                            expected_prefix="clm_",
                            known_ids=known_claim_ids,
                            owner=owner,
                        )
                        for ref in record.get("claim_refs") or []
                    ],
                    "source_selections": copy.deepcopy(record.get("source_selections") or []),
                    "attribution": record.get("attribution"),
                    "origin": _origin("fact", local),
                }
            )
            manifest_items.append(_manifest_item("fact", local, revision_ref, chapter_anchors))

        # continuities ---------------------------------------------------
        for position, record in enumerate(person_states["continuities"]):
            local = record["assertion_id"]
            owner = f"chapter {chapter_id!r} person_states.continuities[{position}]"
            revision_ref = continuity_map[local]
            assembled["continuities"].append(
                {
                    "assertion_id": revision_ref,
                    "fact_ref": _map_plain_ref(
                        record.get("fact_ref"),
                        mapping=fact_map,
                        owner=owner,
                        description="fact",
                    ),
                    "start_phase_ref": _map_plain_ref(
                        record.get("start_phase_ref"),
                        mapping=phase_map,
                        owner=owner,
                        description="start phase",
                    ),
                    "end_phase_ref": _map_plain_ref(
                        record.get("end_phase_ref"),
                        mapping=phase_map,
                        owner=owner,
                        description="end phase",
                        allow_none=True,
                    ),
                    "source_selections": copy.deepcopy(record.get("source_selections") or []),
                    "origin": _origin("continuity", local),
                }
            )
            manifest_items.append(
                _manifest_item("continuity", local, revision_ref, chapter_anchors)
            )

        # disagreements --------------------------------------------------
        for position, record in enumerate(person_states["disagreements"]):
            local = record["assertion_id"]
            owner = f"chapter {chapter_id!r} person_states.disagreements[{position}]"
            revision_ref = disagreement_map[local]
            assembled["disagreements"].append(
                {
                    "assertion_id": revision_ref,
                    "topic": record.get("topic"),
                    "fact_refs": [
                        _map_plain_ref(
                            ref, mapping=fact_map, owner=owner, description="fact"
                        )
                        for ref in record.get("fact_refs") or []
                    ],
                    "phase_refs": [
                        _map_plain_ref(
                            ref, mapping=phase_map, owner=owner, description="phase"
                        )
                        for ref in record.get("phase_refs") or []
                    ],
                    "source_selections": copy.deepcopy(record.get("source_selections") or []),
                    "origin": _origin("disagreement", local),
                }
            )
            manifest_items.append(
                _manifest_item("disagreement", local, revision_ref, chapter_anchors)
            )

        manifest_items.sort(key=lambda item: (item["kind"], item["revision_ref"]))
        evidence_manifests.append(
            {
                "schema": EVIDENCE_MANIFEST_SCHEMA,
                "version": EVIDENCE_MANIFEST_VERSION,
                "assembly_version": PERSON_STATE_ASSEMBLY_VERSION,
                "chapter_id": chapter_id,
                "chapter_index": chapter_index,
                "origin_revision_id": origin_revision_id,
                "target_revision_id": origin_revision_id,
                "artifact_sha256": artifact_sha256,
                "source_sha256": artifact.get("source_sha256"),
                "normalized_sha256": artifact.get("normalized_sha256"),
                "person_states_sha256": artifact.get("person_states_sha256"),
                "items": manifest_items,
            }
        )

    _verify_closed_references(assembled)

    counts = {name: len(assembled[name]) for name in _STATE_COLLECTIONS}
    report = {
        "schema": PERSON_STATE_REPORT_SCHEMA,
        "version": PERSON_STATE_REPORT_VERSION,
        "assembly_version": PERSON_STATE_ASSEMBLY_VERSION,
        "counts": counts,
        "chapters": [
            {
                "chapter_id": chapter_id,
                "chapter_index": chapter_index,
                "artifact_sha256": artifact.get("artifact_sha256"),
                "person_states_sha256": artifact.get("person_states_sha256"),
                "counts": {
                    name: len(person_states[name]) for name in _STATE_COLLECTIONS
                },
            }
            for chapter_index, chapter_id, artifact, person_states in ordered
        ],
        "person_states_sha256": sha256_json(assembled),
        "evidence_manifests_sha256": sha256_json(evidence_manifests),
    }
    return {
        "person_states": assembled,
        "evidence_manifests": evidence_manifests,
        "local_to_revision": dict(sorted(local_to_revision.items())),
        "report": report,
    }


def _manifest_item(
    kind: str, local: str, revision_ref: str, chapter_anchors: dict[tuple[str, str], list[str]]
) -> dict[str, Any]:
    return {
        "kind": kind,
        "origin_ref": local,
        "revision_ref": revision_ref,
        "anchor_ids": list(chapter_anchors.get((kind, local), [])),
    }


def _anchor_ids_by_item(artifact: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """Map ``(kind, item_ref) -> anchor_ids`` from the accepted candidate keys.

    T01 resolves each person-state item's anchors from the item's own
    ``source_selections``; those anchors are the canonical evidence for the
    item and are preserved verbatim here. They are intentionally *not*
    required to be a subset of the artifact's 0.1 anchor set (which is
    collected from the non-state bundle/translation subset), so assembly
    keeps the resolved ids without re-resolving or dropping them.
    """
    by_item: dict[tuple[str, str], list[str]] = {}
    for entry in artifact.get("person_state_candidates") or []:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        item_ref = entry.get("item_ref")
        if not isinstance(kind, str) or not isinstance(item_ref, str):
            continue
        resolved = [anchor_id for anchor_id in entry.get("anchor_ids") or [] if isinstance(anchor_id, str)]
        by_item[(kind, item_ref)] = resolved
    return by_item


def _verify_closed_references(assembled: dict[str, list[dict[str, Any]]]) -> None:
    """Fail closed if any rewritten ref points outside the assembled revision."""
    phase_ids = {record["phase_id"] for record in assembled["phases"]}
    fact_ids = {record["fact_id"] for record in assembled["facts"]}
    for record in assembled["facts"]:
        if record["phase_ref"] not in phase_ids:
            raise PersistenceError(
                f"assembled fact {record['fact_id']!r} references unknown phase "
                f"{record['phase_ref']!r}"
            )
    for record in assembled["phase_orders"]:
        for field in ("earlier_phase_ref", "later_phase_ref"):
            if record[field] not in phase_ids:
                raise PersistenceError(
                    f"assembled phase_order {record['assertion_id']!r} references "
                    f"unknown phase {record[field]!r}"
                )
    for record in assembled["continuities"]:
        if record["fact_ref"] not in fact_ids:
            raise PersistenceError(
                f"assembled continuity {record['assertion_id']!r} references unknown "
                f"fact {record['fact_ref']!r}"
            )
        if record["start_phase_ref"] not in phase_ids:
            raise PersistenceError(
                f"assembled continuity {record['assertion_id']!r} references unknown "
                f"start phase {record['start_phase_ref']!r}"
            )
        if record["end_phase_ref"] is not None and record["end_phase_ref"] not in phase_ids:
            raise PersistenceError(
                f"assembled continuity {record['assertion_id']!r} references unknown "
                f"end phase {record['end_phase_ref']!r}"
            )
    for record in assembled["disagreements"]:
        for ref in record["fact_refs"]:
            if ref not in fact_ids:
                raise PersistenceError(
                    f"assembled disagreement {record['assertion_id']!r} references "
                    f"unknown fact {ref!r}"
                )
        for ref in record["phase_refs"]:
            if ref not in phase_ids:
                raise PersistenceError(
                    f"assembled disagreement {record['assertion_id']!r} references "
                    f"unknown phase {ref!r}"
                )
    for record in assembled["unit_phases"]:
        for ref in record["phase_refs"]:
            if ref not in phase_ids:
                raise PersistenceError(
                    f"assembled unit_phase {record['block_id']!r} references unknown "
                    f"phase {ref!r}"
                )


__all__ = [
    "EVIDENCE_MANIFEST_SCHEMA",
    "EVIDENCE_MANIFEST_VERSION",
    "PERSON_STATE_ASSEMBLY_VERSION",
    "PERSON_STATE_REPORT_SCHEMA",
    "PERSON_STATE_REPORT_VERSION",
    "STATE_COLLECTIONS",
    "assemble_person_state_evidence",
]
