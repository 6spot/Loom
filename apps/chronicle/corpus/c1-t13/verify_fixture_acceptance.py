#!/usr/bin/env python3
"""Verify the full C1-T13 fixture-driven corpus loop against PostgreSQL.

This checker proves development acceptance without treating fixture output as a
live-model deployment acceptance.  It checks the persisted product path: six
Studio jobs completed, exact frozen Claims survived normal extraction/assembly,
real source/resolution/catalog outputs replaced the generic fake completion
artifact, Reader Presentation was persisted with fixture provenance, and no
review debt remains.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg


class AcceptanceError(RuntimeError):
    pass


def _load(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"cannot read {description} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"{description} must be a JSON object")
    return value


def _count(conn, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] if row else 0)


def verify(
    *, database_url: str, baseline_path: Path, fixture_pack_path: Path
) -> dict[str, Any]:
    baseline = _load(baseline_path, "baseline snapshot")
    fixture = _load(fixture_pack_path, "fixture pack")
    rules = (fixture.get("extraction") or {}).get("rules")
    if not isinstance(rules, list) or not rules:
        raise AcceptanceError("fixture pack has no extraction rules")
    model_version = fixture.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise AcceptanceError("fixture pack has no model_version")
    extraction_model = f"fixture:{model_version}:extract"
    presentation_model = f"fixture:{model_version}:present"
    expected_titles = sorted({str(rule.get("document")) for rule in rules})
    expected_evidence = {
        (str(rule.get("document")), str(rule.get("evidence"))) for rule in rules
    }

    errors: list[str] = []
    with psycopg.connect(database_url) as conn:
        jobs = conn.execute(
            """
            SELECT j.job_id, j.status, d.title, r.revision_id, r.source_sha256
            FROM chronicle.ingestion_jobs j
            JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
            JOIN chronicle.documents d ON d.document_id = r.document_id
            ORDER BY d.title, j.job_id
            """
        ).fetchall()
        fixture_jobs = [row for row in jobs if row[2] in expected_titles]
        if len(fixture_jobs) != 6:
            errors.append(f"expected 6 fixture jobs, found {len(fixture_jobs)}")
        non_completed = [(str(row[0]), row[1], row[2]) for row in fixture_jobs if row[1] != "completed"]
        if non_completed:
            errors.append(f"fixture jobs not completed: {non_completed}")
        job_ids = [row[0] for row in fixture_jobs]

        open_reviews = _count(
            conn,
            """
            SELECT count(*) FROM chronicle.review_items ri
            JOIN chronicle.ingestion_jobs j ON j.job_id = ri.job_id
            JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
            JOIN chronicle.documents d ON d.document_id = r.document_id
            WHERE d.title = ANY(%s) AND ri.status = 'open'
            """,
            (expected_titles,),
        )
        if open_reviews:
            errors.append(f"{open_reviews} open fixture review items remain")
        resolved_resolution_reviews = _count(
            conn,
            """
            SELECT count(*) FROM chronicle.review_items ri
            JOIN chronicle.ingestion_jobs j ON j.job_id = ri.job_id
            JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
            JOIN chronicle.documents d ON d.document_id = r.document_id
            WHERE d.title = ANY(%s)
              AND ri.status IN ('resolved', 'dismissed')
              AND ri.payload->>'scope' = 'resolution'
            """,
            (expected_titles,),
        )

        bundle_rows = conn.execute(
            """
            SELECT bundle_label, bundle_payload->'source'->>'title'
            FROM chronicle.source_bundles
            WHERE bundle_payload->'source'->>'title' = ANY(%s)
            ORDER BY 2, 1
            """,
            (expected_titles,),
        ).fetchall()
        found_titles = sorted({str(row[1]) for row in bundle_rows})
        if found_titles != expected_titles:
            errors.append(
                f"fixture source-bundle titles differ: expected {expected_titles}, found {found_titles}"
            )
        if len(bundle_rows) != 6:
            errors.append(f"expected exactly 6 T13 source bundles, found {len(bundle_rows)}")

        claim_rows = conn.execute(
            """
            SELECT b.bundle_payload->'source'->>'title',
                   c.payload->'evidence'->>'text'
            FROM chronicle.staged_claims c
            JOIN chronicle.source_bundles b ON b.bundle_label = c.bundle_label
            WHERE b.bundle_payload->'source'->>'title' = ANY(%s)
            """,
            (expected_titles,),
        ).fetchall()
        actual_evidence = {(str(title), str(evidence)) for title, evidence in claim_rows}
        missing_evidence = sorted(expected_evidence - actual_evidence)
        if missing_evidence:
            errors.append(
                "fixture rules missing from persisted staged Claims: "
                + ", ".join(f"{title}:{evidence}" for title, evidence in missing_evidence)
            )

        run_rows = conn.execute(
            """
            SELECT cr.checkpoint->>'model_version', count(*)
            FROM chronicle.ingestion_chunk_runs cr
            JOIN chronicle.ingestion_chunks c ON c.chunk_id = cr.chunk_id
            JOIN chronicle.ingestion_jobs j ON j.job_id = c.job_id
            JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
            JOIN chronicle.documents d ON d.document_id = r.document_id
            WHERE d.title = ANY(%s) AND cr.status = 'completed'
            GROUP BY cr.checkpoint->>'model_version'
            ORDER BY 1
            """,
            (expected_titles,),
        ).fetchall()
        run_models = {str(model): int(count) for model, count in run_rows}
        if set(run_models) != {extraction_model}:
            errors.append(
                f"completed chunk runs are not exclusively fixture extraction model: {run_models}"
            )

        output_rows = conn.execute(
            """
            SELECT o.artifact_type, count(*)
            FROM chronicle.ingestion_outputs o
            JOIN chronicle.ingestion_jobs j ON j.job_id = o.job_id
            JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
            JOIN chronicle.documents d ON d.document_id = r.document_id
            WHERE d.title = ANY(%s)
            GROUP BY o.artifact_type ORDER BY o.artifact_type
            """,
            (expected_titles,),
        ).fetchall()
        outputs = {str(kind): int(count) for kind, count in output_rows}
        if outputs.get("fake-pipeline-result", 0):
            errors.append("real-source fixture jobs wrote forbidden fake-pipeline-result outputs")
        if outputs.get("source-bundle", 0) != 6:
            errors.append(f"expected 6 source-bundle outputs, found {outputs.get('source-bundle', 0)}")
        if outputs.get("canonical-catalog", 0) != 6:
            errors.append(
                f"expected 6 canonical-catalog outputs, found {outputs.get('canonical-catalog', 0)}"
            )

        presentation_rows = conn.execute(
            """
            SELECT model_version, status, count(*)
            FROM chronicle.reader_presentations
            WHERE origin_job_id = ANY(%s)
            GROUP BY model_version, status ORDER BY model_version, status
            """,
            (job_ids,),
        ).fetchall() if job_ids else []
        presentations = {
            f"{model}:{status}": int(count)
            for model, status, count in presentation_rows
        }
        published_fixture_presentations = presentations.get(
            f"{presentation_model}:published", 0
        )
        if published_fixture_presentations < 1:
            errors.append(
                "no published Reader Presentation carries T13 fixture presentation provenance"
            )
        unexpected_presentation_models = [
            key for key in presentations if not key.startswith(presentation_model + ":")
        ]
        if unexpected_presentation_models:
            errors.append(
                "unexpected Reader Presentation model provenance: "
                + ", ".join(unexpected_presentation_models)
            )
        unsupported_blocks = _count(
            conn,
            """
            SELECT count(*)
            FROM chronicle.reader_presentation_blocks b
            JOIN chronicle.reader_presentations p USING (presentation_id)
            WHERE p.origin_job_id = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1 FROM chronicle.reader_presentation_supports s
                  WHERE s.presentation_id = b.presentation_id
                    AND s.block_index = b.block_index
              )
            """,
            (job_ids,),
        ) if job_ids else 0
        if unsupported_blocks:
            errors.append(f"{unsupported_blocks} fixture presentation blocks lack Claim support")

        current = {
            "documents": _count(conn, "SELECT count(*) FROM chronicle.documents"),
            "document_revisions": _count(conn, "SELECT count(*) FROM chronicle.document_revisions"),
            "ingestion_jobs": _count(conn, "SELECT count(*) FROM chronicle.ingestion_jobs"),
            "source_bundles": _count(conn, "SELECT count(*) FROM chronicle.source_bundles"),
            "staged_entities": _count(conn, "SELECT count(*) FROM chronicle.staged_entities"),
            "staged_events": _count(conn, "SELECT count(*) FROM chronicle.staged_events"),
            "staged_claims": _count(conn, "SELECT count(*) FROM chronicle.staged_claims"),
            "canonical_entities": _count(conn, "SELECT count(*) FROM chronicle.canonical_entities"),
            "canonical_events": _count(conn, "SELECT count(*) FROM chronicle.canonical_events"),
            "reader_presentations": _count(conn, "SELECT count(*) FROM chronicle.reader_presentations"),
        }

    base_control = baseline.get("control_plane") or {}
    base_hist = baseline.get("historical_knowledge") or {}
    base_present = baseline.get("reader_presentation") or {}
    expected_deltas = {
        "documents": 6,
        "document_revisions": 6,
        "ingestion_jobs": 6,
        "source_bundles": 6,
    }
    for key, delta in expected_deltas.items():
        base = (
            base_control.get(key, 0)
            if key in {"documents", "document_revisions", "ingestion_jobs"}
            else base_hist.get(key, 0)
        )
        actual_delta = current[key] - int(base or 0)
        if actual_delta != delta:
            errors.append(f"{key} delta expected {delta}, found {actual_delta}")
    for key in ("staged_entities", "staged_events", "staged_claims", "canonical_entities", "canonical_events"):
        base = int(base_hist.get(key, 0) or 0)
        if current[key] <= base:
            errors.append(f"{key} did not increase above baseline {base}")
    if current["staged_claims"] - int(base_hist.get("staged_claims", 0) or 0) < len(rules):
        errors.append(
            f"staged Claims increased by fewer than {len(rules)} frozen fixture rules"
        )
    if current["reader_presentations"] <= int(base_present.get("presentations", 0) or 0):
        errors.append("Reader Presentations did not increase above baseline")

    if errors:
        raise AcceptanceError("; ".join(errors))

    return {
        "schema": "chronicle.c1-t13-fixture-acceptance",
        "version": "0.1",
        "passed": True,
        "development_mode": "explicit-model-boundary-fixture",
        "live_provider_deployment_acceptance": "deferred-to-C1-T17",
        "fixture_model_version": model_version,
        "source_documents": expected_titles,
        "fixture_rules": len(rules),
        "jobs_completed": len(fixture_jobs),
        "resolved_resolution_reviews": resolved_resolution_reviews,
        "chunk_run_models": run_models,
        "ingestion_outputs": outputs,
        "reader_presentations": presentations,
        "persisted_fixture_claims": len(actual_evidence & expected_evidence),
        "current_counts": current,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("CHRONICLE_DATABASE_URL"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--fixture-pack", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or CHRONICLE_DATABASE_URL is required")
    try:
        report = verify(
            database_url=args.database_url,
            baseline_path=args.baseline,
            fixture_pack_path=args.fixture_pack,
        )
    except AcceptanceError as exc:
        print(f"chronicle C1-T13 fixture acceptance: FAIL: {exc}")
        return 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
