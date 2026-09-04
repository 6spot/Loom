"""PostgreSQL 18 integration tests for Chronicle C1-T5 real segmentation.

Proves the versioned structure/segment path against a real database: one
revision produces stable sections/chunks with exact source locators,
context state flows from chunk N to N+1 through persisted checkpoints,
reruns reproduce identical records without duplication, crash/restart
resumes from persisted checkpoints, and locator drift fails closed.
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
from common import PersistenceConflict  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import ingestion_worker as worker  # noqa: E402
import segmentation as S  # noqa: E402
from segmentation import SegmentationConfig  # noqa: E402

FIXTURE_DIR = HERE.parent / "ingestion" / "fixtures" / "c1t5-boundary-continuity"

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


def _fixture() -> tuple[str, str, SegmentationConfig]:
    text = (FIXTURE_DIR / "raw.txt").read_bytes().decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    spec = json.loads((FIXTURE_DIR / "expected-context.json").read_text())
    config = SegmentationConfig(**spec["segmentation_config"])
    sha = hashlib.sha256((FIXTURE_DIR / "raw.txt").read_bytes()).hexdigest()
    return text, sha, config


def _queue_job(conn, source_sha: str, title: str = "三國志") -> tuple[uuid.UUID, uuid.UUID]:
    document_id = control_plane.create_document(conn, title=title)
    revision_id, _ = control_plane.create_revision(
        conn,
        document_id=document_id,
        source_sha256=source_sha,
        source_bytes=4096,
        source_media_type="text/plain",
    )
    job_id = control_plane.queue_job(conn, revision_id=revision_id)
    return job_id, revision_id


class SegmentationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t5_{uuid.uuid4().hex}"
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

    def _run_real(self, source, config=None):
        return worker.run_once(
            self.database_url, worker="worker-c1t5",
            revision_source=source, segmentation_config=config,
            allow_fake_after_real_source=True,
        )

    def test_real_path_persists_sections_chunks_and_context(self) -> None:
        text, sha, config = _fixture()
        with psycopg.connect(self.database_url) as conn:
            job_id, revision_id = _queue_job(conn, sha)
        result = self._run_real(lambda jid: (text, sha), config)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "completed")
        with psycopg.connect(self.database_url) as conn:
            sections = conn.execute(
                """
                SELECT section_index, label, source_start, source_end,
                       kind, depth, parent_section_index
                FROM chronicle.ingestion_sections
                WHERE job_id = %s ORDER BY section_index
                """,
                (job_id,),
            ).fetchall()
            self.assertGreaterEqual(len(sections), 3)
            kinds = {row[1] for row in sections}
            self.assertTrue({"卷一", "武帝紀", "列傳"} <= kinds)
            # The persisted rows recover the detected hierarchy without
            # worker memory: volumes at depth 0, chapters/biographies
            # nested under the preceding volume.
            by_label = {row[1]: row for row in sections}
            self.assertEqual(by_label["卷一"][4], "volume")
            self.assertEqual(by_label["卷一"][5], 0)
            self.assertIsNone(by_label["卷一"][6])
            for label in ("武帝紀", "列傳"):
                self.assertIn(by_label[label][4], ("treatise", "biography"))
                self.assertEqual(by_label[label][5], 1)
                self.assertEqual(
                    by_label[label][6], by_label["卷一"][0]
                )
            chunks = conn.execute(
                """
                SELECT chunk_index, section_id, source_start, source_end,
                       source_sha256, content_sha256, checkpoint
                FROM chronicle.ingestion_chunks
                WHERE job_id = %s ORDER BY chunk_index
                """,
                (job_id,),
            ).fetchall()
            self.assertGreaterEqual(len(chunks), 2)
            # Exact locators: every slice reconstructs and rehashes; the
            # row's source_sha256 is the whole-revision identity, distinct
            # from the slice hash.
            for row in chunks:
                sliver = text[row[2] : row[3]]
                self.assertTrue(sliver.strip())
                self.assertEqual(
                    hashlib.sha256(sliver.encode("utf-8")).hexdigest(), row[5]
                )
                self.assertEqual(row[4], sha)
                self.assertNotEqual(row[4], row[5])
            # Sections tile the revision; chunks tile their sections.
            self.assertEqual(sections[0][2], 0)
            self.assertEqual(sections[-1][3], len(text))
            # Chunk checkpoints carry versioned context, never authority.
            previous_output = None
            for row in chunks:
                checkpoint = row[6]
                self.assertEqual(
                    checkpoint["segmentation_version"], S.SEGMENTATION_VERSION
                )
                self.assertEqual(
                    checkpoint["context_output"]["version"], S.CONTEXT_VERSION
                )
                self.assertFalse(checkpoint["authoritative"])
                locator = checkpoint["locator"]
                self.assertEqual(locator["revision_id"], str(revision_id))
                self.assertEqual(locator["source_sha256"], sha)
                self.assertEqual(locator["content_sha256"], row[5])
                if previous_output is not None:
                    self.assertEqual(checkpoint["context_input"], previous_output)
                previous_output = checkpoint["context_output"]
            # Stage checkpoints record the segmentation/model versions.
            stages = {
                row[0]: row[1]
                for row in conn.execute(
                    """
                    SELECT stage, checkpoint
                    FROM chronicle.ingestion_job_stages WHERE job_id = %s
                    """,
                    (job_id,),
                ).fetchall()
            }
            self.assertEqual(
                stages["structure"]["segmentation_version"], S.SEGMENTATION_VERSION
            )
            self.assertEqual(
                stages["structure"]["structure_version"], S.STRUCTURE_VERSION
            )
            self.assertEqual(
                stages["segment"]["context_version"], S.CONTEXT_VERSION
            )
            self.assertEqual(stages["segment"]["model_version"], S.MODEL_VERSION)
            self.assertEqual(stages["segment"]["prompt_version"], S.PROMPT_VERSION)
            self.assertEqual(
                stages["structure"]["plan_sha256"], stages["segment"]["plan_sha256"]
            )
            # Reproducibility: the same input re-segmented gives the same plan.
            repeat = S.segment_revision(text, sha, config)
            self.assertEqual(
                repeat.manifest["plan_sha256"], stages["segment"]["plan_sha256"]
            )

    def test_rerun_is_stable_and_resumes_after_failure(self) -> None:
        text, sha, config = _fixture()
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn, sha)
        # First attempt: fail the first extract chunk after real
        # structure+segment persisted, proving crash/restart resumes from
        # those checkpoints.
        failing = worker.StageExecutor(fail_chunks={0: 1})
        runner = worker.JobRunner(
            self.database_url, worker="worker-c1t5", executor=failing,
            revision_source=lambda jid: (text, sha),
            segmentation_config=config,
        )
        with psycopg.connect(self.database_url) as conn:
            claimed = control_plane.claim_job(conn, worker="worker-c1t5")
        self.assertEqual(claimed, job_id)
        self.assertEqual(runner.execute_job(job_id), "failed")
        with psycopg.connect(self.database_url) as conn:
            first_sections = conn.execute(
                "SELECT section_id FROM chronicle.ingestion_sections WHERE job_id = %s ORDER BY section_index",
                (job_id,),
            ).fetchall()
            first_chunks = conn.execute(
                "SELECT chunk_id FROM chronicle.ingestion_chunks WHERE job_id = %s ORDER BY chunk_index",
                (job_id,),
            ).fetchall()
            self.assertTrue(first_sections and first_chunks)
        # Bounded retry reuses every persisted locator row and completes.
        with psycopg.connect(self.database_url) as conn:
            control_plane.retry_job(conn, job_id=job_id)
        result = self._run_real(lambda jid: (text, sha), config)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "completed")
        with psycopg.connect(self.database_url) as conn:
            second_sections = conn.execute(
                "SELECT section_id FROM chronicle.ingestion_sections WHERE job_id = %s ORDER BY section_index",
                (job_id,),
            ).fetchall()
            second_chunks = conn.execute(
                "SELECT chunk_id FROM chronicle.ingestion_chunks WHERE job_id = %s ORDER BY chunk_index",
                (job_id,),
            ).fetchall()
            self.assertEqual(first_sections, second_sections)
            self.assertEqual(first_chunks, second_chunks)

    def test_locator_drift_fails_closed(self) -> None:
        text, sha, config = _fixture()
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn, sha)
            plan = S.segment_revision(text, sha, config)
            S.ensure_sections_chunks(conn, job_id=job_id, plan=plan, source_sha256=sha)
            drifted_text = text + "後人補記一筆。"
            drifted = S.segment_revision(
                drifted_text,
                hashlib.sha256(b"other").hexdigest(),
                config,
            )
            with self.assertRaises(PersistenceConflict):
                S.ensure_sections_chunks(
                    conn, job_id=job_id, plan=drifted,
                    source_sha256=hashlib.sha256(b"other").hexdigest(),
                )

    def test_stale_extra_rows_fail_closed(self) -> None:
        # D-5: re-entry with a smaller plan must not leave old extra rows
        # for a later extract to execute.
        text, sha, config = _fixture()
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn, sha)
            plan = S.segment_revision(text, sha, config)
            section_ids, _ = S.ensure_sections_chunks(
                conn, job_id=job_id, plan=plan, source_sha256=sha
            )
            stray_section = control_plane.create_section(
                conn, job_id=job_id, section_index=99, label="stray",
                source_start=0, source_end=1, kind="unknown",
            )
            control_plane.record_chunk(
                conn, job_id=job_id, section_id=stray_section,
                chunk_index=99, source_start=0, source_end=1,
                source_sha256=sha, content_sha256=hashlib.sha256(b"x").hexdigest(),
            )
            with self.assertRaises(PersistenceConflict):
                S.ensure_sections_chunks(
                    conn, job_id=job_id, plan=plan, source_sha256=sha
                )

    def test_source_mismatch_fails_the_job(self) -> None:
        # D-6: a callback hash that does not match the immutable revision
        # row fails the job instead of segmenting foreign bytes.
        text, sha, config = _fixture()
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn, sha)
        result = worker.run_once(
            self.database_url, worker="worker-c1t5",
            revision_source=lambda jid: (text, "0" * 64),
            segmentation_config=config,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "failed")
        with psycopg.connect(self.database_url) as conn:
            status = conn.execute(
                "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(status, "failed")
            stage = conn.execute(
                """
                SELECT status FROM chronicle.ingestion_job_stages
                WHERE job_id = %s AND stage = 'structure'
                """,
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(stage, "failed")
            count = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_chunks WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(int(count), 0)

    def test_section_hierarchy_validation(self) -> None:
        # D-3: structural fields are validated, not just stored.
        text, sha, _ = _fixture()
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn, sha)
            with self.assertRaises(Exception):
                control_plane.create_section(
                    conn, job_id=job_id, section_index=0, label="x",
                    source_start=0, source_end=1, kind="",
                )
            with self.assertRaises(Exception):
                control_plane.create_section(
                    conn, job_id=job_id, section_index=0, label="x",
                    source_start=0, source_end=1, depth=-1,
                )
            with self.assertRaises(Exception):
                control_plane.create_section(
                    conn, job_id=job_id, section_index=0, label="x",
                    source_start=0, source_end=1,
                    parent_section_index=0,  # must precede self
                )

    def test_jobs_without_source_keep_fake_topology(self) -> None:
        text, sha, _ = _fixture()
        with psycopg.connect(self.database_url) as conn:
            job_id, _ = _queue_job(conn, sha)
        result = worker.run_once(self.database_url, worker="worker-c1t5")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "completed")
        with psycopg.connect(self.database_url) as conn:
            count = conn.execute(
                "SELECT count(*) FROM chronicle.ingestion_chunks WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            self.assertEqual(int(count), worker.FAKE_CHUNKS_PER_JOB)

    def _store_fixture_bytes(self, storage_dir, data: bytes) -> tuple[uuid.UUID, uuid.UUID, str]:
        """Store revision bytes on disk + rows; returns (doc, revision, sha)."""
        import documents

        sha = hashlib.sha256(data).hexdigest()
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title="卷一")
            revision_id = uuid.uuid4()
            storage_key = f"documents/{document_id}/{revision_id}.txt"
            documents.write_source_file(storage_dir, storage_key, data)
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO chronicle.document_revisions(
                        revision_id, document_id, revision_no,
                        source_sha256, source_bytes, source_media_type,
                        filename, storage_key, content_chars
                    ) VALUES (%s, %s, 1, %s, %s, 'text/plain', 'juan1.txt', %s, %s)
                    """,
                    (revision_id, document_id, sha, len(data), storage_key, len(data)),
                )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
        return job_id, revision_id, sha

    def test_production_loader_runs_real_path(self) -> None:
        # D-4: the deployed loader (stored bytes + decode + hash verify)
        # drives real segmentation end to end.
        import tempfile

        text, _, config = _fixture()
        with tempfile.TemporaryDirectory() as tmp:
            job_id, _, sha = self._store_fixture_bytes(
                tmp, text.encode("utf-8")
            )
            loader = worker.build_revision_source(self.database_url, tmp)
            result = worker.run_once(
                self.database_url, worker="worker-c1t5",
                revision_source=loader, segmentation_config=config,
                allow_fake_after_real_source=True,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result[1], "completed")
            with psycopg.connect(self.database_url) as conn:
                sections = conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_sections WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0]
                self.assertGreaterEqual(int(sections), 3)

    def test_production_loader_missing_file_fails_closed(self) -> None:
        # D-4: a revision row whose bytes are gone fails the job; the
        # worker must not silently complete it through fake checkpoints.
        import tempfile

        text, _, config = _fixture()
        with tempfile.TemporaryDirectory() as tmp:
            job_id, _, _ = self._store_fixture_bytes(tmp, text.encode("utf-8"))
            with psycopg.connect(self.database_url) as conn:
                key = conn.execute(
                    """
                    SELECT r.storage_key
                    FROM chronicle.document_revisions r
                    JOIN chronicle.ingestion_jobs j ON j.revision_id = r.revision_id
                    WHERE j.job_id = %s
                    """,
                    (job_id,),
                ).fetchone()[0]
            Path(tmp, *key.split("/")).unlink()
            loader = worker.build_revision_source(self.database_url, tmp)
            result = worker.run_once(
                self.database_url, worker="worker-c1t5",
                revision_source=loader, segmentation_config=config,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result[1], "failed")

    def test_production_loader_tampered_file_fails_closed(self) -> None:
        # D-4: bytes that no longer match the immutable revision hash fail.
        import tempfile

        text, _, config = _fixture()
        with tempfile.TemporaryDirectory() as tmp:
            job_id, _, _ = self._store_fixture_bytes(tmp, text.encode("utf-8"))
            with psycopg.connect(self.database_url) as conn:
                key = conn.execute(
                    """
                    SELECT r.storage_key
                    FROM chronicle.document_revisions r
                    JOIN chronicle.ingestion_jobs j ON j.revision_id = r.revision_id
                    WHERE j.job_id = %s
                    """,
                    (job_id,),
                ).fetchone()[0]
            Path(tmp, *key.split("/")).write_bytes("後人竄改。".encode("utf-8"))
            loader = worker.build_revision_source(self.database_url, tmp)
            result = worker.run_once(
                self.database_url, worker="worker-c1t5",
                revision_source=loader, segmentation_config=config,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result[1], "failed")


if __name__ == "__main__":
    unittest.main()
