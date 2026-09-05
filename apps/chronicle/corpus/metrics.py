#!/usr/bin/env python3
"""Emit a deterministic Chronicle corpus/control-plane density snapshot.

C1-T13 uses this operator-side report for before/after acceptance.  It reads
only Chronicle application-owned PostgreSQL state and never interprets counts
as historical truth or quality by themselves.  The snapshot is intentionally
small and stable so T14 Coverage can consume or supersede it without parsing
human prose.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - deployment/CI installs requirements
    raise SystemExit(
        "metrics.py requires psycopg (apps/chronicle/persistence/requirements.txt)"
    ) from exc

SCHEMA = "chronicle.corpus-density-snapshot"
VERSION = "0.1"


def _scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] if row is not None else 0)


def _status_counts(conn, table: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT status, count(*) FROM chronicle.{table} GROUP BY status ORDER BY status"
    ).fetchall()
    return {str(status): int(count) for status, count in rows}


def snapshot(conn) -> dict[str, Any]:
    """Return one deterministic operational/corpus density snapshot."""
    latest_catalog = conn.execute(
        """
        SELECT artifact_sha256
        FROM chronicle.canonical_catalogs
        ORDER BY imported_at DESC, artifact_sha256 DESC
        LIMIT 1
        """
    ).fetchone()
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "control_plane": {
            "documents": _scalar(conn, "SELECT count(*) FROM chronicle.documents"),
            "document_revisions": _scalar(
                conn, "SELECT count(*) FROM chronicle.document_revisions"
            ),
            "ingestion_jobs": _scalar(
                conn, "SELECT count(*) FROM chronicle.ingestion_jobs"
            ),
            "ingestion_jobs_by_status": _status_counts(conn, "ingestion_jobs"),
            "ingestion_sections": _scalar(
                conn, "SELECT count(*) FROM chronicle.ingestion_sections"
            ),
            "ingestion_chunks": _scalar(
                conn, "SELECT count(*) FROM chronicle.ingestion_chunks"
            ),
            "ingestion_chunk_runs": _scalar(
                conn, "SELECT count(*) FROM chronicle.ingestion_chunk_runs"
            ),
            "review_items": _scalar(
                conn, "SELECT count(*) FROM chronicle.review_items"
            ),
            "open_reviews": _scalar(
                conn,
                "SELECT count(*) FROM chronicle.review_items WHERE status = 'open'",
            ),
            "open_resolution_reviews": _scalar(
                conn,
                """
                SELECT count(*) FROM chronicle.review_items
                WHERE status = 'open' AND payload->>'scope' = 'resolution'
                """,
            ),
        },
        "historical_knowledge": {
            "source_bundles": _scalar(
                conn, "SELECT count(*) FROM chronicle.source_bundles"
            ),
            "staged_entities": _scalar(
                conn, "SELECT count(*) FROM chronicle.staged_entities"
            ),
            "staged_events": _scalar(
                conn, "SELECT count(*) FROM chronicle.staged_events"
            ),
            "staged_claims": _scalar(
                conn, "SELECT count(*) FROM chronicle.staged_claims"
            ),
            "resolution_artifacts": _scalar(
                conn, "SELECT count(*) FROM chronicle.resolution_artifacts"
            ),
            "canonical_entities": _scalar(
                conn, "SELECT count(*) FROM chronicle.canonical_entities"
            ),
            "canonical_events": _scalar(
                conn, "SELECT count(*) FROM chronicle.canonical_events"
            ),
            "canonical_event_relations": _scalar(
                conn, "SELECT count(*) FROM chronicle.canonical_event_relations"
            ),
            "latest_catalog_sha256": latest_catalog[0] if latest_catalog else None,
        },
        "reader_presentation": {
            "presentations": _scalar(
                conn, "SELECT count(*) FROM chronicle.reader_presentations"
            ),
            "published_presentations": _scalar(
                conn,
                "SELECT count(*) FROM chronicle.reader_presentations WHERE status = 'published'",
            ),
            "blocks": _scalar(
                conn, "SELECT count(*) FROM chronicle.reader_presentation_blocks"
            ),
            "supports": _scalar(
                conn, "SELECT count(*) FROM chronicle.reader_presentation_supports"
            ),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CHRONICLE_DATABASE_URL"),
        help="Chronicle PostgreSQL URL (default: CHRONICLE_DATABASE_URL)",
    )
    parser.add_argument("--output", help="Optional JSON output path")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.database_url:
        raise SystemExit(
            "Chronicle database URL is required via --database-url or CHRONICLE_DATABASE_URL"
        )
    with psycopg.connect(args.database_url) as conn:
        payload = snapshot(conn)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
