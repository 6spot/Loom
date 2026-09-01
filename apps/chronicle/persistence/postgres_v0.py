"""Chronicle PostgreSQL persistence v0 orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from canonical_store import persist_catalog
from common import PersistenceConflict, PersistenceError, import_key
from migrations import apply_migrations
from resolution_store import persist_resolution
from staged_store import persist_bundle


@dataclass(frozen=True)
class PersistResult:
    import_key: str
    import_created: bool
    bundle_hashes: dict[str, str]
    resolution_hashes: list[str]
    catalog_hash: str
    inserted: dict[str, Any]
    totals: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _database_totals(conn) -> dict[str, int]:
    tables = {
        "source_bundles": "source_bundles",
        "staged_entities": "staged_entities",
        "staged_events": "staged_events",
        "staged_claims": "staged_claims",
        "resolution_artifacts": "resolution_artifacts",
        "resolution_entity_links": "resolution_entity_links",
        "resolution_event_links": "resolution_event_links",
        "canonical_catalogs": "canonical_catalogs",
        "canonical_entities": "canonical_entities",
        "canonical_events": "canonical_events",
        "canonical_entity_representations": "canonical_entity_representations",
        "canonical_event_representations": "canonical_event_representations",
        "canonical_event_relations": "canonical_event_relations",
        "import_sets": "import_sets",
    }
    result: dict[str, int] = {}
    for key, table in tables.items():
        row = conn.execute(f"SELECT count(*) FROM chronicle.{table}").fetchone()
        result[key] = int(row[0])
    return result


def persist_dataset(
    conn,
    *,
    bundles: dict[str, dict[str, Any]],
    resolutions: list[dict[str, Any]],
    catalog: dict[str, Any],
) -> PersistResult:
    if not bundles:
        raise PersistenceError("persistence requires at least one staged bundle")

    with conn.transaction():
        bundle_hashes: dict[str, str] = {}
        bundle_inserted: dict[str, dict[str, int]] = {}
        for label in sorted(bundles):
            artifact_sha, inserted = persist_bundle(conn, label, bundles[label])
            bundle_hashes[label] = artifact_sha
            bundle_inserted[label] = inserted

        resolution_hashes: list[str] = []
        resolution_inserted: list[dict[str, int]] = []
        for resolution in resolutions:
            artifact_sha, inserted = persist_resolution(conn, resolution)
            resolution_hashes.append(artifact_sha)
            resolution_inserted.append(inserted)

        catalog_hash, catalog_inserted = persist_catalog(conn, catalog)
        key = import_key(bundle_hashes, resolution_hashes, catalog_hash)
        bundle_artifacts = [
            {"label": label, "sha256": bundle_hashes[label]}
            for label in sorted(bundle_hashes)
        ]
        resolution_artifacts = sorted(resolution_hashes)
        created = conn.execute(
            """
            INSERT INTO chronicle.import_sets(
                import_key, bundle_artifacts, resolution_artifacts, catalog_sha256
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (import_key) DO NOTHING
            """,
            (key, Jsonb(bundle_artifacts), Jsonb(resolution_artifacts), catalog_hash),
        ).rowcount == 1
        if not created:
            row = conn.execute(
                """
                SELECT bundle_artifacts, resolution_artifacts, catalog_sha256
                FROM chronicle.import_sets WHERE import_key = %s
                """,
                (key,),
            ).fetchone()
            expected = (bundle_artifacts, resolution_artifacts, catalog_hash)
            if row is None or tuple(row) != expected:
                raise PersistenceConflict(f"import set {key} conflicts with stored metadata")

        totals = _database_totals(conn)
        return PersistResult(
            import_key=key,
            import_created=created,
            bundle_hashes=bundle_hashes,
            resolution_hashes=resolution_hashes,
            catalog_hash=catalog_hash,
            inserted={
                "bundles": bundle_inserted,
                "resolutions": resolution_inserted,
                "catalog": catalog_inserted,
            },
            totals=totals,
        )


def persist_to_url(
    database_url: str,
    *,
    bundles: dict[str, dict[str, Any]],
    resolutions: list[dict[str, Any]],
    catalog: dict[str, Any],
) -> PersistResult:
    if not database_url:
        raise PersistenceError("database URL is empty")
    try:
        with psycopg.connect(database_url) as conn:
            apply_migrations(conn)
            return persist_dataset(
                conn,
                bundles=bundles,
                resolutions=resolutions,
                catalog=catalog,
            )
    except PersistenceError:
        raise
    except psycopg.Error as exc:
        raise PersistenceError(f"PostgreSQL persistence failed: {exc}") from exc


def inspect_database(database_url: str) -> dict[str, int]:
    try:
        with psycopg.connect(database_url) as conn:
            apply_migrations(conn)
            return _database_totals(conn)
    except PersistenceError:
        raise
    except psycopg.Error as exc:
        raise PersistenceError(f"PostgreSQL inspection failed: {exc}") from exc
