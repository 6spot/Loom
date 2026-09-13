"""Two review gates inside the existing present stage; no new worker queue."""
from __future__ import annotations

import json
import os
import threading

import psycopg

import control_plane
import narrative_contract as contract
import narrative_store as store
from common import PersistenceConflict, PersistenceError
from model_provider import ResponsesHTTPModel, timeout_from_env
from reader_language import narrative_text


def model_from_env():
    name = os.environ.get("CHRONICLE_NARRATIVE_MODEL", "").strip()
    if not name:
        return None
    endpoint = os.environ.get("CHRONICLE_MODEL_ENDPOINT", "").strip()
    if not endpoint:
        raise PersistenceError("CHRONICLE_MODEL_ENDPOINT is required for the historical narrative model")
    return ResponsesHTTPModel(name=name, endpoint=endpoint,
        api_key=os.environ.get("CHRONICLE_MODEL_API_KEY") or None,
        timeout_seconds=timeout_from_env(), text_format={"type": "json_object"},
        max_output_tokens=32768, max_response_bytes=contract.MAX_BYTES)


def _complete(database_url, *, job_id, worker, lease_seconds, model, prompt):
    """Keep a bounded provider wait fenced, without holding a transaction."""
    stop = threading.Event()
    failures = []

    def heartbeat():
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            control_plane.heartbeat_job_strict(conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds)

    def keep_alive():
        while not stop.wait(max(0.2, min(30, lease_seconds / 3))):
            try:
                heartbeat()
            except Exception as exc:
                failures.append(exc)
                return

    heartbeat()
    thread = threading.Thread(target=keep_alive, daemon=True)
    thread.start()
    try:
        raw = model.complete(prompt)
    finally:
        stop.set()
        thread.join()
    if failures:
        raise failures[0]
    heartbeat()
    if not isinstance(raw, str) or len(raw.encode()) > contract.MAX_BYTES:
        raise PersistenceError("narrative model response exceeds the candidate envelope")
    return raw


def _generate(database_url, *, job_id, worker, lease_seconds, model, kind, context, facts):
    base = contract.build_prompt(kind, context, facts)
    _, references = contract.model_reference_maps(context)
    correction = ""
    with psycopg.connect(database_url) as conn:
        previous = store.read_last_attempt(conn, job_id=job_id, kind=kind, context=context)
    if previous and previous.get("validation_error"):
        correction = _correction(previous["raw_response"], previous["validation_error"])
    for attempt in range(3):
        prompt = correction + base
        if len(prompt) > contract.MAX_PROMPT_CHARS:
            raise PersistenceError("complete correction context exceeds input budget "
                f"({len(prompt)} > {contract.MAX_PROMPT_CHARS} characters); reduce scope, never truncate")
        raw = _complete(database_url, job_id=job_id, worker=worker, lease_seconds=lease_seconds,
                        model=model, prompt=prompt)
        error = None
        try:
            candidate = narrative_text(contract.map_candidate_references(json.loads(raw), references))
            if kind == "facts":
                contract.validate_facts(candidate, context)
            else:
                if "navigation" not in candidate:
                    raise PersistenceError("综合正文须一并返回 navigation：按已审核时间归组、覆盖全文并包含全部精选入口")
                contract.validate_prose(candidate, context, facts)
        except (ValueError, TypeError, PersistenceError) as exc:
            error = str(exc)[:6000]
        with psycopg.connect(database_url) as conn:
            store.save_attempt(conn, job_id=job_id, worker=worker, kind=kind, context=context,
                               prompt=prompt, response=raw, model=model.name, error=error)
        if error is None:
            return candidate
        # Re-render the same complete context. Diagnostics do not authorize
        # inventing IDs, trimming the chapter, or accepting a partial patch.
        correction = _correction(raw, error)
    raise PersistenceError(f"narrative {kind} failed validation after 3 complete attempts: {error}")


def _correction(raw, error):
    return f"CORRECTION: previous complete candidate was rejected: {error}\n请修正以下完整旧稿的所有诊断，保留已经正确的内容，并补齐全部已批准阶段，输出完整 JSON；不要提交局部补丁或删除后半部。完整来源仍在 INPUT 中。\nPREVIOUS_CANDIDATE={raw}\n"


def execute(database_url, *, job_id, worker, revision_source, model, lease_seconds, scope=None):
    if not callable(getattr(model, "complete", None)) or not getattr(model, "name", None):
        raise PersistenceError("historical narrative provider requires complete(prompt) and a model name")
    with psycopg.connect(database_url) as conn:
        facts_row = store.read_candidate(conn, job_id, "facts")
        descriptors = store.source_descriptors(conn, **(scope or {})) if facts_row is None else None
    context = facts_row["context"] if facts_row else store.build_context(descriptors, revision_source)
    for kind in ("facts", "prose"):
        with psycopg.connect(database_url) as conn:
            row = store.read_candidate(conn, job_id, kind)
            facts = store.approved_content(store.read_candidate(conn, job_id, "facts")) if kind == "prose" else None
        if row is None:
            candidate = _generate(database_url, job_id=job_id, worker=worker, lease_seconds=lease_seconds,
                                  model=model, kind=kind, context=context, facts=facts)
            with psycopg.connect(database_url) as conn:
                row = store.save_candidate(conn, job_id=job_id, worker=worker, kind=kind,
                                           context=context, candidate=candidate, model=model.name)
        if row["status"] == "open":
            return "needs_review"
        # Reject/dismiss never means approval and never advances to public prose.
        store.approved_content(row)
    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            import resolve_publish
            publication = store.publish(conn, job_id=job_id, worker=worker)
            control_plane.write_stage_checkpoint_fenced(conn, job_id=job_id, stage="present", worker=worker,
                checkpoint={"historical_narrative_version": publication["publication_version"],
                            "catalog_sha": context["catalog_sha"], "reviewed": True})
            control_plane.advance_stage_fenced(conn, job_id=job_id, stage="present", status="completed", worker=worker)
            resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return "ok"
