"""PostgreSQL 18 integration tests for the Chronicle C1-T4 durable worker.

Proves the restart-safe contract against a real database: single-lease
claiming with ``FOR UPDATE SKIP LOCKED``, concurrent independent jobs,
crash/restart reclaim from checkpoints, checkpoint-skipping resume,
append-only chunk attempts, bounded retry, review-gated resume, and
cancellation that preserves completed work. No external queue service is
used anywhere: every test coordinates through PostgreSQL alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import control_plane  # noqa: E402
from common import PersistenceConflict  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import ingestion_worker as worker  # noqa: E402
from ingestion_worker import StageExecutionError, StageExecutor  # noqa: E402


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
        cwd=HERE.parents[2],
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
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _queue_job(conn, title: str = "武帝紀", max_attempts: int = 3):
    document_id = control_plane.create_document(conn, title=title)
    revision_id, _ = control_plane.create_revision(
        conn,
        document_id=document_id,
        source_sha256=_sha256(f"{title}-raw-{uuid.uuid4().hex}"),
        source_bytes=1024,
        source_media_type="text/plain",
    )
    job_id = control_plane.queue_job(conn, revision_id=revision_id, max_attempts=max_attempts)
    return job_id, revision_id


def _job_status(conn, job_id) -> str:
    return conn.execute(
        "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()[0]


def _stage_statuses(conn, job_id) -> dict[str, str]:
    return {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT stage, status FROM chronicle.ingestion_job_stages WHERE job_id = %s",
            (job_id,),
        ).fetchall()
    }


def _chunk_runs(conn, job_id) -> list[tuple]:
    return conn.execute(
        """
        SELECT c.chunk_index, r.attempt, r.status, r.worker
        FROM chronicle.ingestion_chunk_runs r
        JOIN chronicle.ingestion_chunks c ON c.chunk_id = r.chunk_id
        WHERE c.job_id = %s
        ORDER BY c.chunk_index, r.attempt
        """,
        (job_id,),
    ).fetchall()


class WorkerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t4_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def test_happy_path_completes_every_stage_with_fake_topology(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn)
        result = worker.run_once(self.database_url, worker="worker-happy")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], job_id)
        self.assertEqual(result[1], "completed")
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(_job_status(conn, job_id), "completed")
            stages = _stage_statuses(conn, job_id)
            self.assertEqual(len(stages), 8)
            self.assertTrue(
                all(status == "completed" for status in stages.values()),
                stages,
            )
            runs = _chunk_runs(conn, job_id)
            # Two fake chunks, one completed attempt each.
            self.assertEqual(len(runs), 2)
            self.assertTrue(all(run[2] == "completed" for run in runs))
            outputs = conn.execute(
                "SELECT artifact_type FROM chronicle.ingestion_outputs WHERE job_id = %s",
                (job_id,),
            ).fetchall()
            self.assertEqual([row[0] for row in outputs], [worker.FAKE_OUTPUT_TYPE])

    def test_single_lease_winner_for_one_queued_job(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn)
            claimed = control_plane.claim_job(conn, worker="worker-a")
            self.assertEqual(claimed, job_id)
            # A second worker cannot steal a live lease, even by job id.
            with self.assertRaises(PersistenceConflict):
                control_plane.claim_job(conn, worker="worker-b", job_id=job_id)
        # And a racing worker finds nothing claimable afterwards.
        with psycopg.connect(self.database_url) as conn:
            control_plane.set_job_status(conn, job_id=job_id, status="cancelled")
        result = worker.run_once(self.database_url, worker="worker-b")
        self.assertIsNone(result)

    def test_concurrent_workers_split_one_queued_job(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            _queue_job(conn)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(worker.run_once, self.database_url, worker=f"racer-{n}")
                for n in range(2)
            ]
            results = [future.result(timeout=120) for future in futures]
        completed = [result for result in results if result is not None]
        idle = [result for result in results if result is None]
        # Exactly one worker wins the single lease; the loser stays idle.
        self.assertEqual(len(completed), 1)
        self.assertEqual(len(idle), 1)
        self.assertEqual(completed[0][1], "completed")

    def test_two_independent_jobs_progress_concurrently_without_duplicates(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            _queue_job(conn, title="武帝紀")
            _queue_job(conn, title="吳主傳")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(worker.run_once, self.database_url, worker=f"parallel-{n}")
                for n in range(2)
            ]
            results = [future.result(timeout=120) for future in futures]
        self.assertTrue(all(result is not None for result in results))
        job_ids = [result[0] for result in results]
        self.assertEqual(len(set(job_ids)), 2)
        self.assertTrue(all(result[1] == "completed" for result in results))
        with psycopg.connect(self.database_url) as conn:
            for job_id in job_ids:
                runs = _chunk_runs(conn, job_id)
                # No duplicate stage execution: exactly one run per chunk.
                self.assertEqual(len(runs), 2, (job_id, runs))

    def test_crash_reclaim_resumes_from_checkpoints(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn)
            control_plane.claim_job(conn, worker="worker-crasher")
            # Partial progress checkpointed before the crash.
            control_plane.advance_stage(conn, job_id=job_id, stage="prepare", status="running")
            control_plane.advance_stage(conn, job_id=job_id, stage="prepare", status="completed")
            # Simulate worker loss: the lease expires while checkpoints stay.
            conn.execute(
                """
                UPDATE chronicle.ingestion_jobs
                SET lease_expires_at = now() - interval '1 second'
                WHERE job_id = %s
                """,
                (job_id,),
            )
        # A restarted worker process reclaims the expired lease on a fresh
        # connection and finishes the job without re-running `prepare`.
        result = worker.run_once(self.database_url, worker="worker-restart")
        self.assertEqual(result, (job_id, "completed"))
        with psycopg.connect(self.database_url) as conn:
            # Takeover evidence: the reclaim consumed a second claim
            # attempt, and the post-crash work ran as worker-restart.
            # (The completed job clears its lease by design.)
            attempt = conn.execute(
                "SELECT attempt FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(attempt, 2)
            workers = {
                row[3] for row in conn.execute(
                    """
                    SELECT r.run_id, r.attempt, r.status, r.worker
                    FROM chronicle.ingestion_chunk_runs r
                    JOIN chronicle.ingestion_chunks c ON c.chunk_id = r.chunk_id
                    WHERE c.job_id = %s
                    """,
                    (job_id,),
                ).fetchall()
            }
            self.assertEqual(workers, {"worker-restart"})
            attempt = conn.execute(
                """
                SELECT attempt FROM chronicle.ingestion_job_stages
                WHERE job_id = %s AND stage = 'prepare'
                """,
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(
                attempt, 1,
                "completed checkpoints must not be re-entered after reclaim",
            )

    def test_chunk_retry_appends_attempts_and_skips_succeeded_work(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn)
        first = worker.run_once(
            self.database_url, worker="worker-retry",
            executor=StageExecutor(fail_chunks={0: 1}),
        )
        self.assertEqual(first, (job_id, "failed"))
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(_job_status(conn, job_id), "failed")
            runs = _chunk_runs(conn, job_id)
            self.assertEqual([(run[0], run[1], run[2]) for run in runs], [(0, 1, "failed")])
            # Bounded Studio retry resets only the failed work.
            control_plane.retry_job(conn, job_id=job_id)
            self.assertEqual(_job_status(conn, job_id), "running")
        second = worker.run_once(self.database_url, worker="worker-retry")
        self.assertEqual(second, (job_id, "completed"))
        with psycopg.connect(self.database_url) as conn:
            runs = _chunk_runs(conn, job_id)
            # Prior evidence is preserved; the retry appends attempt 2.
            self.assertEqual(
                [(run[0], run[1], run[2]) for run in runs],
                [(0, 1, "failed"), (0, 2, "completed"), (1, 1, "completed")],
            )
            stages = _stage_statuses(conn, job_id)
            self.assertTrue(all(s == "completed" for s in stages.values()))

    def test_exhausted_chunks_open_review_and_resume_completes(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn)
        first = worker.run_once(
            self.database_url, worker="worker-gate",
            executor=StageExecutor(fail_chunks={0: 99}),
        )
        self.assertEqual(first[1], "failed")
        # Drive chunk 0 to exhaustion through bounded retries.
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                "UPDATE chronicle.ingestion_chunks SET max_attempts = 1 WHERE job_id = %s",
                (job_id,),
            )
            control_plane.retry_job(conn, job_id=job_id)
        second = worker.run_once(
            self.database_url, worker="worker-gate",
            executor=StageExecutor(fail_chunks={0: 99}),
        )
        self.assertEqual(second, (job_id, "needs_review"))
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(_job_status(conn, job_id), "needs_review")
            reviews = conn.execute(
                "SELECT kind, status FROM chronicle.review_items WHERE job_id = %s",
                (job_id,),
            ).fetchall()
            self.assertEqual([(row[0], row[1]) for row in reviews], [("chunk_failure", "open")])
            # Resume is refused while the gate is open.
            with self.assertRaises(PersistenceConflict):
                control_plane.resume_job(conn, job_id=job_id)
            review_id = conn.execute(
                "SELECT review_id FROM chronicle.review_items WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            control_plane.resolve_review_item(conn, review_id=review_id)
            # The exhausted chunk gets one more bounded attempt after resume.
            conn.execute(
                "UPDATE chronicle.ingestion_chunks SET max_attempts = 3 WHERE job_id = %s",
                (job_id,),
            )
            control_plane.resume_job(conn, job_id=job_id)
        third = worker.run_once(self.database_url, worker="worker-gate")
        self.assertEqual(third, (job_id, "completed"))
        with psycopg.connect(self.database_url) as conn:
            runs = _chunk_runs(conn, job_id)
            chunk0 = [run for run in runs if run[0] == 0]
            self.assertEqual(len(chunk0), 3)
            self.assertEqual(chunk0[-1][2], "completed")

    def test_cancel_stops_new_work_without_corrupting_checkpoints(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn)
            control_plane.claim_job(conn, worker="worker-cancel")
            control_plane.advance_stage(conn, job_id=job_id, stage="prepare", status="running")
            control_plane.advance_stage(conn, job_id=job_id, stage="prepare", status="completed")
            control_plane.cancel_job(conn, job_id=job_id)
            self.assertEqual(_job_status(conn, job_id), "cancelled")
        with psycopg.connect(self.database_url) as conn:
            outcome = worker.execute_job(conn, job_id=job_id, worker="worker-cancel")
            self.assertEqual(outcome, "cancelled")
            stages = _stage_statuses(conn, job_id)
            self.assertEqual(stages["prepare"], "completed")
            self.assertEqual(stages["structure"], "pending")

    def test_bounded_retry_refuses_exhausted_jobs(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn, max_attempts=1)
        result = worker.run_once(
            self.database_url, worker="worker-bound",
            executor=StageExecutor(fail_plan={"prepare": 99}),
        )
        self.assertEqual(result, (job_id, "failed"))
        with psycopg.connect(self.database_url) as conn:
            # The single claim attempt is consumed; no further retry allowed.
            with self.assertRaises(PersistenceConflict):
                control_plane.retry_job(conn, job_id=job_id)
            self.assertEqual(_job_status(conn, job_id), "failed")

    def test_graceful_stop_keeps_running_lease_for_reclaim(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn)
            control_plane.claim_job(conn, worker="worker-stop")
            stop = threading.Event()
            stop.set()
            outcome = worker.execute_job(conn, job_id=job_id, worker="worker-stop", stop=stop)
            self.assertEqual(outcome, "stopped")
            # The job is still running under its lease, so the next worker
            # reclaims it after expiry instead of finding corrupt state.
            self.assertEqual(_job_status(conn, job_id), "running")
            owner = conn.execute(
                "SELECT lease_owner FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(owner, "worker-stop")


class WorkerUnitTests(unittest.TestCase):
    def test_fail_plan_rejects_unknown_stages(self) -> None:
        with self.assertRaises(Exception):
            worker.parse_fail_plan(["nope:2"])

    def test_executor_is_deterministic(self) -> None:
        job_id = uuid.uuid4()
        executor = StageExecutor(fail_plan={"prepare": 1}, fail_chunks={0: 2})
        with self.assertRaises(StageExecutionError):
            executor.execute_stage("prepare", job_id)
        executor.execute_stage("prepare", job_id)
        for _ in range(2):
            with self.assertRaises(StageExecutionError):
                executor.execute_chunk(0, job_id)
        executor.execute_chunk(0, job_id)

    def test_worker_ids_are_unique(self) -> None:
        self.assertNotEqual(worker.default_worker_id(), worker.default_worker_id())


if __name__ == "__main__":
    unittest.main()
