"""Persistence for Chronicle canonical publication catalogs."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from common import PersistenceConflict, PersistenceError, parse_uuid7, sha256_json, stable_relation_payload


def _representation(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise PersistenceError("canonical representation must be an object")
    bundle = value.get("bundle")
    ref = value.get("ref")
    if not isinstance(bundle, str) or not bundle or not isinstance(ref, str) or not ref:
        raise PersistenceError("canonical representation requires bundle/ref")
    return bundle, ref


def _ensure_canonical_id(conn, table: str, catalog_sha: str, canonical_id: str) -> bool:
    if table not in {"canonical_entities", "canonical_events"}:
        raise PersistenceError(f"unsupported canonical table {table!r}")
    return conn.execute(
        f"""
        INSERT INTO chronicle.{table}(canonical_id, first_catalog_sha256)
        VALUES (%s, %s)
        ON CONFLICT (canonical_id) DO NOTHING
        """,
        (parse_uuid7(canonical_id, f"{table} canonical_id"), catalog_sha),
    ).rowcount == 1


def _ensure_membership(
    conn,
    *,
    table: str,
    catalog_sha: str,
    canonical_id: str,
    bundle: str,
    ref: str,
) -> bool:
    if table not in {"canonical_entity_representations", "canonical_event_representations"}:
        raise PersistenceError(f"unsupported membership table {table!r}")
    created = conn.execute(
        f"""
        INSERT INTO chronicle.{table}(
            bundle_label, record_ref, canonical_id, first_catalog_sha256
        ) VALUES (%s, %s, %s, %s)
        ON CONFLICT (bundle_label, record_ref) DO NOTHING
        """,
        (bundle, ref, parse_uuid7(canonical_id, "canonical membership id"), catalog_sha),
    ).rowcount == 1
    if created:
        return True
    row = conn.execute(
        f"SELECT canonical_id::text FROM chronicle.{table} "
        "WHERE bundle_label = %s AND record_ref = %s",
        (bundle, ref),
    ).fetchone()
    if row is None or row[0] != canonical_id:
        stored = row[0] if row else "<missing>"
        raise PersistenceConflict(
            f"canonical membership {bundle}:{ref} would change from {stored} to {canonical_id}"
        )
    return False


def persist_catalog(conn, catalog: dict[str, Any]) -> tuple[str, dict[str, int]]:
    catalog_sha = sha256_json(catalog)
    schema_name = catalog.get("schema")
    version = catalog.get("version")
    if not isinstance(schema_name, str) or not isinstance(version, str):
        raise PersistenceError("canonical catalog is missing schema/version")

    created = conn.execute(
        """
        INSERT INTO chronicle.canonical_catalogs(
            artifact_sha256, schema_name, schema_version, payload
        ) VALUES (%s, %s, %s, %s)
        ON CONFLICT (artifact_sha256) DO NOTHING
        """,
        (catalog_sha, schema_name, version, Jsonb(catalog)),
    ).rowcount == 1
    if not created:
        row = conn.execute(
            "SELECT payload FROM chronicle.canonical_catalogs WHERE artifact_sha256 = %s",
            (catalog_sha,),
        ).fetchone()
        if row is None or row[0] != catalog:
            raise PersistenceConflict(f"canonical catalog hash collision/conflict {catalog_sha}")

    inserted = {
        "catalogs": int(created),
        "entities": 0,
        "events": 0,
        "entity_memberships": 0,
        "event_memberships": 0,
        "relations": 0,
        "relation_links": 0,
        "warnings": 0,
    }

    for record in catalog.get("canonical_entities") or []:
        canonical_id = record.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id:
            raise PersistenceError("canonical entity is missing canonical_id")
        inserted["entities"] += int(
            _ensure_canonical_id(conn, "canonical_entities", catalog_sha, canonical_id)
        )
        conn.execute(
            """
            INSERT INTO chronicle.canonical_catalog_entities(catalog_sha256, canonical_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
            """,
            (catalog_sha, parse_uuid7(canonical_id, "canonical entity id")),
        )
        for representation in record.get("representations") or []:
            bundle, ref = _representation(representation)
            inserted["entity_memberships"] += int(
                _ensure_membership(
                    conn,
                    table="canonical_entity_representations",
                    catalog_sha=catalog_sha,
                    canonical_id=canonical_id,
                    bundle=bundle,
                    ref=ref,
                )
            )

    for record in catalog.get("canonical_events") or []:
        canonical_id = record.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id:
            raise PersistenceError("canonical event is missing canonical_id")
        inserted["events"] += int(
            _ensure_canonical_id(conn, "canonical_events", catalog_sha, canonical_id)
        )
        conn.execute(
            """
            INSERT INTO chronicle.canonical_catalog_events(catalog_sha256, canonical_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
            """,
            (catalog_sha, parse_uuid7(canonical_id, "canonical event id")),
        )
        for representation in record.get("representations") or []:
            bundle, ref = _representation(representation)
            inserted["event_memberships"] += int(
                _ensure_membership(
                    conn,
                    table="canonical_event_representations",
                    catalog_sha=catalog_sha,
                    canonical_id=canonical_id,
                    bundle=bundle,
                    ref=ref,
                )
            )

    for relation in catalog.get("event_relations") or []:
        identity_payload = stable_relation_payload(relation)
        relation_sha = sha256_json(identity_payload)
        left = relation.get("left_canonical_event_id")
        right = relation.get("right_canonical_event_id")
        relation_type = relation.get("type")
        result = conn.execute(
            """
            INSERT INTO chronicle.canonical_event_relations(
                relation_sha256, relation_type,
                left_canonical_event_id, right_canonical_event_id,
                first_catalog_sha256, payload
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (relation_sha256) DO NOTHING
            """,
            (
                relation_sha,
                relation_type,
                parse_uuid7(left, "relation left canonical event id"),
                parse_uuid7(right, "relation right canonical event id"),
                catalog_sha,
                Jsonb(identity_payload),
            ),
        )
        if result.rowcount == 0:
            row = conn.execute(
                "SELECT payload FROM chronicle.canonical_event_relations WHERE relation_sha256 = %s",
                (relation_sha,),
            ).fetchone()
            if row is None or row[0] != identity_payload:
                raise PersistenceConflict(f"canonical event relation {relation_sha} conflicts")
        inserted["relations"] += int(result.rowcount == 1)
        conn.execute(
            """
            INSERT INTO chronicle.canonical_catalog_relations(catalog_sha256, relation_sha256)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
            """,
            (catalog_sha, relation_sha),
        )

        for link in relation.get("resolution_links") or []:
            candidate_id = link.get("candidate_id")
            left_bundle, left_ref = _representation(link.get("left"))
            right_bundle, right_ref = _representation(link.get("right"))
            matches = conn.execute(
                """
                SELECT resolution_sha256
                FROM chronicle.resolution_event_links
                WHERE candidate_id = %s
                  AND decision = 'related_occurrence'
                  AND left_bundle_label = %s
                  AND left_record_ref = %s
                  AND right_bundle_label = %s
                  AND right_record_ref = %s
                ORDER BY resolution_sha256
                """,
                (candidate_id, left_bundle, left_ref, right_bundle, right_ref),
            ).fetchall()
            if not matches:
                raise PersistenceConflict(
                    "canonical related_occurrence provenance has no persisted "
                    f"Resolution Link: {candidate_id} {left_bundle}:{left_ref} -> "
                    f"{right_bundle}:{right_ref}"
                )
            for (resolution_sha,) in matches:
                created_link = conn.execute(
                    """
                    INSERT INTO chronicle.canonical_event_relation_links(
                        relation_sha256, resolution_sha256, candidate_id,
                        left_bundle_label, left_record_ref,
                        right_bundle_label, right_record_ref
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        relation_sha,
                        resolution_sha,
                        candidate_id,
                        left_bundle,
                        left_ref,
                        right_bundle,
                        right_ref,
                    ),
                ).rowcount == 1
                inserted["relation_links"] += int(created_link)

    for index, warning in enumerate(catalog.get("warnings") or []):
        result = conn.execute(
            """
            INSERT INTO chronicle.canonical_warnings(catalog_sha256, warning_index, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (catalog_sha256, warning_index) DO NOTHING
            """,
            (catalog_sha, index, Jsonb(warning)),
        )
        if result.rowcount == 0:
            row = conn.execute(
                "SELECT payload FROM chronicle.canonical_warnings "
                "WHERE catalog_sha256 = %s AND warning_index = %s",
                (catalog_sha, index),
            ).fetchone()
            if row is None or row[0] != warning:
                raise PersistenceConflict(f"canonical warning {catalog_sha}[{index}] conflicts")
        inserted["warnings"] += int(result.rowcount == 1)

    return catalog_sha, inserted
