"""PostgreSQL 18 integration tests for T10 review source contexts/sources."""

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
from urllib.parse import quote
from urllib.request import Request, urlopen

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
ROOT = HERE.parents[2]
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from server import handler_class  # noqa: E402

import control_plane  # noqa: E402
import staged_store  # noqa: E402
from common import sha256_json  # noqa: E402
from migrations import apply_migrations  # noqa: E402
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


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


PART_A = "曹操字孟德，沛國譙人也。𠀋\n瑜、普為左右督。\n"
PART_B = "與曹公戰於赤壁，大破之。曹操、曹操。\n"
NORMALIZED = PART_A + PART_B


def _anchor(
    *, anchor_id: str, chapter_id: str, revision_id: str, source_sha: str,
    normalized_sha: str, quote: str, occurrence: int, text: str,
    first_block: str = "b_001", last_block: str = "b_001",
) -> dict:
    positions: list[int] = []
    start = 0
    while True:
        found = text.find(quote, start)
        if found < 0:
            break
        positions.append(found)
        start = found + max(len(quote), 1)
    assert len(positions) >= occurrence, f"quote {quote!r} occurs {len(positions)}x"
    pos = positions[occurrence - 1]
    return {
        "anchor_id": anchor_id,
        "revision_id": revision_id,
        "chapter_id": chapter_id,
        "source_sha256": source_sha,
        "normalized_sha256": normalized_sha,
        "first_block_id": first_block,
        "last_block_id": last_block,
        "quote": quote,
        "quote_sha256": _sha_text(quote),
        "occurrence": occurrence,
        "start": pos,
        "end": pos + len(quote),
    }


def _candidate_bundle(*, title: str, entities: list[dict], claims: list[dict],
                      record_sources: list[dict], mentions: list[dict],
                      blocks: list[dict]) -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001", "kind": "source", "source_type": "book",
            "title": title, "author": "陳壽", "language": "lzh",
            "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
        },
        "entities": entities,
        "events": [],
        "claims": claims,
        "warnings": [],
        "_record_sources": record_sources,
        "_mentions": mentions,
        "_blocks": blocks,
    }


def _entity(temp_id: str, name: str, *, mentions: list[dict] | None = None) -> dict:
    return {
        "temp_id": temp_id, "kind": "entity", "type": "person",
        "canonical_name": name, "aliases": [],
        "mentions": mentions if mentions is not None else [{"text": name}],
        "resolution": {"status": "unresolved"},
        "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
    }


def _claim(temp_id: str, subject_ref: str, text: str) -> dict:
    return {
        "temp_id": temp_id, "kind": "claim",
        "subject": {"kind": "entity_ref", "ref": subject_ref},
        "predicate": "served_as",
        "object": None,
        "evidence": {"text": text, "source_ref": "src_001", "locator": {}},
        "assessment": {"status": "unassessed"},
        "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
    }


class ReviewSourceContextPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t10_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                f'CREATE DATABASE "{self.database_name}"'
            )
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        raw = "﻿".encode("utf-8") + NORMALIZED.replace("\n", "\r\n").encode("utf-8")
        self.source_sha = hashlib.sha256(raw).hexdigest()
        self.normalized_sha = _sha_text(NORMALIZED)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            document_id = control_plane.create_document(conn, title="三國志合裝本")
            self.revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=self.source_sha,
                source_bytes=len(raw),
                source_media_type="text/plain",
                filename="he 装本.md",
                language="lzh",
                source_label="test edition",
            )
            row = conn.execute(
                "SELECT storage_key FROM chronicle.document_revisions WHERE revision_id = %s",
                (self.revision_id,),
            ).fetchone()
            self.storage_key = row[0]
            self.job_id = control_plane.queue_job(conn, revision_id=self.revision_id)
            control_plane.claim_job(conn, worker="t10", job_id=self.job_id)
            control_plane.set_job_status(conn, job_id=self.job_id, status="needs_review")
            conn.commit()
        self.storage_dir = tempfile.mkdtemp(prefix="chronicle-t10-")
        (Path(self.storage_dir) / self.storage_key).parent.mkdir(parents=True, exist_ok=True)
        (Path(self.storage_dir) / self.storage_key).write_bytes(raw)

        self.new_bundle = f"rev-{self.revision_id.hex[:8]}"
        with psycopg.connect(self.database_url) as conn:
            staged_store.persist_bundle(conn, self.new_bundle, {
                "schema_version": "0.1",
                "source": {
                    "temp_id": "src_001", "kind": "source", "source_type": "book",
                    "title": "三國志合裝本", "author": "陳壽", "language": "lzh",
                    "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
                },
                "entities": [
                    {**_entity("ent_000001", "曹操"), "temp_id": "ent_000001"},
                    {
                        "temp_id": "ent_001001", "kind": "entity", "type": "person",
                        "canonical_name": "曹操", "aliases": [], "mentions": [],
                        "resolution": {"status": "unresolved"},
                        "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
                    },
                ],
                "events": [],
                "claims": [
                    {
                        "temp_id": "clm_000001", "kind": "claim",
                        "subject": {"kind": "entity_ref", "ref": "ent_000001"},
                        "predicate": "served_as",
                        "object": None,
                        "evidence": {
                            "text": "瑜、普為左右督", "source_ref": "src_001",
                            "locator": {"work": "三國志"},
                        },
                        "assessment": {"status": "unassessed"},
                        "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
                    }
                ],
                "warnings": [],
            })
            staged_store.persist_bundle(conn, "pub", {
                "schema_version": "0.1",
                "source": {
                    "temp_id": "src_001", "kind": "source", "source_type": "book",
                    "title": "舊刊本", "author": "陳壽", "language": "lzh",
                    "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
                },
                "entities": [{**_entity("ent_pub_001", "曹操"), "temp_id": "ent_pub_001"}],
                "events": [],
                "claims": [],
                "warnings": [],
            })
            conn.commit()
        self._insert_chapter_artifacts()
        with psycopg.connect(self.database_url) as conn:
            pair_payload = {
                "scope": "resolution",
                "review_mode": "chapter_pair",
                "link_kind": "entity",
                "candidate_id": "ec_001",
                "resolution_sha256": _sha_text("within-resolution"),
                "left": {"bundle": self.new_bundle, "ref": "ent_000001"},
                "right": {"bundle": self.new_bundle, "ref": "ent_001001"},
                "members": [{
                    "candidate_key": f"{_sha_text('within-resolution')}:ec_001",
                    "resolution_sha256": _sha_text("within-resolution"),
                    "candidate_id": "ec_001",
                    "link_kind": "entity",
                    "left": {"bundle": self.new_bundle, "ref": "ent_000001"},
                    "right": {"bundle": self.new_bundle, "ref": "ent_001001"},
                    "signals": ["shared stable surface: 曹操"],
                }],
                "member_count": 1,
                "signals": ["shared stable surface: 曹操"],
                "initial_decision": "uncertain",
                "blocking": True,
                "allowed_decisions": ["same_entity", "not_same", "uncertain"],
                "decision": None,
            }
            self.pair_review_id = control_plane.open_review_item(
                conn, job_id=self.job_id, kind="stage_gate", payload=pair_payload,
            )
            batch_payload = {
                "scope": "resolution",
                "review_mode": "published_batch",
                "link_kind": "entity",
                "candidate_id": "ec_101",
                "resolution_sha256": _sha_text("cross-resolution"),
                "left": {"bundle": "pub", "ref": "ent_pub_001"},
                "right": {"bundle": self.new_bundle, "ref": "ent_000001"},
                "members": [
                    {
                        "candidate_key": f"{_sha_text('cross-resolution')}:ec_101",
                        "resolution_sha256": _sha_text("cross-resolution"),
                        "candidate_id": "ec_101",
                        "link_kind": "entity",
                        "left": {"bundle": "pub", "ref": "ent_pub_001"},
                        "right": {"bundle": self.new_bundle, "ref": "ent_000001"},
                        "signals": ["shared stable surface: 曹操"],
                    },
                    {
                        "candidate_key": f"{_sha_text('cross-resolution')}:ec_102",
                        "resolution_sha256": _sha_text("cross-resolution"),
                        "candidate_id": "ec_102",
                        "link_kind": "entity",
                        "left": {"bundle": "pub", "ref": "ent_pub_001"},
                        "right": {"bundle": self.new_bundle, "ref": "ent_001001"},
                        "signals": ["shared stable surface: 曹操"],
                    },
                ],
                "member_count": 2,
                "group_count": 2,
                "groups": [
                    {
                        "review_group_id": "rg_1",
                        "member_count": 1,
                        "signals": [],
                        "members": [{
                            "candidate_key": f"{_sha_text('cross-resolution')}:ec_101",
                            "resolution_sha256": _sha_text("cross-resolution"),
                            "candidate_id": "ec_101",
                            "link_kind": "entity",
                            "left": {"bundle": "pub", "ref": "ent_pub_001"},
                            "right": {"bundle": self.new_bundle, "ref": "ent_000001"},
                            "signals": [],
                        }],
                    },
                    {
                        "review_group_id": "rg_2",
                        "member_count": 1,
                        "signals": [],
                        "members": [{
                            "candidate_key": f"{_sha_text('cross-resolution')}:ec_102",
                            "resolution_sha256": _sha_text("cross-resolution"),
                            "candidate_id": "ec_102",
                            "link_kind": "entity",
                            "left": {"bundle": "pub", "ref": "ent_pub_001"},
                            "right": {"bundle": self.new_bundle, "ref": "ent_001001"},
                            "signals": [],
                        }],
                    },
                ],
                "signals": [],
                "initial_decision": "uncertain",
                "blocking": True,
                "allowed_decisions": ["same_entity", "not_same", "uncertain"],
                "decision": None,
            }
            self.batch_review_id = control_plane.open_review_item(
                conn, job_id=self.job_id, kind="stage_gate", payload=batch_payload,
            )
            # Legacy partial fixture on the same job: staged-only, no chapter
            # artifact covers it, so its contexts must read unavailable.
            legacy_payload = {
                "scope": "resolution",
                "link_kind": "entity",
                "candidate_id": "legacy-1",
                "resolution_sha256": _sha_text("legacy-resolution"),
                "left": {"bundle": "pub", "ref": "ent_pub_001"},
                "right": {"bundle": "pub", "ref": "ent_pub_001"},
                "signals": [],
                "initial_decision": "uncertain",
                "blocking": True,
                "allowed_decisions": ["same_entity", "not_same", "uncertain"],
                "decision": None,
            }
            self.legacy_review_id = control_plane.open_review_item(
                conn, job_id=self.job_id, kind="stage_gate", payload=legacy_payload,
            )
            conn.commit()
        handler = handler_class(self.database_url, storage_dir=self.storage_dir)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _insert_chapter_artifacts(self) -> None:
        rev = str(self.revision_id)
        anchors_a = [
            _anchor(
                anchor_id="anc_rs_a", chapter_id="ch_A", revision_id=rev,
                source_sha=self.source_sha, normalized_sha=self.normalized_sha,
                quote="瑜、普為左右督", occurrence=1, text=NORMALIZED,
            ),
            _anchor(
                anchor_id="anc_men_a", chapter_id="ch_A", revision_id=rev,
                source_sha=self.source_sha, normalized_sha=self.normalized_sha,
                quote="孟德", occurrence=1, text=NORMALIZED,
            ),
            _anchor(
                anchor_id="anc_tr_a", chapter_id="ch_A", revision_id=rev,
                source_sha=self.source_sha, normalized_sha=self.normalized_sha,
                quote=PART_A.strip(), occurrence=1, text=NORMALIZED,
                first_block="b_001", last_block="b_001",
            ),
        ]
        anchors_b = [
            _anchor(
                anchor_id="anc_rs_b", chapter_id="ch_B", revision_id=rev,
                source_sha=self.source_sha, normalized_sha=self.normalized_sha,
                quote="大破之", occurrence=1, text=NORMALIZED,
            ),
            _anchor(
                anchor_id="anc_tr_b", chapter_id="ch_B", revision_id=rev,
                source_sha=self.source_sha, normalized_sha=self.normalized_sha,
                quote=PART_B.strip(), occurrence=1, text=NORMALIZED,
                first_block="b_001", last_block="b_001",
            ),
        ]
        self.anchor_rs_a = anchors_a[0]["anchor_id"]
        self.anchor_tr_b = anchors_b[1]["anchor_id"]
        candidate_a = {
            "schema": "chronicle.chapter-candidate", "version": "0.1",
            "chapter_id": "ch_A",
            "bundle": {
                "schema_version": "0.1",
                "source": {
                    "temp_id": "src_001", "kind": "source", "source_type": "book",
                    "title": "三國志合裝本", "author": "陳壽", "language": "lzh",
                    "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
                },
                "entities": [_entity("ent_001", "曹操", mentions=[{"text": "曹操"}, {"text": "孟德"}])],
                "events": [],
                "claims": [_claim("clm_001", "ent_001", "瑜、普為左右督")],
                "warnings": [],
            },
            "translation": {
                "language": "zh-CN",
                "blocks": [{
                    "block_id": "t_001", "text": "曹操字孟德",
                    "source_block_ids": ["b_001"],
                    "entity_refs": [{"kind": "entity", "ref": "ent_001"}],
                    "event_refs": [],
                }],
            },
            "mentions": [{
                "mention_id": "m_001", "surface": "孟德", "contextual": False,
                "status": "resolved", "target_ref": "ent_001", "candidate_refs": [],
                "selection": {
                    "first_block_id": "b_001", "last_block_id": "b_001",
                    "quote": "孟德", "occurrence": 1,
                },
            }],
            "record_sources": [{
                "record_ref": "ent_001",
                "selections": [{
                    "first_block_id": "b_001", "last_block_id": "b_001",
                    "quote": "瑜、普為左右督", "occurrence": 1,
                }],
            }],
            "warnings": [],
        }
        candidate_b = {
            "schema": "chronicle.chapter-candidate", "version": "0.1",
            "chapter_id": "ch_B",
            "bundle": {
                "schema_version": "0.1",
                "source": {
                    "temp_id": "src_001", "kind": "source", "source_type": "book",
                    "title": "三國志合裝本", "author": "陳壽", "language": "lzh",
                    "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
                },
                "entities": [{
                    "temp_id": "ent_001", "kind": "entity", "type": "person",
                    "canonical_name": "曹操", "aliases": [], "mentions": [],
                    "resolution": {"status": "unresolved"},
                    "extraction": {"method": "model", "job_id": "t10", "confidence": 0.8},
                }],
                "events": [],
                "claims": [],
                "warnings": [],
            },
            "translation": {
                "language": "zh-CN",
                "blocks": [{
                    "block_id": "t_001", "text": "赤壁大破",
                    "source_block_ids": ["b_001"],
                    "entity_refs": [{"kind": "entity", "ref": "ent_001"}],
                    "event_refs": [],
                }],
            },
            "mentions": [],
            "record_sources": [{
                "record_ref": "ent_001",
                "selections": [{
                    "first_block_id": "b_001", "last_block_id": "b_001",
                    "quote": "大破之", "occurrence": 1,
                }],
            }],
            "warnings": [],
        }
        with psycopg.connect(self.database_url) as conn:
            for chapter_id, index, candidate, anchors in (
                ("ch_A", 0, candidate_a, anchors_a),
                ("ch_B", 1, candidate_b, anchors_b),
            ):
                chunk_id = control_plane.record_chunk(
                    conn, job_id=self.job_id, section_id=None, chunk_index=index,
                    source_start=0, source_end=len(NORMALIZED),
                    source_sha256=self.source_sha, content_sha256=self.normalized_sha,
                )
                run_id, _ = control_plane.record_chunk_run(
                    conn, chunk_id=chunk_id, status="completed", worker="t10",
                    checkpoint={"request_fingerprint": "0" * 64},
                )
                artifact = {
                    "schema": "chronicle.chapter-artifact", "version": "0.1",
                    "chapter_id": chapter_id, "revision_id": rev,
                    "source_sha256": self.source_sha,
                    "normalized_sha256": self.normalized_sha,
                    "candidate": candidate,
                    "candidate_sha256": sha256_json(candidate),
                    "anchors": anchors,
                    "request_fingerprint": "0" * 64,
                    "producing_run": {
                        "run_id": str(run_id), "model": "fixture",
                        "prompt_schema_version": "v1",
                    },
                }
                conn.execute(
                    """
                    INSERT INTO chronicle.chapter_artifacts(
                        artifact_sha256, job_id, revision_id, document_id,
                        chapter_id, chapter_index, chunk_id, producing_run_id,
                        request_fingerprint, candidate_sha256, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        sha256_json(artifact), self.job_id, self.revision_id,
                        conn.execute(
                            "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
                            (self.revision_id,),
                        ).fetchone()[0],
                        chapter_id, index, chunk_id, run_id,
                        "0" * 64, sha256_json(candidate), Jsonb(artifact),
                    ),
                )
            conn.commit()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{self.database_name}" WITH (FORCE)')

    def _json(self, method: str, path: str):
        req = Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        try:
            with urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _collect_contexts(self, base: str) -> tuple[list[dict], dict]:
        items: list[dict] = []
        cursor: str | None = None
        payload: dict = {}
        for _ in range(10):
            path = base
            if cursor:
                glue = "&" if "?" in path else "?"
                path = f"{path}{glue}cursor={quote(cursor, safe='')}"
            status, payload = self._json("GET", path)
            self.assertEqual(status, 200, payload)
            items.extend(payload["items"])
            cursor = payload["next_cursor"]
            if not cursor:
                break
        else:
            self.fail("contexts pagination did not terminate")
        return items, payload

    def test_pair_detail_and_contexts_cover_both_ends(self) -> None:
        status, payload = self._json("GET", f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}")
        self.assertEqual(status, 200, payload)
        detail = payload["review"]
        self.assertIn("source_contexts", detail)
        self.assertEqual(detail["source_contexts"]["total"], 2)
        refs = {(item["bundle"], item["record_ref"]) for item in detail["source_contexts"]["items"]}
        self.assertEqual(refs, {(self.new_bundle, "ent_000001"), (self.new_bundle, "ent_001001")})
        by_ref = {item["record_ref"]: item for item in detail["source_contexts"]["items"]}
        # Entity with a direct Claim keeps it; the Claim-free entity still
        # reads its mandatory record_sources原文.
        self.assertIn("direct_claim", by_ref["ent_000001"]["evidence_kinds"])
        self.assertIn("record_source", by_ref["ent_001001"]["evidence_kinds"])
        self.assertTrue(by_ref["ent_001001"]["available"])
        self.assertGreater(by_ref["ent_001001"]["anchor_count"], 0)

        items, last = self._collect_contexts(
            f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/contexts?limit=1"
        )
        self.assertEqual(len(items), 2)
        self.assertFalse(last["has_more"])
        self.assertIsNone(last["next_cursor"])

    def test_batch_groups_and_all_members_are_addressable(self) -> None:
        items, last = self._collect_contexts(
            f"{STUDIO_REVIEWS_PREFIX}/{self.batch_review_id}/contexts"
        )
        self.assertEqual(last["total"], 3)
        self.assertEqual(len(items), 3)
        refs = {(item["bundle"], item["record_ref"]) for item in items}
        self.assertIn((self.new_bundle, "ent_001001"), refs)
        self.assertIn(("pub", "ent_pub_001"), refs)

        status, payload = self._json(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.batch_review_id}/contexts?group_id=rg_2"
        )
        self.assertEqual(status, 200, payload)
        refs = {(item["bundle"], item["record_ref"]) for item in payload["items"]}
        self.assertIn((self.new_bundle, "ent_001001"), refs)

        status, payload = self._json(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.batch_review_id}/contexts?group_id=rg_missing"
        )
        self.assertEqual(status, 404, payload)

        status, payload = self._json(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.batch_review_id}/contexts?limit=0"
        )
        self.assertEqual(status, 400, payload)
        status, payload = self._json(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.batch_review_id}/contexts?cursor=bogus"
        )
        self.assertEqual(status, 400, payload)

    def test_window_source_is_exact_and_highlighted(self) -> None:
        status, payload = self._json(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/sources/{self.anchor_rs_a}",
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["view"], "window")
        self.assertIn("瑜、普為左右督", payload["text"])
        highlighted = "".join(seg["text"] for seg in payload["segments"] if seg["highlight"])
        self.assertEqual(highlighted, "瑜、普為左右督")
        self.assertEqual(payload["source_sha256"], self.source_sha)
        self.assertFalse(payload["has_more"])
        # Non-BMP char survives the server-side slice as one code point.
        self.assertIn("𠀋", NORMALIZED)

    def test_chapter_view_pages_without_silent_truncation(self) -> None:
        status, payload = self._json(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/sources/{self.anchor_tr_b}?view=chapter",
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["view"], "chapter")
        self.assertFalse(payload["has_more"])
        self.assertIsNone(payload["next_cursor"])
        self.assertIn("大破之", payload["text"])

        status, payload = self._json(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/sources/{self.anchor_tr_b}?view=chapter&cursor=bogus",
        )
        self.assertEqual(status, 400, payload)
        status, payload = self._json(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/sources/{self.anchor_tr_b}?view=full",
        )
        self.assertEqual(status, 400, payload)

    def test_cross_review_anchor_is_404_and_bad_anchor_is_404(self) -> None:
        status, payload = self._json(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.legacy_review_id}/sources/{self.anchor_rs_a}",
        )
        self.assertEqual(status, 404, payload)
        status, payload = self._json(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/sources/anc_does_not_exist",
        )
        self.assertEqual(status, 404, payload)

    def test_hash_drift_and_missing_file_are_409_without_fallback(self) -> None:
        path = Path(self.storage_dir) / self.storage_key
        original = path.read_bytes()
        try:
            path.write_bytes("篡改後的新版文字".encode("utf-8"))
            status, payload = self._json(
                "GET",
                f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/sources/{self.anchor_rs_a}",
            )
            self.assertEqual(status, 409, payload)
            self.assertEqual(payload["error"]["code"], "source_mismatch")
            path.unlink()
            status, payload = self._json(
                "GET",
                f"{STUDIO_REVIEWS_PREFIX}/{self.pair_review_id}/sources/{self.anchor_rs_a}",
            )
            self.assertEqual(status, 409, payload)
            self.assertEqual(payload["error"]["code"], "source_unavailable")
        finally:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)

    def test_legacy_fixture_without_location_is_unavailable(self) -> None:
        status, payload = self._json("GET", f"{STUDIO_REVIEWS_PREFIX}/{self.legacy_review_id}")
        self.assertEqual(status, 200, payload)
        contexts = payload["review"]["source_contexts"]
        self.assertEqual(contexts["total"], 1)
        item = contexts["items"][0]
        self.assertFalse(item["available"])
        self.assertEqual(item["unavailable_reason"], "legacy_fixture_without_location")
        # The original direct-Claim projection is preserved, not migrated.
        self.assertIn("display", payload["review"]["left_context"])


if __name__ == "__main__":
    unittest.main()
