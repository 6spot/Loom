"""PostgreSQL 18 integration tests for the C1-T11 Studio review surface."""

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
ROOT = HERE.parents[2]
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from server import handler_class  # noqa: E402

import control_plane  # noqa: E402
import resolution_store  # noqa: E402
import resolve_publish  # noqa: E402
import staged_store  # noqa: E402
from migrations import apply_migrations  # noqa: E402
from studio_jobs import STUDIO_JOBS_PREFIX  # noqa: E402
from studio_reviews import STUDIO_REVIEWS_PREFIX  # noqa: E402

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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _source(title: str) -> dict:
    return {
        "temp_id": "src_001",
        "kind": "source",
        "source_type": "book",
        "title": title,
        "author": "陳壽",
        "language": "lzh",
        "extraction": {"method": "model", "job_id": "review-test", "confidence": 0.8},
    }


def _entity(name: str) -> dict:
    return {
        "temp_id": "ent_001",
        "kind": "entity",
        "type": "person",
        "canonical_name": name,
        "aliases": [],
        "mentions": [{"text": name}],
        "resolution": {"status": "unresolved"},
        "extraction": {"method": "model", "job_id": "review-test", "confidence": 0.8},
    }


def _event(title: str) -> dict:
    return {
        "temp_id": "evt_001",
        "kind": "event",
        "type": "battle",
        "title": title,
        "time": None,
        "participants": [],
        "places": [],
        "extraction": {"method": "model", "job_id": "review-test", "confidence": 0.8},
    }


def _bundle(title: str, *, entity: str, event: str) -> dict:
    return {
        "schema_version": "0.1",
        "source": _source(title),
        "entities": [_entity(entity)],
        "events": [_event(event)],
        "claims": [],
        "warnings": [],
    }


class StudioReviewsHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_reviews_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            document_id = control_plane.create_document(conn, title="三國志測試")
            self.revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=_sha(uuid.uuid4().hex),
                source_bytes=128,
                source_media_type="text/plain",
                filename="review.txt",
                language="zh-Hant",
                source_label="test edition",
            )
            self.job_id = control_plane.queue_job(conn, revision_id=self.revision_id)
            control_plane.claim_job(conn, worker="review-test", job_id=self.job_id)
            control_plane.set_job_status(conn, job_id=self.job_id, status="needs_review")

            left = _bundle("武帝紀", entity="曹操", event="赤壁之戰")
            right = _bundle("新校本", entity="曹操", event="赤壁之役")
            staged_store.persist_bundle(conn, "left", left)
            staged_store.persist_bundle(conn, "right", right)
            self.resolution = {
                "schema": "chronicle.resolution-links",
                "version": resolve_publish.RESOLUTION_VERSION,
                "left_bundle": {"label": "left", "source_ref": "src_001", "source_title": "武帝紀"},
                "right_bundle": {"label": "right", "source_ref": "src_001", "source_title": "新校本"},
                "entity_links": [
                    {
                        "candidate_id": "entity-1",
                        "left": {"bundle": "left", "ref": "ent_001"},
                        "right": {"bundle": "right", "ref": "ent_001"},
                        "decision": "uncertain",
                        "confidence": 0.5,
                        "rationale": "shared surface is insufficient for identity",
                        "signals": ["same_type", "exact_name"],
                    }
                ],
                "event_links": [
                    {
                        "candidate_id": "event-1",
                        "left": {"bundle": "left", "ref": "evt_001"},
                        "right": {"bundle": "right", "ref": "evt_001"},
                        "decision": "uncertain",
                        "confidence": 0.5,
                        "rationale": "event occurrence needs human review",
                        "signals": ["participant_overlap"],
                    }
                ],
                "warnings": [],
            }
            self.resolution_sha, _ = resolution_store.persist_resolution(conn, self.resolution)
            self.review_ids = resolve_publish.open_resolution_reviews(
                conn, job_id=self.job_id, resolutions=[self.resolution]
            )
            conn.commit()

        self.storage_dir = tempfile.mkdtemp(prefix="chronicle-reviews-")
        handler = handler_class(self.database_url, storage_dir=self.storage_dir)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name)))

    def _json(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_list_and_detail_are_source_attributed(self) -> None:
        status, payload = self._json("GET", STUDIO_REVIEWS_PREFIX)
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["reviews"]), 2)
        entity = next(item for item in payload["reviews"] if item["link_kind"] == "entity")
        self.assertEqual(entity["document"]["title"], "三國志測試")
        self.assertEqual(entity["suggestion"]["decision"], "uncertain")
        self.assertEqual(entity["suggestion"]["confidence"], 0.5)
        self.assertEqual(entity["decision"], None)

        status, payload = self._json("GET", f"{STUDIO_REVIEWS_PREFIX}/{entity['review_id']}")
        self.assertEqual(status, 200, payload)
        detail = payload["review"]
        self.assertEqual(detail["left_context"]["source_title"], "武帝紀")
        self.assertEqual(detail["left_context"]["record"]["name"], "曹操")
        self.assertEqual(detail["right_context"]["source_title"], "新校本")
        self.assertEqual(detail["job_open_resolution_reviews"], 2)

    def test_decision_uses_exact_vocabulary_and_preserves_suggestion(self) -> None:
        entity_id = str(self.review_ids[0])
        status, payload = self._json(
            "POST",
            f"{STUDIO_REVIEWS_PREFIX}/{entity_id}/decision",
            {"decision": "same_occurrence", "rationale": "wrong vocabulary", "confidence": 0.9},
        )
        self.assertEqual(status, 400, payload)
        status, payload = self._json(
            "POST",
            f"{STUDIO_REVIEWS_PREFIX}/{entity_id}/decision",
            {"decision": "same_entity", "rationale": "同名同職且來源脈絡一致", "confidence": 0.9},
        )
        self.assertEqual(status, 200, payload)
        review = payload["review"]
        self.assertEqual(review["status"], "resolved")
        self.assertEqual(review["suggestion"]["decision"], "uncertain")
        self.assertEqual(review["decision"]["decision"], "same_entity")
        self.assertEqual(review["decision"]["rationale"], "同名同職且來源脈絡一致")
        self.assertEqual(review["job_open_resolution_reviews"], 1)

        status, payload = self._json("GET", f"{STUDIO_REVIEWS_PREFIX}?status=resolved")
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["reviews"]), 1)
        self.assertEqual(payload["reviews"][0]["decision"]["decision"], "same_entity")

    def test_uncertain_is_first_class_and_resume_is_server_gated(self) -> None:
        first, second = map(str, self.review_ids)
        self._json(
            "POST", f"{STUDIO_REVIEWS_PREFIX}/{first}/decision",
            {"decision": "uncertain", "rationale": "身份證據仍不足", "confidence": 0.4},
        )
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{self.job_id}/resume")
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "conflict")

        self._json(
            "POST", f"{STUDIO_REVIEWS_PREFIX}/{second}/decision",
            {"decision": "related_occurrence", "rationale": "同一戰役脈絡但記述事件粒度不同", "confidence": 0.7},
        )
        status, payload = self._json("POST", f"{STUDIO_JOBS_PREFIX}/{self.job_id}/resume")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["job"]["status"], "running")

    def test_resolved_review_cannot_be_silently_rewritten(self) -> None:
        review_id = str(self.review_ids[0])
        self._json(
            "POST", f"{STUDIO_REVIEWS_PREFIX}/{review_id}/decision",
            {"decision": "not_same", "rationale": "來源所指人物不同", "confidence": 0.8},
        )
        status, payload = self._json(
            "POST", f"{STUDIO_REVIEWS_PREFIX}/{review_id}/decision",
            {"decision": "same_entity", "rationale": "change mind", "confidence": 0.8},
        )
        self.assertEqual(status, 409, payload)
        status, payload = self._json("GET", f"{STUDIO_REVIEWS_PREFIX}/{review_id}")
        self.assertEqual(payload["review"]["decision"]["decision"], "not_same")


if __name__ == "__main__":
    unittest.main()
