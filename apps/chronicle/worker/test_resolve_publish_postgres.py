"""PostgreSQL 18 integration tests for Chronicle C1-T8 review/publication.

Proves the durable resolve -> human review -> resume -> publish path
against a real database: a newly assembled source bundle resolves
against the persisted corpus through the existing conservative C0
semantics, ambiguous candidates become durable job-scoped review
items that park the job in ``needs_review``, recorded human decisions
(using the exact C0 vocabulary) resume the same job without
re-running accepted extraction work, accepted same-links reuse stable
canonical UUIDs, ``uncertain``/``not_same``/``related_occurrence``
boundaries hold, publication conflicts fail closed, and every job
output links the exact bundle/resolution/catalog artifacts. A second
test proves a disjoint bundle publishes unattended while non-blocking
uncertainty stays explicit.
"""

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

import assembly as A  # noqa: E402
import canonical_store  # noqa: E402
import control_plane  # noqa: E402
import resolve_publish as R  # noqa: E402
import staged_store  # noqa: E402
from common import PersistenceError, sha256_json  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import ingestion_worker as worker  # noqa: E402

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"
WORKER = "worker-c1t8"


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


def _meta() -> dict:
    return {"method": "model", "job_id": "c1t8-pg", "confidence": 0.8}


def _time(year: int) -> dict:
    return {
        "original_text": f"建安{year - 195}年",
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": year - 195,
            "season": None,
            "month": None,
            "inherited_fields": [],
        },
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": year,
            "month": None,
            "day": None,
            "precision": "year",
            "conversion_status": "year_only",
        },
    }


def _source(title: str) -> dict:
    return {
        "temp_id": "src_001",
        "kind": "source",
        "source_type": "book",
        "title": title,
        "author": "陳壽",
        "language": "lzh",
        "extraction": _meta(),
    }


def _entity(temp_id: str, name: str) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "entity",
        "type": "person",
        "canonical_name": name,
        "aliases": [],
        "mentions": [{"text": name}],
        "resolution": {"status": "unresolved"},
        "extraction": _meta(),
    }


def _event(temp_id: str, title: str, participant: str, year: int) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "event",
        "type": "death",
        "title": title,
        "time": _time(year),
        "participants": [{"entity_ref": participant, "role": "subject"}],
        "places": [],
        "extraction": _meta(),
    }


def _claim(temp_id: str, subject: str, predicate: str, text: str) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "claim",
        "subject": {"kind": "entity_ref", "ref": subject},
        "predicate": predicate,
        "object": None,
        "time": None,
        "evidence": {
            "text": text,
            "source_ref": "src_001",
            "locator": {"work": "三國志", "section": "全文"},
        },
        "assessment": {"status": "unassessed"},
        "extraction": _meta(),
    }


def _corpus_bundle(title: str, entities: list[dict], events: list[dict]) -> dict:
    return {
        "schema_version": "0.1",
        "source": _source(title),
        "entities": entities,
        "events": events,
        "claims": [],
        "warnings": [],
    }


def _chunk(
    index: int,
    revision_id: str,
    source_sha: str,
    *,
    entities: list[dict],
    events: list[dict],
    claims: list[dict],
    start: int,
    end: int,
) -> dict:
    return {
        "chunk_index": index,
        "candidate": {
            "schema_version": "0.1",
            "source": _source("三國志·魏書新解"),
            "entities": entities,
            "events": events,
            "claims": claims,
            "warnings": [],
        },
        "locator": {
            "job_id": "job-1",
            "revision_id": revision_id,
            "revision_no": 1,
            "source_sha256": source_sha,
            "section_index": 0,
            "section_id": None,
            "chunk_index": index,
            "source_start": start,
            "source_end": end,
            "offset_unit": "chars-normalized-utf8",
            "content_sha256": "b" * 64,
            "overlap_prev_chars": 0,
            "segmentation_version": "c1t5-seg-v1",
        },
        "run_attempt": 1,
        "model_version": "pg-test-model-v1",
    }


class ResolvePublishPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t8_{uuid.uuid4().hex}"
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

    # -- seeding helpers -------------------------------------------------

    def _seed_corpus(self, conn, catalog_resolutions: list[dict] | None = None) -> dict:
        """Persist a two-bundle corpus plus its singleton catalog."""
        wudi = _corpus_bundle(
            "武帝紀",
            [_entity("ent_001", "曹操")],
            [_event("evt_001", "曹操之死", "ent_001", 220)],
        )
        wuzhu = _corpus_bundle("吳主傳", [_entity("ent_001", "孫權")], [])
        staged_store.persist_bundle(conn, "wudi", wudi)
        staged_store.persist_bundle(conn, "wuzhu", wuzhu)
        import publication_v0  # noqa: E402

        catalog = publication_v0.publish_catalog(
            {"wudi": wudi, "wuzhu": wuzhu}, catalog_resolutions or [], None
        )
        canonical_store.persist_catalog(conn, catalog)
        conn.commit()
        return {"wudi": wudi, "wuzhu": wuzhu, "catalog": catalog}

    def _seed_job_with_bundle(
        self, conn, *, chunks: list[dict], title: str = "三國志·魏書新解"
    ) -> tuple[uuid.UUID, uuid.UUID, dict]:
        """Queue/claim a job, complete it through assemble, record the bundle."""
        import hashlib

        source_sha = hashlib.sha256(f"c1t8-{uuid.uuid4().hex}".encode()).hexdigest()
        document_id = control_plane.create_document(conn, title=title)
        revision_id, _ = control_plane.create_revision(
            conn,
            document_id=document_id,
            source_sha256=source_sha,
            source_bytes=128,
            source_media_type="text/plain",
        )
        job_id = control_plane.queue_job(conn, revision_id=revision_id)
        control_plane.claim_job(conn, worker=WORKER, job_id=job_id)
        for stage in ("prepare", "structure", "segment", "extract", "assemble"):
            control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="running")
            control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="completed")
        for chunk in chunks:
            chunk["locator"]["revision_id"] = str(revision_id)
            chunk["locator"]["source_sha256"] = source_sha
        artifact = A.assemble_revision(
            chunks=chunks,
            document={"title": title},
            revision={
                "revision_id": str(revision_id),
                "revision_no": 1,
                "source_sha256": source_sha,
            },
        )
        control_plane.record_output(
            conn,
            job_id=job_id,
            revision_id=revision_id,
            artifact_type=A.ARTIFACT_TYPE,
            artifact_sha256=A.sha256_json(artifact),
            payload=artifact,
        )
        conn.commit()
        return job_id, revision_id, artifact

    def _new_book_chunks(self, revision_id: str, source_sha: str) -> list[dict]:
        return [
            _chunk(
                0, revision_id, source_sha,
                entities=[_entity("ent_001", "曹操")],
                events=[_event("evt_001", "魏武之薨", "ent_001", 220)],
                claims=[_claim("clm_001", "ent_001", "died", "曹操薨")],
                start=0, end=50,
            ),
            _chunk(
                1, revision_id, source_sha,
                entities=[_entity("ent_001", "孫權")],
                events=[],
                claims=[_claim("clm_001", "ent_001", "ruled", "孫權即位")],
                start=50, end=100,
            ),
        ]

    def _reviews(self, conn, job_id: uuid.UUID) -> list[tuple]:
        return conn.execute(
            """
            SELECT review_id, kind, status, payload
            FROM chronicle.review_items WHERE job_id = %s
            ORDER BY created_at, review_id
            """,
            (job_id,),
        ).fetchall()

    # -- the review-gated path -------------------------------------------

    def test_review_resume_publish_reuses_stable_identities(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            corpus = self._seed_corpus(conn)
            seed_cao = next(
                record["canonical_id"]
                for record in corpus["catalog"]["canonical_entities"]
                if record["representations"] == [
                    {"bundle": "wudi", "ref": "ent_001"}
                ]
            )
            job_id, revision_id, artifact = self._seed_job_with_bundle(
                conn,
                chunks=self._new_book_chunks("rev-placeholder", "0" * 64),
            )
            before = control_plane.get_job_detail(conn, job_id=job_id)

        runner = worker.JobRunner(self.database_url, worker=WORKER)
        self.assertEqual(runner.execute_job(job_id), "needs_review")

        with psycopg.connect(self.database_url) as conn:
            detail = control_plane.get_job_detail(conn, job_id=job_id)
            self.assertEqual(detail["status"], "needs_review")
            stages = {stage["stage"]: stage["status"] for stage in detail["stages"]}
            self.assertEqual(stages["resolve"], "needs_review")
            # Extraction/assembly checkpoints are untouched by resolve.
            for stage in ("extract", "assemble"):
                self.assertEqual(stages[stage], "completed")
            rows = self._reviews(conn, job_id)
            self.assertEqual(len(rows), 3)
            for _review_id, kind, status, payload in rows:
                self.assertEqual(kind, "stage_gate")
                self.assertEqual(status, "open")
                self.assertEqual(payload["scope"], "resolution")
                self.assertTrue(payload["blocking"])
                self.assertIn(payload["link_kind"], ("entity", "event"))
                self.assertTrue(payload["left"]["bundle"])
                self.assertTrue(payload["right"]["bundle"])
                self.assertTrue(payload["signals"])
            # Outputs already link the exact bundle + initial artifacts.
            types = [output["artifact_type"] for output in detail["outputs"]]
            self.assertIn("assembled-source-bundle", types)
            self.assertIn(R.BUNDLE_ARTIFACT_TYPE, types)
            self.assertIn(R.RESOLUTION_ARTIFACT_TYPE, types)
            self.assertNotIn(R.CATALOG_ARTIFACT_TYPE, types)

            by_ref = {
                (row[3]["left"]["ref"], row[3]["right"]["ref"]): row[0] for row in rows
            }
            kinds = {row[0]: row[3]["link_kind"] for row in rows}
            # The C0 vocabulary is enforced: an event decision on an
            # entity item fails and leaves the item open.
            entity_item = next(
                review_id
                for review_id, kind in kinds.items()
                if kind == "entity"
            )
            with self.assertRaises(PersistenceError):
                R.resolve_resolution_review(
                    conn, review_id=entity_item,
                    decision="same_occurrence", rationale="wrong vocab",
                )
            with self.assertRaises(PersistenceError):
                R.resolve_resolution_review(
                    conn, review_id=entity_item,
                    decision="same_entity", rationale="   ",
                )
            # Human review: both identities attach, the event pair is
            # genuinely ambiguous and stays uncertain (non-blocking).
            for (left, _right), review_id in sorted(by_ref.items()):
                if kinds[review_id] == "entity":
                    R.resolve_resolution_review(
                        conn, review_id=review_id,
                        decision="same_entity", rationale="年表與列傳同名同職",
                        confidence=0.9,
                    )
                else:
                    R.resolve_resolution_review(
                        conn, review_id=review_id,
                        decision="uncertain", rationale="薨逝記載粒度不同",
                        confidence=0.5,
                    )
            # Re-resolving a closed item is rejected (audit stays append-only).
            from common import PersistenceConflict

            with self.assertRaises(PersistenceConflict):
                R.resolve_resolution_review(
                    conn, review_id=entity_item,
                    decision="not_same", rationale="second thoughts",
                )
            control_plane.resume_job(conn, job_id=job_id)
            # Resume clears the stale lease; the next live worker claims
            # the running job before executing (as run_once does).
            control_plane.claim_job(conn, worker=WORKER, job_id=job_id)

        self.assertEqual(runner.execute_job(job_id), "completed")

        with psycopg.connect(self.database_url) as conn:
            detail = control_plane.get_job_detail(conn, job_id=job_id)
            self.assertEqual(detail["status"], "completed")
            stages = {stage["stage"]: stage["status"] for stage in detail["stages"]}
            self.assertEqual(
                stages,
                {name: "completed" for name in control_plane.STAGE_NAMES},
            )
            after = control_plane.get_job_detail(conn, job_id=job_id)
            # Completed extraction/assembly were never re-run.
            for name in ("extract", "assemble"):
                old = next(s for s in before["stages"] if s["stage"] == name)
                new = next(s for s in after["stages"] if s["stage"] == name)
                self.assertEqual(old["attempt"], new["attempt"])
            types = [output["artifact_type"] for output in detail["outputs"]]
            self.assertIn(R.CATALOG_ARTIFACT_TYPE, types)

            catalogs = conn.execute(
                """
                SELECT payload FROM chronicle.ingestion_outputs
                WHERE job_id = %s AND artifact_type = %s
                """,
                (job_id, R.CATALOG_ARTIFACT_TYPE),
            ).fetchall()
            self.assertEqual(len(catalogs), 1)
            catalog = catalogs[0][0]["catalog"]
            report = catalogs[0][0]["report"]
            cao = [
                record for record in catalog["canonical_entities"]
                if record["canonical_id"] == seed_cao
            ]
            self.assertEqual(len(cao), 1)
            # UUID stability: the corpus 曹操 identity is reused and the
            # new representation attaches to it.
            new_label = R.new_bundle_label(revision_id)
            cao_reps = sorted(
                (rep["bundle"], rep["ref"]) for rep in cao[0]["representations"]
            )
            self.assertIn(("wudi", "ent_001"), cao_reps)
            self.assertEqual(
                [rep for rep in cao_reps if rep[0] == new_label],
                [(new_label, "ent_000001")],
            )
            # The uncertain event pair publishes as distinct occurrences.
            self.assertEqual(len(catalog["canonical_events"]), 2)
            self.assertEqual(catalog["event_relations"], [])
            self.assertEqual(
                report["decisions"]["entities"].get("same_entity"), 2
            )
            self.assertEqual(report["decisions"]["events"].get("uncertain"), 1)
            # Determinism: rebuilding from corpus + recorded decisions
            # yields the recorded final artifacts byte-for-byte.
            corpus_bundles = R.read_corpus_bundles(conn)
            new_bundle = artifact["bundle"]
            initial = R.build_initial_resolutions(
                new_bundle=new_bundle, new_label=new_label, corpus=corpus_bundles
            )
            recorded_initial = sorted(
                row[0]["resolution_sha256"]
                for row in conn.execute(
                    """
                    SELECT payload FROM chronicle.ingestion_outputs
                    WHERE job_id = %s AND artifact_type = %s
                      AND payload->>'role' = 'initial'
                    """,
                    (job_id, R.RESOLUTION_ARTIFACT_TYPE),
                ).fetchall()
            )
            self.assertEqual(
                sorted(R.initial_artifact_sha(item) for item in initial),
                recorded_initial,
            )
            decisions = R.collect_review_decisions(conn, job_id=job_id)
            final = R.build_final_resolutions(initial, decisions)
            recorded_final = sorted(
                row[0]["resolution_sha256"]
                for row in conn.execute(
                    """
                    SELECT payload FROM chronicle.ingestion_outputs
                    WHERE job_id = %s AND artifact_type = %s
                      AND payload->>'role' = 'final'
                    """,
                    (job_id, R.RESOLUTION_ARTIFACT_TYPE),
                ).fetchall()
            )
            self.assertEqual(
                sorted(sha256_json(item) for item in final), recorded_final
            )

    # -- the dismiss-all path (D-1) ---------------------------------------

    def test_dismissed_reviews_finalize_as_explicit_uncertain(self) -> None:
        """Dismissing every review still resumes to a completed publish.

        Regression test for D-1: dismissed items are durable terminal
        reviews, so finalization records them as explicit ``uncertain``
        (kept distinct, still reviewable) instead of failing on a
        missing decision. Genuinely unreviewed candidates remain a
        fail-closed error (covered by the unit suite).
        """
        with psycopg.connect(self.database_url) as conn:
            corpus = self._seed_corpus(conn)
            seed_ids = {
                record["canonical_id"]
                for record in corpus["catalog"]["canonical_entities"]
            }
            job_id, revision_id, _artifact = self._seed_job_with_bundle(
                conn,
                chunks=self._new_book_chunks("rev-placeholder", "0" * 64),
            )

        runner = worker.JobRunner(self.database_url, worker=WORKER)
        self.assertEqual(runner.execute_job(job_id), "needs_review")

        with psycopg.connect(self.database_url) as conn:
            rows = self._reviews(conn, job_id)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row[2] == "open" for row in rows))
            for review_id, _kind, _status, _payload in rows:
                control_plane.resolve_review_item(
                    conn, review_id=review_id, status="dismissed"
                )
            control_plane.resume_job(conn, job_id=job_id)
            control_plane.claim_job(conn, worker=WORKER, job_id=job_id)

        self.assertEqual(runner.execute_job(job_id), "completed")

        with psycopg.connect(self.database_url) as conn:
            detail = control_plane.get_job_detail(conn, job_id=job_id)
            self.assertEqual(detail["status"], "completed")
            catalogs = conn.execute(
                """
                SELECT payload FROM chronicle.ingestion_outputs
                WHERE job_id = %s AND artifact_type = %s
                """,
                (job_id, R.CATALOG_ARTIFACT_TYPE),
            ).fetchall()
            self.assertEqual(len(catalogs), 1)
            catalog = catalogs[0][0]["catalog"]
            report = catalogs[0][0]["report"]
            # Nothing merged: every representation is a singleton, and
            # every pre-existing canonical UUID survives unchanged.
            for record in catalog["canonical_entities"]:
                self.assertEqual(len(record["representations"]), 1)
            surviving = {
                record["canonical_id"]
                for record in catalog["canonical_entities"]
            }
            self.assertTrue(seed_ids <= surviving)
            self.assertEqual(len(catalog["canonical_events"]), 2)
            self.assertEqual(
                report["decisions"]["entities"].get("uncertain"), 2
            )
            self.assertEqual(report["decisions"]["events"].get("uncertain"), 1)
            # The dismissal rationale is recorded on the final links.
            finals = conn.execute(
                """
                SELECT payload FROM chronicle.resolution_artifacts
                """
            ).fetchall()
            rationales = [
                link.get("rationale")
                for (artifact,) in finals
                for link in (artifact.get("entity_links") or [])
                + (artifact.get("event_links") or [])
                if link.get("decision") == "uncertain"
                and "dismissed" in str(link.get("rationale") or "")
            ]
            self.assertTrue(rationales)

    # -- the unattended path ----------------------------------------------

    def test_disjoint_bundle_publishes_without_review(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            wuzhu = _corpus_bundle("吳主傳", [_entity("ent_001", "孫權")], [])
            staged_store.persist_bundle(conn, "wuzhu", wuzhu)
            import publication_v0  # noqa: E402

            catalog = publication_v0.publish_catalog({"wuzhu": wuzhu}, [], None)
            canonical_store.persist_catalog(conn, catalog)
            conn.commit()
            job_id, revision_id, _artifact = self._seed_job_with_bundle(
                conn,
                chunks=[
                    _chunk(
                        0, "rev-placeholder", "0" * 64,
                        entities=[_entity("ent_001", "曹操")],
                        events=[],
                        claims=[_claim("clm_001", "ent_001", "died", "曹操薨")],
                        start=0, end=50,
                    )
                ],
            )

        runner = worker.JobRunner(self.database_url, worker=WORKER)
        self.assertEqual(runner.execute_job(job_id), "completed")

        with psycopg.connect(self.database_url) as conn:
            detail = control_plane.get_job_detail(conn, job_id=job_id)
            self.assertEqual(detail["status"], "completed")
            self.assertEqual(R.open_resolution_review_count(conn, job_id=job_id), 0)
            catalogs = conn.execute(
                """
                SELECT payload FROM chronicle.ingestion_outputs
                WHERE job_id = %s AND artifact_type = %s
                """,
                (job_id, R.CATALOG_ARTIFACT_TYPE),
            ).fetchall()
            self.assertEqual(len(catalogs), 1)
            # No shared surface: two singleton identities, no merges.
            self.assertEqual(len(catalogs[0][0]["catalog"]["canonical_entities"]), 2)


if __name__ == "__main__":
    unittest.main()
