"""Persistence for Chronicle cross-source Resolution Links."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from common import PersistenceConflict, PersistenceError, sha256_json


def _bundle_label(value: Any, side: str) -> str:
    if not isinstance(value, dict):
        raise PersistenceError(f"resolution {side}_bundle must be an object")
    label = value.get("label")
    if not isinstance(label, str) or not label:
        raise PersistenceError(f"resolution {side}_bundle is missing label")
    return label


def _ref(value: Any, field: str) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise PersistenceError(f"resolution {field} must be an object")
    bundle = value.get("bundle")
    ref = value.get("ref")
    if not isinstance(bundle, str) or not bundle or not isinstance(ref, str) or not ref:
        raise PersistenceError(f"resolution {field} requires bundle/ref")
    return bundle, ref


def _verify_bundle_metadata(conn, bundle_ref: dict[str, Any], side: str) -> str:
    label = _bundle_label(bundle_ref, side)
    source_ref = bundle_ref.get("source_ref")
    source_title = bundle_ref.get("source_title")
    row = conn.execute(
        "SELECT source_ref, source_title FROM chronicle.source_bundles WHERE bundle_label = %s",
        (label,),
    ).fetchone()
    if row is None:
        raise PersistenceConflict(f"resolution {side} bundle {label!r} is not persisted")
    if row[0] != source_ref or row[1] != source_title:
        raise PersistenceConflict(
            f"resolution {side} bundle metadata conflicts for {label!r}: "
            f"database=({row[0]!r}, {row[1]!r}) input=({source_ref!r}, {source_title!r})"
        )
    return label


def persist_resolution(conn, resolution: dict[str, Any]) -> tuple[str, dict[str, int]]:
    artifact_sha = sha256_json(resolution)
    left_bundle = resolution.get("left_bundle")
    right_bundle = resolution.get("right_bundle")
    if not isinstance(left_bundle, dict) or not isinstance(right_bundle, dict):
        raise PersistenceError("resolution is missing left_bundle/right_bundle")
    left_label = _verify_bundle_metadata(conn, left_bundle, "left")
    right_label = _verify_bundle_metadata(conn, right_bundle, "right")
    schema_name = resolution.get("schema")
    version = resolution.get("version")
    if not isinstance(schema_name, str) or not isinstance(version, str):
        raise PersistenceError("resolution is missing schema/version")

    created = conn.execute(
        """
        INSERT INTO chronicle.resolution_artifacts(
            artifact_sha256, schema_name, schema_version,
            left_bundle_label, right_bundle_label, payload
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (artifact_sha256) DO NOTHING
        """,
        (artifact_sha, schema_name, version, left_label, right_label, Jsonb(resolution)),
    ).rowcount == 1
    if not created:
        row = conn.execute(
            "SELECT payload FROM chronicle.resolution_artifacts WHERE artifact_sha256 = %s",
            (artifact_sha,),
        ).fetchone()
        if row is None or row[0] != resolution:
            raise PersistenceConflict(f"resolution artifact hash collision/conflict {artifact_sha}")

    inserted = {"artifacts": int(created), "entity_links": 0, "event_links": 0, "warnings": 0}

    for link in resolution.get("entity_links") or []:
        left_bundle_label, left_ref = _ref(link.get("left"), "entity link left")
        right_bundle_label, right_ref = _ref(link.get("right"), "entity link right")
        candidate_id = link.get("candidate_id")
        result = conn.execute(
            """
            INSERT INTO chronicle.resolution_entity_links(
                resolution_sha256, candidate_id,
                left_bundle_label, left_record_ref,
                right_bundle_label, right_record_ref,
                decision, confidence, rationale, signals, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resolution_sha256, candidate_id) DO NOTHING
            """,
            (
                artifact_sha, candidate_id,
                left_bundle_label, left_ref, right_bundle_label, right_ref,
                link.get("decision"), link.get("confidence"), link.get("rationale"),
                Jsonb(link.get("signals") or []), Jsonb(link),
            ),
        )
        if result.rowcount == 0:
            row = conn.execute(
                "SELECT payload FROM chronicle.resolution_entity_links "
                "WHERE resolution_sha256 = %s AND candidate_id = %s",
                (artifact_sha, candidate_id),
            ).fetchone()
            if row is None or row[0] != link:
                raise PersistenceConflict(
                    f"resolution entity link {artifact_sha}:{candidate_id} conflicts"
                )
        inserted["entity_links"] += int(result.rowcount == 1)

    for link in resolution.get("event_links") or []:
        left_bundle_label, left_ref = _ref(link.get("left"), "event link left")
        right_bundle_label, right_ref = _ref(link.get("right"), "event link right")
        candidate_id = link.get("candidate_id")
        result = conn.execute(
            """
            INSERT INTO chronicle.resolution_event_links(
                resolution_sha256, candidate_id,
                left_bundle_label, left_record_ref,
                right_bundle_label, right_record_ref,
                decision, confidence, rationale, signals, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resolution_sha256, candidate_id) DO NOTHING
            """,
            (
                artifact_sha, candidate_id,
                left_bundle_label, left_ref, right_bundle_label, right_ref,
                link.get("decision"), link.get("confidence"), link.get("rationale"),
                Jsonb(link.get("signals") or []), Jsonb(link),
            ),
        )
        if result.rowcount == 0:
            row = conn.execute(
                "SELECT payload FROM chronicle.resolution_event_links "
                "WHERE resolution_sha256 = %s AND candidate_id = %s",
                (artifact_sha, candidate_id),
            ).fetchone()
            if row is None or row[0] != link:
                raise PersistenceConflict(
                    f"resolution event link {artifact_sha}:{candidate_id} conflicts"
                )
        inserted["event_links"] += int(result.rowcount == 1)

    for index, warning in enumerate(resolution.get("warnings") or []):
        result = conn.execute(
            """
            INSERT INTO chronicle.resolution_warnings(resolution_sha256, warning_index, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (resolution_sha256, warning_index) DO NOTHING
            """,
            (artifact_sha, index, Jsonb(warning)),
        )
        if result.rowcount == 0:
            row = conn.execute(
                "SELECT payload FROM chronicle.resolution_warnings "
                "WHERE resolution_sha256 = %s AND warning_index = %s",
                (artifact_sha, index),
            ).fetchone()
            if row is None or row[0] != warning:
                raise PersistenceConflict(
                    f"resolution warning {artifact_sha}[{index}] conflicts"
                )
        inserted["warnings"] += int(result.rowcount == 1)

    return artifact_sha, inserted
