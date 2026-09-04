"""Chronicle C1-T8 cross-source resolution, human review, and canonical publication.

Pure deterministic logic plus small durable helpers on the C1-T1
control-plane tables behind ``CHRONICLE_DATABASE_URL`` (Architecture
Amendment 0006). The durable worker path lives in
``apps/chronicle/worker/ingestion_worker.py`` (``resolve`` / ``publish``
stages).

Contract summary (GitHub Issue #497):

- A newly assembled source bundle is resolved against the persisted
  Chronicle corpus (every ``source_bundles`` row except the job's own
  new label) using the existing conservative C0 candidate semantics
  (:mod:`resolution_v0` blocking: same Entity type + exact stable
  surface; Event time compatibility + participant/place overlap). No
  new blocking rule, no fuzzy matching, no model adjudication: the
  deterministic layer never invents ``same_entity`` / ``same_occurrence``.
- Initial decisions are all ``uncertain``. Every candidate becomes one
  durable ``ReviewItem`` (kind ``stage_gate``, a frozen C1-T1
  vocabulary value) tied to the originating ingestion job with full
  source/bundle/ref provenance in its payload.
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
  UUIDv7 identities.
- ``IngestionOutput`` rows link the job to the exact produced source
  bundle, resolution artifact(s), and canonical catalog/publication
  evidence by content hash.

No timestamps, UUIDs, or randomness appear in any generated artifact
(human audit times live only in ``review_items`` rows). Unchanged
inputs plus unchanged recorded decisions yield byte-identical
canonical JSON.
"""

from __future__ import annotations

import copy
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
    PersistenceConflict,
    PersistenceError,
    canonical_json_bytes,
    sha256_json,
)
from psycopg.types.json import Jsonb  # noqa: E402

import publication_v0  # noqa: E402
import resolution_v0  # noqa: E402

#: Version of this resolve/review/publish pipeline step.
RESOLVE_PUBLISH_VERSION = "c1t8-v1"

#: Reused C0 resolution contract (candidates + link decisions).
RESOLUTION_VERSION = resolution_v0.RESOLUTION_VERSION

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


def read_corpus_bundles(conn) -> dict[str, dict[str, Any]]:
    """Read every persisted source bundle payload keyed by bundle label."""
    rows = conn.execute(
        "SELECT bundle_label, bundle_payload FROM chronicle.source_bundles ORDER BY bundle_label"
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def read_corpus_resolutions(conn) -> list[dict[str, Any]]:
    """Read every persisted resolution artifact payload in sha order."""
    rows = conn.execute(
        "SELECT payload FROM chronicle.resolution_artifacts ORDER BY artifact_sha256"
    ).fetchall()
    return [row[0] for row in rows]


def read_latest_catalog(conn) -> dict[str, Any] | None:
    """Read the latest persisted canonical catalog payload, if any."""
    row = conn.execute(
        "SELECT payload FROM chronicle.canonical_catalogs ORDER BY imported_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row is not None else None


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
    """Build one initial resolution artifact per corpus bundle.

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
    """Open (or adopt) one review item per resolution candidate.

    Idempotent: existing items for this job with the same
    ``(resolution_sha256, candidate_id)`` — open, resolved, or
    dismissed — are reused in deterministic order instead of
    duplicated, so a crashed-then-resumed worker never multiplies
    review gates.
    """
    rows = conn.execute(
        """
        SELECT review_id, status, payload
        FROM chronicle.review_items
        WHERE job_id = %s
        ORDER BY created_at, review_id
        """,
        (job_id,),
    ).fetchall()
    existing: dict[str, uuid.UUID] = {}
    for review_id, _status, payload in rows:
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("scope") != REVIEW_SCOPE:
            continue
        key = _candidate_key(
            str(payload.get("resolution_sha256") or ""),
            str(payload.get("candidate_id") or ""),
        )
        existing.setdefault(key, review_id)

    ordered: list[uuid.UUID] = []
    for resolution in resolutions:
        resolution_sha = initial_artifact_sha(resolution)
        links: list[tuple[str, dict[str, Any]]] = [
            ("entity", link) for link in resolution.get("entity_links") or []
        ] + [("event", link) for link in resolution.get("event_links") or []]
        links.sort(key=lambda item: str(item[1].get("candidate_id")))
        for link_kind, link in links:
            candidate_id = link.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise PersistenceError("resolution link is missing candidate_id")
            key = _candidate_key(resolution_sha, candidate_id)
            if key in existing:
                ordered.append(existing[key])
                continue
            payload = review_payload(
                resolution_sha=resolution_sha, candidate=link, link_kind=link_kind
            )
            review_id = control_plane.open_review_item(
                conn, job_id=job_id, kind=REVIEW_KIND, payload=payload
            )
            existing[key] = review_id
            ordered.append(review_id)
    return ordered


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
) -> None:
    """Record a human decision on one resolution review item.

    Validates the exact C0 decision vocabulary for the item's link
    kind, stores the decision durably in the item payload, then marks
    the item resolved through the standard control-plane transition
    (open items only; resolved history stays auditable). Raises
    :class:`PersistenceError` for any vocabulary violation and
    :class:`PersistenceConflict` when the item is not open.
    """
    row = conn.execute(
        "SELECT status, payload FROM chronicle.review_items WHERE review_id = %s",
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
    # Two short sequential transactions (the codebase never holds one
    # transaction across steps): a crash between them leaves the
    # decision in the payload while the item stays open, so the next
    # attempt simply records the decision again instead of publishing
    # a half-reviewed graph.
    with conn.transaction():
        conn.execute(
            "UPDATE chronicle.review_items SET payload = %s WHERE review_id = %s",
            (Jsonb(decided), review_id),
        )
    control_plane.resolve_review_item(conn, review_id=review_id, status="resolved")


def collect_review_decisions(
    conn, *, job_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    """Collect recorded decisions keyed by ``resolution_sha:candidate_id``.

    Only resolution-scoped items in ``resolved`` status contribute;
    ``dismissed`` items are intentionally absent so finalization treats
    them as ``uncertain`` (giving up on a review never merges).
    """
    rows = conn.execute(
        """
        SELECT payload FROM chronicle.review_items
        WHERE job_id = %s AND status = 'resolved'
        ORDER BY created_at, review_id
        """,
        (job_id,),
    ).fetchall()
    decisions: dict[str, dict[str, Any]] = {}
    for (payload,) in rows:
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("scope") != REVIEW_SCOPE:
            continue
        decision = payload.get("decision")
        if not isinstance(decision, dict):
            continue
        key = _candidate_key(
            str(payload.get("resolution_sha256") or ""),
            str(payload.get("candidate_id") or ""),
        )
        _require_decision(str(payload.get("link_kind")), decision.get("decision"))
        decisions[key] = {
            "decision": decision["decision"],
            "confidence": float(decision["confidence"]),
            "rationale": str(decision["rationale"]),
        }
    return decisions


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
    """Apply recorded human decisions over initial uncertain artifacts.

    Every candidate keeps its ID, refs, and signals; only
    decision/confidence/rationale change. Candidates without a
    recorded decision (including dismissed reviews) stay ``uncertain``,
    so an incomplete or abandoned review can never merge identities.
    With ``require_complete`` (the worker default), any candidate that
    is neither resolved nor dismissable fails closed instead of
    publishing a partially reviewed graph — the caller must distinguish
    "reviewed uncertain" from "never reviewed", which it does through
    the review-item table, not here.
    """
    final: list[dict[str, Any]] = []
    for pristine in initial:
        # Bind decisions to the full initial artifact hash (the same
        # hash review items were opened under): any change to the
        # initial artifact invalidates stale decisions instead of
        # silently applying them. The hash is taken before any
        # decision is applied below.
        full_sha = initial_artifact_sha(pristine)
        resolution = copy.deepcopy(pristine)
        for collection, link_kind in (
            ("entity_links", "entity"),
            ("event_links", "event"),
        ):
            for link in resolution.get(collection) or []:
                key = _candidate_key(full_sha, str(link.get("candidate_id")))
                recorded = decisions.get(key)
                if recorded is None:
                    if require_complete:
                        raise PersistenceError(
                            "candidate "
                            f"{link.get('candidate_id')} of resolution "
                            f"{full_sha[:12]} has no recorded review decision; "
                            "refusing to publish a partially reviewed graph"
                        )
                    continue
                _require_decision(link_kind, recorded["decision"])
                link["decision"] = recorded["decision"]
                link["confidence"] = float(recorded["confidence"])
                link["rationale"] = str(recorded["rationale"])
        resolution["warnings"] = [
            {
                "type": "unresolved_resolution",
                "message": f"Resolution candidate {link['candidate_id']} remains uncertain.",
                "refs": [link["candidate_id"]],
            }
            for link in (resolution.get("entity_links") or [])
            + (resolution.get("event_links") or [])
            if link.get("decision") == "uncertain"
        ]
        final.append(resolution)
    final.sort(key=lambda item: sha256_json(item))
    return final


def _initial_identity(resolution: dict[str, Any]) -> dict[str, Any]:
    """Identity projection of an initial artifact for decision binding."""
    return {
        "schema": resolution.get("schema"),
        "version": resolution.get("version"),
        "left_bundle": resolution.get("left_bundle"),
        "right_bundle": resolution.get("right_bundle"),
        "entity_links": resolution.get("entity_links"),
        "event_links": resolution.get("event_links"),
        "warnings": resolution.get("warnings"),
    }


def initial_artifact_sha(resolution: dict[str, Any]) -> str:
    """Content hash of an initial resolution artifact (review binding)."""
    return sha256_json(_initial_identity(resolution))


# ---------------------------------------------------------------------------
# Canonical publication over accepted decisions
# ---------------------------------------------------------------------------


def publish_with_decisions(
    *,
    bundles: dict[str, dict[str, Any]],
    resolutions: list[dict[str, Any]],
    existing_catalog: dict[str, Any] | None,
    id_factory=publication_v0.new_uuid7,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Publish accepted resolutions into a canonical catalog plus report.

    Thin deterministic wrapper over :func:`publication_v0.publish_catalog`
    (C0 semantics reused unchanged: only ``same_entity`` /
    ``same_occurrence`` union; ``uncertain`` / ``not_same`` /
    ``related_occurrence`` never merge; negative constraints and
    existing-ID collapse fail closed). The report is run metadata —
    counts and content hashes — never identity authority, and carries
    no timestamps so reruns stay byte-stable.
    """
    catalog = publication_v0.publish_catalog(
        bundles, resolutions, existing_catalog, id_factory
    )
    catalog_sha = sha256_json(catalog)
    decisions: dict[str, dict[str, int]] = {"entities": {}, "events": {}}
    for key, collection in (
        ("entities", "entity_links"),
        ("events", "event_links"),
    ):
        for resolution in resolutions:
            for link in resolution.get(collection) or []:
                name = str(link.get("decision"))
                decisions[key][name] = decisions[key].get(name, 0) + 1
    report = {
        "schema": "chronicle.canonical-publication-report",
        "version": "0.1",
        "resolve_publish_version": RESOLVE_PUBLISH_VERSION,
        "publication_version": PUBLICATION_VERSION,
        "bundles": sorted(bundles),
        "resolutions": sorted(sha256_json(item) for item in resolutions),
        "existing_catalog": (
            sha256_json(existing_catalog) if existing_catalog is not None else None
        ),
        "catalog_sha256": catalog_sha,
        "decisions": decisions,
        "counts": {
            "canonical_entities": len(catalog.get("canonical_entities") or []),
            "canonical_events": len(catalog.get("canonical_events") or []),
            "event_relations": len(catalog.get("event_relations") or []),
        },
        "authoritative": False,
        "authority_note": (
            "canonical publication is deterministic identity membership over "
            "source-owned bundles and accepted resolution links, not "
            "historical authority; staged sources and claims remain intact"
        ),
    }
    return catalog, report


def artifact_canonical_bytes(artifact: dict[str, Any]) -> bytes:
    """Canonical bytes for hashing/persistence of resolve/publish artifacts."""
    if not isinstance(artifact, dict):
        raise PersistenceError("resolve/publish artifact must be a JSON object")
    return canonical_json_bytes(artifact)
