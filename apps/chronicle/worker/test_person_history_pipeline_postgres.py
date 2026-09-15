"""PostgreSQL integration coverage for the independent person-history path."""

from __future__ import annotations

import copy
import json
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

import psycopg

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence", HERE.parent / "read_api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import control_plane  # noqa: E402
import studio_jobs  # noqa: E402
import person_history_store  # noqa: E402
import test_reading_pipeline_postgres as base  # noqa: E402
import person_history_contract as contract  # noqa: E402


class PersonHistoryTestModel:
    """A two-slot provider that deliberately leaves comparison for review."""

    name = "person-history-integration-model"
    steps = {
        "summary_generate": ("model_a", "model_b"),
        "summary_compare": ("judge",),
        "prose_generate": ("model_a", "model_b"),
        "prose_compare": ("judge",),
    }
    max_parallel = 2
    max_step_attempts = 3
    max_response_bytes = contract.MAX_BYTES

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: list[str] = []

    @staticmethod
    def _input(prompt: str) -> dict:
        value = prompt.split("\nINPUT=", 1)[1]
        for marker in ("\nAPPROVED_SUMMARY_SHA256=", "\nCANDIDATE_SET_SHA256="):
            if marker in value:
                value = value.split(marker, 1)[0]
        return json.loads(value)

    def public_config(self) -> dict:
        return {
            "models": {slot: {"model": f"{self.name}:{slot}"} for slot in ("model_a", "model_b", "judge")},
            "max_parallel": self.max_parallel,
            "max_step_attempts": self.max_step_attempts,
        }

    def model_for(self, _step: str, _slot: str):
        return self

    def model_config(self, _step: str, slot: str) -> dict:
        return {"model": f"{self.name}:{slot}"}

    def _summary(self, context: dict) -> dict:
        phases = []
        conclusions = []
        for index, source in enumerate(context["sources"]):
            source_conclusions = [
                item for item in context["approved_conclusions"]
                if item.get("source_id") == source["source_id"]
            ]
            if not source_conclusions:
                continue
            phase_id = f"phase_{index + 1:03}"
            evidence_id = source["evidence"][0]["id"]
            positions = context.get("main_history_positions") or []
            mapping_ids = [item["id"] for item in positions]
            phases.append({
                "id": phase_id,
                "label": source.get("title") or f"第{index + 1}阶段",
                "year": None,
                "period": None,
                "basis": [evidence_id],
                "relation_to_previous": "uncertain" if not phases else "after",
                "mapping_status": "ambiguous" if len(mapping_ids) > 1 else "mapped" if mapping_ids else "unmapped",
                "mapping_position_ids": mapping_ids,
                "mapping_reason": "主历史有多个可对应段落，保留歧义。" if len(mapping_ids) > 1 else "当前没有足够可靠的主历史对应位置。" if not mapping_ids else "仅保留程序提供的可靠主历史位置。",
            })
            approved = source_conclusions[0]
            dimension = approved.get("dimension")
            value = approved.get("value")
            if dimension not in {"office", "title", "allegiance", "action", "related_person", "related_place"}:
                dimension, value = "action", None
            if dimension in {"office", "title", "allegiance"} and not isinstance(value, str):
                dimension, value = "action", None
            conclusions.append({
                "id": f"conclusion_{index + 1:03}",
                "person_id": context["target"]["person_id"],
                "dimension": dimension,
                "phase_ids": [phase_id],
                "text": approved.get("text") or "来源明确记载了这一阶段的内容。",
                "value": value,
                "certainty": approved.get("certainty") if approved.get("certainty") in {"clear", "uncertain"} else "uncertain",
                "qualification": approved.get("qualification") if approved.get("qualification") in {"ordinary", "recommendation", "self_designation", "posthumous", "reported"} else "ordinary",
                "event_id": None,
                "related_entity_ids": [],
                "evidence": [{
                    "id": evidence_id,
                    "relation": "support",
                    "attribution": "已发布原章",
                    "note": "原文证据与批准来源结论相互绑定。",
                }],
                "approved_conclusion_ids": [approved["id"]],
            })
        if not phases or not conclusions:
            raise AssertionError("integration source fixture did not expose a person conclusion")
        return {
            "schema": "chronicle.person-history-summary",
            "version": "0.1",
            "person_id": context["target"]["person_id"],
            "title": "周瑜生平概况",
            "overview": "以下概况仅整理当前收录资料明确记载的经历。",
            "birth": None,
            "death": None,
            "coverage": {
                "statement": "根据当前收录资料整理的经历",
                "exhaustive": False,
                "source_ids": [source["source_id"] for source in context["sources"]],
                "publication_ids": [source["publication_id"] for source in context["sources"]],
            },
            "phases": phases,
            "conclusions": conclusions,
        }

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        stage = prompt.split("\nSTAGE=", 1)[1].split("\n", 1)[0]
        self.calls.append(stage)
        context = self._input(prompt)
        if stage == "summary_generate":
            return json.dumps(self._summary(context), ensure_ascii=False)
        if stage == "prose_generate":
            summary_sha = prompt.split("\nAPPROVED_SUMMARY_SHA256=", 1)[1].split("\n", 1)[0]
            summary = json.loads(prompt.split("\nAPPROVED_SUMMARY=", 1)[1])
            paragraphs = []
            for phase in summary["phases"]:
                cited = [
                    item["id"] for item in summary["conclusions"]
                    if phase["id"] in item["phase_ids"]
                ]
                paragraphs.append({
                    "id": f"paragraph_{len(paragraphs) + 1:03}",
                    "phase_id": phase["id"],
                    "segments": [{
                        "text": f"据当前收录资料，{phase['label']}的相关经历有明确原文依据。",
                        "conclusion_ids": cited,
                        "event_id": None,
                        "related_entity_ids": [],
                    }],
                })
            return json.dumps({
                "schema": "chronicle.person-history-prose",
                "version": "0.1",
                "person_id": context["target"]["person_id"],
                "summary_sha256": summary_sha,
                "coverage": copy.deepcopy(summary["coverage"]),
                "paragraphs": paragraphs,
            }, ensure_ascii=False)
        if stage in {"summary_compare", "prose_compare"}:
            candidates = json.loads(prompt.split("\nCANDIDATES=", 1)[1])
            candidate_set_sha = prompt.split("\nCANDIDATE_SET_SHA256=", 1)[1].split("\n", 1)[0]
            evidence_id = context["sources"][0]["evidence"][0]["id"]
            return json.dumps({
                "schema": "chronicle.person-history-comparison",
                "version": "0.1",
                "product": "summary" if stage == "summary_compare" else "prose",
                "candidate_set_sha256": candidate_set_sha,
                "selected_sha256": candidates[0]["candidate_sha256"],
                "selection_rationale": "两份候选均保留，但仍需人工逐条核对来源绑定。",
                "differences": [
                    {
                        "candidate_sha256": item["candidate_sha256"],
                        "assessment": "selected" if index == 0 else "compatible",
                        "rationale": "候选结构完整，待人工确认其来源引用。",
                        "evidence": [evidence_id],
                    }
                    for index, item in enumerate(candidates)
                ],
                "disagreements": [{
                    "id": "comparison_disputed",
                    "message": "模型比较未能消除候选差异，转入人工审核。",
                    "evidence": [evidence_id],
                }],
            }, ensure_ascii=False)
        raise AssertionError(f"unexpected person-history model stage: {stage}")


class PersonHistoryTransientFailureModel(PersonHistoryTestModel):
    """Inject one malformed step response, then recover through T04 retries."""

    def __init__(self) -> None:
        super().__init__()
        self._failure_lock = threading.Lock()
        self.failure_injected = False

    def complete(self, prompt: str) -> str:
        stage = prompt.split("\nSTAGE=", 1)[1].split("\n", 1)[0]
        if stage == "summary_generate":
            with self._failure_lock:
                if not self.failure_injected:
                    self.failure_injected = True
                    self.prompts.append(prompt)
                    self.calls.append(stage)
                    return '{"schema":"injected-incomplete"'
        return super().complete(prompt)


class PersonHistoryPipelinePostgresTests(unittest.TestCase):
    """Exercise source publication -> person gates -> independent publish."""

    AUTO_APPROVE_PERSON_STATE = True

    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = base._control_url()

    setUp = base.ReadingPipelinePostgresTests.setUp
    tearDown = base.ReadingPipelinePostgresTests.tearDown
    _queue_job = base.ReadingPipelinePostgresTests._queue_job
    _prepare_model = base.ReadingPipelinePostgresTests._prepare_model
    _run_once = base.ReadingPipelinePostgresTests._run_once
    _approve_person_state = base.ReadingPipelinePostgresTests._approve_person_state

    def _queue_person_history_job(self):
        with psycopg.connect(self.database_url) as conn:
            choices = person_history_store.list_person_choices(conn)
            person = next((item for item in choices["items"] if "周瑜" in item["name"]), None)
            self.assertIsNotNone(person, choices)
            source_ids = [
                item["publication_id"]
                for item in person_history_store.narrative_store.list_source_choices(conn)["items"]
            ]
            status, _content_type, body = studio_jobs.dispatch_jobs(
                conn,
                control_plane,
                method="POST",
                path="/api/v1/studio/jobs/person-history",
                body=json.dumps({
                    "person_id": person["person_id"],
                    "catalog_sha": choices["catalog_sha"],
                    "publication_ids": source_ids,
                }).encode(),
            )
            self.assertEqual(201, status, body)
            return (
                uuid.UUID(json.loads(body)["job"]["job_id"]),
                person,
                source_ids,
            )

    def test_person_history_has_two_review_gates_and_immutable_publication(self) -> None:
        text = base.TEXT_DISTINCT
        source_job, _revision, source_sha = self._queue_job(text)
        source_model, _plan = self._prepare_model(text, _revision, source_sha)
        self.assertEqual("completed", self._run_once(source_job, text, source_sha, source_model)[1])

        with psycopg.connect(self.database_url) as conn:
            choices = person_history_store.list_person_choices(conn)
            person = next((item for item in choices["items"] if "周瑜" in item["name"]), None)
            self.assertIsNotNone(person, choices)
            source_ids = [item["publication_id"] for item in person_history_store.narrative_store.list_source_choices(conn)["items"]]
            status, _content_type, body = studio_jobs.dispatch_jobs(
                conn,
                control_plane,
                method="POST",
                path="/api/v1/studio/jobs/person-history",
                body=json.dumps({
                    "person_id": person["person_id"],
                    "catalog_sha": choices["catalog_sha"],
                    "publication_ids": source_ids,
                }).encode(),
            )
            self.assertEqual(201, status, body)
            person_job = json.loads(body)["job"]["job_id"]

        model = PersonHistoryTestModel()
        result = self._run_once(
            uuid.UUID(person_job), text, source_sha, source_model,
            narrative_model=model,
        )
        self.assertEqual("needs_review", result[1])
        self.assertEqual(2, model.calls.count("summary_generate"))
        self.assertEqual(1, model.calls.count("summary_compare"))

        with psycopg.connect(self.database_url) as conn:
            summary = person_history_store.read_candidate(conn, person_job, "summary")
            self.assertEqual("open", summary["status"])
            self.assertIsNone(person_history_store.read_publication(conn, person_id=person["person_id"]))
            original_summary_sha = summary["candidate_sha"]
            revised_content = copy.deepcopy(summary["candidate"])
            revised_content["overview"] = "以下概况仅整理当前收录资料明确记载的经历，并保留未确定处。"
            revised = person_history_store.revise_candidate(
                conn,
                job_id=person_job,
                kind="summary",
                candidate_sha=original_summary_sha,
                content=revised_content,
                rationale="补充范围限定后重新核对概况，保留原稿及其审计记录。",
            )
            self.assertEqual(1, revised["revision_no"])
            self.assertEqual(original_summary_sha, revised["parent_candidate_sha"])
            self.assertEqual(2, conn.execute(
                "SELECT count(*) FROM chronicle.person_history_candidates WHERE job_id = %s AND kind = 'summary'",
                (person_job,),
            ).fetchone()[0])
            summary = revised
            person_history_store.decide(
                conn,
                review_id=summary["review_id"],
                candidate_sha=summary["candidate_sha"],
                decision="approve",
                rationale="逐条核对概况结论与完整原章证据。",
                reviewed_conclusion_ids=[item["id"] for item in summary["candidate"]["conclusions"]],
            )
            control_plane.resume_job(conn, job_id=person_job)

        result = self._run_once(
            uuid.UUID(person_job), text, source_sha, source_model,
            narrative_model=model,
        )
        self.assertEqual("needs_review", result[1])
        self.assertEqual(2, model.calls.count("summary_generate"))
        self.assertEqual(1, model.calls.count("summary_compare"))
        self.assertEqual(2, model.calls.count("prose_generate"))
        self.assertEqual(1, model.calls.count("prose_compare"))

        with psycopg.connect(self.database_url) as conn:
            prose = person_history_store.read_candidate(conn, person_job, "prose")
            self.assertEqual("open", prose["status"])
            reviewed = sorted({
                conclusion_id
                for paragraph in prose["candidate"]["paragraphs"]
                for segment in paragraph["segments"]
                for conclusion_id in segment["conclusion_ids"]
            })
            person_history_store.decide(
                conn,
                review_id=prose["review_id"],
                candidate_sha=prose["candidate_sha"],
                decision="approve",
                rationale="逐段核对正文、阶段边界和引用结论。",
                reviewed_conclusion_ids=reviewed,
            )
            control_plane.resume_job(conn, job_id=person_job)

        result = self._run_once(
            uuid.UUID(person_job), text, source_sha, source_model,
            narrative_model=model,
        )
        self.assertEqual("completed", result[1])
        self.assertEqual(2, model.calls.count("summary_generate"))
        self.assertEqual(1, model.calls.count("summary_compare"))
        self.assertEqual(2, model.calls.count("prose_generate"))
        self.assertEqual(1, model.calls.count("prose_compare"))

        with psycopg.connect(self.database_url) as conn:
            publication = person_history_store.read_publication(conn, person_id=person["person_id"])
            self.assertIsNotNone(publication)
            self.assertEqual("person", publication["person"]["kind"])
            self.assertEqual("根据当前收录资料整理的经历", publication["coverage"]["statement"])
            self.assertEqual(len(source_ids), len(publication["source_publication_ids"]))
            mappings = person_history_store.list_mappings(conn, version=publication["publication_version"])
            self.assertTrue(mappings)
            self.assertTrue(all(item["mapping_status"] in {"mapped", "ambiguous", "unmapped"} for item in mappings))
            self.assertEqual(1, conn.execute("SELECT count(*) FROM chronicle.person_histories").fetchone()[0])
            self.assertEqual(2, conn.execute("SELECT count(*) FROM chronicle.person_history_acceptances").fetchone()[0])
            self.assertEqual(3, conn.execute(
                "SELECT count(*) FROM chronicle.person_history_candidates WHERE job_id = %s",
                (person_job,),
            ).fetchone()[0])
            with self.assertRaises(psycopg.Error):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.person_histories SET payload = '{}'::jsonb"
                        " WHERE version_sha = %s",
                        (publication["publication_version"],),
                    )

    def test_person_history_recovers_step_failure_and_worker_restart_before_publication(self) -> None:
        text = base.TEXT_DISTINCT
        source_job, revision_id, source_sha = self._queue_job(text)
        source_model, _plan = self._prepare_model(text, revision_id, source_sha)
        self.assertEqual("completed", self._run_once(source_job, text, source_sha, source_model)[1])
        person_job, person, source_ids = self._queue_person_history_job()

        first_model = PersonHistoryTransientFailureModel()
        result = self._run_once(
            person_job, text, source_sha, source_model,
            narrative_model=first_model,
        )
        self.assertEqual("needs_review", result[1])
        self.assertTrue(first_model.failure_injected)
        self.assertIn(
            "PREVIOUS_CANDIDATE={\"schema\":\"injected-incomplete\"",
            "\n".join(first_model.prompts),
        )

        with psycopg.connect(self.database_url) as conn:
            outputs = person_history_store.read_outputs(conn, job_id=person_job)
            summary_steps = [
                item for item in outputs
                if item["artifact_type"] == person_history_store.STEP_TYPE
                and item.get("step") == "summary_generate"
            ]
            self.assertEqual(3, len(summary_steps))
            by_node = {}
            for item in summary_steps:
                by_node.setdefault(item["node_key"], []).append(item)
            self.assertEqual(2, len(by_node))
            invalid = [item for item in summary_steps if item["status"] == "invalid"]
            self.assertEqual(1, len(invalid))
            invalid = invalid[0]
            self.assertEqual('{"schema":"injected-incomplete"', invalid["raw_text"])
            attempts = [
                item for item in outputs
                if item["artifact_type"] == person_history_store.STEP_ATTEMPT_TYPE
                and item.get("node_key") == invalid["node_key"]
            ]
            self.assertEqual([1, 2], sorted(item["attempt"] for item in attempts))
            retry = next(item for item in attempts if item["attempt"] == 2)
            self.assertEqual(invalid["output_sha256"], retry["retry_of"])
            self.assertEqual(0, conn.execute(
                "SELECT count(*) FROM chronicle.person_histories"
            ).fetchone()[0])
            self.assertEqual(0, conn.execute(
                "SELECT count(*) FROM chronicle.person_history_mappings"
            ).fetchone()[0])
            self.assertEqual(0, conn.execute(
                "SELECT count(*) FROM chronicle.person_history_acceptances"
            ).fetchone()[0])

            summary = person_history_store.read_candidate(conn, person_job, "summary")
            self.assertEqual("open", summary["status"])
            person_history_store.decide(
                conn,
                review_id=summary["review_id"],
                candidate_sha=summary["candidate_sha"],
                decision="approve",
                rationale="核对模型重试后的概况候选及其原章证据。",
                reviewed_conclusion_ids=[item["id"] for item in summary["candidate"]["conclusions"]],
            )
            control_plane.resume_job(conn, job_id=person_job)

        recovered_model = PersonHistoryTestModel()
        result = self._run_once(
            person_job, text, source_sha, source_model,
            narrative_model=recovered_model,
        )
        self.assertEqual("needs_review", result[1])
        self.assertEqual(0, recovered_model.calls.count("summary_generate"))
        self.assertEqual(2, recovered_model.calls.count("prose_generate"))
        self.assertEqual(1, recovered_model.calls.count("prose_compare"))

        with psycopg.connect(self.database_url) as conn:
            prose = person_history_store.read_candidate(conn, person_job, "prose")
            self.assertEqual("open", prose["status"])
            reviewed = sorted({
                conclusion_id
                for paragraph in prose["candidate"]["paragraphs"]
                for segment in paragraph["segments"]
                for conclusion_id in segment["conclusion_ids"]
            })
            person_history_store.decide(
                conn,
                review_id=prose["review_id"],
                candidate_sha=prose["candidate_sha"],
                decision="approve",
                rationale="核对重启 worker 生成的正文、阶段边界及引用。",
                reviewed_conclusion_ids=reviewed,
            )
            control_plane.resume_job(conn, job_id=person_job)

        with mock.patch.object(
            person_history_store, "publish", side_effect=RuntimeError("injected person-history publish failure")
        ):
            result = self._run_once(
                person_job, text, source_sha, source_model,
                narrative_model=recovered_model,
            )
        self.assertEqual("failed", result[1])

        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(0, conn.execute(
                "SELECT count(*) FROM chronicle.person_histories"
            ).fetchone()[0])
            self.assertEqual(0, conn.execute(
                "SELECT count(*) FROM chronicle.person_history_mappings"
            ).fetchone()[0])
            control_plane.retry_job(conn, job_id=person_job)

        restarted_model = PersonHistoryTestModel()
        result = self._run_once(
            person_job, text, source_sha, source_model,
            narrative_model=restarted_model,
        )
        self.assertEqual("completed", result[1])
        self.assertEqual([], restarted_model.calls)

        with psycopg.connect(self.database_url) as conn:
            outputs = person_history_store.read_outputs(conn, job_id=person_job)
            self.assertEqual(3, len([
                item for item in outputs
                if item["artifact_type"] == person_history_store.STEP_TYPE
                and item.get("step") == "summary_generate"
            ]))
            self.assertEqual(2, len([
                item for item in outputs
                if item["artifact_type"] == person_history_store.STEP_TYPE
                and item.get("step") == "prose_generate"
            ]))
            publication = person_history_store.read_publication(
                conn, person_id=person["person_id"]
            )
            self.assertIsNotNone(publication)
            self.assertEqual(1, conn.execute(
                "SELECT count(*) FROM chronicle.person_histories"
            ).fetchone()[0])
            self.assertEqual(2, conn.execute(
                "SELECT count(*) FROM chronicle.person_history_acceptances"
            ).fetchone()[0])
            self.assertEqual(len(source_ids), len(publication["source_publication_ids"]))
            mappings = person_history_store.list_mappings(
                conn, version=publication["publication_version"]
            )
            self.assertTrue(mappings)
