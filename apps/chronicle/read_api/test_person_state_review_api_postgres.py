"""PostgreSQL 18 integration tests for the C2-R3-T07 person-state review API.

Covers ``person-state-reading.md`` §5.1 on the real Studio surface:

- the mixed queue with ``review_scope=resolution|person_state|all`` keeps the
  existing resolution + narrative facts/prose items and adds the person-state
  package; the omitted scope stays resolution (which covers narrative) and
  ``link_kind`` is rejected outside ``resolution``;
- open_count, cursor and iteration are bound to the full selected scope;
- detail projects the frozen candidates readably, candidate paging is bounded
  and plan-bound;
- contexts expose candidate sources with ``candidate_id`` and bounded pages;
- sources read the exact frozen revision through the shared source reader and
  fail closed (404 for foreign anchors, 409 for drift/missing files);
- the decision branch validates the frozen package and never accepts the
  resolution decision vocabulary.
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

import control_plane  # noqa: E402
import person_state_contract as contract  # noqa: E402
import person_state_review as review  # noqa: E402
from common import sha256_json  # noqa: E402
from migrations import apply_migrations  # noqa: E402
from studio_reviews import STUDIO_REVIEWS_PREFIX  # noqa: E402

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

CHAPTER = "ch_000000000000000000000001"
SOURCE_TEXT = "瑜為建威中郎將。後遷偏將軍。瑜還。策卒。\n"
QUOTE_ONE = "瑜為建威中郎將"
QUOTE_TWO = "後遷偏將軍"
_ANCHOR_ONE_START = SOURCE_TEXT.index(QUOTE_ONE)
_ANCHOR_TWO_START = SOURCE_TEXT.index(QUOTE_TWO)


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


def _uuid7() -> str:
    n = uuid.uuid4().int
    value = (0x019535D93DF7 << 80) | (0x7 << 76) | (n & 0xFFFFFFFFFFFF)
    return str(uuid.UUID(int=value))


def _anchor(anchor_id: str, quote: str, start: int, revision_id, source_sha: str) -> dict:
    return {
        "anchor_id": anchor_id,
        "revision_id": str(revision_id),
        "chapter_id": CHAPTER,
        "source_sha256": source_sha,
        "normalized_sha256": source_sha,
        "first_block_id": "b_001",
        "last_block_id": "b_001",
        "quote": quote,
        "quote_sha256": _sha_text(quote),
        "occurrence": 1,
        "start": start,
        "end": start + len(quote),
    }


def _entity(temp_id: str, name: str) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "entity",
        "type": "person" if temp_id == "ent_001" else "office",
        "canonical_name": name,
        "aliases": [],
        "mentions": [],
        "resolution": {"status": "unresolved"},
        "extraction": {"method": "model", "job_id": "t07", "confidence": 0.8},
    }


def _person_states() -> dict:
    return {
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
                "claim_refs": ["clm_001"],
                "source_selections": [],
                "attribution": "annotation",
            },
            {
                "fact_id": "pf_003",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_002"},
                "relation": None,
                "target_ref": None,
                "operation": "attest",
                "qualification": "ordinary",
                "phase_ref": "ph_001",
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


_ARTIFACT_CANDIDATES = (
    ("phase", "ph_001", ["ph_001"], ["anc_1"]),
    ("phase", "ph_002", ["ph_002"], ["anc_2"]),
    ("fact", "pf_001", ["ph_001"], ["anc_3"]),
    ("fact", "pf_002", ["ph_002"], ["anc_4"]),
    ("fact", "pf_003", ["ph_001"], ["anc_3"]),
)


def _artifact(revision_id, source_sha: str) -> dict:
    anchors = [
        _anchor("anc_1", QUOTE_ONE, _ANCHOR_ONE_START, revision_id, source_sha),
        _anchor("anc_2", QUOTE_TWO, _ANCHOR_TWO_START, revision_id, source_sha),
        _anchor("anc_3", QUOTE_ONE, _ANCHOR_ONE_START, revision_id, source_sha),
        _anchor("anc_4", QUOTE_TWO, _ANCHOR_TWO_START, revision_id, source_sha),
    ]
    candidates = [
        {
            "candidate_key": contract.candidate_key_for(
                kind=kind, chapter_id=CHAPTER, item_ref=item_ref, anchor_ids=list(anchor_ids)
            ),
            "kind": kind,
            "item_ref": item_ref,
            "phase_ids": list(phase_ids),
            "anchor_ids": list(anchor_ids),
            "source_fact_refs": [],
        }
        for kind, item_ref, phase_ids, anchor_ids in _ARTIFACT_CANDIDATES
    ]
    person_states = _person_states()
    candidate = {
        "schema": "chronicle.chapter-candidate",
        "version": "0.3",
        "chapter_id": CHAPTER,
        "bundle": {
            "schema_version": "0.1",
            "source": {
                "temp_id": "src_001",
                "kind": "source",
                "source_type": "book",
                "title": "周瑜傳",
                "author": "陳壽",
                "language": "lzh",
                "extraction": {"method": "model", "job_id": "t07", "confidence": 0.8},
            },
            "entities": [_entity("ent_001", "周瑜"), _entity("ent_002", "建威中郎將")],
            "events": [],
            "claims": [],
            "warnings": [],
        },
        "translation": {
            "language": "zh-CN",
            "blocks": [
                {
                    "block_id": "t_001",
                    "text": "周瑜任建威中郎將",
                    "source_block_ids": ["b_001"],
                    "entity_refs": [{"kind": "entity", "ref": "ent_001"}],
                    "event_refs": [],
                }
            ],
        },
        "mentions": [],
        "record_sources": [],
        "warnings": [],
    }
    core = {
        "schema": "chronicle.chapter-artifact",
        "version": "0.3",
        "chapter_id": CHAPTER,
        "revision_id": str(revision_id),
        "source_sha256": source_sha,
        "normalized_sha256": source_sha,
        "candidate": candidate,
        "candidate_sha256": sha256_json(candidate),
        "anchors": anchors,
        "request_fingerprint": "0" * 64,
        "producing_run": {"run_id": "run-1", "model": "fixture", "prompt_schema_version": "0.3"},
        "reading": {},
        "reading_sha256": sha256_json({}),
        "person_states": person_states,
        "person_states_sha256": sha256_json(person_states),
        "person_state_candidates": candidates,
    }
    artifact = dict(core)
    artifact["artifact_sha256"] = sha256_json(core)
    return artifact


def _assembly() -> dict:
    items = [
        {"kind": kind, "origin_ref": item_ref, "revision_ref": f"ref_{index:06d}"}
        for index, (kind, item_ref, _phase_ids, _anchors) in enumerate(_ARTIFACT_CANDIDATES)
    ]
    person_states = {"facts": []}
    return {
        "person_states": person_states,
        "evidence_manifests": [{"chapter_id": CHAPTER, "items": items}],
        "report": {"person_states_sha256": sha256_json(person_states)},
    }


class PersonStateReviewApiPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t07_api_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.database_name}"')
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        raw = SOURCE_TEXT.encode("utf-8")
        self.source_sha = hashlib.sha256(raw).hexdigest()
        self.storage_dir = tempfile.mkdtemp(prefix="chronicle-t07-")
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            document_id = control_plane.create_document(conn, title="周瑜傳")
            self.revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=self.source_sha,
                source_bytes=len(raw),
                source_media_type="text/plain",
                filename="zhouyu.md",
                language="lzh",
                source_label="test edition",
            )
            self.storage_key = conn.execute(
                "SELECT storage_key FROM chronicle.document_revisions WHERE revision_id = %s",
                (self.revision_id,),
            ).fetchone()[0]
            self.job_id = control_plane.queue_job(conn, revision_id=self.revision_id)
            control_plane.claim_job(conn, worker="t07", job_id=self.job_id)
            control_plane.set_job_status(conn, job_id=self.job_id, status="needs_review")
            conn.commit()
        path = Path(self.storage_dir) / self.storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

        self._seed_chapter_artifact()
        self._seed_person_state_review()
        self._seed_resolution_review()
        self._seed_narrative_reviews()

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

    # -- seeding -----------------------------------------------------------

    def _seed_chapter_artifact(self) -> None:
        artifact = _artifact(self.revision_id, self.source_sha)
        with psycopg.connect(self.database_url) as conn:
            document_id = conn.execute(
                "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
                (self.revision_id,),
            ).fetchone()[0]
            chunk_id = control_plane.record_chunk(
                conn,
                job_id=self.job_id,
                section_id=None,
                chunk_index=0,
                source_start=0,
                source_end=len(SOURCE_TEXT),
                source_sha256=self.source_sha,
                content_sha256=_sha_text(SOURCE_TEXT),
            )
            run_id, _ = control_plane.record_chunk_run(
                conn,
                chunk_id=chunk_id,
                status="completed",
                worker="t07",
                checkpoint={"request_fingerprint": "0" * 64},
            )
            conn.execute(
                """
                INSERT INTO chronicle.chapter_artifacts(
                    artifact_sha256, job_id, revision_id, document_id,
                    chapter_id, chapter_index, chunk_id, producing_run_id,
                    request_fingerprint, candidate_sha256, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    artifact["artifact_sha256"], self.job_id, self.revision_id, document_id,
                    CHAPTER, 0, chunk_id, run_id, "0" * 64,
                    artifact["candidate_sha256"], Jsonb(artifact),
                ),
            )
            conn.commit()
        self.artifact = artifact
        self.anchor_ids = [f"anc_{index}" for index in (1, 2, 3, 4)]

    def _seed_person_state_review(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            plan = review.build_person_state_review_plan(
                job_id=self.job_id,
                revision_id=self.revision_id,
                accepted_artifacts=[self.artifact],
                assembly=_assembly(),
                resolution_hashes=["d" * 64],
                base_catalog_sha="e" * 64,
            )
            (self.person_state_review_id,) = review.open_person_state_reviews(
                conn, job_id=self.job_id, plan=plan
            )
            conn.commit()
        self.plan = plan
        self.person_state_candidates = plan["packages"][0]["candidates"]

    def _seed_resolution_review(self) -> None:
        payload = {
            "scope": "resolution",
            "review_mode": "chapter_pair",
            "link_kind": "entity",
            "candidate_id": "ec_001",
            "resolution_sha256": _sha_text("resolution"),
            "left": {"bundle": "missing-left", "ref": "ent_001"},
            "right": {"bundle": "missing-right", "ref": "ent_002"},
            "signals": [],
            "initial_decision": "uncertain",
            "blocking": True,
            "allowed_decisions": ["same_entity", "not_same", "uncertain"],
            "decision": None,
        }
        with psycopg.connect(self.database_url) as conn:
            self.resolution_review_id = control_plane.open_review_item(
                conn, job_id=self.job_id, kind="stage_gate", payload=payload
            )
            conn.commit()

    def _seed_narrative_reviews(self) -> None:
        context = {"sources": []}
        with psycopg.connect(self.database_url) as conn:
            facts_sha = _sha_text("facts")
            facts_review_id = control_plane.open_review_item(
                conn,
                job_id=self.job_id,
                kind="stage_gate",
                payload={
                    "scope": "narrative",
                    "narrative_kind": "facts",
                    "candidate_sha": facts_sha,
                    "plan_version": "narrative-review-v1",
                    "blocking": True,
                    "allowed_decisions": ["approve", "reject"],
                },
            )
            conn.execute(
                """
                INSERT INTO chronicle.narrative_candidates(
                    candidate_sha, job_id, kind, review_id, context_sha,
                    context_payload, candidate_payload, model_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    facts_sha, self.job_id, "facts", facts_review_id, sha256_json(context),
                    Jsonb(context), Jsonb({"conclusions": []}), "fixture",
                ),
            )

            prose_sha = _sha_text("prose")
            prose_review_id = control_plane.open_review_item(
                conn,
                job_id=self.job_id,
                kind="stage_gate",
                payload={
                    "scope": "narrative",
                    "narrative_kind": "prose",
                    "candidate_sha": prose_sha,
                    "plan_version": "narrative-review-v1",
                    "blocking": True,
                    "allowed_decisions": ["approve", "reject"],
                },
            )
            conn.execute(
                """
                INSERT INTO chronicle.narrative_candidates(
                    candidate_sha, job_id, kind, review_id, context_sha,
                    context_payload, candidate_payload, model_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    prose_sha, self.job_id, "prose", prose_review_id, sha256_json(context),
                    Jsonb(context), Jsonb({"paragraphs": []}), "fixture",
                ),
            )
            conn.commit()
        self.narrative_facts_review_id = facts_review_id
        self.narrative_prose_review_id = prose_review_id

    # -- helpers -----------------------------------------------------------

    def _candidate_key_for(self, item_ref: str) -> str:
        return next(
            candidate["candidate_key"]
            for candidate in self.person_state_candidates
            if candidate["item_ref"] == item_ref
        )

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(req, timeout=15) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _page_all(self, base: str) -> tuple[list[dict], dict]:
        items: list[dict] = []
        cursor: str | None = None
        payload: dict = {}
        for _ in range(20):
            path = base
            if cursor:
                glue = "&" if "?" in path else "?"
                path = f"{path}{glue}cursor={quote(cursor, safe='')}"
            status, payload = self._request("GET", path)
            self.assertEqual(status, 200, payload)
            items.extend(payload["items"])
            cursor = payload["next_cursor"]
            if not cursor:
                break
        else:
            self.fail("queue pagination did not terminate")
        return items, payload

    # -- queue scope -------------------------------------------------------

    def test_all_scope_carries_resolution_person_state_and_narrative(self) -> None:
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}?review_scope=all&limit=50"
        )
        self.assertEqual(status, 200, payload)
        scopes = sorted(item["scope"] for item in payload["items"])
        self.assertEqual(scopes, ["narrative", "narrative", "person_state", "resolution"])
        self.assertEqual(payload["open_count"], 4)
        self.assertEqual(payload["query"]["review_scope"], "all")
        kinds = sorted(
            item.get("narrative_kind")
            for item in payload["items"]
            if item["scope"] == "narrative"
        )
        self.assertEqual(kinds, ["facts", "prose"])

    def test_default_scope_keeps_resolution_and_narrative_only(self) -> None:
        status, payload = self._request("GET", f"{STUDIO_REVIEWS_PREFIX}?limit=50")
        self.assertEqual(status, 200, payload)
        scopes = sorted(item["scope"] for item in payload["items"])
        self.assertEqual(scopes, ["narrative", "narrative", "resolution"])
        self.assertEqual(payload["open_count"], 3)
        self.assertEqual(payload["query"]["review_scope"], "resolution")

    def test_person_state_scope_is_isolated(self) -> None:
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}?review_scope=person_state"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual([item["scope"] for item in payload["items"]], ["person_state"])
        item = payload["items"][0]
        self.assertEqual(item["chapter_id"], CHAPTER)
        self.assertEqual(item["candidate_count"], 5)
        self.assertEqual(item["default_assessment"], "uncertain")
        self.assertEqual(item["left_label"], "阶段依据审核")
        self.assertEqual(item["plan_fingerprint"], self.plan["plan_fingerprint"])

    def test_link_kind_is_rejected_outside_resolution(self) -> None:
        for scope in ("person_state", "all"):
            status, payload = self._request(
                "GET", f"{STUDIO_REVIEWS_PREFIX}?review_scope={scope}&link_kind=entity"
            )
            self.assertEqual(status, 400, payload)
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}?review_scope=resolution&link_kind=entity"
        )
        self.assertEqual(status, 200, payload)

    def test_cursor_is_bound_to_the_selected_scope(self) -> None:
        status, first = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}?review_scope=all&limit=1"
        )
        self.assertEqual(status, 200, first)
        cursor = first["next_cursor"]
        self.assertIsNotNone(cursor)
        status, payload = self._request(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}?review_scope=person_state&limit=1&cursor={quote(cursor, safe='')}",
        )
        self.assertEqual(status, 400, payload)
        items, last = self._page_all(f"{STUDIO_REVIEWS_PREFIX}?review_scope=all&limit=2")
        self.assertEqual(len(items), 4)
        self.assertIsNone(last["next_cursor"])

    # -- detail ------------------------------------------------------------

    def test_person_state_detail_projects_readable_candidates(self) -> None:
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}"
        )
        self.assertEqual(status, 200, payload)
        detail = payload["review"]
        self.assertEqual(detail["scope"], "person_state")
        self.assertEqual(detail["review_mode"], "chapter_state_evidence")
        self.assertEqual(detail["chapter_id"], CHAPTER)
        self.assertEqual(detail["candidate_count"], 5)
        self.assertEqual(len(detail["candidates"]), 5)
        by_kind = {(c["kind"], c["item_ref"]): c for c in detail["candidates"]}
        fact = by_kind[("fact", "pf_001")]
        self.assertEqual(fact["person_name"], "周瑜")
        self.assertEqual(fact["value"], "建威中郎將")
        self.assertEqual(fact["dimension"], "office")
        self.assertEqual(fact["operation"], "start")
        self.assertEqual(fact["quote"], QUOTE_ONE)
        self.assertEqual(fact["source_label"], "周瑜傳")
        self.assertEqual(fact["phase_refs"], ["ph_001"])
        self.assertIn("supported", fact["allowed_assessments"])
        phase = by_kind[("phase", "ph_001")]
        self.assertEqual(phase["value"], "初")

    def test_candidate_paging_is_bounded_and_plan_bound(self) -> None:
        collected: list[dict] = []
        cursor: str | None = None
        for _ in range(10):
            path = f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}?limit=1"
            if cursor:
                path += f"&cursor={quote(cursor, safe='')}"
            status, payload = self._request("GET", path)
            self.assertEqual(status, 200, payload)
            detail = payload["review"]
            collected.extend(candidate["candidate_key"] for candidate in detail["candidates"])
            cursor = detail["next_cursor"]
            if not cursor:
                self.assertFalse(detail["has_more"])
                break
        else:
            self.fail("candidate pagination did not terminate")
        self.assertEqual(len(collected), 5)
        self.assertEqual(len(set(collected)), 5)
        status, payload = self._request(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}?cursor=bogus",
        )
        self.assertEqual(status, 400, payload)

    # -- contexts / sources ------------------------------------------------

    def test_contexts_cover_package_and_filter_by_candidate(self) -> None:
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/contexts?limit=2"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["total"], 4)
        self.assertTrue(payload["has_more"])
        collected: list[str] = [item["anchor_id"] for item in payload["items"]]
        cursor = payload["next_cursor"]
        while cursor:
            status, page = self._request(
                "GET",
                f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/contexts?limit=2&cursor={quote(cursor, safe='')}",
            )
            self.assertEqual(status, 200, page)
            collected.extend(item["anchor_id"] for item in page["items"])
            cursor = page["next_cursor"]
        self.assertEqual(sorted(collected), self.anchor_ids)

        # candidate_id limits the descriptor set to that candidate's anchors.
        candidate_key = self._candidate_key_for("pf_001")
        status, payload = self._request(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/contexts?candidate_id={candidate_key}",
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["candidate_id"], candidate_key)
        self.assertEqual([item["anchor_id"] for item in payload["items"]], ["anc_3"])
        # anc_3 is shared by pf_001 and pf_003: the descriptor keeps both
        # candidate associations instead of only the first.
        shared = payload["items"][0]
        self.assertIn(candidate_key, shared["candidate_keys"])
        self.assertIn(self._candidate_key_for("pf_003"), shared["candidate_keys"])

        status, payload = self._request(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/contexts?candidate_id=psc_missing",
        )
        self.assertEqual(status, 404, payload)

    def test_contexts_evidence_kind_follows_real_claim_and_record_source(self) -> None:
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/contexts?limit=100"
        )
        self.assertEqual(status, 200, payload)
        by_anchor = {item["anchor_id"]: item for item in payload["items"]}
        # pf_001 / pf_003 only have exact source_selections (no direct Claim),
        # so a shared anchor must read as record_source, never direct_claim.
        shared = by_anchor["anc_3"]
        self.assertEqual(shared["evidence_kinds"], ["record_source"])
        self.assertEqual(
            sorted(shared["candidate_keys"]),
            sorted(
                [self._candidate_key_for("pf_001"), self._candidate_key_for("pf_003")]
            ),
        )
        # pf_002 carries claim_refs, so its anchor is direct_claim evidence.
        self.assertEqual(by_anchor["anc_4"]["evidence_kinds"], ["direct_claim"])
        # Phase candidates are record_source.
        self.assertEqual(by_anchor["anc_1"]["evidence_kinds"], ["record_source"])

    def test_source_window_and_chapter_are_exact(self) -> None:
        status, payload = self._request(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/sources/anc_3",
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["view"], "window")
        self.assertEqual(payload["revision_id"], str(self.revision_id))
        self.assertEqual(payload["source_sha256"], self.source_sha)
        self.assertIn(QUOTE_ONE, payload["text"])
        highlighted = "".join(seg["text"] for seg in payload["segments"] if seg["highlight"])
        self.assertEqual(highlighted, QUOTE_ONE)

        status, payload = self._request(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/sources/anc_3?view=chapter",
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["view"], "chapter")
        self.assertEqual(payload["text"], SOURCE_TEXT)

    def test_foreign_anchor_is_404_and_missing_file_is_409(self) -> None:
        status, payload = self._request(
            "GET",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/sources/anc_unknown",
        )
        self.assertEqual(status, 404, payload)

        path = Path(self.storage_dir) / self.storage_key
        original = path.read_bytes()
        try:
            path.write_bytes("篡改後的新版文字".encode("utf-8"))
            status, payload = self._request(
                "GET",
                f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/sources/anc_3",
            )
            self.assertEqual(status, 409, payload)
            self.assertEqual(payload["error"]["code"], "source_mismatch")
            path.unlink()
            status, payload = self._request(
                "GET",
                f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/sources/anc_3",
            )
            self.assertEqual(status, 409, payload)
            self.assertEqual(payload["error"]["code"], "source_unavailable")
        finally:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)

    # -- decision ----------------------------------------------------------

    def _decision_body(self, **overrides) -> dict:
        body = {
            "plan_fingerprint": self.plan["plan_fingerprint"],
            "default_assessment": "uncertain",
            "overrides": [],
            "rationale": "",
        }
        body.update(overrides)
        return body

    def test_person_state_decision_resolves_with_candidate_key_overrides(self) -> None:
        candidate_key = next(
            candidate["candidate_key"]
            for candidate in self.person_state_candidates
            if candidate["item_ref"] == "pf_001"
        )
        status, payload = self._request(
            "POST",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/decision",
            self._decision_body(
                overrides=[
                    {
                        "candidate_key": candidate_key,
                        "assessment": "supported",
                        "rationale": "原文直接支持。",
                    }
                ]
            ),
        )
        self.assertEqual(status, 200, payload)
        detail = payload["review"]
        self.assertEqual(detail["status"], "resolved")
        self.assertEqual(detail["decision"]["default_assessment"], "uncertain")
        self.assertEqual(detail["decision"]["override_count"], 1)
        # Duplicate submission is a 409 and does not change the record.
        status, payload = self._request(
            "POST",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/decision",
            self._decision_body(),
        )
        self.assertEqual(status, 409, payload)

    def test_person_state_decision_rejects_resolution_vocabulary_and_drift(self) -> None:
        status, payload = self._request(
            "POST",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/decision",
            {"decision": "same_entity", "rationale": "identity", "confidence": 0.5},
        )
        self.assertEqual(status, 400, payload)
        status, payload = self._request(
            "POST",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/decision",
            self._decision_body(plan_fingerprint="f" * 64),
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "plan_drift")
        status, payload = self._request(
            "POST",
            f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/decision",
            {"rationale": "no default"},
        )
        self.assertEqual(status, 400, payload)

    def test_person_state_decision_requires_plan_fingerprint(self) -> None:
        endpoint = f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}/decision"
        # A body with legal assessment/overrides/rationale but no fingerprint
        # must still be rejected: the draft's (review_id, plan_fingerprint)
        # isolation cannot be skipped.
        status, payload = self._request(
            "POST",
            endpoint,
            {"default_assessment": "uncertain", "overrides": [], "rationale": ""},
        )
        self.assertEqual(status, 400, payload)
        # A non-string fingerprint is rejected the same way.
        status, payload = self._request(
            "POST",
            endpoint,
            {
                "plan_fingerprint": 123,
                "default_assessment": "uncertain",
                "overrides": [],
                "rationale": "",
            },
        )
        self.assertEqual(status, 400, payload)
        # Neither rejected submission changed the review.
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.person_state_review_id}"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["review"]["status"], "open")

    # -- existing surfaces stay unchanged ----------------------------------

    def test_resolution_and_narrative_dispatch_unchanged(self) -> None:
        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.resolution_review_id}"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["review"]["scope"], "resolution")
        self.assertIn("left_context", payload["review"])

        status, payload = self._request(
            "GET", f"{STUDIO_REVIEWS_PREFIX}/{self.narrative_facts_review_id}"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["review"]["scope"], "narrative")
        self.assertEqual(payload["review"]["narrative_kind"], "facts")

        # Both narrative items stay independently addressable in the mixed
        # queue; prose is never routed through the person-state branch.
        status, payload = self._request("GET", f"{STUDIO_REVIEWS_PREFIX}?status=all")
        self.assertEqual(status, 200, payload)
        prose = [
            item
            for item in payload["items"]
            if item["scope"] == "narrative" and item["narrative_kind"] == "prose"
        ]
        self.assertEqual(len(prose), 1)
        self.assertEqual(prose[0]["review_id"], str(self.narrative_prose_review_id))


if __name__ == "__main__":
    unittest.main()
