"""Current production-entry regression: missing providers fail closed."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (str(HERE), str(HERE.parent / "persistence")):
    if path not in sys.path:
        sys.path.insert(0, path)

import ingestion_worker as worker  # noqa: E402
import pipeline_test_support as support  # noqa: E402


class ProductionSourceFailClosedTests(support.CurrentPipelineDatabase, unittest.TestCase):
    def test_missing_staged_provider_fails_before_creating_processing_outputs(self) -> None:
        job_id, _revision_id, source_sha = self._queue_job(support.TEXT_DISTINCT)

        result = worker.run_once(
            self.database_url,
            worker="current-production-no-model",
            revision_source=lambda _job_id: (support.TEXT_DISTINCT, source_sha),
            chapter_model=None,
        )
        self.assertEqual((job_id, "failed"), result)

        with support.psycopg.connect(self.database_url) as conn:
            job = conn.execute(
                "SELECT status, error FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            self.assertEqual(job[0], "failed")
            self.assertIn("staged 0.4 provider", job[1])

            stages = dict(
                conn.execute(
                    "SELECT stage, status FROM chronicle.ingestion_job_stages WHERE job_id = %s",
                    (job_id,),
                ).fetchall()
            )
            self.assertEqual(set(stages.values()), {"pending"})
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_chunk_runs cr "
                    "JOIN chronicle.ingestion_chunks c ON c.chunk_id = cr.chunk_id "
                    "WHERE c.job_id = %s",
                    (job_id,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_outputs WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
