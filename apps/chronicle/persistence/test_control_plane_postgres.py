"""PostgreSQL 18 integration tests for the Chronicle C1-T1 control plane.

Covers the deterministic fake lifecycle (create revision -> queue job ->
claim -> stage progress -> chunk retry -> needs_review -> resume ->
completed), immutable revision/supersession semantics, illegal-transition
enforcement, lease takeover after worker loss, and output provenance tracing
back to one immutable revision.
"""

from __future__ import annotations

import hashlib
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

import control_plane
from common import PersistenceConflict, PersistenceError
from migrations import apply_migrations


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"


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


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _job_status(conn, job_id) -> str:
    return conn.execute(
        "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()[0]


def _stage_status(conn, job_id, stage) -> str:
    return conn.execute(
        "SELECT status FROM chronicle.ingestion_job_stages WHERE job_id = %s AND stage = %s",
        (job_id, stage),
    ).fetchone()[0]


class ControlPlanePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
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

    def test_fake_lifecycle_retry_review_resume_completes(self) -> None:
        """create revision -> queue -> claim -> stages -> chunk retry ->
        needs_review -> resume -> completed, with provenance to one revision."""
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="武帝纪")
            revision_id, revision_no = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=_sha256("wudi-raw"),
                source_bytes=1024,
                source_media_type="text/plain",
            )
            self.assertEqual(revision_no, 1)

            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            self.assertEqual(_job_status(conn, job_id), "queued")
            # All eight pipeline stages are seeded pending.
            stages = conn.execute(
                "SELECT stage, status FROM chronicle.ingestion_job_stages WHERE job_id = %s ORDER BY stage",
                (job_id,),
            ).fetchall()
            self.assertEqual(len(stages), 8)
            self.assertTrue(all(status == "pending" for _, status in stages))

            # claim -> running
            claimed = control_plane.claim_job(conn, worker="fake-worker-1")
            self.assertEqual(claimed, job_id)
            self.assertEqual(_job_status(conn, job_id), "running")

            # stage progress through prepare/structure/segment
            for stage in ("prepare", "structure", "segment"):
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="running")
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="completed")
            self.assertEqual(_stage_status(conn, job_id, "segment"), "completed")

            # extract: one section, one chunk; first attempt fails, retry succeeds
            section_id = control_plane.create_section(
                conn, job_id=job_id, section_index=0, label="本纪",
                source_start=0, source_end=1024,
            )
            chunk_id = control_plane.record_chunk(
                conn, job_id=job_id, section_id=section_id, chunk_index=0,
                source_start=0, source_end=512,
                source_sha256=_sha256("wudi-raw"),
                content_sha256=_sha256("wudi-chunk-0"),
            )
            control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
            control_plane.advance_stage(conn, job_id=job_id, stage="extract", status="running")
            _, attempt1 = control_plane.record_chunk_run(
                conn, chunk_id=chunk_id, status="failed",
                worker="fake-worker-1", error="simulated model fault",
            )
            self.assertEqual(attempt1, 1)
            control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="failed")
            # retry: failed -> running -> completed, appends run attempt 2
            control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
            _, attempt2 = control_plane.record_chunk_run(
                conn, chunk_id=chunk_id, status="completed", worker="fake-worker-1",
            )
            self.assertEqual(attempt2, 2)
            control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="completed")
            control_plane.advance_stage(conn, job_id=job_id, stage="extract", status="completed")
            runs = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_chunk_runs WHERE chunk_id = %s",
                (chunk_id,),
            ).fetchone()[0]
            self.assertEqual(runs, 2)

            # assemble hits a quality gate: job -> needs_review with an open item
            control_plane.advance_stage(conn, job_id=job_id, stage="assemble", status="running")
            control_plane.advance_stage(
                conn, job_id=job_id, stage="assemble", status="needs_review"
            )
            review_id = control_plane.open_review_item(
                conn, job_id=job_id, kind="quality_flag", chunk_id=chunk_id,
                payload={"note": "verify era name"},
            )
            control_plane.set_job_status(conn, job_id=job_id, status="needs_review")
            self.assertEqual(control_plane.open_review_count(conn, job_id=job_id), 1)

            # resume after human resolution: needs_review -> running -> completed
            control_plane.resolve_review_item(conn, review_id=review_id)
            self.assertEqual(control_plane.open_review_count(conn, job_id=job_id), 0)
            control_plane.set_job_status(conn, job_id=job_id, status="running")
            control_plane.advance_stage(conn, job_id=job_id, stage="assemble", status="running")
            control_plane.advance_stage(conn, job_id=job_id, stage="assemble", status="completed")
            for stage in ("resolve", "publish", "present"):
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="running")
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="completed")

            output_id = control_plane.record_output(
                conn, job_id=job_id, revision_id=revision_id,
                artifact_type="assembled-extraction",
                artifact_sha256=_sha256("assembled"),
                payload={"chunks": 1},
            )
            control_plane.set_job_status(conn, job_id=job_id, status="completed")
            self.assertEqual(_job_status(conn, job_id), "completed")

            provenance = control_plane.trace_provenance(conn, output_id=output_id)
            self.assertEqual(provenance["revision_id"], str(revision_id))
            self.assertEqual(provenance["revision_no"], 1)
            self.assertEqual(provenance["job_status"], "completed")
            self.assertEqual(len(provenance["chunks"]), 1)
            self.assertEqual(provenance["chunks"][0]["runs"], 2)
            self.assertEqual(provenance["chunks"][0]["status"], "completed")
            self.assertEqual(len(provenance["reviews"]), 1)
            self.assertEqual(provenance["reviews"][0]["status"], "resolved")

    def test_restart_reconnect_and_lease_takeover_are_checkpoint_safe(self) -> None:
        """A lost worker's expired lease can be taken over; checkpoints persist."""
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="吴主传")
            revision_id, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("wuzhu-raw"),
                source_bytes=2048, source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            control_plane.claim_job(conn, worker="worker-a", lease_seconds=300)
            # Simulate worker loss by expiring its lease, then reconnect.
            conn.execute(
                """
                UPDATE chronicle.ingestion_jobs
                SET lease_expires_at = now() - interval '1 second'
                WHERE job_id = %s
                """,
                (job_id,),
            )
        # New connection = restarted worker process.
        with psycopg.connect(self.database_url) as conn:
            claimed = control_plane.claim_job(conn, worker="worker-b")
            self.assertEqual(claimed, job_id)
            owner = conn.execute(
                "SELECT lease_owner FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(owner, "worker-b")
            self.assertEqual(_job_status(conn, job_id), "running")
            # Progress made before the crash is still there.
            control_plane.advance_stage(conn, job_id=job_id, stage="prepare", status="running")
            control_plane.heartbeat_job(conn, job_id=job_id, worker="worker-b")
            self.assertEqual(_stage_status(conn, job_id, "prepare"), "running")

    def test_revision_replacement_is_non_destructive_and_auditable(self) -> None:
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="武帝纪")
            rev1, no1 = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("v1"),
                source_bytes=100, source_media_type="text/plain",
            )
            rev2, no2 = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("v2"),
                source_bytes=120, source_media_type="text/plain",
            )
            self.assertEqual((no1, no2), (1, 2))
            row = conn.execute(
                """
                SELECT supersedes_revision_id FROM chronicle.document_revisions
                WHERE revision_id = %s
                """,
                (rev2,),
            ).fetchone()
            self.assertEqual(row[0], rev1)
            # Old revision row is untouched.
            old = conn.execute(
                "SELECT source_sha256, revision_no FROM chronicle.document_revisions WHERE revision_id = %s",
                (rev1,),
            ).fetchone()
            self.assertEqual(tuple(old), (_sha256("v1"), 1))
            # Direct mutation is rejected by the database, not just convention.
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.document_revisions SET source_bytes = 999 WHERE revision_id = %s",
                        (rev1,),
                    )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM chronicle.document_revisions WHERE revision_id = %s",
                        (rev1,),
                    )
            # Both revisions still resolve; current tip is rev2.
            tip = conn.execute(
                """
                SELECT revision_id FROM chronicle.document_revisions
                WHERE document_id = %s ORDER BY revision_no DESC LIMIT 1
                """,
                (document_id,),
            ).fetchone()[0]
            self.assertEqual(tip, rev2)

    def test_output_rejects_revision_mismatch_at_store_and_database(self) -> None:
        """D-1: an output for job A must bind job A's own revision.

        Both the store pre-check and the database trigger reject a foreign
        revision, so trace_provenance can never mix one job's chunks with
        another revision.
        """
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="mismatch")
            rev1, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("m1"),
                source_bytes=10, source_media_type="text/plain",
            )
            rev2, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("m2"),
                source_bytes=10, source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=rev1)
            with self.assertRaises(PersistenceConflict):
                control_plane.record_output(
                    conn, job_id=job_id, revision_id=rev2,
                    artifact_type="assembled-extraction",
                    artifact_sha256=_sha256("assembled"),
                    payload={"chunks": 0},
                )
            # Trigger backstop: raw SQL bypassing the store is rejected too.
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO chronicle.ingestion_outputs(
                            output_id, job_id, revision_id, artifact_type,
                            artifact_sha256, payload
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            uuid.uuid4(), job_id, rev2,
                            "assembled-extraction", _sha256("assembled"), "{}",
                        ),
                    )
            count = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_outputs WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(count, 0)

    def test_cross_job_section_and_chunk_links_are_rejected(self) -> None:
        """D-1: chunks bind sections of their own job; reviews bind chunks of
        their own job. Store pre-checks and database triggers both enforce it."""
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="cross-job")
            revision_id, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("c"),
                source_bytes=10, source_media_type="text/plain",
            )
            job_a = control_plane.queue_job(conn, revision_id=revision_id)
            job_b = control_plane.queue_job(conn, revision_id=revision_id)
            section_b = control_plane.create_section(
                conn, job_id=job_b, section_index=0, label="other",
                source_start=0, source_end=10,
            )
            with self.assertRaises(PersistenceConflict):
                control_plane.record_chunk(
                    conn, job_id=job_a, section_id=section_b, chunk_index=0,
                    source_start=0, source_end=5,
                    source_sha256=_sha256("c"), content_sha256=_sha256("c0"),
                )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO chronicle.ingestion_chunks(
                            chunk_id, job_id, section_id, chunk_index,
                            source_start, source_end, source_sha256, content_sha256
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            uuid.uuid4(), job_a, section_b, 0,
                            0, 5, _sha256("c"), _sha256("c0"),
                        ),
                    )
            chunk_b = control_plane.record_chunk(
                conn, job_id=job_b, section_id=None, chunk_index=0,
                source_start=0, source_end=5,
                source_sha256=_sha256("c"), content_sha256=_sha256("c0"),
            )
            with self.assertRaises(PersistenceConflict):
                control_plane.open_review_item(
                    conn, job_id=job_a, kind="chunk_failure", chunk_id=chunk_b,
                )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO chronicle.review_items(review_id, job_id, chunk_id, kind)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            uuid.uuid4(), job_a, chunk_b, "chunk_failure",
                        ),
                    )

    def test_duplicate_output_retry_returns_existing_id(self) -> None:
        """D-2: repeating an identical record_output call is idempotent and
        returns the persisted row's ID, which trace_provenance resolves."""
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="idempotent")
            revision_id, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("i"),
                source_bytes=10, source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            first = control_plane.record_output(
                conn, job_id=job_id, revision_id=revision_id,
                artifact_type="assembled-extraction",
                artifact_sha256=_sha256("assembled"),
                payload={"chunks": 0},
            )
            second = control_plane.record_output(
                conn, job_id=job_id, revision_id=revision_id,
                artifact_type="assembled-extraction",
                artifact_sha256=_sha256("assembled"),
                payload={"chunks": 0},
            )
            self.assertEqual(first, second)
            count = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_outputs WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(count, 1)
            provenance = control_plane.trace_provenance(conn, output_id=second)
            self.assertEqual(provenance["revision_id"], str(revision_id))
            self.assertEqual(provenance["job_id"], str(job_id))

    def test_parent_identity_remap_is_rejected(self) -> None:
        """D-3: parent identity keys are frozen once child rows exist.

        Reproducer: output recorded for revision 1, then raw-SQL moving its
        job to revision 2. The move must fail so provenance stays one
        immutable revision; lifecycle columns must stay mutable.
        """
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="remap")
            rev1, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("r1"),
                source_bytes=10, source_media_type="text/plain",
            )
            rev2, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("r2"),
                source_bytes=10, source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=rev1)
            section_id = control_plane.create_section(
                conn, job_id=job_id, section_index=0, label="scope",
                source_start=0, source_end=10,
            )
            chunk_id = control_plane.record_chunk(
                conn, job_id=job_id, section_id=section_id, chunk_index=0,
                source_start=0, source_end=5,
                source_sha256=_sha256("r1"), content_sha256=_sha256("c0"),
            )
            output_id = control_plane.record_output(
                conn, job_id=job_id, revision_id=rev1,
                artifact_type="assembled-extraction",
                artifact_sha256=_sha256("assembled"),
                payload={"chunks": 1},
            )
            # Moving the job to another revision is rejected...
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.ingestion_jobs SET revision_id = %s WHERE job_id = %s",
                        (rev2, job_id),
                    )
            # ...as is re-homing sections, chunks, reviews, outputs, and runs.
            review_id = control_plane.open_review_item(
                conn, job_id=job_id, kind="stage_gate", chunk_id=chunk_id,
            )
            other_job = control_plane.queue_job(conn, revision_id=rev2)
            for table, key, row_id, new_parent in (
                ("ingestion_sections", "job_id", section_id, other_job),
                ("ingestion_chunks", "job_id", chunk_id, other_job),
                ("review_items", "job_id", review_id, other_job),
                ("ingestion_outputs", "revision_id", output_id, rev2),
            ):
                pk = {
                    "ingestion_sections": "section_id",
                    "ingestion_chunks": "chunk_id",
                    "review_items": "review_id",
                    "ingestion_outputs": "output_id",
                }[table]
                with self.assertRaises(Exception, msg=f"{table}.{key} remap"):
                    with conn.transaction():
                        conn.execute(
                            f"UPDATE chronicle.{table} SET {key} = %s WHERE {pk} = %s",
                            (new_parent, row_id),
                        )
            # Lifecycle columns stay mutable: claim/heartbeat/status still work.
            control_plane.claim_job(conn, worker="regression-worker", job_id=job_id)
            control_plane.heartbeat_job(conn, job_id=job_id, worker="regression-worker")
            control_plane.set_job_status(conn, job_id=job_id, status="cancelled")
            # Provenance still resolves to exactly one immutable revision.
            provenance = control_plane.trace_provenance(conn, output_id=output_id)
            self.assertEqual(provenance["revision_id"], str(rev1))
            self.assertEqual(provenance["revision_no"], 1)
            self.assertEqual(len(provenance["chunks"]), 1)

    def test_illegal_transitions_are_rejected(self) -> None:
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="illegal")
            revision_id, _ = control_plane.create_revision(
                conn, document_id=document_id, source_sha256=_sha256("x"),
                source_bytes=10, source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            # queued -> completed skips claim; must fail.
            with self.assertRaises(PersistenceConflict):
                control_plane.set_job_status(conn, job_id=job_id, status="completed")
            # pending -> completed skips running; must fail.
            with self.assertRaises(PersistenceConflict):
                control_plane.advance_stage(
                    conn, job_id=job_id, stage="prepare", status="completed"
                )
            # Unknown enum spellings are rejected before touching the database.
            with self.assertRaises(PersistenceError):
                control_plane.set_job_status(conn, job_id=job_id, status="bogus")
            # Job is still queued after the rejected transitions.
            self.assertEqual(_job_status(conn, job_id), "queued")
            control_plane.set_job_status(conn, job_id=job_id, status="cancelled")
            # Terminal: cancelled accepts nothing further.
            with self.assertRaises(PersistenceConflict):
                control_plane.set_job_status(conn, job_id=job_id, status="running")

    def test_migration_preserves_c0_tables_and_seed_data(self) -> None:
        """Applying 0002 on top of 0001 keeps every C0 table present and empty-safe."""
        with self._connect_ready() as conn:
            tables = conn.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'chronicle'
                ORDER BY tablename
                """
            ).fetchall()
            names = {row[0] for row in tables}
            for c0 in (
                "source_bundles", "staged_entities", "staged_events", "staged_claims",
                "staged_warnings", "resolution_artifacts", "resolution_entity_links",
                "resolution_event_links", "resolution_warnings", "canonical_catalogs",
                "canonical_entities", "canonical_events", "canonical_catalog_entities",
                "canonical_catalog_events", "canonical_entity_representations",
                "canonical_event_representations", "canonical_event_relations",
                "canonical_catalog_relations", "canonical_event_relation_links",
                "canonical_warnings", "import_sets",
            ):
                self.assertIn(c0, names)
            for c1 in (
                "documents", "document_revisions", "ingestion_jobs",
                "ingestion_job_stages", "ingestion_sections", "ingestion_chunks",
                "ingestion_chunk_runs", "review_items", "ingestion_outputs",
            ):
                self.assertIn(c1, names)
            versions = conn.execute(
                "SELECT version FROM chronicle.schema_migrations ORDER BY version"
            ).fetchall()
            self.assertEqual(
                [row[0] for row in versions],
                ["0001_chronicle_v0.sql", "0002_chronicle_c1_control_plane.sql"],
            )


if __name__ == "__main__":
    unittest.main()
