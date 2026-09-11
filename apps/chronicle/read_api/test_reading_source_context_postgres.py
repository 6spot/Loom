"""PostgreSQL 18 integration tests for C2-R2-T09 0.2 source reading.

``continuous-reading.md`` §2/§6 requires the second-round reading adaptation to
keep first-round source semantics: a 0.2 ``chapter-artifact`` still carries the
same ``candidate``/``anchors`` payload, so the unique source reader
(``source_context.load_chapter_lookup`` plus the public ``/v0/chapters/...``
source route) must serve it with the same publication/anchor pinning policy as
0.1 — no second source service, no fallback to a newer revision.

The fixture builds a genuinely accepted 0.2 artifact through the T01
``reading_contract.accept_reading_candidate`` entry (the same one the worker
uses), persists it with a chapter publication, and verifies both the shared
Studio/public lookup and the public source window.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PERSISTENCE = ROOT / "apps" / "chronicle" / "persistence"
FIXTURES = ROOT / "apps" / "chronicle" / "ingestion" / "fixtures" / "c2r2-contract"
for path in (PERSISTENCE, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import canonical_store  # noqa: E402
import control_plane  # noqa: E402
import reading_contract  # noqa: E402
import source_context  # noqa: E402
from migrations import apply_migrations  # noqa: E402
from test_postgres_v0 import _control_url, _database_conninfo  # noqa: E402
import reader_chapters  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _uuid7() -> str:
    value = uuid.uuid4().int
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return str(uuid.UUID(int=value))


class ReadingSourceContextPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t09_source_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name))
            )
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self.conn = psycopg.connect(self.database_url)
        apply_migrations(self.conn)
        self.storage_dir = tempfile.mkdtemp(prefix="chronicle-t09-source-")
        self.artifact = self._seed_accepted_reading_chapter()

    def tearDown(self) -> None:
        self.conn.close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(self.database_name)
                )
            )

    # -- fixture -------------------------------------------------------

    def _seed_accepted_reading_chapter(self) -> dict:
        request = _load("request.json")
        candidate = _load("candidate-valid.json")
        text = request["normalized_text"]
        raw = text.encode("utf-8")
        source_sha256 = hashlib.sha256(raw).hexdigest()

        document_id = control_plane.create_document(self.conn, title="赤壁章")
        revision_id, _ = control_plane.create_revision(
            self.conn,
            document_id=document_id,
            source_sha256=source_sha256,
            source_bytes=len(raw),
            source_media_type="text/plain",
            filename="chibi.md",
        )
        storage_key = self.conn.execute(
            "SELECT storage_key FROM chronicle.document_revisions WHERE revision_id = %s",
            (revision_id,),
        ).fetchone()[0]
        target = Path(self.storage_dir) / storage_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

        job_id = control_plane.queue_job(self.conn, revision_id=revision_id)
        control_plane.claim_job(self.conn, worker="t09-source", job_id=job_id)
        section_id = control_plane.create_section(
            self.conn,
            job_id=job_id,
            section_index=0,
            label="章",
            source_start=0,
            source_end=len(text),
        )
        chunk_id = control_plane.record_chunk(
            self.conn,
            job_id=job_id,
            section_id=section_id,
            chunk_index=0,
            source_start=0,
            source_end=len(text),
            source_sha256=source_sha256,
            content_sha256=source_sha256,
        )
        control_plane.set_chunk_status(self.conn, chunk_id=chunk_id, status="running")
        run_id, _ = control_plane.record_chunk_run(
            self.conn, chunk_id=chunk_id, status="running", worker="t09-source"
        )

        # The 0.2 candidate is accepted through the production T01 entry with
        # the request rebound to this revision's exact bytes: the artifact
        # keeps program-resolved reading annotations and anchors.
        bound_request = copy.deepcopy(request)
        bound_request["revision_id"] = str(revision_id)
        bound_request["source_sha256"] = source_sha256
        bound_request["normalized_sha256"] = source_sha256
        artifact = reading_contract.accept_reading_candidate(
            bound_request,
            candidate,
            producing_run={
                "run_id": str(run_id),
                "model": "fixture",
                "prompt_schema_version": "v1",
            },
        )
        self.assertEqual("0.2", artifact["version"])

        self.conn.execute(
            """
            INSERT INTO chronicle.chapter_artifacts(
                artifact_sha256, job_id, revision_id, document_id, chapter_id,
                chapter_index, chunk_id, producing_run_id, request_fingerprint,
                candidate_sha256, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                artifact["artifact_sha256"],
                job_id,
                revision_id,
                document_id,
                artifact["chapter_id"],
                request["chapter_index"],
                chunk_id,
                run_id,
                artifact["request_fingerprint"],
                artifact["candidate_sha256"],
                json.dumps(artifact),
            ),
        )

        catalog_sha, _ = canonical_store.persist_catalog(
            self.conn,
            {
                "schema": "chronicle.canonical-catalog",
                "version": "0.1",
                "canonical_entities": [],
                "canonical_events": [],
                "event_relations": [],
                "warnings": [{"code": "fixture:t09-source"}],
            },
        )
        publication_id = _uuid7()
        assembled_sha = hashlib.sha256(b"assembled").hexdigest()
        publication = {
            "schema": "chronicle.chapter-publication",
            "version": "0.1",
            "chapter_id": artifact["chapter_id"],
            "chapter_index": request["chapter_index"],
            "revision_id": str(revision_id),
            "artifact_sha256": artifact["artifact_sha256"],
            "catalog_sha256": catalog_sha,
            "assembled_bundle_sha256": assembled_sha,
            "translation_blocks": artifact["candidate"]["translation"]["blocks"],
            "anchors": artifact["anchors"],
        }
        self.conn.execute(
            """
            INSERT INTO chronicle.chapter_publications(
                publication_id, artifact_sha256, catalog_sha256,
                assembled_bundle_sha256, document_id, revision_id, job_id,
                chapter_id, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                publication_id,
                artifact["artifact_sha256"],
                catalog_sha,
                assembled_sha,
                document_id,
                revision_id,
                job_id,
                artifact["chapter_id"],
                json.dumps(publication),
            ),
        )
        self.conn.commit()
        return {
            "artifact": artifact,
            "publication_id": publication_id,
            "job_id": job_id,
            "revision_id": revision_id,
            "chapter_id": artifact["chapter_id"],
            "catalog_sha": catalog_sha,
            "source_sha256": source_sha256,
        }

    # -- tests ---------------------------------------------------------

    def test_shared_lookup_indexes_the_accepted_0_2_artifact(self) -> None:
        lookup = source_context.load_chapter_lookup(self.conn, job_id=self.artifact["job_id"])
        chapter = lookup["chapters"].get(self.artifact["chapter_id"])
        self.assertIsNotNone(chapter, lookup["chapters"].keys())
        self.assertEqual(chapter["artifact_sha256"], self.artifact["artifact"]["artifact_sha256"])
        self.assertEqual((chapter["chapter_start"], chapter["chapter_end"]), (0, 36))
        # The candidate's record/mention/translation refs and the artifact
        # anchors are all visible to the single reader.
        self.assertTrue(lookup["by_ref"], "0.2 candidate refs were not indexed")
        anchor_ids = {anchor["anchor_id"] for anchor in self.artifact["artifact"]["anchors"]}
        self.assertTrue(anchor_ids)
        self.assertTrue(anchor_ids.issubset(set(lookup["anchors_by_id"])))

    def test_public_source_window_reads_the_0_2_revision(self) -> None:
        anchor = self.artifact["artifact"]["anchors"][0]
        status, payload = reader_chapters.dispatch_chapters(
            self.conn,
            method="GET",
            path=(
                f"/v0/chapters/{self.artifact['publication_id']}"
                f"/sources/{anchor['anchor_id']}"
            ),
            raw_query="view=window",
            source_dir=self.storage_dir,
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["source_sha256"], self.artifact["source_sha256"])
        self.assertEqual(payload["anchor_id"], anchor["anchor_id"])
        self.assertIn(anchor["quote"], payload["text"])
        self.assertEqual(
            "".join(segment["text"] for segment in payload["segments"]),
            payload["text"],
        )

    def test_cross_publication_anchor_stays_not_found(self) -> None:
        unknown_anchor = "anc_0000000000000000"
        status, payload = reader_chapters.dispatch_chapters(
            self.conn,
            method="GET",
            path=(
                f"/v0/chapters/{self.artifact['publication_id']}"
                f"/sources/{unknown_anchor}"
            ),
            raw_query="view=window",
            source_dir=self.storage_dir,
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
