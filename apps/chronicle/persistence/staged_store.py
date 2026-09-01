"""Persistence for Chronicle source-owned staged bundles."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from common import PersistenceConflict, PersistenceError, record_ref, sha256_json


def _ensure_bundle(conn, label: str, bundle: dict[str, Any], artifact_sha: str) -> bool:
    source = bundle.get("source")
    if not isinstance(source, dict):
        raise PersistenceError(f"bundle {label!r} is missing source object")
    source_ref = record_ref(source)
    source_title = source.get("title")
    if not isinstance(source_title, str) or not source_title:
        raise PersistenceError(f"bundle {label!r} source is missing title")
    schema_version = bundle.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        raise PersistenceError(f"bundle {label!r} is missing schema_version")

    inserted = conn.execute(
        """
        INSERT INTO chronicle.source_bundles(
            bundle_label, schema_version, source_ref, source_title,
            artifact_sha256, source_payload, bundle_payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (bundle_label) DO NOTHING
        """,
        (
            label,
            schema_version,
            source_ref,
            source_title,
            artifact_sha,
            Jsonb(source),
            Jsonb(bundle),
        ),
    ).rowcount == 1
    if inserted:
        return True

    row = conn.execute(
        "SELECT artifact_sha256 FROM chronicle.source_bundles WHERE bundle_label = %s",
        (label,),
    ).fetchone()
    if row is None or row[0] != artifact_sha:
        stored = row[0] if row else "<missing>"
        raise PersistenceConflict(
            f"bundle label {label!r} already exists with different content: "
            f"database={stored} input={artifact_sha}"
        )
    return False


def _ensure_record(
    conn,
    *,
    table: str,
    label: str,
    record: dict[str, Any],
) -> bool:
    ref = record_ref(record)
    payload_sha = sha256_json(record)
    if table not in {"staged_entities", "staged_events", "staged_claims"}:
        raise PersistenceError(f"unsupported staged table {table!r}")
    inserted = conn.execute(
        f"""
        INSERT INTO chronicle.{table}(bundle_label, record_ref, payload_sha256, payload)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (bundle_label, record_ref) DO NOTHING
        """,
        (label, ref, payload_sha, Jsonb(record)),
    ).rowcount == 1
    if inserted:
        return True

    row = conn.execute(
        f"SELECT payload_sha256 FROM chronicle.{table} "
        "WHERE bundle_label = %s AND record_ref = %s",
        (label, ref),
    ).fetchone()
    if row is None or row[0] != payload_sha:
        stored = row[0] if row else "<missing>"
        raise PersistenceConflict(
            f"{table} {label}:{ref} already exists with different content: "
            f"database={stored} input={payload_sha}"
        )
    return False


def persist_bundle(conn, label: str, bundle: dict[str, Any]) -> tuple[str, dict[str, int]]:
    artifact_sha = sha256_json(bundle)
    inserted = {
        "bundles": int(_ensure_bundle(conn, label, bundle, artifact_sha)),
        "entities": 0,
        "events": 0,
        "claims": 0,
        "warnings": 0,
    }

    for record in bundle.get("entities") or []:
        inserted["entities"] += int(
            _ensure_record(conn, table="staged_entities", label=label, record=record)
        )
    for record in bundle.get("events") or []:
        inserted["events"] += int(
            _ensure_record(conn, table="staged_events", label=label, record=record)
        )
    for record in bundle.get("claims") or []:
        inserted["claims"] += int(
            _ensure_record(conn, table="staged_claims", label=label, record=record)
        )

    for index, warning in enumerate(bundle.get("warnings") or []):
        created = conn.execute(
            """
            INSERT INTO chronicle.staged_warnings(bundle_label, warning_index, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (bundle_label, warning_index) DO NOTHING
            """,
            (label, index, Jsonb(warning)),
        ).rowcount == 1
        if not created:
            row = conn.execute(
                "SELECT payload FROM chronicle.staged_warnings "
                "WHERE bundle_label = %s AND warning_index = %s",
                (label, index),
            ).fetchone()
            if row is None or row[0] != warning:
                raise PersistenceConflict(
                    f"staged warning {label}[{index}] already exists with different content"
                )
        inserted["warnings"] += int(created)

    return artifact_sha, inserted
