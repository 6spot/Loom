"""Chronicle C1-T8 cross-source resolution, human review, and canonical publication.

Pure deterministic logic plus small durable helpers on the C1-T1
control-plane tables behind ``CHRONICLE_DATABASE_URL`` (Architecture
Amendment 0006). The durable worker path lives in
``apps/chronicle/worker/ingestion_worker.py`` (``resolve`` / ``publish``
stages).

Contract summary (GitHub Issue #497):

- A newly assembled source bundle is resolved against the *published*
  Chronicle corpus: source bundles represented by the latest canonical
  catalog. Merely staging a source bundle during another in-flight job does
  not make it canonical publication input. Candidate generation still uses
  the existing conservative C0 semantics (:mod:`resolution_v0` blocking:
  same Entity type + exact stable surface; Event time compatibility +
  participant/place overlap). No new blocking rule, no fuzzy matching, no
  model adjudication: the deterministic layer never invents
  ``same_entity`` / ``same_occurrence``.
- Initial decisions are all ``uncertain``. Architecture Amendment 0007
  materializes one durable ``ReviewItem`` per proven semantic review subject,
  while retaining every underlying candidate key/source/bundle/ref in the
  payload. Published equivalence comes only from canonical catalog membership;
  incoming equivalence comes only from proven C1-T7 same-links.
- Blocking policy: every candidate blocks. Publishing the new bundle
  as unattended singletons first and merging later is unsafe: a later
  accepted same-link across two already-published canonical UUIDs
  fails closed in publication (``PublicationConflict``) instead of
  merging. Safe continuation therefore requires the human decision
  *before* first publication whenever candidates exist. Non-blocking
  uncertainty is the complement, and it is real: a human-resolved
  ``uncertain`` (like ``not_same`` / ``related_occurrence``) flows
  into publication as non-merging evidence without further gating,
  and a job with zero candidates proceeds to publication unattended.
- Review decisions reuse the exact C0 decision vocabulary (Entity
  ``same_entity`` / ``not_same`` / ``uncertain``; Event
  ``same_occurrence`` / ``related_occurrence`` / ``not_same`` /
  ``uncertain``) and are validated here before they are recorded.
  Dismissed items are treated as ``uncertain`` at finalization: giving
  up on a review never merges identities.
- Resume is deterministic: candidate IDs, artifact bytes, review-item
  matching, and final decisions are pure functions of the inputs plus
  the recorded human decisions. Re-running a completed resolve/publish
  stage is a checkpoint/output no-op, and already-accepted extraction
  work is never re-executed (the worker skips completed stages).
- Publication reuses :mod:`publication_v0` unchanged: accepted
  same-links union representations, ``uncertain`` / ``not_same`` /
  ``related_occurrence`` never merge, negative constraints fail closed
  with ``PublicationConflict``, and an existing catalog reuses stable
  UUIDv7 identities. Only the latest catalog's published bundles plus the
  current job bundle enter a publication attempt; other in-flight staged
  bundles cannot be accidentally canonicalized as singletons.
- ``IngestionOutput`` rows link the job to the exact produced source
  bundle, resolution artifact(s), and canonical catalog/publication
  evidence by content hash.

No timestamps, UUIDs, or randomness appear in any generated resolution
artifact (human audit times live only in ``review_items`` rows). Unchanged
inputs plus unchanged recorded decisions yield byte-identical resolution JSON;
canonical publication preserves stable prior UUIDv7 identities and allocates
new UUIDv7 identities only for genuinely new canonical groups.
"""

from __future__ import annotations

import copy
import hashlib
import sys
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_INGESTION_PROTOTYPE = HERE.parent / "ingestion" / "prototype"
if str(_INGESTION_PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(_INGESTION_PROTOTYPE))

import control_plane  # noqa: E402
from common import (  # noqa: E402
    LeaseLost,
    PersistenceConflict,
    PersistenceError,
    canonical_json_bytes,
    sha256_json,
)
from psycopg.types.json import Jsonb  # noqa: E402

import assembly as chapter_assembly  # noqa: E402
import canonical_store  # noqa: E402
import chapter_plan as _chapter_plan  # noqa: E402
import chapter_store as chapter_store  # noqa: E402
import publication_v0  # noqa: E402
import reading_contract as reading_contract  # noqa: E402
import reading_projection as reading_projection  # noqa: E402
import reading_store as reading_store  # noqa: E402
import resolution_v0  # noqa: E402
import resolution_store  # noqa: E402
import review_subjects  # noqa: E402
from review_subjects import CanonicalIdentityConflict  # noqa: E402,F401
import staged_store  # noqa: E402

import person_state_projection as person_state_projection  # noqa: E402
import person_state_review as person_state_review  # noqa: E402
import person_state_store as person_state_store  # noqa: E402

#: Version of this resolve/review/publish pipeline step.
RESOLVE_PUBLISH_VERSION = "c2r1t8-v1"

#: Reused C0 resolution contract (candidates + link decisions).
RESOLUTION_VERSION = resolution_v0.RESOLUTION_VERSION

#: Chapter-path resolution-links version/scope (chapter-production §6).
RESOLUTION_V02_VERSION = resolution_v0.RESOLUTION_V02_VERSION
SCOPE_WITHIN_REVISION = resolution_v0.SCOPE_WITHIN_REVISION
SCOPE_CROSS_SOURCE = resolution_v0.SCOPE_CROSS_SOURCE

#: Frozen chapter review plan version and modes (ReviewItem kind stays
#: stage_gate, scope stays resolution; no new database kind).
REVIEW_PLAN_VERSION = review_subjects.REVIEW_PLAN_VERSION
REVIEW_MODE_CHAPTER_PAIR = review_subjects.REVIEW_MODE_CHAPTER_PAIR
REVIEW_MODE_PUBLISHED_BATCH = review_subjects.REVIEW_MODE_PUBLISHED_BATCH

#: Reused C0 canonical publication contract.
PUBLICATION_VERSION = publication_v0.PUBLICATION_VERSION

#: Control-plane artifact types recorded as ingestion outputs.
BUNDLE_ARTIFACT_TYPE = "source-bundle"
RESOLUTION_ARTIFACT_TYPE = "cross-source-resolution"
CATALOG_ARTIFACT_TYPE = "canonical-catalog"

#: Review-item scope marker for resolution candidates.
REVIEW_SCOPE = "resolution"

#: Review-item kind for resolution gates (frozen C1-T1 vocabulary; the
#: Rust control-plane contract is normative and gains no new kind).
REVIEW_KIND = "stage_gate"

#: Deterministic confidence for initial conservative decisions. Like
#: every C0 resolution confidence, it measures confidence in the link
#: decision only, never historical-truth confidence.
CONFIDENCE_INITIAL_UNCERTAIN = 0.5

#: Allowed human decisions per link kind (exact C0 vocabulary).
ENTITY_DECISIONS = ("same_entity", "not_same", "uncertain")
EVENT_DECISIONS = ("same_occurrence", "related_occurrence", "not_same", "uncertain")

_INITIAL_RATIONALE = (
    "Conservative initial decision: the candidate shares a stable "
    "surface across sources, but a shared surface alone never proves "
    "identity, so the records are kept distinct until a human reviewer "
    "decides."
)


# ---------------------------------------------------------------------------
# Bundle labels and corpus access
# ---------------------------------------------------------------------------


def new_bundle_label(revision_id: uuid.UUID | str) -> str:
    """Return the deterministic corpus label for a job's new source bundle."""
    text = str(revision_id)
    try:
        parsed = uuid.UUID(text)
    except ValueError as exc:
        raise PersistenceError(f"revision id {text!r} is not a UUID") from exc
    return f"c1rev-{parsed.hex[:12]}"


#: Fixed database key for the unified canonical-publish advisory lock.
#: Every catalog write entry takes this transaction-scoped lock, so two
#: publishers serialize on the lock instead of racing on ``imported_at``.
PUBLISH_ADVISORY_LOCK_KEY = "chronicle.catalog-publish"

#: Error code surfaced when the frozen review baseline moved under a job.
PUBLICATION_PLAN_STALE = "publication_plan_stale"


class PublicationPlanStale(PersistenceConflict):
    """The frozen review baseline moved: a newer catalog now exists.

    The old frozen plan is kept untouched and nothing is auto-passed or
    rebuilt. A follow-up job must replan; it is never a success-resume
    of the stale plan.
    """


def acquire_publish_lock(conn) -> None:
    """Take the unified publish advisory lock (transaction-scoped).

    The lock is held until the surrounding transaction commits or rolls
    back (``pg_advisory_xact_lock``), so catalog reads, candidate
    re-verification, and every public write below serialize against all
    other locked catalog writers.
    """
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (PUBLISH_ADVISORY_LOCK_KEY,),
    )


def read_latest_catalog(conn) -> dict[str, Any] | None:
    """Read the latest persisted canonical catalog payload, if any.

    The newest catalog is defined by the unique increasing
    ``publication_sequence`` identity column, never by the transaction
    start time ``imported_at``: two waiting publishers cannot misorder
    catalogs that committed while they were queued.
    """
    row = conn.execute(
        """
        SELECT payload FROM chronicle.canonical_catalogs
        ORDER BY publication_sequence DESC NULLS LAST,
                 imported_at DESC, artifact_sha256 DESC
        LIMIT 1
        """
    ).fetchone()
    return row[0] if row is not None else None


def read_latest_catalog_sha(conn) -> str | None:
    """Return the content hash of the latest catalog, if any."""
    row = conn.execute(
        """
        SELECT artifact_sha256 FROM chronicle.canonical_catalogs
        ORDER BY publication_sequence DESC NULLS LAST,
                 imported_at DESC, artifact_sha256 DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row[0]) if row is not None else None


def published_bundle_labels(catalog: dict[str, Any] | None) -> set[str]:
    """Return source-bundle labels represented by a canonical catalog.

    Canonical membership is the publication authority. A staged bundle that is
    absent from both canonical Entity and Event representation sets remains
    in-flight/unpublished and must not be pulled into another job's catalog.
    """
    if catalog is None:
        return set()
    if not isinstance(catalog, dict):
        raise PersistenceError("canonical catalog must be an object or null")
    labels: set[str] = set()
    for collection in ("canonical_entities", "canonical_events"):
        records = catalog.get(collection) or []
        if not isinstance(records, list):
            raise PersistenceError(f"canonical catalog {collection} must be an array")
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise PersistenceError(
                    f"canonical catalog {collection}[{index}] must be an object"
                )
            representations = record.get("representations") or []
            if not isinstance(representations, list):
                raise PersistenceError(
                    f"canonical catalog {collection}[{index}].representations must be an array"
                )
            for rep_index, representation in enumerate(representations):
                if not isinstance(representation, dict):
                    raise PersistenceError(
                        f"canonical catalog {collection}[{index}].representations[{rep_index}] must be an object"
                    )
                label = representation.get("bundle")
                if not isinstance(label, str) or not label:
                    raise PersistenceError(
                        f"canonical catalog {collection}[{index}].representations[{rep_index}] has no bundle label"
                    )
                labels.add(label)
    return labels


def read_all_staged_bundles(conn) -> dict[str, dict[str, Any]]:
    """Read every persisted staged source bundle, including in-flight jobs."""
    rows = conn.execute(
        "SELECT bundle_label, bundle_payload FROM chronicle.source_bundles ORDER BY bundle_label"
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def read_published_corpus_bundles(
    conn, catalog: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Read only source bundles already represented by canonical publication."""
    if catalog is None:
        catalog = read_latest_catalog(conn)
    labels = published_bundle_labels(catalog)
    if not labels:
        return {}
    rows = conn.execute(
        """
        SELECT bundle_label, bundle_payload
        FROM chronicle.source_bundles
        WHERE bundle_label = ANY(%s)
        ORDER BY bundle_label
        """,
        (sorted(labels),),
    ).fetchall()
    found = {row[0]: row[1] for row in rows}
    missing = sorted(labels - set(found))
    if missing:
        raise PersistenceError(
            "canonical catalog references missing staged source bundle(s): "
            + ", ".join(missing)
        )
    return found


def read_corpus_bundles(conn) -> dict[str, dict[str, Any]]:
    """Read the canonical-published corpus bundle set.

    Historical staging is intentionally excluded. This function is the worker's
    resolution/publication input authority; use :func:`read_all_staged_bundles`
    only for audit/debug views that explicitly need in-flight data.
    """
    return read_published_corpus_bundles(conn)


def filter_resolutions_for_bundles(
    resolutions: list[dict[str, Any]], labels: set[str]
) -> list[dict[str, Any]]:
    """Keep only resolution artifacts whose two bundles are publication inputs.

    Initial/final artifacts involving an in-flight bundle remain durable audit
    records but cannot influence a catalog that does not include that bundle.
    Malformed persisted resolution metadata fails closed rather than being
    silently ignored.
    """
    kept: list[dict[str, Any]] = []
    for index, resolution in enumerate(resolutions):
        if not isinstance(resolution, dict):
            raise PersistenceError(f"persisted resolution[{index}] must be an object")
        left = resolution.get("left_bundle")
        right = resolution.get("right_bundle")
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise PersistenceError(
                f"persisted resolution[{index}] is missing left/right bundle metadata"
            )
        left_label = left.get("label")
        right_label = right.get("label")
        if not isinstance(left_label, str) or not isinstance(right_label, str):
            raise PersistenceError(
                f"persisted resolution[{index}] has invalid left/right bundle labels"
            )
        if left_label in labels and right_label in labels:
            kept.append(resolution)
    return kept


def read_all_staged_resolutions(conn) -> list[dict[str, Any]]:
    """Read every persisted resolution artifact, including in-flight pairs."""
    rows = conn.execute(
        "SELECT payload FROM chronicle.resolution_artifacts ORDER BY artifact_sha256"
    ).fetchall()
    return [row[0] for row in rows]


def read_corpus_resolutions(conn) -> list[dict[str, Any]]:
    """Read effective resolution artifacts wholly inside the published corpus."""
    labels = published_bundle_labels(read_latest_catalog(conn))
    return filter_resolutions_for_bundles(
        resolution_store.read_effective_resolutions(conn), labels
    )


# ---------------------------------------------------------------------------
# Initial resolution (deterministic, conservative, C0-reusing)
# ---------------------------------------------------------------------------


def _bundle_ref(bundle: dict[str, Any], label: str) -> dict[str, str]:
    source = bundle.get("source")
    if not isinstance(source, dict):
        raise PersistenceError(f"bundle {label!r} is missing its source")
    ref = source.get("temp_id") or source.get("id")
    title = source.get("title")
    if not isinstance(ref, str) or not ref:
        raise PersistenceError(f"bundle {label!r} source is missing identity")
    if not isinstance(title, str) or not title:
        raise PersistenceError(f"bundle {label!r} source is missing title")
    return {"label": label, "source_ref": ref, "source_title": title}


def build_initial_resolutions(
    *,
    new_bundle: dict[str, Any],
    new_label: str,
    corpus: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build one initial resolution artifact per published corpus bundle.

    Each artifact reuses the C0 candidate blocking
    (:func:`resolution_v0.build_candidate_set`) and records every
    candidate with an ``uncertain`` decision: the deterministic layer
    adjudicates nothing. Pairs without any blocked candidate produce
    no artifact. Corpus pairs are visited in label order and every
    step is deterministic, so unchanged inputs yield byte-identical
    artifacts.
    """
    if not isinstance(new_bundle, dict):
        raise PersistenceError("new source bundle must be a JSON object")
    if not isinstance(new_label, str) or not new_label:
        raise PersistenceError("new bundle label must be a non-empty string")
    new_ref = _bundle_ref(new_bundle, new_label)
    resolutions: list[dict[str, Any]] = []
    for label in sorted(corpus):
        if label == new_label:
            continue
        bundle = corpus[label]
        if not isinstance(bundle, dict):
            raise PersistenceError(f"corpus bundle {label!r} must be a JSON object")
        candidates = resolution_v0.build_candidate_set(
            bundle, label, new_bundle, new_label
        )
        entity_candidates = candidates.get("entity_candidates") or []
        event_candidates = candidates.get("event_candidates") or []
        if not entity_candidates and not event_candidates:
            continue
        resolutions.append(
            _initial_resolution(
                candidates,
                entity_candidates,
                event_candidates,
                left_ref=_bundle_ref(bundle, label),
                right_ref=new_ref,
            )
        )
    resolutions.sort(key=lambda item: sha256_json(item))
    return resolutions


def _initial_resolution(
    candidates: dict[str, Any],
    entity_candidates: list[dict[str, Any]],
    event_candidates: list[dict[str, Any]],
    *,
    left_ref: dict[str, str],
    right_ref: dict[str, str],
) -> dict[str, Any]:
    def _link(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate["candidate_id"],
            "left": candidate["left"],
            "right": candidate["right"],
            "decision": "uncertain",
            "confidence": CONFIDENCE_INITIAL_UNCERTAIN,
            "rationale": _INITIAL_RATIONALE,
            "signals": list(candidate.get("signals") or []),
        }

    entity_links = [_link(candidate) for candidate in entity_candidates]
    event_links = [_link(candidate) for candidate in event_candidates]
    warnings = [
        {
            "type": "unresolved_resolution",
            "message": f"Resolution candidate {link['candidate_id']} remains uncertain.",
            "refs": [link["candidate_id"]],
        }
        for link in entity_links + event_links
    ]
    return {
        "schema": "chronicle.resolution-links",
        "version": RESOLUTION_VERSION,
        "left_bundle": dict(left_ref),
        "right_bundle": dict(right_ref),
        "entity_links": entity_links,
        "event_links": event_links,
        "warnings": warnings,
    }


def count_candidates(resolutions: list[dict[str, Any]]) -> dict[str, int]:
    """Count entity/event candidates across resolution artifacts."""
    entities = sum(len(item.get("entity_links") or []) for item in resolutions)
    events = sum(len(item.get("event_links") or []) for item in resolutions)
    return {"artifacts": len(resolutions), "entities": entities, "events": events}


# ---------------------------------------------------------------------------
# Chapter path: within-bundle initials + frozen mixed review plan (C2-R1-T08)
# ---------------------------------------------------------------------------


def _initial_resolution_v02(
    candidates: dict[str, Any],
    entity_candidates: list[dict[str, Any]],
    event_candidates: list[dict[str, Any]],
    *,
    left_ref: dict[str, str],
    right_ref: dict[str, str],
    scope: str,
) -> dict[str, Any]:
    """Wrap v0.2 candidates with all-uncertain initial decisions."""
    if scope not in (SCOPE_WITHIN_REVISION, SCOPE_CROSS_SOURCE):
        raise PersistenceError(f"chapter initial resolution scope {scope!r} is invalid")
    artifact = _initial_resolution(
        candidates,
        entity_candidates,
        event_candidates,
        left_ref=left_ref,
        right_ref=right_ref,
    )
    artifact["version"] = RESOLUTION_V02_VERSION
    artifact["scope"] = scope
    return artifact


def build_within_bundle_initial_resolution(
    *,
    bundle: dict[str, Any],
    bundle_label: str,
    chapter_by_ref: dict[str, str],
    chapter_index_by_id: dict[str, int],
) -> dict[str, Any] | None:
    """Build the within-bundle initial (v0.2 within_revision) artifact.

    Returns None when no cross-chapter candidate blocks. Different
    chapters sharing only a name stay ``uncertain`` here; a shared name
    alone never proves identity. Ends order on ``(chapter_index, ref)``
    via the required ``chapter_index_by_id`` (assembly plan chapters);
    a missing map fails closed.
    """
    if not isinstance(bundle, dict):
        raise PersistenceError("assembled source bundle must be a JSON object")
    if not isinstance(bundle_label, str) or not bundle_label:
        raise PersistenceError("assembled bundle label must be a non-empty string")
    if not isinstance(chapter_by_ref, dict) or not chapter_by_ref:
        raise PersistenceError("chapter_by_ref must be a non-empty mapping")
    if not isinstance(chapter_index_by_id, dict) or not chapter_index_by_id:
        raise PersistenceError(
            "chapter_index_by_id is required: pass the assembly "
            "plan chapter order instead of sorting by ref"
        )
    candidates = resolution_v0.build_within_bundle_candidate_set(
        bundle,
        bundle_label,
        chapter_by_ref,
        chapter_index_by_id,
    )
    entity_candidates = candidates.get("entity_candidates") or []
    event_candidates = candidates.get("event_candidates") or []
    if not entity_candidates and not event_candidates:
        return None
    ref = _bundle_ref(bundle, bundle_label)
    return _initial_resolution_v02(
        candidates,
        entity_candidates,
        event_candidates,
        left_ref=dict(ref),
        right_ref=dict(ref),
        scope=SCOPE_WITHIN_REVISION,
    )


def build_chapter_cross_initial_resolutions(
    *,
    new_bundle: dict[str, Any],
    new_label: str,
    corpus: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build v0.2 cross_source initials against the published corpus."""
    if not isinstance(new_bundle, dict):
        raise PersistenceError("new source bundle must be a JSON object")
    if not isinstance(new_label, str) or not new_label:
        raise PersistenceError("new bundle label must be a non-empty string")
    new_ref = _bundle_ref(new_bundle, new_label)
    resolutions: list[dict[str, Any]] = []
    for label in sorted(corpus):
        if label == new_label:
            continue
        bundle = corpus[label]
        if not isinstance(bundle, dict):
            raise PersistenceError(f"corpus bundle {label!r} must be a JSON object")
        candidates = resolution_v0.build_cross_source_candidate_set_v02(
            bundle, label, new_bundle, new_label
        )
        entity_candidates = candidates.get("entity_candidates") or []
        event_candidates = candidates.get("event_candidates") or []
        if not entity_candidates and not event_candidates:
            continue
        resolutions.append(
            _initial_resolution_v02(
                candidates,
                entity_candidates,
                event_candidates,
                left_ref=_bundle_ref(bundle, label),
                right_ref=new_ref,
                scope=SCOPE_CROSS_SOURCE,
            )
        )
    resolutions.sort(key=lambda item: sha256_json(item))
    return resolutions


def build_chapter_initial_resolutions(
    *,
    bundle: dict[str, Any],
    bundle_label: str,
    chapter_by_ref: dict[str, str],
    chapter_index_by_id: dict[str, int],
    corpus: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build all chapter initials: within-bundle plus published-corpus pairs."""
    resolutions: list[dict[str, Any]] = []
    within = build_within_bundle_initial_resolution(
        bundle=bundle,
        bundle_label=bundle_label,
        chapter_by_ref=chapter_by_ref,
        chapter_index_by_id=chapter_index_by_id,
    )
    if within is not None:
        resolutions.append(within)
    resolutions.extend(
        build_chapter_cross_initial_resolutions(
            new_bundle=bundle, new_label=bundle_label, corpus=dict(corpus or {})
        )
    )
    resolutions.sort(key=lambda item: sha256_json(item))
    return resolutions


def persist_chapter_initial_resolutions(conn, resolutions: list[dict[str, Any]]) -> list[str]:
    """Validate the v0.2 envelope and persist chapter initial artifacts."""
    if not isinstance(resolutions, list):
        raise PersistenceError("chapter initial resolutions must be an array")
    shas: list[str] = []
    for resolution in resolutions:
        if not isinstance(resolution, dict):
            raise PersistenceError("chapter initial resolution must be an object")
        if resolution.get("version") != RESOLUTION_V02_VERSION:
            raise PersistenceError(
                "chapter initials must be chronicle.resolution-links/0.2 "
                "(refusing to downgrade to 0.1)"
            )
        scope = resolution.get("scope")
        if scope not in (SCOPE_WITHIN_REVISION, SCOPE_CROSS_SOURCE):
            raise PersistenceError(
                f"chapter initial resolution scope {scope!r} is invalid"
            )
        sha, _ = resolution_store.persist_resolution(conn, resolution)
        if sha256_json(resolution) != sha:
            raise PersistenceError("chapter initial resolution hash drifted")
        shas.append(sha)
    return sorted(shas)


def create_chapter_review_plan(
    *,
    job_id: uuid.UUID,
    revision_id: uuid.UUID,
    assembled_bundle_sha256: str,
    base_catalog_sha256: str,
    initial_resolutions: list[dict[str, Any]],
    catalog: dict[str, Any] | None,
    within_book_links: dict[str, Any] | None = None,
    chapter_by_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create the frozen mixed review plan (chapter_pair + published_batch)."""
    return review_subjects.build_chapter_review_plan(
        job_id=job_id,
        revision_id=revision_id,
        assembled_bundle_sha256=assembled_bundle_sha256,
        base_catalog_sha256=base_catalog_sha256,
        resolutions=initial_resolutions,
        catalog=catalog,
        within_book_links=within_book_links,
        chapter_by_ref=chapter_by_ref,
    )


def validate_chapter_review_plan(
    plan: dict[str, Any],
    initial_resolutions: list[dict[str, Any]],
    *,
    job_id: uuid.UUID,
    revision_id: uuid.UUID,
    assembled_bundle_sha256: str,
    base_catalog_sha256: str,
) -> str:
    """Revalidate a frozen plan exactly without re-materializing it."""
    return review_subjects.validate_chapter_review_plan(
        plan,
        initial_resolutions,
        job_id=job_id,
        revision_id=revision_id,
        assembled_bundle_sha256=assembled_bundle_sha256,
        base_catalog_sha256=base_catalog_sha256,
    )


def open_chapter_reviews(
    conn,
    *,
    job_id: uuid.UUID,
    plan: dict[str, Any],
    initial_resolutions: list[dict[str, Any]],
    revision_id: uuid.UUID,
    assembled_bundle_sha256: str,
    base_catalog_sha256: str,
) -> list[uuid.UUID]:
    """Open/adopt one ReviewItem per frozen chapter plan unit.

    Fully revalidates the frozen plan against the frozen initials
    before any database read; an empty plan returns ``[]``.
    """
    return review_subjects.open_chapter_review_plan(
        conn,
        job_id=job_id,
        plan=plan,
        initial_resolutions=initial_resolutions,
        revision_id=revision_id,
        assembled_bundle_sha256=assembled_bundle_sha256,
        base_catalog_sha256=base_catalog_sha256,
    )


def collect_chapter_decisions(
    conn, *, job_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    """Collect terminal chapter reviews fanned out to C0 candidate keys."""
    return review_subjects.collect_review_subject_decisions(conn, job_id=job_id)


def build_final_chapter_resolutions(
    initial: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    *,
    require_complete: bool = True,
) -> list[dict[str, Any]]:
    """Apply durable chapter decisions (v0.2 scope preserved, no downgrade)."""
    for artifact in initial:
        if not isinstance(artifact, dict):
            raise PersistenceError("chapter initial resolution must be an object")
        if artifact.get("version") != RESOLUTION_V02_VERSION:
            raise PersistenceError(
                "chapter finals must stay chronicle.resolution-links/0.2"
            )
        if artifact.get("scope") not in (SCOPE_WITHIN_REVISION, SCOPE_CROSS_SOURCE):
            raise PersistenceError("chapter final resolution scope is invalid")
    final = build_final_resolutions(initial, decisions, require_complete=require_complete)
    for artifact in final:
        if artifact.get("version") != RESOLUTION_V02_VERSION:
            raise PersistenceError("chapter final downgraded below 0.2 (fail closed)")
    return final


# ---------------------------------------------------------------------------
# Review items (durable, auditable, job-scoped)
# ---------------------------------------------------------------------------


def _candidate_key(resolution_sha: str, candidate_id: str) -> str:
    return f"{resolution_sha}:{candidate_id}"


def review_payload(
    *,
    resolution_sha: str,
    candidate: dict[str, Any],
    link_kind: str,
) -> dict[str, Any]:
    """Build the durable payload for one resolution review item."""
    if link_kind not in ("entity", "event"):
        raise PersistenceError(f"unknown resolution link kind {link_kind!r}")
    left, right = candidate.get("left"), candidate.get("right")
    for side in (left, right):
        if not isinstance(side, dict) or not side.get("bundle") or not side.get("ref"):
            raise PersistenceError(
                "resolution candidate is missing bundle/ref provenance"
            )
    return {
        "scope": REVIEW_SCOPE,
        "link_kind": link_kind,
        "candidate_id": candidate.get("candidate_id"),
        "resolution_sha256": resolution_sha,
        "left": {"bundle": left["bundle"], "ref": left["ref"]},
        "right": {"bundle": right["bundle"], "ref": right["ref"]},
        "signals": list(candidate.get("signals") or []),
        "initial_decision": candidate.get("decision"),
        "blocking": True,
        "allowed_decisions": list(
            ENTITY_DECISIONS if link_kind == "entity" else EVENT_DECISIONS
        ),
        "decision": None,
    }


def open_resolution_reviews(
    conn, *, job_id: uuid.UUID, resolutions: list[dict[str, Any]]
) -> list[uuid.UUID]:
    """Open/adopt Amendment-0007 semantic review subjects.

    Fresh jobs collapse only equivalence already proven by canonical catalog
    membership / C1-T7 same-links. Pre-amendment jobs keep their frozen legacy
    candidate plan. Final C0 candidate links are restored by deterministic
    decision fan-out.
    """
    return review_subjects.open_review_subjects(
        conn, job_id=job_id, resolutions=resolutions
    )


def _require_decision(link_kind: str, decision: Any) -> str:
    allowed = ENTITY_DECISIONS if link_kind == "entity" else EVENT_DECISIONS
    if decision not in allowed:
        raise PersistenceError(
            f"resolution {link_kind} decision must be one of {list(allowed)}, "
            f"got {decision!r}"
        )
    return str(decision)


def resolve_resolution_review(
    conn,
    *,
    review_id: uuid.UUID,
    decision: str,
    rationale: str,
    confidence: float = CONFIDENCE_INITIAL_UNCERTAIN,
    group_decisions: list[dict[str, Any]] | None = None,
) -> None:
    """Record a human decision on one resolution review item.

    Validates the exact C0 decision vocabulary for the item's link
    kind, stores the decision durably in the item payload, then marks
    the item resolved through the standard control-plane transition
    (open items only; resolved history stays auditable). Raises
    :class:`PersistenceError` for any vocabulary violation and
    :class:`PersistenceConflict` when the item is not open, or
    :class:`CanonicalIdentityConflict` when Entity same-links would join
    existing canonical IDs. Validation and resolution are one atomic write.
    """
    # Serialize decisions for one job before reading its effective graph. The
    # row lock also prevents a concurrent submission from rewriting this item
    # after another request resolves it. No model/network work occurs here.
    with conn.transaction():
        owner = conn.execute(
            """
            SELECT job_id FROM chronicle.ingestion_jobs
            WHERE job_id = (SELECT job_id FROM chronicle.review_items WHERE review_id = %s)
            FOR UPDATE
            """,
            (review_id,),
        ).fetchone()
        if owner is None:
            raise PersistenceError(f"unknown review item {review_id}")
        row = conn.execute(
            "SELECT status, payload FROM chronicle.review_items WHERE review_id = %s FOR UPDATE",
            (review_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown review item {review_id}")
        status, payload = row[0], row[1] if isinstance(row[1], dict) else {}
        if status != "open":
            raise PersistenceConflict(
                f"review item {review_id} is already {status!r}"
            )
        if payload.get("scope") != REVIEW_SCOPE:
            raise PersistenceError(
                f"review item {review_id} is not a resolution review "
                f"(scope {payload.get('scope')!r})"
            )
        link_kind = payload.get("link_kind")
        decision = _require_decision(str(link_kind), decision)
        if not isinstance(rationale, str) or not rationale.strip():
            raise PersistenceError("resolution review rationale must be non-empty")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise PersistenceError("resolution review confidence must be within [0, 1]")
        decided = dict(payload)
        decided["decision"] = {
            "decision": decision,
            "confidence": float(confidence),
            "rationale": rationale.strip(),
        }
        normalized_group_decisions = review_subjects.normalize_group_decisions(
            payload, group_decisions
        )
        if normalized_group_decisions:
            decided["decision"]["group_decisions"] = normalized_group_decisions
        review_subjects.validate_proposed_entity_review(
            conn, job_id=owner[0], review_id=review_id, payload=decided
        )
        conn.execute(
            "UPDATE chronicle.review_items SET payload = %s WHERE review_id = %s",
            (Jsonb(decided), review_id),
        )
        control_plane.resolve_review_item(conn, review_id=review_id, status="resolved")


def collect_review_decisions(
    conn, *, job_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    """Collect terminal reviews and fan subject decisions to C0 candidates."""
    return review_subjects.collect_review_subject_decisions(conn, job_id=job_id)


def open_resolution_review_count(conn, *, job_id: uuid.UUID) -> int:
    """Count still-open resolution review items for a job."""
    rows = conn.execute(
        """
        SELECT count(*) FROM chronicle.review_items
        WHERE job_id = %s AND status = 'open' AND payload->>'scope' = %s
        """,
        (job_id, REVIEW_SCOPE),
    ).fetchone()
    return int(rows[0])


# ---------------------------------------------------------------------------
# Final resolution from recorded decisions
# ---------------------------------------------------------------------------


def build_final_resolutions(
    initial: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    *,
    require_complete: bool = True,
) -> list[dict[str, Any]]:
    """Apply durable review decisions to initial artifacts deterministically."""
    final: list[dict[str, Any]] = []
    for artifact in initial:
        resolution_sha = initial_artifact_sha(artifact)
        updated = copy.deepcopy(artifact)
        updated_warnings: list[dict[str, Any]] = []
        for field, link_kind in (("entity_links", "entity"), ("event_links", "event")):
            for link in updated.get(field) or []:
                candidate_id = link.get("candidate_id")
                key = _candidate_key(resolution_sha, str(candidate_id))
                decision = decisions.get(key)
                if decision is None:
                    if require_complete:
                        raise PersistenceError(
                            f"resolution candidate {candidate_id!r} in {resolution_sha} "
                            "has no recorded human decision"
                        )
                    updated_warnings.append(
                        {
                            "type": "unresolved_resolution",
                            "message": f"Resolution candidate {candidate_id} remains uncertain.",
                            "refs": [str(candidate_id)],
                        }
                    )
                    continue
                link["decision"] = _require_decision(
                    link_kind, decision.get("decision")
                )
                link["confidence"] = float(decision["confidence"])
                link["rationale"] = str(decision["rationale"])
                if link["decision"] == "uncertain":
                    updated_warnings.append(
                        {
                            "type": "unresolved_resolution",
                            "message": f"Resolution candidate {candidate_id} remains uncertain.",
                            "refs": [str(candidate_id)],
                        }
                    )
        updated["warnings"] = updated_warnings
        final.append(updated)
    final.sort(key=sha256_json)
    return final


def initial_artifact_sha(artifact: dict[str, Any]) -> str:
    """Return the content address for an initial resolution artifact."""
    return sha256_json(artifact)


# ---------------------------------------------------------------------------
# Publication bridge (C0 semantics unchanged)
# ---------------------------------------------------------------------------


def publish_with_decisions(
    *,
    bundles: dict[str, dict[str, Any]],
    resolutions: list[dict[str, Any]],
    existing_catalog: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Publish through C0 canonical semantics and return catalog + audit report."""
    try:
        catalog = publication_v0.publish_catalog(
            bundles, resolutions, existing_catalog=existing_catalog
        )
    except publication_v0.PublicationConflict:
        raise
    except publication_v0.PublicationV0Error as exc:
        raise PersistenceError(f"canonical publication input is invalid: {exc}") from exc
    return catalog, publication_report(catalog, resolutions)


def publication_report(
    catalog: dict[str, Any], resolutions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a small deterministic report (no copied source truth)."""
    decisions = {
        "entities": {},
        "events": {},
    }
    for resolution in resolutions:
        for field, destination in (("entity_links", "entities"), ("event_links", "events")):
            for link in resolution.get(field) or []:
                decision = str(link.get("decision"))
                decisions[destination][decision] = decisions[destination].get(decision, 0) + 1
    return {
        "schema": "chronicle.publication-report",
        "version": "0.1",
        "publication_version": PUBLICATION_VERSION,
        "counts": {
            "canonical_entities": len(catalog.get("canonical_entities") or []),
            "canonical_events": len(catalog.get("canonical_events") or []),
            "event_relations": len(catalog.get("event_relations") or []),
        },
        "decisions": decisions,
        "catalog_sha256": sha256_json(catalog),
    }


# ---------------------------------------------------------------------------
# Atomic chapter publication (C2-R1-T13): catalog + publications in one txn
# ---------------------------------------------------------------------------


def build_chapter_publication(
    *,
    artifact_entry: dict[str, Any],
    catalog_sha256: str,
    assembled_bundle_sha256: str,
    translation_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the immutable public reading payload for one accepted chapter.

    The payload carries the complete ordered translation blocks plus the
    already-remapped references, source anchors, and unresolved mentions
    from the accepted artifact. It never substitutes a summary or a
    person/event blurb for the full text; ``present`` re-checks exactly
    this before serving.

    For a 0.2 reading book the caller passes the revision-assembled
    ``translation_blocks`` (``block_id`` remapped to the revision namespace)
    so the reading units, whose block IDs are the same remapped IDs, resolve
    their body in this very publication. A 0.1 publication keeps the frozen
    chapter-local candidate blocks.
    """
    artifact = artifact_entry.get("artifact")
    if not isinstance(artifact, dict):
        raise PersistenceError("accepted chapter entry carries no artifact")
    candidate = artifact.get("candidate")
    if not isinstance(candidate, dict):
        raise PersistenceError("accepted chapter artifact carries no candidate")
    if translation_blocks is not None:
        if not isinstance(translation_blocks, list) or not translation_blocks:
            raise PersistenceError(
                f"chapter {artifact_entry.get('chapter_id')!r} has no "
                "assembled translation blocks; refusing to publish a partial"
            )
        ordered = [dict(block) for block in translation_blocks]
    else:
        translation = candidate.get("translation") or {}
        blocks = translation.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise PersistenceError(
                f"chapter {artifact_entry.get('chapter_id')!r} candidate carries "
                "no complete translation blocks; refusing to publish a partial"
            )
        ordered = sorted(
            blocks,
            key=lambda block: (
                block.get("chapter_index", artifact_entry.get("chapter_index", 0)),
                str(block.get("block_id")),
            ),
        )
    return {
        "schema": "chronicle.chapter-publication",
        "version": "0.1",
        "chapter_id": artifact_entry.get("chapter_id"),
        "chapter_index": artifact_entry.get("chapter_index"),
        "revision_id": artifact.get("revision_id"),
        "artifact_sha256": artifact_entry.get("artifact_sha256"),
        "catalog_sha256": catalog_sha256,
        "assembled_bundle_sha256": assembled_bundle_sha256,
        "translation_blocks": ordered,
        "mentions": list(candidate.get("mentions") or []),
        "record_sources": list(candidate.get("record_sources") or []),
        "anchors": list(artifact.get("anchors") or []),
    }


#: Accepted chapter artifact generation that carries reading annotations.
READING_ARTIFACT_VERSION = reading_contract.ARTIFACT_VERSION

#: Accepted chapter artifact generation that additionally carries the 0.3
#: ``person_states`` block (C2-R3-T01/T02; T08 publishes it).
PERSON_STATE_ARTIFACT_VERSION = "0.3"

#: Chapter artifact generations the atomic chapter publish accepts.
CHAPTER_ARTIFACT_VERSIONS = (
    chapter_store.ARTIFACT_VERSION,
    READING_ARTIFACT_VERSION,
    PERSON_STATE_ARTIFACT_VERSION,
)

#: Control-plane output type for the frozen person-state review plan. Kept
#: distinct from the chapter review plan so resolve reuses the exact frozen
#: plan on resume instead of rebuilding one.
PERSON_STATE_PLAN_OUTPUT_TYPE = "person-state-review-plan"

#: Review-item scope marker for a frozen chapter-state-evidence package
#: (mirrors :mod:`person_state_review`).
PERSON_STATE_REVIEW_SCOPE = "person_state"


def reading_stream_seed(revision_id: uuid.UUID | str) -> str:
    """Return the deterministic RFC 9562 UUIDv7 stream identity for a revision.

    The compiled projection binds every unit, group and the manifest to one
    ``stream_id``, so the identity must be a valid UUID and stable across a
    retry of the same revision. Deriving it deterministically from the
    revision id makes recompiling and republishing the same revision
    byte-identical, so :func:`reading_store.persist_reading_stream` reuses the
    exact same stream and units instead of raising an immutability conflict.
    """
    digest = hashlib.sha256(
        f"chronicle.reading-stream:{str(revision_id)}".encode("utf-8")
    ).digest()
    value = int.from_bytes(digest[:16], "big")
    value &= ~(0xF << 76)
    value |= 0x7 << 76
    value &= ~(0b11 << 62)
    value |= 0b10 << 62
    return str(uuid.UUID(int=value))


def require_unexpired_lease(conn, *, job_id: uuid.UUID, worker: str) -> None:
    """Lease fence on the live wall clock, re-asserting ownership.

    ``control_plane.require_job_lease`` checks the owner only (expiry is
    ignored by contract), and PostgreSQL ``now()`` is fixed at transaction
    start, so an expensive assemble/reading compile inside the publish
    transaction could outlive the lease while both the initial check and the
    later fenced writes still pass. This helper re-checks the owner and the
    expiry with ``clock_timestamp()``, so a lease that expires during the
    transaction (or is taken over) fails closed before any further public
    write or the commit.
    """
    control_plane.require_job_lease(conn, job_id=job_id, worker=worker)
    lease_row = conn.execute(
        "SELECT lease_expires_at FROM chronicle.ingestion_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    if lease_row is None or lease_row[0] is None or lease_row[0] <= now:
        raise LeaseLost(
            f"worker {worker!r} holds no unexpired lease for job {job_id}; "
            "refusing to publish after a long assemble/compile (renew and "
            "re-enter instead of committing on a stale lease)"
        )


def require_chapter_plan_binding(
    *,
    chapter_plan: dict[str, Any],
    assembled_payload: dict[str, Any],
    assembled_sha256: str,
    job_id: uuid.UUID,
) -> None:
    """Bind the published chapter plan to the persisted T03/assembled record.

    The reading manifest must never carry caller-supplied bytes that differ
    from what was assembled and accepted. The persisted
    ``assembled-source-bundle`` output records the T03 ``plan_sha256``, the
    exact revision binding and plan geometry, plus the assembled bundle hash.
    The binding recomputes the canonical T03 plan hash over the caller's
    complete plan (including every chapter's ``blocks`` and
    ``required_block_ids``) and requires it to match the plan's own declared
    hash and the persisted hash, so any covered-field drift (a rewritten
    ``normalized_sha256``, a chapter block ``content_sha256``, a block range,
    ...) is rejected before a single reading row is written even when the
    supplied ``plan_sha256`` string is left untouched.
    """
    if not isinstance(chapter_plan, dict) or not chapter_plan:
        raise PersistenceError(
            f"job {job_id} has no chapter plan to bind to the assembled output"
        )
    if not isinstance(assembled_payload, dict):
        raise PersistenceError(
            f"job {job_id} assembled output payload must be an object"
        )
    recorded_bundle_sha = assembled_payload.get("bundle_sha256")
    if recorded_bundle_sha is not None and recorded_bundle_sha != assembled_sha256:
        raise PersistenceError(
            f"job {job_id} assembled output records bundle "
            f"{recorded_bundle_sha!r} but carries {assembled_sha256!r}; "
            "refusing to publish drifted evidence"
        )
    report = assembled_payload.get("report")
    if not isinstance(report, dict):
        raise PersistenceError(
            f"job {job_id} assembled output carries no report; refusing to "
            "publish unverifiable reading metadata"
        )
    revision = report.get("revision")
    if not isinstance(revision, dict):
        raise PersistenceError(
            f"job {job_id} assembled report carries no revision binding"
        )
    for key in ("revision_id", "source_sha256", "normalized_sha256"):
        if str(chapter_plan.get(key)) != str(revision.get(key)):
            raise PersistenceError(
                f"chapter plan {key} drift: supplied "
                f"{chapter_plan.get(key)!r} but persisted revision records "
                f"{revision.get(key)!r}; refusing to publish"
            )
    recorded_plan = report.get("plan")
    if not isinstance(recorded_plan, dict):
        raise PersistenceError(
            f"job {job_id} assembled report carries no plan binding"
        )
    # The plan hash is the integrity authority: recompute the T03 canonical
    # hash over the caller's complete plan (version, revision binding and the
    # full chapters array including each chapter's blocks) and require it to
    # match both the plan's own declared hash and the persisted plan hash. A
    # tampered covered field (e.g. a chapter block content_sha256 or block
    # range) changes the recomputation even when the supplied plan_sha256
    # string is left in place.
    recomputed_plan_sha = _chapter_plan.plan_sha256_for(chapter_plan)
    if recomputed_plan_sha != chapter_plan.get("plan_sha256"):
        raise PersistenceError(
            f"job {job_id} chapter plan content does not match its own "
            f"plan_sha256 (recomputed {recomputed_plan_sha!r}, declared "
            f"{chapter_plan.get('plan_sha256')!r}); refusing to publish a "
            "tampered plan"
        )
    if recomputed_plan_sha != recorded_plan.get("plan_sha256"):
        raise PersistenceError(
            f"job {job_id} chapter plan plan_sha256 drift: recomputed "
            f"{recomputed_plan_sha!r} but persisted records "
            f"{recorded_plan.get('plan_sha256')!r}; refusing to publish"
        )
    if chapter_plan.get("version") != chapter_assembly.CHAPTER_PLAN_VERSION:
        raise PersistenceError(
            f"chapter plan version {chapter_plan.get('version')!r} is not "
            f"{chapter_assembly.CHAPTER_PLAN_VERSION!r}"
        )

    def _geometry(chapters: Any) -> dict[str, tuple[Any, ...]]:
        result: dict[str, tuple[Any, ...]] = {}
        for chapter in chapters or []:
            if not isinstance(chapter, dict):
                raise PersistenceError("chapter plan chapter must be an object")
            chapter_id = chapter.get("chapter_id")
            if not isinstance(chapter_id, str) or not chapter_id:
                raise PersistenceError("chapter plan chapter requires chapter_id")
            result[chapter_id] = (
                chapter.get("chapter_index"),
                chapter.get("title"),
                chapter.get("start"),
                chapter.get("end"),
            )
        return result

    if _geometry(chapter_plan.get("chapters")) != _geometry(
        recorded_plan.get("chapters")
    ):
        raise PersistenceError(
            f"job {job_id} chapter plan geometry (chapter_id/index/title/"
            "start/end) drifts from the persisted assembled plan; refusing "
            "to publish"
        )


def _ordered_chapter_publications(
    projection: dict[str, Any], publication_by_chapter: dict[str, Any]
) -> list[str]:
    """Return the stream's chapter publications in compiled reading order."""
    ordered: list[str] = []
    for chapter in projection.get("chapter_publications") or []:
        chapter_id = chapter.get("chapter_id")
        publication_id = publication_by_chapter.get(chapter_id)
        if not isinstance(publication_id, str) or not publication_id:
            raise PersistenceError(
                f"reading projection has no chapter publication for {chapter_id!r}"
            )
        if publication_id not in ordered:
            ordered.append(publication_id)
    if not ordered:
        raise PersistenceError("reading projection carries no chapter publications")
    return ordered


def build_reading_stream_payload(
    *,
    projection: dict[str, Any],
    catalog: dict[str, Any],
    revision_id: uuid.UUID,
    document_id: uuid.UUID,
    chapter_publication_ids: list[str],
    artifact_sha256_by_chapter: dict[str, str],
    bundle_label: str,
) -> dict[str, Any]:
    """Adapt the T04 compiled projection into the T05 store's stream input.

    The store consumes a flattened occurrence shape (``event_kind`` +
    ``bundle_label``/``record_ref``), explicit group unit ranges, and the
    accepted-artifact key each unit's publication was written under. A 0.2
    artifact's embedded ``artifact_sha256`` is its reading-excluded core hash
    (the identity unit IDs were derived from), while ``chapter_artifacts`` /
    ``chapter_publications`` key the whole accepted product; the reading index
    references the latter. This adapter performs only that pure translation;
    it never re-derives text, spans, narrative time or canonical identity,
    and any inconsistency fails closed before the caller writes a single
    reading row.
    """
    if not isinstance(projection, dict):
        raise PersistenceError("reading projection must be a JSON object")
    canonical = reading_projection.build_canonical_ref_map(
        catalog, bundle_label=bundle_label
    )
    event_ids = canonical["events"]

    raw_units = projection.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        raise PersistenceError("reading projection carries no units")
    units: list[dict[str, Any]] = []
    for index, unit in enumerate(raw_units):
        if not isinstance(unit, dict):
            raise PersistenceError(f"reading projection unit[{index}] must be an object")
        chapter_id = unit["chapter_id"]
        artifact_sha256 = artifact_sha256_by_chapter.get(chapter_id)
        if not isinstance(artifact_sha256, str) or not artifact_sha256:
            raise PersistenceError(
                f"reading projection unit[{index}] chapter {chapter_id!r} has no "
                "accepted artifact key"
            )
        units.append(
            {
                "ordinal": unit["ordinal"],
                "unit_id": unit["unit_id"],
                "publication_id": unit["publication_id"],
                "artifact_sha256": artifact_sha256,
                "chapter_id": chapter_id,
                "block_id": unit["block_id"],
                "text_hash": unit["text_hash"],
                "group_id": unit["group_id"],
                "narrative_time": unit["narrative_time"],
                "segments": unit["segments"],
                "context_entities": unit["context_entities"],
                "source_anchor_ids": unit["source_anchor_ids"],
                "continues_previous": unit["continues_previous"],
            }
        )

    raw_groups = projection.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise PersistenceError("reading projection carries no time groups")
    groups: list[dict[str, Any]] = []
    cursor = 0
    for index, group in enumerate(raw_groups):
        if not isinstance(group, dict):
            raise PersistenceError(f"reading projection group[{index}] must be an object")
        count = group.get("unit_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise PersistenceError(
                f"reading projection group[{index}] must carry a positive unit_count"
            )
        covered = units[cursor : cursor + count]
        if len(covered) != count:
            raise PersistenceError(
                "reading projection groups do not partition the compiled units"
            )
        groups.append(
            {
                "ordinal": group["ordinal"],
                "group_id": group["group_id"],
                "first_unit_ordinal": covered[0]["ordinal"],
                "last_unit_ordinal": covered[-1]["ordinal"],
                "first_unit_id": covered[0]["unit_id"],
                "last_unit_id": covered[-1]["unit_id"],
                "unit_count": count,
                "year_key": group["year_key"],
                "period_key": group["period_key"],
                "year_label": group.get("year_label"),
                "period_label": group["period_label"],
                "precision": group["precision"],
                "observations": list(group.get("observations") or []),
                "continues_previous": bool(group.get("continues_previous")),
            }
        )
        cursor += count
    if cursor != len(units):
        raise PersistenceError(
            "reading projection groups do not cover every compiled unit"
        )

    occurrences: list[dict[str, Any]] = []
    for unit in units:
        covered_refs: set[str] = set()
        for segment in unit["segments"]:
            if not isinstance(segment, dict) or segment.get("kind") != "event":
                continue
            span = segment.get("span") or {}
            target_ref = span.get("target_ref")
            canonical_id = span.get("target_event_id")
            if not isinstance(target_ref, str) or not isinstance(canonical_id, str):
                # unresolved/ambiguous spans have no canonical target and are
                # deliberately absent from the reverse index.
                continue
            relation = span.get("relation")
            if relation not in reading_contract.SPAN_RELATIONS:
                raise PersistenceError(
                    f"reading span {span.get('span_id')!r} has invalid relation {relation!r}"
                )
            covered_refs.add(target_ref)
            occurrences.append(
                {
                    "unit_id": unit["unit_id"],
                    "event_kind": "span",
                    "span_id": span.get("span_id"),
                    "canonical_event_id": canonical_id,
                    "relation": relation,
                    "bundle_label": bundle_label,
                    "record_ref": target_ref,
                }
            )
        for event_ref in unit["narrative_time"].get("event_refs") or []:
            if event_ref in covered_refs:
                continue
            canonical_id = event_ids.get(event_ref)
            if not isinstance(canonical_id, str):
                continue
            occurrences.append(
                {
                    "unit_id": unit["unit_id"],
                    "event_kind": "current",
                    "span_id": None,
                    "canonical_event_id": canonical_id,
                    "relation": "current",
                    "bundle_label": bundle_label,
                    "record_ref": event_ref,
                }
            )

    return {
        "stream_id": reading_stream_seed(revision_id),
        "revision_id": revision_id,
        "document_id": document_id,
        "origin_catalog_sha": sha256_json(catalog),
        "manifest": projection["manifest"],
        "chapter_publication_ids": list(chapter_publication_ids),
        "units": units,
        "groups": groups,
        "event_occurrences": occurrences,
    }


# ---------------------------------------------------------------------------
# C2-R3-T08 person-state review wiring + atomic state publication
# ---------------------------------------------------------------------------


def read_person_state_plan_output(conn, *, job_id: uuid.UUID) -> dict[str, Any] | None:
    """Return the frozen person-state review plan recorded by resolve, if any."""
    row = conn.execute(
        """
        SELECT payload FROM chronicle.ingestion_outputs
        WHERE job_id = %s AND artifact_type = %s
        ORDER BY created_at DESC LIMIT 1
        """,
        (job_id, PERSON_STATE_PLAN_OUTPUT_TYPE),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        return None
    return row[0]


def open_person_state_review_count(conn, *, job_id: uuid.UUID) -> int:
    """Count open ``person_state`` review packages for a job."""
    return int(
        conn.execute(
            """
            SELECT count(*) FROM chronicle.review_items
            WHERE job_id = %s AND payload->>'scope' = %s AND status = 'open'
            """,
            (job_id, PERSON_STATE_REVIEW_SCOPE),
        ).fetchone()[0]
    )


def build_person_state_plan(
    *,
    job_id: uuid.UUID,
    revision_id: uuid.UUID,
    accepted_artifacts: list[dict[str, Any]],
    assembly: dict[str, Any],
    final_resolutions: list[dict[str, Any]],
    base_catalog_sha256: str,
) -> dict[str, Any]:
    """Freeze the person-state review plan over the accepted 0.3 evidence.

    Wraps :func:`person_state_review.build_person_state_review_plan` with the
    revision-level bindings the chapter pipeline already owns (final identity
    Resolution hashes and the frozen base catalog), so resolve never rebuilds
    or re-ranks the plan on resume.
    """
    if not isinstance(base_catalog_sha256, str) or not base_catalog_sha256:
        raise PersistenceError(
            f"job {job_id} has no frozen base catalog for the person-state plan"
        )
    resolution_hashes = sorted(sha256_json(item) for item in final_resolutions)
    plan = person_state_review.build_person_state_review_plan(
        job_id=job_id,
        revision_id=revision_id,
        accepted_artifacts=accepted_artifacts,
        assembly=assembly,
        resolution_hashes=resolution_hashes,
        base_catalog_sha=base_catalog_sha256,
    )
    return plan


def _person_state_context(projection: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(entity_labels, canonical_name)`` from the reading projection."""
    labels: dict[str, str] = {}
    names: dict[str, str] = {}
    for unit in projection.get("units") or []:
        for context in unit.get("context_entities") or []:
            if not isinstance(context, dict):
                continue
            ref = context.get("entity_ref")
            canonical_id = context.get("canonical_id")
            name = context.get("name")
            if isinstance(ref, str) and isinstance(name, str) and name:
                labels.setdefault(ref, name)
            if isinstance(canonical_id, str) and isinstance(name, str) and name:
                names.setdefault(canonical_id, name)
    return labels, names


def build_person_state_manifest(
    *,
    projection: dict[str, Any],
    catalog: dict[str, Any],
    bundle_label: str,
    stream_id: str,
    revision_id: uuid.UUID,
    chapter_publication_ids: list[str],
    publication_by_chapter: dict[str, str],
    evidence: dict[str, Any],
    assessments: dict[str, Any],
    assessment_hashes: list[str],
) -> dict[str, Any]:
    """Adapt the T04 compiled projection into the T05 manifest/index input.

    Compiles the pure T04 projection once per reading unit with that unit's own
    frozen phase binding, so a fact proven only for a later phase never leaks
    into an earlier unit and no GET-time inference is needed. Any missing
    binding, unresolved person or oversized item fails closed before a row is
    written; the manifest is persisted in the same publish transaction as the
    catalog, chapters and reading stream.
    """
    if not isinstance(projection.get("units"), list) or not projection["units"]:
        raise PersistenceError("person-state compile requires compiled reading units")
    canonical_map = dict(
        reading_projection.build_canonical_ref_map(catalog, bundle_label=bundle_label)[
            "entities"
        ]
    )
    labels, canonical_names = _person_state_context(projection)
    canonical_map["labels"] = labels
    chapter_publications = {
        str(chapter_id): str(publication_id)
        for chapter_id, publication_id in publication_by_chapter.items()
    }
    chapter_titles = {
        str(unit.get("chapter_id")): str(unit.get("source_title") or "")
        for unit in projection["units"]
    }
    bindings = {
        binding.get("block_id"): binding
        for binding in evidence.get("unit_phases") or []
        if isinstance(binding, dict)
    }
    phases_by_id = {
        phase.get("phase_id"): phase
        for phase in evidence.get("phases") or []
        if isinstance(phase, dict)
    }

    units: list[dict[str, Any]] = []
    for unit in sorted(projection["units"], key=lambda item: item["ordinal"]):
        binding = bindings.get(unit.get("block_id"))
        if binding is None:
            raise PersistenceError(
                f"reading unit {unit.get('unit_id')!r} has no frozen person-state "
                "phase binding; refusing to publish a partial state projection"
            )
        mode = binding.get("mode")
        if mode not in ("single", "process", "ambiguous", "unknown"):
            raise PersistenceError(
                f"reading unit {unit.get('unit_id')!r} has invalid phase mode {mode!r}"
            )
        phase_refs = [
            ref for ref in binding.get("phase_refs") or [] if isinstance(ref, str)
        ]
        reading_manifest = {
            "unit_id": unit.get("unit_id"),
            "unit_phase": {"mode": mode, "phase_ids": phase_refs},
            "chapter_publications": chapter_publications,
            "chapter_titles": chapter_titles,
            "entity_labels": labels,
        }
        compiled = person_state_projection.compile_person_state_projection(
            evidence, assessments, canonical_map, reading_manifest
        )
        context_by_canonical = {
            context.get("canonical_id"): context
            for context in unit.get("context_entities") or []
            if isinstance(context, dict) and isinstance(context.get("canonical_id"), str)
        }
        people: list[dict[str, Any]] = []
        for person_id in sorted(compiled.get("people") or {}):
            person = compiled["people"][person_id]
            context = context_by_canonical.get(person_id) or {}
            name = context.get("name") or canonical_names.get(person_id) or person_id
            people.append(
                {
                    "person_id": person_id,
                    "name": str(name),
                    "importance": context.get("importance") or "other",
                    "phase_mode": person.get("phase_mode") or mode,
                    "certainty": person.get("certainty") or "uncertain",
                    "reason_codes": list(person.get("reason_codes") or []),
                    "items": list(person.get("items") or []),
                    "changes": list(person.get("changes") or []),
                    "evidence": list(person.get("evidence") or []),
                }
            )
        phase_summaries = []
        for index, phase_id in enumerate(phase_refs):
            phase = phases_by_id.get(phase_id)
            if phase is None:
                raise PersistenceConflict(
                    f"wrong_phase: reading unit {unit.get('unit_id')!r} binds "
                    f"unknown phase {phase_id!r}"
                )
            label = phase.get("label")
            if not isinstance(label, str) or not label:
                label = phase_id
            phase_summaries.append(
                {
                    "phase_id": phase_id,
                    "label": label,
                    "ordinal": index,
                    "mode": mode,
                }
            )
        units.append(
            {
                "unit_id": unit.get("unit_id"),
                "unit_ordinal": unit.get("ordinal"),
                "publication_id": unit.get("publication_id"),
                "phase_mode": mode,
                "phases": phase_summaries,
                "people": people,
            }
        )

    manifest_payload = {
        "schema": "chronicle.person-state-manifest",
        "version": "0.1",
        "compiler_version": person_state_projection.PROJECTION_VERSION,
        "stream_id": str(stream_id),
        "revision_id": str(revision_id),
        "chapter_publications": [str(value) for value in chapter_publication_ids],
        "counts": {
            "units": len(units),
            "people": sum(len(unit["people"]) for unit in units),
        },
    }
    return {
        "stream_id": stream_id,
        "compiler_version": person_state_projection.PROJECTION_VERSION,
        "assessment_hashes": list(assessment_hashes),
        "chapter_publication_ids": [str(value) for value in chapter_publication_ids],
        "manifest": manifest_payload,
        "units": units,
    }


def build_person_state_disagreement_envelope(
    *,
    catalog_sha: str,
    evidence: dict[str, Any],
    assessments: dict[str, Any],
    publication_by_chapter: dict[str, str],
) -> dict[str, Any]:
    """Compile the reviewed, catalog-scoped disagreement index input.

    Only reviewed disagreements whose facts belong to the published revision
    participate; an explicitly rejected candidate is dropped. Every side keeps
    its own source publication, phase and Claim attribution, and the index can
    only add recorded explanations — it never promotes an uncertain claim.
    """
    rejected = {
        ref
        for ref, assessment in (assessments or {}).items()
        if assessment == "rejected"
    }
    base: list[dict[str, Any]] = []
    facts: dict[str, dict[str, Any]] = {}
    for fact in evidence.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        ref = fact.get("fact_id") or fact.get("fact_ref")
        origin = fact.get("origin") if isinstance(fact.get("origin"), dict) else {}
        chapter_id = origin.get("chapter_id") or fact.get("chapter_id")
        if not isinstance(ref, str) or not isinstance(chapter_id, str):
            continue
        phase_ref = fact.get("phase_ref")
        facts[ref] = {
            "chapter_id": chapter_id,
            "phase_ids": [phase_ref] if isinstance(phase_ref, str) else [],
            "claim_refs": [
                claim.get("ref")
                for claim in fact.get("claim_refs") or []
                if isinstance(claim, dict) and isinstance(claim.get("ref"), str)
            ],
            "source_publication_id": publication_by_chapter.get(chapter_id),
        }
    for record in evidence.get("disagreements") or []:
        if not isinstance(record, dict):
            continue
        assertion = record.get("assertion_id")
        if isinstance(assertion, str) and assertion in rejected:
            continue
        base.append(record)
    compiled = person_state_projection.compile_person_state_disagreements(
        base, [], {"catalog_sha": catalog_sha, "facts": facts}
    )
    records: list[dict[str, Any]] = []
    for record in compiled:
        sources: list[dict[str, Any]] = []
        for side in record.get("sides") or []:
            publication = side.get("source_publication_id")
            for fact_ref in side.get("fact_refs") or []:
                info = facts.get(fact_ref) or {}
                entry: dict[str, Any] = {
                    "fact_ref": fact_ref,
                    "chapter_id": info.get("chapter_id"),
                }
                if isinstance(publication, str) and publication:
                    entry["publication_id"] = publication
                if side.get("claim_refs"):
                    entry["claim_refs"] = list(side["claim_refs"])
                sources.append(entry)
        records.append(
            {
                "disagreement_id": record["disagreement_id"],
                "topic": record["topic"],
                "fact_refs": list(record["fact_refs"]),
                "phase_ids": list(record.get("phase_ids") or []),
                "reason_codes": list(record.get("reason_codes") or []),
                "sources": sources,
            }
        )
    return {
        "catalog_sha": catalog_sha,
        "compiler_version": person_state_projection.PROJECTION_VERSION,
        "disagreements": records,
    }


def validate_frozen_person_state_inputs(
    *,
    job_id: uuid.UUID,
    plan: dict[str, Any],
    evidence: dict[str, Any],
    accepted_artifacts: list[dict[str, Any]],
    final_resolutions: list[dict[str, Any]],
    base_catalog_sha256: str,
) -> None:
    """Re-verify the frozen 0.3 state inputs at the publication boundary.

    Resolve freezes the plan over the accepted artifacts, the assembled
    ``person_states``/evidence manifests, the final Resolution hashes and the
    base catalog. Publish must never trust the persisted rows alone: this
    recomputes every binding and fails closed when the accepted artifact set,
    the resolution set, the base catalog, the assembled state hash, the
    evidence-manifest reference mapping or the unit-phase closure drifted after
    the review was frozen. A wrong phase binding can otherwise compile a
    manifest with a fallback label and publish it. Any drift is a
    :class:`PersistenceConflict` and writes nothing.
    """
    states = evidence.get("person_states")
    manifests = evidence.get("evidence_manifests")
    if not isinstance(states, dict) or not isinstance(manifests, list):
        raise PersistenceError(
            f"job {job_id} person-state evidence is not a frozen 0.3 assembly"
        )
    assembled_hash = sha256_json(states)
    if assembled_hash != plan.get("assembled_hash"):
        raise PersistenceConflict(
            "state_drift: assembled person_states no longer matches the frozen "
            f"plan assembled_hash ({assembled_hash} != {plan.get('assembled_hash')})"
        )
    report = evidence.get("report") if isinstance(evidence.get("report"), dict) else {}
    reported_states_hash = report.get("person_states_sha256")
    if reported_states_hash is not None and reported_states_hash != assembled_hash:
        raise PersistenceConflict(
            "state_drift: reported person_states_sha256 does not match the "
            "assembled person_states"
        )
    reported_manifest_hash = report.get("evidence_manifests_sha256")
    if reported_manifest_hash is not None and reported_manifest_hash != sha256_json(
        manifests
    ):
        raise PersistenceConflict(
            "state_drift: reported evidence_manifests_sha256 does not match the "
            "assembled evidence manifests"
        )
    artifact_hashes = sorted(
        str(artifact.get("artifact_sha256"))
        for artifact in accepted_artifacts
        if isinstance(artifact, dict)
    )
    if artifact_hashes != sorted(str(value) for value in plan.get("accepted_artifact_hashes") or []):
        raise PersistenceConflict(
            "state_drift: accepted artifact set no longer matches the frozen plan"
        )
    resolution_hashes = sorted(sha256_json(item) for item in final_resolutions)
    if resolution_hashes != sorted(str(value) for value in plan.get("resolution_hashes") or []):
        raise PersistenceConflict(
            "state_drift: final Resolution hashes no longer match the frozen plan"
        )
    if plan.get("base_catalog_sha") != base_catalog_sha256:
        raise PersistenceConflict(
            "state_drift: frozen plan base catalog no longer matches the resolve baseline"
        )
    references = person_state_review._reference_maps(evidence)
    for package in plan.get("packages") or []:
        chapter_refs = references.get(package.get("chapter_id"), {})
        for candidate in package.get("candidates") or []:
            mapped = chapter_refs.get((candidate.get("kind"), candidate.get("item_ref")))
            if mapped != candidate.get("revision_ref"):
                raise PersistenceConflict(
                    "state_drift: evidence manifest no longer maps "
                    f"{candidate.get('kind')}:{candidate.get('item_ref')} to the "
                    "frozen revision reference"
                )

    phase_ids = {
        phase.get("phase_id")
        for phase in states.get("phases") or []
        if isinstance(phase, dict) and isinstance(phase.get("phase_id"), str)
    }
    # Frozen candidates carry chapter-local phase refs; resolve the manifest's
    # local->revision mapping so a candidate that points at a phase no longer
    # present in the assembled evidence fails closed instead of compiling with a
    # fallback label.
    local_phase_map: dict[tuple[Any, Any], Any] = {}
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        chapter_id = manifest.get("chapter_id")
        for item in manifest.get("items") or []:
            if not isinstance(item, dict) or item.get("kind") != "phase":
                continue
            local_phase_map[(chapter_id, item.get("origin_ref"))] = item.get("revision_ref")
    for package in plan.get("packages") or []:
        chapter_id = package.get("chapter_id")
        for candidate in package.get("candidates") or []:
            for local_phase in candidate.get("phase_ids") or []:
                mapped = local_phase_map.get((chapter_id, local_phase))
                if mapped is None or mapped not in phase_ids:
                    raise PersistenceConflict(
                        "wrong_phase: frozen candidate "
                        f"{candidate.get('kind')}:{candidate.get('item_ref')} references "
                        f"phase {local_phase!r} that is not in the assembled evidence"
                    )

    def require_phase(value: Any, owner: str) -> None:
        if value is not None and value not in phase_ids:
            raise PersistenceConflict(
                f"wrong_phase: {owner} references unknown phase {value!r}"
            )

    for binding in states.get("unit_phases") or []:
        owner = f"unit_phase {binding.get('block_id')!r}"
        for phase_ref in binding.get("phase_refs") or []:
            require_phase(phase_ref, owner)
    for order in states.get("phase_orders") or []:
        require_phase(order.get("earlier_phase_ref"), "phase_order earlier")
        require_phase(order.get("later_phase_ref"), "phase_order later")
    for fact in states.get("facts") or []:
        require_phase(fact.get("phase_ref"), f"fact {fact.get('fact_id')!r}")
    for continuity in states.get("continuities") or []:
        require_phase(continuity.get("start_phase_ref"), "continuity start")
        require_phase(continuity.get("end_phase_ref"), "continuity end")
    for disagreement in states.get("disagreements") or []:
        for phase_ref in disagreement.get("phase_refs") or []:
            require_phase(phase_ref, f"disagreement {disagreement.get('assertion_id')!r}")


def persist_person_state_publication(
    conn,
    *,
    job_id: uuid.UUID,
    plan: dict[str, Any],
    catalog: dict[str, Any],
    catalog_sha256: str,
    bundle_label: str,
    revision_id: uuid.UUID,
    projection: dict[str, Any],
    chapter_publication_ids: list[str],
    publication_by_chapter: dict[str, str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Persist assessments, the state manifest/index and disagreements in-txn.

    Called from :func:`publish_chapters` after the catalog, chapters, and
    reading stream exist in the same transaction, so the reviewed assessments,
    the immutable state projection and the catalog disagreement index either
    all commit together or roll back with everything else.
    """
    collected = person_state_review.collect_person_state_assessments(
        conn, job_id=job_id, plan=plan, persist=False
    )
    compiler_assessments = collected["compiler_assessments"]
    payload = copy.deepcopy(collected["payload"])
    # The published catalog is the membership the state facts actually belong
    # to; binding it here keeps the assessment reproducible from the published
    # version instead of an unpublished baseline.
    payload["base_catalog_sha"] = catalog_sha256
    assessment_sha = person_state_store.persist_person_state_assessments(
        conn,
        {
            "plan_fingerprint": plan["plan_fingerprint"],
            "base_catalog_sha": catalog_sha256,
            "compiler_version": payload["compiler_version"],
            "payload": payload,
        },
    )[0]
    stream_id = reading_stream_seed(revision_id)
    manifest = build_person_state_manifest(
        projection=projection,
        catalog=catalog,
        bundle_label=bundle_label,
        stream_id=stream_id,
        revision_id=revision_id,
        chapter_publication_ids=chapter_publication_ids,
        publication_by_chapter=publication_by_chapter,
        evidence=evidence,
        assessments=compiler_assessments,
        assessment_hashes=[assessment_sha],
    )
    manifest_sha = person_state_store.persist_person_state_manifest(conn, manifest)
    disagreements = build_person_state_disagreement_envelope(
        catalog_sha=catalog_sha256,
        evidence=evidence,
        assessments=compiler_assessments,
        publication_by_chapter=publication_by_chapter,
    )
    if disagreements["disagreements"]:
        person_state_store.persist_person_state_disagreements(conn, disagreements)
    return {
        "person_state_manifest_sha": manifest_sha,
        "person_state_assessment_sha": assessment_sha,
        "person_state_unit_count": len(manifest["units"]),
        "person_state_person_count": int(manifest["manifest"]["counts"]["people"]),
        "person_state_disagreement_count": len(disagreements["disagreements"]),
    }


def publish_chapters(
    conn,
    *,
    job_id: uuid.UUID,
    worker: str,
    chapter_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically publish every accepted chapter of a job (one transaction).

    Holds the unified transaction advisory lock, re-reads the latest
    catalog by ``publication_sequence``, re-verifies the lease (a lock
    wait never extends an expired lease), reuses the frozen review plan
    exactly (never rebuilding or re-ranking it), and requires every
    candidate to carry a terminal human decision with zero open reviews.
    One missing/invalid chapter, one open review, or one wrong frozen
    plan fails the whole publish: no partial catalog or translation can
    ever become public.

    In the same transaction this writes the catalog, every chapter
    publication, the canonical membership maps (via
    :mod:`canonical_store`), the catalog output, and the publish
    checkpoint/completed status — any fault rolls back all public
    content. When the frozen baseline moved (a newer catalog exists),
    raises :class:`PublicationPlanStale` and writes nothing: the old
    plan and its evidence are kept, nothing is auto-passed.

    When the accepted chapters are 0.2 reading artifacts, the caller must
    pass the exact T03 ``chapter_plan`` used for the accepted products; the
    plan is strictly bound to the persisted T03/assembled record
    (:func:`require_chapter_plan_binding`) and the re-assembled bundle must
    equal the persisted assembled bundle, so caller-supplied drift can never
    reach the reading manifest. In that case the same transaction compiles
    the immutable reading projection (T04) and persists the whole reading
    stream/units/groups/occurrences (T05) before the checkpoint commits, so a
    job either publishes catalog + complete chapters + full reading index
    together or publishes nothing. A 0.1 job keeps the first-round behavior
    and writes no reading rows.

    The lease is re-verified on the live clock (``clock_timestamp``) after
    the expensive catalog/assembly computation, after the reading compile and
    again immediately before the commit, so a lease that expires while the
    transaction is computing fails closed with :class:`LeaseLost` and rolls
    back every write instead of committing public content.
    """
    if not isinstance(worker, str) or not worker:
        raise PersistenceError("worker must be a non-empty string")
    try:
        job_id = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PersistenceError(f"job_id must be a UUID, got {job_id!r}") from exc

    with conn.transaction():
        acquire_publish_lock(conn)
        # Re-verify the lease under the lock: waiting for the lock never
        # extends a lease that expired while queued. Ownership alone is
        # not enough (`require_job_lease` ignores expiry by contract),
        # so an expired lease fails closed here even without a takeover.
        require_unexpired_lease(conn, job_id=job_id, worker=worker)

        job_row = conn.execute(
            """
            SELECT revision_id, status FROM chronicle.ingestion_jobs
            WHERE job_id = %s
            """,
            (job_id,),
        ).fetchone()
        if job_row is None:
            raise PersistenceError(f"unknown job {job_id}")
        revision_id, job_status = job_row[0], job_row[1]
        if job_status in ("cancelled", "failed", "completed"):
            raise PersistenceConflict(
                f"job {job_id} is {job_status!r}; refusing publication"
            )

        accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
        if not accepted:
            raise PersistenceError(
                f"job {job_id} has no accepted chapters; refusing to "
                "publish an empty catalog"
            )
        artifact_versions = {
            entry["artifact"].get("version") for entry in accepted
        }
        if (
            len(artifact_versions) != 1
            or not artifact_versions <= set(CHAPTER_ARTIFACT_VERSIONS)
        ):
            raise PersistenceError(
                f"job {job_id} accepted chapters mix unsupported artifact "
                f"generations {sorted(str(v) for v in artifact_versions)}; "
                "refusing to publish a mixed-generation book"
            )
        person_state_path = artifact_versions == {PERSON_STATE_ARTIFACT_VERSION}
        reading_path = artifact_versions in (
            {READING_ARTIFACT_VERSION},
            {PERSON_STATE_ARTIFACT_VERSION},
        )
        if reading_path and not isinstance(chapter_plan, dict):
            raise PersistenceError(
                f"job {job_id} carries reading artifacts but no chapter "
                "plan; refusing to publish without the compiled reading index"
            )
        person_state_evidence: dict[str, Any] | None = None
        person_state_plan: dict[str, Any] | None = None

        assembled_row = conn.execute(
            """
            SELECT payload FROM chronicle.ingestion_outputs
            WHERE job_id = %s AND artifact_type = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (job_id, "assembled-source-bundle"),
        ).fetchone()
        if assembled_row is None or not isinstance(assembled_row[0], dict):
            raise PersistenceError(
                f"job {job_id} has no assembled chapter bundle output"
            )
        assembled_payload = assembled_row[0]
        bundle = assembled_payload.get("bundle")
        if not isinstance(bundle, dict):
            raise PersistenceError(
                f"job {job_id} assembled output carries no source bundle"
            )
        assembled_sha256 = sha256_json(bundle)
        if reading_path:
            # Never compile reading metadata from a caller plan that drifts
            # from the persisted T03/assembled evidence.
            require_chapter_plan_binding(
                chapter_plan=chapter_plan,
                assembled_payload=assembled_payload,
                assembled_sha256=assembled_sha256,
                job_id=job_id,
            )
        if person_state_path:
            raw_states = assembled_payload.get("person_states")
            raw_manifests = assembled_payload.get("person_state_evidence")
            if not isinstance(raw_states, dict) or not isinstance(raw_manifests, list):
                raise PersistenceError(
                    f"job {job_id} carries 0.3 artifacts but no persisted "
                    "person-state assembly; refusing to publish a partial state "
                    "projection (run assemble first)"
                )
            report = assembled_payload.get("report")
            person_report = (
                report.get("person_state") if isinstance(report, dict) else None
            )
            person_state_evidence = {
                "person_states": raw_states,
                "evidence_manifests": raw_manifests,
                "report": person_report if isinstance(person_report, dict) else {},
            }
            plan_payload = read_person_state_plan_output(conn, job_id=job_id)
            person_state_plan = (
                plan_payload.get("plan") if isinstance(plan_payload, dict) else None
            )
            if not isinstance(person_state_plan, dict) or not person_state_plan:
                raise PersistenceError(
                    f"job {job_id} has no frozen person-state review plan; "
                    "refusing to publish before the state evidence review "
                    "(run resolve first)"
                )
            person_state_review.validate_person_state_review_plan(person_state_plan)
            if open_person_state_review_count(conn, job_id=job_id) > 0:
                raise PersistenceError(
                    f"job {job_id} has open person-state reviews; refusing to "
                    "publish a partially reviewed state projection"
                )

        plan_row = conn.execute(
            """
            SELECT payload FROM chronicle.ingestion_outputs
            WHERE job_id = %s AND artifact_type = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (job_id, "chapter-review-plan"),
        ).fetchone()
        if plan_row is None or not isinstance(plan_row[0], dict):
            raise PersistenceError(
                f"job {job_id} has no frozen chapter review plan; "
                "refusing to publish without human review (run resolve first)"
            )
        frozen_plan = (plan_row[0].get("plan") or {})
        base_catalog_sha256 = plan_row[0].get("base_catalog_sha256")
        initial_shas = plan_row[0].get("initial_shas") or []
        if not isinstance(frozen_plan, dict) or not frozen_plan:
            raise PersistenceError(
                f"job {job_id} frozen chapter review plan is missing"
            )
        if plan_row[0].get("assembled_bundle_sha256") != assembled_sha256:
            raise PersistenceError(
                f"job {job_id} frozen plan binds a different assembled "
                "bundle; refusing publication from conflicting bytes"
            )

        initials: list[dict[str, Any]] = []
        if initial_shas:
            fetched = conn.execute(
                """
                SELECT artifact_sha256, payload
                FROM chronicle.resolution_artifacts
                WHERE artifact_sha256 = ANY(%s)
                """,
                (sorted({str(sha) for sha in initial_shas}),),
            ).fetchall()
            by_sha = {row[0]: row[1] for row in fetched}
            for sha in initial_shas:
                payload = by_sha.get(str(sha))
                if not isinstance(payload, dict):
                    raise PersistenceError(
                        f"job {job_id} frozen initial resolution {sha!r} "
                        "is not persisted; refusing publication"
                    )
                initials.append(payload)
        # Re-validate the frozen plan exactly: no rebuild, no re-rank.
        validate_chapter_review_plan(
            frozen_plan, initials, job_id=job_id, revision_id=revision_id,
            assembled_bundle_sha256=assembled_sha256,
            base_catalog_sha256=base_catalog_sha256,
        )

        open_count = open_resolution_review_count(conn, job_id=job_id)
        if open_count > 0:
            raise PersistenceError(
                f"job {job_id} has {open_count} open resolution review(s); "
                "refusing to publish a partially reviewed graph"
            )
        decisions = collect_chapter_decisions(conn, job_id=job_id)
        # Every candidate must carry a terminal decision: missing
        # coverage fails closed instead of publishing a partial graph.
        final = build_final_chapter_resolutions(
            initials, decisions, require_complete=True
        )

        if person_state_path:
            # Re-verify every frozen state/evidence binding against the actual
            # accepted artifacts and terminal decisions before compiling the
            # projection: drift or a wrong phase fails closed and writes
            # nothing public.
            assert person_state_evidence is not None
            assert person_state_plan is not None
            validate_frozen_person_state_inputs(
                job_id=job_id,
                plan=person_state_plan,
                evidence=person_state_evidence,
                accepted_artifacts=[entry["artifact"] for entry in accepted],
                final_resolutions=final,
                base_catalog_sha256=base_catalog_sha256,
            )

        latest = read_latest_catalog(conn)
        latest_sha = sha256_json(latest) if latest is not None else sha256_json(None)
        if latest_sha != base_catalog_sha256:
            raise PublicationPlanStale(
                f"{PUBLICATION_PLAN_STALE}: job {job_id} frozen baseline "
                f"{base_catalog_sha256} is no longer latest ({latest_sha}); "
                "keeping the frozen plan and its evidence, refusing to "
                "auto-pass or rebuild"
            )

        new_label = new_bundle_label(revision_id)
        # Idempotent reuse: the staged bundle and the final resolutions
        # persist as no-ops when their exact bytes already exist.
        staged_store.persist_bundle(conn, new_label, bundle)
        for resolution in final:
            resolution_store.persist_resolution(conn, resolution)

        bundles = read_published_corpus_bundles(conn, latest)
        bundles[new_label] = bundle
        prior = read_corpus_resolutions(conn)
        resolutions = list(prior)
        prior_shas = {sha256_json(item) for item in prior}
        resolutions.extend(
            item for item in final if sha256_json(item) not in prior_shas
        )
        try:
            catalog, report = publish_with_decisions(
                bundles=bundles, resolutions=resolutions,
                existing_catalog=latest,
            )
        except publication_v0.PublicationConflict as exc:
            raise PersistenceError(
                f"chapter publication failed closed: {exc}"
            ) from exc
        catalog_sha256 = sha256_json(catalog)

        # One atomic public commit: catalog, canonical maps, every
        # chapter publication, the reading index, the catalog output, and
        # the publish checkpoint/completed status. Any fault rolls back
        # all of it, so no partial catalog/chapter/reading content is ever
        # externally visible.
        # For a reading book, the chapter publication serves the
        # revision-assembled blocks (remapped ``block_id``), which are exactly
        # the blocks the reading units cite. Assembly is deterministic, so the
        # projection compiles over identical bytes.
        reading_blocks_by_chapter: dict[str, list[dict[str, Any]]] = {}
        if reading_path:
            assembled_for_publish = chapter_assembly.assemble_chapters(
                accepted_artifacts=[entry["artifact"] for entry in accepted],
                chapter_plan=chapter_plan,
            )
            if sha256_json(assembled_for_publish.get("bundle")) != assembled_sha256:
                raise PersistenceError(
                    f"job {job_id} re-assembled bundle does not match the "
                    "persisted assembled bundle; refusing to publish reading "
                    "metadata compiled from drifted bytes"
                )
            for block in assembled_for_publish.get("translation_blocks") or []:
                reading_blocks_by_chapter.setdefault(
                    str(block.get("chapter_id")), []
                ).append(block)

        # Re-fence on the live clock after the expensive catalog/assembly
        # computation and before the first public write.
        require_unexpired_lease(conn, job_id=job_id, worker=worker)

        canonical_store.persist_catalog(conn, catalog)
        publication_ids: list[str] = []
        publication_by_chapter: dict[str, str] = {}
        artifact_sha256_by_chapter: dict[str, str] = {}
        for entry in accepted:
            publication = build_chapter_publication(
                artifact_entry=entry, catalog_sha256=catalog_sha256,
                assembled_bundle_sha256=assembled_sha256,
                translation_blocks=reading_blocks_by_chapter.get(entry["chapter_id"]),
            )
            publication_id = chapter_store.insert_chapter_publication_in_txn(
                conn, job_id=job_id, artifact_sha256=entry["artifact_sha256"],
                catalog_sha256=catalog_sha256,
                assembled_bundle_sha256=assembled_sha256,
                publication=publication,
            )
            publication_ids.append(str(publication_id))
            publication_by_chapter[entry["chapter_id"]] = str(publication_id)
            artifact_sha256_by_chapter[entry["chapter_id"]] = entry["artifact_sha256"]

        reading: dict[str, Any] = {}
        if reading_path:
            document_row = conn.execute(
                "SELECT document_id FROM chronicle.document_revisions"
                " WHERE revision_id = %s",
                (revision_id,),
            ).fetchone()
            if document_row is None:
                raise PersistenceError(
                    f"job {job_id} revision {revision_id} is not persisted"
                )
            document_id = document_row[0]
            projection = reading_projection.compile_reading_projection(
                accepted_artifacts=[entry["artifact"] for entry in accepted],
                chapter_plan=chapter_plan,
                catalog=catalog,
                stream_id=reading_stream_seed(revision_id),
                publication_by_chapter=dict(publication_by_chapter),
                bundle_label=new_label,
            )
            ordered_publications = _ordered_chapter_publications(
                projection, publication_by_chapter
            )
            stream_payload = build_reading_stream_payload(
                projection=projection,
                catalog=catalog,
                revision_id=revision_id,
                document_id=document_id,
                chapter_publication_ids=ordered_publications,
                artifact_sha256_by_chapter=artifact_sha256_by_chapter,
                bundle_label=new_label,
            )
            # The reading compile is expensive; an expired lease here must
            # never write a public stream row (the whole transaction rolls
            # back, including the catalog and chapters already written).
            require_unexpired_lease(conn, job_id=job_id, worker=worker)
            stream_id = reading_store.persist_reading_stream(conn, stream_payload)
            reading = {
                "reading_stream_id": str(stream_id),
                "reading_unit_count": int(projection["counts"]["units"]),
                "reading_group_count": int(projection["counts"]["groups"]),
                "reading_occurrence_count": int(projection["counts"]["occurrences"]),
            }
            if person_state_path:
                # The catalog, every chapter publication and the reading
                # stream are already written in this transaction; persist the
                # reviewed assessments, the immutable state manifest/index and
                # the catalog disagreement index next. Any fault here rolls
                # back all of it — no partial state is ever visible.
                assert person_state_evidence is not None
                assert person_state_plan is not None
                reading.update(
                    persist_person_state_publication(
                        conn,
                        job_id=job_id,
                        plan=person_state_plan,
                        catalog=catalog,
                        catalog_sha256=catalog_sha256,
                        bundle_label=new_label,
                        revision_id=revision_id,
                        projection=projection,
                        chapter_publication_ids=ordered_publications,
                        publication_by_chapter=publication_by_chapter,
                        evidence=person_state_evidence["person_states"],
                    )
                )

        # Final live-clock fence immediately before the fenced output,
        # checkpoint and commit: no public content may commit on a lease
        # that expired during the expensive compile.
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=revision_id,
            worker=worker,
            artifact_type=CATALOG_ARTIFACT_TYPE,
            artifact_sha256=catalog_sha256,
            payload={
                "catalog_sha256": catalog_sha256,
                "report": report,
                "catalog": catalog,
                "counts": report["counts"],
                "publication_ids": sorted(publication_ids),
                "chapter_count": len(accepted),
                **reading,
            },
        )
        control_plane.write_stage_checkpoint_fenced(
            conn, job_id=job_id, stage="publish", worker=worker,
            checkpoint={
                "resolve_publish_version": RESOLVE_PUBLISH_VERSION,
                "catalog_sha256": catalog_sha256,
                "assembled_bundle_sha256": assembled_sha256,
                "publication_ids": sorted(publication_ids),
                "counts": report["counts"],
                "authoritative": False,
                **reading,
            },
        )
        control_plane.advance_stage_fenced(
            conn, job_id=job_id, stage="publish", status="completed",
            worker=worker,
        )
    return {
        "catalog_sha256": catalog_sha256,
        "publication_ids": sorted(publication_ids),
        "chapter_count": len(accepted),
        "counts": report["counts"],
        **reading,
    }
