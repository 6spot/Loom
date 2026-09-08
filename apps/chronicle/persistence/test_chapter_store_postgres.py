"""PostgreSQL 18 integration tests for the Chronicle C2-R1-T04 chapter store.

Covers chapter-production.md sections 5/7: fresh migration + reapply,
complete-product write/read round-trip, and negative cases for partial
products, wrong revision/producing-run/lease, hash conflicts,
non-idempotent duplicate publications, resolution envelope guards
(v0.1/cross_source same-bundle rejected, v0.2 within_revision allowed,
self-ref links rejected), the publication visibility gate, and the
untouched Reader Presentation Claim constraint.

The T01 chapter contract (chapter_contract.py) is the sole accepted
input: every write path re-validates the exact request/candidate pair
fail-closed before opening a transaction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
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

import canonical_store
import chapter_contract
import chapter_store
import control_plane
from common import LeaseLost, PersistenceConflict, PersistenceError
from migrations import apply_migrations

FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r1-contract"

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


def _uuid7(n: int) -> str:
    # Deterministic RFC 9562 variant/version values for test fixtures.
    return f"019535d9-3df7-7{n:03x}-8000-00000000000{n:x}"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ChapterStorePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t04_test_{uuid.uuid4().hex}"
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

    # -- fixtures ------------------------------------------------------

    def _request_for_revision(self, revision_id: uuid.UUID) -> tuple[dict, dict]:
        request = _load("request.json")
        candidate = _load("candidate-valid.json")
        request["revision_id"] = str(revision_id)
        self.assertEqual(candidate["chapter_id"], request["chapter_id"])
        report = chapter_contract.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        return request, candidate

    def _setup_job(self, conn, *, worker: str = "worker-t04") -> dict:
        """Create doc/revision/job/chunk/run; return ids + valid request/candidate."""
        request_template = _load("request.json")
        document_id = control_plane.create_document(conn, title="章存储用书")
        revision_id, _ = control_plane.create_revision(
            conn,
            document_id=document_id,
            source_sha256=request_template["source_sha256"],
            source_bytes=len(request_template["normalized_text"].encode("utf-8")),
            source_media_type="text/markdown",
        )
        request, candidate = self._request_for_revision(revision_id)
        job_id = control_plane.queue_job(conn, revision_id=revision_id)
        control_plane.claim_job(conn, worker=worker, job_id=job_id)
        section_id = control_plane.create_section(
            conn, job_id=job_id, section_index=0, label="章",
            source_start=0, source_end=len(request["normalized_text"]),
        )
        chunk_id = control_plane.record_chunk(
            conn, job_id=job_id, section_id=section_id, chunk_index=0,
            source_start=0, source_end=len(request["normalized_text"]),
            source_sha256=request["source_sha256"],
            content_sha256=_sha256("chapter-chunk-0"),
        )
        control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
        run_id, _ = control_plane.record_chunk_run(
            conn, chunk_id=chunk_id, status="running", worker=worker,
        )
        return {
            "document_id": document_id,
            "revision_id": revision_id,
            "job_id": job_id,
            "chunk_id": chunk_id,
            "run_id": run_id,
            "worker": worker,
            "request": request,
            "candidate": candidate,
        }

    def _publication(self, ctx: dict, *, catalog_tag: str = "catalog-1",
                     bundle_tag: str = "bundle-1") -> tuple[str, str, dict]:
        catalog_sha256 = _sha256(catalog_tag)
        assembled_sha256 = _sha256(bundle_tag)
        publication = {
            "chapter_id": ctx["request"]["chapter_id"],
            "revision_id": str(ctx["revision_id"]),
            "translation_blocks": ctx["candidate"]["translation"]["blocks"],
            "source_overview": {"source_title": "t", "chapter_title": "c",
                                "revision_id": str(ctx["revision_id"])},
            "references": {"entities": [], "events": []},
        }
        return catalog_sha256, assembled_sha256, publication

    # -- migration -----------------------------------------------------

    def test_fresh_migrate_reapply_and_tables(self) -> None:
        with self._connect_ready() as conn:
            apply_migrations(conn)  # reapply is a no-op
            names = {row[0] for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'chronicle'")}
            self.assertIn("chapter_artifacts", names)
            self.assertIn("chapter_publications", names)
            scope_col = conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = 'chronicle'"
                " AND table_name = 'resolution_artifacts' AND column_name = 'scope'").fetchone()
            self.assertIsNotNone(scope_col)
            seq_col = conn.execute(
                "SELECT is_nullable, is_identity FROM information_schema.columns"
                " WHERE table_schema = 'chronicle' AND table_name = 'canonical_catalogs'"
                " AND column_name = 'publication_sequence'").fetchone()
            self.assertIsNotNone(seq_col)
            bundle_guard = conn.execute(
                "SELECT 1 FROM pg_constraint"
                " WHERE conname = 'resolution_artifacts_bundle_scope_valid'").fetchone()
            self.assertIsNotNone(bundle_guard)
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM pg_constraint"
                " WHERE conname = 'resolution_entity_links_no_self_ref'").fetchone())
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM pg_constraint"
                " WHERE conname = 'resolution_event_links_no_self_ref'").fetchone())
            versions = [row[0] for row in conn.execute(
                "SELECT version FROM chronicle.schema_migrations ORDER BY version")]
            self.assertIn("0006_chronicle_chapters.sql", versions)

    # -- write/read round-trip -----------------------------------------

    def test_full_artifact_write_read_roundtrip(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            sha = chapter_store.record_accepted_chapter_fenced(
                conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=ctx["worker"], request=ctx["request"],
                candidate=ctx["candidate"],
                producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                               "prompt_schema_version": "v"},
            )
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            # Chunk accepted pointer + completed status committed together.
            chunk = conn.execute(
                "SELECT status, checkpoint FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
                (ctx["chunk_id"],)).fetchone()
            self.assertEqual(chunk[0], "completed")
            self.assertEqual(chunk[1].get("accepted_chapter_artifact"), sha)
            # Read back the complete joint product.
            entries = chapter_store.read_accepted_chapters(conn, job_id=ctx["job_id"])
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry["artifact_sha256"], sha)
            self.assertEqual(entry["artifact"]["chapter_id"], ctx["request"]["chapter_id"])
            self.assertTrue(entry["artifact"]["anchors"])
            text = ctx["request"]["normalized_text"]
            for anchor in entry["artifact"]["anchors"]:
                self.assertEqual(text[anchor["start"]:anchor["end"]], anchor["quote"])
            single = chapter_store.read_accepted_chapter(
                conn, job_id=ctx["job_id"], chapter_id=ctx["request"]["chapter_id"])
            self.assertIsNotNone(single)
            self.assertEqual(single["artifact_sha256"], sha)

    def test_partial_candidate_rejected_and_nothing_written(self) -> None:
        """A translation-only half product fails closed with no partial rows."""
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            partial = _load("candidate-translation-only-shape.json")
            partial["chapter_id"] = ctx["request"]["chapter_id"]
            with self.assertRaises(PersistenceError):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker=ctx["worker"], request=ctx["request"], candidate=partial,
                    producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                                   "prompt_schema_version": "v"},
                )
            count = conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts WHERE job_id = %s",
                (ctx["job_id"],)).fetchone()[0]
            self.assertEqual(count, 0)
            status = conn.execute(
                "SELECT status FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
                (ctx["chunk_id"],)).fetchone()[0]
            self.assertEqual(status, "running")

    def test_wrong_revision_rejected(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            other_revision = uuid.uuid4()
            bad_request = copy.deepcopy(ctx["request"])
            bad_request["revision_id"] = str(other_revision)
            with self.assertRaises(PersistenceConflict):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker=ctx["worker"], request=bad_request, candidate=ctx["candidate"],
                    producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                                   "prompt_schema_version": "v"},
                )
            count = conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0]
            self.assertEqual(count, 0)

    def test_unknown_producing_run_rejected(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            with self.assertRaises(PersistenceConflict):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                    producing_run={"run_id": str(uuid.uuid4()), "model": "m",
                                   "prompt_schema_version": "v"},
                )
            count = conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0]
            self.assertEqual(count, 0)

    def test_failed_producing_run_rejected_and_rows_unchanged(self) -> None:
        """A failed run can never produce an accepted chapter: the write is
        refused before any row changes, leaving the artifact table empty
        and the chunk still running for a genuine retry."""
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            failed_run, _ = control_plane.record_chunk_run(
                conn, chunk_id=ctx["chunk_id"], status="failed",
                worker=ctx["worker"], error="simulated model fault",
            )
            with self.assertRaisesRegex(PersistenceConflict, "failed run"):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                    producing_run={"run_id": str(failed_run), "model": "m",
                                   "prompt_schema_version": "v"},
                )
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0], 0)
            status = conn.execute(
                "SELECT status FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
                (ctx["chunk_id"],)).fetchone()[0]
            self.assertEqual(status, "running")

    def test_concurrent_identical_accept_and_publish_is_idempotent(self) -> None:
        """Barrier-aligned concurrent replays of the same artifact and
        publication all succeed with the same ids and leave single rows:
        the savepoint-scoped race inserts keep the fenced transactions
        usable instead of dying with InFailedSqlTransaction."""
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            catalog_sha, assembled_sha, publication = self._publication(ctx)
            producing_run = {"run_id": str(ctx["run_id"]), "model": "m",
                             "prompt_schema_version": "v"}
            job_id, chunk_id, worker = ctx["job_id"], ctx["chunk_id"], ctx["worker"]
            request, candidate = ctx["request"], ctx["candidate"]
        barrier = threading.Barrier(4)
        outcomes: list = [None] * 4

        def _replay(index: int) -> None:
            try:
                with psycopg.connect(self.database_url) as conn:
                    barrier.wait(timeout=60)
                    sha = chapter_store.record_accepted_chapter_fenced(
                        conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
                        request=request, candidate=candidate,
                        producing_run=producing_run,
                    )
                    pub_id = chapter_store.persist_chapter_publication(
                        conn, job_id=job_id, worker=worker, artifact_sha256=sha,
                        catalog_sha256=catalog_sha, assembled_bundle_sha256=assembled_sha,
                        publication=publication,
                    )
                    outcomes[index] = (sha, str(pub_id), None)
            except Exception as exc:  # captured, asserted below
                outcomes[index] = (None, None, exc)

        threads = [threading.Thread(target=_replay, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
            self.assertFalse(thread.is_alive(), "replay thread hung")
        for sha, pub_id, error in outcomes:
            self.assertIsNone(error, f"concurrent replay failed: {error!r}")
        self.assertEqual(len({sha for sha, _, _ in outcomes}), 1)
        self.assertEqual(len({pub_id for _, pub_id, _ in outcomes}), 1)
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM chronicle.chapter_publications").fetchone()[0], 1)

    def test_concurrent_chapter_conflict_surfaced_as_persistence_conflict(self) -> None:
        """Two chapters racing on one chunk (one chunk per chapter: the
        second insert violates the unique binding) must surface a
        PersistenceConflict, never a leaked InFailedSqlTransaction from a
        UniqueViolation recovery SELECT on an aborted transaction."""
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            producing_run = {"run_id": str(ctx["run_id"]), "model": "m",
                             "prompt_schema_version": "v"}
            other_request = copy.deepcopy(ctx["request"])
            other_request["chapter_id"] = "ch_756922e9af0d759d29d74760"
            other_candidate = copy.deepcopy(ctx["candidate"])
            other_candidate["chapter_id"] = other_request["chapter_id"]
            report = chapter_contract.validate_chapter_candidate(
                other_request, other_candidate)
            self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
            job_id, chunk_id, worker = ctx["job_id"], ctx["chunk_id"], ctx["worker"]
            pairs = [(ctx["request"], ctx["candidate"]),
                     (other_request, other_candidate)]
        barrier = threading.Barrier(2)
        outcomes: list = [None] * 2

        def _accept(index: int) -> None:
            try:
                with psycopg.connect(self.database_url) as conn:
                    barrier.wait(timeout=60)
                    request, candidate = pairs[index]
                    sha = chapter_store.record_accepted_chapter_fenced(
                        conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
                        request=request, candidate=candidate,
                        producing_run=producing_run,
                    )
                    outcomes[index] = ("ok", sha)
            except Exception as exc:  # captured, asserted below
                outcomes[index] = ("error", exc)

        threads = [threading.Thread(target=_accept, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
            self.assertFalse(thread.is_alive(), "accept thread hung")
        kinds = sorted(kind for kind, _ in outcomes)
        self.assertEqual(kinds, ["error", "ok"])
        error = next(value for kind, value in outcomes if kind == "error")
        self.assertIsInstance(error, PersistenceConflict)
        self.assertNotIsInstance(error, LeaseLost)
        self.assertNotIn("InFailedSqlTransaction", type(error).__name__)
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0], 1)

    def test_lease_lost_and_cancelled_cannot_write(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn, worker="worker-a")
            # Expire worker-a's lease and let worker-b take over.
            conn.execute(
                "UPDATE chronicle.ingestion_jobs SET lease_expires_at = now() - interval '1 second'"
                " WHERE job_id = %s", (ctx["job_id"],))
        with psycopg.connect(self.database_url) as conn:
            claimed = control_plane.claim_job(conn, worker="worker-b", job_id=ctx["job_id"])
            self.assertEqual(claimed, ctx["job_id"])
            producing_run = {"run_id": str(ctx["run_id"]), "model": "m",
                             "prompt_schema_version": "v"}
            with self.assertRaises(LeaseLost):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker="worker-a", request=ctx["request"], candidate=ctx["candidate"],
                    producing_run=producing_run,
                )
            # Cancellation clears the lease: nobody may write afterwards.
            control_plane.cancel_job(conn, job_id=ctx["job_id"])
            with self.assertRaises(LeaseLost):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker="worker-b", request=ctx["request"], candidate=ctx["candidate"],
                    producing_run=producing_run,
                )
            count = conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0]
            self.assertEqual(count, 0)

    def test_hash_conflict_same_chapter_different_content(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            sha = chapter_store.record_accepted_chapter_fenced(
                conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                               "prompt_schema_version": "v"},
            )
            other = copy.deepcopy(ctx["candidate"])
            other["translation"]["blocks"][0]["text"] += "（补）"
            report = chapter_contract.validate_chapter_candidate(ctx["request"], other)
            self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
            run2, _ = control_plane.record_chunk_run(
                conn, chunk_id=ctx["chunk_id"], status="running", worker=ctx["worker"])
            with self.assertRaises(PersistenceConflict):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker=ctx["worker"], request=ctx["request"], candidate=other,
                    producing_run={"run_id": str(run2), "model": "m",
                                   "prompt_schema_version": "v"},
                )
            rows = conn.execute(
                "SELECT artifact_sha256 FROM chronicle.chapter_artifacts WHERE job_id = %s",
                (ctx["job_id"],)).fetchall()
            self.assertEqual([row[0] for row in rows], [sha])

    def test_idempotent_replay_same_artifact(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            producing_run = {"run_id": str(ctx["run_id"]), "model": "m",
                             "prompt_schema_version": "v"}
            first = chapter_store.record_accepted_chapter_fenced(
                conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                producing_run=producing_run,
            )
            second = chapter_store.record_accepted_chapter_fenced(
                conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                producing_run=producing_run,
            )
            self.assertEqual(first, second)
            count = conn.execute(
                "SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0]
            self.assertEqual(count, 1)

    def test_completed_run_adopted_after_revalidation(self) -> None:
        """A run committed before acceptance is adopted via full re-validation."""
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            fingerprint = chapter_contract.request_fingerprint(ctx["request"])
            conn.execute(
                "UPDATE chronicle.ingestion_chunk_runs SET status = 'completed',"
                " checkpoint = %s, finished_at = now() WHERE run_id = %s",
                (json.dumps({"request_fingerprint": fingerprint}), ctx["run_id"]),
            )
            sha = chapter_store.record_accepted_chapter_fenced(
                conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                               "prompt_schema_version": "v"},
            )
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            # A run bound to another fingerprint cannot be adopted.
            conn.execute(
                "UPDATE chronicle.ingestion_chunk_runs SET checkpoint = %s WHERE run_id = %s",
                (json.dumps({"request_fingerprint": _sha256("drift")}), ctx["run_id"]),
            )
            other_request = copy.deepcopy(ctx["request"])
            with self.assertRaises(PersistenceConflict):
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                    worker=ctx["worker"], request=other_request, candidate=ctx["candidate"],
                    producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                                   "prompt_schema_version": "v"},
                )

    def test_interrupt_resume_reads_accepted_without_new_queue(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            sha = chapter_store.record_accepted_chapter_fenced(
                conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                               "prompt_schema_version": "v"},
            )
            runs_before = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_chunk_runs").fetchone()[0]
        # Interrupted worker restarts on a fresh connection and resumes by reading.
        with psycopg.connect(self.database_url) as conn:
            entries = chapter_store.read_accepted_chapters(conn, job_id=ctx["job_id"])
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["artifact_sha256"], sha)
            self.assertEqual(entries[0]["artifact"]["candidate"],
                             ctx["candidate"])
            runs_after = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_chunk_runs").fetchone()[0]
            self.assertEqual(runs_before, runs_after)
            stray = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'chronicle'"
                " AND (tablename LIKE 'chapter_queue%' OR tablename LIKE 'chapter_run%')").fetchall()
            self.assertEqual(stray, [])

    # -- publications --------------------------------------------------

    def test_publication_idempotent_conflict_and_visibility_gate(self) -> None:
        with self._connect_ready() as conn:
            ctx = self._setup_job(conn)
            # No public directory entry before the publication helper runs.
            self.assertEqual(
                chapter_store.list_published_chapters(conn, job_id=ctx["job_id"]), [])
            sha = chapter_store.record_accepted_chapter_fenced(
                conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=ctx["worker"], request=ctx["request"], candidate=ctx["candidate"],
                producing_run={"run_id": str(ctx["run_id"]), "model": "m",
                               "prompt_schema_version": "v"},
            )
            self.assertEqual(
                chapter_store.list_published_chapters(conn, job_id=ctx["job_id"]), [])
            catalog_sha, assembled_sha, publication = self._publication(ctx)
            first = chapter_store.persist_chapter_publication(
                conn, job_id=ctx["job_id"], worker=ctx["worker"],
                artifact_sha256=sha, catalog_sha256=catalog_sha,
                assembled_bundle_sha256=assembled_sha, publication=publication,
            )
            from common import parse_uuid7
            parse_uuid7(str(first), "publication_id")
            # Identical replay is idempotent.
            second = chapter_store.persist_chapter_publication(
                conn, job_id=ctx["job_id"], worker=ctx["worker"],
                artifact_sha256=sha, catalog_sha256=catalog_sha,
                assembled_bundle_sha256=assembled_sha, publication=publication,
            )
            self.assertEqual(first, second)
            # Same triple with different bytes is a conflict, not a new row.
            other = copy.deepcopy(publication)
            other["references"] = {"entities": ["ent_001"], "events": []}
            with self.assertRaises(PersistenceConflict):
                chapter_store.persist_chapter_publication(
                    conn, job_id=ctx["job_id"], worker=ctx["worker"],
                    artifact_sha256=sha, catalog_sha256=catalog_sha,
                    assembled_bundle_sha256=assembled_sha, publication=other,
                )
            # Now the public directory shows exactly this publication.
            directory = chapter_store.list_published_chapters(conn, job_id=ctx["job_id"])
            self.assertEqual(len(directory), 1)
            self.assertEqual(directory[0]["publication_id"], str(first))
            self.assertEqual(directory[0]["artifact_sha256"], sha)
            detail = chapter_store.read_published_chapter(conn, publication_id=first)
            self.assertEqual(detail["artifact"]["chapter_id"], ctx["request"]["chapter_id"])
            self.assertEqual(detail["publication"], publication)
            with self.assertRaises(PersistenceError):
                chapter_store.read_published_chapter(conn, publication_id=uuid.uuid4())

    # -- resolution envelope -------------------------------------------

    def _seed_bundle(self, conn, label: str, refs: list[str]) -> None:
        conn.execute(
            "INSERT INTO chronicle.source_bundles(bundle_label, schema_version, source_ref,"
            " source_title, artifact_sha256, source_payload, bundle_payload)"
            " VALUES (%s, '0.1', 'src_001', 'T', %s, '{}', '{}')",
            (label, _sha256(label)),
        )
        for ref in refs:
            conn.execute(
                "INSERT INTO chronicle.staged_entities(bundle_label, record_ref,"
                " payload_sha256, payload) VALUES (%s, %s, %s, %s)",
                (label, ref, _sha256(label + ref), json.dumps({"temp_id": ref})),
            )

    def test_resolution_same_bundle_envelope_and_self_ref(self) -> None:
        with self._connect_ready() as conn:
            with conn.transaction():
                self._seed_bundle(conn, "bund-a", ["ent_001", "ent_002"])
                self._seed_bundle(conn, "bund-b", ["ent_001"])
                # v0.1 same-bundle artifacts stay rejected.
                with self.assertRaises(Exception):
                    with conn.transaction():
                        conn.execute(
                            "INSERT INTO chronicle.resolution_artifacts(artifact_sha256, schema_name,"
                            " schema_version, left_bundle_label, right_bundle_label, payload)"
                            " VALUES (%s, 'chronicle.resolution-links', '0.1', 'bund-a', 'bund-a', '{}')",
                            (_sha256("res-v01-same"),),
                        )
                # v0.2 cross_source same-bundle stays rejected.
                with self.assertRaises(Exception):
                    with conn.transaction():
                        conn.execute(
                            "INSERT INTO chronicle.resolution_artifacts(artifact_sha256, schema_name,"
                            " schema_version, scope, left_bundle_label, right_bundle_label, payload)"
                            " VALUES (%s, 'chronicle.resolution-links', '0.2',"
                            " 'cross_source', 'bund-a', 'bund-a', '{}')",
                            (_sha256("res-v02-cross-same"),),
                        )
                # v0.2 within_revision same-bundle is the controlled write path.
                conn.execute(
                    "INSERT INTO chronicle.resolution_artifacts(artifact_sha256, schema_name,"
                    " schema_version, scope, left_bundle_label, right_bundle_label, payload)"
                    " VALUES (%s, 'chronicle.resolution-links', '0.2',"
                    " 'within_revision', 'bund-a', 'bund-a', '{}')",
                    (_sha256("res-v02-within-same"),),
                )
                # Distinct-bundle v0.1 rows keep working.
                conn.execute(
                    "INSERT INTO chronicle.resolution_artifacts(artifact_sha256, schema_name,"
                    " schema_version, left_bundle_label, right_bundle_label, payload)"
                    " VALUES (%s, 'chronicle.resolution-links', '0.1', 'bund-a', 'bund-b', '{}')",
                    (_sha256("res-v01-distinct"),),
                )
                # Self-ref Entity/Event links are rejected; enums/FKs still hold.
                with self.assertRaises(Exception):
                    with conn.transaction():
                        conn.execute(
                            "INSERT INTO chronicle.resolution_entity_links(resolution_sha256,"
                            " candidate_id, left_bundle_label, left_record_ref,"
                            " right_bundle_label, right_record_ref, decision, confidence,"
                            " rationale, signals, payload)"
                            " VALUES (%s, 'ec_001', 'bund-a', 'ent_001', 'bund-a', 'ent_001',"
                            " 'uncertain', 0.5, 'r', '[]', '{}')",
                            (_sha256("res-v02-within-same"),),
                        )
                conn.execute(
                    "INSERT INTO chronicle.resolution_entity_links(resolution_sha256,"
                    " candidate_id, left_bundle_label, left_record_ref,"
                    " right_bundle_label, right_record_ref, decision, confidence,"
                    " rationale, signals, payload)"
                    " VALUES (%s, 'ec_001', 'bund-a', 'ent_001', 'bund-a', 'ent_002',"
                    " 'uncertain', 0.5, 'r', '[]', '{}')",
                    (_sha256("res-v02-within-same"),),
                )
                with self.assertRaises(Exception):
                    with conn.transaction():
                        conn.execute(
                            "INSERT INTO chronicle.resolution_entity_links(resolution_sha256,"
                            " candidate_id, left_bundle_label, left_record_ref,"
                            " right_bundle_label, right_record_ref, decision, confidence,"
                            " rationale, signals, payload)"
                            " VALUES (%s, 'ec_002', 'bund-a', 'ent_001', 'bund-a', 'ent_002',"
                            " 'bogus_decision', 0.5, 'r', '[]', '{}')",
                            (_sha256("res-v02-within-same"),),
                        )

    def test_reader_presentation_claim_constraint_unweakened(self) -> None:
        """0006 must not relax the 0005 Claim-only support constraint."""
        with self._connect_ready() as conn:
            trigger = conn.execute(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'validate_reader_presentation_support'"
            ).fetchone()
            self.assertIsNotNone(trigger)
            target = conn.execute(
                "SELECT confrelid::regclass::text FROM pg_constraint"
                " WHERE conname = 'reader_presentation_supports_bundle_label_claim_ref_fkey'"
            ).fetchone()
            if target is None:
                rows = conn.execute(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
                    " WHERE conrelid = 'chronicle.reader_presentation_supports'::regclass"
                    " AND contype = 'f'").fetchall()
                self.assertTrue(
                    any("staged_claims" in definition for _, definition in rows),
                    f"support FK must still target staged_claims, got {rows}",
                )
            else:
                self.assertIn("staged_claims", target[0])
            # Dangling support rows are still rejected, not silently accepted.
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO chronicle.reader_presentation_supports("
                        "presentation_id, block_index, bundle_label, claim_ref)"
                        " VALUES (%s, 0, 'nope', 'clm_999')",
                        (uuid.uuid4(),),
                    )

    def test_publication_sequence_unique_increasing_structure(self) -> None:
        """0006 adds the sequence; T13 owns the locked write path and reads."""
        with self._connect_ready() as conn:
            first_catalog = {
                "schema": "chronicle.canonical-catalog", "version": "0.1",
                "canonical_entities": [
                    {"canonical_id": _uuid7(4),
                     "representations": [{"bundle": "left", "ref": "ent_001"}]}],
                "canonical_events": [], "event_relations": [], "warnings": [],
            }
            # Seed the referenced staged rows through the v0 bundle path.
            from staged_store import persist_bundle
            bundle = {
                "schema_version": "0.1",
                "source": {"temp_id": "src_001", "kind": "source",
                           "source_type": "book", "title": "T",
                           "language": "zh-Hant",
                           "extraction": {"method": "model"}},
                "entities": [{"temp_id": "ent_001", "kind": "entity",
                              "type": "person", "canonical_name": "T",
                              "aliases": [], "mentions": [{"text": "T"}],
                              "resolution": {"status": "unresolved"},
                              "extraction": {"method": "model"}}],
                "events": [], "claims": [],
                "warnings": [],
            }
            with conn.transaction():
                persist_bundle(conn, "left", bundle)
                first_sha, _ = canonical_store.persist_catalog(conn, first_catalog)
                second_catalog = copy.deepcopy(first_catalog)
                second_catalog["warnings"] = [{"type": "t", "message": "second"}]
                second_sha, _ = canonical_store.persist_catalog(conn, second_catalog)
            rows = conn.execute(
                "SELECT artifact_sha256, publication_sequence"
                " FROM chronicle.canonical_catalogs ORDER BY publication_sequence").fetchall()
            by_sha = {row[0]: row[1] for row in rows}
            self.assertIn(first_sha, by_sha)
            self.assertIn(second_sha, by_sha)
            self.assertIsNotNone(by_sha[first_sha])
            self.assertIsNotNone(by_sha[second_sha])
            self.assertLess(by_sha[first_sha], by_sha[second_sha])
            self.assertEqual(len({row[1] for row in rows}), len(rows))


if __name__ == "__main__":
    unittest.main()
