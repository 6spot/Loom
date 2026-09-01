"""Chronicle canonical publication v0.1.

Publication is a deterministic, non-destructive application layer above staged
source bundles and cross-source Resolution Links. It assigns stable canonical
UUIDv7 identities to Entity/Event representation groups without rewriting any
source-owned record or Claim.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections import defaultdict
from typing import Any, Callable, Iterable

PUBLICATION_VERSION = "0.1"
Representation = tuple[str, str]
IdFactory = Callable[[], str]


class PublicationV0Error(RuntimeError):
    pass


class PublicationConflict(PublicationV0Error):
    pass


class _DisjointSet:
    def __init__(self, items: Iterable[Representation]) -> None:
        self.parent: dict[Representation, Representation] = {}
        self.rank: dict[Representation, int] = {}
        for item in items:
            self.add(item)

    def add(self, item: Representation) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0

    def find(self, item: Representation) -> Representation:
        try:
            parent = self.parent[item]
        except KeyError as exc:
            raise PublicationV0Error(f"unknown representation {item[0]}:{item[1]}") from exc
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: Representation, right: Representation) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        left_rank = self.rank[left_root]
        right_rank = self.rank[right_root]
        if left_rank < right_rank:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if left_rank == right_rank:
            self.rank[left_root] += 1

    def components(self) -> list[list[Representation]]:
        grouped: dict[Representation, list[Representation]] = defaultdict(list)
        for item in self.parent:
            grouped[self.find(item)].append(item)
        return sorted(
            (sorted(members) for members in grouped.values()),
            key=lambda members: members[0],
        )


def new_uuid7() -> str:
    """Generate an RFC 9562 UUIDv7 using only Python's standard library."""

    unix_ms = time.time_ns() // 1_000_000
    if unix_ms >= 1 << 48:
        raise PublicationV0Error("current Unix millisecond timestamp does not fit UUIDv7")
    random_bits = secrets.randbits(74)
    rand_a = random_bits >> 62
    rand_b = random_bits & ((1 << 62) - 1)
    value = (
        (unix_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=value))


def _require_uuid7(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise PublicationV0Error(f"{context} must be a UUIDv7 string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise PublicationV0Error(f"{context} is not a valid UUID: {value!r}") from exc
    if parsed.version != 7:
        raise PublicationV0Error(f"{context} must be UUIDv7: {value}")
    return value


def _record_id(record: dict[str, Any], context: str) -> str:
    value = record.get("temp_id") or record.get("id")
    if not isinstance(value, str) or not value:
        raise PublicationV0Error(f"{context} is missing identity")
    return value


def _representation(value: Any, context: str) -> Representation:
    if not isinstance(value, dict):
        raise PublicationV0Error(f"{context} must be an object")
    bundle = value.get("bundle")
    ref = value.get("ref")
    if not isinstance(bundle, str) or not bundle or not isinstance(ref, str) or not ref:
        raise PublicationV0Error(f"{context} must contain non-empty bundle/ref")
    return bundle, ref


def _representation_json(rep: Representation) -> dict[str, str]:
    return {"bundle": rep[0], "ref": rep[1]}


def _bundle_source_ref(bundle: dict[str, Any], label: str) -> tuple[str, str]:
    source = bundle.get("source")
    if not isinstance(source, dict):
        raise PublicationV0Error(f"bundle {label!r} is missing source")
    source_ref = _record_id(source, f"bundle {label!r} source")
    source_title = source.get("title")
    if not isinstance(source_title, str) or not source_title:
        raise PublicationV0Error(f"bundle {label!r} source is missing title")
    return source_ref, source_title


def _collect_current_representations(
    bundles: dict[str, dict[str, Any]], collection: str
) -> set[Representation]:
    result: set[Representation] = set()
    for label in sorted(bundles):
        bundle = bundles[label]
        records = bundle.get(collection) or []
        if not isinstance(records, list):
            raise PublicationV0Error(f"bundle {label!r} {collection} must be an array")
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                raise PublicationV0Error(f"bundle {label!r} {collection} contains a non-object")
            ref = _record_id(record, f"bundle {label!r} {collection} record")
            if ref in seen:
                raise PublicationV0Error(
                    f"bundle {label!r} contains duplicate {collection} ref {ref!r}"
                )
            seen.add(ref)
            result.add((label, ref))
    return result


def _existing_membership(
    existing_catalog: dict[str, Any] | None,
    collection: str,
) -> tuple[dict[Representation, str], dict[str, set[Representation]]]:
    by_rep: dict[Representation, str] = {}
    by_id: dict[str, set[Representation]] = defaultdict(set)
    if existing_catalog is None:
        return by_rep, by_id

    records = existing_catalog.get(collection) or []
    if not isinstance(records, list):
        raise PublicationV0Error(f"existing catalog {collection} must be an array")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise PublicationV0Error(f"existing catalog {collection}[{index}] must be an object")
        canonical_id = _require_uuid7(
            record.get("canonical_id"), f"existing catalog {collection}[{index}].canonical_id"
        )
        representations = record.get("representations") or []
        if not isinstance(representations, list) or not representations:
            raise PublicationV0Error(
                f"existing catalog {collection}[{index}] requires representations"
            )
        for rep_index, raw_rep in enumerate(representations):
            rep = _representation(
                raw_rep, f"existing catalog {collection}[{index}].representations[{rep_index}]"
            )
            previous = by_rep.get(rep)
            if previous is not None and previous != canonical_id:
                raise PublicationConflict(
                    f"representation {rep[0]}:{rep[1]} belongs to both {previous} and {canonical_id}"
                )
            by_rep[rep] = canonical_id
            by_id[canonical_id].add(rep)
    return by_rep, by_id


def _validate_resolution_bundle_ref(
    resolution: dict[str, Any],
    side: str,
    bundles: dict[str, dict[str, Any]],
    resolution_index: int,
) -> None:
    raw = resolution.get(f"{side}_bundle")
    if not isinstance(raw, dict):
        raise PublicationV0Error(f"resolution[{resolution_index}] missing {side}_bundle")
    label = raw.get("label")
    if not isinstance(label, str) or label not in bundles:
        raise PublicationV0Error(
            f"resolution[{resolution_index}] references unknown {side} bundle {label!r}"
        )
    source_ref, source_title = _bundle_source_ref(bundles[label], label)
    if raw.get("source_ref") != source_ref or raw.get("source_title") != source_title:
        raise PublicationV0Error(
            f"resolution[{resolution_index}] {side}_bundle metadata does not match bundle {label!r}"
        )


def _iter_links(
    resolutions: list[dict[str, Any]],
    field: str,
) -> Iterable[tuple[int, dict[str, Any]]]:
    for resolution_index, resolution in enumerate(resolutions):
        links = resolution.get(field) or []
        if not isinstance(links, list):
            raise PublicationV0Error(f"resolution[{resolution_index}] {field} must be an array")
        for link in links:
            if not isinstance(link, dict):
                raise PublicationV0Error(
                    f"resolution[{resolution_index}] {field} contains a non-object"
                )
            yield resolution_index, link


def _build_canonical_records(
    dsu: _DisjointSet,
    existing_by_rep: dict[Representation, str],
    existing_by_id: dict[str, set[Representation]],
    id_factory: IdFactory,
    kind: str,
) -> tuple[list[dict[str, Any]], dict[Representation, str]]:
    rep_to_id: dict[Representation, str] = {}
    records: list[dict[str, Any]] = []
    consumed_existing_ids: set[str] = set()
    used_ids: set[str] = set(existing_by_id)

    for component in dsu.components():
        existing_ids = {existing_by_rep[rep] for rep in component if rep in existing_by_rep}
        if len(existing_ids) > 1:
            joined = ", ".join(sorted(existing_ids))
            members = ", ".join(f"{bundle}:{ref}" for bundle, ref in component)
            raise PublicationConflict(
                f"{kind} publication would collapse existing canonical IDs [{joined}] via [{members}]"
            )
        if existing_ids:
            canonical_id = next(iter(existing_ids))
            consumed_existing_ids.add(canonical_id)
        else:
            canonical_id = _require_uuid7(id_factory(), f"generated canonical {kind} id")
            if canonical_id in used_ids:
                raise PublicationConflict(
                    f"generated canonical {kind} ID collision: {canonical_id}"
                )
            used_ids.add(canonical_id)

        members = set(component)
        if existing_ids:
            members.update(existing_by_id[canonical_id])
        ordered_members = sorted(members)
        for rep in ordered_members:
            previous = rep_to_id.get(rep)
            if previous is not None and previous != canonical_id:
                raise PublicationConflict(
                    f"representation {rep[0]}:{rep[1]} maps to both {previous} and {canonical_id}"
                )
            rep_to_id[rep] = canonical_id
        records.append(
            {
                "canonical_id": canonical_id,
                "representations": [_representation_json(rep) for rep in ordered_members],
            }
        )

    for canonical_id in sorted(existing_by_id):
        if canonical_id in consumed_existing_ids:
            continue
        ordered_members = sorted(existing_by_id[canonical_id])
        for rep in ordered_members:
            previous = rep_to_id.get(rep)
            if previous is not None and previous != canonical_id:
                raise PublicationConflict(
                    f"representation {rep[0]}:{rep[1]} maps to both {previous} and {canonical_id}"
                )
            rep_to_id[rep] = canonical_id
        records.append(
            {
                "canonical_id": canonical_id,
                "representations": [_representation_json(rep) for rep in ordered_members],
            }
        )

    records.sort(key=lambda record: record["canonical_id"])
    return records, rep_to_id


def _negative_constraint_conflict(
    links: Iterable[tuple[int, dict[str, Any]]],
    rep_to_id: dict[Representation, str],
    prohibited_decisions: set[str],
    label: str,
) -> None:
    for resolution_index, link in links:
        if link.get("decision") not in prohibited_decisions:
            continue
        left = _representation(link.get("left"), f"resolution[{resolution_index}] {label}.left")
        right = _representation(link.get("right"), f"resolution[{resolution_index}] {label}.right")
        if rep_to_id[left] == rep_to_id[right]:
            raise PublicationConflict(
                f"{label} decision {link.get('decision')!r} requires distinct canonical records, "
                f"but {left[0]}:{left[1]} and {right[0]}:{right[1]} resolve to {rep_to_id[left]}"
            )


def publish_catalog(
    bundles: dict[str, dict[str, Any]],
    resolutions: list[dict[str, Any]],
    existing_catalog: dict[str, Any] | None = None,
    id_factory: IdFactory = new_uuid7,
) -> dict[str, Any]:
    """Publish source representations into stable canonical Entity/Event identities.

    Inputs are read-only. The returned catalog contains identity membership and
    canonical Event relations only; source names, titles, Claims, evidence, and
    resolution rationale remain owned by their original layers.
    """

    if not bundles:
        raise PublicationV0Error("publication requires at least one staged bundle")
    if existing_catalog is not None:
        if existing_catalog.get("schema") != "chronicle.canonical-catalog":
            raise PublicationV0Error("existing catalog has unexpected schema")
        if existing_catalog.get("version") != PUBLICATION_VERSION:
            raise PublicationV0Error("existing catalog has unsupported version")

    entity_current = _collect_current_representations(bundles, "entities")
    event_current = _collect_current_representations(bundles, "events")
    entity_existing_by_rep, entity_existing_by_id = _existing_membership(
        existing_catalog, "canonical_entities"
    )
    event_existing_by_rep, event_existing_by_id = _existing_membership(
        existing_catalog, "canonical_events"
    )

    entity_dsu = _DisjointSet(entity_current | set(entity_existing_by_rep))
    event_dsu = _DisjointSet(event_current | set(event_existing_by_rep))
    for members in entity_existing_by_id.values():
        ordered = sorted(members)
        for rep in ordered[1:]:
            entity_dsu.union(ordered[0], rep)
    for members in event_existing_by_id.values():
        ordered = sorted(members)
        for rep in ordered[1:]:
            event_dsu.union(ordered[0], rep)

    for resolution_index, resolution in enumerate(resolutions):
        if not isinstance(resolution, dict):
            raise PublicationV0Error(f"resolution[{resolution_index}] must be an object")
        if resolution.get("schema") != "chronicle.resolution-links":
            raise PublicationV0Error(f"resolution[{resolution_index}] has unexpected schema")
        if resolution.get("version") != "0.1":
            raise PublicationV0Error(f"resolution[{resolution_index}] has unsupported version")
        _validate_resolution_bundle_ref(resolution, "left", bundles, resolution_index)
        _validate_resolution_bundle_ref(resolution, "right", bundles, resolution_index)

    entity_links = list(_iter_links(resolutions, "entity_links"))
    event_links = list(_iter_links(resolutions, "event_links"))

    for resolution_index, link in entity_links:
        left = _representation(link.get("left"), f"resolution[{resolution_index}] entity link left")
        right = _representation(link.get("right"), f"resolution[{resolution_index}] entity link right")
        if left not in entity_current or right not in entity_current:
            raise PublicationV0Error(
                f"resolution[{resolution_index}] entity link references unknown Entity representation"
            )
        decision = link.get("decision")
        if decision == "same_entity":
            entity_dsu.union(left, right)
        elif decision not in {"not_same", "uncertain"}:
            raise PublicationV0Error(
                f"resolution[{resolution_index}] has unknown entity decision {decision!r}"
            )

    for resolution_index, link in event_links:
        left = _representation(link.get("left"), f"resolution[{resolution_index}] event link left")
        right = _representation(link.get("right"), f"resolution[{resolution_index}] event link right")
        if left not in event_current or right not in event_current:
            raise PublicationV0Error(
                f"resolution[{resolution_index}] event link references unknown Event representation"
            )
        decision = link.get("decision")
        if decision == "same_occurrence":
            event_dsu.union(left, right)
        elif decision not in {"related_occurrence", "not_same", "uncertain"}:
            raise PublicationV0Error(
                f"resolution[{resolution_index}] has unknown event decision {decision!r}"
            )

    canonical_entities, entity_rep_to_id = _build_canonical_records(
        entity_dsu,
        entity_existing_by_rep,
        entity_existing_by_id,
        id_factory,
        "Entity",
    )
    canonical_events, event_rep_to_id = _build_canonical_records(
        event_dsu,
        event_existing_by_rep,
        event_existing_by_id,
        id_factory,
        "Event",
    )

    _negative_constraint_conflict(
        entity_links, entity_rep_to_id, {"not_same"}, "Entity"
    )
    _negative_constraint_conflict(
        event_links,
        event_rep_to_id,
        {"not_same", "related_occurrence"},
        "Event",
    )

    relation_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    if existing_catalog is not None:
        existing_relations = existing_catalog.get("event_relations") or []
        if not isinstance(existing_relations, list):
            raise PublicationV0Error("existing catalog event_relations must be an array")
        canonical_event_ids = {record["canonical_id"] for record in canonical_events}
        for index, relation in enumerate(existing_relations):
            if not isinstance(relation, dict) or relation.get("type") != "related_occurrence":
                raise PublicationV0Error(
                    f"existing catalog event_relations[{index}] is not related_occurrence"
                )
            left_id = _require_uuid7(
                relation.get("left_canonical_event_id"),
                f"existing catalog event_relations[{index}].left_canonical_event_id",
            )
            right_id = _require_uuid7(
                relation.get("right_canonical_event_id"),
                f"existing catalog event_relations[{index}].right_canonical_event_id",
            )
            if left_id == right_id:
                raise PublicationConflict(
                    f"existing related_occurrence relation[{index}] points to one canonical Event"
                )
            if left_id not in canonical_event_ids or right_id not in canonical_event_ids:
                raise PublicationV0Error(
                    f"existing catalog event_relations[{index}] references unknown canonical Event"
                )
            provenance = relation.get("resolution_links") or []
            if not isinstance(provenance, list):
                raise PublicationV0Error(
                    f"existing catalog event_relations[{index}].resolution_links must be an array"
                )
            endpoint_ids = tuple(sorted((left_id, right_id)))
            for item in provenance:
                if not isinstance(item, dict):
                    raise PublicationV0Error(
                        f"existing catalog event_relations[{index}] contains invalid resolution provenance"
                    )
                relation_groups[endpoint_ids].append(dict(item))

    for resolution_index, link in event_links:
        if link.get("decision") != "related_occurrence":
            continue
        left_rep = _representation(
            link.get("left"), f"resolution[{resolution_index}] related event left"
        )
        right_rep = _representation(
            link.get("right"), f"resolution[{resolution_index}] related event right"
        )
        endpoint_ids = tuple(sorted((event_rep_to_id[left_rep], event_rep_to_id[right_rep])))
        provenance = {
            "candidate_id": link.get("candidate_id"),
            "left": _representation_json(left_rep),
            "right": _representation_json(right_rep),
        }
        relation_groups[endpoint_ids].append(provenance)

    event_relations: list[dict[str, Any]] = []
    for (left_id, right_id), provenance in sorted(relation_groups.items()):
        unique_provenance: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for item in provenance:
            key = (
                str(item.get("candidate_id")),
                item["left"]["bundle"],
                item["left"]["ref"],
                item["right"]["bundle"],
                item["right"]["ref"],
            )
            unique_provenance[key] = item
        provenance = [unique_provenance[key] for key in sorted(unique_provenance)]
        event_relations.append(
            {
                "type": "related_occurrence",
                "left_canonical_event_id": left_id,
                "right_canonical_event_id": right_id,
                "resolution_links": provenance,
            }
        )

    return {
        "schema": "chronicle.canonical-catalog",
        "version": PUBLICATION_VERSION,
        "canonical_entities": canonical_entities,
        "canonical_events": canonical_events,
        "event_relations": event_relations,
        "warnings": [],
    }
