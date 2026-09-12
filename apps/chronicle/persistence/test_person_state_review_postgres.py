"""PostgreSQL 18 integration tests for the C2-R3-T06 person-state review core.

Covers the durable half of ``person-state-reading.md`` section 5:

- one ``stage_gate`` ReviewItem per chapter package is opened once and adopted
  on resume instead of duplicating review debt;
- a decision is committed atomically with the terminal review status; repeated
  submission, plan drift, unknown candidates and missing premises fail with a
  concrete conflict and change nothing;
- dismissed packages only ever contribute ``uncertain``;
- collection refuses an open package, fans decisions back once and persists the
  immutable assessment artifact through T05 without touching canonical links;
- a concurrent resolve yields exactly one winner and one 409-style conflict.

Fixtures seed a real control-plane job and a real canonical catalog; that seed
path is an explicit test loading path, not a second production success path.
"""

from __future__ import annotations

import sys
import threading
import unittest
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import canonical_store  # noqa: E402
import control_plane  # noqa: E402
import person_state_contract as contract  # noqa: E402
import person_state_review as review  # noqa: E402
from common import PersistenceConflict, PersistenceError, sha256_json  # noqa: E402
from migrations import apply_migrations  # noqa: E402

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

CHAPTER = "ch_000000000000000000000001"
REVISION_SHA = "a" * 64
NORM = "b" * 64


def _sha256(text: str) -> str:
    return sha256_json(text)


def _uuid7() -> str:
    n = uuid.uuid4().int
    value = (0x019535D93DF7 << 80) | (0x7 << 76) | (n & 0xFFFFFFFFFFFF)
    return str(uuid.UUID(int=value))


def _control_url() -> str:
    import os
    import subprocess

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


def _artifact(revision_id: str) -> dict:
    candidates = []

    def add(kind: str, item_ref: str, phase_ids: list[str], fact_refs: list[str]) -> None:
        anchor = "anc_" + f"{len(candidates):016x}"
        candidates.append(
            {
                "candidate_key": contract.candidate_key_for(
                    kind=kind, chapter_id=CHAPTER, item_ref=item_ref, anchor_ids=[anchor]
                ),
                "kind": kind,
                "item_ref": item_ref,
                "phase_ids": list(phase_ids),
                "anchor_ids": [anchor],
                "source_fact_refs": list(fact_refs),
            }
        )

    person_states = {
        "phases": [
            {"phase_id": "ph_001", "label": "初", "event_refs": [], "source_selections": []},
            {"phase_id": "ph_002", "label": "後", "event_refs": [], "source_selections": []},
        ],
        "phase_orders": [
            {
                "assertion_id": "po_001",
                "earlier_phase_ref": "ph_001",
                "later_phase_ref": "ph_002",
                "source_selections": [],
            }
        ],
        "unit_phases": [
            {
                "block_id": "t_001",
                "mode": "single",
                "phase_refs": ["ph_001"],
                "source_selections": [],
            }
        ],
        "facts": [
            {
                "fact_id": "pf_001",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_002"},
                "relation": None,
                "target_ref": None,
                "operation": "start",
                "qualification": "ordinary",
                "phase_ref": "ph_001",
                "claim_refs": [],
                "source_selections": [],
                "attribution": "narrator",
            },
            {
                "fact_id": "pf_002",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_002"},
                "relation": None,
                "target_ref": None,
                "operation": "end",
                "qualification": "ordinary",
                "phase_ref": "ph_002",
                "claim_refs": [],
                "source_selections": [],
                "attribution": "narrator",
            },
        ],
        "continuities": [
            {
                "assertion_id": "pc_001",
                "fact_ref": "pf_001",
                "start_phase_ref": "ph_001",
                "end_phase_ref": None,
                "source_selections": [],
            }
        ],
        "disagreements": [
            {
                "assertion_id": "pd_001",
                "topic": "任職_月份",
                "fact_refs": ["pf_001", "pf_002"],
                "phase_refs": ["ph_001", "ph_002"],
                "source_selections": [],
            }
        ],
    }
    add("phase", "ph_001", ["ph_001"], [])
    add("phase", "ph_002", ["ph_002"], [])
    add("phase_order", "po_001", ["ph_001", "ph_002"], [])
    add("unit_phase", "t_001", ["ph_001"], [])
    add("fact", "pf_001", ["ph_001"], ["pf_001"])
    add("fact", "pf_002", ["ph_002"], ["pf_002"])
    add("continuity", "pc_001", ["ph_001"], ["pf_001"])
    add("disagreement", "pd_001", ["ph_001", "ph_002"], ["pf_001", "pf_002"])
    core = {
        "schema": "chronicle.chapter-artifact",
        "version": "0.3",
        "chapter_id": CHAPTER,
        "revision_id": revision_id,
        "source_sha256": REVISION_SHA,
        "normalized_sha256": NORM,
        "candidate": {"schema": "chronicle.chapter-candidate", "version": "0.3"},
        "candidate_sha256": _sha256("candidate"),
        "anchors": [],
        "request_fingerprint": "fp-1",
        "producing_run": {"run_id": "run-1", "model": "m", "prompt_schema_version": "0.3"},
        "reading": {},
        "reading_sha256": _sha256("reading"),
        "person_states": person_states,
        "person_states_sha256": sha256_json(person_states),
        "person_state_candidates": candidates,
    }
    artifact = dict(core)
    artifact["artifact_sha256"] = sha256_json(core)
    return artifact


def _assembly() -> dict:
    items = [
        {"kind": "phase", "origin_ref": "ph_001", "revision_ref": "ph_000001"},
        {"kind": "phase", "origin_ref": "ph_002", "revision_ref": "ph_000002"},
        {"kind": "phase_order", "origin_ref": "po_001", "revision_ref": "po_000001"},
        {"kind": "unit_phase", "origin_ref": "t_001", "revision_ref": "t_000001"},
        {"kind": "fact", "origin_ref": "pf_001", "revision_ref": "pf_000001"},
        {"kind": "fact", "origin_ref": "pf_002", "revision_ref": "pf_000002"},
        {"kind": "continuity", "origin_ref": "pc_001", "revision_ref": "pc_000001"},
        {"kind": "disagreement", "origin_ref": "pd_001", "revision_ref": "pd_000001"},
    ]
    person_states = {"facts": []}
    return {
        "person_states": person_states,
        "evidence_manifests": [{"chapter_id": CHAPTER, "items": items}],
        "report": {"person_states_sha256": sha256_json(person_states)},
    }


class PersonStateReviewPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t06_review_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self.conn = psycopg.connect(self.database_url)
        apply_migrations(self.conn)
        self.revision_id = _uuid7()
        self.catalog_sha = self._seed_catalog()
        # ``canonical_store.persist_catalog`` relies on the caller's transaction;
        # commit the seed before control-plane writes so every connection sees it.
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _seed_catalog(self) -> str:
        catalog = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "tag": "t06",
            "canonical_entities": [],
            "canonical_events": [],
            "event_relations": [],
            "warnings": [],
        }
        catalog_sha, _ = canonical_store.persist_catalog(self.conn, catalog)
        return catalog_sha

    def _seed_job(self) -> uuid.UUID:
        document_id = control_plane.create_document(self.conn, title="周瑜傳")
        revision_id, _ = control_plane.create_revision(
            self.conn,
            document_id=document_id,
            source_sha256=REVISION_SHA,
            source_bytes=10,
            source_media_type="text/markdown",
        )
        return control_plane.queue_job(self.conn, revision_id=revision_id)

    def _plan(self, job_id: uuid.UUID, *, resolution_hashes=None) -> dict:
        return review.build_person_state_review_plan(
            job_id=job_id,
            revision_id=self.revision_id,
            accepted_artifacts=[_artifact(self.revision_id)],
            assembly=_assembly(),
            resolution_hashes=resolution_hashes or ["d" * 64],
            base_catalog_sha=self.catalog_sha,
        )

    def _all_supported(self, package: dict) -> dict:
        return {
            "default_assessment": "supported",
            "rationale": "整章逐项核对原文后确认。",
            "overrides": [
                {
                    "candidate_id": candidate["candidate_key"],
                    "assessment": "supported",
                    "rationale": "直接原文支持。",
                }
                for candidate in package["candidates"]
            ],
        }

    # -- open / adopt ------------------------------------------------------

    def test_open_creates_one_item_per_chapter_and_resume_adopts(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        first = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        self.assertEqual(len(first), 1)
        second = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        self.assertEqual(second, first)
        rows = self.conn.execute(
            "SELECT status, payload FROM chronicle.review_items WHERE job_id = %s", (job_id,)
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "open")
        self.assertEqual(rows[0][1]["scope"], review.REVIEW_SCOPE)
        self.assertEqual(rows[0][1]["review_mode"], review.REVIEW_MODE)
        self.assertEqual(rows[0][1]["candidate_count"], 8)

    def test_concurrent_open_creates_exactly_one_package(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        barrier = threading.Barrier(2)
        results: list[list[str]] = []
        errors: list[str] = []

        def attempt() -> None:
            conn = psycopg.connect(self.database_url)
            try:
                barrier.wait(timeout=10)
                ids = review.open_person_state_reviews(conn, job_id=job_id, plan=plan)
                results.append([str(review_id) for review_id in ids])
            except Exception as exc:  # noqa: BLE001 - surface any failure
                errors.append(repr(exc))
            finally:
                conn.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(results[0]), 1)
        count = self.conn.execute(
            "SELECT count(*) FROM chronicle.review_items WHERE job_id = %s", (job_id,)
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_open_rejects_a_drifted_plan(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        drifted = self._plan(job_id, resolution_hashes=["e" * 64])
        with self.assertRaises(PersistenceConflict):
            review.open_person_state_reviews(self.conn, job_id=job_id, plan=drifted)

    # -- resolve -----------------------------------------------------------

    def test_resolve_commits_decision_and_terminal_status(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        package = plan["packages"][0]
        record = review.resolve_person_state_review(
            self.conn,
            job_id=job_id,
            review_id=review_id,
            plan=plan,
            decision=self._all_supported(package),
        )
        self.assertEqual(record["default_assessment"], "supported")
        status, payload = self.conn.execute(
            "SELECT status, payload FROM chronicle.review_items WHERE review_id = %s",
            (review_id,),
        ).fetchone()
        self.assertEqual(status, "resolved")
        self.assertEqual(payload["decision"]["default_assessment"], "supported")
        self.assertEqual(len(payload["decision"]["decisions"]), 8)

    def test_duplicate_submission_is_conflict(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        package = plan["packages"][0]
        review.resolve_person_state_review(
            self.conn,
            job_id=job_id,
            review_id=review_id,
            plan=plan,
            decision=self._all_supported(package),
        )
        with self.assertRaises(PersistenceConflict):
            review.resolve_person_state_review(
                self.conn,
                job_id=job_id,
                review_id=review_id,
                plan=plan,
                decision=self._all_supported(package),
            )

    def test_unknown_candidate_leaves_review_open(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        with self.assertRaises(PersistenceError):
            review.resolve_person_state_review(
                self.conn,
                job_id=job_id,
                review_id=review_id,
                plan=plan,
                decision={
                    "default_assessment": "uncertain",
                    "overrides": [
                        {"candidate_id": "psc_unknown", "assessment": "supported", "rationale": "x"}
                    ],
                },
            )
        status = self.conn.execute(
            "SELECT status FROM chronicle.review_items WHERE review_id = %s", (review_id,)
        ).fetchone()[0]
        self.assertEqual(status, "open")

    def test_plan_drift_is_conflict(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        drifted = self._plan(job_id, resolution_hashes=["e" * 64])
        with self.assertRaises(PersistenceConflict):
            review.resolve_person_state_review(
                self.conn,
                job_id=job_id,
                review_id=review_id,
                plan=drifted,
                decision=self._all_supported(plan["packages"][0]),
            )
        status = self.conn.execute(
            "SELECT status FROM chronicle.review_items WHERE review_id = %s", (review_id,)
        ).fetchone()[0]
        self.assertEqual(status, "open")

    def test_concurrent_resolve_has_one_winner(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        decision = self._all_supported(plan["packages"][0])
        results: list[Any] = []

        def attempt() -> None:
            conn = psycopg.connect(self.database_url)
            try:
                review.resolve_person_state_review(
                    conn, job_id=job_id, review_id=review_id, plan=plan, decision=decision
                )
                results.append("resolved")
            except PersistenceConflict:
                results.append("conflict")
            finally:
                conn.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ["conflict", "resolved"])

    # -- collect -----------------------------------------------------------

    def test_collect_refuses_an_open_package(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        with self.assertRaises(PersistenceConflict):
            review.collect_person_state_assessments(self.conn, job_id=job_id, plan=plan)

    def test_collect_persists_immutable_assessment(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        review.resolve_person_state_review(
            self.conn,
            job_id=job_id,
            review_id=review_id,
            plan=plan,
            decision=self._all_supported(plan["packages"][0]),
        )
        result = review.collect_person_state_assessments(self.conn, job_id=job_id, plan=plan)
        self.assertIn("assessment_sha", result)
        self.assertEqual(len(result["assessment_by_candidate"]), 8)
        row = self.conn.execute(
            "SELECT payload FROM chronicle.person_state_assessments WHERE plan_fingerprint = %s",
            (plan["plan_fingerprint"],),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0]["plan_fingerprint"], plan["plan_fingerprint"])
        # The compiler mapping points at the assembled revision refs.
        self.assertEqual(result["compiler_assessments"]["pf_000001"], "supported")
        # No canonical link is created by an assessment.
        count = self.conn.execute(
            "SELECT count(*) FROM chronicle.resolution_entity_links"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_dismissed_package_collects_as_uncertain(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        review.resolve_person_state_review(
            self.conn, job_id=job_id, review_id=review_id, plan=plan, dismiss=True
        )
        status = self.conn.execute(
            "SELECT status FROM chronicle.review_items WHERE review_id = %s", (review_id,)
        ).fetchone()[0]
        self.assertEqual(status, "dismissed")
        result = review.collect_person_state_assessments(self.conn, job_id=job_id, plan=plan)
        self.assertTrue(
            all(value == "uncertain" for value in result["assessment_by_candidate"].values())
        )

    def test_replay_returns_same_assessment_sha(self) -> None:
        job_id = self._seed_job()
        plan = self._plan(job_id)
        (review_id,) = review.open_person_state_reviews(self.conn, job_id=job_id, plan=plan)
        review.resolve_person_state_review(
            self.conn,
            job_id=job_id,
            review_id=review_id,
            plan=plan,
            decision=self._all_supported(plan["packages"][0]),
        )
        first = review.collect_person_state_assessments(self.conn, job_id=job_id, plan=plan)
        second = review.collect_person_state_assessments(self.conn, job_id=job_id, plan=plan)
        self.assertEqual(first["assessment_sha"], second["assessment_sha"])


if __name__ == "__main__":
    unittest.main()
