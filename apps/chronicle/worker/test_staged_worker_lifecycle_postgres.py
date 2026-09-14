"""Current staged worker lifecycle safety cases.

The old fake StageExecutor suite was removed with the retired C1 runner. These
cases exercise the same lease, cancellation and job-shape boundaries against
the current T01 database fixture and the real JobRunner entry.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
for path in (str(HERE), str(HERE.parent / "persistence")):
    if path not in sys.path:
        sys.path.insert(0, path)

import control_plane  # noqa: E402
import ingestion_worker as worker  # noqa: E402
import pipeline_test_support as support  # noqa: E402
from common import LeaseLost, PersistenceConflict  # noqa: E402


class StagedWorkerLifecyclePostgresTests(
    support.CurrentPipelineDatabase, unittest.TestCase
):
    def test_claim_is_exclusive_and_takeover_fences_the_old_owner(self) -> None:
        job_id, _revision_id, _source_sha = self._queue_job(support.TEXT_DISTINCT)

        with support.psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                job_id,
                control_plane.claim_job(
                    conn, worker="lifecycle-first", lease_seconds=60, job_id=job_id
                ),
            )

        with support.psycopg.connect(self.database_url) as conn:
            with self.assertRaises(PersistenceConflict):
                control_plane.claim_job(
                    conn, worker="lifecycle-second", lease_seconds=60, job_id=job_id
                )
            conn.execute(
                "UPDATE chronicle.ingestion_jobs "
                "SET lease_expires_at = clock_timestamp() - interval '1 second' "
                "WHERE job_id = %s",
                (job_id,),
            )

        with support.psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                job_id,
                control_plane.claim_job(
                    conn, worker="lifecycle-second", lease_seconds=60, job_id=job_id
                ),
            )
            with self.assertRaises(LeaseLost):
                control_plane.advance_stage_fenced(
                    conn,
                    job_id=job_id,
                    stage="prepare",
                    status="running",
                    worker="lifecycle-first",
                )

        with support.psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT attempt, lease_owner, status FROM chronicle.ingestion_jobs "
                "WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            self.assertEqual((2, "lifecycle-second", "running"), row)

    def test_cancellation_preserves_completed_stage_and_stops_runner(self) -> None:
        job_id, _revision_id, _source_sha = self._queue_job(support.TEXT_DISTINCT)

        with support.psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(
                conn, worker="lifecycle-cancel", lease_seconds=60, job_id=job_id
            )
            control_plane.advance_stage_fenced(
                conn,
                job_id=job_id,
                stage="prepare",
                status="running",
                worker="lifecycle-cancel",
            )
            control_plane.advance_stage_fenced(
                conn,
                job_id=job_id,
                stage="prepare",
                status="completed",
                worker="lifecycle-cancel",
            )
            control_plane.cancel_job(conn, job_id=job_id)

        result = worker.JobRunner(
            self.database_url, worker="lifecycle-cancel"
        ).execute_job(job_id)
        self.assertEqual("cancelled", result)
        with support.psycopg.connect(self.database_url) as conn:
            detail = control_plane.get_job_detail(conn, job_id=job_id)
            self.assertEqual("cancelled", detail["status"])
            self.assertEqual(
                "completed",
                next(stage["status"] for stage in detail["stages"] if stage["stage"] == "prepare"),
            )
            self.assertIsNone(detail["lease_owner"])

    def test_unknown_job_shape_fails_without_synthetic_public_content(self) -> None:
        job_id, _revision_id, _source_sha = self._queue_job(support.TEXT_DISTINCT)
        with support.psycopg.connect(self.database_url) as conn:
            conn.execute(
                "UPDATE chronicle.ingestion_jobs SET checkpoint = %s WHERE job_id = %s",
                (Jsonb({"legacy_runner": "c1"}), job_id),
            )

        result = worker.run_once(
            self.database_url,
            worker="lifecycle-invalid-kind",
            revision_source=lambda _job_id: (support.TEXT_DISTINCT, _source_sha),
            chapter_model=object(),
            job_id=job_id,
        )
        self.assertEqual((job_id, "failed"), result)
        with support.psycopg.connect(self.database_url) as conn:
            job = conn.execute(
                "SELECT status, error FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            self.assertEqual("failed", job[0])
            self.assertIn("unsupported ingestion job type", job[1])
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_outputs WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
