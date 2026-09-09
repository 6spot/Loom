"""PostgreSQL 18 integration tests for T14 public chapter API.

Two revisions of one document model old/new reading versions: job J1
publishes two chapters of revision R1, job J2 publishes two chapters of
revision R2 (different bytes). A third job holds an accepted-but-unpublished
artifact that must never leak into the public directory.

Coverage: published-only stable directory + cursor paging, complete
translation detail (head/tail + claim-less blocks, many-to-many refs with
revision-pinned canonical ids), cross-publication/cross-version 404s,
old-revision pinning, hash-drift/missing-file 409s without fallback, window
+ chapter paging, 400/404/405/409 codes, read-only + no-model-call proof,
and explicit failure on unmapped references.
"""

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

import assembly  # noqa: E402
import canonical_store  # noqa: E402
import chapter_contract  # noqa: E402
import chapter_store  # noqa: E402
import control_plane  # noqa: E402
import resolve_publish  # noqa: E402
import staged_store  # noqa: E402
from common import sha256_json  # noqa: E402
from migrations import apply_migrations  # noqa: E402

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


def _uuid7(n: int) -> str:
    assert 0 < n < 0x1000, n
    return f"019535d9-3df7-7{n:03x}-8000-{n:012x}"


PART_A = "先主姓劉諱備字玄德涿郡涿縣人也。\n𠀋\n"
PART_B = "瑜字公瑾廬江舒人也。\n曹操與孫權會獵於江陵曹操大破之。\n"
PART_B2 = "瑜字公瑾廬江舒人也。\n曹操大破於赤壁。\n"
TEXT_R1 = PART_A + PART_B
TEXT_R2 = PART_A + PART_B2
LEN_A = len(PART_A)

R1_ONLY_QUOTE = "會獵於江陵"


def _anchor(
    *, anchor_id: str, chapter_id: str, revision_id: str, source_sha: str,
    normalized_sha: str, quote: str, occurrence: int, text: str,
    chapter_start: int = 0, chapter_end: int | None = None,
) -> dict:
    chapter_end = len(text) if chapter_end is None else chapter_end
    window = text[chapter_start:chapter_end]
    positions: list[int] = []
    start = 0
    while True:
        found = window.find(quote, start)
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
        "first_block_id": "b_001",
        "last_block_id": "b_001",
        "quote": quote,
        "quote_sha256": _sha_text(quote),
        "occurrence": occurrence,
        "start": pos,
        "end": pos + len(quote),
    }


def _entity(temp_id: str, name: str) -> dict:
    return {
        "temp_id": temp_id, "kind": "entity", "type": "person",
        "canonical_name": name, "aliases": [],
        "mentions": [{"text": name}],
        "resolution": {"status": "unresolved"},
        "extraction": {"method": "model", "job_id": "t14", "confidence": 0.8},
    }


def _event(temp_id: str, title: str) -> dict:
    return {
        "temp_id": temp_id, "kind": "event", "type": "battle",
        "title": title, "summary": title,
        "time": None, "participants": [], "places": [],
        "extraction": {"method": "model", "job_id": "t14", "confidence": 0.8},
    }


def _claim(temp_id: str, subject_ref: str, text: str) -> dict:
    return {
        "temp_id": temp_id, "kind": "claim",
        "subject": {"kind": "entity_ref", "ref": subject_ref},
        "predicate": "served_as",
        "object": None,
        "evidence": {"text": text, "source_ref": "src_001", "locator": {}},
        "assessment": {"status": "unassessed"},
        "extraction": {"method": "model", "job_id": "t14", "confidence": 0.8},
    }


def _candidate(
    *, chapter_id: str, title: str, entities: list[dict], events: list[dict],
    claims: list[dict], blocks: list[dict], mentions: list[dict],
    record_sources: list[dict],
) -> dict:
    return {
        "schema": "chronicle.chapter-candidate", "version": "0.1",
        "chapter_id": chapter_id,
        "bundle": {
            "schema_version": "0.1",
            "source": {
                "temp_id": "src_001", "kind": "source", "source_type": "book",
                "title": title, "author": "陳壽", "language": "lzh",
                "extraction": {"method": "model", "job_id": "t14", "confidence": 0.8},
            },
            "entities": entities,
            "events": events,
            "claims": claims,
            "warnings": [],
        },
        "translation": {"language": "zh-CN", "blocks": blocks},
        "mentions": mentions,
        "record_sources": record_sources,
        "warnings": [],
    }


def _block(block_id: str, text: str, entity_refs: list[str], event_refs: list[str]) -> dict:
    return {
        "block_id": block_id, "text": text,
        "source_block_ids": ["b_001"],
        "entity_refs": [{"kind": "entity", "ref": ref} for ref in entity_refs],
        "event_refs": [{"kind": "event", "ref": ref} for ref in event_refs],
    }


def _selection(quote: str, occurrence: int = 1) -> dict:
    return {
        "first_block_id": "b_001", "last_block_id": "b_001",
        "quote": quote, "occurrence": occurrence,
    }


class ReaderChaptersPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t14_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.database_name}"')
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        raw_r1 = TEXT_R1.encode("utf-8")
        raw_r2 = TEXT_R2.encode("utf-8")
        self.source_sha_r1 = hashlib.sha256(raw_r1).hexdigest()
        self.source_sha_r2 = hashlib.sha256(raw_r2).hexdigest()
        self.normalized_r1 = _sha_text(TEXT_R1)
        self.normalized_r2 = _sha_text(TEXT_R2)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            document_id = control_plane.create_document(conn, title="三國志合裝本")
            self.revision_r1, rev_no_1 = control_plane.create_revision(
                conn, document_id=document_id,
                source_sha256=self.source_sha_r1, source_bytes=len(raw_r1),
                source_media_type="text/plain", filename="he-ben-a.md",
                language="lzh", source_label="test edition",
            )
            self.revision_r2, rev_no_2 = control_plane.create_revision(
                conn, document_id=document_id,
                source_sha256=self.source_sha_r2, source_bytes=len(raw_r2),
                source_media_type="text/plain", filename="he-ben-b.md",
                language="lzh", source_label="test edition",
            )
            self.assertEqual(1, rev_no_1)
            self.assertEqual(2, rev_no_2)
            row = conn.execute(
                "SELECT storage_key FROM chronicle.document_revisions WHERE revision_id = %s",
                (self.revision_r1,),
            ).fetchone()
            self.storage_key_r1 = row[0]
            row = conn.execute(
                "SELECT storage_key FROM chronicle.document_revisions WHERE revision_id = %s",
                (self.revision_r2,),
            ).fetchone()
            self.storage_key_r2 = row[0]
            self.job_r1 = control_plane.queue_job(conn, revision_id=self.revision_r1)
            self.job_r2 = control_plane.queue_job(conn, revision_id=self.revision_r2)
            # Accepted-but-unpublished job: same revision, own chapter row,
            # never published, must stay invisible to every public route.
            self.job_private = control_plane.queue_job(conn, revision_id=self.revision_r1)
            conn.commit()
        self.storage_dir = tempfile.mkdtemp(prefix="chronicle-t14-")
        for key, raw in (
            (self.storage_key_r1, raw_r1),
            (self.storage_key_r2, raw_r2),
        ):
            target = Path(self.storage_dir) / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self._publish_job(
            self.job_r1, self.revision_r1, TEXT_R1,
            self.source_sha_r1, self.normalized_r1, title_suffix="甲本",
            canon_base=100,
        )
        self._publish_job(
            self.job_r2, self.revision_r2, TEXT_R2,
            self.source_sha_r2, self.normalized_r2, title_suffix="甲本",
            canon_base=200,
        )
        self._insert_unpublished_artifact()
        handler = handler_class(self.database_url, storage_dir=self.storage_dir)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{self.database_name}" WITH (FORCE)')

    # -- fixture builders -------------------------------------------------

    def _remap(self, prefix: str, index: int, local: str) -> str:
        return assembly._remapped_chapter_id(prefix, index, local)

    def _chapter_specs(self, text: str) -> list[dict]:
        split = text.index(PART_A) + len(PART_A)
        return [
            {"chapter_id": "ch_A", "index": 0, "title": "先主傳",
             "start": 0, "end": split},
            {"chapter_id": "ch_B", "index": 1, "title": "周瑜傳",
             "start": split, "end": len(text)},
        ]

    def _build_candidates(
        self, *, revision_id: uuid.UUID, text: str,
        source_sha: str, normalized_sha: str, title_suffix: str,
    ) -> list[tuple[dict, dict, list[dict]]]:
        rev = str(revision_id)
        specs = self._chapter_specs(text)
        out = []
        for spec in specs:
            chapter_text = text[spec["start"]:spec["end"]]
            if spec["chapter_id"] == "ch_A":
                candidate = _candidate(
                    chapter_id="ch_A", title=f"三國志合裝本{title_suffix}",
                    entities=[_entity("ent_001", "劉備")],
                    events=[_event("evt_001", "先主出身")],
                    claims=[_claim("clm_001", "ent_001", "涿縣人也")],
                    blocks=[
                        _block("t_001", "劉備字玄德為涿縣人先主出身。",
                               ["ent_001"], ["evt_001"]),
                        _block("t_002", "此段無對應主張僅述源流。",
                               [], []),
                    ],
                    mentions=[{
                        "mention_id": "m_001", "surface": "玄德",
                        "contextual": False, "status": "resolved",
                        "target_ref": "ent_001", "candidate_refs": [],
                        "selection": _selection("玄德", 1),
                    }],
                    record_sources=[
                        {"record_ref": "ent_001",
                         "selections": [_selection("玄德", 1)]},
                        {"record_ref": "evt_001",
                         "selections": [_selection("涿縣人也", 1)]},
                        {"record_ref": "clm_001",
                         "selections": [_selection("涿縣人也", 1)]},
                    ],
                )
                anchors = [
                    _anchor(
                        anchor_id=f"anc_a_ent_{rev[:8]}", chapter_id="ch_A",
                        revision_id=rev, source_sha=source_sha,
                        normalized_sha=normalized_sha, quote="玄德",
                        occurrence=1, text=text,
                        chapter_start=spec["start"], chapter_end=spec["end"],
                    ),
                    _anchor(
                        anchor_id=f"anc_a_evt_{rev[:8]}", chapter_id="ch_A",
                        revision_id=rev, source_sha=source_sha,
                        normalized_sha=normalized_sha, quote="涿縣人也",
                        occurrence=1, text=text,
                        chapter_start=spec["start"], chapter_end=spec["end"],
                    ),
                ]
            else:
                quote_men = "曹操"
                occ_men = 2 if chapter_text.count("曹操") >= 2 else 1
                evt_quote = "赤壁" if "赤壁" in chapter_text else "江陵"
                candidate = _candidate(
                    chapter_id="ch_B", title=f"三國志合裝本{title_suffix}",
                    entities=[_entity("ent_001", "周瑜"), _entity("ent_002", "曹操")],
                    events=[_event("evt_001", "赤壁之會")],
                    claims=[_claim("clm_001", "ent_002", quote_men)],
                    blocks=[
                        _block("t_001", "周瑜與曹操會於赤壁。",
                               ["ent_001", "ent_002"], ["evt_001"]),
                        _block("t_002", "此段無對應主張僅述風物。",
                               [], []),
                    ],
                    mentions=[{
                        "mention_id": "m_001", "surface": quote_men,
                        "contextual": False, "status": "resolved",
                        "target_ref": "ent_002", "candidate_refs": [],
                        "selection": _selection(quote_men, occ_men),
                    }],
                    record_sources=[
                        {"record_ref": "ent_001",
                         "selections": [_selection("公瑾", 1)]},
                        {"record_ref": "ent_002",
                         "selections": [_selection(quote_men, occ_men)]},
                        {"record_ref": "evt_001",
                         "selections": [_selection(evt_quote, 1)]},
                        {"record_ref": "clm_001",
                         "selections": [_selection(quote_men, 1)]},
                    ],
                )
                anchors = [
                    _anchor(
                        anchor_id=f"anc_b_men_{rev[:8]}", chapter_id="ch_B",
                        revision_id=rev, source_sha=source_sha,
                        normalized_sha=normalized_sha, quote=quote_men,
                        occurrence=occ_men, text=text,
                        chapter_start=spec["start"], chapter_end=spec["end"],
                    ),
                    _anchor(
                        anchor_id=f"anc_b_rs_{rev[:8]}", chapter_id="ch_B",
                        revision_id=rev, source_sha=source_sha,
                        normalized_sha=normalized_sha, quote="公瑾",
                        occurrence=1, text=text,
                        chapter_start=spec["start"], chapter_end=spec["end"],
                    ),
                    _anchor(
                        anchor_id=f"anc_b_evt_{rev[:8]}", chapter_id="ch_B",
                        revision_id=rev, source_sha=source_sha,
                        normalized_sha=normalized_sha, quote=evt_quote,
                        occurrence=1, text=text,
                        chapter_start=spec["start"], chapter_end=spec["end"],
                    ),
                ]
            assert chapter_text, "chapter slice must be non-empty"
            out.append((spec, candidate, anchors))
        return out

    def _publish_job(
        self, job_id: uuid.UUID, revision_id: uuid.UUID, text: str,
        source_sha: str, normalized_sha: str, *, title_suffix: str,
        canon_base: int,
    ) -> None:
        label = resolve_publish.new_bundle_label(revision_id)
        built = self._build_candidates(
            revision_id=revision_id, text=text, source_sha=source_sha,
            normalized_sha=normalized_sha, title_suffix=title_suffix,
        )
        with psycopg.connect(self.database_url) as conn:
            document_id = conn.execute(
                "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
                (revision_id,),
            ).fetchone()[0]
            bundle_records: dict[str, list[dict]] = {
                "entities": [], "events": [], "claims": [],
            }
            local_to_revision: dict[str, str] = {}
            chapter_by_ref: dict[str, str] = {}
            for spec, candidate, anchors in built:
                index = spec["index"]
                chunk_id = control_plane.record_chunk(
                    conn, job_id=job_id, section_id=None, chunk_index=index,
                    source_start=spec["start"], source_end=spec["end"],
                    source_sha256=source_sha, content_sha256=normalized_sha,
                )
                run_id, _ = control_plane.record_chunk_run(
                    conn, chunk_id=chunk_id, status="completed", worker="t14",
                    checkpoint={"request_fingerprint": "0" * 64},
                )
                artifact = {
                    "schema": "chronicle.chapter-artifact", "version": "0.1",
                    "chapter_id": spec["chapter_id"],
                    "revision_id": str(revision_id),
                    "source_sha256": source_sha,
                    "normalized_sha256": normalized_sha,
                    "candidate": candidate,
                    "candidate_sha256": sha256_json(candidate),
                    "anchors": anchors,
                    "request_fingerprint": "0" * 64,
                    "producing_run": {
                        "run_id": str(run_id), "model": "fixture",
                        "prompt_schema_version": "v1",
                    },
                }
                artifact_sha = sha256_json(artifact)
                conn.execute(
                    """
                    INSERT INTO chronicle.chapter_artifacts(
                        artifact_sha256, job_id, revision_id, document_id,
                        chapter_id, chapter_index, chunk_id, producing_run_id,
                        request_fingerprint, candidate_sha256, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        artifact_sha, job_id, revision_id, document_id,
                        spec["chapter_id"], index, chunk_id, run_id,
                        "0" * 64, sha256_json(candidate), Jsonb(artifact),
                    ),
                )
                bundle = candidate["bundle"]
                for collection, prefix in (
                    ("entities", "ent"), ("events", "evt"), ("claims", "clm"),
                ):
                    for record in bundle.get(collection) or []:
                        local = record["temp_id"]
                        new_ref = self._remap(prefix, index, local)
                        local_to_revision[f"({index},{local})"] = new_ref
                        chapter_by_ref[new_ref] = spec["chapter_id"]
                        copied = dict(record)
                        copied["temp_id"] = new_ref
                        if collection == "claims":
                            subject = dict(copied.get("subject") or {})
                            if subject.get("ref"):
                                subject["ref"] = self._remap("ent", index, subject["ref"])
                                copied["subject"] = subject
                        bundle_records[collection].append(copied)
            assembled_bundle = {
                "schema_version": "0.1",
                "source": {
                    "temp_id": "src_001", "kind": "source",
                    "source_type": "book",
                    "title": f"三國志合裝本{title_suffix}",
                    "language": "lzh",
                    "extraction": {"method": "model", "job_id": "t14", "confidence": 0.8},
                },
                **bundle_records,
                "warnings": [],
            }
            staged_store.persist_bundle(conn, label, assembled_bundle)
            assembled_sha = sha256_json(assembled_bundle)
            plan_chapters = [
                {
                    "chapter_id": spec["chapter_id"],
                    "chapter_index": spec["index"],
                    "title": spec["title"],
                    "start": spec["start"], "end": spec["end"],
                }
                for spec, _, _ in built
            ]
            control_plane.record_output(
                conn, job_id=job_id, revision_id=revision_id,
                artifact_type="assembled-source-bundle",
                artifact_sha256=assembled_sha,
                payload={
                    "bundle_sha256": assembled_sha,
                    "report": {
                        "plan": {"chapters": plan_chapters},
                        "local_to_revision": dict(sorted(local_to_revision.items())),
                        "chapter_by_ref": dict(sorted(chapter_by_ref.items())),
                    },
                    "bundle": assembled_bundle,
                    "chapter_by_ref": dict(sorted(chapter_by_ref.items())),
                },
            )
            catalog = {
                "schema": "chronicle.canonical-catalog", "version": "0.1",
                "canonical_entities": [
                    {
                        "canonical_id": _uuid7(canon_base + position),
                        "representations": [{"bundle": label, "ref": ref}],
                    }
                    for position, ref in enumerate(sorted(
                        {r["temp_id"] for r in bundle_records["entities"]}
                    ))
                ],
                "canonical_events": [
                    {
                        "canonical_id": _uuid7(canon_base + 400 + position),
                        "representations": [{"bundle": label, "ref": ref}],
                    }
                    for position, ref in enumerate(sorted(
                        {r["temp_id"] for r in bundle_records["events"]}
                    ))
                ],
            }
            catalog_sha, _ = canonical_store.persist_catalog(conn, catalog)
            for spec, candidate, _anchors in built:
                # The artifact row already stores the exact accepted bytes;
                # reread it instead of rebuilding (never two sources of truth).
                row = conn.execute(
                    """
                    SELECT payload FROM chronicle.chapter_artifacts
                    WHERE job_id = %s AND chapter_id = %s
                    """,
                    (job_id, spec["chapter_id"]),
                ).fetchone()
                stored = row[0]
                entry = {
                    "artifact": stored,
                    "chapter_id": spec["chapter_id"],
                    "chapter_index": spec["index"],
                    "artifact_sha256": sha256_json(stored),
                }
                publication = resolve_publish.build_chapter_publication(
                    artifact_entry=entry, catalog_sha256=catalog_sha,
                    assembled_bundle_sha256=assembled_sha,
                )
                chapter_store.insert_chapter_publication_in_txn(
                    conn, job_id=job_id,
                    artifact_sha256=entry["artifact_sha256"],
                    catalog_sha256=catalog_sha,
                    assembled_bundle_sha256=assembled_sha,
                    publication=publication,
                )
            conn.commit()

    def _insert_unpublished_artifact(self) -> None:
        # Accepted row without any publication: the public API must not
        # expose it through the directory, detail, or source routes.
        with psycopg.connect(self.database_url) as conn:
            document_id = conn.execute(
                "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
                (self.revision_r1,),
            ).fetchone()[0]
            candidate = _candidate(
                chapter_id="ch_A", title="三國志合裝本甲本",
                entities=[_entity("ent_001", "劉備")], events=[],
                claims=[], blocks=[_block("t_001", "未公開譯文。", ["ent_001"], [])],
                mentions=[], record_sources=[],
            )
            chunk_id = control_plane.record_chunk(
                conn, job_id=self.job_private, section_id=None, chunk_index=0,
                source_start=0, source_end=LEN_A,
                source_sha256=self.source_sha_r1,
                content_sha256=self.normalized_r1,
            )
            run_id, _ = control_plane.record_chunk_run(
                conn, chunk_id=chunk_id, status="completed", worker="t14",
                checkpoint={"request_fingerprint": "0" * 64},
            )
            artifact = {
                "schema": "chronicle.chapter-artifact", "version": "0.1",
                "chapter_id": "ch_A", "revision_id": str(self.revision_r1),
                "source_sha256": self.source_sha_r1,
                "normalized_sha256": self.normalized_r1,
                "candidate": candidate,
                "candidate_sha256": sha256_json(candidate),
                "anchors": [],
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
                    sha256_json(artifact), self.job_private, self.revision_r1,
                    document_id, "ch_A", 0, chunk_id, run_id,
                    "0" * 64, sha256_json(candidate), Jsonb(artifact),
                ),
            )
            conn.commit()

    # -- HTTP helpers -----------------------------------------------------

    def _request(self, method: str, path: str):
        req = Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        try:
            with urlopen(req, timeout=15) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _walk_directory(self, limit: int = 50) -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        for _ in range(10):
            path = f"/v0/chapters?limit={limit}"
            if cursor is not None:
                path += f"&cursor={quote(cursor, safe='')}"
            status, payload = self._request("GET", path)
            self.assertEqual(200, status, payload)
            items.extend(payload["items"])
            cursor = payload["next_cursor"]
            if cursor is None:
                break
        return items

    def _output_counts(self) -> dict[str, int]:
        with psycopg.connect(self.database_url) as conn:
            return {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (
                    "chronicle.ingestion_outputs",
                    "chronicle.chapter_publications",
                    "chronicle.canonical_catalogs",
                    "chronicle.ingestion_chunk_runs",
                    "chronicle.review_items",
                )
            }

    # -- tests ------------------------------------------------------------

    def test_directory_lists_only_published_in_stable_order(self) -> None:
        items = self._walk_directory(limit=1)
        # Two revisions x two chapters; the unpublished job stays invisible.
        self.assertEqual(4, len(items))
        keys = [
            (item["document_id"], item["revision_no"], item["chapter_index"],
             item["publication_id"])
            for item in items
        ]
        self.assertEqual(sorted(keys), keys)
        self.assertEqual(
            ["先主傳", "周瑜傳", "先主傳", "周瑜傳"],
            [item["chapter_title"] for item in items],
        )
        self.assertEqual([1, 1, 2, 2], [item["revision_no"] for item in items])
        for item in items:
            self.assertEqual("三國志合裝本", item["document_title"])
            self.assertIn("publication_id", item)
            self.assertIn("artifact_sha256", item)
            uuid.UUID(item["publication_id"])

    def test_detail_returns_full_blocks_and_pinned_references(self) -> None:
        items = self._walk_directory()
        first = [i for i in items if i["revision_no"] == 1 and i["chapter_index"] == 0][0]
        status, detail = self._request("GET", f"/v0/chapters/{first['publication_id']}")
        self.assertEqual(200, status, detail)
        self.assertEqual(
            [], chapter_contract.validate_public_chapter_response({
                "publication_id": detail["publication_id"],
                "chapter_id": detail["chapter_id"],
                "revision_id": detail["revision_id"],
                "translation_blocks": detail["translation_blocks"],
                "source_overview": detail["source_overview"],
                "references": detail["references"],
            }),
        )
        # Head, tail, and the claim-less block are all readable.
        self.assertEqual(2, len(detail["translation_blocks"]))
        self.assertEqual("t_001", detail["translation_blocks"][0]["block_id"])
        self.assertEqual("t_002", detail["translation_blocks"][1]["block_id"])
        self.assertIn("劉備", detail["translation_blocks"][0]["text"])
        self.assertIn("無對應主張", detail["translation_blocks"][1]["text"])
        # Many-to-many refs stay attached to their block position.
        refs = detail["translation_blocks"][0]
        self.assertEqual(["ent_001"], [r["ref"] for r in refs["entity_refs"]])
        self.assertEqual(["evt_001"], [r["ref"] for r in refs["event_refs"]])
        # Precomputed references are revision-pinned, canonicalized, named.
        by_ref = {r["ref"]: r for r in detail["references"]["entities"]}
        self.assertEqual("ent_000001", by_ref["ent_000001"]["ref"])
        self.assertEqual("劉備", by_ref["ent_000001"]["name"])
        uuid.UUID(by_ref["ent_000001"]["canonical_id"])
        events = {r["ref"]: r for r in detail["references"]["events"]}
        self.assertEqual("先主出身", events["evt_000001"]["title"])
        self.assertEqual(str(self.revision_r1), detail["revision_id"])
        self.assertEqual("先主傳", detail["source_overview"]["chapter_title"])
        self.assertEqual("三國志合裝本", detail["source_overview"]["source_title"])

    def test_unknown_and_unpublished_publications_404(self) -> None:
        status, payload = self._request("GET", f"/v0/chapters/{uuid.uuid4()}")
        self.assertEqual(404, status)
        self.assertEqual("not_found", payload["error"]["code"])
        status, payload = self._request("GET", "/v0/chapters/not-a-uuid")
        self.assertEqual(404, status)

    def test_cross_publication_anchor_404(self) -> None:
        items = self._walk_directory()
        r1 = [i for i in items if i["revision_no"] == 1 and i["chapter_index"] == 1][0]
        r2 = [i for i in items if i["revision_no"] == 2 and i["chapter_index"] == 1][0]
        # Anchor ids are deterministic per revision prefix; the R2 anchor
        # must not resolve through the R1 publication and vice versa.
        r2_anchor = f"anc_b_men_{str(self.revision_r2)[:8]}"
        status, payload = self._request(
            "GET", f"/v0/chapters/{r1['publication_id']}/sources/{r2_anchor}"
        )
        self.assertEqual(404, status, payload)
        r1_anchor = f"anc_b_men_{str(self.revision_r1)[:8]}"
        status, payload = self._request(
            "GET", f"/v0/chapters/{r2['publication_id']}/sources/{r1_anchor}"
        )
        self.assertEqual(404, status, payload)
        status, payload = self._request(
            "GET", f"/v0/chapters/{r1['publication_id']}/sources/anc_does_not_exist"
        )
        self.assertEqual(404, status, payload)

    def test_old_revision_links_stay_pinned(self) -> None:
        items = self._walk_directory()
        r1 = [i for i in items if i["revision_no"] == 1 and i["chapter_index"] == 1][0]
        anchor = f"anc_b_men_{str(self.revision_r1)[:8]}"
        status, window = self._request(
            "GET", f"/v0/chapters/{r1['publication_id']}/sources/{anchor}"
        )
        self.assertEqual(200, status, window)
        self.assertEqual(str(self.revision_r1), window["revision_id"])
        self.assertIn(R1_ONLY_QUOTE, window["text"])
        self.assertTrue(
            any(seg.get("highlight") for seg in window["segments"]),
            window["segments"],
        )

    def test_source_hash_drift_never_reads_new_bytes(self) -> None:
        items = self._walk_directory()
        r1 = [i for i in items if i["revision_no"] == 1 and i["chapter_index"] == 0][0]
        anchor = f"anc_a_ent_{str(self.revision_r1)[:8]}"
        status, before = self._request(
            "GET", f"/v0/chapters/{r1['publication_id']}/sources/{anchor}"
        )
        self.assertEqual(200, status, before)
        target = Path(self.storage_dir) / self.storage_key_r1
        original = target.read_bytes()
        try:
            # Same length, different bytes: the stored hash no longer matches.
            drifted = bytearray(original)
            drifted[0] ^= 0xFF
            target.write_bytes(bytes(drifted))
            status, payload = self._request(
                "GET", f"/v0/chapters/{r1['publication_id']}/sources/{anchor}"
            )
            self.assertEqual(409, status, payload)
            self.assertEqual("source_mismatch", payload["error"]["code"])
            self.assertNotIn("玄德", payload.get("text", ""))
        finally:
            target.write_bytes(original)
        # The stored translation detail never depended on the live file.
        status, detail = self._request("GET", f"/v0/chapters/{r1['publication_id']}")
        self.assertEqual(200, status, detail)
        self.assertIn("劉備", detail["translation_blocks"][0]["text"])

    def test_missing_source_file_is_409_without_fallback(self) -> None:
        items = self._walk_directory()
        r2 = [i for i in items if i["revision_no"] == 2 and i["chapter_index"] == 0][0]
        anchor = f"anc_a_ent_{str(self.revision_r2)[:8]}"
        target = Path(self.storage_dir) / self.storage_key_r2
        original = target.read_bytes()
        try:
            target.unlink()
            status, payload = self._request(
                "GET", f"/v0/chapters/{r2['publication_id']}/sources/{anchor}"
            )
            self.assertEqual(409, status, payload)
            self.assertEqual("source_unavailable", payload["error"]["code"])
        finally:
            target.write_bytes(original)

    def test_chapter_paging_covers_exact_chapter(self) -> None:
        items = self._walk_directory()
        r1 = [i for i in items if i["revision_no"] == 1 and i["chapter_index"] == 1][0]
        anchor = f"anc_b_men_{str(self.revision_r1)[:8]}"
        chapter_text = TEXT_R1[LEN_A:]
        pieces: list[str] = []
        cursor: str | None = None
        for _ in range(20):
            path = (
                f"/v0/chapters/{r1['publication_id']}/sources/{anchor}"
                "?view=chapter&limit=7"
            )
            if cursor is not None:
                path += f"&cursor={quote(cursor, safe='')}"
            status, payload = self._request("GET", path)
            self.assertEqual(200, status, payload)
            self.assertEqual("chapter", payload["view"])
            pieces.append(payload["text"])
            cursor = payload["next_cursor"]
            if not payload["has_more"]:
                break
        self.assertEqual(chapter_text, "".join(pieces))
        self.assertIsNone(cursor)

    def test_request_error_codes(self) -> None:
        items = self._walk_directory()
        publication_id = items[0]["publication_id"]
        for bad in (
            "/v0/chapters?limit=0",
            "/v0/chapters?limit=101",
            "/v0/chapters?limit=nope",
            "/v0/chapters?unknown=1",
            "/v0/chapters?cursor=bogus",
        ):
            status, payload = self._request("GET", bad)
            self.assertEqual(400, status, payload)
        anchor = f"anc_a_ent_{str(self.revision_r1)[:8]}"
        r1 = [i for i in items if i["revision_no"] == 1 and i["chapter_index"] == 0][0]
        status, _ = self._request("GET", "/v0/chapters?limit=1")
        self.assertEqual(200, status)
        # A directory cursor is bound to its own scope, not to sources.
        status, payload = self._request(
            "GET",
            f"/v0/chapters/{r1['publication_id']}/sources/{anchor}"
            "?view=chapter&cursor=bogus",
        )
        self.assertEqual(400, status, payload)
        # View/cursor/limit misuse is explicit, never silent truncation.
        status, _ = self._request(
            "GET", f"/v0/chapters/{publication_id}/sources/{anchor}?view=bogus"
        )
        self.assertEqual(400, status)
        status, _ = self._request(
            "GET", f"/v0/chapters/{publication_id}/sources/{anchor}?view=window&limit=5"
        )
        self.assertEqual(400, status)
        status, _ = self._request(
            "GET", f"/v0/chapters/{publication_id}/sources/{anchor}?view=window&cursor=x"
        )
        self.assertEqual(400, status)

    def test_wrong_methods_are_405(self) -> None:
        items = self._walk_directory()
        publication_id = items[0]["publication_id"]
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, payload = self._request(method, "/v0/chapters")
            self.assertEqual(405, status, (method, payload))
            status, payload = self._request(
                method, f"/v0/chapters/{publication_id}"
            )
            self.assertEqual(405, status, (method, payload))

    def test_reads_change_no_db_state_and_call_no_model(self) -> None:
        # Model execution would append chunk runs/outputs; every read below
        # must leave all write-side tables (and the review queue) untouched.
        before = self._output_counts()
        items = self._walk_directory(limit=1)
        for item in items:
            status, _ = self._request("GET", f"/v0/chapters/{item['publication_id']}")
            self.assertEqual(200, status)
        anchor = f"anc_a_ent_{str(self.revision_r1)[:8]}"
        r1 = [i for i in items if i["revision_no"] == 1 and i["chapter_index"] == 0][0]
        for path in (
            f"/v0/chapters/{r1['publication_id']}/sources/{anchor}",
            f"/v0/chapters/{r1['publication_id']}/sources/{anchor}?view=chapter",
        ):
            status, _ = self._request("GET", path)
            self.assertEqual(200, status)
        self.assertEqual(before, self._output_counts())

    def test_unmapped_reference_fails_explicitly(self) -> None:
        # A translation ref with no assembled revision mapping must 409,
        # never resolve by guessing another object.
        with psycopg.connect(self.database_url) as conn:
            candidate = _candidate(
                chapter_id="ch_X", title="三國志合裝本甲本",
                entities=[_entity("ent_001", "劉備")], events=[],
                claims=[],
                blocks=[_block("t_001", "孤證一段。", ["ent_999"], [])],
                mentions=[], record_sources=[],
            )
            chunk_id = control_plane.record_chunk(
                conn, job_id=self.job_r1, section_id=None, chunk_index=7,
                source_start=0, source_end=LEN_A,
                source_sha256=self.source_sha_r1,
                content_sha256=self.normalized_r1,
            )
            run_id, _ = control_plane.record_chunk_run(
                conn, chunk_id=chunk_id, status="completed", worker="t14",
                checkpoint={"request_fingerprint": "0" * 64},
            )
            artifact = {
                "schema": "chronicle.chapter-artifact", "version": "0.1",
                "chapter_id": "ch_X", "revision_id": str(self.revision_r1),
                "source_sha256": self.source_sha_r1,
                "normalized_sha256": self.normalized_r1,
                "candidate": candidate,
                "candidate_sha256": sha256_json(candidate),
                "anchors": [],
                "request_fingerprint": "0" * 64,
                "producing_run": {
                    "run_id": str(run_id), "model": "fixture",
                    "prompt_schema_version": "v1",
                },
            }
            artifact_sha = sha256_json(artifact)
            document_id = conn.execute(
                "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
                (self.revision_r1,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO chronicle.chapter_artifacts(
                    artifact_sha256, job_id, revision_id, document_id,
                    chapter_id, chapter_index, chunk_id, producing_run_id,
                    request_fingerprint, candidate_sha256, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    artifact_sha, self.job_r1, self.revision_r1, document_id,
                    "ch_X", 2, chunk_id, run_id,
                    "0" * 64, sha256_json(candidate), Jsonb(artifact),
                ),
            )
            catalog_sha = conn.execute(
                "SELECT catalog_sha256 FROM chronicle.chapter_publications WHERE job_id = %s LIMIT 1",
                (self.job_r1,),
            ).fetchone()[0]
            assembled_row = conn.execute(
                "SELECT output_id, payload FROM chronicle.ingestion_outputs "
                "WHERE job_id = %s AND artifact_type = %s",
                (self.job_r1, "assembled-source-bundle"),
            ).fetchone()
            assembled_sha = assembled_row[1]["bundle_sha256"]
            # Give the stray chapter a recorded title so the read path
            # reaches the reference remap instead of failing on the title:
            # the missing local->revision entry must fail explicitly.
            patched = dict(assembled_row[1])
            report = json.loads(json.dumps(patched["report"]))
            report["plan"]["chapters"].append({
                "chapter_id": "ch_X", "chapter_index": 2,
                "title": "闕文", "start": 0, "end": LEN_A,
            })
            patched["report"] = report
            conn.execute(
                "UPDATE chronicle.ingestion_outputs SET payload = %s WHERE output_id = %s",
                (Jsonb(patched), assembled_row[0]),
            )
            entry = {
                "artifact": artifact, "chapter_id": "ch_X",
                "chapter_index": 2, "artifact_sha256": artifact_sha,
            }
            publication = resolve_publish.build_chapter_publication(
                artifact_entry=entry, catalog_sha256=catalog_sha,
                assembled_bundle_sha256=assembled_sha,
            )
            publication_id = chapter_store.insert_chapter_publication_in_txn(
                conn, job_id=self.job_r1, artifact_sha256=artifact_sha,
                catalog_sha256=catalog_sha,
                assembled_bundle_sha256=assembled_sha,
                publication=publication,
            )
            conn.commit()
        status, payload = self._request("GET", f"/v0/chapters/{publication_id}")
        self.assertEqual(409, status, payload)
        self.assertEqual("reference_unmapped", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
