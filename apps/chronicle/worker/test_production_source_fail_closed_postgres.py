"""C1-T13 regression: real immutable source jobs never fall back to fake extraction."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import control_plane  # noqa: E402
from migrations import apply_migrations  # noqa: E402
import ingestion_worker as worker  # noqa: E402

FIXTURE_DIR = HERE.parent / "ingestion" / "fixtures" / "c1t5-boundary-continuity"
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


class ProductionSourceFailClosedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t13_failclosed_{uuid.uuid4().hex}"
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

    def test_real_revision_without_extraction_model_fails_before_fake_chunk_runs(self) -> None:
        raw = (FIXTURE_DIR / "raw.txt").read_bytes()
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        import hashlib
        source_sha = hashlib.sha256(raw).hexdigest()

        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title="real-source-no-model")
            revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=source_sha,
                source_bytes=len(raw),
                source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)

        result = worker.run_once(
            self.database_url,
            worker="worker-c1t13-no-model",
            revision_source=lambda _job_id: (text, source_sha),
            chunk_model=None,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0], job_id)
        self.assertEqual(result[1], "failed")

        with psycopg.connect(self.database_url) as conn:
            job = conn.execute(
                "SELECT status, last_error FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            self.assertEqual(job[0], "failed")
            self.assertIn("extraction model", job[1])

            stages = dict(
                conn.execute(
                    "SELECT stage_name, status FROM chronicle.ingestion_job_stages WHERE job_id = %s",
                    (job_id,),
                ).fetchall()
            )
            self.assertEqual(stages["structure"], "completed")
            self.assertEqual(stages["segment"], "completed")
            self.assertEqual(stages["extract"], "failed")

            run_count = conn.execute(
                """
                SELECT count(*)
                FROM chronicle.ingestion_chunk_runs cr
                JOIN chronicle.ingestion_chunks c ON c.chunk_id = cr.chunk_id
                WHERE c.job_id = %s
                """,
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(run_count, 0)

            fake_outputs = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_outputs WHERE job_id = %s AND artifact_type = %s",
                (job_id, worker.FAKE_OUTPUT_TYPE),
            ).fetchone()[0]
            self.assertEqual(fake_outputs, 0)


if __name__ == "__main__":
    unittest.main()
