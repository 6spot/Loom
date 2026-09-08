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
        self.assertEqual(payload["schema"], "chronicle.studio-review-page")
        self.assertEqual(payload["version"], "0.2")
        self.assertEqual(len(payload["items"]), 2)
        self.assertIsNone(payload["next_cursor"])
        self.assertEqual(payload["open_count"], 2)
        self.assertIn("observed_at", payload)
        self.assertRegex(payload["plan_fingerprint"], r"^[0-9a-f]{64}$")
        entity = next(item for item in payload["items"] if item["link_kind"] == "entity")
        self.assertEqual(entity["plan_fingerprint"], payload["plan_fingerprint"])
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
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["decision"]["decision"], "same_entity")
        # open_count is the whole-scope open total, independent of the status filter.
        self.assertEqual(payload["open_count"], 1)

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


class StudioReviewsKeysetPaginationTests(StudioReviewsHttpTests):
    """C2-R1-T09: stable keyset queue over 450+ items, shared timestamps."""

    SHARED_CREATED_AT = "2026-02-01T00:00:00+00:00"
    BULK_COUNT = 460

    def _queue_second_job(self) -> uuid.UUID:
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title="資治通鑑測試")
            revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=_sha(uuid.uuid4().hex),
                source_bytes=128,
                source_media_type="text/plain",
                filename="second.txt",
                language="zh-Hant",
                source_label="test edition",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            control_plane.claim_job(conn, worker="review-test", job_id=job_id)
            control_plane.set_job_status(conn, job_id=job_id, status="needs_review")
            conn.commit()
            return job_id

    def _bulk_insert(self, job_ids: list[uuid.UUID]) -> list[str]:
        from psycopg.types.json import Jsonb

        rows = []
        for index in range(self.BULK_COUNT):
            link_kind = "entity" if index % 2 == 0 else "event"
            record_ref = "ent_001" if link_kind == "entity" else "evt_001"
            allowed = (
                ["same_entity", "not_same", "uncertain"]
                if link_kind == "entity"
                else ["same_occurrence", "related_occurrence", "not_same", "uncertain"]
            )
            payload = {
                "scope": "resolution",
                "link_kind": link_kind,
                "candidate_id": f"bulk-{index}",
                "resolution_sha256": _sha(f"bulk-resolution-{index}"),
                "left": {"bundle": "left", "ref": record_ref},
                "right": {"bundle": "right", "ref": record_ref},
                "signals": [],
                "initial_decision": "uncertain",
                "blocking": True,
                "allowed_decisions": allowed,
                "decision": None,
            }
            rows.append(
                (
                    uuid.uuid4(),
                    job_ids[index % len(job_ids)],
                    "stage_gate",
                    payload,
                )
            )
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO chronicle.review_items
                        (review_id, job_id, kind, status, payload, created_at)
                    VALUES (%s, %s, %s, 'open', %s, %s::timestamptz)
                    """,
                    [(rid, job, kind, Jsonb(payload), self.SHARED_CREATED_AT) for rid, job, kind, payload in rows],
                )
            conn.commit()
        return [str(rid) for rid, _, _, _ in rows]

    def _get_page(self, query: str):
        status, payload = self._json("GET", f"{STUDIO_REVIEWS_PREFIX}?{query}" if query else STUDIO_REVIEWS_PREFIX)
        self.assertEqual(status, 200, payload)
        return payload

    def _collect_all(self, query: str, *, initial_cursor: str | None = None) -> tuple[list[dict], dict]:
        from urllib.parse import quote

        items: list[dict] = []
        cursor: str | None = initial_cursor
        last_payload: dict = {}
        for _ in range(100):
            suffix = query
            if cursor:
                glue = "&" if suffix else ""
                suffix = f"{suffix}{glue}cursor={quote(cursor, safe='')}"
            last_payload = self._get_page(suffix)
            items.extend(last_payload["items"])
            cursor = last_payload["next_cursor"]
            if not cursor:
                break
        else:
            self.fail("pagination did not terminate")
        return items, last_payload

    def test_bulk_filter_paginate_and_count(self) -> None:
        second_job = self._queue_second_job()
        bulk_ids = set(self._bulk_insert([self.job_id, second_job]))
        total = self.BULK_COUNT + 2

        items, _ = self._collect_all("status=open&limit=50")
        self.assertEqual(len(items), total)
        self.assertEqual(len({item["review_id"] for item in items}), total)
        keys = [(item["created_at"], item["review_id"]) for item in items]
        self.assertEqual(keys, sorted(keys))

        fingerprints = {item["plan_fingerprint"] for item in items}
        self.assertEqual(len(fingerprints), 1)

        # Per-job scope.
        for job_id, expected_open in ((self.job_id, self.BULK_COUNT // 2 + 2), (second_job, self.BULK_COUNT // 2)):
            scoped, _ = self._collect_all(f"status=open&limit=100&job_id={job_id}")
            self.assertEqual(len(scoped), expected_open)
            self.assertTrue(all(item["job_id"] == str(job_id) for item in scoped))

        # Per-kind scope.
        entities, _ = self._collect_all("status=open&limit=100&link_kind=entity")
        events, _ = self._collect_all("status=open&limit=100&link_kind=event")
        self.assertEqual(len(entities), self.BULK_COUNT // 2 + 1)
        self.assertEqual(len(events), self.BULK_COUNT // 2 + 1)
        self.assertTrue(all(item["link_kind"] == "entity" for item in entities))
        self.assertTrue(all(item["link_kind"] == "event" for item in events))
        self.assertEqual(
            {item["review_id"] for item in entities} | {item["review_id"] for item in events},
            bulk_ids | {str(rid) for rid in self.review_ids},
        )

    def test_continue_cursor_after_resolving_front_page(self) -> None:
        self._bulk_insert([self.job_id])
        first = self._get_page("status=open&limit=50")
        self.assertIsNotNone(first["next_cursor"])
        first_ids = [item["review_id"] for item in first["items"]]

        for review_id in first_ids:
            link_kind = next(item["link_kind"] for item in first["items"] if item["review_id"] == review_id)
            decision = "not_same" if link_kind == "entity" else "related_occurrence"
            status, _ = self._json(
                "POST", f"{STUDIO_REVIEWS_PREFIX}/{review_id}/decision",
                {"decision": decision, "rationale": "批量核對", "confidence": 0.8},
            )
            self.assertEqual(status, 200)

        continued, _ = self._collect_all(
            "status=open&limit=50", initial_cursor=first["next_cursor"]
        )
        continued_ids = {item["review_id"] for item in continued}
        # No still-open item past the cursor is skipped, and no resolved
        # front-page item reappears.
        self.assertEqual(len(continued_ids), len(continued))
        self.assertFalse(continued_ids & set(first_ids))
        fresh, _ = self._collect_all("status=open&limit=100")
        self.assertEqual(continued_ids, {item["review_id"] for item in fresh})
        self.assertEqual(len(fresh), self.BULK_COUNT + 2 - len(first_ids))

    def test_cursor_scope_binding_and_malformed_input_rejected(self) -> None:
        self._bulk_insert([self.job_id])
        first = self._get_page("status=open&limit=10")
        cursor = first["next_cursor"]
        self.assertIsNotNone(cursor)
        from urllib.parse import quote
        encoded = quote(cursor, safe="")

        bad_paths = [
            f"{STUDIO_REVIEWS_PREFIX}?status=resolved&limit=10&cursor={encoded}",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&limit=10&job_id={self.job_id}&cursor={encoded}",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&limit=10&link_kind=entity&cursor={encoded}",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&cursor=not-a-cursor",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&cursor={quote('{{bad json', safe='')}",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&limit=0",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&limit=101",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&offset=0",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&status=resolved",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&job_id=nope",
            f"{STUDIO_REVIEWS_PREFIX}?status=open&link_kind=person",
            f"{STUDIO_REVIEWS_PREFIX}?status=bogus",
        ]
        for path in bad_paths:
            status, payload = self._json("GET", path)
            self.assertEqual(status, 400, path)
            self.assertEqual(payload["error"]["code"], "bad_request")

    def test_late_row_before_cursor_found_on_fresh_read(self) -> None:
        self._bulk_insert([self.job_id])
        first = self._get_page("status=open&limit=50")
        cursor = first["next_cursor"]
        before_count = first["open_count"]
        before_fingerprint = first["plan_fingerprint"]
        self.assertIsNotNone(cursor)

        from psycopg.types.json import Jsonb

        late_id = uuid.uuid4()
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                """
                INSERT INTO chronicle.review_items
                    (review_id, job_id, kind, status, payload, created_at)
                VALUES (%s, %s, 'stage_gate', 'open', %s, %s::timestamptz)
                """,
                (
                    late_id,
                    self.job_id,
                    Jsonb({
                        "scope": "resolution",
                        "link_kind": "entity",
                        "candidate_id": "late-arrival",
                        "resolution_sha256": _sha("late-resolution"),
                        "left": {"bundle": "left", "ref": "ent_001"},
                        "right": {"bundle": "right", "ref": "ent_001"},
                        "signals": [],
                        "initial_decision": "uncertain",
                        "blocking": True,
                        "allowed_decisions": ["same_entity", "not_same", "uncertain"],
                        "decision": None,
                    }),
                    "2020-01-01T00:00:00+00:00",
                ),
            )
            conn.commit()

        # The observed open count moves with reality instead of freezing a total.
        refetched = self._get_page("status=open&limit=50")
        self.assertEqual(refetched["open_count"], before_count + 1)
        self.assertNotEqual(refetched["plan_fingerprint"], before_fingerprint)

        continued, _ = self._collect_all("status=open&limit=100", initial_cursor=cursor)
        self.assertNotIn(str(late_id), {item["review_id"] for item in continued})

        fresh, _ = self._collect_all("status=open&limit=100")
        fresh_ids = [item["review_id"] for item in fresh]
        self.assertIn(str(late_id), fresh_ids)
        # The late row sorts before the old cursor, i.e. at the head.
        self.assertEqual(fresh_ids[0], str(late_id))
        self.assertEqual(len(fresh), before_count + 1)

    def test_fingerprint_stable_across_pages_and_decisions(self) -> None:
        self._bulk_insert([self.job_id])
        first = self._get_page("status=open&limit=50")
        fingerprint = first["plan_fingerprint"]
        seen = {item["review_id"] for item in first["items"]}

        from urllib.parse import quote
        cursor: str | None = first["next_cursor"]
        while cursor:
            page = self._get_page(f"status=open&limit=50&cursor={quote(cursor, safe='')}")
            self.assertEqual(page["plan_fingerprint"], fingerprint)
            seen.update(item["review_id"] for item in page["items"])
            cursor = page["next_cursor"]
        self.assertEqual(len(seen), self.BULK_COUNT + 2)

        # Resolving one item changes status/open_count but not the frozen plan.
        victim = first["items"][0]
        decision = "not_same" if victim["link_kind"] == "entity" else "not_same"
        status, _ = self._json(
            "POST", f"{STUDIO_REVIEWS_PREFIX}/{victim['review_id']}/decision",
            {"decision": decision, "rationale": "指代不同", "confidence": 0.8},
        )
        self.assertEqual(status, 200)
        after = self._get_page("status=open&limit=50")
        self.assertEqual(after["plan_fingerprint"], fingerprint)
        self.assertEqual(after["open_count"], first["open_count"] - 1)


if __name__ == "__main__":
    unittest.main()
