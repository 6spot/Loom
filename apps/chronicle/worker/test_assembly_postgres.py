"""PostgreSQL 18 integration tests for Chronicle C1-T7 source assembly.

Proves the real assemble stage against a live database: accepted
per-chunk extraction checkpoints assemble into one revision-scoped
C0-compatible source bundle artifact with within-book links and a
provenance-bearing report, boundary duplicates are suppressed with
evidence, and a job with incomplete chunks fails closed without
recording a bundle.
"""

from __future__ import annotations

import hashlib
import json
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
import control_plane  # noqa: E402
import extraction as X  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import ingestion_worker as worker  # noqa: E402

SCHEMA = json.loads(
    (HERE.parent / "ingestion" / "schemas" / "chronicle-v0.1.schema.json").read_text(
        encoding="utf-8"
    )
)

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"
WORKER = "worker-c1t7"


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
    return {"method": "model", "job_id": "c1t7-pg", "confidence": 0.7}


def _candidate(extra_claims: list[dict] | None = None) -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": "三國志·魏書·武帝紀（節選）",
            "author": "陳壽",
            "language": "lzh",
            "extraction": _meta(),
        },
        "entities": [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": "曹操",
                "aliases": [],
                "mentions": [{"text": "曹操"}],
                "resolution": {"status": "unresolved"},
                "extraction": _meta(),
            }
        ],
        "events": [],
        "claims": [
            {
                "temp_id": "clm_001",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "died",
                "object": None,
                "evidence": {
                    "text": "八月，表卒",
                    "source_ref": "src_001",
                    "locator": {"work": "三國志", "section": "全文"},
                },
                "assessment": {"status": "unassessed"},
                "extraction": _meta(),
            },
            *(extra_claims or []),
        ],
        "warnings": [],
    }


def _second_claim() -> dict:
    claim = _candidate()["claims"][0]
    claim = dict(claim)
    claim["temp_id"] = "clm_002"
    claim["predicate"] = "appointed"
    claim["evidence"] = {
        "text": "命周瑜為大都督",
        "source_ref": "src_001",
        "locator": {"work": "三國志", "section": "全文"},
    }
    return claim


class AssemblyPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t7_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
        self.source_sha = hashlib.sha256(b"c1t7-revision-bytes").hexdigest()

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _seed_job(self, *, chunk_statuses: list[str]) -> tuple[uuid.UUID, uuid.UUID]:
        """Seed a claimed job whose chunks carry accepted extraction layers."""
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(
                conn, title="三國志·魏書·武帝紀（節選）"
            )
            revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=self.source_sha,
                source_bytes=64,
                source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            control_plane.claim_job(conn, worker=WORKER, job_id=job_id)
            section_id = control_plane.create_section(
                conn, job_id=job_id, section_index=0, label="全文",
                source_start=0, source_end=100,
            )
            for index, status in enumerate(chunk_statuses):
                content_sha = hashlib.sha256(f"c1t7-chunk-{index}".encode()).hexdigest()
                chunk_id = control_plane.record_chunk(
                    conn, job_id=job_id, section_id=section_id,
                    chunk_index=index, source_start=index * 50,
                    source_end=index * 50 + 50,
                    source_sha256=self.source_sha, content_sha256=content_sha,
                )
                locator = {
                    "job_id": str(job_id),
                    "revision_id": str(revision_id),
                    "revision_no": 1,
                    "source_sha256": self.source_sha,
                    "section_index": 0,
                    "section_id": str(section_id),
                    "chunk_index": index,
                    "source_start": index * 50,
                    "source_end": index * 50 + 50,
                    "offset_unit": "chars-normalized-utf8",
                    "content_sha256": content_sha,
                }
                if status == "completed":
                    candidate = _candidate(
                        [_second_claim()] if index == 1 else None
                    )
                    accepted = X.build_accepted_checkpoint(
                        candidate=candidate, run_attempt=1,
                        locator=locator, context_output=None,
                    )
                    control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
                    control_plane.record_chunk_run(
                        conn, chunk_id=chunk_id, status="completed",
                        worker=WORKER,
                        checkpoint={"model_version": "pg-test-model-v1", "accepted": True},
                    )
                    control_plane.write_chunk_checkpoint(
                        conn, chunk_id=chunk_id,
                        checkpoint={"extraction": accepted},
                    )
                    control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="completed")
            control_plane.advance_stage(conn, job_id=job_id, stage="assemble", status="running")
            return job_id, revision_id

    def _runner(self) -> worker.JobRunner:
        return worker.JobRunner(self.database_url, worker=WORKER)

    def _outputs(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            return conn.execute(
                """
                SELECT artifact_type, artifact_sha256, payload
                FROM chronicle.ingestion_outputs WHERE job_id = %s
                """,
                (job_id,),
            ).fetchall()

    def test_real_assemble_records_bundle_links_and_report(self) -> None:
        job_id, revision_id = self._seed_job(chunk_statuses=["completed", "completed"])
        outcome = self._runner()._execute_real_assemble(job_id)
        self.assertEqual("ok", outcome)

        rows = self._outputs(job_id)
        self.assertEqual(1, len(rows))
        artifact_type, artifact_sha, payload = rows[0]
        self.assertEqual(A.ARTIFACT_TYPE, artifact_type)
        self.assertEqual(64 * "0" != artifact_sha, True)
        self.assertEqual(A.sha256_json(payload), artifact_sha)

        bundle = payload["bundle"]
        from jsonschema import Draft202012Validator, FormatChecker

        schema_errors = list(
            Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(bundle)
        )
        self.assertEqual([], schema_errors)

        # Adjacent duplicate claim suppressed once; the distinct second
        # claim survives; both entities link as the same identity.
        self.assertEqual(2, len(bundle["entities"]))
        self.assertEqual(2, len(bundle["claims"]))
        report = payload["report"]
        self.assertEqual(1, report["counts"]["suppressed_claims"])
        self.assertEqual(1, len(report["duplicate_suppressions"]))
        self.assertEqual("c1t7-v1", report["assembly_version"])
        self.assertEqual(str(revision_id), report["revision"]["revision_id"])
        self.assertEqual(self.source_sha, report["revision"]["source_sha256"])
        for ref, prov in report["record_provenance"].items():
            if ref == "src_001":
                continue
            self.assertIn(prov["chunk_index"], (0, 1))
            self.assertEqual(1, prov["run_attempt"])
            self.assertEqual("pg-test-model-v1", prov["model_version"])
        links = payload["within_book_links"]
        self.assertEqual(1, len(links["entity_links"]))
        self.assertEqual("same_entity", links["entity_links"][0]["decision"])

        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT status FROM chronicle.ingestion_job_stages
                WHERE job_id = %s AND stage = 'assemble'
                """,
                (job_id,),
            ).fetchone()
        self.assertEqual("completed", row[0])

    def test_real_assemble_is_idempotent_on_retry(self) -> None:
        job_id, _ = self._seed_job(chunk_statuses=["completed", "completed"])
        runner = self._runner()
        self.assertEqual("ok", runner._execute_real_assemble(job_id))
        first = self._outputs(job_id)
        # A resumed worker reruns the stage: content-addressed output and
        # the completed->completed transition make this a no-op.
        self.assertEqual("ok", runner._execute_real_assemble(job_id))
        second = self._outputs(job_id)
        self.assertEqual(len(first), len(second))
        self.assertEqual(first[0][1], second[0][1])

    def test_partial_chunks_fail_closed_without_output(self) -> None:
        job_id, _ = self._seed_job(chunk_statuses=["completed", "pending"])
        outcome = self._runner()._execute_real_assemble(job_id)
        self.assertEqual("failed", outcome)
        self.assertEqual([], self._outputs(job_id))


if __name__ == "__main__":
    unittest.main()
