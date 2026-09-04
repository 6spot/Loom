"""Chronicle C1-T12 grounded zh-CN Reader Presentation projection.

Reader Presentation is derived application content, never historical authority.
The only durable support edge is `(bundle_label, staged Claim ref)`; canonical
identity, Claim/evidence payloads and source records stay untouched.

Generation is deliberately split into three phases so no database transaction
is held across a model call:

1. ``load_generation_context`` reads the exact canonical/source/Claim scope;
2. ``generate_candidate`` calls a provider using only that frozen context and
   validates the returned v0.1 contract fail-closed;
3. ``persist_candidate`` appends a new immutable presentation version whose
   support refs are rechecked by PostgreSQL triggers.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any

from psycopg.types.json import Jsonb

from common import PersistenceConflict, PersistenceError, canonical_json_bytes, sha256_json

CONTRACT_VERSION = "0.1"
SCHEMA_NAME = "chronicle.reader-presentation"
BASE_LANGUAGE = "zh-CN"
GENERATOR_VERSION = "c1t12-v1"
PROMPT_VERSION = "c1t12-reader-zh-v1"
MAX_BLOCKS = 12
MAX_BLOCK_TEXT_CHARS = 600
BLOCK_KINDS = ("overview", "sequence", "outcome", "source_notes", "uncertainty")
EPISTEMIC_MODES = ("fact_summary", "source_report", "uncertainty")


def _canonical_id(value: uuid.UUID | str, description: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PersistenceError(f"{description} must be a UUID") from exc


def _target_spec(target_kind: str) -> tuple[str, str, str, str]:
    if target_kind == "entity":
        return (
            "chronicle.canonical_entity_representations",
            "chronicle.staged_entities",
            "entity_ref",
            "canonical_entity_id",
        )
    if target_kind == "event":
        return (
            "chronicle.canonical_event_representations",
            "chronicle.staged_events",
            "event_ref",
            "canonical_event_id",
        )
    raise PersistenceError("Reader Presentation target_kind must be 'entity' or 'event'")


def _direct_claims(conn, *, bundle: str, ref_kind: str, record_ref: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT record_ref, payload
        FROM chronicle.staged_claims
        WHERE bundle_label = %s
          AND (
            (payload->'subject'->>'kind' = %s AND payload->'subject'->>'ref' = %s)
            OR
            (payload->'object'->>'kind' = %s AND payload->'object'->>'ref' = %s)
          )
        ORDER BY record_ref
        """,
        (bundle, ref_kind, record_ref, ref_kind, record_ref),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for claim_ref, payload in rows:
        if not isinstance(payload, dict):
            continue
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict):
            continue
        text = evidence.get("text")
        source_ref = evidence.get("source_ref")
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(source_ref, str) or not source_ref.strip():
            continue
        result.append({"bundle": bundle, "ref": claim_ref, "claim": payload})
    return result


def _resolution_links(conn, *, target_kind: str, reps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table = (
        "chronicle.resolution_entity_links"
        if target_kind == "entity"
        else "chronicle.resolution_event_links"
    )
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for rep in reps:
        rows = conn.execute(
            f"""
            SELECT resolution_sha256, candidate_id,
                   left_bundle_label, left_record_ref,
                   right_bundle_label, right_record_ref,
                   decision, confidence, rationale, signals
            FROM {table}
            WHERE (left_bundle_label = %s AND left_record_ref = %s)
               OR (right_bundle_label = %s AND right_record_ref = %s)
            ORDER BY resolution_sha256, candidate_id
            """,
            (rep["bundle"], rep["ref"], rep["bundle"], rep["ref"]),
        ).fetchall()
        for row in rows:
            found[(row[0], row[1])] = {
                "resolution_sha256": row[0],
                "candidate_id": row[1],
                "left": {"bundle": row[2], "ref": row[3]},
                "right": {"bundle": row[4], "ref": row[5]},
                "decision": row[6],
                "confidence": float(row[7]),
                "rationale": row[8],
                "signals": row[9] if isinstance(row[9], list) else [],
            }
    return [found[key] for key in sorted(found)]


def _claim_disagreement(claims: list[dict[str, Any]]) -> bool:
    """Conservatively flag same-predicate, materially different Claim objects."""
    by_predicate: dict[str, set[bytes]] = defaultdict(set)
    for entry in claims:
        claim = entry.get("claim")
        if not isinstance(claim, dict):
            continue
        predicate = claim.get("predicate")
        if not isinstance(predicate, str) or not predicate:
            continue
        # Object + time are the assertion surface. Evidence wording alone can
        # differ across sources without constituting a historical disagreement.
        assertion = {"object": claim.get("object"), "time": claim.get("time")}
        by_predicate[predicate].add(canonical_json_bytes(assertion))
    return any(len(values) > 1 for values in by_predicate.values())


def load_generation_context(
    conn,
    *,
    target_kind: str,
    canonical_id: uuid.UUID | str,
) -> dict[str, Any]:
    """Read the frozen, direct-Claim context allowed for one presentation."""
    rep_table, staged_table, ref_kind, _ = _target_spec(target_kind)
    canonical_uuid = _canonical_id(canonical_id, "canonical target id")
    rows = conn.execute(
        f"""
        SELECT r.bundle_label, r.record_ref, s.payload,
               b.source_ref, b.source_title
        FROM {rep_table} r
        JOIN {staged_table} s
          ON s.bundle_label = r.bundle_label AND s.record_ref = r.record_ref
        JOIN chronicle.source_bundles b ON b.bundle_label = r.bundle_label
        WHERE r.canonical_id = %s
        ORDER BY r.bundle_label, r.record_ref
        """,
        (canonical_uuid,),
    ).fetchall()
    if not rows:
        raise PersistenceError(
            f"canonical {target_kind} {canonical_uuid} has no persisted representations"
        )

    reps: list[dict[str, Any]] = []
    all_claims: list[dict[str, Any]] = []
    for bundle, record_ref, payload, source_ref, source_title in rows:
        claims = _direct_claims(
            conn, bundle=bundle, ref_kind=ref_kind, record_ref=record_ref
        )
        all_claims.extend(claims)
        reps.append(
            {
                "bundle": bundle,
                "ref": record_ref,
                "source": {"ref": source_ref, "title": source_title},
                "record": payload,
                "claims": claims,
            }
        )
    if not all_claims:
        raise PersistenceError(
            f"canonical {target_kind} {canonical_uuid} has no direct evidenced Claims; "
            "Reader Presentation refuses to invent prose without Claim support"
        )

    resolutions = _resolution_links(conn, target_kind=target_kind, reps=reps)
    unresolved_identity = any(item.get("decision") == "uncertain" for item in resolutions)
    disagreement = _claim_disagreement(all_claims)
    allowed_refs = sorted(
        {f"{claim['bundle']}:{claim['ref']}" for claim in all_claims}
    )
    context = {
        "schema": "chronicle.reader-presentation-context",
        "version": CONTRACT_VERSION,
        "target_kind": target_kind,
        "canonical_id": str(canonical_uuid),
        "language": BASE_LANGUAGE,
        "representations": reps,
        "resolution_links": resolutions,
        "constraints": {
            "allowed_claim_refs": allowed_refs,
            "requires_uncertainty": bool(unresolved_identity or disagreement),
            "disagreement_detected": disagreement,
            "uncertain_resolution_detected": unresolved_identity,
        },
    }
    context["input_fingerprint"] = sha256_json(context)
    return context


def build_prompt(context: dict[str, Any]) -> str:
    """Build the frozen v0.1 prompt. The supplied JSON is the entire world."""
    if context.get("schema") != "chronicle.reader-presentation-context":
        raise PersistenceError("Reader Presentation context has the wrong schema")
    payload = canonical_json_bytes(context).decode("utf-8")
    return (
        "你是 Chronicle Reader Presentation 生成器。只允许使用下面 INPUT JSON 中已经提供的事实。\n"
        "目标：把古文/结构化 Claim 整理成现代、清楚、克制的简体中文阅读文本，而不是逐字翻译。\n"
        "绝对规则：\n"
        "1. 不得补充 INPUT 之外的常识、背景、因果、意义、人物评价或年代。\n"
        "2. 每个 block 必须是一个可以单独审计的原子陈述，并至少引用一个 INPUT.constraints.allowed_claim_refs 中的 Claim。\n"
        "3. claim_refs 只能写成 {\"bundle\":...,\"ref\":...}；不能创造 Claim。\n"
        "4. 若证据不足，省略该内容；不要猜。\n"
        "5. 如果 INPUT.constraints.requires_uncertainty=true，必须至少输出一个 block_kind=uncertainty、epistemic_mode=uncertainty 的 block，明确来源分歧或身份不确定，而不是消除它。\n"
        "6. 不要生成 why/significance；C1-T12 只允许 overview/sequence/outcome/source_notes/uncertainty。\n"
        "7. 只输出严格 JSON，不要 Markdown、代码围栏或解释。\n"
        f"输出 schema={SCHEMA_NAME}, version={CONTRACT_VERSION}, language={BASE_LANGUAGE}。\n"
        "INPUT:\n"
        + payload
    )


def _claim_key(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise PersistenceError("Reader Presentation claim_ref must be an object")
    bundle, ref = value.get("bundle"), value.get("ref")
    if not isinstance(bundle, str) or not bundle or not isinstance(ref, str) or not ref:
        raise PersistenceError("Reader Presentation claim_ref requires bundle/ref")
    return bundle, ref


def validate_candidate(candidate: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Normalize one model candidate and reject any out-of-scope support."""
    if not isinstance(candidate, dict):
        raise PersistenceError("Reader Presentation candidate must be a JSON object")
    expected = {
        "schema": SCHEMA_NAME,
        "version": CONTRACT_VERSION,
        "target_kind": context["target_kind"],
        "canonical_id": context["canonical_id"],
        "language": BASE_LANGUAGE,
    }
    for key, value in expected.items():
        if candidate.get(key) != value:
            raise PersistenceError(
                f"Reader Presentation candidate {key} must be {value!r}, got {candidate.get(key)!r}"
            )
    blocks = candidate.get("blocks")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= MAX_BLOCKS:
        raise PersistenceError(
            f"Reader Presentation blocks must contain 1..{MAX_BLOCKS} items"
        )

    allowed: set[tuple[str, str]] = set()
    for rep in context.get("representations") or []:
        for claim in rep.get("claims") or []:
            allowed.add((str(claim.get("bundle")), str(claim.get("ref"))))

    normalized_blocks: list[dict[str, Any]] = []
    has_uncertainty = False
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise PersistenceError(f"Reader Presentation block {index} must be an object")
        kind = block.get("block_kind")
        mode = block.get("epistemic_mode")
        text = block.get("text")
        if kind not in BLOCK_KINDS:
            raise PersistenceError(f"Reader Presentation block {index} has invalid block_kind")
        if mode not in EPISTEMIC_MODES:
            raise PersistenceError(f"Reader Presentation block {index} has invalid epistemic_mode")
        if (kind == "uncertainty") != (mode == "uncertainty"):
            raise PersistenceError(
                "uncertainty blocks must use epistemic_mode=uncertainty and vice versa"
            )
        if not isinstance(text, str) or not text.strip():
            raise PersistenceError(f"Reader Presentation block {index} text must be non-empty")
        text = text.strip()
        if len(text) > MAX_BLOCK_TEXT_CHARS:
            raise PersistenceError(
                f"Reader Presentation block {index} exceeds {MAX_BLOCK_TEXT_CHARS} characters"
            )
        refs = block.get("claim_refs")
        if not isinstance(refs, list) or not refs:
            raise PersistenceError(
                f"Reader Presentation block {index} must bind at least one Claim"
            )
        support = sorted({_claim_key(item) for item in refs})
        unknown = [item for item in support if item not in allowed]
        if unknown:
            raise PersistenceError(
                f"Reader Presentation block {index} references Claims outside generation scope: {unknown}"
            )
        normalized_blocks.append(
            {
                "block_id": f"b{index + 1:03d}",
                "block_kind": kind,
                "epistemic_mode": mode,
                "text": text,
                "claim_refs": [
                    {"bundle": bundle, "ref": ref} for bundle, ref in support
                ],
            }
        )
        has_uncertainty = has_uncertainty or kind == "uncertainty"

    if context.get("constraints", {}).get("requires_uncertainty") and not has_uncertainty:
        raise PersistenceError(
            "Reader Presentation context contains disagreement/uncertainty but candidate omitted an uncertainty block"
        )
    return {
        "schema": SCHEMA_NAME,
        "version": CONTRACT_VERSION,
        "target_kind": context["target_kind"],
        "canonical_id": context["canonical_id"],
        "language": BASE_LANGUAGE,
        "blocks": normalized_blocks,
    }


def generate_candidate(context: dict[str, Any], model: Any) -> dict[str, Any]:
    """Call one provider with the frozen prompt and validate strict JSON output."""
    if not callable(getattr(model, "complete", None)):
        raise PersistenceError("Reader Presentation model must expose complete(prompt)->str")
    name = getattr(model, "name", None)
    if not isinstance(name, str) or not name:
        raise PersistenceError("Reader Presentation model must expose a non-empty name")
    raw = model.complete(build_prompt(context))
    if not isinstance(raw, str):
        raise PersistenceError("Reader Presentation model response must be text")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PersistenceError(
            f"Reader Presentation model response is not strict JSON: {exc}"
        ) from exc
    return validate_candidate(parsed, context)


def _presentation_target_clause(target_kind: str) -> tuple[str, str]:
    _target_spec(target_kind)
    if target_kind == "entity":
        return "canonical_entity_id", "canonical_event_id"
    return "canonical_event_id", "canonical_entity_id"


def persist_candidate(
    conn,
    *,
    context: dict[str, Any],
    candidate: dict[str, Any],
    model_version: str,
    origin_job_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Append (or idempotently adopt) one validated immutable presentation."""
    candidate = validate_candidate(candidate, context)
    if not isinstance(model_version, str) or not model_version:
        raise PersistenceError("Reader Presentation model_version must be non-empty")
    target_kind = str(context["target_kind"])
    canonical_uuid = _canonical_id(context["canonical_id"], "canonical target id")
    target_column, other_column = _presentation_target_clause(target_kind)
    input_fingerprint = context.get("input_fingerprint")
    if not isinstance(input_fingerprint, str) or len(input_fingerprint) != 64:
        raise PersistenceError("Reader Presentation context is missing input_fingerprint")
    content_sha = sha256_json(candidate)
    job_uuid = None if origin_job_id is None else _canonical_id(origin_job_id, "origin job id")

    # Crash/retry adoption: exact same target/input/generator/model/content is
    # the same derived artifact and must not create another version.
    existing = conn.execute(
        f"""
        SELECT presentation_id, presentation_version, supersedes_presentation_id
        FROM chronicle.reader_presentations
        WHERE target_kind = %s AND {target_column} = %s
          AND input_fingerprint = %s AND content_sha256 = %s
          AND generator_version = %s AND prompt_version = %s
          AND model_version = %s AND status = 'published'
        ORDER BY presentation_version DESC
        LIMIT 1
        """,
        (
            target_kind,
            canonical_uuid,
            input_fingerprint,
            content_sha,
            GENERATOR_VERSION,
            PROMPT_VERSION,
            model_version,
        ),
    ).fetchone()
    if existing is not None:
        return {
            "presentation_id": str(existing[0]),
            "presentation_version": int(existing[1]),
            "content_sha256": content_sha,
            "input_fingerprint": input_fingerprint,
            "adopted": True,
        }

    with conn.transaction():
        # Serialize version allocation on the canonical identity row without
        # taking any ownership over that identity.
        canonical_table = (
            "chronicle.canonical_entities"
            if target_kind == "entity"
            else "chronicle.canonical_events"
        )
        locked = conn.execute(
            f"SELECT 1 FROM {canonical_table} WHERE canonical_id = %s FOR UPDATE",
            (canonical_uuid,),
        ).fetchone()
        if locked is None:
            raise PersistenceError(f"unknown canonical {target_kind} {canonical_uuid}")
        previous = conn.execute(
            f"""
            SELECT presentation_id, presentation_version
            FROM chronicle.reader_presentations
            WHERE target_kind = %s AND {target_column} = %s AND status = 'published'
            ORDER BY presentation_version DESC
            LIMIT 1
            """,
            (target_kind, canonical_uuid),
        ).fetchone()
        version = 1 if previous is None else int(previous[1]) + 1
        previous_id = None if previous is None else previous[0]
        presentation_id = uuid.uuid4()
        entity_id = canonical_uuid if target_kind == "entity" else None
        event_id = canonical_uuid if target_kind == "event" else None
        conn.execute(
            """
            INSERT INTO chronicle.reader_presentations(
                presentation_id, target_kind,
                canonical_entity_id, canonical_event_id,
                base_language, contract_version, presentation_version,
                status, generator_version, model_version, prompt_version,
                input_fingerprint, content_sha256, origin_job_id,
                supersedes_presentation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                'published', %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                presentation_id,
                target_kind,
                entity_id,
                event_id,
                BASE_LANGUAGE,
                CONTRACT_VERSION,
                version,
                GENERATOR_VERSION,
                model_version,
                PROMPT_VERSION,
                input_fingerprint,
                content_sha,
                job_uuid,
                previous_id,
            ),
        )
        for index, block in enumerate(candidate["blocks"]):
            conn.execute(
                """
                INSERT INTO chronicle.reader_presentation_blocks(
                    presentation_id, block_index, block_id,
                    block_kind, epistemic_mode, text
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    presentation_id,
                    index,
                    block["block_id"],
                    block["block_kind"],
                    block["epistemic_mode"],
                    block["text"],
                ),
            )
            for support in block["claim_refs"]:
                conn.execute(
                    """
                    INSERT INTO chronicle.reader_presentation_supports(
                        presentation_id, block_index, bundle_label, claim_ref
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        presentation_id,
                        index,
                        support["bundle"],
                        support["ref"],
                    ),
                )
    return {
        "presentation_id": str(presentation_id),
        "presentation_version": version,
        "content_sha256": content_sha,
        "input_fingerprint": input_fingerprint,
        "adopted": False,
    }


def targets_for_job(conn, *, job_id: uuid.UUID | str) -> list[dict[str, str]]:
    """Return canonical targets touched by the job's published revision bundle."""
    job_uuid = _canonical_id(job_id, "job id")
    row = conn.execute(
        "SELECT revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s",
        (job_uuid,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown job {job_uuid}")
    revision_id = row[0]
    # Keep the label rule identical to C1-T8 without importing worker code.
    bundle_label = f"c1rev-{str(revision_id).replace('-', '')[:12]}"
    result: list[dict[str, str]] = []
    for target_kind, table in (
        ("entity", "chronicle.canonical_entity_representations"),
        ("event", "chronicle.canonical_event_representations"),
    ):
        rows = conn.execute(
            f"""
            SELECT DISTINCT canonical_id::text
            FROM {table}
            WHERE bundle_label = %s
            ORDER BY canonical_id::text
            """,
            (bundle_label,),
        ).fetchall()
        result.extend(
            {"target_kind": target_kind, "canonical_id": item[0]}
            for item in rows
        )
    return result


def content_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    """Stable output artifact payload for control-plane provenance."""
    return {
        "schema": SCHEMA_NAME,
        "version": CONTRACT_VERSION,
        "language": BASE_LANGUAGE,
        "target_kind": candidate["target_kind"],
        "canonical_id": candidate["canonical_id"],
        "blocks": candidate["blocks"],
    }
