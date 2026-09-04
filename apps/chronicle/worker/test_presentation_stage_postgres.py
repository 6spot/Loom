"""PostgreSQL 18 integration for the C1-T12 offline ``present`` stage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import assembly  # noqa: E402
import canonical_store  # noqa: E402
import control_plane  # noqa: E402
import presentation_stage  # noqa: E402
import resolve_publish  # noqa: E402
import staged_store  # noqa: E402
from common import LeaseLost, sha256_json  # noqa: E402
from migrations import apply_migrations  # noqa: E402
import ingestion_worker as worker_mod  # noqa: E402

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"
WORKER = "worker-c1t12"


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
    return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _meta() -> dict:
    return {"method": "model", "job_id": "c1t12-pg", "confidence": 0.9}


def _bundle() -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": "三國志·蜀書·先主傳",
            "author": "陳壽",
            "language": "lzh",
            "extraction": _meta(),
        },
        "entities": [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": "劉備",
                "aliases": ["先主"],
                "mentions": [{"text": "先主"}],
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
                "predicate": "named",
                "object": {"kind": "literal", "value": "劉備"},
                "time": None,
                "evidence": {
                    "text": "先主姓劉，諱備",
                    "source_ref": "src_001",
                    "locator": {"work": "三國志", "section": "先主傳"},
                },
                "assessment": {"status": "unassessed"},
                "extraction": _meta(),
            }
        ],
        "warnings": [],
    }


class GroundedPresentationModel:
    name = "reader-test-model-v1"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        context = json.loads(prompt.split("INPUT:\n", 1)[1])
        claim = context["representations"][0]["claims"][0]
        return json.dumps(
            {
                "schema": "chronicle.reader-presentation",
                "version": "0.1",
                "target_kind": context["target_kind"],
                "canonical_id": context["canonical_id"],
                "language": "zh-CN",
                "blocks": [
                    {
                        "block_kind": "overview",
                        "epistemic_mode": "fact_summary",
                        "text": "史料直接记载：先主姓刘，名备。",
                        "claim_refs": [
                            {"bundle": claim["bundle"], "ref": claim["ref"]}
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )


class CancellingPresentationModel(GroundedPresentationModel):
    def __init__(self, database_url: str, job_id: uuid.UUID) -> None:
        super().__init__()
        self.database_url = database_url
        self.job_id = job_id

    def complete(self, prompt: str) -> str:
        raw = super().complete(prompt)
        # Model calls are outside a transaction, so an operator can cancel
        # while inference is in flight. The later lease fence must win.
        with psycopg.connect(self.database_url) as conn:
            control_plane.cancel_job(conn, job_id=self.job_id)
        return raw


class PresentationStagePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t12_worker_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _seed_presentable_job(self) -> tuple[uuid.UUID, uuid.UUID, str]:
        bundle = _bundle()
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title="先主傳")
            revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=sha256_json({"source": str(uuid.uuid4())}),
                source_bytes=128,
                source_media_type="text/plain",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            control_plane.claim_job(conn, worker=WORKER, job_id=job_id)
            for stage in control_plane.STAGE_NAMES:
                if stage == "present":
                    break
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="running")
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="completed")

            label = resolve_publish.new_bundle_label(revision_id)
            staged_store.persist_bundle(conn, label, bundle)
            import publication_v0

            catalog = publication_v0.publish_catalog({label: bundle}, [], None)
            canonical_store.persist_catalog(conn, catalog)
            control_plane.record_output(
                conn,
                job_id=job_id,
                revision_id=revision_id,
                artifact_type=assembly.ARTIFACT_TYPE,
                artifact_sha256=sha256_json({"fixture": "assembly", "job": str(job_id)}),
                payload={"bundle": bundle, "fixture": True},
            )
            conn.commit()
            canonical_id = catalog["canonical_entities"][0]["canonical_id"]
        return job_id, revision_id, canonical_id

    def test_stage_is_offline_grounded_and_crash_window_adopts_without_model_recall(self) -> None:
        job_id, _revision_id, canonical_id = self._seed_presentable_job()
        model = GroundedPresentationModel()

        first = presentation_stage.execute_present_stage(
            self.database_url, job_id=job_id, worker=WORKER, model=model
        )
        self.assertEqual(first["published"], 1)
        self.assertEqual(first["adopted"], 0)
        self.assertEqual(model.calls, 1)

        second = presentation_stage.execute_present_stage(
            self.database_url, job_id=job_id, worker=WORKER, model=model
        )
        self.assertEqual(second["published"], 0)
        self.assertEqual(second["adopted"], 1)
        self.assertEqual(model.calls, 1, "exact-input retry must not call the model again")

        # The JobRunner owns normal execution. It should adopt the exact
        # already-persisted artifact, complete ``present``, then complete job.
        runner = worker_mod.JobRunner(
            self.database_url, worker=WORKER, presentation_model=model
        )
        self.assertEqual(runner.execute_job(job_id), "completed")
        self.assertEqual(model.calls, 1)

        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT p.presentation_version, p.origin_job_id, p.base_language,
                       b.text, s.claim_ref
                FROM chronicle.reader_presentations p
                JOIN chronicle.reader_presentation_blocks b USING (presentation_id)
                JOIN chronicle.reader_presentation_supports s
                  ON s.presentation_id = b.presentation_id
                 AND s.block_index = b.block_index
                WHERE p.canonical_entity_id = %s::uuid
                """,
                (canonical_id,),
            ).fetchone()
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], job_id)
            self.assertEqual(row[2], "zh-CN")
            self.assertIn("先主", row[3])
            self.assertEqual(row[4], "clm_001")

            outputs = conn.execute(
                """
                SELECT payload FROM chronicle.ingestion_outputs
                WHERE job_id = %s AND artifact_type = %s
                """,
                (job_id, presentation_stage.ARTIFACT_TYPE),
            ).fetchall()
            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0][0]["canonical_id"], canonical_id)
            self.assertEqual(outputs[0][0]["model_version"], model.name)
            detail = control_plane.get_job_detail(conn, job_id=job_id)
            present = next(stage for stage in detail["stages"] if stage["stage"] == "present")
            self.assertEqual(present["status"], "completed")
            self.assertEqual(present["checkpoint"]["stage_version"], presentation_stage.STAGE_VERSION)
            self.assertFalse(present["checkpoint"]["authoritative"])

    def test_cancellation_during_model_call_prevents_projection_and_output(self) -> None:
        job_id, _revision_id, _canonical_id = self._seed_presentable_job()
        model = CancellingPresentationModel(self.database_url, job_id)

        with self.assertRaises(LeaseLost):
            presentation_stage.execute_present_stage(
                self.database_url, job_id=job_id, worker=WORKER, model=model
            )

        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chronicle.reader_presentations").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_outputs WHERE artifact_type = %s",
                    (presentation_stage.ARTIFACT_TYPE,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0],
                "cancelled",
            )


if __name__ == "__main__":
    unittest.main()
