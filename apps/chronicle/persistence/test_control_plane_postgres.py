"""PostgreSQL 18 integration tests for the Chronicle C1 control plane.

Covers migration 0002 on top of the frozen C0 baseline: C0 preservation,
non-destructive revision supersession, job/stage/chunk/review transition
invariants, restart-safe worker leases, and a deterministic fake lifecycle
(create revision -> queue -> claim -> stage progress -> chunk retry ->
needs_review -> resume -> completed) with full provenance back to one
immutable revision.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from common import PersistenceConflict, PersistenceError
from control_plane_store import (
    PIPELINE_ORDER,
    claim_job,
    create_chunk,
    create_document,
    create_revision,
    create_section,
    finish_chunk_run,
    get_job,
    heartbeat_job,
    job_provenance,
    open_review,
    open_reviews,
    publish_output,
    queue_job,
    resolve_review,
    save_job_checkpoint,
    start_chunk_run,
    transition_chunk,
    transition_job,
    transition_stage,
)
from migrations import apply_migrations


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

C0_TABLES = (
    "source_bundles",
    "staged_entities",
    "staged_events",
    "staged_claims",
    "staged_warnings",
    "resolution_artifacts",
    "resolution_entity_links",
    "resolution_event_links",
    "resolution_warnings",
    "canonical_catalogs",
    "canonical_entities",
    "canonical_events",
    "canonical_catalog_entities",
    "canonical_catalog_events",
    "canonical_entity_representations",
    "canonical_event_representations",
    "canonical_event_relations",
    "canonical_catalog_relations",
    "canonical_event_relation_links",
    "canonical_warnings",
    "import_sets",
)

C1_TABLES = (
    "documents",
    "document_revisions",
    "ingestion_jobs",
    "ingestion_job_stages",
    "ingestion_sections",
    "ingestion_chunks",
    "ingestion_chunk_runs",
    "review_items",
    "ingestion_outputs",
)


def _control_url() -> str:
    explicit = os.environ.get("LOOM_TEST_POSTGRES_URL")
    url = explicit or DEFAULT_CONTROL_URL
    try:
        with psycopg.connect(url, connect_timeout=2):
            return url
    except psycopg.Error:
        if explicit:
            raise
    subprocess.run(
        ["bash", "tools/postgres-test.sh", "up"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with psycopg.connect(url, connect_timeout=10):
        return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


class _Ids:
    """Deterministic UUIDv7 sequence for repeatable fixtures."""

    def __init__(self) -> None:
        self.counter = 0

    def next(self) -> str:
        self.counter += 1
        n = self.counter
        return f"019535d9-3df7-7{n:03x}-8000-{n:012x}"


def _sha(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class ControlPlanePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.ids = _Ids()
        self.database_name = f"chronicle_c1_test_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _connect_ready(self):
        conn = psycopg.connect(self.database_url)
        apply_migrations(conn)
        return conn

    def _tables(self, conn) -> set[str]:
        rows = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'chronicle'
            """
        ).fetchall()
        return {row[0] for row in rows}

    # -- C0 preservation ----------------------------------------------------

    def test_c0_tables_preserved_and_writable(self) -> None:
        with self._connect_ready() as conn:
            tables = self._tables(conn)
            for expected in C0_TABLES:
                self.assertIn(expected, tables, f"C0 table missing: {expected}")
            for expected in C1_TABLES:
                self.assertIn(expected, tables, f"C1 table missing: {expected}")
            # The C0 staged path still accepts writes after 0002.
            bundle = {
                "schema_version": "0.1",
                "source": {"temp_id": "src_001", "title": "Control Plane Probe"},
                "entities": [],
                "events": [],
                "claims": [],
                "warnings": [],
            }
            from psycopg.types.json import Jsonb

            from common import sha256_json

            artifact = sha256_json(bundle)
            conn.execute(
                """
                INSERT INTO chronicle.source_bundles(
                    bundle_label, schema_version, source_ref, source_title,
                    artifact_sha256, source_payload, bundle_payload
                ) VALUES ('probe', '0.1', 'src_001', 'Control Plane Probe',
                          %s, %s, %s)
                """,
                (artifact, Jsonb(bundle["source"]), Jsonb(bundle)),
            )
            count = conn.execute(
                "SELECT count(*) FROM chronicle.source_bundles WHERE bundle_label = 'probe'"
            ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_migrations_are_idempotent(self) -> None:
        with self._connect_ready() as conn:
            apply_migrations(conn)
            versions = conn.execute(
                "SELECT version FROM chronicle.schema_migrations ORDER BY version"
            ).fetchall()
            self.assertEqual(
                [row[0] for row in versions],
                ["0001_chronicle_v0.sql", "0002_chronicle_c1_control_plane.sql"],
            )

    # -- Revision supersession ----------------------------------------------

    def test_supersession_is_non_destructive_and_auditable(self) -> None:
        with self._connect_ready() as conn:
            document_id = create_document(conn, title="Book A", document_id=self.ids.next())
            rev1 = create_revision(
                conn,
                document_id=document_id,
                source_ref="artifacts/book-a/v1.txt",
                source_sha256=_sha("book-a-v1"),
                source_length_bytes=100,
                revision_id=self.ids.next(),
            )
            rev2 = create_revision(
                conn,
                document_id=document_id,
                source_ref="artifacts/book-a/v2.txt",
                source_sha256=_sha("book-a-v2"),
                source_length_bytes=120,
                supersedes_revision_id=rev1["revision_id"],
                revision_id=self.ids.next(),
            )
            self.assertEqual(rev1["revision_number"], 1)
            self.assertEqual(rev2["revision_number"], 2)
            self.assertEqual(rev2["supersedes_revision_id"], rev1["revision_id"])
            rows = conn.execute(
                """
                SELECT revision_id::text, revision_number, source_sha256,
                       supersedes_revision_id::text
                FROM chronicle.document_revisions
                WHERE document_id = %s ORDER BY revision_number
                """,
                (document_id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            # The old uploaded source is untouched: same hash, no overwrite.
            self.assertEqual(rows[0][2], _sha("book-a-v1"))
            self.assertIsNone(rows[0][3])
            # Replacing without a supersession link is rejected.
            with self.assertRaises(PersistenceConflict):
                create_revision(
                    conn,
                    document_id=document_id,
                    source_ref="artifacts/book-a/v3.txt",
                    source_sha256=_sha("book-a-v3"),
                    source_length_bytes=130,
                    revision_id=self.ids.next(),
                )
            # Revisions are immutable at the database level too.
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.document_revisions SET source_ref = 'x' "
                        "WHERE revision_id = %s",
                        (rev1["revision_id"],),
                    )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM chronicle.document_revisions WHERE revision_id = %s",
                        (rev1["revision_id"],),
                    )

    def test_supersession_cannot_cross_documents(self) -> None:
        with self._connect_ready() as conn:
            doc_a = create_document(conn, title="Book A", document_id=self.ids.next())
            doc_b = create_document(conn, title="Book B", document_id=self.ids.next())
            rev_a = create_revision(
                conn,
                document_id=doc_a,
                source_ref="artifacts/a/v1.txt",
                source_sha256=_sha("a-v1"),
                source_length_bytes=10,
                revision_id=self.ids.next(),
            )
            with self.assertRaises(PersistenceConflict):
                create_revision(
                    conn,
                    document_id=doc_b,
                    source_ref="artifacts/b/v1.txt",
                    source_sha256=_sha("b-v1"),
                    source_length_bytes=10,
                    supersedes_revision_id=rev_a["revision_id"],
                    revision_id=self.ids.next(),
                )

    # -- Transition invariants ----------------------------------------------

    def test_illegal_transitions_are_rejected(self) -> None:
        with self._connect_ready() as conn:
            document_id = create_document(conn, title="Book", document_id=self.ids.next())
            revision = create_revision(
                conn,
                document_id=document_id,
                source_ref="artifacts/book/v1.txt",
                source_sha256=_sha("book-v1"),
                source_length_bytes=10,
                revision_id=self.ids.next(),
            )
            job_id = queue_job(
                conn,
                document_id=document_id,
                revision_id=revision["revision_id"],
                job_id=self.ids.next(),
            )
            # queued -> completed skips running: illegal.
            with self.assertRaises(PersistenceConflict):
                transition_job(conn, job_id, "completed")
            # Unknown vocabulary is rejected before any write.
            with self.assertRaises(PersistenceError):
                transition_job(conn, job_id, "archived")
            claimed = claim_job(conn, worker_id="worker-1")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["job_id"], job_id)
            # running <- queued is legal; running -> queued is not.
            with self.assertRaises(PersistenceConflict):
                transition_job(conn, job_id, "queued")
            # Stage vocabulary: pending -> completed skips running: illegal.
            with self.assertRaises(PersistenceConflict):
                transition_stage(conn, job_id, "prepare", "completed")
            with self.assertRaises(PersistenceError):
                transition_stage(conn, job_id, "nope", "running")
            # Terminal states are terminal.
            transition_job(conn, job_id, "cancelled")
            with self.assertRaises(PersistenceConflict):
                transition_job(conn, job_id, "running")

    def test_chunk_and_review_transitions(self) -> None:
        with self._connect_ready() as conn:
            document_id = create_document(conn, title="Book", document_id=self.ids.next())
            revision = create_revision(
                conn,
                document_id=document_id,
                source_ref="artifacts/book/v1.txt",
                source_sha256=_sha("book-v1"),
                source_length_bytes=64,
                revision_id=self.ids.next(),
            )
            job_id = queue_job(
                conn,
                document_id=document_id,
                revision_id=revision["revision_id"],
                job_id=self.ids.next(),
            )
            section_id = create_section(
                conn,
                job_id=job_id,
                revision_id=revision["revision_id"],
                section_index=0,
                source_start_offset=0,
                source_end_offset=64,
                section_id=self.ids.next(),
            )
            chunk_id = create_chunk(
                conn,
                job_id=job_id,
                section_id=section_id,
                revision_id=revision["revision_id"],
                chunk_index=0,
                source_start_offset=0,
                source_end_offset=64,
                source_sha256=_sha("chunk-0"),
                chunk_id=self.ids.next(),
            )
            with self.assertRaises(PersistenceConflict):
                transition_chunk(conn, chunk_id, "completed")
            review_id = open_review(
                conn,
                job_id=job_id,
                revision_id=revision["revision_id"],
                kind="extraction",
                chunk_id=chunk_id,
                stage="extract",
                review_id=self.ids.next(),
            )
            resolve_review(conn, review_id, "approved", resolution={"by": "operator"})
            with self.assertRaises(PersistenceConflict):
                resolve_review(conn, review_id, "rejected")
            # Chunk runs are append-only history.
            run_id = start_chunk_run(
                conn,
                chunk_id=chunk_id,
                job_id=job_id,
                attempt_number=1,
                run_id=self.ids.next(),
            )
            finish_chunk_run(conn, run_id, "failed", error={"reason": "timeout"})
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM chronicle.ingestion_chunk_runs WHERE run_id = %s",
                        (run_id,),
                    )

    # -- Restart-safe leases --------------------------------------------------

    def test_expired_lease_is_reclaimable_with_checkpoint(self) -> None:
        with self._connect_ready() as conn:
            document_id = create_document(conn, title="Book", document_id=self.ids.next())
            revision = create_revision(
                conn,
                document_id=document_id,
                source_ref="artifacts/book/v1.txt",
                source_sha256=_sha("book-v1"),
                source_length_bytes=10,
                revision_id=self.ids.next(),
            )
            job_id = queue_job(
                conn,
                document_id=document_id,
                revision_id=revision["revision_id"],
                job_id=self.ids.next(),
            )
            first = claim_job(conn, worker_id="worker-1", lease_seconds=300)
            self.assertEqual(first["worker_id"], "worker-1")
            self.assertEqual(first["attempt_count"], 1)
            save_job_checkpoint(
                conn, job_id, {"prepare": {"done": True}}, worker_id="worker-1"
            )
            heartbeat_job(conn, job_id=job_id, worker_id="worker-1", lease_seconds=300)
            # A live lease cannot be stolen by another worker.
            stolen = claim_job(conn, worker_id="worker-2")
            self.assertIsNone(stolen)
            # After the lease expires (simulated worker death), another
            # worker reclaims the same job with its checkpoint intact.
            conn.execute(
                "UPDATE chronicle.ingestion_jobs "
                "SET lease_expires_at = now() - make_interval(secs => 1) "
                "WHERE job_id = %s",
                (job_id,),
            )
            second = claim_job(conn, worker_id="worker-2", lease_seconds=300)
            self.assertIsNotNone(second)
            self.assertEqual(second["worker_id"], "worker-2")
            self.assertEqual(second["attempt_count"], 2)
            self.assertEqual(second["checkpoint"], {"prepare": {"done": True}})
            # Heartbeats from the dead worker are rejected.
            with self.assertRaises(PersistenceConflict):
                heartbeat_job(conn, job_id=job_id, worker_id="worker-1")

    # -- Deterministic fake lifecycle -----------------------------------------

    def test_fake_restart_retry_review_lifecycle(self) -> None:
        with self._connect_ready() as conn:
            document_id = create_document(conn, title="Book", document_id=self.ids.next())
            revision = create_revision(
                conn,
                document_id=document_id,
                source_ref="artifacts/book/v1.txt",
                source_sha256=_sha("book-v1"),
                source_length_bytes=128,
                revision_id=self.ids.next(),
            )
            job_id = queue_job(
                conn,
                document_id=document_id,
                revision_id=revision["revision_id"],
                job_id=self.ids.next(),
            )
            claimed = claim_job(conn, worker_id="fake-worker")
            assert claimed is not None
            for stage in ("prepare", "structure", "segment"):
                transition_stage(conn, job_id, stage, "running")
                transition_stage(conn, job_id, stage, "completed")
            section_id = create_section(
                conn,
                job_id=job_id,
                revision_id=revision["revision_id"],
                section_index=0,
                source_start_offset=0,
                source_end_offset=128,
                section_id=self.ids.next(),
            )
            chunk_id = create_chunk(
                conn,
                job_id=job_id,
                section_id=section_id,
                revision_id=revision["revision_id"],
                chunk_index=0,
                source_start_offset=0,
                source_end_offset=128,
                source_sha256=_sha("chunk-full"),
                coordinates={"section": 0, "chunk": 0},
                chunk_id=self.ids.next(),
            )
            # First attempt fails; the retry is a new run, not a rewrite.
            transition_chunk(conn, chunk_id, "processing")
            run1 = start_chunk_run(
                conn, chunk_id=chunk_id, job_id=job_id,
                attempt_number=1, worker_id="fake-worker",
                run_id=self.ids.next(),
            )
            finish_chunk_run(conn, run1, "failed", error={"reason": "fake-timeout"})
            transition_chunk(conn, chunk_id, "failed")
            transition_chunk(conn, chunk_id, "processing")
            run2 = start_chunk_run(
                conn, chunk_id=chunk_id, job_id=job_id,
                attempt_number=2, worker_id="fake-worker",
                run_id=self.ids.next(),
            )
            finish_chunk_run(conn, run2, "succeeded")
            transition_chunk(conn, chunk_id, "completed")
            for stage in ("extract", "assemble", "resolve"):
                transition_stage(conn, job_id, stage, "running")
                transition_stage(conn, job_id, stage, "completed")
            # Human review gate: job pauses, review resolves, job resumes.
            transition_job(conn, job_id, "needs_review")
            review_id = open_review(
                conn,
                job_id=job_id,
                revision_id=revision["revision_id"],
                kind="resolution_decision",
                stage="resolve",
                payload={"candidate": "same_occurrence?"},
                review_id=self.ids.next(),
            )
            self.assertEqual(len(open_reviews(conn, job_id)), 1)
            resolve_review(conn, review_id, "approved", resolution={"decision": "same_occurrence"})
            self.assertEqual(open_reviews(conn, job_id), [])
            transition_job(conn, job_id, "running")
            for stage in ("publish", "present"):
                transition_stage(conn, job_id, stage, "running")
                transition_stage(conn, job_id, stage, "completed")
            publish_output(
                conn,
                job_id=job_id,
                revision_id=revision["revision_id"],
                output_kind="staged_bundle",
                artifact_sha256=_sha("output-bundle"),
                payload={"bundle_label": "book-v1"},
                output_id=self.ids.next(),
            )
            transition_job(conn, job_id, "completed")
            final = get_job(conn, job_id)
            self.assertEqual(final["status"], "completed")
            self.assertIsNotNone(final["finished_at"])
            # Provenance traces every artifact to the one immutable revision.
            provenance = job_provenance(conn, job_id)
            self.assertEqual(provenance["revision"]["revision_id"], revision["revision_id"])
            self.assertEqual(len(provenance["stages"]), len(PIPELINE_ORDER))
            self.assertTrue(
                all(stage["status"] == "completed" for stage in provenance["stages"])
            )
            self.assertEqual(len(provenance["chunks"]), 1)
            self.assertEqual(len(provenance["runs"]), 2)
            self.assertEqual(len(provenance["reviews"]), 1)
            self.assertEqual(len(provenance["outputs"]), 1)
            run_statuses = {run[3] for run in provenance["runs"]}
            self.assertEqual(run_statuses, {"failed", "succeeded"})


if __name__ == "__main__":
    unittest.main()
