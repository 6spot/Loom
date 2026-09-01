"""Read-only Chronicle PostgreSQL repository for Timeline/Event/Entity contracts."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Iterable

from common import (
    READ_SCHEMA_VERSION,
    ReadModelError,
    ReadModelNotFound,
    entity_display,
    event_display,
    time_window,
)


MAX_TIMELINE_LIMIT = 200


def _canonical_uuid(value: str, description: str) -> str:
    if not isinstance(value, str):
        raise ReadModelError(f"{description} must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ReadModelError(f"{description} is not a valid UUID") from exc


def _source(label: str, source_ref: str, source_title: str, source_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundle": label,
        "ref": source_ref,
        "title": source_title,
        "record": source_payload,
    }


class ChronicleReadRepository:
    """Build stable presentation contracts using SELECT-only persisted Chronicle data."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def _event_rows(self, canonical_event_id: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = ""
        if canonical_event_id is not None:
            canonical_event_id = _canonical_uuid(canonical_event_id, "canonical Event id")
            where = "WHERE r.canonical_id = %s::uuid"
            params = (canonical_event_id,)
        rows = self.conn.execute(
            f"""
            SELECT
                r.canonical_id::text,
                r.bundle_label,
                r.record_ref,
                e.payload,
                b.source_ref,
                b.source_title,
                b.source_payload
            FROM chronicle.canonical_event_representations r
            JOIN chronicle.staged_events e
              ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
            JOIN chronicle.source_bundles b
              ON b.bundle_label = r.bundle_label
            {where}
            ORDER BY r.canonical_id, r.bundle_label, r.record_ref
            """,
            params,
        ).fetchall()
        return [
            {
                "canonical_id": row[0],
                "bundle": row[1],
                "ref": row[2],
                "payload": row[3],
                "source_ref": row[4],
                "source_title": row[5],
                "source_payload": row[6],
            }
            for row in rows
        ]

    def _entity_rows(self, canonical_entity_id: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = ""
        if canonical_entity_id is not None:
            canonical_entity_id = _canonical_uuid(canonical_entity_id, "canonical Entity id")
            where = "WHERE r.canonical_id = %s::uuid"
            params = (canonical_entity_id,)
        rows = self.conn.execute(
            f"""
            SELECT
                r.canonical_id::text,
                r.bundle_label,
                r.record_ref,
                e.payload,
                b.source_ref,
                b.source_title,
                b.source_payload
            FROM chronicle.canonical_entity_representations r
            JOIN chronicle.staged_entities e
              ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
            JOIN chronicle.source_bundles b
              ON b.bundle_label = r.bundle_label
            {where}
            ORDER BY r.canonical_id, r.bundle_label, r.record_ref
            """,
            params,
        ).fetchall()
        return [
            {
                "canonical_id": row[0],
                "bundle": row[1],
                "ref": row[2],
                "payload": row[3],
                "source_ref": row[4],
                "source_title": row[5],
                "source_payload": row[6],
            }
            for row in rows
        ]

    def _event_summary_from_rows(self, canonical_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        payloads = [row["payload"] for row in rows]
        sources = sorted({row["source_title"] for row in rows})
        return {
            "canonical_event_id": canonical_id,
            "display": event_display(payloads),
            "time": time_window(payloads),
            "representation_count": len(rows),
            "source_count": len({row["bundle"] for row in rows}),
            "source_titles": sources,
        }

    def _entity_summary_from_rows(self, canonical_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        payloads = [row["payload"] for row in rows]
        return {
            "canonical_entity_id": canonical_id,
            "display": entity_display(payloads),
            "representation_count": len(rows),
            "source_count": len({row["bundle"] for row in rows}),
            "source_titles": sorted({row["source_title"] for row in rows}),
        }

    def _event_summary(self, canonical_event_id: str) -> dict[str, Any]:
        rows = self._event_rows(canonical_event_id)
        if not rows:
            raise ReadModelNotFound(f"canonical Event {canonical_event_id} not found")
        return self._event_summary_from_rows(rows[0]["canonical_id"], rows)

    def _entity_summary(self, canonical_entity_id: str) -> dict[str, Any]:
        rows = self._entity_rows(canonical_entity_id)
        if not rows:
            raise ReadModelNotFound(f"canonical Entity {canonical_entity_id} not found")
        return self._entity_summary_from_rows(rows[0]["canonical_id"], rows)

    def timeline(
        self,
        *,
        from_year: int | None = None,
        to_year: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if from_year is not None and not isinstance(from_year, int):
            raise ReadModelError("from_year must be an integer")
        if to_year is not None and not isinstance(to_year, int):
            raise ReadModelError("to_year must be an integer")
        if from_year is not None and to_year is not None and from_year > to_year:
            raise ReadModelError("from_year must be <= to_year")
        if not isinstance(limit, int) or limit < 1 or limit > MAX_TIMELINE_LIMIT:
            raise ReadModelError(f"limit must be between 1 and {MAX_TIMELINE_LIMIT}")
        if not isinstance(offset, int) or offset < 0:
            raise ReadModelError("offset must be >= 0")

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self._event_rows():
            grouped[row["canonical_id"]].append(row)

        items = [
            self._event_summary_from_rows(canonical_id, rows)
            for canonical_id, rows in grouped.items()
        ]

        if from_year is not None or to_year is not None:
            filtered = []
            for item in items:
                start_year = item["time"]["start_year"]
                end_year = item["time"]["end_year"]
                if start_year is None or end_year is None:
                    continue
                if from_year is not None and end_year < from_year:
                    continue
                if to_year is not None and start_year > to_year:
                    continue
                filtered.append(item)
            items = filtered

        def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
            start = item["time"]["start_year"]
            end = item["time"]["end_year"]
            title = item["display"].get("title") or ""
            return (
                start is None,
                start if start is not None else 0,
                end if end is not None else 0,
                title,
                item["canonical_event_id"],
            )

        items.sort(key=sort_key)
        total = len(items)
        page = items[offset : offset + limit]
        return {
            "schema": "chronicle.timeline",
            "version": READ_SCHEMA_VERSION,
            "query": {
                "from_year": from_year,
                "to_year": to_year,
                "limit": limit,
                "offset": offset,
            },
            "page": {
                "total": total,
                "returned": len(page),
                "has_more": offset + len(page) < total,
            },
            "items": page,
        }

    def _claims_for_ref(self, bundle: str, kind: str, ref: str) -> list[dict[str, Any]]:
        if kind not in {"entity_ref", "event_ref"}:
            raise ReadModelError(f"unsupported Claim reference kind {kind!r}")
        rows = self.conn.execute(
            """
            SELECT record_ref, payload
            FROM chronicle.staged_claims
            WHERE bundle_label = %s
              AND (
                (payload->'subject'->>'kind' = %s AND payload->'subject'->>'ref' = %s)
                OR
                (payload->'object'->>'kind' = %s AND payload->'object'->>'ref' = %s)
              )
            ORDER BY record_ref
            """,
            (bundle, kind, ref, kind, ref),
        ).fetchall()
        return [
            {
                "bundle": bundle,
                "ref": row[0],
                "claim": row[1],
            }
            for row in rows
        ]

    def _canonical_entity_for_rep(self, bundle: str, ref: str) -> tuple[str | None, dict[str, Any] | None]:
        row = self.conn.execute(
            """
            SELECT r.canonical_id::text, e.payload
            FROM chronicle.canonical_entity_representations r
            JOIN chronicle.staged_entities e
              ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
            WHERE r.bundle_label = %s AND r.record_ref = %s
            """,
            (bundle, ref),
        ).fetchone()
        if row is None:
            return None, None
        return row[0], row[1]

    def _canonical_event_for_rep(self, bundle: str, ref: str) -> str | None:
        row = self.conn.execute(
            """
            SELECT canonical_id::text
            FROM chronicle.canonical_event_representations
            WHERE bundle_label = %s AND record_ref = %s
            """,
            (bundle, ref),
        ).fetchone()
        return row[0] if row else None

    def _event_resolution_links(self, representations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        found: dict[tuple[str, str], tuple[Any, ...]] = {}
        for representation in representations:
            rows = self.conn.execute(
                """
                SELECT
                    resolution_sha256,
                    candidate_id,
                    left_bundle_label,
                    left_record_ref,
                    right_bundle_label,
                    right_record_ref,
                    decision,
                    confidence,
                    rationale,
                    signals
                FROM chronicle.resolution_event_links
                WHERE (left_bundle_label = %s AND left_record_ref = %s)
                   OR (right_bundle_label = %s AND right_record_ref = %s)
                """,
                (
                    representation["bundle"], representation["ref"],
                    representation["bundle"], representation["ref"],
                ),
            ).fetchall()
            for row in rows:
                found[(row[0], row[1])] = row

        result = []
        for key in sorted(found):
            row = found[key]
            left_canonical = self._canonical_event_for_rep(row[2], row[3])
            right_canonical = self._canonical_event_for_rep(row[4], row[5])
            result.append(
                {
                    "resolution_sha256": row[0],
                    "candidate_id": row[1],
                    "decision": row[6],
                    "confidence": row[7],
                    "rationale": row[8],
                    "signals": row[9],
                    "left": {
                        "bundle": row[2],
                        "ref": row[3],
                        "canonical_event_id": left_canonical,
                    },
                    "right": {
                        "bundle": row[4],
                        "ref": row[5],
                        "canonical_event_id": right_canonical,
                    },
                }
            )
        return result

    def _entity_resolution_links(self, representations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        found: dict[tuple[str, str], tuple[Any, ...]] = {}
        for representation in representations:
            rows = self.conn.execute(
                """
                SELECT
                    resolution_sha256,
                    candidate_id,
                    left_bundle_label,
                    left_record_ref,
                    right_bundle_label,
                    right_record_ref,
                    decision,
                    confidence,
                    rationale,
                    signals
                FROM chronicle.resolution_entity_links
                WHERE (left_bundle_label = %s AND left_record_ref = %s)
                   OR (right_bundle_label = %s AND right_record_ref = %s)
                """,
                (
                    representation["bundle"], representation["ref"],
                    representation["bundle"], representation["ref"],
                ),
            ).fetchall()
            for row in rows:
                found[(row[0], row[1])] = row

        result = []
        for key in sorted(found):
            row = found[key]
            left_id, _ = self._canonical_entity_for_rep(row[2], row[3])
            right_id, _ = self._canonical_entity_for_rep(row[4], row[5])
            result.append(
                {
                    "resolution_sha256": row[0],
                    "candidate_id": row[1],
                    "decision": row[6],
                    "confidence": row[7],
                    "rationale": row[8],
                    "signals": row[9],
                    "left": {
                        "bundle": row[2],
                        "ref": row[3],
                        "canonical_entity_id": left_id,
                    },
                    "right": {
                        "bundle": row[4],
                        "ref": row[5],
                        "canonical_entity_id": right_id,
                    },
                }
            )
        return result

    def _event_participants(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        unresolved: list[dict[str, Any]] = []
        for row in rows:
            participants = row["payload"].get("participants") or []
            for participant in participants:
                if not isinstance(participant, dict):
                    continue
                entity_ref = participant.get("entity_ref")
                role = participant.get("role")
                if not isinstance(entity_ref, str) or not entity_ref:
                    continue
                canonical_id, entity_payload = self._canonical_entity_for_rep(row["bundle"], entity_ref)
                source_role = {
                    "bundle": row["bundle"],
                    "event_ref": row["ref"],
                    "entity_ref": entity_ref,
                    "role": role,
                }
                if canonical_id is None:
                    unresolved.append(
                        {
                            "canonical_entity_id": None,
                            "display": {"name": entity_ref, "type": None},
                            "source_roles": [source_role],
                        }
                    )
                    continue
                entry = grouped.setdefault(
                    canonical_id,
                    {
                        "canonical_entity_id": canonical_id,
                        "payloads": [],
                        "source_roles": [],
                    },
                )
                if entity_payload is not None:
                    entry["payloads"].append(entity_payload)
                entry["source_roles"].append(source_role)

        result = []
        for canonical_id in sorted(grouped):
            entry = grouped[canonical_id]
            roles = {
                (item["bundle"], item["event_ref"], item["entity_ref"], item.get("role")): item
                for item in entry["source_roles"]
            }
            result.append(
                {
                    "canonical_entity_id": canonical_id,
                    "display": entity_display(entry["payloads"]),
                    "source_roles": [roles[key] for key in sorted(roles, key=lambda value: tuple(str(v) for v in value))],
                }
            )
        result.extend(unresolved)
        return result

    def _event_places(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        unresolved: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            for place_ref in row["payload"].get("places") or []:
                if not isinstance(place_ref, str) or not place_ref:
                    continue
                canonical_id, entity_payload = self._canonical_entity_for_rep(row["bundle"], place_ref)
                source_ref = {"bundle": row["bundle"], "event_ref": row["ref"], "entity_ref": place_ref}
                if canonical_id is None:
                    unresolved[(row["bundle"], place_ref)] = {
                        "canonical_entity_id": None,
                        "display": {"name": place_ref, "type": None},
                        "source_refs": [source_ref],
                    }
                    continue
                entry = grouped.setdefault(
                    canonical_id,
                    {"payloads": [], "source_refs": []},
                )
                if entity_payload is not None:
                    entry["payloads"].append(entity_payload)
                entry["source_refs"].append(source_ref)

        result = []
        for canonical_id in sorted(grouped):
            entry = grouped[canonical_id]
            refs = {
                (item["bundle"], item["event_ref"], item["entity_ref"]): item
                for item in entry["source_refs"]
            }
            result.append(
                {
                    "canonical_entity_id": canonical_id,
                    "display": entity_display(entry["payloads"]),
                    "source_refs": [refs[key] for key in sorted(refs)],
                }
            )
        result.extend(unresolved[key] for key in sorted(unresolved))
        return result

    def _related_events(self, canonical_event_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                relation_sha256,
                relation_type,
                left_canonical_event_id::text,
                right_canonical_event_id::text
            FROM chronicle.canonical_event_relations
            WHERE left_canonical_event_id = %s::uuid
               OR right_canonical_event_id = %s::uuid
            ORDER BY relation_sha256
            """,
            (canonical_event_id, canonical_event_id),
        ).fetchall()
        result = []
        for relation_sha, relation_type, left_id, right_id in rows:
            other_id = right_id if left_id == canonical_event_id else left_id
            provenance = self.conn.execute(
                """
                SELECT resolution_sha256, candidate_id,
                       left_bundle_label, left_record_ref,
                       right_bundle_label, right_record_ref
                FROM chronicle.canonical_event_relation_links
                WHERE relation_sha256 = %s
                ORDER BY resolution_sha256, candidate_id
                """,
                (relation_sha,),
            ).fetchall()
            result.append(
                {
                    "relation_sha256": relation_sha,
                    "type": relation_type,
                    "event": self._event_summary(other_id),
                    "provenance": [
                        {
                            "resolution_sha256": item[0],
                            "candidate_id": item[1],
                            "left": {"bundle": item[2], "ref": item[3]},
                            "right": {"bundle": item[4], "ref": item[5]},
                        }
                        for item in provenance
                    ],
                }
            )
        return result

    def event_detail(self, canonical_event_id: str) -> dict[str, Any]:
        canonical_event_id = _canonical_uuid(canonical_event_id, "canonical Event id")
        rows = self._event_rows(canonical_event_id)
        if not rows:
            raise ReadModelNotFound(f"canonical Event {canonical_event_id} not found")

        representations = []
        for row in rows:
            representations.append(
                {
                    "bundle": row["bundle"],
                    "ref": row["ref"],
                    "source": _source(
                        row["bundle"], row["source_ref"], row["source_title"], row["source_payload"]
                    ),
                    "event": row["payload"],
                    "claims": self._claims_for_ref(row["bundle"], "event_ref", row["ref"]),
                }
            )

        summary = self._event_summary_from_rows(canonical_event_id, rows)
        return {
            "schema": "chronicle.event-detail",
            "version": READ_SCHEMA_VERSION,
            **summary,
            "representations": representations,
            "participants": self._event_participants(rows),
            "places": self._event_places(rows),
            "related_events": self._related_events(canonical_event_id),
            "resolution_links": self._event_resolution_links(rows),
        }

    def _events_for_entity_rep(self, bundle: str, entity_ref: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT r.canonical_id::text, e.record_ref, e.payload
            FROM chronicle.staged_events e
            JOIN chronicle.canonical_event_representations r
              ON r.bundle_label = e.bundle_label AND r.record_ref = e.record_ref
            WHERE e.bundle_label = %s
              AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements(COALESCE(e.payload->'participants', '[]'::jsonb)) participant
                WHERE participant->>'entity_ref' = %s
              )
            ORDER BY r.canonical_id, e.record_ref
            """,
            (bundle, entity_ref),
        ).fetchall()
        return [
            {"canonical_event_id": row[0], "event_ref": row[1], "payload": row[2]}
            for row in rows
        ]

    def entity_detail(self, canonical_entity_id: str) -> dict[str, Any]:
        canonical_entity_id = _canonical_uuid(canonical_entity_id, "canonical Entity id")
        rows = self._entity_rows(canonical_entity_id)
        if not rows:
            raise ReadModelNotFound(f"canonical Entity {canonical_entity_id} not found")

        representations = []
        event_occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
        all_claims: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            claims = self._claims_for_ref(row["bundle"], "entity_ref", row["ref"])
            for claim in claims:
                all_claims[(claim["bundle"], claim["ref"])] = claim
            representations.append(
                {
                    "bundle": row["bundle"],
                    "ref": row["ref"],
                    "source": _source(
                        row["bundle"], row["source_ref"], row["source_title"], row["source_payload"]
                    ),
                    "entity": row["payload"],
                    "claims": claims,
                }
            )
            for event in self._events_for_entity_rep(row["bundle"], row["ref"]):
                roles = [
                    participant.get("role")
                    for participant in event["payload"].get("participants") or []
                    if isinstance(participant, dict)
                    and participant.get("entity_ref") == row["ref"]
                ]
                event_occurrences[event["canonical_event_id"]].append(
                    {
                        "bundle": row["bundle"],
                        "entity_ref": row["ref"],
                        "event_ref": event["event_ref"],
                        "roles": roles,
                    }
                )

        events = []
        for event_id in sorted(event_occurrences):
            event = self._event_summary(event_id)
            event["source_roles"] = sorted(
                event_occurrences[event_id],
                key=lambda item: (item["bundle"], item["event_ref"], item["entity_ref"]),
            )
            events.append(event)
        events.sort(
            key=lambda item: (
                item["time"]["start_year"] is None,
                item["time"]["start_year"] or 0,
                item["display"].get("title") or "",
                item["canonical_event_id"],
            )
        )

        summary = self._entity_summary_from_rows(canonical_entity_id, rows)
        return {
            "schema": "chronicle.entity-detail",
            "version": READ_SCHEMA_VERSION,
            **summary,
            "representations": representations,
            "events": events,
            "claims": [all_claims[key] for key in sorted(all_claims)],
            "resolution_links": self._entity_resolution_links(rows),
        }
