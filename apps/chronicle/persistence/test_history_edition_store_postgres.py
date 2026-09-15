"""Focused PostgreSQL coverage for the immutable history-edition frontier."""

from __future__ import annotations

import sys
import types
import uuid
import unittest
import json
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from migrations import apply_migrations
from history_edition_contract import contract_fixture
import history_edition_store as store

# The focused persistence suite does not need the optional OpenCC package;
# provide the tiny presentation symbol required by read_common so the public
# history router can be exercised in this minimal worker environment.
reader_language = types.ModuleType("reader_language")
reader_language.simplified = lambda value: value
sys.modules.setdefault("reader_language", reader_language)
if str(HERE.parent / "read_api") not in sys.path:
    sys.path.insert(0, str(HERE.parent / "read_api"))
import history
from read_common import ReadModelNotFound
import control_plane
import studio_jobs
import resolve_publish
import studio_reviews

from test_postgres_v0 import _control_url


class HistoryEditionStorePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_history_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        params = conninfo_to_dict(self.control_url)
        params["dbname"] = self.database_name
        self.database_url = make_conninfo(**params)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name)))

    def _connect(self):
        conn = psycopg.connect(self.database_url)
        apply_migrations(conn)
        return conn

    def test_publish_pages_and_keeps_old_edition_after_append(self) -> None:
        first_fixture = contract_fixture(paragraphs_per_fragment=2, fragment_count=2)
        full_fixture = contract_fixture(paragraphs_per_fragment=2, fragment_count=3)
        with self._connect() as conn:
            first_draft = store.create_draft(
                conn,
                fragments=first_fixture["fragments"],
                boundary_reviews=first_fixture["boundary_reviews"],
                navigation=first_fixture["navigation"],
            )
            first = store.publish_draft(conn, first_draft["draft_id"])
            self.assertEqual(4, first["paragraph_count"])

            second_draft = store.create_draft(
                conn,
                fragments=full_fixture["fragments"],
                boundary_reviews=full_fixture["boundary_reviews"],
                navigation=full_fixture["navigation"],
                baseline_manifest_sha256=first["version"],
                operation="append",
            )
            second = store.publish_draft(conn, second_draft["draft_id"])
            self.assertEqual(6, second["paragraph_count"])
            self.assertNotEqual(first["version"], second["version"])

            old_page = store.read_paragraph_page(
                conn, version=first["version"], start=0, limit=2
            )
            new_page = store.read_paragraph_page(
                conn, version=second["version"], start=4, limit=2
            )
            self.assertEqual(4, old_page["total"])
            self.assertEqual(6, new_page["total"])
            self.assertEqual(2, len(new_page["paragraphs"]))
            self.assertEqual(
                [4, 5], [item["ordinal"] for item in new_page["paragraphs"]]
            )
            conclusion_id = new_page["paragraphs"][0]["conclusion_ids"][0]
            conclusion = store.read_conclusion(
                conn, version=second["version"], conclusion_id=conclusion_id
            )
            self.assertEqual(conclusion_id, conclusion["conclusion"]["id"])

            latest = store.read_latest_metadata(conn)
            self.assertEqual(second["version"], latest["version"])
            self.assertEqual(
                latest["first_paragraph_id"],
                store.read_paragraph_page(
                    conn, version=second["version"], start=0, limit=1
                )["paragraphs"][0]["id"],
            )
            self.assertEqual(
                second["paragraph_count"],
                sum(group["count"] for group in latest["groups"]),
            )
            self.assertEqual(latest["first_paragraph_id"], latest["navigation"][0]["id"])
            self.assertEqual(second["paragraph_count"] - 1, latest["navigation"][-1]["end"])
            self.assertTrue(all("ordinal" in entry and "excerpt" in entry for entry in latest["entry_points"]))
            directory = history.dispatch_history(conn, "/v0/history", "")
            self.assertEqual(second["version"], directory["edition"]["version"])
            self.assertEqual(latest["navigation"], directory["edition"]["navigation"])
            api_page = history.dispatch_history(
                conn,
                "/v0/history/paragraphs",
                f"version={second['version']}&start=4&limit=2",
            )
            self.assertEqual([4, 5], [item["ordinal"] for item in api_page["paragraphs"]])
            with self.assertRaises(ReadModelNotFound):
                history.dispatch_history(
                    conn,
                    "/v0/history/paragraphs",
                    "version=" + "0" * 64,
                )

    def test_pending_seam_and_stale_baseline_leave_public_frontier_unchanged(self) -> None:
        fixture = contract_fixture(paragraphs_per_fragment=2, fragment_count=2)
        with self._connect() as conn:
            pending = store.create_draft(conn, fragments=fixture["fragments"])
            with self.assertRaises(Exception) as error:
                store.publish_draft(conn, pending["draft_id"])
            self.assertIn("boundary_review", str(error.exception))
            self.assertIsNone(store.read_latest_metadata(conn))

            accepted = store.create_draft(
                conn,
                fragments=fixture["fragments"],
                boundary_reviews=fixture["boundary_reviews"],
                navigation=fixture["navigation"],
            )
            first = store.publish_draft(conn, accepted["draft_id"])
            stale = store.create_draft(
                conn,
                fragments=fixture["fragments"],
                boundary_reviews=fixture["boundary_reviews"],
                navigation=fixture["navigation"],
                baseline_manifest_sha256=first["version"],
            )
            # A second valid edition moves the pointer before the stale draft
            # publishes.  The stale draft must remain a draft and expose no
            # half-written index rows.
            other = contract_fixture(paragraphs_per_fragment=2, fragment_count=1)
            other_draft = store.create_draft(
                conn,
                fragments=other["fragments"],
                boundary_reviews=[],
                navigation=other["navigation"],
            )
            store.publish_draft(conn, other_draft["draft_id"])
            with self.assertRaises(Exception) as error:
                store.publish_draft(conn, stale["draft_id"])
            self.assertIn("baseline_changed", str(error.exception))
            self.assertEqual("draft", store.read_draft(conn, stale["draft_id"])["status"])

    def test_studio_routes_create_and_publish_an_edition_without_a_new_queue(self) -> None:
        fixture = contract_fixture(paragraphs_per_fragment=2, fragment_count=1)
        with self._connect() as conn:
            status, _content_type, raw = studio_jobs.dispatch_jobs(
                conn,
                control_plane,
                method="POST",
                path="/api/v1/studio/jobs/history/editions",
                body=json.dumps({
                    "fragments": fixture["fragments"],
                    "navigation": fixture["navigation"],
                }).encode(),
            )
            self.assertEqual(201, status, raw)
            draft = json.loads(raw)["draft"]
            self.assertEqual("draft", draft["status"])
            status, _content_type, raw = studio_jobs.dispatch_jobs(
                conn,
                control_plane,
                method="POST",
                path=f"/api/v1/studio/jobs/history/editions/{draft['draft_id']}/publish",
                body=b"{}",
            )
            self.assertEqual(200, status, raw)
            edition = json.loads(raw)["edition"]
            self.assertEqual(1, edition["fragment_count"])

    def test_job_bound_seam_review_and_publish_require_the_existing_lease(self) -> None:
        fixture = contract_fixture(paragraphs_per_fragment=2, fragment_count=2)
        worker = "history-edition-test-worker"
        with self._connect() as conn:
            document_id = control_plane.create_document(conn, title="history edition test")
            revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256="a" * 64,
                source_bytes=1,
                source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            control_plane.claim_job(conn, worker=worker, job_id=job_id, lease_seconds=30)
            draft = store.create_draft(
                conn,
                fragments=fixture["fragments"],
                navigation=fixture["navigation"],
                job_id=job_id,
            )
            review_id = draft["boundary_reviews"][0]["review_id"]
            status, _content_type, raw = studio_reviews.dispatch_reviews(
                conn,
                resolve_publish,
                method="GET",
                path="/api/v1/studio/jobs/reviews",
                raw_query="review_scope=history_edition",
            )
            self.assertEqual(200, status, raw)
            self.assertEqual(review_id, json.loads(raw)["items"][0]["review_id"])
            status, _content_type, raw = studio_reviews.dispatch_reviews(
                conn,
                resolve_publish,
                method="GET",
                path=f"/api/v1/studio/jobs/reviews/{review_id}",
            )
            self.assertEqual(200, status, raw)
            self.assertEqual(
                "history_edition", json.loads(raw)["review"]["scope"]
            )
            status, _content_type, raw = studio_reviews.dispatch_reviews(
                conn,
                resolve_publish,
                method="POST",
                path=f"/api/v1/studio/jobs/reviews/{review_id}/decision",
                body=json.dumps({
                    "decision": "accept",
                    "rationale": "两侧边界按资料范围连续。",
                    "review_basis": fixture["boundary_reviews"][0]["review_basis"],
                }).encode(),
            )
            self.assertEqual(200, status, raw)
            edition = store.publish_draft(
                conn, draft["draft_id"], job_id=job_id, worker=worker
            )
            self.assertEqual(2, edition["fragment_count"])

    def test_bounded_pages_cross_three_fragments_without_duplicate_global_ids(self) -> None:
        fixture = contract_fixture(paragraphs_per_fragment=128, fragment_count=3)
        with self._connect() as conn:
            draft = store.create_draft(
                conn,
                fragments=fixture["fragments"],
                boundary_reviews=fixture["boundary_reviews"],
                navigation=fixture["navigation"],
            )
            edition = store.publish_draft(conn, draft["draft_id"])
            observed = []
            start = 0
            while start < edition["paragraph_count"]:
                page = store.read_paragraph_page(
                    conn, version=edition["version"], start=start, limit=50
                )
                observed.extend(page["paragraphs"])
                if page["next_start"] is None:
                    break
                start = page["next_start"]
            self.assertEqual(384, len(observed))
            self.assertEqual(list(range(384)), [item["ordinal"] for item in observed])
            self.assertEqual(384, len({item["id"] for item in observed}))
            self.assertEqual(
                {"fixture-fragment-001", "fixture-fragment-002", "fixture-fragment-003"},
                {item["fragment_version"] for item in observed},
            )


if __name__ == "__main__":
    unittest.main()
