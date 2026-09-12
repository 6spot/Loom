"""Chronicle C2-R3-T06 chapter-level person-state evidence review core.

Owns the third-round review step fixed by
``apps/chronicle/docs/person-state-reading.md`` section 5 and the
``C2-R3-T06`` task note. After the existing identity Resolution review,
operators assess one frozen evidence package per natural chapter; the
assessments feed T04's compiler without ever changing canonical identity,
the accepted 0.3 artifact or the original C0 Claim.

Public entries
--------------

- :func:`build_person_state_review_plan` — freeze
  ``c2r3-person-state-review-plan-v1`` from the accepted 0.3 artifacts and
  the T03 assembly. It binds the accepted/assembled hashes, the final
  Resolution hashes, the base catalog and every candidate key; a candidate
  key appears exactly once and display names never establish a group.
- :func:`open_person_state_reviews` — open/adopt one ``stage_gate``
  ReviewItem per chapter package (``scope=person_state``,
  ``review_mode=chapter_state_evidence``). Resuming the same job adopts the
  frozen items instead of duplicating review debt.
- :func:`resolve_person_state_review` — under the job lock validate a
  default + per-candidate override decision against the frozen package,
  then commit the decision, terminal status and audit together. Missing,
  duplicate, out-of-scope, drifted or repeated submissions fail with a
  concrete :class:`PersistenceConflict` and leave no half decision.
- :func:`collect_person_state_assessments` — once every package is terminal,
  fan the decisions back to every frozen candidate, persist the immutable
  assessment artifact through T05 and return the compiler-ready assessment
  mapping.

The module never writes a ``same_entity`` link, never edits an accepted
artifact or Claim and never reopens the identity review. Explicitly
``uncertain`` material may still publish; a dismissed package only ever
yields ``uncertain``; an open package can never be collected.
"""

from __future__ import annotations

import copy
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import control_plane  # noqa: E402
import person_state_contract as _contract  # noqa: E402
import person_state_projection as _projection  # noqa: E402
import person_state_store as _store  # noqa: E402
from common import PersistenceConflict, PersistenceError, sha256_json  # noqa: E402

#: Frozen chapter-level review plan version (enters the fingerprint).
REVIEW_PLAN_VERSION = "c2r3-person-state-review-plan-v1"

#: Plan document marker (a program document, never model-generated).
REVIEW_PLAN_SCHEMA = "chronicle.person-state-review-plan"

#: ReviewItem payload marker for a chapter-state-evidence package.
REVIEW_SCOPE = "person_state"
REVIEW_MODE = _contract.REVIEW_MODE
REVIEW_KIND = "stage_gate"

#: Assessment artifact marker persisted through T05.
ASSESSMENT_SCHEMA = "chronicle.person-state-assessment"
ASSESSMENT_VERSION = "0.1"

#: Default compiler version recorded with a collected assessment artifact.
DEFAULT_COMPILER_VERSION = _projection.PROJECTION_VERSION

ASSESSMENTS = tuple(_contract.ASSESSMENTS)
DEFAULT_ASSESSMENT = "uncertain"

#: Candidate kinds that must resolve at least one immutable anchor as their
#: source premise (mirrors T03 ``_ANCHOR_REQUIRED_KINDS``).
ANCHOR_REQUIRED_KINDS = ("phase", "phase_order", "fact", "continuity", "disagreement")

#: Kinds whose candidate maps onto a state evidence reference consumed by the
#: T04 compiler (``fact_ref`` / ``assertion_id`` in the assembled namespace).
COMPILER_ASSESSMENT_KINDS = ("phase", "phase_order", "fact", "continuity", "disagreement")

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

#: Candidate kinds carried by an accepted 0.3 artifact.
CANDIDATE_KINDS = (
    "phase",
    "phase_order",
    "unit_phase",
    "fact",
    "continuity",
    "disagreement",
)

#: Stable predicted-effect codes shown on a review candidate. They are a
#: bounded summary of what approving the candidate can change; T04 still owns
#: the actual compiled effect and `preview_person_state_review` exposes it.
EFFECT_CODES = (
    "current_identity",
    "prior_identity",
    "attested_identity",
    "change",
    "phase_definition",
    "prove_phase_order",
    "extend_tenure",
    "bind_unit_phase",
    "record_source_disagreement",
)


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------


def _require_sha256(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.match(value):
        raise PersistenceError(f"{description} must be a lowercase hex SHA-256 string")
    return value


def _require_text(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise PersistenceError(f"{description} must be a non-empty string")
    return value


def _require_object(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PersistenceError(f"{description} must be a JSON object")
    return value


def _require_list(value: Any, description: str) -> list[Any]:
    if not isinstance(value, list):
        raise PersistenceError(f"{description} must be an array")
    return value


# ---------------------------------------------------------------------------
# Accepted-artifact / assembly indexing (pure)
# ---------------------------------------------------------------------------


def _state_index(person_states: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """Index one artifact's state items as ``(kind, local_ref) -> item``."""
    if not isinstance(person_states, dict):
        return {}
    index: dict[tuple[str, str], dict[str, Any]] = {}
    groups = (
        ("phase", "phases", "phase_id"),
        ("phase_order", "phase_orders", "assertion_id"),
        ("unit_phase", "unit_phases", "block_id"),
        ("fact", "facts", "fact_id"),
        ("continuity", "continuities", "assertion_id"),
        ("disagreement", "disagreements", "assertion_id"),
    )
    for kind, collection, id_field in groups:
        for item in person_states.get(collection) or []:
            if isinstance(item, dict) and isinstance(item.get(id_field), str):
                index[(kind, item[id_field])] = item
    return index


def _reference_maps(assembly: dict[str, Any]) -> dict[str, dict[tuple[str, str], str]]:
    """Return ``chapter_id -> {(kind, origin_ref): revision_ref}`` from T03."""
    maps: dict[str, dict[tuple[str, str], str]] = {}
    for manifest in assembly.get("evidence_manifests") or []:
        if not isinstance(manifest, dict):
            continue
        chapter_id = manifest.get("chapter_id")
        if not isinstance(chapter_id, str) or not chapter_id:
            continue
        mapping = maps.setdefault(chapter_id, {})
        for item in manifest.get("items") or []:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            origin = item.get("origin_ref")
            revision = item.get("revision_ref")
            if not isinstance(kind, str) or not isinstance(origin, str):
                continue
            if not isinstance(revision, str) or not revision:
                continue
            key = (kind, origin)
            previous = mapping.get(key)
            if previous is not None and previous != revision:
                raise PersistenceConflict(
                    f"assembly maps {kind}:{origin} in {chapter_id} to two refs"
                )
            mapping[key] = revision
    return maps


def _predicted_effect(kind: str, item: dict[str, Any] | None) -> str:
    """A stable, bounded predicted effect for one candidate.

    ``current_identity`` / ``prior_identity`` distinguish an appointment whose
    phase is the reviewed unit's own phase from an earlier record; approving a
    start never marks a later phase's tenure clear (T04 keeps that separate).
    """
    if kind == "phase":
        return "phase_definition"
    if kind == "phase_order":
        return "prove_phase_order"
    if kind == "continuity":
        return "extend_tenure"
    if kind == "unit_phase":
        return "bind_unit_phase"
    if kind == "disagreement":
        return "record_source_disagreement"
    if kind == "fact" and isinstance(item, dict):
        operation = item.get("operation")
        qualification = item.get("qualification")
        if operation == "end":
            return "change"
        if qualification in _contract.UNLIMITED_QUALIFICATIONS:
            return "attested_identity"
        if operation == "start":
            return "current_identity"
        return "prior_identity" if operation == "attest" else "attested_identity"
    return "attested_identity"


def _artifact_candidates(
    artifact: dict[str, Any],
    *,
    chapter_id: str,
    references: dict[tuple[str, str], str],
) -> list[dict[str, Any]]:
    raw = artifact.get("person_state_candidates")
    if not isinstance(raw, list):
        raise PersistenceError(
            f"chapter {chapter_id!r} 0.3 artifact is missing its candidate keys"
        )
    state_index = _state_index(artifact.get("person_states"))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise PersistenceError(f"chapter {chapter_id!r} candidate[{position}] must be an object")
        kind = entry.get("kind")
        item_ref = entry.get("item_ref")
        anchor_ids = entry.get("anchor_ids")
        if kind not in CANDIDATE_KINDS:
            raise PersistenceConflict(f"chapter {chapter_id!r} candidate has unknown kind {kind!r}")
        if not isinstance(item_ref, str) or not item_ref:
            raise PersistenceError(f"chapter {chapter_id!r} candidate requires an item_ref")
        if not isinstance(anchor_ids, list) or any(not isinstance(a, str) for a in anchor_ids):
            raise PersistenceError(f"chapter {chapter_id!r} candidate anchor_ids must be strings")
        if len(set(anchor_ids)) != len(anchor_ids):
            raise PersistenceError(f"chapter {chapter_id!r} candidate repeats an anchor id")
        if kind in ANCHOR_REQUIRED_KINDS and not anchor_ids:
            raise PersistenceError(
                f"chapter {chapter_id!r} candidate {kind}:{item_ref} is missing its source anchors"
            )
        expected = _contract.candidate_key_for(
            kind=kind, chapter_id=chapter_id, item_ref=item_ref, anchor_ids=list(anchor_ids)
        )
        candidate_key = entry.get("candidate_key")
        if candidate_key != expected:
            raise PersistenceConflict(
                f"chapter {chapter_id!r} candidate {kind}:{item_ref} key does not match "
                "its resolved anchors"
            )
        if candidate_key in seen:
            raise PersistenceConflict(
                f"chapter {chapter_id!r} repeats candidate {kind}:{item_ref}"
            )
        seen.add(candidate_key)
        item = state_index.get((kind, item_ref))
        if item is None:
            raise PersistenceConflict(
                f"chapter {chapter_id!r} candidate {kind}:{item_ref} has no matching state item"
            )
        revision_ref = references.get((kind, item_ref))
        if not isinstance(revision_ref, str) or not revision_ref:
            raise PersistenceConflict(
                f"chapter {chapter_id!r} candidate {kind}:{item_ref} has no assembled "
                "revision reference (assembly no longer covers the frozen candidate)"
            )
        candidates.append(
            {
                "candidate_key": candidate_key,
                "kind": kind,
                "item_ref": item_ref,
                "chapter_id": chapter_id,
                "anchor_ids": list(anchor_ids),
                "phase_ids": [
                    phase for phase in entry.get("phase_ids") or [] if isinstance(phase, str)
                ],
                "source_fact_refs": [
                    ref for ref in entry.get("source_fact_refs") or [] if isinstance(ref, str)
                ],
                "revision_ref": revision_ref,
                "predicted_effect": _predicted_effect(kind, item),
                "dimension": item.get("dimension"),
                "operation": item.get("operation"),
                "qualification": item.get("qualification"),
                "attribution": item.get("attribution"),
                "assessment_default": DEFAULT_ASSESSMENT,
                "allowed_assessments": list(ASSESSMENTS),
            }
        )
    candidates.sort(key=lambda candidate: candidate["candidate_key"])
    return candidates


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def build_person_state_review_plan(
    *,
    job_id: Any,
    revision_id: Any,
    accepted_artifacts: list[dict[str, Any]],
    assembly: dict[str, Any],
    resolution_hashes: list[str],
    base_catalog_sha: str,
) -> dict[str, Any]:
    """Freeze one ``c2r3-person-state-review-plan-v1`` for a resolve job.

    ``accepted_artifacts`` are the accepted ``chronicle.chapter-artifact /
    0.3`` documents and ``assembly`` is the T03
    :func:`person_state_assembly.assemble_person_state_evidence` result. The
    plan binds the accepted/assembled hashes, the final Resolution hashes, the
    base catalog and the complete candidate set. A chapter with no person-state
    candidates contributes no package (no review debt), and every candidate key
    is covered exactly once.
    """
    if not isinstance(accepted_artifacts, list) or not accepted_artifacts:
        raise PersistenceError("person-state review plan requires at least one accepted artifact")
    _require_object(assembly, "person-state assembly")
    _require_sha256(base_catalog_sha, "base_catalog_sha")
    hashes = [_require_sha256(value, "resolution_hash") for value in _require_list(
        resolution_hashes, "resolution_hashes"
    )]
    person_states = assembly.get("person_states")
    if not isinstance(person_states, dict):
        raise PersistenceError("person-state assembly must carry a person_states block")
    # Never trust the reported hash: recompute it from the actual assembled
    # payload and fail closed when a report claims a different (older) content.
    # Otherwise a plan could advertise the old assembled hash while preview and
    # compilation consume tampered/new evidence.
    assembled_hash = sha256_json(person_states)
    report = assembly.get("report") if isinstance(assembly.get("report"), dict) else {}
    reported_hash = report.get("person_states_sha256")
    if reported_hash is not None and reported_hash != assembled_hash:
        raise PersistenceConflict(
            "assembly report person_states_sha256 does not match the actual assembled "
            f"payload ({reported_hash!r} != {assembled_hash!r}); refusing to freeze a plan"
        )

    references = _reference_maps(assembly)
    artifact_hashes: list[str] = []
    packages: list[dict[str, Any]] = []
    all_keys: list[str] = []
    for artifact in accepted_artifacts:
        artifact = _require_object(artifact, "accepted artifact")
        if artifact.get("schema") != _contract.ARTIFACT_SCHEMA or artifact.get(
            "version"
        ) != _contract.ARTIFACT_VERSION:
            raise PersistenceError("plan input must be chronicle.chapter-artifact / 0.3")
        chapter_id = _require_text(artifact.get("chapter_id"), "artifact chapter_id")
        artifact_sha = _require_sha256(artifact.get("artifact_sha256"), "artifact_sha256")
        person_states_sha = _require_sha256(
            artifact.get("person_states_sha256"), "person_states_sha256"
        )
        if artifact_sha in artifact_hashes:
            raise PersistenceConflict(f"duplicate accepted artifact for chapter {chapter_id!r}")
        artifact_hashes.append(artifact_sha)
        candidates = _artifact_candidates(
            artifact, chapter_id=chapter_id, references=references.get(chapter_id, {})
        )
        if not candidates:
            continue
        packages.append(
            {
                "chapter_id": chapter_id,
                "artifact_sha256": artifact_sha,
                "person_states_sha256": person_states_sha,
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        )
        all_keys.extend(candidate["candidate_key"] for candidate in candidates)

    if len(all_keys) != len(set(all_keys)):
        raise PersistenceConflict("person-state review plan repeats a candidate key")
    packages.sort(key=lambda package: package["chapter_id"])
    candidate_keys = sorted(all_keys)
    fingerprint = _contract.person_state_plan_fingerprint(
        accepted_artifact_hashes=sorted(artifact_hashes),
        assembled_hash=assembled_hash,
        resolution_hashes=sorted(hashes),
        base_catalog_sha=base_catalog_sha,
        candidate_keys=candidate_keys,
    )
    plan = {
        "schema": REVIEW_PLAN_SCHEMA,
        "version": REVIEW_PLAN_VERSION,
        "job_id": str(job_id),
        "revision_id": str(revision_id),
        "base_catalog_sha": base_catalog_sha,
        "assembled_hash": assembled_hash,
        "accepted_artifact_hashes": sorted(artifact_hashes),
        "resolution_hashes": sorted(hashes),
        "candidate_keys": candidate_keys,
        "plan_fingerprint": fingerprint,
        "packages": packages,
    }
    validate_person_state_review_plan(plan)
    return plan


def validate_person_state_review_plan(plan: dict[str, Any]) -> str:
    """Recompute and verify a frozen plan; return its fingerprint.

    Rebuilds the ``c2r3-person-state-review-plan-v1`` fingerprint from the
    stored bindings and re-derives every candidate key, so a tampered package,
    candidate list, hash binding or coverage gap fails closed before any
    database read.
    """
    plan = _require_object(plan, "person-state review plan")
    if plan.get("version") != REVIEW_PLAN_VERSION:
        raise PersistenceConflict(
            f"unknown person-state review plan version {plan.get('version')!r}"
        )
    frozen_keys = plan.get("candidate_keys")
    if (
        not isinstance(frozen_keys, list)
        or any(not isinstance(key, str) or not key for key in frozen_keys)
        or len(frozen_keys) != len(set(frozen_keys))
    ):
        raise PersistenceConflict("person-state review plan is missing its candidate list")
    packages = plan.get("packages")
    if not isinstance(packages, list) or any(not isinstance(p, dict) for p in packages):
        raise PersistenceConflict("person-state review plan packages must be objects")

    covered: list[str] = []
    for package in packages:
        chapter_id = _require_text(package.get("chapter_id"), "package chapter_id")
        candidates = package.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise PersistenceConflict(f"package {chapter_id!r} carries no candidates")
        seen: set[str] = set()
        for candidate in candidates:
            candidate = _require_object(candidate, "package candidate")
            kind = candidate.get("kind")
            item_ref = candidate.get("item_ref")
            anchor_ids = candidate.get("anchor_ids")
            if not isinstance(anchor_ids, list) or any(
                not isinstance(anchor, str) for anchor in anchor_ids
            ):
                raise PersistenceConflict(
                    f"package {chapter_id!r} candidate anchors must be strings"
                )
            expected = _contract.candidate_key_for(
                kind=str(kind),
                chapter_id=chapter_id,
                item_ref=str(item_ref),
                anchor_ids=list(anchor_ids),
            )
            if candidate.get("candidate_key") != expected:
                raise PersistenceConflict(
                    f"package {chapter_id!r} candidate {kind}:{item_ref} key no longer "
                    "matches its resolved anchors"
                )
            key = candidate["candidate_key"]
            if key in seen:
                raise PersistenceConflict(
                    f"package {chapter_id!r} repeats candidate {kind}:{item_ref}"
                )
            seen.add(key)
            covered.append(key)
        if package.get("candidate_count") != len(candidates):
            raise PersistenceConflict(f"package {chapter_id!r} candidate_count drifted")

    if sorted(covered) != sorted(frozen_keys) or len(covered) != len(set(covered)):
        raise PersistenceConflict(
            "person-state review plan does not cover every frozen candidate exactly once"
        )
    accepted = plan.get("accepted_artifact_hashes")
    resolutions = plan.get("resolution_hashes")
    if not isinstance(accepted, list) or not isinstance(resolutions, list):
        raise PersistenceConflict("person-state review plan is missing its hash bindings")
    recomputed = _contract.person_state_plan_fingerprint(
        accepted_artifact_hashes=[str(value) for value in accepted],
        assembled_hash=str(plan.get("assembled_hash")),
        resolution_hashes=[str(value) for value in resolutions],
        base_catalog_sha=str(plan.get("base_catalog_sha")),
        candidate_keys=frozen_keys,
    )
    if recomputed != plan.get("plan_fingerprint"):
        raise PersistenceConflict("person-state review plan fingerprint mismatch")
    return recomputed


# ---------------------------------------------------------------------------
# Open / adopt
# ---------------------------------------------------------------------------


def _scoped_review_rows(conn, job_id: uuid.UUID) -> list[tuple[Any, str, dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT review_id, status, payload
        FROM chronicle.review_items
        WHERE job_id = %s AND payload->>'scope' = %s
        ORDER BY created_at, review_id
        """,
        (job_id, REVIEW_SCOPE),
    ).fetchall()
    return [
        (review_id, status, payload if isinstance(payload, dict) else {})
        for review_id, status, payload in rows
    ]


def _package_payload(plan: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": REVIEW_SCOPE,
        "review_mode": REVIEW_MODE,
        "plan_version": REVIEW_PLAN_VERSION,
        "plan_fingerprint": plan["plan_fingerprint"],
        "chapter_id": package["chapter_id"],
        "artifact_sha256": package["artifact_sha256"],
        "person_states_sha256": package["person_states_sha256"],
        "base_catalog_sha": plan["base_catalog_sha"],
        "candidates": copy.deepcopy(package["candidates"]),
        "candidate_count": len(package["candidates"]),
        "default_assessment": DEFAULT_ASSESSMENT,
        "allowed_assessments": list(ASSESSMENTS),
        "decision": None,
    }


def _payload_candidate_keys(payload: dict[str, Any]) -> list[str]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise PersistenceConflict("person-state review payload is missing its candidates")
    keys: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise PersistenceConflict("person-state review candidate must be an object")
        key = candidate.get("candidate_key")
        if not isinstance(key, str) or not key:
            raise PersistenceConflict("person-state review candidate is missing its key")
        keys.append(key)
    if len(keys) != len(set(keys)):
        raise PersistenceConflict("person-state review payload repeats a candidate key")
    return sorted(keys)


def open_person_state_reviews(
    conn, *, job_id: uuid.UUID, plan: dict[str, Any]
) -> list[uuid.UUID]:
    """Open/adopt one ``stage_gate`` item per frozen chapter package.

    The whole frozen plan is validated first. The job row is then locked
    ``FOR UPDATE`` for the whole read/insert, so two concurrent open/resume
    calls serialize on the database row: the first inserts the packages, the
    second observes the committed items and adopts them exactly. Without this
    lock both calls could see an empty table and insert a second item for the
    same chapter. Existing ``person_state`` items for the job are adopted only
    when their fingerprint, chapter packages and candidate coverage match the
    plan exactly; otherwise the conflict is reported instead of silently
    opening a second set of reviews.
    """
    fingerprint = validate_person_state_review_plan(plan)
    if str(plan.get("job_id")) != str(job_id):
        raise PersistenceConflict("person-state review plan job mismatch")
    with conn.transaction():
        locked = conn.execute(
            "SELECT 1 FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if locked is None:
            raise PersistenceError(f"unknown job {job_id}")
        existing = _scoped_review_rows(conn, job_id)
        if existing:
            existing_keys: list[str] = []
            chapter_ids: set[str] = set()
            for _review_id, _status, payload in existing:
                if payload.get("review_mode") != REVIEW_MODE:
                    raise PersistenceConflict(
                        "persisted person-state review has an unknown review mode"
                    )
                if payload.get("plan_fingerprint") != fingerprint:
                    raise PersistenceConflict(
                        "persisted person-state review plan fingerprint mismatch"
                    )
                chapter_ids.add(str(payload.get("chapter_id")))
                existing_keys.extend(_payload_candidate_keys(payload))
            if len(chapter_ids) != len(existing):
                raise PersistenceConflict(
                    "persisted person-state review plan has more than one package per chapter"
                )
            if sorted(existing_keys) != sorted(plan["candidate_keys"]) or len(
                existing_keys
            ) != len(set(existing_keys)):
                raise PersistenceConflict(
                    "persisted person-state review plan no longer matches the frozen candidates"
                )
            if chapter_ids != {package["chapter_id"] for package in plan["packages"]}:
                raise PersistenceConflict(
                    "persisted person-state review plan chapter packages no longer match"
                )
            return [row[0] for row in existing]

        if not plan["packages"]:
            return []
        ordered: list[uuid.UUID] = []
        for package in plan["packages"]:
            ordered.append(
                control_plane.open_review_item(
                    conn,
                    job_id=job_id,
                    kind=REVIEW_KIND,
                    payload=_package_payload(plan, package),
                )
            )
        return ordered


# ---------------------------------------------------------------------------
# Decision normalization (pure)
# ---------------------------------------------------------------------------


def normalize_person_state_decision(
    package: dict[str, Any],
    decision: Any,
    *,
    plan_fingerprint: str,
) -> dict[str, Any]:
    """Validate a default + override decision against one frozen package.

    The default must be stated explicitly (an omitted default is never
    ``supported``); every override must name a frozen candidate, use the
    assessment vocabulary and carry a rationale; a bulk non-uncertain default
    requires a plan-level rationale. Returns the expanded per-candidate
    decisions plus the durable decision record.
    """
    decision = _require_object(decision, "person-state decision")
    default = decision.get("default_assessment")
    if default is None:
        raise PersistenceError(
            "person-state decision requires default_assessment; unreviewed candidates "
            "cannot default to supported"
        )
    if default not in ASSESSMENTS:
        raise PersistenceError(
            f"person-state default_assessment must be one of {list(ASSESSMENTS)}, got {default!r}"
        )
    rationale = decision.get("rationale", "")
    if rationale is None:
        rationale = ""
    if not isinstance(rationale, str):
        raise PersistenceError("person-state decision rationale must be a string")
    rationale = rationale.strip()
    if default != DEFAULT_ASSESSMENT and not rationale:
        raise PersistenceError(
            f"person-state default_assessment {default!r} requires a rationale"
        )

    overrides = decision.get("overrides") or []
    if not isinstance(overrides, list):
        raise PersistenceError("person-state decision overrides must be an array")
    candidates = package.get("candidates")
    if not isinstance(candidates, list):
        raise PersistenceError("person-state review package is missing its candidates")
    by_key = {candidate["candidate_key"]: candidate for candidate in candidates}
    seen: set[str] = set()
    normalized_overrides: list[dict[str, Any]] = []
    override_assessments: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(overrides):
        raw = _require_object(raw, f"person-state overrides[{index}]")
        candidate_id = raw.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in by_key:
            raise PersistenceError(
                f"person-state overrides[{index}] references unknown candidate {candidate_id!r}"
            )
        if candidate_id in seen:
            raise PersistenceConflict(
                f"person-state candidate {candidate_id} has duplicate overrides"
            )
        seen.add(candidate_id)
        assessment = raw.get("assessment")
        if assessment not in ASSESSMENTS:
            raise PersistenceError(
                f"person-state overrides[{index}] assessment must be one of "
                f"{list(ASSESSMENTS)}, got {assessment!r}"
            )
        override_rationale = raw.get("rationale")
        if not isinstance(override_rationale, str) or not override_rationale.strip():
            raise PersistenceError(
                f"person-state overrides[{index}] requires a non-empty rationale"
            )
        candidate = by_key[candidate_id]
        if candidate.get("kind") in ANCHOR_REQUIRED_KINDS and not candidate.get("anchor_ids"):
            raise PersistenceError(
                f"person-state overrides[{index}] candidate {candidate_id} has no source premise"
            )
        record = {
            "candidate_id": candidate_id,
            "assessment": assessment,
            "rationale": override_rationale.strip(),
        }
        normalized_overrides.append(record)
        override_assessments[candidate_id] = record

    decisions: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = candidate["candidate_key"]
        selected = override_assessments.get(key)
        if selected is not None:
            decisions[key] = {
                "assessment": selected["assessment"],
                "rationale": selected["rationale"],
                "override": True,
            }
        else:
            decisions[key] = {
                "assessment": default,
                "rationale": rationale,
                "override": False,
            }
    normalized_overrides.sort(key=lambda record: record["candidate_id"])
    return {
        "plan_fingerprint": plan_fingerprint,
        "default_assessment": default,
        "overrides": normalized_overrides,
        "rationale": rationale,
        "decisions": decisions,
    }


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------


def _package_by_chapter(plan: dict[str, Any], chapter_id: Any) -> dict[str, Any] | None:
    for package in plan.get("packages") or []:
        if package.get("chapter_id") == chapter_id:
            return package
    return None


def resolve_person_state_review(
    conn,
    *,
    job_id: uuid.UUID,
    review_id: uuid.UUID,
    plan: dict[str, Any],
    decision: dict[str, Any] | None = None,
    dismiss: bool = False,
) -> dict[str, Any]:
    """Validate and atomically commit one chapter package decision.

    Holds the job row lock for the whole validation/commit, then writes the
    durable decision record and the terminal review status together. A missing
    job, a review from another job, a repeated submission, a drifted plan or an
    out-of-scope candidate raises a concrete conflict and leaves the review
    untouched.
    """
    fingerprint = validate_person_state_review_plan(plan)
    if str(plan.get("job_id")) != str(job_id):
        raise PersistenceConflict("person-state review plan job mismatch")
    with conn.transaction():
        job = conn.execute(
            "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if job is None:
            raise PersistenceError(f"unknown job {job_id}")
        row = conn.execute(
            "SELECT status, payload FROM chronicle.review_items"
            " WHERE review_id = %s AND job_id = %s FOR UPDATE",
            (review_id, job_id),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown review item {review_id} for job {job_id}")
        status, raw_payload = row
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        if payload.get("scope") != REVIEW_SCOPE or payload.get("review_mode") != REVIEW_MODE:
            raise PersistenceError(
                f"review {review_id} is not a chapter_state_evidence person-state package"
            )
        if payload.get("plan_fingerprint") != fingerprint:
            raise PersistenceConflict(
                "plan_drift: person-state review was frozen against a different plan"
            )
        if status != "open":
            raise PersistenceConflict(
                f"person-state review {review_id} is already {status!r} (duplicate submission)"
            )
        package = _package_by_chapter(plan, payload.get("chapter_id"))
        if package is None or package.get("candidates") != payload.get("candidates"):
            raise PersistenceConflict(
                "plan_drift: frozen person-state package no longer matches the plan"
            )
        package = _require_object(package, "person-state package")

        if dismiss:
            record = {
                "plan_fingerprint": fingerprint,
                "default_assessment": DEFAULT_ASSESSMENT,
                "overrides": [],
                "rationale": "dismissed; the candidates stay uncertain and reviewable.",
                "dismissed": True,
                "decisions": {
                    candidate["candidate_key"]: {
                        "assessment": DEFAULT_ASSESSMENT,
                        "rationale": "dismissed; kept explicitly uncertain.",
                        "override": False,
                    }
                    for candidate in package["candidates"]
                },
            }
            terminal = "dismissed"
        else:
            if decision is None:
                raise PersistenceError("person-state resolve requires a decision or dismiss=True")
            normalized = normalize_person_state_decision(
                package, decision, plan_fingerprint=fingerprint
            )
            record = {**normalized, "dismissed": False}
            terminal = "resolved"

        stored = dict(payload)
        stored["decision"] = record
        conn.execute(
            "UPDATE chronicle.review_items SET payload = %s WHERE review_id = %s",
            (Jsonb(stored), review_id),
        )
        control_plane.resolve_review_item(conn, review_id=review_id, status=terminal)
    return record


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------


def _decision_entries(
    payload: dict[str, Any], *, status: str, package: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    if status == "dismissed":
        return {
            candidate["candidate_key"]: {
                "assessment": DEFAULT_ASSESSMENT,
                "rationale": "dismissed; kept explicitly uncertain.",
                "override": False,
            }
            for candidate in package["candidates"]
        }
    if status != "resolved":
        return {}
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        raise PersistenceConflict("resolved person-state review is missing its decision")
    decisions = decision.get("decisions")
    if not isinstance(decisions, dict):
        raise PersistenceConflict("resolved person-state review is missing its decisions")
    expected = {candidate["candidate_key"] for candidate in package["candidates"]}
    if set(decisions) != expected:
        raise PersistenceConflict(
            "resolved person-state review no longer covers its frozen candidates"
        )
    entries: dict[str, dict[str, Any]] = {}
    for key, entry in decisions.items():
        entry = _require_object(entry, f"person-state decision {key}")
        assessment = entry.get("assessment")
        if assessment not in ASSESSMENTS:
            raise PersistenceConflict(
                f"person-state decision {key} carries invalid assessment {assessment!r}"
            )
        entries[key] = {
            "assessment": assessment,
            "rationale": entry.get("rationale", "") if isinstance(entry.get("rationale"), str) else "",
            "override": bool(entry.get("override")),
        }
    return entries


def collect_person_state_assessments(
    conn,
    *,
    job_id: uuid.UUID,
    plan: dict[str, Any],
    compiler_version: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Fan every terminal package back to its candidates and persist the artifact.

    Every frozen candidate must be covered exactly once. An open package is a
    conflict; a dismissed package only ever contributes ``uncertain``. The
    immutable artifact is written through T05 atomically (a nested savepoint
    when the caller already holds T08's publish transaction).
    """
    with conn.transaction():
        return _collect_person_state_assessments(
            conn,
            job_id=job_id,
            plan=plan,
            compiler_version=compiler_version,
            persist=persist,
        )


def _collect_person_state_assessments(
    conn,
    *,
    job_id: uuid.UUID,
    plan: dict[str, Any],
    compiler_version: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    fingerprint = validate_person_state_review_plan(plan)
    if str(plan.get("job_id")) != str(job_id):
        raise PersistenceConflict("person-state review plan job mismatch")
    compiler_version = compiler_version or DEFAULT_COMPILER_VERSION
    _require_text(compiler_version, "compiler_version")
    rows = _scoped_review_rows(conn, job_id)
    open_items = [review_id for review_id, status, _payload in rows if status == "open"]
    if open_items:
        raise PersistenceConflict(
            f"person_state_review_open: {len(open_items)} person-state review(s) still open"
        )

    by_chapter = {package["chapter_id"]: package for package in plan["packages"]}
    decisions: dict[str, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    for review_id, status, payload in rows:
        chapter_id = payload.get("chapter_id")
        package = by_chapter.get(chapter_id)
        if package is None:
            raise PersistenceConflict(
                f"person-state review {review_id} references unknown chapter {chapter_id!r}"
            )
        if payload.get("plan_fingerprint") != fingerprint:
            raise PersistenceConflict(
                f"person-state review {review_id} was frozen against a different plan"
            )
        entries = _decision_entries(payload, status=status, package=package)
        for key, entry in entries.items():
            previous = decisions.get(key)
            if previous is not None:
                raise PersistenceConflict(
                    f"person-state candidate {key} was assessed more than once"
                )
            decisions[key] = entry
        decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
        audit.append(
            {
                "review_id": str(review_id),
                "chapter_id": chapter_id,
                "status": status,
                "default_assessment": decision.get("default_assessment", DEFAULT_ASSESSMENT),
                "override_count": len(decision.get("overrides") or []),
            }
        )
    if sorted(decisions) != sorted(plan["candidate_keys"]) or len(decisions) != len(
        set(decisions)
    ):
        raise PersistenceConflict(
            "person-state review decisions do not cover every frozen candidate exactly once"
        )

    decision_rows: list[dict[str, Any]] = []
    assessment_by_candidate: dict[str, str] = {}
    for package in plan["packages"]:
        for candidate in package["candidates"]:
            key = candidate["candidate_key"]
            entry = decisions[key]
            assessment_by_candidate[key] = entry["assessment"]
            decision_rows.append(
                {
                    "candidate_key": key,
                    "kind": candidate["kind"],
                    "item_ref": candidate["item_ref"],
                    "chapter_id": package["chapter_id"],
                    "revision_ref": candidate.get("revision_ref"),
                    "assessment": entry["assessment"],
                    "rationale": entry["rationale"],
                    "source_fact_refs": list(candidate.get("source_fact_refs") or []),
                }
            )
    decision_rows.sort(key=lambda row: row["candidate_key"])
    audit.sort(key=lambda row: (row["chapter_id"] or "", row["review_id"]))

    payload = {
        "schema": ASSESSMENT_SCHEMA,
        "version": ASSESSMENT_VERSION,
        "plan_fingerprint": fingerprint,
        "plan_version": REVIEW_PLAN_VERSION,
        "base_catalog_sha": plan["base_catalog_sha"],
        "revision_id": str(plan["revision_id"]),
        "compiler_version": compiler_version,
        "decisions": decision_rows,
        "assessment_by_candidate": assessment_by_candidate,
        "reviews": audit,
    }
    compiler_assessments = _compiler_assessments(plan, assessment_by_candidate)
    result: dict[str, Any] = {
        "plan_fingerprint": fingerprint,
        "payload": payload,
        "decisions": decisions,
        "assessment_by_candidate": assessment_by_candidate,
        "compiler_assessments": compiler_assessments,
        "reviews": audit,
    }
    if persist:
        assessment_sha = _store.persist_person_state_assessments(
            conn,
            {
                "plan_fingerprint": fingerprint,
                "base_catalog_sha": plan["base_catalog_sha"],
                "compiler_version": compiler_version,
                "payload": payload,
            },
        )[0]
        result["assessment_sha"] = assessment_sha
    return result


def _compiler_assessments(
    plan: dict[str, Any], assessment_by_candidate: dict[str, str]
) -> dict[str, str]:
    """Map candidate decisions onto the T04 compiler's evidence references."""
    mapping: dict[str, str] = {}
    for package in plan.get("packages") or []:
        for candidate in package.get("candidates") or []:
            if candidate.get("kind") not in COMPILER_ASSESSMENT_KINDS:
                continue
            revision_ref = candidate.get("revision_ref")
            key = candidate.get("candidate_key")
            if not isinstance(revision_ref, str) or key not in assessment_by_candidate:
                continue
            mapping[revision_ref] = assessment_by_candidate[key]
    return dict(sorted(mapping.items()))


# ---------------------------------------------------------------------------
# T04 preview
# ---------------------------------------------------------------------------


def preview_person_state_review(
    *,
    plan: dict[str, Any],
    assembly: dict[str, Any],
    decisions: dict[str, Any],
    canonical_map: dict[str, Any],
    reading_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compile the T04 projection for a proposed set of candidate decisions.

    ``decisions`` maps a ``candidate_key`` to an assessment (or a decision
    record carrying ``assessment``). The preview uses only the assembled
    evidence and the T04 compiler, so approving a start appointment can never
    mark a later phase's tenure clear. The assembly payload is re-hashed and
    must match the frozen ``assembled_hash``; a drifted assembly fails closed
    instead of silently previewing different content than the plan bound.
    """
    validate_person_state_review_plan(plan)
    person_states = assembly.get("person_states") if isinstance(assembly, dict) else None
    if not isinstance(person_states, dict):
        raise PersistenceError("person-state assembly must carry a person_states block")
    if sha256_json(person_states) != plan.get("assembled_hash"):
        raise PersistenceConflict(
            "plan_drift: assembled payload no longer matches the frozen assembled_hash"
        )
    assessment_by_candidate: dict[str, str] = {}
    for key, value in (decisions or {}).items():
        if isinstance(value, str):
            assessment = value
        elif isinstance(value, dict):
            assessment = value.get("assessment")
        else:
            assessment = None
        if assessment not in ASSESSMENTS:
            raise PersistenceError(
                f"preview decision {key!r} must carry one of {list(ASSESSMENTS)}"
            )
        assessment_by_candidate[key] = assessment
    compiler_assessments = _compiler_assessments(plan, assessment_by_candidate)
    evidence = assembly.get("person_states")
    if not isinstance(evidence, dict):
        raise PersistenceError("person-state assembly must carry a person_states block")
    return _projection.compile_person_state_projection(
        evidence, compiler_assessments, canonical_map, reading_manifest
    )


__all__ = [
    "ASSESSMENTS",
    "ASSESSMENT_SCHEMA",
    "ASSESSMENT_VERSION",
    "DEFAULT_ASSESSMENT",
    "DEFAULT_COMPILER_VERSION",
    "REVIEW_KIND",
    "REVIEW_MODE",
    "REVIEW_PLAN_SCHEMA",
    "REVIEW_PLAN_VERSION",
    "REVIEW_SCOPE",
    "build_person_state_review_plan",
    "collect_person_state_assessments",
    "normalize_person_state_decision",
    "open_person_state_reviews",
    "preview_person_state_review",
    "resolve_person_state_review",
    "validate_person_state_review_plan",
]
