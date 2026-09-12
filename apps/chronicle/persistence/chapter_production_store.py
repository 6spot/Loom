"""Staged chapter logs in the existing application ingestion output store.

There is no second job queue. Attempts, drafts and acceptance receipts are
immutable output payloads; the ordinary chunk checkpoint is only a pointer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import control_plane
import chapter_contract
import chapter_production
from common import PersistenceConflict, PersistenceError, sha256_json
from resolve_publish import require_unexpired_lease

PLAN_TYPE = "chapter-production-plan"
ATTEMPT_TYPE = "chapter-production-attempt"
STEP_TYPE = "chapter-production-step"
DRAFT_TYPE = "chapter-production-draft"
ACCEPTANCE_TYPE = "chapter-production-acceptance"


class StepBudgetExhausted(PersistenceError):
    pass


def read_outputs(conn, *, job_id, chunk_id) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT artifact_type, artifact_sha256, payload
           FROM chronicle.ingestion_outputs
           WHERE job_id = %s AND artifact_type LIKE 'chapter-production-%%'
             AND payload->>'chunk_id' = %s
           ORDER BY created_at, output_id""", (job_id, str(chunk_id)),
    ).fetchall()
    outputs = []
    for artifact_type, digest, payload in rows:
        if not isinstance(payload, dict) or sha256_json(payload) != digest:
            raise PersistenceConflict("staged chapter output hash drift")
        outputs.append({"artifact_type": artifact_type, "output_sha256": digest, **payload})
    return outputs


def append_output(conn, *, job_id, chunk_id, worker, artifact_type, payload) -> dict:
    with conn.transaction():
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
        row = conn.execute(
            """SELECT j.revision_id, c.checkpoint FROM chronicle.ingestion_jobs j
               JOIN chronicle.ingestion_chunks c ON c.job_id = j.job_id
               WHERE j.job_id = %s AND c.chunk_id = %s""", (job_id, chunk_id),
        ).fetchone()
        if row is None:
            raise PersistenceConflict("chapter output chunk does not belong to this job")
        value = {**payload, "chunk_id": str(chunk_id)}
        digest = sha256_json(value)
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=row[0], worker=worker,
            artifact_type=artifact_type, artifact_sha256=digest, payload=value,
        )
        checkpoint = dict(row[1] or {})
        prior = dict(checkpoint.get("production") or {})
        prior.update({"pipeline_fingerprint": value.get("pipeline_fingerprint"),
                      "last_output_sha256": digest, "step": value.get("step"),
                      "status": value.get("status"), "round": value.get("round", 0),
                      "model": value.get("model"), "attempt": value.get("attempt")})
        if value.get("node_key") and artifact_type in (ATTEMPT_TYPE, STEP_TYPE):
            steps = dict(prior.get("steps") or {})
            summary = {key: value.get(key) for key in (
                "step", "slot", "model", "status", "round", "attempt", "error")}
            summary["output_sha256"] = digest
            receipt = value.get("receipt") or {}
            summary["elapsed_seconds"] = receipt.get("elapsed_seconds")
            summary["usage"] = receipt.get("usage")
            steps[value["node_key"]] = summary
            prior["steps"] = steps
        checkpoint["production"] = prior
        control_plane.write_chunk_checkpoint_fenced(
            conn, job_id=job_id, chunk_id=chunk_id, worker=worker, checkpoint=checkpoint)
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return {"artifact_type": artifact_type, "output_sha256": digest, **value}


def freeze_pipeline(conn, *, job_id, chunk_id, worker, request, config) -> dict:
    with conn.transaction():
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
        # The lease lock serializes all chapter plans for this job. A resume
        # can skip an already accepted chapter, so checking only this chunk
        # would silently mix model/prompt policies across the same source.
        job_configs = conn.execute(
            "SELECT payload->'config' FROM chronicle.ingestion_outputs"
            " WHERE job_id = %s AND artifact_type = %s", (job_id, PLAN_TYPE),
        ).fetchall()
        if any(row[0] != config for row in job_configs):
            raise PersistenceConflict("chapter_pipeline_drift: model and step configuration is frozen for the whole job")
        fingerprint = sha256_json({"request": request, "config": config})
        existing = [row for row in read_outputs(conn, job_id=job_id, chunk_id=chunk_id)
                    if row["artifact_type"] == PLAN_TYPE]
        if existing:
            if len(existing) != 1 or existing[0].get("pipeline_fingerprint") != fingerprint:
                raise PersistenceConflict("chapter_pipeline_drift: source, prompt, policy or model configuration changed")
            return existing[0]
        return append_output(conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
            artifact_type=PLAN_TYPE, payload={
                "schema": "chronicle.chapter-production-plan", "version": "0.1",
                "chapter_id": request["chapter_id"], "request": request, "config": config,
                "request_fingerprint": chapter_contract.request_fingerprint(request),
                "pipeline_fingerprint": fingerprint, "status": "frozen",
            })


def node_key(plan: dict, *, step: str, round: int, slot: str, data: dict,
             prompt: str, model_config: dict) -> str:
    return sha256_json({"pipeline_fingerprint": plan["pipeline_fingerprint"],
                       "step": step, "round": round, "slot": slot,
                       "data": data, "prompt": prompt, "model_config": model_config})


def begin_attempt(conn, *, job_id, chunk_id, worker, plan, step, round, slot,
                  data, prompt, model_config, max_attempts) -> tuple[dict, bool]:
    """Return a saved complete result or reserve exactly one finite attempt.

    A crash before saving a response consumes an attempt, since whether the
    remote service finished is unknown. It never becomes a successful vote.
    """
    with conn.transaction():
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
        key = node_key(plan, step=step, round=round, slot=slot, data=data,
                       prompt=prompt, model_config=model_config)
        records = read_outputs(conn, job_id=job_id, chunk_id=chunk_id)
        results = [r for r in records if r["artifact_type"] == STEP_TYPE and r.get("node_key") == key]
        completed = [r for r in results if r["status"] == "completed"]
        if completed:
            if len(completed) != 1:
                raise PersistenceConflict("one chapter node has multiple completed results")
            return completed[0], True
        invalid = [row for row in results if row["status"] == "invalid"]
        previous = max(invalid, key=lambda row: row["attempt"]) if invalid else None
        if previous is not None and step not in chapter_production.FORMAT_RETRY_STEPS:
            # Reuse the malformed opinion for the existing human gate even
            # if a later sibling failed or the attempt budget is exhausted.
            # A new model response must not erase an unresolved objection.
            return previous, True
        starts = [r for r in records if r["artifact_type"] == ATTEMPT_TYPE and r.get("node_key") == key]
        if len(starts) >= max_attempts:
            raise StepBudgetExhausted(f"{step}/{slot}: {max_attempts} saved attempts exhausted")
        attempt = len(starts) + 1
        # A transport failure did not correct the last invalid result. Keep
        # its exact feedback on resume without spending a fresh node budget.
        actual_prompt = prompt
        if previous is not None:
            actual_prompt = chapter_production.retry_prompt(
                prompt, previous, max_chars=plan["request"]["limits"]["max_prompt_chars"])
        return append_output(conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
            artifact_type=ATTEMPT_TYPE, payload={
                "schema": "chronicle.chapter-step-attempt", "version": "0.1",
                "chapter_id": plan["chapter_id"], "pipeline_fingerprint": plan["pipeline_fingerprint"],
                "request_fingerprint": plan["request_fingerprint"], "node_key": key,
                "step": step, "round": round, "slot": slot, "attempt": attempt,
                "input_sha256": sha256_json(data), "model": model_config["model"],
                "model_config": model_config, "prompt": actual_prompt, "input": data,
                "base_prompt_sha256": sha256_json(prompt),
                "retry_of": previous["output_sha256"] if actual_prompt != prompt else None,
                "status": "started", "started_at": datetime.now(timezone.utc).isoformat(),
            }), False


def finish_attempt(conn, *, job_id, chunk_id, worker, attempt, raw_text, parsed,
                   validation_errors, receipt, status, error=None) -> dict:
    with conn.transaction():
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
        rows = read_outputs(conn, job_id=job_id, chunk_id=chunk_id)
        if any(r["artifact_type"] == STEP_TYPE and r.get("attempt_sha256") == attempt["output_sha256"] for r in rows):
            raise PersistenceConflict("chapter attempt already has a saved result")
        if not any(r["artifact_type"] == ATTEMPT_TYPE and r["output_sha256"] == attempt["output_sha256"] for r in rows):
            raise PersistenceConflict("chapter attempt has no durable start")
        return append_output(conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
            artifact_type=STEP_TYPE, payload={
                "schema": "chronicle.chapter-step", "version": "0.1",
                **{key: attempt[key] for key in (
                    "chapter_id", "pipeline_fingerprint", "request_fingerprint", "node_key",
                    "step", "round", "slot", "attempt", "input_sha256", "model")},
                "attempt_sha256": attempt["output_sha256"], "raw_text": raw_text,
                "parsed": parsed, "validation_errors": validation_errors, "receipt": receipt,
                "status": status, "error": error,
            })


def save_draft(conn, *, job_id, chunk_id, worker, plan, candidate, round,
               history_refs, issues, parent_sha256=None) -> dict:
    with conn.transaction():
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
        records = read_outputs(conn, job_id=job_id, chunk_id=chunk_id)
        previous = [r for r in records if r["artifact_type"] == DRAFT_TYPE and r.get("round") == round]
        value = {"schema": "chronicle.chapter-production-draft", "version": "0.1",
                 "chapter_id": plan["chapter_id"], "pipeline_fingerprint": plan["pipeline_fingerprint"],
                 "request_fingerprint": plan["request_fingerprint"], "candidate": candidate,
                 "candidate_sha256": sha256_json(candidate), "round": round,
                 "history_refs": list(dict.fromkeys(history_refs)), "issues": issues,
                 "parent_sha256": parent_sha256, "status": "draft", "chunk_id": str(chunk_id)}
        if previous:
            if len(previous) != 1 or previous[0]["output_sha256"] != sha256_json(value):
                raise PersistenceConflict("chapter draft version already frozen with different inputs")
            return previous[0]
        known = {r["output_sha256"] for r in records}
        if set(history_refs) - known:
            raise PersistenceConflict("draft refers to unsaved history")
        return append_output(conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
                             artifact_type=DRAFT_TYPE, payload=value)


def resolve_history(records: list[dict], refs: list[str]) -> list[dict]:
    by_sha = {record["output_sha256"]: record for record in records}
    if len(refs) != len(set(refs)) or set(refs) - set(by_sha):
        raise PersistenceConflict("chapter opinion history references are missing or duplicated")
    return [by_sha[ref] for ref in refs]
