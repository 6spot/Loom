"""Real PostgreSQL review/HTTP-projection contracts before chapter acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import chapter_content_review as reviews
import chapter_contract as C
import chapter_production as production
import chapter_production_store as production_store
import control_plane as control
import resolve_publish
import staged_chapter_contract as staged
import studio_reviews
from common import LeaseLost, PersistenceConflict, sha256_json
from migrations import apply_migrations
from test_staged_chapter_contract_unit import fixture
from test_chapter_content_review_unit import decision_for
from test_person_state_review_postgres import _control_url, _database_conninfo


class ChapterContentReviewPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control_url = _control_url()

    def setUp(self):
        self.database_name = f"chronicle_content_review_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self.conn = psycopg.connect(self.database_url)
        apply_migrations(self.conn)
        self.storage = tempfile.TemporaryDirectory()
        self.source_dir = Path(self.storage.name)
        self.request, self.candidate = fixture()
        self.chapter_text = self.request["normalized_text"]
        self.full_text = "# 独立的前章𠮷\n\n" + self.chapter_text
        raw = ("\ufeff" + self.full_text.replace("\n", "\r\n")).encode("utf-8")
        (self.source_dir / "source.txt").write_bytes(raw)
        source_sha = hashlib.sha256(raw).hexdigest()
        document_id = control.create_document(self.conn, title="完整章节内容审核")
        self.revision_id, _ = control.create_revision(
            self.conn, document_id=document_id, source_sha256=source_sha, source_bytes=len(raw),
            source_media_type="text/plain", filename="source.txt", storage_key="source.txt",
        )
        self.job_id = control.queue_job(self.conn, revision_id=self.revision_id)
        control.claim_job(self.conn, worker="review-test", job_id=self.job_id, lease_seconds=300)
        start = len(self.full_text) - len(self.chapter_text)
        self.chunk_id = control.record_chunk(
            self.conn, job_id=self.job_id, section_id=None, chunk_index=0, source_start=start,
            source_end=len(self.full_text), source_sha256=source_sha, content_sha256=C.sha256_text(self.chapter_text),
        )
        self.request.update({"revision_id": str(self.revision_id), "source_sha256": source_sha,
                             "normalized_sha256": C.sha256_text(self.chapter_text), "chapter_start": start,
                             "chapter_end": len(self.full_text), "revision_normalized_sha256": C.sha256_text(self.full_text)})
        self.request["source_scope"] = staged.build_source_scope(self.request)
        self.candidate["source_scope"] = copy.deepcopy(self.request["source_scope"])
        self.history = [
            {"step": "translation", "model": "fixture-a", "raw_text": "完整初稿" * 5000},
            {"step": "review", "model": "fixture-b", "raw_text": "不同模型提出的主语异议，不能覆盖原先意见"},
        ]
        self.issues = [{"id": "subject", "type": "processing_error", "target": "/translation/blocks/0/text",
                        "message": "请结合整章确认主语", "evidence": ["完整原文", "两次意见"]}]
        step = {"step": "translation", "response": "fixture"}
        self.step_sha = sha256_json(step)
        control.record_output_fenced(self.conn, job_id=self.job_id, revision_id=self.revision_id, worker="review-test",
                                    artifact_type="chapter-step-attempt", artifact_sha256=self.step_sha, payload=step)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.storage.cleanup()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name)))

    def freeze(self, **overrides):
        args = {"job_id": self.job_id, "chunk_id": self.chunk_id, "worker": "review-test",
                "request": self.request, "candidate": self.candidate, "history": self.history,
                "issues": self.issues, "validation_errors": [], "pipeline_fingerprint": "a" * 64,
                "step_output_sha256s": [self.step_sha]}
        args.update(overrides)
        result = reviews.freeze_content_review(self.conn, **args)
        self.conn.commit()
        return result

    def packet(self, review_id):
        with psycopg.connect(self.database_url) as conn:
            return reviews.read_content_review(conn, review_id)["packet"]

    def call(self, path="", *, query="", method="GET", body=None):
        with psycopg.connect(self.database_url) as conn:
            status, _, raw = studio_reviews.dispatch_reviews(
                conn, resolve_publish, method=method, path=studio_reviews.STUDIO_REVIEWS_PREFIX + path,
                raw_query=query, body=json.dumps(body).encode() if body is not None else b"", source_dir=self.source_dir,
            )
        return status, json.loads(raw)

    def test_freeze_adopts_packet_and_keeps_every_result_without_chunk_attempts(self):
        first = self.freeze()
        second = self.freeze()
        self.assertEqual(first["review_id"], second["review_id"])
        self.assertEqual(self.packet(first["review_id"])["history"], self.history)
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.review_items WHERE job_id=%s", (self.job_id,)).fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT attempt FROM chronicle.ingestion_chunks WHERE chunk_id=%s", (self.chunk_id,)).fetchone()[0], 0)
        with self.assertRaisesRegex(PersistenceConflict, "open chapter review"):
            self.freeze(history=self.history + [{"step": "review", "raw_text": "不同意见"}])

    def test_unaccepted_original_source_is_full_revision_bound_and_paged(self):
        review = self.freeze()
        status, detail = self.call(f"/{review['review_id']}")
        self.assertEqual(status, 200)
        data = detail["review"]["chapter_content"]
        self.assertTrue(data["can_accept"], data["validation_errors"])
        self.assertNotIn("raw_text", data["history"][0])
        anchor = data["source"]["anchors"][0]["anchor_id"]
        parts, cursor = [], None
        for _ in range(100):
            status, page = self.call(f"/{review['review_id']}/sources/{anchor}", query="view=chapter&limit=17" + (f"&cursor={cursor}" if cursor else ""))
            self.assertEqual(status, 200)
            parts.append(page["text"])
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        self.assertFalse(cursor)
        self.assertEqual("".join(parts), self.chapter_text)
        self.assertNotIn("独立的前章", "".join(parts))
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.chapter_artifacts").fetchone()[0], 0)
        self.assertEqual(self.call(f"/{review['review_id']}/sources/foreign", query="view=chapter")[0], 404)
        (self.source_dir / "source.txt").write_text("新版本不能冒充旧版本")
        status, error = self.call(f"/{review['review_id']}/sources/{anchor}", query="view=chapter")
        self.assertEqual((status, error["error"]["code"]), (409, "source_mismatch"))

    def test_history_pages_retain_long_early_candidate_and_bind_record_cursor(self):
        review = self.freeze()
        text, cursor = "", None
        for _ in range(20):
            status, page = self.call(f"/{review['review_id']}/history", query="entry=0&limit=4096" + (f"&cursor={cursor}" if cursor else ""))
            self.assertEqual(status, 200)
            text += page["text"]
            cursor = page["next_cursor"]
            if not cursor:
                break
            self.assertEqual(self.call(f"/{review['review_id']}/history", query=f"entry=1&cursor={cursor}")[0], 400)
        self.assertFalse(cursor)
        self.assertEqual(json.loads(text), self.history[0])

    def _linked_step(self, *, chunk_id=None):
        parsed = {key: copy.deepcopy(self.candidate[key]) for key in (
            "chapter_id", "bundle", "mentions", "record_sources", "person_states", "warnings",
        )}
        parsed["person_states"].pop("unit_phases")
        raw_text = json.dumps(parsed, ensure_ascii=False, indent=2) + " \n" * 8000
        self.assertEqual(production.parse_step("extraction", raw_text)[1], [])
        output = production_store.append_output(
            self.conn, job_id=self.job_id, chunk_id=chunk_id or self.chunk_id, worker="review-test",
            artifact_type=production_store.STEP_TYPE,
            payload={
                "schema": "chronicle.chapter-step", "version": "0.1", "chapter_id": self.request["chapter_id"],
                "pipeline_fingerprint": "a" * 64, "step": "extraction", "round": 0, "slot": "executor",
                "model": "fixture-full-result", "status": "completed", "attempt": 1,
                "raw_text": raw_text, "parsed": parsed, "validation_errors": [], "error": None,
                "receipt": {"status": "completed", "http_status": 200, "elapsed_seconds": 1.5,
                            "usage": {"input_tokens": 12, "output_tokens": 20, "total_tokens": 32,
                                      "api_key": "PRIVATE_USAGE_KEY_SENTINEL"},
                            "authorization": "PRIVATE_RECEIPT_KEY_SENTINEL"},
                "prompt": "PRIVATE_PROMPT_SENTINEL",
                "model_config": {"api_key": "PRIVATE_CONFIG_KEY_SENTINEL"},
            },
        )
        self.conn.commit()
        projected = production.history_for_model([output])[0]
        self.assertNotIn("raw_text", projected)
        return output, projected

    def test_linked_history_pages_show_exact_raw_result_and_safe_receipt(self):
        output, projected = self._linked_step()
        review = self.freeze(history=[projected], step_output_sha256s=[output["output_sha256"]])
        path = f"/{review['review_id']}"
        status, detail = self.call(path)
        self.assertEqual(status, 200, detail)
        descriptor = detail["review"]["chapter_content"]["history"][0]
        self.assertNotEqual(descriptor["entry_sha256"], sha256_json(projected))
        self.assertNotIn("raw_text", self.packet(review["review_id"])["history"][0])
        text, cursor = "", None
        for index in range(30):
            status, page = self.call(path + "/history", query="entry=0&limit=4096" + (f"&cursor={cursor}" if cursor else ""))
            self.assertEqual(status, 200, page)
            self.assertEqual(page["entry_sha256"], descriptor["entry_sha256"])
            text += page["text"]
            cursor = page["next_cursor"]
            if index == 0:
                # A newer attempt for the same step must not replace this view.
                newer = {key: copy.deepcopy(value) for key, value in output.items() if key not in ("artifact_type", "output_sha256")}
                newer["raw_text"] += "\n"
                newer["attempt"] = 2
                production_store.append_output(self.conn, job_id=self.job_id, chunk_id=self.chunk_id,
                    worker="review-test", artifact_type=production_store.STEP_TYPE, payload=newer)
                self.conn.commit()
            if not cursor:
                break
        self.assertIsNone(cursor)
        displayed = json.loads(text)
        self.assertEqual(displayed["raw_text"], output["raw_text"])
        self.assertEqual(displayed["parsed"], output["parsed"])
        self.assertEqual(displayed["validation_errors"], [])
        self.assertEqual(displayed["receipt"]["usage"], {"input_tokens": 12, "output_tokens": 20, "total_tokens": 32})
        self.assertEqual(displayed["receipt"]["elapsed_seconds"], 1.5)
        self.assertEqual(sha256_json(displayed), descriptor["entry_sha256"])
        self.assertNotIn("PRIVATE_", text)
        self.assertNotIn("prompt", displayed)
        self.assertNotIn("model_config", displayed)
        self.assertEqual(self.call(path)[1]["review"]["chapter_content"]["history"][0], descriptor)

    def test_linked_history_output_must_belong_to_this_chapter_chunk(self):
        foreign_chunk = control.record_chunk(
            self.conn, job_id=self.job_id, section_id=None, chunk_index=1,
            source_start=self.request["chapter_start"], source_end=self.request["chapter_end"],
            source_sha256=self.request["source_sha256"], content_sha256=self.request["normalized_sha256"],
        )
        output, projected = self._linked_step(chunk_id=foreign_chunk)
        review = self.freeze(history=[projected], step_output_sha256s=[output["output_sha256"]])
        for suffix, query in (("", ""), ("/history", "entry=0")):
            status, body = self.call(f"/{review['review_id']}{suffix}", query=query)
            self.assertEqual((status, body["error"]["code"]), (409, "plan_drift"))

    def test_linked_history_cursor_rejects_output_hash_drift(self):
        output, projected = self._linked_step()
        review = self.freeze(history=[projected], step_output_sha256s=[output["output_sha256"]])
        path = f"/{review['review_id']}/history"
        status, first = self.call(path, query="entry=0&limit=32")
        self.assertEqual(status, 200)
        self.assertIsNotNone(first["next_cursor"])
        tampered = {key: copy.deepcopy(value) for key, value in output.items() if key not in ("artifact_type", "output_sha256")}
        tampered["raw_text"] = "旧输出已被擅自替换，不能继续使用旧分页游标"
        self.conn.execute("UPDATE chronicle.ingestion_outputs SET payload=%s WHERE artifact_sha256=%s", (Jsonb(tampered), output["output_sha256"]))
        self.conn.commit()
        status, body = self.call(path, query=f"entry=0&cursor={first['next_cursor']}")
        self.assertEqual((status, body["error"]["code"]), (409, "plan_drift"))

    def test_queue_scope_has_content_and_keeps_legacy_default(self):
        review = self.freeze()
        for scope in ("all", "chapter_content"):
            status, page = self.call(query=f"review_scope={scope}")
            self.assertEqual(status, 200)
            self.assertEqual(page["open_count"], 1)
            self.assertEqual(page["items"][0]["plan_fingerprint"], review["plan_fingerprint"])
            self.assertEqual(page["items"][0]["scope"], "chapter_content")
        self.assertEqual(self.call()[1]["items"], [])
        self.assertEqual(self.call(query="review_scope=chapter_content&link_kind=entity")[0], 400)

    def test_decision_rejects_missing_issues_patches_stale_candidate_and_repeated_submit(self):
        review = self.freeze()
        packet = self.packet(review["review_id"])
        path = f"/{review['review_id']}/decision"
        for changes, expected in (({"issue_dispositions": []}, 400), ({"patches": []}, 400), ({"candidate_sha256": "0" * 64}, 409)):
            status, _ = self.call(path, method="POST", body=decision_for(packet, **changes))
            self.assertEqual(status, expected)
            self.assertEqual(self.call(f"/{review['review_id']}")[1]["review"]["status"], "open")
        status, body = self.call(path, method="POST", body=decision_for(packet))
        self.assertEqual(status, 200)
        self.assertEqual(body["review"]["status"], "resolved")
        self.assertEqual(self.call(path, method="POST", body=decision_for(packet))[0], 409)
        with psycopg.connect(self.database_url) as conn:
            fixed = reviews.get_content_decision(conn, review["review_id"])
            self.assertEqual(fixed["candidate_sha256"], packet["candidate_sha256"])
            self.assertEqual(fixed["decision"], "accept")

    def test_concurrent_decisions_have_one_winner(self):
        review = self.freeze()
        decision = decision_for(self.packet(review["review_id"]))
        barrier = threading.Barrier(2)
        outcomes = []
        def submit():
            barrier.wait(timeout=5)
            outcomes.append(self.call(f"/{review['review_id']}/decision", method="POST", body=decision)[0])
        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(sorted(outcomes), [200, 409])

    def test_cancelled_job_cannot_be_decided_and_reject_cancels(self):
        review = self.freeze()
        packet = self.packet(review["review_id"])
        control.cancel_job(self.conn, job_id=self.job_id)
        self.conn.commit()
        self.assertEqual(self.call(f"/{review['review_id']}/decision", method="POST", body=decision_for(packet))[0], 409)
        self.assertEqual(self.call(query="review_scope=chapter_content")[1]["open_count"], 0)
        status, body = self.call(f"/{review['review_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(body["review"]["status"], "dismissed")
        self.assertEqual(body["review"]["chapter_content"]["history_count"], 2)

    def test_revision_saves_only_a_patch_and_requires_a_distinct_rechecked_version(self):
        from chapter_production import apply_patches
        review = self.freeze()
        packet = self.packet(review["review_id"])
        before = self.candidate["translation"]["blocks"][0]["text"]
        patch = {"op": "replace", "path": "/translation/blocks/0/text", "before_sha256": sha256_json(before), "value": before + "（合成修订测试）"}
        decision = decision_for(packet, decision="revise", patches=[patch])
        status, body = self.call(f"/{review['review_id']}/decision", method="POST", body=decision)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["review"]["chapter_content"]["decision"]["decision"], "revise")
        self.assertEqual(body["review"]["chapter_content"]["candidate"], self.candidate)
        amended = apply_patches(self.candidate, [patch])
        amended_history = self.history + [{"step": "human_revision", "patches": [patch], "prior_review": review["review_id"]}]
        next_review = self.freeze(candidate=amended, history=amended_history)
        self.assertNotEqual(next_review["review_id"], review["review_id"])
        self.assertNotEqual(next_review["candidate_sha256"], review["candidate_sha256"])
        self.assertEqual(self.call(f"/{next_review['review_id']}/decision", method="POST", body=decision_for(packet))[0], 409)
        self.assertEqual(self.packet(next_review["review_id"])["history"][:2], self.history)

    def test_bad_revision_hash_or_attempted_source_rewrite_keeps_review_open(self):
        review = self.freeze()
        packet = self.packet(review["review_id"])
        for patch in (
            {"path": "/translation/blocks/0/text", "before_sha256": "0" * 64, "value": "错版本的修订"},
            {"path": "/source_scope", "before_sha256": sha256_json(self.candidate["source_scope"]), "value": {}},
        ):
            status, _ = self.call(f"/{review['review_id']}/decision", method="POST", body=decision_for(packet, decision="revise", patches=[patch]))
            self.assertEqual(status, 400)
        self.assertEqual(self.call(f"/{review['review_id']}")[1]["review"]["status"], "open")

    def test_reject_is_durable_and_cancels_job(self):
        review = self.freeze()
        packet = self.packet(review["review_id"])
        status, body = self.call(f"/{review['review_id']}/decision", method="POST", body=decision_for(packet, decision="reject"))
        self.assertEqual(status, 200)
        self.assertEqual(body["review"]["job_status"], "cancelled")
        self.assertEqual(body["review"]["chapter_content"]["decision"]["decision"], "reject")

    def test_old_owner_and_expired_lease_cannot_open_review(self):
        with self.assertRaises(LeaseLost):
            self.freeze(worker="stale-worker")
        self.conn.execute("UPDATE chronicle.ingestion_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (self.job_id,))
        self.conn.commit()
        with self.assertRaises(LeaseLost):
            self.freeze()
        self.conn.rollback()
        self.assertEqual(self.conn.execute("SELECT count(*) FROM chronicle.review_items").fetchone()[0], 0)

    def test_no_complete_candidate_is_reviewable_but_never_accepted(self):
        review = self.freeze(candidate=None)
        status, body = self.call(f"/{review['review_id']}")
        self.assertEqual(status, 200)
        self.assertFalse(body["review"]["chapter_content"]["can_accept"])
        self.assertEqual(body["review"]["allowed_decisions"], ["reject"])
        self.assertEqual(self.call(f"/{review['review_id']}/decision", method="POST", body=decision_for(self.packet(review["review_id"])))[0], 409)


if __name__ == "__main__":
    unittest.main()
