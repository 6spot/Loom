"""Persistence authority for independently produced person histories.

The store deliberately reuses the ordinary Chronicle ingestion job, leases,
ReviewItems and ``ingestion_outputs`` from T04.  Only the product frontier is
new: summary/prose candidates, acceptance receipts, immutable publications and
the explicit main-history mapping index live in these tables.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

import canonical_store
import control_plane
import person_history_acceptance as acceptance
import person_history_contract as contract
import narrative_store
from common import PersistenceConflict, PersistenceError, sha256_json
from step_runner import StepInput

REQUEST_TYPE = "studio-production-request"
PLAN_TYPE = "person-history-plan"
STEP_ATTEMPT_TYPE = "person-history-step-attempt"
STEP_TYPE = "person-history-step"
PRODUCT_SCOPE = "person_history"
KINDS = ("summary", "prose")
VERSION = contract.VERSION


class StepBudgetExhausted(PersistenceError):
    """A person-history model node used its frozen finite attempt budget."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid(value: Any, name: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PersistenceError(f"{name} must be a UUID") from exc


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise PersistenceError(f"{name} must be a lowercase SHA-256")
    return value


def _kind(kind: Any) -> str:
    if kind not in KINDS:
        raise PersistenceError("person-history candidate kind must be summary or prose")
    return kind


def _require_reviewed_ids(value: Any, expected: set[str], label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
        or set(value) != expected
    ):
        raise PersistenceError(
            f"{label} approval must explicitly review every conclusion exactly once"
        )
    return list(value)


def _job_revision(conn, job_id: Any) -> uuid.UUID:
    row = conn.execute(
        "SELECT revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s", (job_id,)
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown person-history job {job_id}")
    return row[0]


def _read_request(conn, job_id: Any) -> dict[str, Any] | None:
    rows = conn.execute(
        "SELECT artifact_sha256, payload FROM chronicle.ingestion_outputs "
        "WHERE job_id = %s AND artifact_type = %s",
        (job_id, REQUEST_TYPE),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or not isinstance(rows[0][1], dict) or sha256_json(rows[0][1]) != rows[0][0]:
        raise PersistenceConflict("person-history production request changed")
    return rows[0][1]


def _scope_from_parent(checkpoint: Any) -> dict[str, Any] | None:
    if not isinstance(checkpoint, dict):
        return None
    scope = checkpoint.get("person_history_scope")
    return scope if isinstance(scope, dict) else None


def _require_person_in_descriptors(descriptors: dict[str, Any], person_id: str) -> dict[str, Any]:
    entity = descriptors.get("entities", {}).get(person_id)
    if not isinstance(entity, dict) or entity.get("kind") != "person":
        raise PersistenceError(
            "person_id must be a published canonical person present in the selected complete sources"
        )
    return entity


def validate_source_scope(conn, *, person_id: Any, catalog_sha: Any, publication_ids: Any) -> dict[str, Any]:
    """Validate the frozen catalog/publication/person selection read-only."""
    person_id = str(_uuid(person_id, "person_id"))
    selection = narrative_store.validate_source_scope(
        conn, catalog_sha=catalog_sha, publication_ids=publication_ids
    )
    descriptors = narrative_store.source_descriptors(
        conn,
        catalog_sha=selection["catalog_sha"],
        publication_ids=selection["publication_ids"],
    )
    _require_person_in_descriptors(descriptors, person_id)
    return {
        "person_id": person_id,
        "catalog_sha": selection["catalog_sha"],
        "publication_ids": selection["publication_ids"],
    }


def list_person_choices(
    conn, *, catalog_sha: Any = None, publication_ids: Any = None,
    limit: int = 50, offset: int = 0,
) -> dict[str, Any]:
    """List canonical people available for an explicit Studio selection."""
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise PersistenceError("person selection requires limit 1–100 and nonnegative offset")
    descriptors = narrative_store.source_descriptors(
        conn, catalog_sha=catalog_sha, publication_ids=publication_ids
    )
    rows = []
    selected = {value for source in descriptors["sources"] for value in source["canonical_refs"]["entities"].values()}
    for person_id, entity in descriptors.get("entities", {}).items():
        if person_id not in selected or not isinstance(entity, dict) or entity.get("kind") != "person":
            continue
        source_count = sum(
            person_id in source.get("canonical_refs", {}).get("entities", {}).values()
            for source in descriptors["sources"]
        )
        rows.append({
            "person_id": person_id,
            "name": entity.get("name") or person_id,
            "source_count": source_count,
            "catalog_sha": descriptors["catalog_sha"],
        })
    rows.sort(key=lambda item: (item["name"], item["person_id"]))
    total = len(rows)
    page = rows[offset: offset + limit]
    return {
        "schema": "chronicle.person-history-people",
        "version": VERSION,
        "catalog_sha": descriptors["catalog_sha"],
        "items": page,
        "has_more": offset + len(page) < total,
        "offset": offset,
        "total": total,
    }


def queue_person_history(
    conn, *, person_id: Any, catalog_sha: Any, publication_ids: Any,
    model_selection: dict[str, Any] | None = None,
    parent_job_id: uuid.UUID | None = None,
    max_attempts: int = 5,
) -> uuid.UUID:
    """Queue an explicit person/source selection on the shared job graph."""
    import resolve_publish

    if not isinstance(model_selection, dict) and model_selection is not None:
        raise PersistenceError("person-history model selection must be an object")
    if type(max_attempts) is not int or max_attempts < 1:
        raise PersistenceError("max_attempts must be a positive integer")
    person_id = str(_uuid(person_id, "person_id"))
    with conn.transaction():
        resolve_publish.acquire_publish_lock(conn)
        parent = None
        if parent_job_id is not None:
            parent = conn.execute(
                "SELECT revision_id, status, checkpoint FROM chronicle.ingestion_jobs "
                "WHERE job_id = %s FOR UPDATE",
                (parent_job_id,),
            ).fetchone()
            if parent is None:
                raise PersistenceError("unknown parent job")
            if parent[1] not in ("failed", "cancelled"):
                raise PersistenceConflict("only a failed or cancelled task can start a linked rerun")
            parent_scope = _scope_from_parent(parent[2])
            if parent_scope is None:
                raise PersistenceConflict("parent is not a person-history task")
        selection = narrative_store.validate_source_scope(
            conn, catalog_sha=catalog_sha, publication_ids=publication_ids
        )
        normalized_publications = selection["publication_ids"]
        descriptors = narrative_store.source_descriptors(
            conn,
            catalog_sha=selection["catalog_sha"],
            publication_ids=normalized_publications,
        )
        _require_person_in_descriptors(descriptors, person_id)
        scope = {
            "person_id": person_id,
            "catalog_sha": selection["catalog_sha"],
            "publication_ids": normalized_publications,
        }
        if parent is not None:
            parent_scope = parent[2].get("person_history_scope") if isinstance(parent[2], dict) else None
            if parent_scope != scope:
                raise PersistenceConflict("person-history person/source selection changed; choose again")
            if parent[0] != uuid.UUID(descriptors["sources"][0]["revision_id"]):
                raise PersistenceConflict("person-history parent and source revision do not match")
        job_id = control_plane.queue_job(
            conn,
            revision_id=uuid.UUID(descriptors["sources"][0]["revision_id"]),
            max_attempts=max_attempts,
        )
        for stage in control_plane.STAGE_NAMES:
            if stage != "present":
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="skipped")
        conn.execute(
            "UPDATE chronicle.ingestion_jobs SET checkpoint = %s WHERE job_id = %s",
            (Jsonb({"person_history_scope": scope}), job_id),
        )
        if model_selection is not None or parent_job_id is not None:
            request = {
                "version": VERSION,
                "model_selection": copy.deepcopy(model_selection),
                "parent_job_id": str(parent_job_id) if parent_job_id is not None else None,
            }
            control_plane.record_output(
                conn,
                job_id=job_id,
                revision_id=uuid.UUID(descriptors["sources"][0]["revision_id"]),
                artifact_type=REQUEST_TYPE,
                artifact_sha256=sha256_json(request),
                payload=request,
            )
        return job_id


def job_scope(conn, job_id: Any) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT checkpoint->'person_history_scope' FROM chronicle.ingestion_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    return row[0] if row and isinstance(row[0], dict) else None


def _approved_source_conclusions(context: dict[str, Any], person_id: str) -> list[dict[str, Any]]:
    """Flatten accepted person-state facts and accepted source claims.

    The generated product can cite only these records.  They retain the
    original fact/claim refs and publication binding; no conclusion is made
    merely because a person name appears in a chapter.
    """
    result: list[dict[str, Any]] = []
    for source in context.get("sources", []):
        local_person_refs = {
            local for local, canonical in source.get("canonical_refs", {}).get("entities", {}).items()
            if canonical == person_id
        }
        for state in source.get("reviewed_person_states", []):
            if not isinstance(state, dict) or str(state.get("person_id")) != person_id:
                continue
            source_facts = state.get("source_facts") or []
            if not source_facts:
                # A state row without its source fact is not an approved
                # conclusion and must not become biography material.
                continue
            for fact in source_facts:
                if not isinstance(fact, dict):
                    continue
                fact_ref = fact.get("fact_ref")
                if not isinstance(fact_ref, str) or not fact_ref:
                    continue
                result.append({
                    "id": "ac_" + sha256_json([source["source_id"], fact_ref])[:24],
                    "source_id": source["source_id"],
                    "source_publication_id": source["publication_id"],
                    "person_id": person_id,
                    "dimension": state.get("dimension"),
                    "value": state.get("value"),
                    "text": state.get("value") or state.get("dimension") or "来源状态",
                    "certainty": state.get("certainty"),
                    "qualification": state.get("qualification"),
                    "phase_ids": list(state.get("phase_ids") or []),
                    "source_fact_refs": [fact_ref],
                    "claim_refs": list(fact.get("claim_refs") or []),
                })
        # Accepted chapter claims are also approved source conclusions for
        # actions.  Their exact source claim and evidence remain in `sources`.
        for claim in source.get("source_claims", []):
            if not isinstance(claim, dict):
                continue
            claim_id = claim.get("temp_id") or claim.get("id")
            subject = claim.get("subject") if isinstance(claim.get("subject"), dict) else {}
            object_ref = claim.get("object") if isinstance(claim.get("object"), dict) else {}
            if not (subject.get("ref") in local_person_refs or object_ref.get("ref") in local_person_refs):
                continue
            if not isinstance(claim_id, str) or not claim_id:
                continue
            evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
            result.append({
                "id": "ac_claim_" + sha256_json([source["source_id"], claim_id])[:20],
                "source_id": source["source_id"],
                "source_publication_id": source["publication_id"],
                "person_id": person_id,
                "dimension": "action",
                "value": None,
                "text": evidence.get("text") or claim.get("predicate") or "来源行动记载",
                "certainty": "clear",
                "qualification": "ordinary",
                "phase_ids": [],
                "source_fact_refs": [],
                "claim_refs": [claim_id],
            })
    # Same approved fact can appear in multiple reading units.  Preserve
    # source variants, but never duplicate byte-identical approved records.
    unique: dict[str, dict[str, Any]] = {}
    for item in result:
        unique.setdefault(item["id"], item)
    return [unique[key] for key in sorted(unique)]


def _main_history_positions(conn, *, person_id: str, catalog_sha: str) -> list[dict[str, Any]]:
    """Expose exact published main-history positions as selectable handles."""
    row = conn.execute(
        "SELECT version_sha, payload FROM chronicle.historical_narratives "
        "WHERE catalog_sha = %s ORDER BY publication_sequence DESC LIMIT 1",
        (catalog_sha,),
    ).fetchone()
    if row is None or not isinstance(row[1], dict):
        return []
    version_sha, publication = row
    result = []
    for paragraph in publication.get("paragraphs", []):
        if not isinstance(paragraph, dict):
            continue
        entities = paragraph.get("entities") or []
        if not any(isinstance(entity, dict) and entity.get("id") == person_id for entity in entities):
            continue
        segments = paragraph.get("segments") or []
        text = "".join(
            segment.get("text", "")
            for segment in segments
            if isinstance(segment, dict) and isinstance(segment.get("text"), str)
        )
        result.append({
            "id": "mh_" + sha256_json([version_sha, paragraph.get("id")])[:24],
            "version_sha": version_sha,
            "paragraph_id": paragraph.get("id"),
            "phase_id": paragraph.get("phase_id"),
            "person_id": person_id,
            "text": text,
        })
    return result


def build_context(conn, *, descriptors: dict[str, Any], revision_source, person_id: Any) -> dict[str, Any]:
    """Build a hashable, complete context through the existing source reader."""
    person_id = str(_uuid(person_id, "person_id"))
    _require_person_in_descriptors(descriptors, person_id)
    base = narrative_store.build_context(descriptors, revision_source)
    target = base["entities"][person_id]
    context = {
        "schema": contract.CONTEXT_SCHEMA,
        "version": contract.VERSION,
        "source_selection": {
            "catalog_sha": descriptors["catalog_sha"],
            "publication_ids": [source["publication_id"] for source in base["sources"]],
        },
        "target": {"person_id": person_id, "name": target.get("name"), "kind": "person"},
        "sources": base["sources"],
        "entities": base["entities"],
        "events": base["events"],
    }
    context["approved_conclusions"] = _approved_source_conclusions(context, person_id)
    if not context["approved_conclusions"]:
        raise PersistenceError("selected sources have no approved conclusions for the canonical person")
    context["main_history_positions"] = _main_history_positions(
        conn, person_id=person_id, catalog_sha=descriptors["catalog_sha"]
    )
    return context


def read_outputs(conn, *, job_id: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT artifact_type, artifact_sha256, payload FROM chronicle.ingestion_outputs "
        "WHERE job_id = %s AND artifact_type LIKE 'person-history-%%' "
        "ORDER BY created_at, output_id",
        (job_id,),
    ).fetchall()
    result = []
    for artifact_type, digest, payload in rows:
        if not isinstance(payload, dict) or sha256_json(payload) != digest:
            raise PersistenceConflict("person-history output hash drift")
        result.append({"artifact_type": artifact_type, "output_sha256": digest, **payload})
    return result


def freeze_pipeline(conn, *, job_id: Any, worker: str, context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    import resolve_publish

    if not isinstance(context, dict) or not isinstance(config, dict):
        raise PersistenceError("person-history pipeline requires JSON context and model configuration")
    value = {
        "schema": contract.PLAN_SCHEMA,
        "version": contract.VERSION,
        "context": copy.deepcopy(context),
        "context_sha256": sha256_json(context),
        "config": copy.deepcopy(config),
        "pipeline_fingerprint": sha256_json({"adapter": PRODUCT_SCOPE, "context": context, "config": config}),
        "status": "frozen",
        "created_at": _now(),
    }
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        plans = [item for item in read_outputs(conn, job_id=job_id) if item["artifact_type"] == PLAN_TYPE]
        if plans:
            if len(plans) != 1 or any(
                plans[0].get(key) != value.get(key)
                for key in ("context", "context_sha256", "config", "pipeline_fingerprint")
            ):
                raise PersistenceConflict("person-history pipeline source/prompt/model configuration drifted")
            return plans[0]
        revision_id = _job_revision(conn, job_id)
        digest = sha256_json(value)
        control_plane.record_output_fenced(
            conn,
            job_id=job_id,
            revision_id=revision_id,
            worker=worker,
            artifact_type=PLAN_TYPE,
            artifact_sha256=digest,
            payload=value,
        )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return {"artifact_type": PLAN_TYPE, "output_sha256": digest, **value}


def node_key(plan: dict[str, Any], *, step: str, round: int, slot: str, data: dict[str, Any], prompt: str, model_config: dict[str, Any]) -> str:
    return StepInput(
        pipeline_fingerprint=plan["pipeline_fingerprint"],
        step=step,
        round=round,
        slot=slot,
        data=data,
        prompt=prompt,
        model_config=model_config,
    ).fingerprint()


def begin_step_attempt(
    conn, *, job_id: Any, worker: str, plan: dict[str, Any], step: str, round: int,
    slot: str, data: dict[str, Any], prompt: str, model_config: dict[str, Any],
    max_attempts: int, retryable: bool = True, retry_prompt=None,
) -> tuple[dict[str, Any], bool]:
    import resolve_publish

    if type(max_attempts) is not int or max_attempts < 1:
        raise PersistenceError("person-history step max_attempts must be positive")
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        key = node_key(
            plan, step=step, round=round, slot=slot, data=data,
            prompt=prompt, model_config=model_config,
        )
        records = read_outputs(conn, job_id=job_id)
        results = [item for item in records if item["artifact_type"] == STEP_TYPE and item.get("node_key") == key]
        completed = [item for item in results if item.get("status") == "completed"]
        if completed:
            if len(completed) != 1:
                raise PersistenceConflict("one person-history model node has multiple completed results")
            return completed[0], True
        invalid = [item for item in results if item.get("status") == "invalid"]
        previous = max(invalid, key=lambda item: item.get("attempt", 0)) if invalid else None
        starts = [
            item for item in records
            if item["artifact_type"] == STEP_ATTEMPT_TYPE and item.get("node_key") == key
        ]
        if previous is not None and not retryable:
            return previous, True
        if len(starts) >= max_attempts:
            raise StepBudgetExhausted(f"{step}/{slot}: {max_attempts} saved attempts exhausted")
        actual_prompt = prompt
        if previous is not None:
            if retry_prompt is None:
                raise PersistenceError(f"{step}/{slot}: retry prompt adapter is required")
            actual_prompt = retry_prompt(prompt, previous)
        attempt = len(starts) + 1
        value = {
            "schema": "chronicle.person-history-step-attempt",
            "version": contract.VERSION,
            "pipeline_fingerprint": plan["pipeline_fingerprint"],
            "context_sha256": plan["context_sha256"],
            "node_key": key,
            "step": step,
            "round": round,
            "slot": slot,
            "attempt": attempt,
            "input_sha256": sha256_json(data),
            "model": model_config.get("model"),
            "model_config": copy.deepcopy(model_config),
            "prompt": actual_prompt,
            "base_prompt_sha256": sha256_json(prompt),
            "input": copy.deepcopy(data),
            "retry_of": previous["output_sha256"] if previous is not None else None,
            "status": "started",
            "started_at": _now(),
        }
        digest = sha256_json(value)
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=_job_revision(conn, job_id), worker=worker,
            artifact_type=STEP_ATTEMPT_TYPE, artifact_sha256=digest, payload=value,
        )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        return {"artifact_type": STEP_ATTEMPT_TYPE, "output_sha256": digest, **value}, False


def finish_step_attempt(
    conn, *, job_id: Any, worker: str, attempt: dict[str, Any], raw_text: str,
    parsed: Any, validation_errors: list[str], receipt: dict[str, Any], status: str, error: str | None = None,
) -> dict[str, Any]:
    import resolve_publish

    if status not in {"completed", "invalid", "failed"}:
        raise PersistenceError("person-history step result has an invalid status")
    errors = list(validation_errors or [])
    value = {
        "schema": "chronicle.person-history-step",
        "version": contract.VERSION,
        **{key: attempt[key] for key in (
            "pipeline_fingerprint", "context_sha256", "node_key", "step",
            "round", "slot", "attempt", "input_sha256", "model",
        )},
        "attempt_sha256": attempt["output_sha256"],
        "raw_text": raw_text if isinstance(raw_text, str) else "",
        "raw_response": raw_text if isinstance(raw_text, str) else "",
        "parsed": copy.deepcopy(parsed),
        "validation_errors": errors,
        "validation_error": "; ".join(str(item) for item in errors) if errors else error,
        "receipt": copy.deepcopy(receipt) if isinstance(receipt, dict) else {},
        "status": status,
        "error": error,
    }
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        records = read_outputs(conn, job_id=job_id)
        if any(item["artifact_type"] == STEP_TYPE and item.get("attempt_sha256") == attempt["output_sha256"] for item in records):
            raise PersistenceConflict("person-history attempt already has a saved result")
        if not any(item["artifact_type"] == STEP_ATTEMPT_TYPE and item["output_sha256"] == attempt["output_sha256"] for item in records):
            raise PersistenceConflict("person-history attempt has no durable start")
        digest = sha256_json(value)
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=_job_revision(conn, job_id), worker=worker,
            artifact_type=STEP_TYPE, artifact_sha256=digest, payload=value,
        )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return {"artifact_type": STEP_TYPE, "output_sha256": digest, **value}


def _frontier(conn, job_id: Any, kind: str):
    _kind(kind)
    return conn.execute(
        "SELECT candidate_sha, job_id, kind, review_id, parent_candidate_sha, revision_no, "
        "upstream_candidate_sha, context_sha, context_payload, candidate_payload, model_version "
        "FROM chronicle.person_history_candidates WHERE job_id = %s AND kind = %s "
        "ORDER BY revision_no DESC, candidate_sha DESC LIMIT 1",
        (job_id, kind),
    ).fetchone()


def _candidate_view(conn, row) -> dict[str, Any]:
    review_id = row[3]
    review = conn.execute(
        "SELECT status, payload FROM chronicle.review_items WHERE review_id = %s", (review_id,)
    ).fetchone() if review_id is not None else None
    acceptance_row = conn.execute(
        "SELECT acceptance_id, acceptance_type, payload FROM chronicle.person_history_acceptances "
        "WHERE job_id = %s AND kind = %s AND candidate_sha256 = %s",
        (row[1], row[2], row[0]),
    ).fetchone()
    review_payload = review[1] if review and isinstance(review[1], dict) else {}
    acceptance_payload = acceptance_row[2] if acceptance_row and isinstance(acceptance_row[2], dict) else None
    if acceptance_row is not None:
        status = "accepted"
    elif review is not None:
        status = review[0]
    else:
        status = "unaccepted"
    return {
        "candidate_sha": row[0],
        "job_id": str(row[1]),
        "kind": row[2],
        "review_id": str(review_id) if review_id is not None else None,
        "parent_candidate_sha": row[4],
        "revision_no": int(row[5]),
        "upstream_candidate_sha": row[6],
        "context_sha": row[7],
        "context": copy.deepcopy(row[8]),
        "candidate": copy.deepcopy(row[9]),
        "model_version": row[10],
        "status": status,
        "decision": review_payload.get("decision") if isinstance(review_payload.get("decision"), dict) else None,
        "review_payload": copy.deepcopy(review_payload),
        "acceptance_id": str(acceptance_row[0]) if acceptance_row else None,
        "acceptance_type": acceptance_row[1] if acceptance_row else None,
        "acceptance": copy.deepcopy(acceptance_payload),
    }


def read_candidate(conn, job_id: Any, kind: str) -> dict[str, Any] | None:
    row = _frontier(conn, job_id, kind)
    return _candidate_view(conn, row) if row else None


def _dismiss_review(conn, review_id: Any, *, superseded_by: str) -> None:
    if review_id is None:
        return
    conn.execute(
        "UPDATE chronicle.review_items SET status = 'dismissed', resolved_at = now(), "
        "payload = payload || %s WHERE review_id = %s AND status = 'open'",
        (Jsonb({"dismissal": "superseded", "superseded_by": superseded_by}), review_id),
    )


def approved_content(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        raise PersistenceConflict("person-history content has not been accepted")
    content = row["candidate"]
    receipt = row.get("acceptance")
    if row["status"] == "accepted":
        if not isinstance(receipt, dict):
            raise PersistenceConflict("person-history acceptance receipt is missing")
        acceptance.validate_receipt(receipt)
        if (
            receipt.get("input_sha256") != row["context_sha"]
            or receipt.get("candidate_sha256") != row["candidate_sha"]
            or receipt.get("draft_sha256") != sha256_json(content)
            or receipt.get("content_sha256") != sha256_json(content)
        ):
            raise PersistenceConflict("person-history acceptance is not bound to this candidate")
        if receipt.get("acceptance_type") == "policy_model_review":
            return copy.deepcopy(content)
        if receipt.get("acceptance_type") != "human":
            raise PersistenceConflict("person-history acceptance type is invalid")
        decision = row.get("decision")
        if not isinstance(decision, dict) or decision.get("decision") != "approve":
            raise PersistenceConflict("human person-history acceptance has no approval decision")
        if decision.get("content") != content or decision.get("content_sha") != sha256_json(content):
            raise PersistenceConflict("person-history human decision content hash mismatch")
        if receipt.get("review_id") != row.get("review_id"):
            raise PersistenceConflict("human person-history acceptance receipt is stale")
        return copy.deepcopy(content)
    decision = row.get("decision")
    if row["status"] != "resolved" or not isinstance(decision, dict) or decision.get("decision") != "approve":
        raise PersistenceConflict("person-history content has not been accepted")
    if decision.get("content") != content or decision.get("content_sha") != sha256_json(content):
        raise PersistenceConflict("person-history human decision content hash mismatch")
    if not isinstance(receipt, dict):
        raise PersistenceConflict("human person-history acceptance receipt is missing")
    acceptance.validate_receipt(receipt)
    if (
        receipt.get("acceptance_type") != "human"
        or receipt.get("input_sha256") != row["context_sha"]
        or receipt.get("candidate_sha256") != row["candidate_sha"]
        or receipt.get("draft_sha256") != sha256_json(content)
        or receipt.get("content_sha256") != sha256_json(content)
        or receipt.get("review_id") != row.get("review_id")
    ):
        raise PersistenceConflict("human person-history acceptance receipt is stale")
    return copy.deepcopy(content)


def _automatic_frontier(
    conn, *, job_id: Any, kind: str, context: dict[str, Any], candidate: dict[str, Any],
    plan: dict[str, Any] | None, candidate_records: list[dict[str, Any]],
    comparison_records: list[dict[str, Any]], issues: list[dict[str, Any]] | None,
) -> dict[str, list[str]] | None:
    """Return model receipts only when the complete durable frontier agrees.

    A review payload is not acceptance evidence by itself: callers can pass a
    forged or partial record list.  Re-read every referenced result from the
    append-only output store and bind it to the frozen plan, input, logical
    step, configured slot and parsed content before granting the policy receipt.
    """
    if not isinstance(plan, dict) or not candidate_records or list(issues or []):
        return None
    if plan.get("context_sha256") != sha256_json(context) or not plan.get("pipeline_fingerprint"):
        return None
    configured_steps = (plan.get("config") or {}).get("steps")
    if not isinstance(configured_steps, dict):
        return None

    def configured_slots(step: str):
        slots = configured_steps.get(step)
        return slots if isinstance(slots, list) and slots else None

    outputs = {
        (item["artifact_type"], item["output_sha256"]): item
        for item in read_outputs(conn, job_id=job_id)
        if item.get("artifact_type") and item.get("output_sha256")
    }
    generation_step = f"{kind}_generate"
    generation_slots = configured_slots(generation_step)
    complete = [
        item for item in candidate_records
        if item.get("status") == "completed" and isinstance(item.get("parsed"), dict)
    ]
    if (
        generation_slots is None
        or len(complete) != len(candidate_records)
        or len(candidate_records) != len(generation_slots)
        or {item.get("slot") for item in candidate_records} != set(generation_slots)
    ):
        return None
    model_outputs: list[str] = []
    for item in candidate_records:
        digest = item.get("output_sha256")
        result = outputs.get((STEP_TYPE, digest))
        if (
            not isinstance(digest, str)
            or result is None
            or result.get("status") != "completed"
            or result.get("step") != generation_step
            or result.get("pipeline_fingerprint") != plan["pipeline_fingerprint"]
            or result.get("context_sha256") != plan["context_sha256"]
            or result.get("parsed") != item.get("parsed")
        ):
            return None
        model_outputs.append(digest)
    selected = [item for item in candidate_records if item.get("parsed") == candidate]
    if len(selected) != 1:
        return None

    model_opinions: list[str] = []
    if len(candidate_records) > 1:
        comparison_step = f"{kind}_compare"
        comparison_slots = configured_slots(comparison_step)
        if (
            comparison_slots is None
            or len(comparison_records) != len(comparison_slots)
            or {item.get("slot") for item in comparison_records} != set(comparison_slots)
        ):
            return None
        candidate_set = {item.get("output_sha256") for item in candidate_records}
        if any(not isinstance(value, str) for value in candidate_set):
            return None
        if len(candidate_set) != len(candidate_records):
            return None
        selections: set[str] = set()
        for item in comparison_records:
            digest = item.get("output_sha256")
            result = outputs.get((STEP_TYPE, digest))
            if (
                item.get("status") != "completed"
                or not isinstance(digest, str)
                or result is None
                or result.get("status") != "completed"
                or result.get("step") != comparison_step
                or result.get("pipeline_fingerprint") != plan["pipeline_fingerprint"]
                or result.get("context_sha256") != plan["context_sha256"]
                or result.get("parsed") != item.get("parsed")
            ):
                return None
            parsed = item.get("parsed") if isinstance(item.get("parsed"), dict) else {}
            selected_sha = parsed.get("selected_sha256")
            if not isinstance(selected_sha, str) or selected_sha not in candidate_set:
                return None
            if parsed.get("disagreements") or any(
                isinstance(difference, dict) and difference.get("assessment") == "disputed"
                for difference in (parsed.get("differences") or [])
            ):
                return None
            selections.add(selected_sha)
            model_opinions.append(digest)
        if len(selections) != 1:
            return None
        selected_candidate = next(
            (item for item in candidate_records if item.get("output_sha256") == next(iter(selections))),
            None,
        )
        if selected_candidate is None or selected_candidate.get("parsed") != candidate:
            return None
    elif comparison_records:
        return None
    return {"model_output_sha256s": model_outputs, "model_opinion_sha256s": model_opinions}


def save_candidate(
    conn, *, job_id: Any, worker: str, kind: str, context: dict[str, Any], candidate: dict[str, Any],
    model: str, plan: dict[str, Any] | None = None, candidate_records: list[dict[str, Any]] | None = None,
    comparison_records: list[dict[str, Any]] | None = None, issues: list[dict[str, Any]] | None = None,
    upstream_candidate_sha: str | None = None,
) -> dict[str, Any]:
    import resolve_publish

    kind = _kind(kind)
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        existing = read_candidate(conn, job_id, kind)
        if existing and existing.get("upstream_candidate_sha") == upstream_candidate_sha:
            if existing["context"] != context or existing["candidate"] != candidate:
                raise PersistenceConflict("person-history candidate frontier already contains a different draft")
            return existing
        if kind == "summary":
            contract.validate_summary(candidate, context)
        else:
            summary_row = read_candidate(conn, job_id, "summary")
            if summary_row is None:
                raise PersistenceConflict("person-history prose cannot be saved before summary")
            summary = approved_content(summary_row)
            contract.validate_prose(candidate, context, summary)
            if summary_row["context"] != context:
                raise PersistenceConflict("person-history summary and prose use different frozen contexts")
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        parent_sha = existing["candidate_sha"] if existing else None
        revision_no = (int(existing.get("revision_no") or 0) + 1) if existing else 0
        digest_payload = {
            "job_id": str(job_id), "kind": kind, "context": context,
            "candidate": candidate, "upstream_candidate_sha": upstream_candidate_sha,
        }
        if existing:
            digest_payload.update({
                "parent_candidate_sha": parent_sha,
                "revision_no": revision_no,
            })
        digest = sha256_json(digest_payload)
        candidate_records = list(candidate_records or [])
        comparison_records = list(comparison_records or [])
        issues = list(issues or [])
        automatic = _automatic_frontier(
            conn,
            job_id=job_id,
            kind=kind,
            context=context,
            candidate=candidate,
            plan=plan,
            candidate_records=candidate_records,
            comparison_records=comparison_records,
            issues=issues,
        )
        review_payload = {
            "scope": PRODUCT_SCOPE,
            "stage": "present",
            "person_history_kind": kind,
            "candidate_sha": digest,
            "context_sha256": sha256_json(context),
            "plan_version": "person-history-review-v1",
            "pipeline_fingerprint": plan.get("pipeline_fingerprint") if isinstance(plan, dict) else None,
            "blocking": True,
            "allowed_decisions": ["approve", "reject", "revise"],
            "issues": copy.deepcopy(issues),
            "candidate_count": len(candidate_records),
            "upstream_candidate_sha": upstream_candidate_sha,
            "candidates": [
                {
                    "output_sha256": item.get("output_sha256"), "step": item.get("step"),
                    "slot": item.get("slot"), "model": item.get("model"),
                    "status": item.get("status"), "candidate": copy.deepcopy(item.get("parsed")),
                    "raw_text": item.get("raw_text"), "validation_errors": list(item.get("validation_errors") or []),
                }
                for item in candidate_records
            ],
            "comparisons": [
                {
                    "output_sha256": item.get("output_sha256"), "step": item.get("step"),
                    "slot": item.get("slot"), "model": item.get("model"),
                    "status": item.get("status"), "comparison": copy.deepcopy(item.get("parsed")),
                    "raw_text": item.get("raw_text"), "validation_errors": list(item.get("validation_errors") or []),
                }
                for item in comparison_records
            ],
            "step_output_sha256s": [item.get("output_sha256") for item in candidate_records + comparison_records if item.get("output_sha256")],
            "model_output_sha256s": [item.get("output_sha256") for item in candidate_records if item.get("output_sha256")],
            "model_opinion_sha256s": [item.get("output_sha256") for item in comparison_records if item.get("output_sha256")],
        }
        if existing:
            _dismiss_review(conn, existing.get("review_id"), superseded_by=digest)
        if kind == "summary":
            prose_row = read_candidate(conn, job_id, "prose")
            if prose_row and prose_row.get("upstream_candidate_sha") != digest:
                _dismiss_review(conn, prose_row.get("review_id"), superseded_by=digest)
        review_id = None
        if automatic is None:
            review_payload["acceptance_mode"] = "exception_review"
            review_payload["pending_issues"] = copy.deepcopy(issues)
            review_id = control_plane.open_review_item(
                conn, job_id=job_id, kind="stage_gate", payload=review_payload
            )
        else:
            review_payload["acceptance_mode"] = "policy_model_review"
        conn.execute(
            "INSERT INTO chronicle.person_history_candidates "
            "(candidate_sha, job_id, kind, review_id, parent_candidate_sha, revision_no, "
            "upstream_candidate_sha, context_sha, context_payload, candidate_payload, model_version) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                digest, job_id, kind, review_id, parent_sha, revision_no,
                upstream_candidate_sha, sha256_json(context), Jsonb(context), Jsonb(candidate), model,
            ),
        )
        if automatic is not None:
            if not isinstance(plan, dict):
                raise PersistenceError("automatic person-history acceptance requires a frozen plan")
            receipt = acceptance.build_receipt(
                job_id=job_id, kind=kind, acceptance_type="policy_model_review",
                input_sha256=sha256_json(context), candidate_sha256=digest, content=candidate,
                pipeline_fingerprint=plan["pipeline_fingerprint"],
                model_output_sha256s=automatic["model_output_sha256s"],
                model_opinion_sha256s=automatic["model_opinion_sha256s"],
                decision_reason="结构、来源引用、人物身份边界和模型比较均通过；无未解决异议。",
                reviewed_conclusion_ids=(
                    [item["id"] for item in candidate.get("conclusions", [])]
                    if kind == "summary" else sorted({
                        conclusion_id
                        for paragraph in candidate.get("paragraphs", [])
                        for segment in paragraph.get("segments", [])
                        for conclusion_id in segment.get("conclusion_ids", [])
                    })
                ),
            )
            acceptance.validate_receipt(receipt)
            conn.execute(
                "INSERT INTO chronicle.person_history_acceptances "
                "(acceptance_id,job_id,kind,acceptance_type,policy_version,input_sha256,candidate_sha256,"
                "draft_sha256,content_sha256,pipeline_fingerprint,model_output_sha256s,model_opinion_sha256s,"
                "decision,decision_reason,review_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    uuid.uuid4(), job_id, kind, "policy_model_review", acceptance.POLICY_VERSION,
                    receipt["input_sha256"], receipt["candidate_sha256"], receipt["draft_sha256"],
                    receipt["content_sha256"], receipt["pipeline_fingerprint"],
                    receipt["model_output_sha256s"], receipt["model_opinion_sha256s"],
                    receipt["decision"], receipt["decision_reason"], None, Jsonb(receipt),
                ),
            )
        return read_candidate(conn, job_id, kind)


def review_detail(conn, review_id: Any) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT candidate_sha, job_id, kind, review_id, parent_candidate_sha, revision_no, "
        "upstream_candidate_sha, context_sha, context_payload, candidate_payload, model_version "
        "FROM chronicle.person_history_candidates WHERE review_id = %s",
        (review_id,),
    ).fetchone()
    return _candidate_view(conn, row) if row else None


def decide(
    conn, *, review_id: Any, candidate_sha: str, decision: str, rationale: str,
    content: dict[str, Any] | None = None,
    reviewed_conclusion_ids: list[str] | None = None,
) -> dict[str, Any]:
    if decision not in {"approve", "reject"} or not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        raise PersistenceError("person-history review requires approve/reject and a rationale up to 4000 characters")
    reject_job = None
    with conn.transaction():
        identity = conn.execute(
            "SELECT job_id FROM chronicle.review_items WHERE review_id = %s", (review_id,)
        ).fetchone()
        if identity is None:
            raise PersistenceError("unknown person-history review")
        job_row = conn.execute(
            "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE", (identity[0],)
        ).fetchone()
        conn.execute("SELECT review_id FROM chronicle.review_items WHERE review_id = %s FOR UPDATE", (review_id,))
        row = review_detail(conn, review_id)
        if job_row is None or job_row[0] not in {"running", "needs_review"}:
            raise PersistenceConflict("cannot decide a cancelled or terminal person-history job")
        if not row or row["candidate_sha"] != candidate_sha or row["status"] != "open":
            raise PersistenceConflict("person-history review is stale or already decided")
        accepted = content if content is not None else row["candidate"]
        if decision == "approve":
            if accepted != row["candidate"]:
                raise PersistenceConflict("human edits require a new person-history draft; use revise_candidate")
            if row["kind"] == "summary":
                contract.validate_summary(accepted, row["context"])
                expected_reviewed = {item["id"] for item in accepted["conclusions"]}
                reviewed_conclusion_ids = _require_reviewed_ids(
                    reviewed_conclusion_ids, expected_reviewed, "summary"
                )
            else:
                summary = approved_content(read_candidate(conn, identity[0], "summary"))
                contract.validate_prose(accepted, row["context"], summary)
                expected_reviewed = {
                    conclusion_id
                    for paragraph in accepted["paragraphs"]
                    for segment in paragraph["segments"]
                    for conclusion_id in segment["conclusion_ids"]
                }
                reviewed_conclusion_ids = _require_reviewed_ids(
                    reviewed_conclusion_ids, expected_reviewed, "prose"
                )
        elif reviewed_conclusion_ids is not None:
            raise PersistenceError("reviewed_conclusion_ids is only valid when approving")
        result = {
            "decision": decision, "rationale": rationale.strip(), "content": accepted,
            "content_sha": sha256_json(accepted), "candidate_sha": candidate_sha,
        }
        if reviewed_conclusion_ids is not None:
            result["reviewed_conclusion_ids"] = list(reviewed_conclusion_ids)
        conn.execute(
            "UPDATE chronicle.review_items SET payload = payload || %s WHERE review_id = %s",
            (Jsonb({"decision": result}), review_id),
        )
        control_plane.resolve_review_item(conn, review_id=review_id)
        if decision == "approve":
            payload = row.get("review_payload") or {}
            receipt = acceptance.build_receipt(
                job_id=identity[0], kind=row["kind"], acceptance_type="human",
                input_sha256=row["context_sha"], candidate_sha256=candidate_sha,
                content=accepted, pipeline_fingerprint=payload.get("pipeline_fingerprint"),
                model_output_sha256s=list(payload.get("model_output_sha256s") or []),
                model_opinion_sha256s=list(payload.get("model_opinion_sha256s") or []),
                decision_reason=rationale, review_id=review_id,
                reviewed_conclusion_ids=list(reviewed_conclusion_ids or []),
            )
            acceptance.validate_receipt(receipt)
            conn.execute(
                "INSERT INTO chronicle.person_history_acceptances "
                "(acceptance_id,job_id,kind,acceptance_type,policy_version,input_sha256,candidate_sha256,"
                "draft_sha256,content_sha256,pipeline_fingerprint,model_output_sha256s,model_opinion_sha256s,"
                "decision,decision_reason,review_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    uuid.uuid4(), identity[0], row["kind"], "human", acceptance.POLICY_VERSION,
                    receipt["input_sha256"], receipt["candidate_sha256"], receipt["draft_sha256"],
                    receipt["content_sha256"], receipt["pipeline_fingerprint"],
                    receipt["model_output_sha256s"], receipt["model_opinion_sha256s"],
                    receipt["decision"], receipt["decision_reason"], review_id, Jsonb(receipt),
                ),
            )
        else:
            reject_job = identity[0]
    if reject_job is not None:
        control_plane.cancel_job(conn, job_id=reject_job)
    return review_detail(conn, review_id)


def revise_candidate(
    conn, *, job_id: Any, worker: str | None = None, kind: str, candidate_sha: str,
    content: dict[str, Any], rationale: str,
) -> dict[str, Any]:
    import resolve_publish

    kind = _kind(kind)
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        raise PersistenceError("person-history revision requires a rationale up to 4000 characters")
    with conn.transaction():
        if worker is not None:
            resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        job = conn.execute(
            "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE", (job_id,)
        ).fetchone()
        if job is None or job[0] not in {"running", "needs_review"}:
            raise PersistenceConflict("cannot revise a cancelled or terminal person-history job")
        row = read_candidate(conn, job_id, kind)
        if not row or row["candidate_sha"] != candidate_sha:
            raise PersistenceConflict("person-history revision is stale; reload the candidate frontier")
        if content == row["candidate"]:
            raise PersistenceError("person-history revision must change the candidate draft")
        if kind == "summary":
            contract.validate_summary(content, row["context"])
            upstream = None
        else:
            summary_row = read_candidate(conn, job_id, "summary")
            summary = approved_content(summary_row)
            contract.validate_prose(content, row["context"], summary)
            upstream = summary_row["candidate_sha"]
        digest = sha256_json({
            "job_id": str(job_id), "kind": kind, "context": row["context"],
            "candidate": content, "upstream_candidate_sha": upstream,
            "parent_candidate_sha": row["candidate_sha"], "revision_no": row["revision_no"] + 1,
        })
        _dismiss_review(conn, row.get("review_id"), superseded_by=digest)
        if kind == "summary":
            prose_row = read_candidate(conn, job_id, "prose")
            if prose_row:
                _dismiss_review(conn, prose_row.get("review_id"), superseded_by=digest)
        old_payload = row.get("review_payload") or {}
        payload = {
            "scope": PRODUCT_SCOPE, "stage": "present", "person_history_kind": kind,
            "candidate_sha": digest, "parent_candidate_sha": row["candidate_sha"],
            "revision_no": row["revision_no"] + 1, "review_mode": "manual_revision",
            "revision_rationale": rationale.strip(), "acceptance_mode": "exception_review",
            "blocking": True, "allowed_decisions": ["approve", "reject", "revise"],
            "issues": list(old_payload.get("issues") or []) + [{
                "id": "manual_revision_unreviewed", "type": "manual_edit",
                "message": "人工修改形成新稿，必须重新完成受影响内容、来源和身份核对。",
                "evidence": [], "represented": False,
            }],
            "pending_issues": ["manual_revision_unreviewed"],
            "pipeline_fingerprint": old_payload.get("pipeline_fingerprint"),
            "context_sha256": row["context_sha"], "upstream_candidate_sha": upstream,
            "candidates": list(old_payload.get("candidates") or []),
            "comparisons": list(old_payload.get("comparisons") or []),
            "model_output_sha256s": list(old_payload.get("model_output_sha256s") or []),
            "model_opinion_sha256s": list(old_payload.get("model_opinion_sha256s") or []),
        }
        new_review = control_plane.open_review_item(conn, job_id=job_id, kind="stage_gate", payload=payload)
        if job[0] == "running":
            control_plane.set_job_status(conn, job_id=job_id, status="needs_review")
            control_plane.advance_stage(conn, job_id=job_id, stage="present", status="needs_review")
        conn.execute(
            "INSERT INTO chronicle.person_history_candidates "
            "(candidate_sha,job_id,kind,review_id,parent_candidate_sha,revision_no,upstream_candidate_sha,"
            "context_sha,context_payload,candidate_payload,model_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                digest, job_id, kind, new_review, row["candidate_sha"], row["revision_no"] + 1,
                upstream, row["context_sha"], Jsonb(row["context"]), Jsonb(content), "human-revision",
            ),
        )
    return read_candidate(conn, job_id, kind)


revise = revise_candidate


def _mapping_rows(context: dict[str, Any], summary: dict[str, Any], version_sha: str) -> list[tuple[Any, ...]]:
    positions = {item["id"]: item for item in context.get("main_history_positions", [])}
    conclusions = summary["conclusions"]
    result = []
    for phase in summary["phases"]:
        conclusion_ids = [item["id"] for item in conclusions if phase["id"] in item["phase_ids"]]
        position_ids = list(phase["mapping_position_ids"])
        if not position_ids:
            result.append((version_sha, phase["id"], 0, "unmapped", None, None, None,
                           phase["mapping_reason"], conclusion_ids,
                           Jsonb({"phase_id": phase["id"], "mapping_status": "unmapped"})))
            continue
        for index, position_id in enumerate(position_ids):
            position = positions[position_id]
            result.append((
                version_sha, phase["id"], index, phase["mapping_status"],
                position["version_sha"], position["paragraph_id"], position.get("phase_id"),
                phase["mapping_reason"], conclusion_ids,
                Jsonb({"phase_id": phase["id"], "position_id": position_id, "mapping_status": phase["mapping_status"]}),
            ))
    return result


def publish(conn, *, job_id: Any, worker: str) -> dict[str, Any]:
    import resolve_publish

    with conn.transaction():
        control_plane.require_job_lease(conn, job_id=job_id, worker=worker)
        resolve_publish.acquire_publish_lock(conn)
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        summary_row = read_candidate(conn, job_id, "summary")
        prose_row = read_candidate(conn, job_id, "prose")
        summary = approved_content(summary_row)
        prose = approved_content(prose_row)
        if summary_row["context"] != prose_row["context"]:
            raise PersistenceConflict("person-history summary and prose use different frozen contexts")
        context = summary_row["context"]
        if canonical_store.read_latest_catalog_sha256(conn) != context["source_selection"]["catalog_sha"]:
            raise resolve_publish.PublicationPlanStale(
                "new sources changed the person-history context; select sources again"
            )
        publication = contract.compile_publication(context, summary, prose)
        person_id = _uuid(context["target"]["person_id"], "person_id")
        publication_ids = [_uuid(item, "source publication id") for item in context["source_selection"]["publication_ids"]]
        summary_acceptance = _uuid(summary_row["acceptance_id"], "summary acceptance id")
        prose_acceptance = _uuid(prose_row["acceptance_id"], "prose acceptance id")
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        conn.execute(
            "INSERT INTO chronicle.person_histories "
            "(version_sha,job_id,person_id,catalog_sha,context_sha,source_publication_ids,"
            "summary_candidate_sha,prose_candidate_sha,summary_acceptance_id,prose_acceptance_id,"
            "summary_sha,prose_sha,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (version_sha) DO NOTHING",
            (
                publication["publication_version"], job_id, person_id,
                context["source_selection"]["catalog_sha"], sha256_json(context), publication_ids,
                summary_row["candidate_sha"], prose_row["candidate_sha"], summary_acceptance, prose_acceptance,
                sha256_json(summary), sha256_json(prose), Jsonb(publication),
            ),
        )
        for values in _mapping_rows(context, summary, publication["publication_version"]):
            conn.execute(
                "INSERT INTO chronicle.person_history_mappings "
                "(person_history_version_sha,person_phase_id,mapping_no,mapping_status,"
                "main_history_version_sha,main_history_paragraph_id,main_history_phase_id,reason,"
                "evidence_conclusion_ids,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                values,
            )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        return publication


def read_publication(conn, *, person_id: Any = None, version: str | None = None) -> dict[str, Any] | None:
    if version is not None:
        _sha(version, "person-history version")
    params: list[Any] = []
    where = []
    if version is not None:
        where.append("version_sha = %s")
        params.append(version)
    if person_id is not None:
        where.append("person_id = %s")
        params.append(_uuid(person_id, "person_id"))
    clause = " WHERE " + " AND ".join(where) if where else ""
    order = "" if version is not None else " ORDER BY publication_sequence DESC"
    row = conn.execute(
        "SELECT payload FROM chronicle.person_histories" + clause + order + " LIMIT 1", tuple(params)
    ).fetchone()
    return copy.deepcopy(row[0]) if row else None


def list_mappings(conn, *, version: str, person_phase_id: str | None = None) -> list[dict[str, Any]]:
    _sha(version, "person-history version")
    params: list[Any] = [version]
    where = "WHERE person_history_version_sha = %s"
    if person_phase_id is not None:
        if not isinstance(person_phase_id, str) or not person_phase_id:
            raise PersistenceError("person_phase_id must be a nonempty string")
        where += " AND person_phase_id = %s"
        params.append(person_phase_id)
    rows = conn.execute(
        "SELECT person_phase_id,mapping_no,mapping_status,main_history_version_sha,"
        "main_history_paragraph_id,main_history_phase_id,reason,evidence_conclusion_ids,payload "
        "FROM chronicle.person_history_mappings " + where +
        " ORDER BY person_phase_id,mapping_no",
        tuple(params),
    ).fetchall()
    return [
        {
            "person_phase_id": row[0], "mapping_no": row[1], "mapping_status": row[2],
            "main_history_version_sha": row[3], "main_history_paragraph_id": row[4],
            "main_history_phase_id": row[5], "reason": row[6],
            "evidence_conclusion_ids": list(row[7] or []), "payload": copy.deepcopy(row[8]),
        }
        for row in rows
    ]


__all__ = [
    "KINDS",
    "PLAN_TYPE",
    "PRODUCT_SCOPE",
    "REQUEST_TYPE",
    "STEP_ATTEMPT_TYPE",
    "STEP_TYPE",
    "StepBudgetExhausted",
    "approved_content",
    "begin_step_attempt",
    "build_context",
    "finish_step_attempt",
    "freeze_pipeline",
    "job_scope",
    "list_mappings",
    "list_person_choices",
    "publish",
    "queue_person_history",
    "read_candidate",
    "read_outputs",
    "read_publication",
    "review_detail",
    "revise",
    "revise_candidate",
    "save_candidate",
    "validate_source_scope",
    "decide",
]
