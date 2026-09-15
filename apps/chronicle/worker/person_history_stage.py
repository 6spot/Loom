"""T04--T06 execution adapter for the independent person-history product.

The shared :mod:`step_runner` owns leases, bounded model execution, retries
and durable attempts.  This adapter supplies the person-history prompts and
semantic boundary, then hands accepted summary/prose to the separate
person-history publication store.
"""
from __future__ import annotations

import psycopg

import control_plane
import narrative_store
import person_history_contract as contract
import person_history_store as store
import step_runner
from common import PersistenceConflict, PersistenceError


def model_from_env(env=None):
    """Use the existing credential-free narrative provider configuration."""
    from narrative_stage import model_from_env as load_narrative_model

    return load_narrative_model(env)


_STEP_ALIASES = {
    "summary_generate": ("summary_generate", "facts_generate", "facts"),
    "summary_compare": ("summary_compare", "facts_compare", "facts_review", "facts_compare/review"),
    "prose_generate": ("prose_generate", "prose"),
    "prose_compare": ("prose_compare", "prose_review", "prose_compare/review"),
}


def _configured_step(model, step: str) -> str:
    for name in _STEP_ALIASES[step]:
        if name in getattr(model, "steps", {}):
            return name
    # A legacy wrapper uses the person-history name directly.
    return step


def _step_slots(model, step: str) -> tuple[str, ...]:
    steps = getattr(model, "steps", {})
    for name in _STEP_ALIASES[step]:
        slots = steps.get(name)
        if slots is not None:
            values = tuple(slots)
            if not values or len(values) != len(set(values)):
                raise PersistenceError(f"person-history step {step} has no distinct model slots")
            return values
    raise PersistenceError(f"person-history model configuration has no {step} slots")


def _step_config(model, step: str, slot: str) -> dict:
    configured = _configured_step(model, step)
    if callable(getattr(model, "model_config", None)):
        value = model.model_config(configured, slot)
    elif callable(getattr(model, "config_for", None)):
        value = model.config_for(configured, slot)
    else:
        provider = _model_for(model, step, slot)
        value = {"model": getattr(provider, "name", slot)}
    if not isinstance(value, dict):
        raise PersistenceError("person-history model configuration must be an object")
    value = dict(value)
    value["product"] = "person_history"
    value["schema_sha256"] = contract.sha256_json(contract.step_schema(step))
    return value


def _model_for(model, step: str, slot: str):
    configured = _configured_step(model, step)
    return model.model_for(configured, slot)


def _step_config_snapshot(model) -> dict:
    raw = model.public_config() if callable(getattr(model, "public_config", None)) else {}
    if not isinstance(raw, dict):
        raw = {}
    profiles = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    if not profiles:
        profiles = {
            slot: {"model": getattr(_model_for(model, step, slot), "name", slot)}
            for step in contract.PERSON_HISTORY_STEPS
            for slot in _step_slots(model, step)
        }
    return {
        "adapter": "person_history",
        "version": contract.VERSION,
        "candidate_version": contract.VERSION,
        "models": profiles,
        "steps": {
            step: list(_step_slots(model, step))
            for step in contract.PERSON_HISTORY_STEPS
        },
        "step_definitions": {
            step: {"dependencies": [], "retryable": True}
            for step in contract.PERSON_HISTORY_STEPS
        },
        "schemas": {
            step: contract.sha256_json(contract.step_schema(step))
            for step in contract.PERSON_HISTORY_STEPS
        },
        "max_parallel": int(getattr(model, "max_parallel", 2)),
        "max_step_attempts": int(getattr(model, "max_step_attempts", 3)),
    }


def _legacy_model(model):
    """Expose one complete provider in every graph slot for old deployments."""
    if not callable(getattr(model, "complete", None)) or not getattr(model, "name", None):
        return model

    class Legacy:
        name = model.name
        steps = {step: ("legacy",) for step in contract.PERSON_HISTORY_STEPS}
        max_parallel = 1
        max_step_attempts = 3
        max_response_bytes = contract.MAX_BYTES

        @staticmethod
        def model_for(_step, _slot):
            return model

        @staticmethod
        def model_config(_step, _slot):
            return {"model": model.name, "product": "person_history"}

        @staticmethod
        def public_config():
            return {
                "models": {"legacy": {"model": model.name}},
                "max_parallel": 1,
                "max_step_attempts": 3,
            }

    return Legacy()


def _comparison_issue(kind: str, comparisons: list[dict], selections: set[str]) -> dict:
    refs = [record.get("output_sha256") for record in comparisons if record.get("output_sha256")]
    return {
        "id": "comparison_" + contract.sha256_json([kind, refs, sorted(selections)])[:24],
        "type": "source_uncertainty",
        "target": f"{kind}_compare",
        "message": "模型比较未能依据来源给出唯一、可解释的选择；请查看所有候选、分歧和 evidence 引用。",
        "evidence": [],
        "represented": False,
        "comparison_disputed": True,
    }


def _choose_multi(
    *, kind: str, generated: list[dict], run_step, context: dict, facts: dict | None = None
) -> tuple[dict, list[dict], list[dict], str | None]:
    if not generated:
        raise PersistenceError(f"{kind}_generate returned no model candidates")
    complete = [item for item in generated if item.get("status") == "completed" and isinstance(item.get("parsed"), dict)]
    if not complete:
        raise PersistenceError(f"{kind}_generate has no complete candidate; durable diagnostics require review")
    candidate_set = [
        {"candidate_sha256": item["output_sha256"], "model": item.get("model"), "content": item["parsed"]}
        for item in complete
    ]
    issues = []
    if len(complete) != len(generated):
        issues.append({
            "id": "generation_incomplete",
            "type": "model_review_incomplete",
            "target": f"{kind}_generate",
            "message": "部分配置模型没有完成同一候选指纹的完整结果，不能自动通过。",
            "evidence": [item.get("output_sha256") for item in generated if item.get("output_sha256")],
            "represented": False,
        })
    if len(candidate_set) == 1:
        return complete[0]["parsed"], [], issues, complete[0].get("model")
    data = {
        "context": context,
        "product": kind,
        "candidates": candidate_set,
        "candidate_set_sha256": contract.sha256_json(candidate_set),
    }
    if facts is not None:
        data["summary"] = facts
    comparisons = run_step(f"{kind}_compare", data, 0)
    completed = [item for item in comparisons if item.get("status") == "completed" and isinstance(item.get("parsed"), dict)]
    selections = {
        item["parsed"].get("selected_sha256")
        for item in completed
        if isinstance(item.get("parsed"), dict)
    }
    valid = selections <= {item["candidate_sha256"] for item in candidate_set} and len(selections) == 1
    disputed = any(
        item.get("status") != "completed"
        or bool((item.get("parsed") or {}).get("disagreements"))
        or any(
            isinstance(difference, dict) and difference.get("assessment") == "disputed"
            for difference in (item.get("parsed") or {}).get("differences", [])
        )
        for item in comparisons
    )
    selected_sha = next(iter(selections)) if valid else candidate_set[0]["candidate_sha256"]
    selected = next(item for item in complete if item["output_sha256"] == selected_sha)
    if not valid or disputed:
        issues.append(_comparison_issue(kind, comparisons, selections))
    return selected["parsed"], comparisons, issues, selected.get("model")


class PipelineFailure(PersistenceError):
    """A person-history graph cannot produce a complete acceptance frontier."""


def execute(
    database_url,
    *,
    job_id,
    worker: str,
    revision_source,
    model,
    lease_seconds: int,
    scope: dict,
    on_event=None,
):
    if not isinstance(scope, dict) or not scope.get("person_id"):
        raise PersistenceError("person-history execution requires a fixed person/source scope")
    if not isinstance(getattr(model, "steps", None), dict):
        model = _legacy_model(model)
    if not callable(getattr(model, "model_for", None)):
        raise PersistenceError("person-history provider has no model_for entry")

    with psycopg.connect(database_url) as conn:
        summary_row = store.read_candidate(conn, job_id, "summary")
        if summary_row is None:
            descriptors = narrative_store.source_descriptors(
                conn,
                catalog_sha=scope["catalog_sha"],
                publication_ids=scope["publication_ids"],
            )
            context = store.build_context(
                conn,
                descriptors=descriptors,
                revision_source=revision_source,
                person_id=scope["person_id"],
            )
        else:
            context = summary_row["context"]
        plan = store.freeze_pipeline(
            conn,
            job_id=job_id,
            worker=worker,
            context=context,
            config=_step_config_snapshot(model),
        )

    definitions = {
        step: step_runner.StepDefinition(step, dependencies=(), retryable=True)
        for step in contract.PERSON_HISTORY_STEPS
    }
    max_parallel = int(getattr(model, "max_parallel", 2))
    max_attempts = int(getattr(model, "max_step_attempts", 3))
    max_response_chars = int(getattr(model, "max_response_bytes", contract.MAX_BYTES))

    def heartbeat():
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            control_plane.heartbeat_job_strict(
                conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds
            )

    def build_prompt(step, data):
        if step.endswith("_generate"):
            return contract.build_step_prompt(step, data)
        return contract.build_compare_prompt(step, data)

    def parse(step, raw):
        return contract.parse_step(step, raw, context)

    def semantic_errors(step, parsed, data):
        if not isinstance(parsed, dict):
            return ["person-history model returned no JSON object"]
        try:
            if step == "summary_generate":
                contract.validate_summary(parsed, context)
            elif step == "prose_generate":
                contract.validate_prose(parsed, context, data["summary"])
            else:
                contract.validate_comparison(
                    parsed,
                    context,
                    "summary" if step == "summary_compare" else "prose",
                    data["candidates"],
                )
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

    def run_step(step: str, data: dict, round_no: int):
        heartbeat()
        runner = step_runner.StepRunner(
            definitions=definitions,
            model_slots=lambda name: _step_slots(model, name),
            model_for=lambda name, slot: _model_for(model, name, slot),
            model_config=lambda name, slot: _step_config(model, name, slot),
            build_prompt=build_prompt,
            parse=parse,
            semantic_errors=semantic_errors,
            begin_attempt=begin_attempt,
            finish_attempt=finish_attempt,
            retry_prompt=lambda prompt, previous: contract.retry_prompt(prompt, previous),
            heartbeat=heartbeat,
            max_parallel=max_parallel,
            max_attempts=max_attempts,
            max_response_chars=max_response_chars,
            wait_timeout_seconds=max(0.1, min(15, lease_seconds / 3)),
            preparation_exceptions=(store.StepBudgetExhausted, contract.PromptLimitExceeded),
            on_event=on_event,
            event_prefix="person_history_step",
        )
        try:
            return runner.execute([step_runner.StepSpec(step=step, data=data, round=round_no)])[step]
        except step_runner.StepRunnerFailure as exc:
            raise PipelineFailure(str(exc)) from exc

    with psycopg.connect(database_url) as conn:
        summary_row = store.read_candidate(conn, job_id, "summary")
    if summary_row is None:
        generated = run_step("summary_generate", {"context": context}, 0)
        summary, comparisons, issues, selected_model = _choose_multi(
            kind="summary", generated=generated, run_step=run_step, context=context
        )
        with psycopg.connect(database_url) as conn:
            summary_row = store.save_candidate(
                conn,
                job_id=job_id,
                worker=worker,
                kind="summary",
                context=context,
                candidate=summary,
                model=selected_model or "multi-model",
                plan=plan,
                candidate_records=generated,
                comparison_records=comparisons,
                issues=issues,
            )
    if summary_row["status"] == "open":
        return "needs_review"
    approved_summary = store.approved_content(summary_row)

    with psycopg.connect(database_url) as conn:
        prose_row = store.read_candidate(conn, job_id, "prose")
    if prose_row is None or prose_row.get("upstream_candidate_sha") != summary_row["candidate_sha"]:
        generated = run_step(
            "prose_generate",
            {"context": context, "summary": approved_summary},
            0,
        )
        prose, comparisons, issues, selected_model = _choose_multi(
            kind="prose",
            generated=generated,
            run_step=run_step,
            context=context,
            facts=approved_summary,
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
                upstream_candidate_sha=summary_row["candidate_sha"],
            )
    if prose_row["status"] == "open":
        return "needs_review"
    store.approved_content(prose_row)

    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            publication = store.publish(conn, job_id=job_id, worker=worker)
            control_plane.write_stage_checkpoint_fenced(
                conn,
                job_id=job_id,
                stage="present",
                worker=worker,
                checkpoint={
                    "person_history_version": publication["publication_version"],
                    "person_id": context["target"]["person_id"],
                    "catalog_sha": context["source_selection"]["catalog_sha"],
                    "reviewed": True,
                },
            )
            control_plane.advance_stage_fenced(
                conn, job_id=job_id, stage="present", status="completed", worker=worker
            )
    return "ok"


__all__ = ["PipelineFailure", "execute", "model_from_env"]
