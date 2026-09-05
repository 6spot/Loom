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
RESOLVE_PUBLISH_VERSION = "c1t8-v2"

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


def read_latest_catalog(conn) -> dict[str, Any] | None:
    """Read the latest persisted canonical catalog payload, if any."""
    row = conn.execute(
        "SELECT payload FROM chronicle.canonical_catalogs ORDER BY imported_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row is not None else None


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
    """Read only resolution artifacts wholly inside the published corpus."""
    labels = published_bundle_labels(read_latest_catalog(conn))
    return filter_resolutions_for_bundles(read_all_staged_resolutions(conn), labels)


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

    Resolution-scoped items in ``resolved`` status contribute their
    recorded human decision. Items in ``dismissed`` status contribute
    an explicit ``uncertain`` decision: dismissal is a durable,
    auditable terminal state of the review (the row stays with its
    ``resolved_at`` stamp), so finalization can distinguish "reviewed
    and set aside, keep distinct" from "never reviewed". Candidates
    with no item at all — genuinely unreviewed, or bound to a changed
    initial artifact — stay absent, and finalization with
    ``require_complete=True`` still fails closed on those.
    """
    rows = conn.execute(
        """
        SELECT status, payload FROM chronicle.review_items
        WHERE job_id = %s AND status IN ('resolved', 'dismissed')
        ORDER BY created_at, review_id
        """,
        (job_id,),
    ).fetchall()
    decisions: dict[str, dict[str, Any]] = {}
    for status, payload in rows:
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("scope") != REVIEW_SCOPE:
            continue
        key = _candidate_key(
            str(payload.get("resolution_sha256") or ""),
            str(payload.get("candidate_id") or ""),
        )
        if status == "dismissed":
            decisions[key] = {
                "decision": "uncertain",
                "confidence": CONFIDENCE_INITIAL_UNCERTAIN,
                "rationale": (
                    "Resolution review dismissed without a same/not-same "
                    "decision; the candidate is kept distinct as explicit "
                    "uncertain and remains reviewable."
                ),
                "dismissed": True,
            }
            continue
        decision = payload.get("decision")
        if not isinstance(decision, dict):
            continue
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
