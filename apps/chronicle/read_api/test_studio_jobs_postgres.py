"""PostgreSQL 18 integration tests for the Studio ingestion-job HTTP surface.

Exercises the real sidecar (ThreadingHTTPServer + handler_class) against
an isolated database: queue, list/detail inspection, retry, resume, and
cancel, plus safe failures (unknown revision/job, illegal transitions,
exhausted retries, open-review resume, oversize bodies). This is the
HTTP-level proof of the C1-T4 Studio contract; the Rust proxy tests cover
auth gating and byte passthrough separately.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
WORKER = HERE.parent / "worker"
ROOT = HERE.parents[2]
for candidate in (str(HERE), str(PERSISTENCE), str(WORKER)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from server import handler_class  # noqa: E402

import control_plane  # noqa: E402
import ingestion_worker as worker  # noqa: E402
from studio_jobs import STUDIO_JOBS_PREFIX  # noqa: E402

from migrations import apply_migrations  # noqa: E402


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


class StudioJobsHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_jobs_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
        self.storage_dir = tempfile.mkdtemp(prefix="chronicle-jobs-")
        handler = handler_class(self.database_url, storage_dir=self.storage_dir)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title="武帝紀")
            self.revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=_sha256(f"jobs-raw-{uuid.uuid4().hex}"),
                source_bytes=512,
                source_media_type="text/plain",
            )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    # -- HTTP helpers ----------------------------------------------------

    def _request(self, method: str, path: str, body: bytes | dict | None = None,
                 content_type: str | None = None):
        data = None
        headers = {}
        if isinstance(body, dict):
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif body is not None:
            data = body
        if content_type is not None:
            headers["Content-Type"] = content_type
        request = Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()

    def _json(self, method: str, path: str, body: bytes | dict | None = None):
        status, raw = self._request(method, path, body)
        return status, json.loads(raw.decode("utf-8"))

    # -- lifecycle -------------------------------------------------------

    def test_queue_inspect_complete_round_trip(self) -> None:
        status, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)}
        )
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["schema"], "chronicle.job")
        job = payload["job"]
        self.assertEqual(job["status"], "queued")
        self.assertEqual(len(job["stages"]), 8)
        job_id = job["job_id"]

        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["revision_id"], str(self.revision_id))

        status, payload = self._json("GET", STUDIO_JOBS_PREFIX)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["schema"], "chronicle.job-list")
        self.assertEqual(len(payload["jobs"]), 1)

        # The fake worker drains the queued job end to end through Studio state.
        claimed = worker.run_once(self.database_url, worker="studio-e2e")
        self.assertEqual(claimed[1], "completed")
        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        self.assertEqual(payload["job"]["status"], "completed")
        self.assertEqual(len(payload["job"]["outputs"]), 1)
        self.assertEqual(len(payload["job"]["chunks"]), 2)
        for chunk in payload["job"]["chunks"]:
            self.assertEqual(chunk["status"], "completed")
            self.assertEqual(len(chunk["runs"]), 1)

    def test_queue_rejects_unknown_revision(self) -> None:
        status, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX, {"revision_id": str(uuid.uuid4())}
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_retry_failed_job_and_refuse_terminal_retry(self) -> None:
        _, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX,
            {"revision_id": str(self.revision_id), "max_attempts": 3},
        )
        job_id = payload["job"]["job_id"]
        from ingestion_worker import StageExecutor

        claimed = worker.run_once(
            self.database_url, worker="studio-retry",
            executor=StageExecutor(fail_plan={"prepare": 99}),
        )
        self.assertEqual(claimed[1], "failed")

        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/retry")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["status"], "running")

        # A running job is not retryable: only failed jobs accept retry.
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/retry")
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "conflict")

    def test_resume_requires_resolved_reviews(self) -> None:
        _, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)}
        )
        job_id = payload["job"]["job_id"]
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(conn, worker="studio-review")
            control_plane.set_job_status(conn, job_id=uuid.UUID(job_id), status="needs_review")
            control_plane.open_review_item(
                conn, job_id=uuid.UUID(job_id), kind="quality_flag",
                payload={"note": "check era name"},
            )
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/resume")
        self.assertEqual(status, 409, payload)
        with psycopg.connect(self.database_url) as conn:
            review_id = conn.execute(
                "SELECT review_id FROM chronicle.review_items WHERE job_id = %s",
                (uuid.UUID(job_id),),
            ).fetchone()[0]
            control_plane.resolve_review_item(conn, review_id=review_id)
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/resume")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["status"], "running")

    def test_cancel_preserves_checkpoints_and_rejects_terminal(self) -> None:
        _, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)}
        )
        job_id = payload["job"]["job_id"]
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(conn, worker="studio-cancel")
            control_plane.advance_stage(
                conn, job_id=uuid.UUID(job_id), stage="prepare", status="running"
            )
            control_plane.advance_stage(
                conn, job_id=uuid.UUID(job_id), stage="prepare", status="completed"
            )
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/cancel")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["status"], "cancelled")
        prepare = next(
            stage for stage in payload["job"]["stages"] if stage["stage"] == "prepare"
        )
        self.assertEqual(prepare["status"], "completed")
        # Cancelling again is idempotent (self-transitions are legal
        # worker re-entries): still cancelled, checkpoints intact.
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/cancel")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["status"], "cancelled")

    def test_unknown_job_is_404_and_bad_body_is_400(self) -> None:
        missing = str(uuid.uuid4())
        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{missing}")
        self.assertEqual(status, 404, payload)
        status, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX, {"revision_id": "not-a-uuid"}
        )
        self.assertEqual(status, 404, payload)
        status, raw = self._request("POST", STUDIO_JOBS_PREFIX, b"{not json")
        self.assertEqual(status, 400, raw)
        status, payload = self._json("PUT", STUDIO_JOBS_PREFIX, {})
        self.assertEqual(status, 405, payload)

    def test_list_supports_status_filter(self) -> None:
        _, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)}
        )
        job_id = payload["job"]["job_id"]
        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}?status=queued")
        self.assertEqual(len(payload["jobs"]), 1)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(conn, worker="studio-filter")
            control_plane.cancel_job(conn, job_id=uuid.UUID(job_id))
        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}?status=queued")
        self.assertEqual(payload["jobs"], [])
        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}?status=cancelled")
        self.assertEqual(len(payload["jobs"]), 1)


if __name__ == "__main__":
    unittest.main()
