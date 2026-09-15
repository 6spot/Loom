"""Auditable acceptance inside the existing present stage; no new worker queue."""
from __future__ import annotations

import json
import threading

import psycopg

import control_plane
import narrative_contract as contract
import narrative_store as store
from common import PersistenceConflict, PersistenceError
from reader_language import narrative_text


def model_from_env(env=None):
    """Resolve the frozen multi-step narrative provider configuration."""
    from narrative_models import from_env

    return from_env(env)


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
            error = str(exc)
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


def _execute_legacy(database_url, *, job_id, worker, revision_source, model, lease_seconds, scope=None):
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
                checkpoint={"history_edition_version": publication["history_edition_version"],
                            "catalog_sha": context["catalog_sha"], "reviewed": True})
            control_plane.advance_stage_fenced(conn, job_id=job_id, stage="present", status="completed", worker=worker)
            resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return "ok"


class PipelineFailure(PersistenceError):
    """A narrative step failed closed; saved successful siblings remain reusable."""


def _supports_step_graph(model):
    return isinstance(getattr(model, "steps", None), dict) and callable(
        getattr(model, "model_for", None)
    )


_STEP_ALIASES = {
    "facts_generate": ("facts_generate", "facts"),
    "facts_compare": ("facts_compare", "facts_review", "facts_compare/review"),
    "prose_generate": ("prose_generate", "prose"),
    "prose_compare": ("prose_compare", "prose_review", "prose_compare/review"),
}


def _configured_step(model, step):
    for name in _STEP_ALIASES[step]:
        if name in model.steps:
            return name
    return step


def _step_slots(model, step):
    for name in _STEP_ALIASES[step]:
        slots = model.steps.get(name)
        if slots is not None:
            values = tuple(slots)
            if not values or len(values) != len(set(values)):
                raise PersistenceError(f"narrative step {step} has no distinct model slots")
            return values
    raise PersistenceError(f"narrative model configuration has no {step} slots")


def _step_config(model, step, slot):
    step = _configured_step(model, step)
    if callable(getattr(model, "model_config", None)):
        return model.model_config(step, slot)
    if callable(getattr(model, "config_for", None)):
        return model.config_for(step, slot)
    provider = model.model_for(step, slot)
    return {"model": getattr(provider, "name", slot)}


def _publish(database_url, *, job_id, worker, lease_seconds, context):
    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            import resolve_publish

            publication = store.publish(conn, job_id=job_id, worker=worker)
            control_plane.write_stage_checkpoint_fenced(
                conn,
                job_id=job_id,
                stage="present",
                worker=worker,
                checkpoint={
                    "history_edition_version": publication["history_edition_version"],
                    "catalog_sha": context["catalog_sha"],
                    "reviewed": True,
                },
            )
            control_plane.advance_stage_fenced(
                conn,
                job_id=job_id,
                stage="present",
                status="completed",
                worker=worker,
            )
            resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return publication


def _multi_compare_issue(kind, comparison_records, *, selections=None):
    """Make a stable human-review issue for unresolved model comparison."""
    selected = sorted(selections or [])
    refs = [record.get("output_sha256") for record in comparison_records if record.get("output_sha256")]
    return {
        "id": "comparison_" + contract.sha256_json([kind, refs, selected])[:24],
        "type": "source_uncertainty",
        "target": f"{kind}_compare",
        "message": "模型比较未能依据来源给出唯一、可解释的选择；请查看所有候选、分歧和 evidence 引用。",
        "evidence": [],
        "represented": False,
        "comparison_disputed": True,
    }


def _choose_multi(
    database_url,
    *,
    job_id,
    worker,
    lease_seconds,
    model,
    plan,
    context,
    kind,
    generated,
    run_step,
    facts=None,
):
    """Compare a complete fixed candidate set and retain every result."""
    if not generated:
        raise PipelineFailure(f"{kind}_generate returned no model candidates")
    complete_generated = [
        record for record in generated if record.get("status") == "completed"
    ]
    if not complete_generated:
        raise PipelineFailure(
            f"{kind}_generate has no complete candidate; saved diagnostics are available"
        )
    candidate_set = [
        {
            "candidate_sha256": record["output_sha256"],
            "model": record.get("model"),
            "content": record.get("parsed"),
        }
        for record in complete_generated
    ]
    generation_issues = []
    if len(complete_generated) != len(generated):
        generation_issues.append({
            "id": "generation_incomplete",
            "type": "model_review_incomplete",
            "target": f"{kind}_generate",
            "message": "部分配置模型没有完成同一候选指纹的完整结果，不能自动通过。",
            "evidence": [record.get("output_sha256") for record in generated if record.get("output_sha256")],
            "represented": False,
        })
    if len(candidate_set) == 1:
        return complete_generated[0]["parsed"], [], generation_issues, complete_generated[0].get("model")
    data = {
        "context": context,
        "kind": kind,
        "candidates": candidate_set,
        "candidate_set_sha256": contract.sha256_json(candidate_set),
    }
    if facts is not None:
        data["facts"] = facts
    comparison_step = f"{kind}_compare"
    comparisons = run_step(comparison_step, data, 0)
    completed = [record for record in comparisons if record.get("status") == "completed"]
    selections = {
        record.get("parsed", {}).get("selected_sha256")
        for record in completed
        if isinstance(record.get("parsed"), dict)
    }
    valid = selections <= {item["candidate_sha256"] for item in candidate_set} and len(selections) == 1
    disputed = any(
        item.get("status") != "completed"
        or any(
            difference.get("assessment") == "disputed"
            for difference in (item.get("parsed") or {}).get("differences", [])
            if isinstance(difference, dict)
        )
        or bool((item.get("parsed") or {}).get("disagreements"))
        for item in comparisons
    )
    selected_sha = next(iter(selections)) if valid else candidate_set[0]["candidate_sha256"]
    selected = next(item for item in complete_generated if item["output_sha256"] == selected_sha)
    issues = generation_issues
    if not valid or disputed:
        issues.append(_multi_compare_issue(kind, comparisons, selections=selections))
    return selected["parsed"], comparisons, issues, selected.get("model")


def _execute_multi(
    database_url,
    *,
    job_id,
    worker,
    revision_source,
    model,
    lease_seconds,
    scope=None,
):
    """Run the facts → accepted facts → prose graph through the shared runner."""
    import step_runner

    with psycopg.connect(database_url) as conn:
        facts_row = store.read_candidate(conn, job_id, "facts")
        if facts_row is None:
            descriptors = store.source_descriptors(conn, **(scope or {}))
            context = store.build_context(descriptors, revision_source)
        else:
            context = facts_row["context"]
        config = model.public_config() if callable(getattr(model, "public_config", None)) else {
            "version": contract.VERSION,
            "steps": {step: list(_step_slots(model, step)) for step in contract.NARRATIVE_STEPS},
        }
        plan = store.freeze_pipeline(conn, job_id=job_id, worker=worker, context=context, config=config)

    definitions = {
        step: step_runner.StepDefinition(step, dependencies=(), retryable=True)
        for step in contract.NARRATIVE_STEPS
    }
    max_parallel = int(getattr(model, "max_parallel", 2))
    max_attempts = int(getattr(model, "max_step_attempts", 3))
    max_response_chars = int(getattr(model, "max_response_bytes", contract.MAX_BYTES))
    max_prompt_chars = contract.MAX_PROMPT_CHARS

    def heartbeat():
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            control_plane.heartbeat_job_strict(
                conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds
            )

    def build_prompt(step, data):
        if step in ("facts_generate", "prose_generate"):
            return contract.build_step_prompt(step, data, max_chars=max_prompt_chars)
        return contract.build_compare_prompt(step, data, max_chars=max_prompt_chars)

    def parse(step, raw):
        return contract.parse_step(step, raw, context)

    def semantic_errors(step, parsed, data):
        if not isinstance(parsed, dict):
            return ["narrative model returned no JSON object"]
        try:
            if step == "facts_generate":
                contract.validate_facts(parsed, context)
            elif step == "prose_generate":
                if "navigation" not in parsed:
                    raise PersistenceError("prose_generate must return navigation with the complete prose")
                contract.validate_prose(parsed, context, data["facts"])
            else:
                contract.validate_comparison(parsed, context, data["kind"], data["candidates"])
        except PersistenceError as exc:
            return [str(exc)]
        return []

    def begin_attempt(**values):
        with psycopg.connect(database_url) as conn:
            return store.begin_step_attempt(
                conn, job_id=job_id, worker=worker, plan=plan, **values
            )

    def finish_attempt(**values):
        with psycopg.connect(database_url) as conn:
            return store.finish_step_attempt(
                conn, job_id=job_id, worker=worker, **values
            )

    def retry_prompt(prompt, previous):
        return contract.retry_prompt(prompt, previous, max_chars=max_prompt_chars)

    def run_step(step, data, round):
        heartbeat()
        runner = step_runner.StepRunner(
            definitions=definitions,
            model_slots=lambda name: _step_slots(model, name),
            model_for=lambda name, slot: model.model_for(_configured_step(model, name), slot),
            model_config=lambda name, slot: _step_config(model, name, slot),
            build_prompt=build_prompt,
            parse=parse,
            semantic_errors=semantic_errors,
            begin_attempt=begin_attempt,
            finish_attempt=finish_attempt,
            retry_prompt=retry_prompt,
            heartbeat=heartbeat,
            max_parallel=max_parallel,
            max_attempts=max_attempts,
            max_response_chars=max_response_chars,
            wait_timeout_seconds=max(0.1, min(15, lease_seconds / 3)),
            preparation_exceptions=(
                store.StepBudgetExhausted,
                contract.PromptLimitExceeded,
            ),
            event_prefix="narrative_step",
        )
        try:
            return runner.execute([step_runner.StepSpec(step=step, data=data, round=round)])[
                step
            ]
        except step_runner.StepRunnerFailure as exc:
            raise PipelineFailure(str(exc)) from exc

    with psycopg.connect(database_url) as conn:
        facts_row = store.read_candidate(conn, job_id, "facts")
    if facts_row is None:
        generated = run_step("facts_generate", {"context": context}, 0)
        facts, comparisons, issues, selected_model = _choose_multi(
            database_url,
            job_id=job_id,
            worker=worker,
            lease_seconds=lease_seconds,
            model=model,
            plan=plan,
            context=context,
            kind="facts",
            generated=generated,
            run_step=run_step,
        )
        with psycopg.connect(database_url) as conn:
            facts_row = store.save_candidate(
                conn,
                job_id=job_id,
                worker=worker,
                kind="facts",
                context=context,
                candidate=facts,
                model=selected_model or "multi-model",
                plan=plan,
                candidate_records=generated,
                comparison_records=comparisons,
                issues=issues,
            )
    if facts_row["status"] == "open":
        return "needs_review"
    approved_facts = store.approved_content(facts_row)

    with psycopg.connect(database_url) as conn:
        prose_row = store.read_candidate(conn, job_id, "prose")
    if prose_row is None or prose_row.get("upstream_candidate_sha") != facts_row["candidate_sha"]:
        generated = run_step(
            "prose_generate",
            {"context": context, "facts": approved_facts},
            0,
        )
        prose, comparisons, issues, selected_model = _choose_multi(
            database_url,
            job_id=job_id,
            worker=worker,
            lease_seconds=lease_seconds,
            model=model,
            plan=plan,
            context=context,
            kind="prose",
            generated=generated,
            run_step=run_step,
            facts=approved_facts,
        )
        with psycopg.connect(database_url) as conn:
            prose_row = store.save_candidate(
                conn,
                job_id=job_id,
                worker=worker,
                kind="prose",
                context=context,
                candidate=prose,
                model=selected_model or "multi-model",
                plan=plan,
                candidate_records=generated,
                comparison_records=comparisons,
                issues=issues,
                upstream_candidate_sha=facts_row["candidate_sha"],
            )
    if prose_row["status"] == "open":
        return "needs_review"
    store.approved_content(prose_row)
    _publish(
        database_url,
        job_id=job_id,
        worker=worker,
        lease_seconds=lease_seconds,
        context=context,
    )
    return "ok"


def execute(database_url, *, job_id, worker, revision_source, model, lease_seconds, scope=None):
    if not _supports_step_graph(model) and not callable(getattr(model, "complete", None)):
        raise PersistenceError("historical narrative provider requires complete(prompt) and a model name")
    if _supports_step_graph(model):
        return _execute_multi(
            database_url,
            job_id=job_id,
            worker=worker,
            revision_source=revision_source,
            model=model,
            lease_seconds=lease_seconds,
            scope=scope,
        )
    return _execute_legacy(
        database_url,
        job_id=job_id,
        worker=worker,
        revision_source=revision_source,
        model=model,
        lease_seconds=lease_seconds,
        scope=scope,
    )
