"""Chronicle application-local aggregation for human resolution review.

Architecture Amendment 0007 keeps candidate generation and canonical
publication unchanged while reducing operator review debt in two layers:

1. proven review groups use only canonical-catalog membership plus C1-T7
   ``same_entity`` / ``same_occurrence`` links;
2. operator review batches may contain several unproven incoming groups that
   all ask about the same already-published canonical identity/event.

Batching is presentation/orchestration only. It never creates equivalence.
A human default decision plus optional per-group overrides is expanded
back to every underlying C0 candidate key before final resolution/publication.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

import control_plane
from common import PersistenceConflict, PersistenceError, sha256_json

REVIEW_SCOPE = "resolution"
REVIEW_KIND = "stage_gate"
REVIEW_SUBJECT_VERSION = "0.2"
SUPPORTED_REVIEW_SUBJECT_VERSIONS = frozenset({"0.1", "0.2"})
ASSEMBLY_ARTIFACT_TYPE = "assembled-source-bundle"
CONFIDENCE_INITIAL_UNCERTAIN = 0.5
ENTITY_DECISIONS = ("same_entity", "not_same", "uncertain")
EVENT_DECISIONS = ("same_occurrence", "related_occurrence", "not_same", "uncertain")


def candidate_key(resolution_sha: str, candidate_id: str) -> str:
    return f"{resolution_sha}:{candidate_id}"


def _representation(value: Any, context: str) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise PersistenceError(f"{context} must be an object")
    bundle, ref = value.get("bundle"), value.get("ref")
    if not isinstance(bundle, str) or not bundle or not isinstance(ref, str) or not ref:
        raise PersistenceError(f"{context} must contain non-empty bundle/ref")
    return bundle, ref


def _rep_json(rep: tuple[str, str]) -> dict[str, str]:
    return {"bundle": rep[0], "ref": rep[1]}


class _DisjointSet:
    def __init__(self, items: set[str]) -> None:
        self.parent = {item: item for item in items}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        kept, moved = sorted((left_root, right_root))
        self.parent[moved] = kept

    def canonical_roots(self) -> dict[str, str]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in sorted(self.parent):
            grouped[self.find(item)].append(item)
        result: dict[str, str] = {}
        for members in grouped.values():
            root = min(members)
            for member in members:
                result[member] = root
        return result


def _candidate_members(resolutions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for resolution in sorted(resolutions, key=sha256_json):
        if not isinstance(resolution, dict):
            raise PersistenceError("resolution review input must contain objects")
        resolution_sha = sha256_json(resolution)
        for field, link_kind in (("entity_links", "entity"), ("event_links", "event")):
            raw_links = resolution.get(field) or []
            if not isinstance(raw_links, list):
                raise PersistenceError(f"resolution {field} must be an array")
            for link in raw_links:
                if not isinstance(link, dict):
                    raise PersistenceError(f"resolution {field} contains a non-object")
                candidate_id = link.get("candidate_id")
                if not isinstance(candidate_id, str) or not candidate_id:
                    raise PersistenceError("resolution link is missing candidate_id")
                left = _representation(link.get("left"), f"candidate {candidate_id}.left")
                right = _representation(link.get("right"), f"candidate {candidate_id}.right")
                members.append(
                    {
                        "candidate_key": candidate_key(resolution_sha, candidate_id),
                        "resolution_sha256": resolution_sha,
                        "candidate_id": candidate_id,
                        "link_kind": link_kind,
                        "left": _rep_json(left),
                        "right": _rep_json(right),
                        "signals": sorted(str(value) for value in (link.get("signals") or [])),
                    }
                )
    members.sort(key=lambda item: item["candidate_key"])
    keys = [item["candidate_key"] for item in members]
    if len(keys) != len(set(keys)):
        raise PersistenceConflict("resolution review input contains duplicate candidate keys")
    return members


def _catalog_membership(
    catalog: dict[str, Any] | None, link_kind: str
) -> dict[tuple[str, str], str]:
    if catalog is None:
        return {}
    if not isinstance(catalog, dict):
        raise PersistenceError("canonical catalog must be an object")
    collection = "canonical_entities" if link_kind == "entity" else "canonical_events"
    raw_records = catalog.get(collection) or []
    if not isinstance(raw_records, list):
        raise PersistenceError(f"canonical catalog {collection} must be an array")
    result: dict[tuple[str, str], str] = {}
    for index, record in enumerate(raw_records):
        if not isinstance(record, dict):
            raise PersistenceError(f"canonical catalog {collection}[{index}] must be an object")
        canonical_id = record.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id:
            raise PersistenceError(f"canonical catalog {collection}[{index}] has no canonical_id")
        representations = record.get("representations") or []
        if not isinstance(representations, list) or not representations:
            raise PersistenceError(
                f"canonical catalog {collection}[{index}] requires representations"
            )
        for rep_index, raw_rep in enumerate(representations):
            rep = _representation(
                raw_rep,
                f"canonical catalog {collection}[{index}].representations[{rep_index}]",
            )
            previous = result.get(rep)
            if previous is not None and previous != canonical_id:
                raise PersistenceConflict(
                    f"published representation {rep[0]}:{rep[1]} belongs to both "
                    f"{previous} and {canonical_id}"
                )
            result[rep] = canonical_id
    return result


def _new_component_roots(
    within_book_links: dict[str, Any] | None,
    *,
    link_kind: str,
    refs: set[str],
) -> dict[str, str]:
    dsu = _DisjointSet(set(refs))
    if within_book_links is None:
        return dsu.canonical_roots()
    if not isinstance(within_book_links, dict):
        raise PersistenceError("within_book_links must be an object")
    field = "entity_links" if link_kind == "entity" else "event_links"
    same_decision = "same_entity" if link_kind == "entity" else "same_occurrence"
    prohibited = {"not_same"} if link_kind == "entity" else {"not_same", "related_occurrence"}
    negative_pairs: list[tuple[str, str, str]] = []
    raw_links = within_book_links.get(field) or []
    if not isinstance(raw_links, list):
        raise PersistenceError(f"within_book_links.{field} must be an array")
    for index, link in enumerate(raw_links):
        if not isinstance(link, dict):
            raise PersistenceError(f"within_book_links.{field}[{index}] must be an object")
        left = link.get("left")
        right = link.get("right")
        left_ref = left.get("ref") if isinstance(left, dict) else None
        right_ref = right.get("ref") if isinstance(right, dict) else None
        if (
            not isinstance(left_ref, str)
            or not left_ref
            or not isinstance(right_ref, str)
            or not right_ref
        ):
            raise PersistenceError(f"within_book_links.{field}[{index}] is missing refs")
        dsu.add(left_ref)
        dsu.add(right_ref)
        decision = link.get("decision")
        if decision == same_decision:
            dsu.union(left_ref, right_ref)
        elif decision in prohibited:
            negative_pairs.append((left_ref, right_ref, str(decision)))

    roots = dsu.canonical_roots()
    for left_ref, right_ref, decision in negative_pairs:
        if roots[left_ref] == roots[right_ref]:
            raise PersistenceConflict(
                f"within-book {link_kind} component would cross explicit {decision}: "
                f"{left_ref} ~ {right_ref}"
            )
    return {ref: roots.get(ref, ref) for ref in refs}


def _review_group(
    *,
    kind: str,
    canonical_id: str,
    right_root: str,
    members: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(members, key=lambda item: item["candidate_key"])
    right_members = sorted(
        {(item["right"]["bundle"], item["right"]["ref"]) for item in ordered}
    )
    identity = {
        "version": REVIEW_SUBJECT_VERSION,
        "link_kind": kind,
        "published_canonical_id": canonical_id,
        "incoming_component_root": right_root,
        "candidate_keys": [item["candidate_key"] for item in ordered],
    }
    return {
        "review_group_id": "rg_" + sha256_json(identity)[:24],
        "component_root": right_root,
        "right_subject": {
            "component_kind": "proven_within_book",
            "component_root": right_root,
            "members": [_rep_json(rep) for rep in right_members],
        },
        "members": ordered,
        "member_count": len(ordered),
        "signals": sorted(
            {signal for item in ordered for signal in item.get("signals") or []}
        ),
    }


def build_review_subjects(
    resolutions: list[dict[str, Any]],
    *,
    catalog: dict[str, Any] | None,
    within_book_links: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build one operator review batch per published canonical identity/event.

    Incoming equivalence is still represented only by explicit review groups
    proven by C1-T7 same-links. Several distinct groups may share one batch;
    batching itself creates no equivalence.
    """
    members = _candidate_members(resolutions)
    if not members:
        return []
    right_labels = {item["right"]["bundle"] for item in members}
    if len(right_labels) != 1:
        raise PersistenceError(
            "review-subject aggregation expects one incoming/right bundle, got "
            + ", ".join(sorted(right_labels))
        )

    published_membership = {
        kind: _catalog_membership(catalog, kind) for kind in ("entity", "event")
    }
    new_roots: dict[str, dict[str, str]] = {}
    for kind in ("entity", "event"):
        refs = {item["right"]["ref"] for item in members if item["link_kind"] == kind}
        new_roots[kind] = _new_component_roots(
            within_book_links, link_kind=kind, refs=refs
        )

    semantic_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    left_by_batch: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for member in members:
        kind = member["link_kind"]
        left_rep = (member["left"]["bundle"], member["left"]["ref"])
        canonical_id = published_membership[kind].get(left_rep)
        if canonical_id is None:
            raise PersistenceError(
                f"resolution candidate {member['candidate_key']} references published-side "
                f"representation {left_rep[0]}:{left_rep[1]} absent from the latest canonical catalog"
            )
        right_ref = member["right"]["ref"]
        right_root = new_roots[kind].get(right_ref, right_ref)
        semantic_groups[(kind, canonical_id, right_root)].append(member)
        left_by_batch[(kind, canonical_id)].add(left_rep)

    groups_by_batch: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (kind, canonical_id, right_root), group_members in sorted(semantic_groups.items()):
        groups_by_batch[(kind, canonical_id)].append(
            _review_group(
                kind=kind,
                canonical_id=canonical_id,
                right_root=right_root,
                members=group_members,
            )
        )

    subjects: list[dict[str, Any]] = []
    for (kind, canonical_id), groups in sorted(groups_by_batch.items()):
        groups = sorted(groups, key=lambda item: item["review_group_id"])
        ordered = sorted(
            [member for group in groups for member in group["members"]],
            key=lambda item: item["candidate_key"],
        )
        left_members = sorted(left_by_batch[(kind, canonical_id)])
        right_members = sorted(
            {(item["right"]["bundle"], item["right"]["ref"]) for item in ordered}
        )
        identity = {
            "version": REVIEW_SUBJECT_VERSION,
            "link_kind": kind,
            "published_canonical_id": canonical_id,
            "review_group_ids": [group["review_group_id"] for group in groups],
            "candidate_keys": [item["candidate_key"] for item in ordered],
        }
        subjects.append(
            {
                "review_subject_id": "rs_" + sha256_json(identity)[:24],
                "review_subject_version": REVIEW_SUBJECT_VERSION,
                "link_kind": kind,
                "left_subject": {
                    "component_kind": "published_canonical",
                    "canonical_id": canonical_id,
                    "members": [_rep_json(rep) for rep in left_members],
                },
                "right_subject": {
                    "component_kind": "operator_review_batch",
                    "members": [_rep_json(rep) for rep in right_members],
                },
                "groups": groups,
                "group_count": len(groups),
                "members": ordered,
                "member_count": len(ordered),
                "signals": sorted(
                    {signal for item in ordered for signal in item.get("signals") or []}
                ),
            }
        )
    subjects.sort(key=lambda item: item["review_subject_id"])

    covered = [
        member["candidate_key"] for subject in subjects for member in subject["members"]
    ]
    expected = [item["candidate_key"] for item in members]
    if sorted(covered) != sorted(expected) or len(covered) != len(set(covered)):
        raise PersistenceConflict(
            "review-subject aggregation did not preserve a one-to-one candidate membership"
        )
    return subjects


def subject_payload(subject: dict[str, Any]) -> dict[str, Any]:
    members = subject.get("members") or []
    if not isinstance(members, list) or not members:
        raise PersistenceError("review subject requires at least one candidate member")
    representative = members[0]
    link_kind = subject.get("link_kind")
    if link_kind not in ("entity", "event"):
        raise PersistenceError(f"unknown review-subject link kind {link_kind!r}")
    groups = subject.get("groups") or []
    if not isinstance(groups, list) or not groups:
        raise PersistenceError("review batch requires at least one incoming review group")
    return {
        "scope": REVIEW_SCOPE,
        "review_subject_id": subject["review_subject_id"],
        "review_subject_version": REVIEW_SUBJECT_VERSION,
        "link_kind": link_kind,
        "candidate_id": representative["candidate_id"],
        "resolution_sha256": representative["resolution_sha256"],
        "left": dict(representative["left"]),
        "right": dict(representative["right"]),
        "left_subject": subject["left_subject"],
        "right_subject": subject["right_subject"],
        "groups": groups,
        "group_count": len(groups),
        "members": members,
        "member_count": len(members),
        "signals": list(subject.get("signals") or []),
        "initial_decision": "uncertain",
        "blocking": True,
        "allowed_decisions": list(
            ENTITY_DECISIONS if link_kind == "entity" else EVENT_DECISIONS
        ),
        "decision": None,
    }


def _legacy_payload(member: dict[str, Any]) -> dict[str, Any]:
    link_kind = member["link_kind"]
    return {
        "scope": REVIEW_SCOPE,
        "link_kind": link_kind,
        "candidate_id": member["candidate_id"],
        "resolution_sha256": member["resolution_sha256"],
        "left": dict(member["left"]),
        "right": dict(member["right"]),
        "signals": list(member.get("signals") or []),
        "initial_decision": "uncertain",
        "blocking": True,
        "allowed_decisions": list(
            ENTITY_DECISIONS if link_kind == "entity" else EVENT_DECISIONS
        ),
        "decision": None,
    }


def _payload_candidate_keys(payload: dict[str, Any]) -> list[str]:
    version = payload.get("review_subject_version")
    if version:
        if version not in SUPPORTED_REVIEW_SUBJECT_VERSIONS:
            raise PersistenceError(f"unsupported review subject version {version!r}")
        members = payload.get("members")
        if not isinstance(members, list) or not members:
            raise PersistenceError("review subject payload has no candidate members")
        result: list[str] = []
        for index, member in enumerate(members):
            if not isinstance(member, dict):
                raise PersistenceError(f"review subject member[{index}] must be an object")
            key = member.get("candidate_key")
            if not isinstance(key, str) or not key:
                resolution_sha = member.get("resolution_sha256")
                candidate_id = member.get("candidate_id")
                if not isinstance(resolution_sha, str) or not isinstance(candidate_id, str):
                    raise PersistenceError(
                        f"review subject member[{index}] is missing candidate provenance"
                    )
                key = candidate_key(resolution_sha, candidate_id)
            result.append(key)
        if len(result) != len(set(result)):
            raise PersistenceConflict("review subject payload repeats a candidate key")
        return sorted(result)
    resolution_sha = payload.get("resolution_sha256")
    candidate_id = payload.get("candidate_id")
    if not isinstance(resolution_sha, str) or not isinstance(candidate_id, str):
        raise PersistenceError("legacy resolution review payload is missing candidate provenance")
    return [candidate_key(resolution_sha, candidate_id)]


def _group_candidate_keys(group: dict[str, Any]) -> list[str]:
    members = group.get("members")
    if not isinstance(members, list) or not members:
        raise PersistenceError("review group has no candidate members")
    result: list[str] = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise PersistenceError(f"review group member[{index}] must be an object")
        key = member.get("candidate_key")
        if not isinstance(key, str) or not key:
            resolution_sha = member.get("resolution_sha256")
            candidate_id = member.get("candidate_id")
            if not isinstance(resolution_sha, str) or not isinstance(candidate_id, str):
                raise PersistenceError(
                    f"review group member[{index}] is missing candidate provenance"
                )
            key = candidate_key(resolution_sha, candidate_id)
        result.append(key)
    if len(result) != len(set(result)):
        raise PersistenceConflict("review group repeats a candidate key")
    return sorted(result)


def _payload_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("review_subject_version") != REVIEW_SUBJECT_VERSION:
        return []
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        raise PersistenceError("review batch payload has no review groups")
    seen_ids: set[str] = set()
    covered: list[str] = []
    result: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise PersistenceError(f"review group[{index}] must be an object")
        group_id = group.get("review_group_id")
        if not isinstance(group_id, str) or not group_id:
            raise PersistenceError(f"review group[{index}] is missing review_group_id")
        if group_id in seen_ids:
            raise PersistenceConflict(f"review batch repeats group {group_id}")
        seen_ids.add(group_id)
        covered.extend(_group_candidate_keys(group))
        result.append(group)
    expected = _payload_candidate_keys(payload)
    if sorted(covered) != expected or len(covered) != len(set(covered)):
        raise PersistenceConflict(
            "review batch groups do not preserve one-to-one candidate membership"
        )
    return sorted(result, key=lambda item: item["review_group_id"])


def _scoped_review_rows(conn, job_id: uuid.UUID) -> list[tuple[Any, str, dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT review_id, status, payload
        FROM chronicle.review_items
        WHERE job_id = %s
        ORDER BY created_at, review_id
        """,
        (job_id,),
    ).fetchall()
    result: list[tuple[Any, str, dict[str, Any]]] = []
    for review_id, status, payload in rows:
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("scope") == REVIEW_SCOPE:
            result.append((review_id, status, payload))
    return result


def _load_subject_inputs(
    conn, job_id: uuid.UUID
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    assembly_row = conn.execute(
        """
        SELECT payload FROM chronicle.ingestion_outputs
        WHERE job_id = %s AND artifact_type = %s
        ORDER BY created_at DESC LIMIT 1
        """,
        (job_id, ASSEMBLY_ARTIFACT_TYPE),
    ).fetchone()
    if assembly_row is None or not isinstance(assembly_row[0], dict):
        return None, None
    catalog_row = conn.execute(
        "SELECT payload FROM chronicle.canonical_catalogs ORDER BY imported_at DESC LIMIT 1"
    ).fetchone()
    catalog = catalog_row[0] if catalog_row is not None else None
    if catalog is not None and not isinstance(catalog, dict):
        raise PersistenceError("latest canonical catalog payload must be an object")
    within_book_links = assembly_row[0].get("within_book_links")
    if within_book_links is not None and not isinstance(within_book_links, dict):
        raise PersistenceError("assembled artifact within_book_links must be an object")
    return catalog, within_book_links


def _open_legacy(
    conn,
    *,
    job_id: uuid.UUID,
    members: list[dict[str, Any]],
    existing_rows: list[tuple[Any, str, dict[str, Any]]],
) -> list[uuid.UUID]:
    existing: dict[str, uuid.UUID] = {}
    for review_id, _status, payload in existing_rows:
        if payload.get("review_subject_version"):
            raise PersistenceConflict(
                "cannot mix legacy candidate reviews with review-subject items in one job"
            )
        for key in _payload_candidate_keys(payload):
            existing.setdefault(key, review_id)
    ordered: list[uuid.UUID] = []
    for member in members:
        key = member["candidate_key"]
        if key in existing:
            ordered.append(existing[key])
            continue
        review_id = control_plane.open_review_item(
            conn, job_id=job_id, kind=REVIEW_KIND, payload=_legacy_payload(member)
        )
        existing[key] = review_id
        ordered.append(review_id)
    return ordered


def open_review_subjects(
    conn, *, job_id: uuid.UUID, resolutions: list[dict[str, Any]]
) -> list[uuid.UUID]:
    """Open/adopt one durable ReviewItem per frozen review plan unit."""
    members = _candidate_members(resolutions)
    existing_rows = _scoped_review_rows(conn, job_id)
    if existing_rows:
        subject_flags = [
            bool(payload.get("review_subject_version")) for _, _, payload in existing_rows
        ]
        if any(subject_flags) and not all(subject_flags):
            raise PersistenceConflict(
                "resolution review plan mixes legacy and review-subject items"
            )
        if all(subject_flags):
            expected = sorted(item["candidate_key"] for item in members)
            covered: list[str] = []
            for _review_id, _status, payload in existing_rows:
                covered.extend(_payload_candidate_keys(payload))
            if sorted(covered) != expected or len(covered) != len(set(covered)):
                raise PersistenceConflict(
                    "persisted review-subject plan no longer matches initial resolution candidates"
                )
            return [row[0] for row in existing_rows]
        return _open_legacy(
            conn, job_id=job_id, members=members, existing_rows=existing_rows
        )

    if not members:
        return []
    catalog, within_book_links = _load_subject_inputs(conn, job_id)
    if catalog is None:
        return _open_legacy(conn, job_id=job_id, members=members, existing_rows=[])

    subjects = build_review_subjects(
        resolutions, catalog=catalog, within_book_links=within_book_links
    )
    ordered: list[uuid.UUID] = []
    for subject in subjects:
        ordered.append(
            control_plane.open_review_item(
                conn, job_id=job_id, kind=REVIEW_KIND, payload=subject_payload(subject)
            )
        )
    return ordered


def _require_decision(link_kind: str, decision: Any) -> str:
    allowed = ENTITY_DECISIONS if link_kind == "entity" else EVENT_DECISIONS
    if decision not in allowed:
        raise PersistenceError(
            f"resolution {link_kind} decision must be one of {list(allowed)}, got {decision!r}"
        )
    return str(decision)


def _decision_record(link_kind: str, raw: Any, context: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PersistenceError(f"{context} must be an object")
    resolved = _require_decision(link_kind, raw.get("decision"))
    confidence = raw.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= confidence <= 1
    ):
        raise PersistenceError(f"{context} confidence must be within [0, 1]")
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise PersistenceError(f"{context} rationale must be non-empty")
    return {
        "decision": resolved,
        "confidence": float(confidence),
        "rationale": rationale.strip(),
    }


def normalize_group_decisions(
    payload: dict[str, Any], group_decisions: Any
) -> list[dict[str, Any]]:
    """Validate operator exceptions against the frozen v0.2 review groups."""
    if group_decisions in (None, []):
        return []
    if payload.get("review_subject_version") != REVIEW_SUBJECT_VERSION:
        raise PersistenceError("group decision overrides require a v0.2 review batch")
    if not isinstance(group_decisions, list):
        raise PersistenceError("group_decisions must be an array")
    link_kind = str(payload.get("link_kind") or "")
    groups = _payload_groups(payload)
    allowed_ids = {str(group["review_group_id"]) for group in groups}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(group_decisions):
        if not isinstance(raw, dict):
            raise PersistenceError(f"group_decisions[{index}] must be an object")
        group_id = raw.get("review_group_id")
        if not isinstance(group_id, str) or group_id not in allowed_ids:
            raise PersistenceError(
                f"group_decisions[{index}] references unknown review group {group_id!r}"
            )
        if group_id in seen:
            raise PersistenceConflict(f"review group {group_id} has duplicate overrides")
        seen.add(group_id)
        decision = _decision_record(link_kind, raw, f"group_decisions[{index}]")
        normalized.append({"review_group_id": group_id, **decision})
    return sorted(normalized, key=lambda item: item["review_group_id"])


def decision_entries_for_payload(
    payload: dict[str, Any], *, status: str
) -> dict[str, dict[str, Any]]:
    if payload.get("scope") != REVIEW_SCOPE:
        return {}
    link_kind = str(payload.get("link_kind") or "")
    keys = _payload_candidate_keys(payload)
    if status == "dismissed":
        decision = {
            "decision": "uncertain",
            "confidence": CONFIDENCE_INITIAL_UNCERTAIN,
            "rationale": (
                "Resolution review dismissed without a same/not-same decision; "
                "the candidate is kept distinct as explicit uncertain and remains reviewable."
            ),
            "dismissed": True,
        }
        return {key: dict(decision) for key in keys}
    if status != "resolved":
        return {}

    raw = payload.get("decision")
    if not isinstance(raw, dict):
        return {}
    default_decision = _decision_record(link_kind, raw, "recorded resolution review")

    if payload.get("review_subject_version") != REVIEW_SUBJECT_VERSION:
        return {key: dict(default_decision) for key in keys}

    overrides = normalize_group_decisions(payload, raw.get("group_decisions") or [])
    by_group = {item["review_group_id"]: item for item in overrides}
    result: dict[str, dict[str, Any]] = {}
    for group in _payload_groups(payload):
        group_id = str(group["review_group_id"])
        selected = by_group.get(group_id)
        decision = (
            {
                "decision": selected["decision"],
                "confidence": selected["confidence"],
                "rationale": selected["rationale"],
            }
            if selected is not None
            else default_decision
        )
        for key in _group_candidate_keys(group):
            if key in result:
                raise PersistenceConflict(
                    f"candidate {key} is covered by multiple review groups"
                )
            result[key] = dict(decision)
    if sorted(result) != keys:
        raise PersistenceConflict(
            "review batch decision fan-out no longer matches candidate membership"
        )
    return result


def collect_review_subject_decisions(
    conn, *, job_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT status, payload FROM chronicle.review_items
        WHERE job_id = %s AND status IN ('resolved', 'dismissed')
        ORDER BY created_at, review_id
        """,
        (job_id,),
    ).fetchall()
    decisions: dict[str, dict[str, Any]] = {}
    for status, payload in rows:
        payload = payload if isinstance(payload, dict) else {}
        for key, decision in decision_entries_for_payload(payload, status=status).items():
            previous = decisions.get(key)
            if previous is not None and previous != decision:
                raise PersistenceConflict(
                    f"candidate {key} received conflicting propagated review decisions"
                )
            decisions[key] = decision
    return decisions


def review_subject_counts(subjects: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "subjects": len(subjects),
        "review_groups": sum(int(item.get("group_count") or 0) for item in subjects),
        "candidate_members": sum(int(item.get("member_count") or 0) for item in subjects),
    }
