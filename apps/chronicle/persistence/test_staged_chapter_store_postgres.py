"""Real PostgreSQL acceptance fences for complete 0.4 chapter products."""

from __future__ import annotations

import copy
import sys
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import chapter_contract as C
import chapter_store as Store
import control_plane as CP
import staged_chapter_contract as S
from common import LeaseLost, PersistenceConflict, sha256_json
import test_chapter_store_postgres as LegacyStore
from test_staged_chapter_contract_unit import fixture, receipt


class StagedChapterStorePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control_url = LegacyStore._control_url()

    setUp = LegacyStore.ChapterStorePostgresTests.setUp
    tearDown = LegacyStore.ChapterStorePostgresTests.tearDown
    _connect_ready = LegacyStore.ChapterStorePostgresTests._connect_ready

    def _job(self, conn, *, output=True, step=True, checkpoint=True):
        request, candidate = fixture(annotation=True)
        document_id = CP.create_document(conn, title="分阶段章节接受")
        revision_id, _ = CP.create_revision(
            conn, document_id=document_id, source_sha256=request["source_sha256"],
            source_bytes=len(request["normalized_text"].encode()), source_media_type="text/plain",
        )
        request["revision_id"] = str(revision_id)
        request["source_scope"] = S.build_source_scope(request)
        candidate["source_scope"] = copy.deepcopy(request["source_scope"])
        job_id = CP.queue_job(conn, revision_id=revision_id)
        worker = "staged-store-test"
        CP.claim_job(conn, worker=worker, job_id=job_id)
        section_id = CP.create_section(
            conn, job_id=job_id, section_index=0, label="章", source_start=0,
            source_end=len(request["normalized_text"]),
        )
        chunk_id = CP.record_chunk(
            conn, job_id=job_id, section_id=section_id, chunk_index=0,
            source_start=0, source_end=len(request["normalized_text"]),
            source_sha256=request["source_sha256"], content_sha256=request["normalized_sha256"],
        )
        CP.set_chunk_status_fenced(
            conn, job_id=job_id, chunk_id=chunk_id, worker=worker, status="running",
        )
        step_result = {"step": "review", "candidate_sha256": sha256_json(candidate), "status": "completed"}
        acceptance = receipt(request, candidate)
        acceptance["step_output_sha256s"] = [sha256_json(step_result)]
        for enabled, kind, value in (
            (step, "chapter-production-step", step_result),
            (output, "chapter-production-acceptance", acceptance),
        ):
            if enabled:
                CP.record_output_fenced(
                    conn, job_id=job_id, revision_id=revision_id, worker=worker,
                    artifact_type=kind, artifact_sha256=sha256_json(value), payload=value,
                )
        run_id, _ = CP.record_chunk_run_fenced(
            conn, job_id=job_id, chunk_id=chunk_id, status="completed", worker=worker,
            checkpoint={"request_fingerprint": C.request_fingerprint(request), **(
                {"production_receipt": acceptance} if checkpoint else {}
            )},
        )
        return {
            "job_id": job_id, "chunk_id": chunk_id, "worker": worker,
            "request": request, "candidate": candidate, "production_receipt": acceptance,
            "producing_run": {"run_id": str(run_id), "model": "fixture", "prompt_schema_version": "staged-v1"},
        }

    def test_receipt_persisted_run_and_steps_adopt_without_rerun(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn)
            first = Store.record_accepted_chapter_fenced(conn, **ctx)
            self.assertEqual(first, Store.record_accepted_chapter_fenced(conn, **ctx))
            rows = Store.read_accepted_chapters(conn, job_id=ctx["job_id"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["artifact"]["version"], "0.4")
            self.assertEqual(rows[0]["artifact"]["production_receipt"], ctx["production_receipt"])
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.ingestion_chunk_runs").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.chapter_publications").fetchone()[0], 0)

    def test_candidate_without_persisted_acceptance_output_rejected(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn, output=False)
            with self.assertRaisesRegex(PersistenceConflict, "receipt is missing"):
                Store.record_accepted_chapter_fenced(conn, **ctx)
            self.assertEqual(Store.read_accepted_chapters(conn, job_id=ctx["job_id"]), [])

    def test_receipt_must_also_be_bound_to_producing_run(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn, checkpoint=False)
            with self.assertRaisesRegex(PersistenceConflict, "not bound"):
                Store.record_accepted_chapter_fenced(conn, **ctx)

    def test_receipt_step_hashes_must_resolve_to_persisted_same_job_outputs(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn, step=False)
            with self.assertRaisesRegex(PersistenceConflict, "step outputs"):
                Store.record_accepted_chapter_fenced(conn, **ctx)

    def test_source_scope_origin_must_match_the_persisted_chunk(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn)
            conn.execute(
                "UPDATE chronicle.ingestion_chunks SET source_start = source_start + 1, source_end = source_end + 1 WHERE chunk_id = %s",
                (ctx["chunk_id"],),
            )
            with self.assertRaisesRegex(PersistenceConflict, "source scope"):
                Store.record_accepted_chapter_fenced(conn, **ctx)

    def test_changed_receipt_cannot_replace_reviewed_history(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn)
            ctx["production_receipt"] = {**ctx["production_receipt"], "history_sha256": "d" * 64}
            with self.assertRaisesRegex(PersistenceConflict, "not bound"):
                Store.record_accepted_chapter_fenced(conn, **ctx)

    def test_expired_owner_cannot_accept_even_with_complete_receipt(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn)
            conn.execute("UPDATE chronicle.ingestion_jobs SET lease_expires_at = now() - interval '1 second' WHERE job_id = %s", (ctx["job_id"],))
            with self.assertRaises(LeaseLost):
                Store.record_accepted_chapter_fenced(conn, **ctx)
            self.assertEqual(Store.read_accepted_chapters(conn, job_id=ctx["job_id"]), [])

    def test_expiry_during_accept_rolls_back_artifact_and_completed_pointer(self):
        with self._connect_ready() as conn:
            ctx = self._job(conn)
            point_at_artifact = Store._point_chunk_at_artifact

            def expire_after_pointer(connection, **kwargs):
                point_at_artifact(connection, **kwargs)
                connection.execute(
                    "UPDATE chronicle.ingestion_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE job_id = %s",
                    (ctx["job_id"],),
                )

            with mock.patch.object(Store, "_point_chunk_at_artifact", side_effect=expire_after_pointer):
                with self.assertRaises(LeaseLost):
                    Store.record_accepted_chapter_fenced(conn, **ctx)
            self.assertEqual(Store.read_accepted_chapters(conn, job_id=ctx["job_id"]), [])
            self.assertEqual(conn.execute(
                "SELECT status FROM chronicle.ingestion_chunks WHERE chunk_id = %s", (ctx["chunk_id"],),
            ).fetchone()[0], "running")


if __name__ == "__main__":
    unittest.main()
