"""PostgreSQL 18 integration tests for Chronicle C1-T6 chunk extraction.

Proves the real extract path against a live database: persisted chunks
produce schema-valid candidates with exact evidence, every model attempt
is preserved in append-only ChunkRun history, ordinary resume never
duplicates a successful chunk, retries append without overwriting, and
ungroundable output fails closed without a manufactured candidate.
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

import control_plane  # noqa: E402
import extraction as X  # noqa: E402
from extraction import ExtractionConfig  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import ingestion_worker as worker  # noqa: E402
import segmentation as S  # noqa: E402

FIXTURE_DIR = HERE.parent / "ingestion" / "fixtures" / "c1t6-inherited-jianan"
SCHEMA = json.loads(
    (HERE.parent / "ingestion" / "schemas" / "chronicle-v0.1.schema.json").read_text(
        encoding="utf-8"
    )
)
ALLOWED_PREDICATES = [
    "held_office",
    "died",
    "succeeded",
    "surrendered_to",
    "attacked",
    "fought",
    "outcome",
    "affected",
    "gained_territory",
    "moved_to",
    "stationed_at",
    "appointed",
    "retreated",
]

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


def _meta() -> dict:
    return {"method": "model", "job_id": "c1t6-pg", "confidence": 0.7}


def _time(original: str, fields: list[str]) -> dict:
    return {
        "original_text": original,
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": 13,
            "season": None,
            "month": None,
            "inherited_fields": fields,
        },
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": 208,
            "month": None,
            "day": None,
            "precision": "year",
            "conversion_status": "year_only",
        },
    }


# Per-chunk (entity, entity_type, predicate, evidence, object) grounded in
# the c1t6-inherited-jianan fixture slices. Chunk 0 carries the explicit
# year; chunks 1-3 inherit it verbatim.
CHUNK_SPECS = [
    ("劉表", "person", "died", "劉表卒", None, True),
    ("張遼", "person", "stationed_at", "其將張遼為先鋒",
     {"kind": "literal", "value": "先鋒"}, False),
    ("周瑜", "person", "appointed", "命周瑜為大都督",
     {"kind": "literal", "value": "大都督"}, False),
    ("劉備", "person", "gained_territory", "劉備遂有荊州、江南諸郡",
     {"kind": "entity_ref", "ref": "ent_002"}, False),
]


def canned_bundle(chunk_index: int, section_label: str) -> dict:
    name, kind, predicate, evidence, obj, explicit = CHUNK_SPECS[chunk_index]
    entities = [
        {
            "temp_id": "ent_001",
            "kind": "entity",
            "type": kind,
            "canonical_name": name,
            "aliases": [],
            "mentions": [{"text": name}],
            "resolution": {"status": "unresolved"},
            "extraction": _meta(),
        }
    ]
    if obj is not None and obj.get("kind") == "entity_ref":
        entities.append(
            {
                "temp_id": "ent_002",
                "kind": "entity",
                "type": "place",
                "canonical_name": "荊州",
                "aliases": [],
                "mentions": [{"text": "荊州"}],
                "resolution": {"status": "unresolved"},
                "extraction": _meta(),
            }
        )
        obj = {"kind": "entity_ref", "ref": "ent_002"}
    time_block = _time("建安十三年", [] if explicit else ["era", "era_year"])
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
        "entities": entities,
        "events": [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "other",
                "title": evidence[:12],
                "time": None,
                "participants": [{"entity_ref": "ent_001", "role": "subject"}],
                "places": [],
                "extraction": _meta(),
            }
        ],
        "claims": [
            {
                "temp_id": "clm_001",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": predicate,
                "object": obj,
                "time": time_block,
                "evidence": {
                    "text": evidence,
                    "source_ref": "src_001",
                    "locator": {"work": "三國志", "section": section_label},
                },
                "assessment": {"status": "unassessed"},
                "extraction": _meta(),
            }
        ],
        "warnings": [],
    }


class ScriptedChunkModel:
    """Ordered scripted provider: one canned response per model call."""

    def __init__(self, responses: list[str], name: str = "scripted-c1t6-v1"):
        self.responses = list(responses)
        self.name = name
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        if not self.responses:
            raise AssertionError("model called more times than scripted")
        return self.responses.pop(0)


def _bad_bundle(section_label: str) -> dict:
    bundle = canned_bundle(0, section_label)
    bundle["claims"][0]["evidence"]["text"] = "刘表去世了"
    return bundle


class ExtractionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t6_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
        raw_bytes = (FIXTURE_DIR / "raw.txt").read_bytes()
        self.text = raw_bytes.decode("utf-8")
        self.source_sha = hashlib.sha256(raw_bytes).hexdigest()
        spec = json.loads((FIXTURE_DIR / "extraction.json").read_text(encoding="utf-8"))
        self.doc = spec["document"]
        self.segmentation_config = S.SegmentationConfig(**spec["segmentation_config"])

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _queue_job(self) -> tuple[uuid.UUID, uuid.UUID]:
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title=self.doc["title"])
            revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=self.source_sha,
                source_bytes=len((FIXTURE_DIR / "raw.txt").read_bytes()),
                source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            return job_id, revision_id

    def _run(self, model, **kwargs):
        schema = kwargs.pop("extraction_schema", SCHEMA)
        return worker.run_once(
            self.database_url,
            worker="worker-c1t6",
            revision_source=lambda jid: (self.text, self.source_sha),
            segmentation_config=self.segmentation_config,
            chunk_model=model,
            extraction_config=ExtractionConfig(max_repair_attempts=1),
            extraction_schema=schema,
            allowed_predicates=ALLOWED_PREDICATES,
            document_meta=self.doc,
            **kwargs,
        )

    def _chunks(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            return conn.execute(
                """
                SELECT chunk_id, chunk_index, status, attempt, checkpoint
                FROM chronicle.ingestion_chunks
                WHERE job_id = %s ORDER BY chunk_index
                """,
                (job_id,),
            ).fetchall()

    def _runs(self, chunk_id):
        with psycopg.connect(self.database_url) as conn:
            return conn.execute(
                """
                SELECT attempt, status, checkpoint, error
                FROM chronicle.ingestion_chunk_runs
                WHERE chunk_id = %s ORDER BY attempt
                """,
                (chunk_id,),
            ).fetchall()

    def test_real_extract_accepts_all_chunks_with_history(self) -> None:
        job_id, _ = self._queue_job()
        model = ScriptedChunkModel(
            [json.dumps(canned_bundle(i, "全文"), ensure_ascii=False) for i in range(4)]
        )
        result = self._run(model)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "completed")
        self.assertEqual(model.calls, 4)

        chunks = self._chunks(job_id)
        self.assertEqual(4, len(chunks))
        for chunk_id, index, status, _attempt, checkpoint in chunks:
            self.assertEqual("completed", status)
            runs = self._runs(chunk_id)
            self.assertEqual(1, len(runs))
            self.assertEqual("completed", runs[0][1])
            history = runs[0][2]
            self.assertEqual("c1t6-v1", history["extraction_version"])
            self.assertEqual("0.2", history["contract_version"])
            self.assertTrue(history["accepted"])
            self.assertEqual(1, history["attempt_count"])
            self.assertFalse(history["authoritative"])
            # Replayable: stored validation reproduces over stored pairs.
            plan = S.segment_revision(
                self.text, self.source_sha, self.segmentation_config
            )
            chunk = plan.chunks[index]
            pairs = S.context_chain(plan, self.text, self.segmentation_config)
            mismatches = X.verify_history(
                history,
                chunk_text=self.text[chunk.source_start : chunk.source_end],
                context_input=pairs[index]["input"],
                section_label="全文",
                document=self.doc,
                schema=SCHEMA,
                allowed_predicates=ALLOWED_PREDICATES,
            )
            self.assertEqual([], mismatches)
            # Accepted-output layer: exact evidence plus chunk locator.
            accepted = checkpoint["extraction"]
            self.assertTrue(accepted["accepted"])
            self.assertFalse(accepted["authoritative"])
            self.assertEqual(index, accepted["locator"]["chunk_index"])
            evidence = accepted["candidate"]["claims"][0]["evidence"]["text"]
            sliver = self.text[chunk.source_start : chunk.source_end]
            self.assertIn(evidence, sliver)
            self.assertNotIn("context_output", accepted["candidate"])

    def test_resume_never_duplicates_success_and_retry_appends(self) -> None:
        job_id, _ = self._queue_job()
        good = [json.dumps(canned_bundle(i, "全文"), ensure_ascii=False) for i in range(4)]
        bad = json.dumps(_bad_bundle("全文"), ensure_ascii=False)
        # First pass: chunk 0 succeeds; chunk 1 fails closed twice
        # (initial + one bounded correction), parking the job as failed.
        model = ScriptedChunkModel([good[0], bad, bad])
        result = self._run(model)
        self.assertEqual(result[1], "failed")

        chunks = self._chunks(job_id)
        self.assertEqual("completed", chunks[0][2])
        self.assertEqual("failed", chunks[1][2])
        self.assertEqual(1, len(self._runs(chunks[0][0])))
        first_runs = self._runs(chunks[1][0])
        self.assertEqual(2, len(first_runs))
        self.assertTrue(all(status == "failed" for _, status, _, _ in first_runs))

        # Bounded Studio retry: only failed chunks re-run; the successful
        # chunk keeps exactly one run row and the failed chunk's history
        # grows by exactly one appended row.
        with psycopg.connect(self.database_url) as conn:
            control_plane.retry_job(conn, job_id=job_id)
        # Chunk 0 is skipped (already completed); chunk 1 retries and the
        # never-started chunks 2-3 run for the first time.
        model2 = ScriptedChunkModel([good[1], good[2], good[3]])
        result2 = self._run(model2, )
        self.assertEqual(result2[1], "completed")
        self.assertEqual(3, model2.calls)

        chunks = self._chunks(job_id)
        self.assertTrue(all(status == "completed" for _, _, status, _, _ in chunks))
        self.assertEqual(1, len(self._runs(chunks[0][0])))
        rerun = self._runs(chunks[1][0])
        self.assertEqual(3, len(rerun))
        self.assertEqual("completed", rerun[-1][1])
        self.assertTrue(rerun[-1][2]["accepted"])
        # Earlier attempts were never overwritten.
        self.assertTrue(all(status == "failed" for _, status, _, _ in rerun[:2]))

    def test_fail_closed_output_leaves_no_accepted_candidate(self) -> None:
        job_id, _ = self._queue_job()
        bad = json.dumps(_bad_bundle("全文"), ensure_ascii=False)
        # Chunk 0 consumes both scripted calls (initial + one bounded
        # correction) and still cannot be grounded: the job parks failed.
        model = ScriptedChunkModel([bad, bad])
        result = self._run(model)
        self.assertEqual(result[1], "failed")

        chunks = self._chunks(job_id)
        self.assertEqual("failed", chunks[0][2])
        runs = self._runs(chunks[0][0])
        self.assertEqual(2, len(runs))
        self.assertIn("failed closed", runs[-1][3])
        # No manufactured candidate: the chunk checkpoint keeps the C1-T5
        # segmentation state with no accepted extraction layer.
        self.assertNotIn("extraction", chunks[0][4])

    def test_chunk_model_without_revision_source_fails_closed(self) -> None:
        job_id, _ = self._queue_job()
        model = ScriptedChunkModel([])
        result = worker.run_once(
            self.database_url,
            worker="worker-c1t6",
            segmentation_config=self.segmentation_config,
            chunk_model=model,
            extraction_config=ExtractionConfig(),
            document_meta=self.doc,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "failed")
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT status, error FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            self.assertEqual("failed", row[0])
            self.assertIn("revision_source", row[1])

    def test_real_extract_requires_schema_and_fails_closed(self) -> None:
        job_id, _ = self._queue_job()
        model = ScriptedChunkModel([])
        result = worker.run_once(
            self.database_url,
            worker="worker-c1t6",
            revision_source=lambda jid: (self.text, self.source_sha),
            segmentation_config=self.segmentation_config,
            chunk_model=model,
            extraction_config=ExtractionConfig(),
            extraction_schema={},
            document_meta=self.doc,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "failed")
        self.assertEqual(0, model.calls)
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT status, error FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            self.assertEqual("failed", row[0])
            self.assertIn("canonical", row[1])

    def test_none_schema_binds_canonical_and_completes(self) -> None:
        job_id, _ = self._queue_job()
        model = ScriptedChunkModel(
            [json.dumps(canned_bundle(i, "全文"), ensure_ascii=False) for i in range(4)]
        )
        result = self._run(model, extraction_schema=None)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "completed")
        self.assertEqual(4, model.calls)
        chunks = self._chunks(job_id)
        self.assertTrue(all(status == "completed" for _, _, status, _, _ in chunks))

    def test_crash_window_resume_adopts_accepted_run(self) -> None:
        job_id, _ = self._queue_job()
        model = ScriptedChunkModel(
            [json.dumps(canned_bundle(i, "全文"), ensure_ascii=False) for i in range(4)]
        )
        result = self._run(model)
        self.assertEqual(result[1], "completed")

        chunks = self._chunks(job_id)
        victim = chunks[1][0]
        self.assertEqual(1, len(self._runs(victim)))

        # Simulate a worker exit between the accepted run-row commit and
        # the accepted-layer/status commit for chunk 1: the run history
        # holds an accepted run, but the chunk checkpoint and status do
        # not. Direct SQL stands in for the crash (it bypasses the state
        # machine exactly as a torn commit would).
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                """
                UPDATE chronicle.ingestion_chunks
                SET status = 'running', checkpoint = checkpoint - 'extraction'
                WHERE chunk_id = %s
                """,
                (victim,),
            )
            conn.execute(
                """
                UPDATE chronicle.ingestion_jobs
                SET status = 'running', lease_owner = NULL,
                    lease_expires_at = NULL, error = NULL
                WHERE job_id = %s
                """,
                (job_id,),
            )
            conn.execute(
                """
                UPDATE chronicle.ingestion_job_stages
                SET status = 'running'
                WHERE job_id = %s AND stage = 'extract'
                """,
                (job_id,),
            )

        strict = ScriptedChunkModel([])
        resumed = self._run(strict)
        self.assertEqual(resumed[1], "completed")
        # Zero model calls: the accepted run was adopted, not re-extracted.
        self.assertEqual(0, strict.calls)
        self.assertEqual(1, len(self._runs(victim)))
        chunks = self._chunks(job_id)
        self.assertEqual("completed", chunks[1][2])
        accepted = chunks[1][4]["extraction"]
        self.assertTrue(accepted["accepted"])
        self.assertEqual(1, accepted["produced_by_run_attempt"])
        evidence = accepted["candidate"]["claims"][0]["evidence"]["text"]
        self.assertIn(evidence, self.text)


if __name__ == "__main__":
    unittest.main()
