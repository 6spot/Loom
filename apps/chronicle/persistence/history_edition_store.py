"""Durable Chronicle history-edition publication and bounded read helpers.

The pure ordering/mapping rules live in :mod:`history_edition_contract`.  This
module supplies the application-owned PostgreSQL boundary around that
contract.  Published editions and their indexes are append-only; the only
mutable public pointer is ``history_edition_latest``.  Fragment content is
read from the already published narrative record (or from an immutable draft
snapshot for contract fixtures), never generated at read time.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from psycopg.types.json import Jsonb

import control_plane
import history_edition_contract as contract
import resolve_publish
from common import LeaseLost, PersistenceConflict, PersistenceError, sha256_json


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRAFT_STATUSES = ("draft", "published", "conflict")
_EDITION_SCOPE = "history_edition"
_REVIEW_KIND = "stage_gate"


class HistoryEditionNotFound(PersistenceError):
    """A fixed edition/draft/fragment was not present."""


class HistoryEditionConflict(PersistenceConflict):
    """A draft, baseline, source fragment, or review moved concurrently."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: Any, description: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        raise PersistenceError(f"{description} must be a UUID string")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise PersistenceError(f"{description} is not a valid UUID") from exc


def _sha(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PersistenceError(f"{description} must be a lowercase SHA-256")
    return value


def _copy_json(value: Any) -> Any:
    return copy.deepcopy(value)


def _latest_version(conn, *, lock: bool = False) -> str | None:
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute(
        "SELECT edition_version FROM chronicle.history_edition_latest "
        "WHERE pointer_key = 'history'" + suffix
    ).fetchone()
    return str(row[0]) if row is not None else None


def _edition_row(conn, version: str, *, include_manifest: bool = False):
    columns = (
        "edition_version, manifest_sha256, content_sha256, fragment_count, "
        "paragraph_count, metadata, publication_sequence, published_at"
        + (", manifest" if include_manifest else "")
    )
    return conn.execute(
        f"SELECT {columns} FROM chronicle.history_editions WHERE edition_version = %s",
        (version,),
    ).fetchone()


def _metadata_from_row(row: Sequence[Any]) -> dict[str, Any]:
    metadata = _copy_json(row[5]) if isinstance(row[5], dict) else {}
    result = {
        "version": str(row[0]),
        "edition_version": str(row[0]),
        "manifest_sha256": str(row[1]),
        "content_sha256": str(row[2]),
        "fragment_count": int(row[3]),
        "paragraph_count": int(row[4]),
        "publication_sequence": int(row[6]),
        **metadata,
    }
    if row[7] is not None:
        result["published_at"] = row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7])
    return result


def read_latest_metadata(conn) -> dict[str, Any] | None:
    """Read only the latest edition header and curated navigation metadata."""

    version = _latest_version(conn)
    if version is None:
        return None
    row = _edition_row(conn, version)
    if row is None:
        # A dangling pointer is an invariant violation, not an empty state.
        raise PersistenceError("history edition latest pointer has no target")
    return _metadata_from_row(row)


def read_edition_metadata(conn, version: str) -> dict[str, Any] | None:
    """Read the exact edition header; never substitute the current edition."""

    _sha(version, "edition version")
    row = _edition_row(conn, version)
    return _metadata_from_row(row) if row is not None else None


def read_edition_manifest(conn, version: str) -> dict[str, Any] | None:
    """Internal/audit helper for the complete immutable manifest."""

    _sha(version, "edition version")
    row = _edition_row(conn, version, include_manifest=True)
    return _copy_json(row[8]) if row is not None else None


def _load_published_fragment(conn, version: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT payload FROM chronicle.historical_narratives WHERE version_sha = %s",
        (version,),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise HistoryEditionNotFound(f"unknown history fragment {version}")
    fragment = _copy_json(row[0])
    # T09 predates the explicit fragment marker.  These defaults describe the
    # existing immutable publication record; they do not make an unpublished
    # candidate readable.
    fragment.setdefault("publication_status", "published")
    fragment.setdefault("publication_version", version)
    fragment.setdefault("publication_id", version)
    return _normalise_legacy_fragment_scope(fragment)


def _normalise_legacy_fragment_scope(fragment: dict[str, Any]) -> dict[str, Any]:
    """Bind pre-T10 evidence rows to the immutable narrative fragment.

    Older narrative payloads used ``publication_id`` for the source chapter
    that supplied one evidence item.  T10 needs that field to identify the
    owning fragment, so retain the old value as ``source_publication_id`` and
    close each evidence record over the fragment publication id.
    """

    result = _copy_json(fragment)
    publication_id = result.get("publication_id")
    evidence = result.get("evidence")
    if isinstance(evidence, dict):
        for item in evidence.values():
            if not isinstance(item, dict):
                continue
            if item.get("publication_id") != publication_id:
                item.setdefault("source_publication_id", item.get("publication_id"))
                item["publication_id"] = publication_id
    elif isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            if item.get("publication_id") != publication_id:
                item.setdefault("source_publication_id", item.get("publication_id"))
                item["publication_id"] = publication_id
    return result


def _fragment_from_input(
    conn,
    value: Any,
    *,
    coverage_overrides: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Resolve a Studio/reference input to one immutable fragment snapshot."""

    source_version: str | None = None
    fragment: dict[str, Any] | None = None
    if isinstance(value, str):
        source_version = value
        fragment = _load_published_fragment(conn, value)
    elif isinstance(value, dict):
        source_version = value.get("fragment_version") or value.get("publication_version")
        nested = value.get("fragment")
        if isinstance(nested, dict):
            fragment = _copy_json(nested)
        elif isinstance(value.get("payload"), dict) and value["payload"].get("schema"):
            fragment = _copy_json(value["payload"])
        elif value.get("schema") == contract.PUBLISHED_FRAGMENT_SCHEMA:
            fragment = _copy_json(value)
        elif source_version:
            fragment = _load_published_fragment(conn, str(source_version))
        else:
            raise PersistenceError("each history fragment selection needs a version or fragment payload")
        if source_version is None:
            source_version = fragment.get("publication_version") or fragment.get("fragment_version")
        # Selection metadata may provide the explicit non-year coverage for a
        # legacy narrative row.  It is copied into the draft snapshot and is
        # subsequently hash-bound by the edition manifest.
        if isinstance(value.get("coverage"), dict):
            fragment["coverage"] = _copy_json(value["coverage"])
        if value.get("publication_id") is not None:
            fragment["publication_id"] = value["publication_id"]
    else:
        raise PersistenceError("history fragment selections must be strings or objects")

    if not isinstance(fragment, dict):
        raise PersistenceError("history fragment payload must be an object")
    if coverage_overrides and source_version in coverage_overrides:
        fragment["coverage"] = _copy_json(coverage_overrides[source_version])
    if not isinstance(fragment.get("publication_version"), str):
        if isinstance(fragment.get("fragment_version"), str):
            fragment["publication_version"] = fragment["fragment_version"]
        elif source_version:
            fragment["publication_version"] = source_version
    fragment.setdefault("publication_status", "published")
    fragment.setdefault("publication_id", fragment.get("publication_version"))
    return _normalise_legacy_fragment_scope(fragment), str(source_version) if source_version is not None else None


def _fragment_list(
    conn,
    fragments: Sequence[Any] | None,
    fragment_versions: Sequence[Any] | None,
    *,
    fragment_coverages: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if fragments is None:
        fragments = fragment_versions
    if not isinstance(fragments, (list, tuple)) or not fragments:
        raise PersistenceError("history edition requires a non-empty ordered fragment list")
    result = []
    for value in fragments:
        fragment, _source = _fragment_from_input(
            conn, value, coverage_overrides=fragment_coverages
        )
        # Validate each source before any draft or edition row is written.
        contract.validate_published_fragment(fragment)
        result.append(fragment)
    return result


def _review_decision(payload: Mapping[str, Any]) -> str | None:
    decision = payload.get("decision")
    if isinstance(decision, dict):
        decision = decision.get("decision")
    if not isinstance(decision, str):
        return None
    return decision.lower()


def _review_boundary_payload(
    conn,
    value: Any,
    *,
    default: Mapping[str, Any] | None = None,
    expected_job: uuid.UUID | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Return a contract boundary review and its durable ReviewItem id."""

    review_id: str | None = None
    item = value
    row = None
    if isinstance(value, str):
        review_id = value
    elif isinstance(value, dict):
        raw_id = value.get("review_id")
        if raw_id is not None:
            review_id = str(raw_id)
        item = value.get("boundary") if isinstance(value.get("boundary"), dict) else value
    if review_id is not None:
        parsed = _uuid(review_id, "boundary review id")
        row = conn.execute(
            "SELECT job_id, status, payload FROM chronicle.review_items WHERE review_id = %s",
            (parsed,),
        ).fetchone()
        if row is None:
            raise HistoryEditionNotFound(f"unknown boundary review {review_id}")
        if expected_job is not None and row[0] != expected_job:
            raise HistoryEditionConflict("boundary review belongs to another job")
        raw_payload = row[2] if isinstance(row[2], dict) else {}
        if raw_payload.get("scope") != _EDITION_SCOPE:
            raise PersistenceConflict("review item is not a history-edition seam review")
        candidate = raw_payload.get("boundary") if isinstance(raw_payload.get("boundary"), dict) else raw_payload
        item = {**(candidate if isinstance(candidate, dict) else {})}
        if isinstance(value, dict):
            # Caller-supplied locator fields are useful for a pending review,
            # but the ReviewItem remains the authority for its status.
            for key in (
                "left_fragment_version", "right_fragment_version", "geometry",
                "review_basis", "note",
            ):
                if key in value:
                    item[key] = _copy_json(value[key])
        accepted = row[1] == "resolved" and _review_decision(raw_payload) in {
            "accept", "accepted", "approve", "approved", "coherent",
        }
        item["status"] = "accepted" if accepted else "pending"
    if not isinstance(item, dict):
        item = {}
    if default:
        merged = _copy_json(dict(default))
        merged.update(item)
        item = merged
    item.setdefault("status", "pending")
    if review_id is not None:
        item["review_id"] = review_id
    return item, review_id


def _review_inputs(
    conn,
    values: Iterable[Any] | None,
    *,
    seams: Sequence[Mapping[str, Any]] | None = None,
    expected_job: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    supplied = list(values or [])
    result: list[dict[str, Any]] = []
    for value in supplied:
        item, _review_id = _review_boundary_payload(conn, value, expected_job=expected_job)
        result.append(item)
    # Fill a ReviewItem-backed review with the seam locator when the caller
    # supplied only an ID.  Missing seams remain missing so the pure contract
    # reports boundary_review_missing instead of auto-accepting anything.
    if seams:
        for seam in seams:
            key = (
                seam.get("left_fragment_version"),
                seam.get("right_fragment_version"),
            )
            for item in result:
                if (
                    item.get("left_fragment_version"),
                    item.get("right_fragment_version"),
                ) == key:
                    break
    return result


def _review_refs_for_draft(
    conn, stored: Any, *, expected_job: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    if not isinstance(stored, list):
        return []
    result = []
    for value in stored:
        item, _ = _review_boundary_payload(conn, value, expected_job=expected_job)
        result.append(item)
    return result


def _draft_row(conn, draft_id: uuid.UUID, *, lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    return conn.execute(
        "SELECT draft_id, baseline_manifest_sha256, fragment_snapshots, "
        "boundary_reviews, navigation, lineage, status, edition_version, job_id, "
        "created_at, updated_at FROM chronicle.history_edition_drafts "
        "WHERE draft_id = %s" + suffix,
        (draft_id,),
    ).fetchone()


def _draft_projection(conn, row: Sequence[Any], *, include_fragments: bool = True) -> dict[str, Any]:
    snapshots = row[2] if isinstance(row[2], list) else []
    refs = []
    for fragment in snapshots:
        if not isinstance(fragment, dict):
            continue
        try:
            info = contract.validate_published_fragment(fragment)
        except contract.HistoryEditionError:
            continue
        refs.append({
            "fragment_version": info["version"],
            "publication_id": info["publication_id"],
            "content_sha256": info["content_sha256"],
            "paragraph_count": len(info["paragraphs"]),
            "coverage": _copy_json(info["coverage"]),
        })
    result: dict[str, Any] = {
        "draft_id": str(row[0]),
        "baseline_manifest_sha256": row[1],
        "fragments": refs,
        "fragment_versions": [item["fragment_version"] for item in refs],
        "boundary_reviews": _copy_json(row[3]) if isinstance(row[3], list) else [],
        "boundaries": contract.inspect_boundaries(snapshots, _review_refs_for_draft(conn, row[3])) if snapshots else [],
        "navigation": _copy_json(row[4]) if isinstance(row[4], list) else None,
        "lineage": _copy_json(row[5]) if isinstance(row[5], dict) else None,
        "status": row[6],
        "edition_version": str(row[7]) if row[7] is not None else None,
        "job_id": str(row[8]) if row[8] is not None else None,
        "created_at": row[9].isoformat() if hasattr(row[9], "isoformat") else str(row[9]),
        "updated_at": row[10].isoformat() if hasattr(row[10], "isoformat") else str(row[10]),
    }
    if include_fragments:
        result["fragment_snapshots"] = _copy_json(snapshots)
    return result


def create_draft(
    conn,
    *,
    fragments: Sequence[Any] | None = None,
    fragment_versions: Sequence[Any] | None = None,
    boundary_reviews: Sequence[Any] | None = None,
    navigation: Sequence[Mapping[str, Any]] | None = None,
    baseline_manifest_sha256: str | None = None,
    fragment_coverages: Mapping[str, Any] | None = None,
    lineage: Mapping[str, Any] | None = None,
    operation: str | None = None,
    replacement_range: Mapping[str, Any] | None = None,
    job_id: uuid.UUID | str | None = None,
    worker: str | None = None,
) -> dict[str, Any]:
    """Persist a Studio-selected draft and durable pending seam reviews.

    Draft creation snapshots the exact source fragments and current edition
    baseline.  It deliberately does not publish or infer that a pending seam
    is coherent.  If a job is supplied, each missing/pending adjacent seam is
    represented by the existing ``stage_gate`` ReviewItem kind.
    """

    parsed_job = _uuid(job_id, "job id") if job_id is not None else None
    draft_id = uuid.uuid4()
    with conn.transaction():
        if worker is not None and parsed_job is None:
            raise PersistenceError("worker requires a job id")
        if parsed_job is not None and worker is not None:
            control_plane.require_job_lease(conn, job_id=parsed_job, worker=worker)
        resolve_publish.acquire_publish_lock(conn)
        current = _latest_version(conn, lock=True)
        if baseline_manifest_sha256 is not None:
            _sha(baseline_manifest_sha256, "baseline_manifest_sha256")
            if current != baseline_manifest_sha256:
                raise contract.HistoryEditionError(
                    "baseline_changed",
                    f"current history edition is {current!r}, not {baseline_manifest_sha256!r}",
                )
        baseline = baseline_manifest_sha256 if baseline_manifest_sha256 is not None else current
        snapshots = _fragment_list(
            conn, fragments, fragment_versions, fragment_coverages=fragment_coverages
        )
        boundary_rows = _review_inputs(
            conn, boundary_reviews, expected_job=parsed_job
        )
        if parsed_job is not None and any(
            item.get("status") == "accepted" and not item.get("review_id")
            for item in boundary_rows
        ):
            raise PersistenceConflict(
                "job-bound history seams must be accepted through an existing ReviewItem"
            )
        boundaries = contract.inspect_boundaries(snapshots, boundary_rows)
        stored_reviews: list[dict[str, Any]] = [
            _copy_json(item) for item in boundary_rows
        ]
        existing_keys = {
            (item.get("left_fragment_version"), item.get("right_fragment_version"))
            for item in stored_reviews
        }
        if parsed_job is not None:
            for seam in boundaries:
                key = (seam["left_fragment_version"], seam["right_fragment_version"])
                if key in existing_keys and any(
                    item.get("status") == "accepted" for item in stored_reviews
                    if (item.get("left_fragment_version"), item.get("right_fragment_version")) == key
                ):
                    continue
                if key in existing_keys:
                    continue
                review_id = control_plane.open_review_item(
                    conn,
                    job_id=parsed_job,
                    kind=_REVIEW_KIND,
                    payload={
                        "scope": _EDITION_SCOPE,
                        "review_mode": _EDITION_SCOPE,
                        "draft_id": str(draft_id),
                        "boundary": {
                            "left_fragment_version": key[0],
                            "right_fragment_version": key[1],
                            "geometry": seam["geometry"],
                            "status": "pending",
                            "review_basis": [],
                        },
                        "left_fragment_version": key[0],
                        "right_fragment_version": key[1],
                        "geometry": seam["geometry"],
                        "status": "pending",
                    },
                )
                stored_reviews.append({
                    "review_id": str(review_id),
                    "left_fragment_version": key[0],
                    "right_fragment_version": key[1],
                    "geometry": seam["geometry"],
                    "status": "pending",
                })
                existing_keys.add(key)
        stored_lineage = _copy_json(dict(lineage)) if isinstance(lineage, Mapping) else {}
        if operation is not None:
            if operation not in ("append", "replace"):
                raise PersistenceError("history edition operation must be append or replace")
            stored_lineage.setdefault("operation", operation)
            if operation == "replace":
                if not isinstance(replacement_range, Mapping):
                    raise contract.HistoryEditionError(
                        "replacement_range_invalid", "replace requires an exact replacement_range"
                    )
                stored_lineage["replacement_range"] = _copy_json(dict(replacement_range))
        conn.execute(
            "INSERT INTO chronicle.history_edition_drafts "
            "(draft_id, baseline_manifest_sha256, fragment_snapshots, boundary_reviews, "
            "navigation, lineage, status, job_id) VALUES (%s,%s,%s,%s,%s,%s,'draft',%s)",
            (
                draft_id,
                baseline,
                Jsonb(snapshots),
                Jsonb(stored_reviews),
                Jsonb(_copy_json(list(navigation)) if isinstance(navigation, list) else None),
                Jsonb(stored_lineage),
                parsed_job,
            ),
        )
        row = _draft_row(conn, draft_id)
        assert row is not None
        result = _draft_projection(conn, row)
        result["boundaries"] = boundaries
        result["current_baseline_manifest_sha256"] = current
        return result


def read_draft(conn, draft_id: uuid.UUID | str, *, include_fragments: bool = True) -> dict[str, Any] | None:
    parsed = _uuid(draft_id, "draft id")
    row = _draft_row(conn, parsed)
    return _draft_projection(conn, row, include_fragments=include_fragments) if row else None


def list_drafts(conn, *, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    if status is not None and status not in _DRAFT_STATUSES:
        raise PersistenceError(f"draft status must be one of {_DRAFT_STATUSES}")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PersistenceError("draft limit must be between 1 and 100")
    if type(offset) is not int or offset < 0:
        raise PersistenceError("draft offset must be nonnegative")
    where = ""
    params: list[Any] = []
    if status is not None:
        where = " WHERE status = %s"
        params.append(status)
    rows = conn.execute(
        "SELECT draft_id, baseline_manifest_sha256, fragment_snapshots, boundary_reviews, "
        "navigation, lineage, status, edition_version, job_id, created_at, updated_at "
        "FROM chronicle.history_edition_drafts" + where
        + " ORDER BY updated_at DESC, draft_id DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    ).fetchall()
    items = [_draft_projection(conn, row, include_fragments=False) for row in rows]
    return {"schema": "chronicle.history-edition-draft-list", "version": "0.1", "items": items, "offset": offset, "has_more": len(items) == limit}


def list_published_fragments(conn, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PersistenceError("fragment limit must be between 1 and 100")
    if type(offset) is not int or offset < 0:
        raise PersistenceError("fragment offset must be nonnegative")
    rows = conn.execute(
        "SELECT version_sha, catalog_sha, job_id, publication_sequence, published_at, "
        "payload->>'publication_id', payload->>'title', "
        "jsonb_array_length(COALESCE(payload->'paragraphs','[]'::jsonb)), "
        "payload->'coverage', payload->>'publication_status' "
        "FROM chronicle.historical_narratives ORDER BY publication_sequence DESC, version_sha DESC "
        "LIMIT %s OFFSET %s",
        (limit, offset),
    ).fetchall()
    items = []
    for row in rows:
        items.append({
            "fragment_version": str(row[0]),
            "publication_id": row[5] or str(row[0]),
            "catalog_sha": row[1],
            "job_id": str(row[2]),
            "publication_sequence": int(row[3]),
            "published_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
            "title": row[6],
            "paragraph_count": int(row[7] or 0),
            "coverage": _copy_json(row[8]) if isinstance(row[8], dict) else None,
            "publication_status": row[9] or "published",
        })
    return {"schema": "chronicle.history-fragment-list", "version": "0.1", "items": items, "offset": offset, "has_more": len(items) == limit}


def _source_snapshot_is_current(conn, fragment: Mapping[str, Any]) -> None:
    version = fragment.get("publication_version") or fragment.get("fragment_version")
    if not isinstance(version, str):
        raise PersistenceConflict("draft fragment has no immutable publication version")
    row = conn.execute(
        "SELECT payload FROM chronicle.historical_narratives WHERE version_sha = %s",
        (version,),
    ).fetchone()
    if row is None:
        # Contract fixtures and future registered fragment tables may not use
        # historical_narratives; their complete snapshot is still immutable in
        # the draft until an owning source record is registered.
        return
    current = _copy_json(row[0]) if isinstance(row[0], dict) else None
    if current is None:
        raise HistoryEditionConflict(f"source fragment {version} is no longer readable")
    current.setdefault("publication_status", "published")
    current.setdefault("publication_version", version)
    current.setdefault("publication_id", version)
    current = _normalise_legacy_fragment_scope(current)
    def source_hash(value: Mapping[str, Any]) -> str:
        # Coverage/publication markers are the edition-selection envelope for
        # legacy rows; paragraph/phase/conclusion/evidence content remains
        # source-owned and is still fully hash checked.
        payload = _copy_json(dict(value))
        for key in ("coverage", "publication_status", "publication_id"):
            payload.pop(key, None)
        return sha256_json(payload)

    if source_hash(current) != source_hash(fragment):
        raise HistoryEditionConflict(
            f"source fragment {version} changed after the edition draft was created"
        )


def _metadata_for_manifest(manifest: Mapping[str, Any], fragments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    first = fragments[0] if fragments else {}
    paragraphs = manifest.get("paragraphs") if isinstance(manifest.get("paragraphs"), list) else []
    navigation = _copy_json(manifest.get("navigation") or [])
    entry_points = [
        _copy_json(item)
        for item in navigation
        if isinstance(item, Mapping)
    ]
    return {
        "title": first.get("title"),
        "catalog_sha": first.get("catalog_sha"),
        "first_paragraph_id": paragraphs[0].get("paragraph_id") if paragraphs else None,
        "last_paragraph_id": paragraphs[-1].get("paragraph_id") if paragraphs else None,
        "navigation": navigation,
        "entry_points": entry_points,
        "lineage": _copy_json(manifest.get("lineage")) if isinstance(manifest.get("lineage"), dict) else None,
    }


def _insert_or_verify_edition(
    conn,
    *,
    manifest: Mapping[str, Any],
    fragments: Sequence[Mapping[str, Any]],
    job_id: uuid.UUID | None,
) -> None:
    version = _sha(manifest["version"], "edition version")
    metadata = _metadata_for_manifest(manifest, fragments)
    row = conn.execute(
        "INSERT INTO chronicle.history_editions "
        "(edition_version, manifest_sha256, content_sha256, fragment_count, paragraph_count, manifest, metadata, job_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (edition_version) DO NOTHING RETURNING edition_version",
        (
            version,
            version,
            manifest["content_sha256"],
            manifest["fragment_count"],
            manifest["paragraph_count"],
            Jsonb(_copy_json(dict(manifest))),
            Jsonb(metadata),
            job_id,
        ),
    ).fetchone()
    if row is None:
        existing = _edition_row(conn, version, include_manifest=True)
        if existing is None or existing[8] != manifest:
            raise HistoryEditionConflict("edition version already exists with different content")
        return

    for ordinal, fragment in enumerate(fragments):
        info = contract.validate_published_fragment(fragment)
        source_version = info["version"]
        conn.execute(
            "INSERT INTO chronicle.history_edition_fragments "
            "(edition_version, fragment_ordinal, fragment_version, publication_id, content_sha256, coverage, fragment_payload, source_publication_version) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                version,
                ordinal,
                source_version,
                info["publication_id"],
                info["content_sha256"],
                Jsonb(info["coverage"]),
                Jsonb(_copy_json(fragment)),
                source_version,
            ),
        )
    for item in manifest["paragraphs"]:
        conn.execute(
            "INSERT INTO chronicle.history_edition_paragraph_index "
            "(edition_version, ordinal, paragraph_id, fragment_version, source_paragraph_id, source_ordinal, phase_id, conclusion_ids, content_ref) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                version,
                item["ordinal"],
                item["paragraph_id"],
                item["fragment_version"],
                item["source_paragraph_id"],
                item["source_ordinal"],
                item["phase_id"],
                Jsonb(_copy_json(item["conclusion_ids"])),
                Jsonb(_copy_json(item["content_ref"])),
            ),
        )
    for item in manifest["phases"]:
        conn.execute(
            "INSERT INTO chronicle.history_edition_phase_index "
            "(edition_version, phase_id, fragment_version, source_phase_id, payload) VALUES (%s,%s,%s,%s,%s)",
            (
                version,
                item["phase_id"],
                item["fragment_version"],
                item["source"]["phase_id"],
                Jsonb(_copy_json(item)),
            ),
        )
    for item in manifest["conclusions"]:
        conn.execute(
            "INSERT INTO chronicle.history_edition_conclusion_index "
            "(edition_version, conclusion_id, fragment_version, source_conclusion_id, phase_ids, evidence, payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                version,
                item["conclusion_id"],
                item["fragment_version"],
                item["source"]["conclusion_id"],
                Jsonb(_copy_json(item["phase_ids"])),
                Jsonb(_copy_json(item["evidence"])),
                Jsonb(_copy_json(item)),
            ),
        )


def _fragment_for_version(fragments: Sequence[Mapping[str, Any]], version: str) -> Mapping[str, Any]:
    for fragment in fragments:
        if fragment.get("publication_version") == version or fragment.get("fragment_version") == version:
            return fragment
    raise PersistenceError(f"edition fragment {version} is missing from the draft snapshot")


def _compile_for_draft(
    conn,
    *,
    fragments: Sequence[Mapping[str, Any]],
    boundary_reviews: Sequence[Mapping[str, Any]],
    navigation: Sequence[Mapping[str, Any]] | None,
    lineage: Mapping[str, Any] | None,
    baseline: str | None,
) -> dict[str, Any]:
    operation = lineage.get("operation") if isinstance(lineage, Mapping) else None
    previous = read_edition_manifest(conn, baseline) if baseline else None
    if operation == "append":
        if previous is None or baseline is None:
            raise contract.HistoryEditionError("baseline_changed", "append requires a current baseline edition")
        return contract.append_history_edition(
            previous,
            fragments,
            baseline_manifest_sha256=baseline,
            boundary_reviews=boundary_reviews,
            navigation=navigation,
        )
    if operation == "replace":
        if previous is None or baseline is None:
            raise contract.HistoryEditionError("baseline_changed", "replace requires a current baseline edition")
        replacement_range = lineage.get("replacement_range") if isinstance(lineage, Mapping) else None
        return contract.replace_history_edition(
            previous,
            fragments,
            replacement_range=replacement_range,
            baseline_manifest_sha256=baseline,
            boundary_reviews=boundary_reviews,
            navigation=navigation,
        )
    return contract.compile_history_edition(
        fragments,
        boundary_reviews=boundary_reviews,
        navigation=navigation,
        lineage=lineage if isinstance(lineage, Mapping) and lineage else None,
    )


def publish_draft(
    conn,
    draft_id: uuid.UUID | str,
    *,
    job_id: uuid.UUID | str | None = None,
    worker: str | None = None,
    baseline_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Atomically publish one draft after rechecking baseline, reviews, and lease."""

    parsed_draft = _uuid(draft_id, "draft id")
    requested_job = _uuid(job_id, "job id") if job_id is not None else None
    with conn.transaction():
        # Preserve the established job -> publication-lock ordering used by
        # narrative_store.publish and catalog publication.
        draft_peek = _draft_row(conn, parsed_draft)
        if draft_peek is None:
            raise HistoryEditionNotFound(f"unknown history edition draft {draft_id}")
        stored_job = draft_peek[8]
        effective_job = requested_job or stored_job
        if stored_job is not None and requested_job is not None and stored_job != requested_job:
            raise HistoryEditionConflict("edition draft belongs to another job")
        if effective_job is not None and not worker:
            raise LeaseLost("history edition publication requires the owning job lease")
        if worker and effective_job is None:
            raise PersistenceError("worker requires a job-bound history edition draft")
        if effective_job is not None:
            control_plane.require_job_lease(conn, job_id=effective_job, worker=worker)
        resolve_publish.acquire_publish_lock(conn)
        if effective_job is not None:
            resolve_publish.require_unexpired_lease(conn, job_id=effective_job, worker=worker)
        row = _draft_row(conn, parsed_draft, lock=True)
        if row is None:
            raise HistoryEditionNotFound(f"unknown history edition draft {draft_id}")
        if row[6] == "published" and row[7] is not None:
            manifest = read_edition_manifest(conn, str(row[7]))
            if manifest is None:
                raise PersistenceError("published history draft points to a missing edition")
            return _metadata_from_row(_edition_row(conn, str(row[7])))
        if row[6] not in ("draft", "conflict"):
            raise HistoryEditionConflict(f"history edition draft is already {row[6]!r}")
        stored_baseline = row[1]
        if baseline_manifest_sha256 is not None:
            _sha(baseline_manifest_sha256, "baseline_manifest_sha256")
            if stored_baseline != baseline_manifest_sha256:
                raise contract.HistoryEditionError(
                    "baseline_changed",
                    "publish baseline differs from the baseline captured by the draft",
                )
        baseline = baseline_manifest_sha256 if baseline_manifest_sha256 is not None else stored_baseline
        current = _latest_version(conn, lock=True)
        if current != baseline:
            raise contract.HistoryEditionError(
                "baseline_changed",
                f"current history edition is {current!r}, draft baseline is {baseline!r}",
            )
        fragments = row[2] if isinstance(row[2], list) else []
        for fragment in fragments:
            if not isinstance(fragment, dict):
                raise PersistenceError("history edition draft contains an invalid fragment snapshot")
            _source_snapshot_is_current(conn, fragment)
        boundary_reviews = _review_refs_for_draft(
            conn, row[3], expected_job=effective_job
        )
        navigation = row[4] if isinstance(row[4], list) else None
        lineage = row[5] if isinstance(row[5], dict) else None
        # No edition write happens until every seam is durably accepted and the
        # pure compiler has validated all local/global references.
        manifest = _compile_for_draft(
            conn,
            fragments=fragments,
            boundary_reviews=boundary_reviews,
            navigation=navigation,
            lineage=lineage,
            baseline=baseline,
        )
        contract.validate_history_edition(manifest, fragments)
        if effective_job is not None:
            resolve_publish.require_unexpired_lease(conn, job_id=effective_job, worker=worker)
        _insert_or_verify_edition(
            conn, manifest=manifest, fragments=fragments, job_id=effective_job
        )
        # The pointer is the sole public frontier and is updated only after all
        # immutable index inserts have succeeded.
        if effective_job is not None:
            resolve_publish.require_unexpired_lease(conn, job_id=effective_job, worker=worker)
        conn.execute(
            "INSERT INTO chronicle.history_edition_latest(pointer_key, edition_version) "
            "VALUES ('history', %s) ON CONFLICT (pointer_key) DO UPDATE SET edition_version = EXCLUDED.edition_version, updated_at = clock_timestamp()",
            (manifest["version"],),
        )
        conn.execute(
            "UPDATE chronicle.history_edition_drafts SET status = 'published', edition_version = %s, updated_at = clock_timestamp() WHERE draft_id = %s",
            (manifest["version"], parsed_draft),
        )
        if effective_job is not None:
            # Final live-clock fence: if the lease expired while the bounded
            # index rows/pointer were being written, roll back the whole
            # transaction instead of exposing a publication by a stale worker.
            resolve_publish.require_unexpired_lease(conn, job_id=effective_job, worker=worker)
        return _metadata_from_row(_edition_row(conn, manifest["version"]))


def publish_narrative_fragment(
    conn,
    *,
    fragment_version: str,
    job_id: uuid.UUID | str,
    worker: str,
) -> dict[str, Any]:
    """Publish one approved narrative fragment as the current edition.

    The normal narrative acceptance path produces a complete, reviewed
    fragment.  It therefore has no cross-fragment seam to review, but it must
    still pass through the same draft snapshot, baseline, source-integrity,
    publication-lock, and lease fences as an explicitly composed edition.
    """

    draft = create_draft(
        conn,
        fragment_versions=[fragment_version],
        job_id=job_id,
        worker=worker,
    )
    return publish_draft(conn, draft["draft_id"], job_id=job_id, worker=worker)


def _source_paragraph(fragment: Mapping[str, Any], local_id: str) -> dict[str, Any] | None:
    paragraphs = fragment.get("paragraphs") if isinstance(fragment.get("paragraphs"), list) else []
    for paragraph in paragraphs:
        if isinstance(paragraph, dict) and paragraph.get("id") == local_id:
            return _copy_json(paragraph)
    return None


def _source_record(fragment: Mapping[str, Any], field: str, local_id: str) -> dict[str, Any] | None:
    raw = fragment.get(field)
    records: list[Any]
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = [{"id": key, **value} for key, value in raw.items() if isinstance(value, dict)]
    else:
        records = []
    for record in records:
        if isinstance(record, dict) and record.get("id") == local_id:
            return _copy_json(record)
    return None


def _mapped_paragraph(
    paragraph: Mapping[str, Any], index_row: Sequence[Any], fragment: Mapping[str, Any]
) -> dict[str, Any]:
    global_id, ordinal, fragment_version, source_id, source_ordinal, phase_id, conclusion_ids, content_ref = index_row
    result = _copy_json(dict(paragraph))
    result.update({
        "id": str(global_id),
        "paragraph_id": str(global_id),
        "ordinal": int(ordinal),
        "fragment_version": fragment_version,
        "source_paragraph_id": source_id,
        "source_ordinal": int(source_ordinal),
        "source": _copy_json(content_ref),
        "content_ref": _copy_json(content_ref),
        "phase_id": phase_id,
    })
    local_conclusions = []
    for segment in result.get("segments", []) if isinstance(result.get("segments"), list) else []:
        if not isinstance(segment, dict):
            continue
        source_ids = list(segment.get("conclusion_ids") or [])
        segment["source_conclusion_ids"] = source_ids
        segment["conclusion_ids"] = [
            contract.derive_global_conclusion_id(fragment_version, value)
            for value in source_ids if isinstance(value, str)
        ]
        event_id = segment.get("event_id")
        if isinstance(event_id, str):
            segment["source_event_id"] = event_id
            segment["event_id"] = contract.derive_scoped_id("event", fragment_version, event_id)
        local_conclusions.extend(source_ids)
    for entity in result.get("entities", []) if isinstance(result.get("entities"), list) else []:
        if not isinstance(entity, dict):
            continue
        for state in entity.get("states", []) if isinstance(entity.get("states"), list) else []:
            if isinstance(state, dict):
                local_id = state.get("id", state.get("conclusion_id"))
                if isinstance(local_id, str):
                    state["source_conclusion_id"] = local_id
                    state["id"] = contract.derive_global_conclusion_id(fragment_version, local_id)
    result["conclusion_ids"] = list(conclusion_ids) if isinstance(conclusion_ids, list) else list(dict.fromkeys(local_conclusions))
    result["group_id"] = result.get("group_id") or phase_id
    return result


def read_paragraph_page(
    conn,
    *,
    version: str,
    start: int = 0,
    limit: int = 20,
    at: str | None = None,
) -> dict[str, Any]:
    _sha(version, "edition version")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise PersistenceError("history page limit must be between 1 and 50")
    if type(start) is not int or start < 0:
        raise PersistenceError("history page start must be nonnegative")
    if at is not None:
        row = conn.execute(
            "SELECT ordinal FROM chronicle.history_edition_paragraph_index WHERE edition_version = %s AND paragraph_id = %s",
            (version, at),
        ).fetchone()
        if row is None:
            raise HistoryEditionNotFound("paragraph is outside this fixed edition")
        start = int(row[0]) // limit * limit
    total_row = conn.execute(
        "SELECT paragraph_count FROM chronicle.history_editions WHERE edition_version = %s",
        (version,),
    ).fetchone()
    if total_row is None:
        raise HistoryEditionNotFound("this history edition version is not published")
    total = int(total_row[0])
    if start >= total:
        raise PersistenceError("history page start is outside this fixed edition")
    rows = conn.execute(
        "SELECT p.paragraph_id, p.ordinal, p.fragment_version, p.source_paragraph_id, "
        "p.source_ordinal, p.phase_id, p.conclusion_ids, p.content_ref, f.fragment_payload "
        "FROM chronicle.history_edition_paragraph_index p "
        "JOIN chronicle.history_edition_fragments f USING (edition_version, fragment_version) "
        "WHERE p.edition_version = %s AND p.ordinal >= %s ORDER BY p.ordinal LIMIT %s",
        (version, start, limit),
    ).fetchall()
    paragraphs = []
    for row in rows:
        fragment = row[8] if isinstance(row[8], dict) else {}
        source = _source_paragraph(fragment, str(row[3]))
        if source is None:
            raise PersistenceError("history edition paragraph source mapping is missing")
        paragraphs.append(_mapped_paragraph(source, row[:8], fragment))
    end = start + len(paragraphs)
    return {
        "schema": "chronicle.history-page",
        "version": "0.1",
        "edition_version": version,
        "publication_version": version,
        "paragraphs": paragraphs,
        "start": start,
        "total": total,
        "previous_start": max(0, start - limit) if start else None,
        "next_start": end if end < total else None,
    }


def read_conclusion(conn, *, version: str, conclusion_id: str) -> dict[str, Any]:
    _sha(version, "edition version")
    row = conn.execute(
        "SELECT c.conclusion_id, c.fragment_version, c.source_conclusion_id, c.phase_ids, c.evidence, c.payload, f.fragment_payload "
        "FROM chronicle.history_edition_conclusion_index c "
        "JOIN chronicle.history_edition_fragments f USING (edition_version, fragment_version) "
        "WHERE c.edition_version = %s AND c.conclusion_id = %s",
        (version, conclusion_id),
    ).fetchone()
    if row is None:
        raise HistoryEditionNotFound("conclusion is outside this fixed edition")
    fragment = row[6] if isinstance(row[6], dict) else {}
    source = _source_record(fragment, "conclusions", str(row[2]))
    if source is None:
        raise PersistenceError("history edition conclusion source mapping is missing")
    result = _copy_json(source)
    result.update({
        "id": str(row[0]),
        "conclusion_id": str(row[0]),
        "fragment_version": row[1],
        "source_conclusion_id": row[2],
        "source": {"fragment_version": row[1], "conclusion_id": row[2]},
        "phase_ids": _copy_json(row[3]) if isinstance(row[3], list) else [],
    })
    evidence_values = source.get("evidence") if isinstance(source.get("evidence"), list) else []
    evidence = []
    for value in evidence_values:
        local_id = value if isinstance(value, str) else value.get("id", value.get("evidence_id")) if isinstance(value, dict) else None
        if not isinstance(local_id, str):
            continue
        detail = _source_record(fragment, "evidence", local_id)
        if detail is None and isinstance(fragment.get("evidence"), dict):
            candidate = fragment["evidence"].get(local_id)
            detail = _copy_json(candidate) if isinstance(candidate, dict) else None
        detail = detail or {"id": local_id}
        evidence.append({**detail, "id": local_id, "evidence_id": local_id, "fragment_version": row[1], "source": {"fragment_version": row[1], "evidence_id": local_id}})
    result["evidence"] = evidence
    return {
        "schema": "chronicle.history-conclusion",
        "version": "0.1",
        "edition_version": version,
        "publication_version": version,
        "conclusion": result,
        "source_relations": _copy_json(fragment.get("source_relations") or []),
    }


def decide_boundary_review(
    conn,
    review_id: uuid.UUID | str,
    *,
    decision: str,
    rationale: str,
    review_basis: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Record a seam decision on the existing ReviewItem authority."""

    parsed = _uuid(review_id, "review id")
    if decision not in ("accept", "accepted", "approve", "approved", "reject", "pending"):
        raise PersistenceError("history seam decision must be accept, reject, or pending")
    if not isinstance(rationale, str) or not rationale.strip():
        raise PersistenceError("history seam review requires a rationale")
    with conn.transaction():
        row = conn.execute(
            "SELECT status, payload FROM chronicle.review_items WHERE review_id = %s FOR UPDATE",
            (parsed,),
        ).fetchone()
        if row is None:
            raise HistoryEditionNotFound(f"unknown boundary review {review_id}")
        payload = _copy_json(row[1]) if isinstance(row[1], dict) else {}
        if payload.get("scope") != _EDITION_SCOPE:
            raise PersistenceConflict("review item is not a history-edition seam review")
        boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}
        basis = list(review_basis) if isinstance(review_basis, list) else boundary.get("review_basis")
        if decision in ("accept", "accepted", "approve", "approved"):
            if not isinstance(basis, list) or not basis:
                raise PersistenceError("accepted history seam requires review_basis anchors")
            boundary["status"] = "accepted"
            boundary["review_basis"] = _copy_json(basis)
            payload["status"] = "accepted"
            new_status = "resolved"
        elif decision == "reject":
            boundary["status"] = "rejected"
            payload["status"] = "rejected"
            new_status = "resolved"
        else:
            boundary["status"] = "pending"
            payload["status"] = "pending"
            new_status = "open"
        payload["boundary"] = boundary
        payload["decision"] = {"decision": "accept" if decision in ("accept", "accepted", "approve", "approved") else decision, "rationale": rationale, "review_basis": _copy_json(basis or [])}
        conn.execute(
            "UPDATE chronicle.review_items SET status = %s, payload = %s, resolved_at = CASE WHEN %s = 'open' THEN NULL ELSE clock_timestamp() END WHERE review_id = %s",
            (new_status, Jsonb(payload), new_status, parsed),
        )
        return {"review_id": str(parsed), "status": new_status, "payload": payload}


def publish_edition(conn, draft_id: uuid.UUID | str, **kwargs: Any) -> dict[str, Any]:
    """Product-term alias for :func:`publish_draft`."""

    return publish_draft(conn, draft_id, **kwargs)


def create_edition_draft(conn, **kwargs: Any) -> dict[str, Any]:
    return create_draft(conn, **kwargs)


def read_latest(conn) -> dict[str, Any] | None:
    return read_latest_metadata(conn)


def read_page(conn, **kwargs: Any) -> dict[str, Any]:
    return read_paragraph_page(conn, **kwargs)


def read_public_edition(conn, version: str | None = None) -> dict[str, Any] | None:
    return read_latest_metadata(conn) if version is None else read_edition_metadata(conn, version)


# Product-language aliases keep callers independent of whether they call the
# persisted object a draft, manifest, or edition.  All aliases still pass
# through the same contract/lock/lease boundary above.
create_history_edition_draft = create_draft
publish_history_edition = publish_draft
read_latest_edition = read_latest_metadata
read_edition = read_edition_metadata
