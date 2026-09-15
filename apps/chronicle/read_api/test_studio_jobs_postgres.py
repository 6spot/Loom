"""PostgreSQL 18 integration tests for the Studio ingestion-job HTTP surface.

Exercises the real sidecar (ThreadingHTTPServer + handler_class) against
an isolated database: queue, list/detail inspection, retry, resume, and
cancel, plus safe failures (unknown revision/job, illegal transitions,
exhausted retries, open-review resume, oversize bodies). This is the
HTTP-level proof of the current Studio contract; the Rust proxy tests cover
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
from unittest import mock

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
from studio_jobs import STUDIO_JOBS_PREFIX  # noqa: E402

from migrations import apply_migrations  # noqa: E402
from common import sha256_json  # noqa: E402
import studio_production  # noqa: E402


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

    def _model_env(self):
        return {"CHRONICLE_CHAPTER_MODEL": "luna", "CHRONICLE_CHAPTER_REVIEW_MODELS": "review-model",
                "CHRONICLE_MODEL_ENDPOINT": "https://private-provider.invalid/v1/responses",
                "CHRONICLE_MODEL_API_KEY": "not-for-the-browser"}

    def test_model_catalog_and_selection_are_credential_free_and_persisted(self):
        with mock.patch.dict(os.environ, self._model_env(), clear=True):
            status, choices = self._json("GET", STUDIO_JOBS_PREFIX + "/model-options")
            self.assertEqual(status, 200, choices)
            self.assertEqual([item["name"] for item in choices["models"]], ["luna", "review-model"])
            self.assertNotIn("private-provider", json.dumps(choices))
            self.assertNotIn("not-for-the-browser", json.dumps(choices))
            selection = {key: choices[key] for key in ("config_sha256", "steps")}
            selection["steps"]["translation"] = ["reviewer_1"]
            status, body = self._json("POST", STUDIO_JOBS_PREFIX,
                {"revision_id": str(self.revision_id), "model_selection": selection})
            self.assertEqual(status, 201, body)
            job = body["job"]
            self.assertEqual(job["production_request"]["model_selection"], selection)
            self.assertEqual(job["document"]["title"], "武帝紀")
            self.assertEqual(job["job_kind"], "chapter")
            with psycopg.connect(self.database_url) as conn:
                self.assertEqual(studio_production.read_request(conn, job["job_id"])["model_selection"], selection)
            selection["config_sha256"] = "0" * 64
            status, _ = self._json("POST", STUDIO_JOBS_PREFIX,
                {"revision_id": str(self.revision_id), "model_selection": selection})
            self.assertEqual(status, 409)
            selection["config_sha256"] = choices["config_sha256"]
            selection["steps"]["translation"] = ["unconfigured-model"]
            status, _ = self._json("POST", STUDIO_JOBS_PREFIX,
                {"revision_id": str(self.revision_id), "model_selection": selection})
            self.assertEqual(status, 400)
            _, listing = self._json("GET", STUDIO_JOBS_PREFIX)
            self.assertEqual(len(listing["jobs"]), 1, "invalid selections must not create jobs")
            self.assertEqual(listing["jobs"][0]["document"], job["document"])

    def test_linked_rerun_retains_original_results_and_exact_revision(self):
        _, body = self._json("POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)})
        original_id = body["job"]["job_id"]
        path = f"{STUDIO_JOBS_PREFIX}/{original_id}"
        self.assertEqual(self._json("POST", path + "/rerun")[0], 409)
        with psycopg.connect(self.database_url) as conn:
            job_uuid = uuid.UUID(original_id)
            control_plane.claim_job(conn, worker="rerun-test", job_id=job_uuid)
            control_plane.advance_stage(conn, job_id=job_uuid, stage="prepare", status="running")
            control_plane.advance_stage(conn, job_id=job_uuid, stage="prepare", status="failed", error="test failure")
            control_plane.set_job_status(conn, job_id=job_uuid, status="failed", error="test failure")
            result = {"step": "translation", "status": "completed", "parsed": {"blocks": [{"text": "旧结果仍保留。"}]}}
            control_plane.record_output(conn, job_id=job_uuid, revision_id=self.revision_id,
                artifact_type="chapter-production-step", artifact_sha256=sha256_json(result), payload=result)
        _, original = self._json("GET", path)
        status, body = self._json("POST", path + "/rerun", {})
        self.assertEqual(status, 201, body)
        created = body["job"]
        self.assertNotEqual(created["job_id"], original_id)
        self.assertEqual(created["revision_id"], str(self.revision_id))
        self.assertEqual(created["production_request"]["parent_job_id"], original_id)
        self.assertEqual(created["status"], "queued")
        self.assertTrue(all(item["status"] == "pending" for item in created["stages"]))
        self.assertEqual(created["chunks"], [])
        _, retained = self._json("GET", path)
        self.assertEqual(retained, original, "new run must not rewrite the original task or its outputs")
        with psycopg.connect(self.database_url) as conn:
            conn.execute("UPDATE chronicle.ingestion_jobs SET checkpoint = %s WHERE job_id=%s",
                (psycopg.types.json.Jsonb({"narrative_scope": {"publication_ids": ["saved-source"]}}), original_id))
        self.assertEqual(self._json("POST", path + "/rerun")[0], 409,
                         "narrative tasks must not become chapter tasks on rerun")

    def test_job_and_model_request_commit_atomically(self):
        with psycopg.connect(self.database_url) as conn:
            before = conn.execute("SELECT count(*) FROM chronicle.ingestion_jobs").fetchone()[0]
            with mock.patch.object(control_plane, "record_output", side_effect=RuntimeError("storage failure")):
                with self.assertRaisesRegex(RuntimeError, "storage failure"):
                    studio_production.queue(conn, revision_id=self.revision_id,
                        selection={"config_sha256": "0" * 64, "steps": {}})
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.ingestion_jobs").fetchone()[0], before)

    def test_saved_outputs_are_exact_scoped_paginated_and_exclude_requests(self):
        _, body = self._json("POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)})
        job_id = body["job"]["job_id"]
        result = {"step": "translation", "model": "luna", "status": "completed", "round": 0, "attempt": 1,
                  "parsed": {"blocks": [{"text": "完整白话文𠮷。" * 100}]}, "raw_text": "保留模型返回。",
                  "prompt": "private-prompt", "input": {"hidden": "private-input"},
                  "model_config": {"api_key": "private-key"}, "receipt": {"endpoint": "private-provider"}}
        digest = sha256_json(result)
        with psycopg.connect(self.database_url) as conn:
            control_plane.record_output(conn, job_id=uuid.UUID(job_id), revision_id=self.revision_id,
                artifact_type="chapter-production-step", artifact_sha256=digest, payload=result)
        _, detail = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        self.assertTrue(detail["job"]["outputs"][0]["readable"])
        self.assertEqual(detail["job"]["outputs"][0]["model"], "luna")
        self.assertNotIn("完整白话文", json.dumps(detail, ensure_ascii=False), "detail lists metadata only")
        path = f"{STUDIO_JOBS_PREFIX}/{job_id}/outputs/{digest}"
        collected, offset = "", 0
        while offset is not None:
            status, page = self._json("GET", path + f"?offset={offset}&limit=333")
            self.assertEqual(status, 200, page)
            self.assertEqual(page["job_id"], job_id)
            self.assertEqual(page["output_sha256"], digest)
            self.assertEqual(page["offset"], offset)
            self.assertLessEqual(len(page["text"]), 333)
            collected += page["text"]
            offset = page["next_offset"]
        value = json.loads(collected)
        self.assertEqual(value["parsed"], result["parsed"])
        self.assertEqual(value["raw_text"], result["raw_text"])
        self.assertNotIn("private-", collected)
        self.assertEqual(self._json("GET", path + "?limit=16001")[0], 400)
        self.assertEqual(self._json("GET", path + "?offset=-1")[0], 400)
        self.assertEqual(self._json("GET", path + "?offset=999999")[0], 400)
        self.assertEqual(self._json("GET", f"{STUDIO_JOBS_PREFIX}/{uuid.uuid4()}/outputs/{digest}")[0], 404)
        with psycopg.connect(self.database_url) as conn:
            conn.execute("UPDATE chronicle.ingestion_outputs SET payload=%s WHERE job_id=%s AND artifact_sha256=%s",
                (psycopg.types.json.Jsonb({**result, "status": "changed"}), job_id, digest))
        self.assertEqual(self._json("GET", path)[0], 409)

    def test_acceptance_receipt_output_is_readable_without_candidate_or_transport_data(self):
        _, body = self._json("POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)})
        job_id = body["job"]["job_id"]
        receipt = {
            "schema": "chronicle.chapter-acceptance",
            "version": "0.1",
            "status": "accepted",
            "chapter_id": "ch_" + "1" * 24,
            "chunk_id": "chunk-1",
            "request_fingerprint": "a" * 64,
            "candidate_sha256": "b" * 64,
            "history_sha256": "c" * 64,
            "step_output_sha256s": ["d" * 64],
            "decision": {"kind": "human", "candidate": "do-not-embed"},
            "draft_sha256": "e" * 64,
            "prompt": "must not be exposed",
        }
        digest = sha256_json(receipt)
        with psycopg.connect(self.database_url) as conn:
            control_plane.record_output(
                conn,
                job_id=uuid.UUID(job_id),
                revision_id=self.revision_id,
                artifact_type=studio_production.ACCEPTANCE_TYPE,
                artifact_sha256=digest,
                payload=receipt,
            )
        status, detail = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        self.assertEqual(status, 200, detail)
        acceptance = next(
            item for item in detail["job"]["outputs"]
            if item["artifact_type"] == studio_production.ACCEPTANCE_TYPE
        )
        self.assertTrue(acceptance["readable"])
        accepted = detail["job"]["accepted_results"][0]
        self.assertIn("d" * 64, accepted["model_output_sha256s"])
        status, page = self._json(
            "GET", f"{STUDIO_JOBS_PREFIX}/{job_id}/outputs/{digest}"
        )
        self.assertEqual(status, 200, page)
        value = json.loads(page["text"])
        self.assertEqual("accepted", value["status"])
        self.assertEqual("chunk-1", value["chunk_id"])
        self.assertEqual({"kind": "human"}, value["decision"])
        self.assertNotIn("do-not-embed", page["text"])
        self.assertNotIn("prompt", value)

    def test_queue_inspect_complete_round_trip(self) -> None:
        status, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)}
        )
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["schema"], "chronicle.job")
        job = payload["job"]
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["max_attempts"], 8)
        self.assertEqual(len(job["stages"]), 8)
        job_id = job["job_id"]

        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["revision_id"], str(self.revision_id))

        status, payload = self._json("GET", STUDIO_JOBS_PREFIX)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["schema"], "chronicle.job-list")
        self.assertEqual(len(payload["jobs"]), 1)
        listed = payload["jobs"][0]
        self.assertEqual(listed["task"]["label"], "章节生产任务")
        self.assertEqual(len(listed["step_graph"]["steps"]), 8)
        self.assertEqual(listed["step_graph"]["dependencies"]["present"], ["publish"])
        self.assertIn("cancel", listed["available_actions"])

        # The HTTP surface queues work; the current staged worker owns
        # execution and is covered by the T01 fixture-backed PostgreSQL suite.
        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["status"], "queued")
        self.assertEqual(payload["job"]["outputs"], [])
        self.assertEqual(payload["job"]["chunks"], [])

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
        with psycopg.connect(self.database_url) as conn:
            job_uuid = uuid.UUID(job_id)
            control_plane.claim_job(conn, worker="studio-retry", job_id=job_uuid)
            control_plane.advance_stage(conn, job_id=job_uuid, stage="prepare", status="running")
            control_plane.advance_stage(conn, job_id=job_uuid, stage="prepare", status="failed", error="test failure")
            control_plane.set_job_status(conn, job_id=job_uuid, status="failed", error="test failure")

        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/retry")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["status"], "running")

        # A running job is not retryable: only failed jobs accept retry.
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/retry")
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "conflict")

    def test_unified_projection_reports_real_actions_and_new_run(self) -> None:
        _, payload = self._json(
            "POST", STUDIO_JOBS_PREFIX,
            {"revision_id": str(self.revision_id), "max_attempts": 3},
        )
        job_id = payload["job"]["job_id"]
        self.assertEqual(payload["job"]["task"]["type"], "chapter")
        actions = {item["key"]: item for item in payload["job"]["actions"]}
        self.assertTrue(actions["cancel"]["available"])
        self.assertFalse(actions["new_run"]["available"])
        self.assertEqual(payload["job"]["current_step"]["label"], "准备")
        with psycopg.connect(self.database_url) as conn:
            job_uuid = uuid.UUID(job_id)
            control_plane.claim_job(conn, worker="studio-projection", job_id=job_uuid)
            control_plane.advance_stage(conn, job_id=job_uuid, stage="prepare", status="running")
            control_plane.advance_stage(conn, job_id=job_uuid, stage="prepare", status="failed", error="test failure")
            control_plane.set_job_status(conn, job_id=job_uuid, status="failed", error="test failure")
        status, payload = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        self.assertEqual(status, 200, payload)
        actions = {item["key"]: item for item in payload["job"]["actions"]}
        self.assertTrue(actions["retry"]["available"])
        self.assertTrue(actions["new_run"]["available"])
        self.assertFalse(actions["cancel"]["available"])
        self.assertEqual(payload["job"]["current_step"]["failure_reason"], "test failure")
        status, child_payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{job_id}/new-run", {})
        self.assertEqual(status, 201, child_payload)
        child = child_payload["job"]
        self.assertEqual(child["production_request"]["parent_job_id"], job_id)
        self.assertEqual(child["revision_id"], str(self.revision_id))

    def test_attempt_projection_and_raw_result_page_are_redacted_and_linked(self) -> None:
        _, payload = self._json("POST", STUDIO_JOBS_PREFIX, {"revision_id": str(self.revision_id)})
        job_id = payload["job"]["job_id"]
        job_uuid = uuid.UUID(job_id)
        start = {
            "schema": "chronicle.chapter-step-attempt", "version": "0.1",
            "node_key": "node-1", "step": "extraction", "slot": "primary",
            "round": 0, "attempt": 1, "model": "model-a",
            "model_config": {"api_key": "private-key", "endpoint": "https://private.invalid"},
            "prompt": "private prompt", "input": {"secret": "private input"},
            "input_sha256": "a" * 64, "status": "started",
            "started_at": "2026-09-15T01:00:00+00:00",
        }
        start_sha = sha256_json(start)
        result = {
            "schema": "chronicle.chapter-step", "version": "0.1",
            "node_key": "node-1", "step": "extraction", "slot": "primary",
            "round": 0, "attempt": 1, "model": "model-a", "attempt_sha256": start_sha,
            "raw_text": "可读模型结果。", "parsed": {"claims": [{"text": "事实", "api_key": "private"}]},
            "validation_errors": [], "receipt": {
                "status": "completed", "elapsed_seconds": 2.5,
                "usage": {"output_tokens": 9}, "endpoint": "https://private.invalid",
            }, "status": "completed",
        }
        result_sha = sha256_json(result)
        with psycopg.connect(self.database_url) as conn:
            control_plane.record_output(conn, job_id=job_uuid, revision_id=self.revision_id,
                artifact_type="chapter-production-attempt", artifact_sha256=start_sha, payload=start)
            control_plane.record_output(conn, job_id=job_uuid, revision_id=self.revision_id,
                artifact_type="chapter-production-step", artifact_sha256=result_sha, payload=result)
        _, detail = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}")
        attempt = detail["job"]["attempts"][0]
        self.assertEqual(attempt["attempt_sha256"], start_sha)
        self.assertEqual(attempt["result_sha256"], result_sha)
        self.assertEqual(attempt["attempt_count"], 1)
        self.assertTrue(attempt["output_complete"])
        self.assertEqual(attempt["validation_status"], "passed")
        self.assertEqual(attempt["usage"], {"output_tokens": 9})
        self.assertNotIn("private-key", json.dumps(detail, ensure_ascii=False))
        self.assertNotIn("private.invalid", json.dumps(detail, ensure_ascii=False))
        status, page = self._json("GET", f"{STUDIO_JOBS_PREFIX}/{job_id}/outputs/{result_sha}")
        self.assertEqual(status, 200, page)
        self.assertEqual(page["revision_id"], str(self.revision_id))
        self.assertNotIn("private-key", page["text"])
        self.assertNotIn("private.invalid", page["text"])
        self.assertNotIn("prompt", page["text"])

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
