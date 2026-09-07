"""R19: a reviewed incoming component must not bridge two published Entity IDs."""

from __future__ import annotations

import copy
import queue
import sys
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import canonical_store
import control_plane
import resolution_store
import resolve_publish as R
import staged_store
import test_control_plane_postgres as pg
from common import PersistenceConflict, sha256_json
from migrations import apply_migrations
from test_resolve_publish_unit import _bundle, _entity
from test_review_subjects_r16_unit import _catalog, _resolution, _within

CANONICAL_A = "018f0000-0000-7000-8000-000000000001"
CANONICAL_B = "018f0000-0000-7000-8000-000000000002"
INCOMING = "c1rev-16479a9c007b"
R19_REFS = ("ent_000044", "ent_001035", "ent_003022")


def review_fixture(*, a_refs=R19_REFS, b_refs=R19_REFS, within=None) -> dict:
    """Retain R19's wudi/wuzhu/incoming topology with deterministic identities."""
    if within is None:
        within = [
            (R19_REFS[0], R19_REFS[1], "same_entity"),
            (R19_REFS[1], R19_REFS[2], "same_entity"),
        ]
    refs = set(a_refs) | set(b_refs)
    refs.update(ref for left, right, _decision in within for ref in (left, right))
    bundles = {
        "wudi": _bundle("wudi", [_entity("ent_013", "襄阳", "place")], []),
        "wuzhu": _bundle("wuzhu", [_entity("ent_030", "襄阳", "place")], []),
        INCOMING: _bundle(INCOMING, [_entity(ref, "襄阳", "place") for ref in sorted(refs)], []),
    }
    initial = [
        _resolution("wudi", entity_pairs=[("ent_013", ref) for ref in a_refs]),
        _resolution("wuzhu", entity_pairs=[("ent_030", ref) for ref in b_refs]),
    ]
    for artifact in initial:
        artifact["right_bundle"]["label"] = INCOMING
        artifact["right_bundle"]["source_title"] = INCOMING
        for link in artifact["entity_links"]:
            link["right"]["bundle"] = INCOMING
    return {
        "bundles": bundles,
        "initial": initial,
        "within_book_links": _within(entity_links=within),
        "catalog": _catalog(entity_groups=[
            (CANONICAL_A, [("wudi", "ent_013")]),
            (CANONICAL_B, [("wuzhu", "ent_030")]),
        ]),
    }


def seed_reviews(conn, fixture: dict) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    apply_migrations(conn)
    document = control_plane.create_document(conn, title="R19 deterministic review regression")
    revision, _ = control_plane.create_revision(
        conn, document_id=document, source_sha256=sha256_json(fixture),
        source_bytes=128, source_media_type="text/plain",
    )
    job = control_plane.queue_job(conn, revision_id=revision)
    control_plane.claim_job(conn, worker="r19-regression", job_id=job)
    control_plane.set_job_status(conn, job_id=job, status="needs_review")
    for label, bundle in fixture["bundles"].items():
        staged_store.persist_bundle(conn, label, bundle)
    canonical_store.persist_catalog(conn, fixture["catalog"])
    assembly = {
        "bundle": fixture["bundles"][INCOMING],
        "within_book_links": fixture["within_book_links"],
    }
    control_plane.record_output(
        conn, job_id=job, revision_id=revision,
        artifact_type="assembled-source-bundle", artifact_sha256=sha256_json(assembly),
        payload=assembly,
    )
    for artifact in fixture["initial"]:
        artifact_sha, _ = resolution_store.persist_resolution(conn, artifact)
        control_plane.record_output(
            conn, job_id=job, revision_id=revision,
            artifact_type=R.RESOLUTION_ARTIFACT_TYPE, artifact_sha256=artifact_sha,
            payload={"role": "initial", "resolution_sha256": artifact_sha},
        )
    R.open_resolution_reviews(conn, job_id=job, resolutions=fixture["initial"])
    rows = conn.execute(
        "SELECT review_id, payload FROM chronicle.review_items WHERE job_id = %s",
        (job,),
    ).fetchall()
    return job, {payload["left_subject"]["canonical_id"]: review_id for review_id, payload in rows}


class EntityReviewConflictPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = pg._control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_r19_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = pg._database_conninfo(self.control_url, self.database_name)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name)))

    def _decide(self, review_id, decision="same_entity", **kwargs) -> None:
        with psycopg.connect(self.database_url) as conn:
            R.resolve_resolution_review(
                conn, review_id=review_id, decision=decision,
                rationale="逐字证据已人工核对", confidence=0.9, **kwargs,
            )

    def _snapshot(self) -> dict:
        with psycopg.connect(self.database_url) as conn:
            return {
                table: conn.execute(f"SELECT * FROM chronicle.{table} ORDER BY 1").fetchall()
                for table in (
                    "review_items", "ingestion_jobs", "resolution_artifacts", "resolution_entity_links",
                    "ingestion_outputs", "canonical_catalogs", "canonical_entity_representations",
                )
            }

    def test_r19_second_same_entity_is_rejected_without_any_writes(self) -> None:
        fixture = review_fixture()
        with psycopg.connect(self.database_url) as conn:
            job, reviews = seed_reviews(conn, fixture)
        self._decide(reviews[CANONICAL_A])
        before = copy.deepcopy(self._snapshot())
        with self.assertRaises(R.CanonicalIdentityConflict):
            self._decide(reviews[CANONICAL_B])
        self.assertEqual(self._snapshot(), before)
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(R.open_resolution_review_count(conn, job_id=job), 1)
            decisions = R.collect_review_decisions(conn, job_id=job)
            self.assertEqual(len(decisions), len(R19_REFS))
            self.assertTrue(all(item["decision"] == "same_entity" for item in decisions.values()))

    def _assert_corrected_decision_publishes(self, decision: str) -> None:
        fixture = review_fixture()
        with psycopg.connect(self.database_url) as conn:
            job, reviews = seed_reviews(conn, fixture)
        self._decide(reviews[CANONICAL_A])
        with self.assertRaises(R.CanonicalIdentityConflict):
            self._decide(reviews[CANONICAL_B])
        self._decide(reviews[CANONICAL_B], decision)
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(R.open_resolution_review_count(conn, job_id=job), 0)
            final = R.build_final_resolutions(
                fixture["initial"], R.collect_review_decisions(conn, job_id=job),
            )
            catalog, _ = R.publish_with_decisions(
                bundles=fixture["bundles"], resolutions=final,
                existing_catalog=fixture["catalog"],
            )
            canonical_store.persist_catalog(conn, catalog)
        membership = {
            (rep["bundle"], rep["ref"]): entity["canonical_id"]
            for entity in catalog["canonical_entities"] for rep in entity["representations"]
        }
        self.assertEqual(set(membership.values()), {CANONICAL_A, CANONICAL_B})
        self.assertEqual(membership[("wuzhu", "ent_030")], CANONICAL_B)
        for ref in R19_REFS:
            self.assertEqual(membership[(INCOMING, ref)], CANONICAL_A)

    def test_not_same_after_rejection_preserves_ids_and_allows_publication(self) -> None:
        self._assert_corrected_decision_publishes("not_same")

    def test_uncertain_after_rejection_preserves_ids_and_allows_publication(self) -> None:
        self._assert_corrected_decision_publishes("uncertain")

    def test_group_override_validation_and_persistence_are_atomic(self) -> None:
        fixture = review_fixture(a_refs=("ent_x",), b_refs=("ent_x", "ent_y"), within=[])
        with psycopg.connect(self.database_url) as conn:
            job, reviews = seed_reviews(conn, fixture)
            payload = conn.execute(
                "SELECT payload FROM chronicle.review_items WHERE review_id = %s",
                (reviews[CANONICAL_B],),
            ).fetchone()[0]
        group = next(group for group in payload["groups"] if group["component_root"] == "ent_x")
        self._decide(reviews[CANONICAL_A])
        before = self._snapshot()
        override = {
            "review_group_id": group["review_group_id"], "decision": "same_entity",
            "rationale": "此组例外仍须检查全局图", "confidence": 0.9,
        }
        with self.assertRaises(R.CanonicalIdentityConflict) as caught:
            self._decide(reviews[CANONICAL_B], "uncertain", group_decisions=[override])
        self.assertEqual(caught.exception.details["review_group_ids"], [group["review_group_id"]])
        self.assertEqual(self._snapshot(), before)
        override["decision"] = "not_same"
        self._decide(reviews[CANONICAL_B], group_decisions=[override])
        with psycopg.connect(self.database_url) as conn:
            final = R.build_final_resolutions(
                fixture["initial"], R.collect_review_decisions(conn, job_id=job),
            )
        catalog, _ = R.publish_with_decisions(
            bundles=fixture["bundles"], resolutions=final, existing_catalog=fixture["catalog"],
        )
        membership = {
            (rep["bundle"], rep["ref"]): entity["canonical_id"]
            for entity in catalog["canonical_entities"] for rep in entity["representations"]
        }
        self.assertEqual(membership[(INCOMING, "ent_x")], CANONICAL_A)
        self.assertEqual(membership[(INCOMING, "ent_y")], CANONICAL_B)

    def test_failed_status_transition_rolls_back_the_decision_payload(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            _, reviews = seed_reviews(conn, review_fixture())
        before = self._snapshot()
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            with patch.object(control_plane, "resolve_review_item", side_effect=PersistenceConflict("transition failed")):
                with self.assertRaisesRegex(PersistenceConflict, "transition failed"):
                    R.resolve_resolution_review(
                        conn, review_id=reviews[CANONICAL_A], decision="same_entity",
                        rationale="核对来源证据", confidence=0.9,
                    )
        self.assertEqual(self._snapshot(), before)

    def test_concurrent_reviews_serialize_before_reading_the_effective_graph(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            job, reviews = seed_reviews(conn, review_fixture())
        second_pid: queue.Queue[int] = queue.Queue()

        def submit_second() -> None:
            with psycopg.connect(self.database_url) as conn:
                conn.execute("SET LOCAL statement_timeout = '10s'")
                second_pid.put(conn.info.backend_pid)
                R.resolve_resolution_review(
                    conn, review_id=reviews[CANONICAL_B], decision="same_entity",
                    rationale="第二个并发判断", confidence=0.9,
                )

        blocked_by_first = False
        with ThreadPoolExecutor(max_workers=1) as pool:
            with psycopg.connect(self.database_url) as first:
                with first.transaction():
                    R.resolve_resolution_review(
                        first, review_id=reviews[CANONICAL_A], decision="same_entity",
                        rationale="第一个尚未提交的判断", confidence=0.9,
                    )
                    second = pool.submit(submit_second)
                    pid = second_pid.get(timeout=5)
                    with psycopg.connect(self.database_url, autocommit=True) as observer:
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline and not second.done():
                            blockers = observer.execute("SELECT pg_blocking_pids(%s)", (pid,)).fetchone()[0]
                            if first.info.backend_pid in blockers:
                                blocked_by_first = True
                                break
                            time.sleep(0.01)
            with self.assertRaises(R.CanonicalIdentityConflict):
                second.result(timeout=10)
        self.assertTrue(blocked_by_first, "second submission must wait for the job's first decision")
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(R.open_resolution_review_count(conn, job_id=job), 1)

    def test_r19_publisher_remains_the_final_fail_closed_guard(self) -> None:
        fixture = review_fixture()
        final = copy.deepcopy(fixture["initial"])
        for artifact in final:
            for link in artifact["entity_links"]:
                link["decision"] = "same_entity"
        with self.assertRaisesRegex(R.publication_v0.PublicationConflict, "collapse existing canonical IDs"):
            R.publish_with_decisions(
                bundles=fixture["bundles"], resolutions=final, existing_catalog=fixture["catalog"],
            )


if __name__ == "__main__":
    unittest.main()
