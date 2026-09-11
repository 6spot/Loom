"""Chronicle C2-R2-T08 fixed-snapshot event preview and position lookup.

Read-only domain queries over the immutable second-round reading index
(``continuous-reading.md`` sections 5-7; Architecture Amendment 0006):

- :func:`event_preview` returns a lightweight preview for one canonical
  Event *inside a chosen snapshot catalog*: the snapshot name, each member
  source's own raw time observations (never a canonical aggregate year) and,
  when a published ``current`` occurrence exists, a short excerpt of that
  already-published translation block. A source that only has retrospective
  mentions gets no occurrence excerpt (the UI then shows its explicit
  "no published excerpt" state); no summary is ever generated and nothing is
  written.
- :func:`event_targets` pages the exact source positions of one canonical
  Event with a stable ``(relation, stream_id, unit_ordinal, span_id)``
  keyset cursor, keeping ``current`` and ``mention`` explicitly separated.
  A first page never impersonates the whole set.

Scope discipline (the T05 invariant): membership comes from the snapshot
catalog's immutable *payload* and from ``reading_event_occurrences`` written
under a stream whose origin catalog is not newer than the snapshot. The
global representation tables are never consulted, so a later publication for
the same canonical id can never leak into an older card, and a name match can
never wire two same-named events together.

The module deliberately holds no HTTP wiring (T09) and does not touch the
stream/unit page path (T07). It only reads the shared immutable tables plus
the already-published block text through ``reading_units.segments``; it never
copies or edits the body.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from read_common import ReadModelError, ReadModelNotFound, event_display

# T01 contract validators and the T04 time-observation builder live in the
# sibling persistence package. The same bootstrap as server.py keeps this
# module importable outside the server process.
_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
if str(_PERSISTENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE_DIR))

import reading_contract as _reading_contract  # noqa: E402
import reading_projection as _reading_projection  # noqa: E402

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

#: Maximum preview sources carried by one card (continuous-reading.md §6).
PREVIEW_MAX_SOURCES = 8

#: Exact excerpt budgets fixed by the contract (code points).
PREVIEW_EXCERPT_CODE_POINTS = 160
TARGET_EXCERPT_CODE_POINTS = 160

#: Targets page bound (continuous-reading.md §6: limit 1..50).
TARGETS_MIN_LIMIT = 1
TARGETS_MAX_LIMIT = 50

#: Opaque cursor format marker.
CURSOR_VERSION = 1


class ReadModelInconsistency(RuntimeError):
    """Persisted reading rows contradict each other.

    Unlike a bad request (400) or a missing object (404), an internally
    inconsistent reading index is a server-side defect: the contract requires
    it to fail explicitly instead of being patched with a fallback. T09 maps
    this to a 5xx response.
    """


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------


def _require_sha(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.match(value):
        raise ReadModelError(f"{description} must be a lowercase hex SHA-256 string")
    return value


def _require_uuid(value: Any, description: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReadModelError(f"{description} must be a UUID") from exc


def _clip(text: str, limit: int) -> tuple[str, bool]:
    """Return ``(text[:limit], clipped)`` without splitting surrogate pairs."""
    if not isinstance(text, str):
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit], True


# ---------------------------------------------------------------------------
# Snapshot catalog membership (immutable payload is the only member authority)
# ---------------------------------------------------------------------------


class _Snapshot:
    """Read-only view of one immutable snapshot catalog payload."""

    def __init__(self, payload: dict[str, Any], publication_sequence: int) -> None:
        self.publication_sequence = publication_sequence
        self.event_members: dict[tuple[str, str], str] = {}
        self.event_reps: dict[str, list[tuple[str, str]]] = {}
        self.event_ids: set[str] = set()
        if not isinstance(payload, dict):
            return
        for record in payload.get("canonical_events") or []:
            if not isinstance(record, dict):
                continue
            canonical_id = record.get("canonical_id")
            if not isinstance(canonical_id, str) or not canonical_id:
                continue
            canonical_id = canonical_id.lower()
            self.event_ids.add(canonical_id)
            reps = self.event_reps.setdefault(canonical_id, [])
            for representation in record.get("representations") or []:
                if not isinstance(representation, dict):
                    continue
                bundle = representation.get("bundle")
                ref = representation.get("ref")
                if not (
                    isinstance(bundle, str)
                    and bundle
                    and isinstance(ref, str)
                    and ref
                ):
                    continue
                key = (bundle, ref)
                if key in self.event_members:
                    continue
                self.event_members[key] = canonical_id
                reps.append(key)


def load_snapshot(conn, catalog_sha: str) -> _Snapshot:
    """Load one persisted snapshot catalog or raise a 404 read error."""
    catalog_sha = _require_sha(catalog_sha, "snapshot catalog_sha")
    row = conn.execute(
        "SELECT payload, publication_sequence FROM chronicle.canonical_catalogs"
        " WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if row is None:
        raise ReadModelNotFound(f"snapshot catalog {catalog_sha} not found")
    return _Snapshot(row[0], int(row[1]))


#: Membership predicate shared by every occurrence query: an occurrence is
#: visible only through a source representation the snapshot payload lists for
#: that exact canonical id. The global representation tables are never used.
_MEMBERSHIP_PREDICATE = """
EXISTS (
    SELECT 1
    FROM chronicle.canonical_catalogs snapshot
    CROSS JOIN LATERAL jsonb_array_elements(snapshot.payload -> 'canonical_events') AS ev
    CROSS JOIN LATERAL jsonb_array_elements(ev -> 'representations') AS rep
    WHERE snapshot.artifact_sha256 = %s
      AND ev ->> 'canonical_id' = o.canonical_event_id::text
      AND rep ->> 'bundle' = o.bundle_label
      AND rep ->> 'ref' = o.record_ref
)
"""


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _event_payloads(
    conn, reps: list[tuple[str, str]]
) -> dict[tuple[str, str], tuple[dict[str, Any], str | None]]:
    """Fetch member source payloads and titles in one bounded query."""
    if not reps:
        return {}
    bundles = [bundle for bundle, _ in reps]
    refs = [ref for _, ref in reps]
    rows = conn.execute(
        """
        SELECT e.bundle_label, e.record_ref, e.payload, b.source_title
        FROM chronicle.staged_events e
        JOIN chronicle.source_bundles b ON b.bundle_label = e.bundle_label
        WHERE (e.bundle_label, e.record_ref) IN (
            SELECT * FROM unnest(%s::text[], %s::text[])
        )
        """,
        (bundles, refs),
    ).fetchall()
    return {
        (row[0], row[1]): (row[2] if isinstance(row[2], dict) else {}, row[3])
        for row in rows
    }


def _event_name(
    payloads: list[dict[str, Any]], reps: list[tuple[str, str]], event_id: str
) -> str:
    title = event_display(payloads).get("title")
    if isinstance(title, str) and title.strip():
        return title
    if reps:
        fallback = reps[0][1]
        if isinstance(fallback, str) and fallback:
            return fallback
    return event_id


def _current_occurrences(
    conn, *, catalog_sha: str, event_id: str, publication_sequence: int
) -> dict[str, list[tuple]]:
    """Return the published ``current`` occurrences grouped by bundle label."""
    rows = conn.execute(
        f"""
        SELECT o.bundle_label, o.stream_id, o.unit_ordinal, o.span_id,
               u.unit_id, u.publication_id, u.chapter_id, u.segments,
               u.source_anchor_ids
        FROM chronicle.reading_event_occurrences o
        JOIN chronicle.reading_units u
          ON u.stream_id = o.stream_id AND u.ordinal = o.unit_ordinal
        JOIN chronicle.reading_streams s ON s.stream_id = o.stream_id
        JOIN chronicle.canonical_catalogs origin
          ON origin.artifact_sha256 = s.origin_catalog_sha
        WHERE o.canonical_event_id = %s::uuid
          AND o.relation = 'current'
          AND origin.publication_sequence <= %s
          AND {_MEMBERSHIP_PREDICATE}
        ORDER BY o.stream_id, o.unit_ordinal, o.span_id NULLS FIRST
        """,
        (event_id, publication_sequence, catalog_sha),
    ).fetchall()
    by_bundle: dict[str, list[tuple]] = {}
    for row in rows:
        by_bundle.setdefault(row[0], []).append(row)
    return by_bundle


def _unit_text(segments: Any) -> str:
    if not isinstance(segments, list):
        return ""
    return "".join(
        segment.get("text", "")
        for segment in segments
        if isinstance(segment, dict) and isinstance(segment.get("text"), str)
    )


def _anchor_entry(publication_id: Any, source_anchor_ids: Any) -> dict[str, str] | None:
    if not isinstance(publication_id, (str, uuid.UUID)):
        return None
    anchors = source_anchor_ids if isinstance(source_anchor_ids, list) else []
    anchor_id = next(
        (anchor for anchor in anchors if isinstance(anchor, str) and anchor), None
    )
    if anchor_id is None:
        return None
    return {"publication_id": str(publication_id), "anchor_id": anchor_id}


def event_preview(
    conn, *, snapshot_catalog_sha: str, canonical_event_id: str
) -> dict[str, Any]:
    """Return the fixed-snapshot preview for one canonical Event.

    The Event must be a member of the named snapshot catalog; otherwise the
    caller gets a 404 (:class:`ReadModelNotFound`). Text and time are read
    from the snapshot's own member representations, and the excerpt comes
    only from an already-published ``current`` occurrence.
    """
    catalog_sha = _require_sha(snapshot_catalog_sha, "snapshot catalog_sha")
    event_id = _require_uuid(canonical_event_id, "canonical Event id")
    snapshot = load_snapshot(conn, catalog_sha)
    if event_id not in snapshot.event_ids:
        raise ReadModelNotFound(
            f"canonical Event {event_id} is not a member of snapshot {catalog_sha}"
        )
    reps = snapshot.event_reps.get(event_id, [])
    payloads_by_rep = _event_payloads(conn, reps)
    current_by_bundle = _current_occurrences(
        conn,
        catalog_sha=catalog_sha,
        event_id=event_id,
        publication_sequence=snapshot.publication_sequence,
    )

    sources: list[dict[str, Any]] = []
    for bundle, ref in reps[:PREVIEW_MAX_SOURCES]:
        payload, source_title = payloads_by_rep.get((bundle, ref), ({}, None))
        observation = _reading_projection.event_time_observation(ref, payload)
        excerpt: str | None = None
        excerpt_more = False
        original_entry: dict[str, str] | None = None
        occurrences = current_by_bundle.get(bundle) or []
        if occurrences:
            row = occurrences[0]
            if row[3] is not None:
                # A published span occurrence must still resolve to its exact
                # segment; a mismatch is an internal inconsistency, not a
                # reason to silently show a fallback.
                _require_span_text(row[7], row[3], row[4])
            text, excerpt_more = _clip(_unit_text(row[7]), PREVIEW_EXCERPT_CODE_POINTS)
            excerpt = text or None
            original_entry = _anchor_entry(row[5], row[8])
        sources.append(
            {
                "source_title": source_title or bundle,
                "publication_id": str(occurrences[0][5]) if occurrences else None,
                "observations": [observation] if observation is not None else [],
                "excerpt": excerpt,
                "excerpt_more": excerpt_more,
                "original_entry": original_entry,
            }
        )

    preview = {
        "event_id": event_id,
        "catalog_sha": catalog_sha,
        "name": _event_name(
            [payload for payload, _ in payloads_by_rep.values()], reps, event_id
        ),
        "sources": sources,
        "source_count": len(reps),
        "has_more_sources": len(reps) > len(sources),
    }
    _assert_valid("event_preview", preview)
    return preview


# ---------------------------------------------------------------------------
# Targets (exact source positions, current/mention separated)
# ---------------------------------------------------------------------------


def _encode_cursor(
    *,
    catalog_sha: str,
    event_id: str,
    rank: int,
    stream_id: str,
    unit_ordinal: int,
    span_id: str,
) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "catalog": catalog_sha,
        "event": event_id,
        "rank": rank,
        "stream": stream_id,
        "ordinal": unit_ordinal,
        "span": span_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str, *, catalog_sha: str, event_id: str
) -> tuple[int, str, int, str]:
    if not isinstance(cursor, str) or not cursor:
        raise ReadModelError("cursor must be a non-empty string")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ReadModelError("cursor is not a valid position token") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise ReadModelError("cursor version is not supported")
    if payload.get("catalog") != catalog_sha or payload.get("event") != event_id:
        raise ReadModelError(
            "cursor does not belong to this snapshot catalog and event"
        )
    rank = payload.get("rank")
    ordinal = payload.get("ordinal")
    stream_id = payload.get("stream")
    span_id = payload.get("span")
    if rank not in (0, 1):
        raise ReadModelError("cursor relation key is invalid")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise ReadModelError("cursor ordinal key is invalid")
    if not isinstance(stream_id, str) or not stream_id:
        raise ReadModelError("cursor stream key is invalid")
    try:
        stream_id = str(uuid.UUID(stream_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReadModelError("cursor stream key is not a valid UUID") from exc
    if not isinstance(span_id, str) or not span_id:
        raise ReadModelError("cursor span key is invalid")
    return rank, stream_id, ordinal, span_id


_TARGET_BASE = f"""
    FROM chronicle.reading_event_occurrences o
    JOIN chronicle.reading_units u
      ON u.stream_id = o.stream_id AND u.ordinal = o.unit_ordinal
    JOIN chronicle.reading_streams s ON s.stream_id = o.stream_id
    JOIN chronicle.canonical_catalogs origin
      ON origin.artifact_sha256 = s.origin_catalog_sha
    JOIN chronicle.source_bundles b ON b.bundle_label = o.bundle_label
    JOIN chronicle.chapter_publications p ON p.publication_id = u.publication_id
    WHERE o.canonical_event_id = %s::uuid
      AND o.event_kind = 'span'
      AND o.span_id IS NOT NULL
      AND origin.publication_sequence <= %s
      AND {_MEMBERSHIP_PREDICATE}
"""


def _span_text(segments: Any, span_id: str) -> str:
    if not isinstance(segments, list):
        return ""
    for segment in segments:
        if not isinstance(segment, dict) or segment.get("kind") != "event":
            continue
        span = segment.get("span")
        if isinstance(span, dict) and span.get("span_id") == span_id:
            text = segment.get("text")
            if isinstance(text, str):
                return text
    return ""


def _require_span_text(segments: Any, span_id: str, unit_id: str) -> str:
    """Return the exact event span text or fail on an inconsistent index."""
    text = _span_text(segments, span_id)
    if not text:
        raise ReadModelInconsistency(
            f"reading span {span_id!r} in unit {unit_id!r} has no matching "
            "segment; the reading index and its segments disagree"
        )
    return text


def _chapter_titles(conn, rows: list[tuple]) -> dict[tuple[str, str, str], str]:
    """Batch-load source chapter titles for one target page.

    The title lives in the publication's own assembled source bundle
    (``report.plan.chapters``), never in the reading index; it is loaded once
    per distinct ``(job_id, assembled_bundle_sha256)`` in the page instead of
    once per target, so a page never causes an N+1 lookup.
    """
    pairs = sorted(
        {
            (str(row[12]), row[13])
            for row in rows
            if row[12] is not None and isinstance(row[13], str) and row[13]
        }
    )
    if not pairs:
        return {}
    output_rows = conn.execute(
        """
        SELECT o.job_id, o.artifact_sha256, o.payload
        FROM chronicle.ingestion_outputs o
        JOIN unnest(%s::text[], %s::text[]) AS wanted(job_id, artifact_sha256)
          ON o.job_id = wanted.job_id::uuid
         AND o.artifact_sha256 = wanted.artifact_sha256
        WHERE o.artifact_type = 'assembled-source-bundle'
        """,
        ([pair[0] for pair in pairs], [pair[1] for pair in pairs]),
    ).fetchall()
    titles: dict[tuple[str, str, str], str] = {}
    for job_id, sha, payload in output_rows:
        if not isinstance(payload, dict):
            continue
        report = payload.get("report")
        chapters = (
            report.get("plan", {}).get("chapters")
            if isinstance(report, dict)
            else None
        )
        if not isinstance(chapters, list):
            continue
        for entry in chapters:
            if not isinstance(entry, dict):
                continue
            chapter_id = entry.get("chapter_id")
            title = entry.get("title")
            if (
                isinstance(chapter_id, str)
                and chapter_id
                and isinstance(title, str)
                and title
            ):
                titles[(str(job_id), sha, chapter_id)] = title
    return titles


def _target_counts(
    conn, *, catalog_sha: str, event_id: str, publication_sequence: int
) -> tuple[int, int]:
    row = conn.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE o.relation = 'current'),
            count(*) FILTER (WHERE o.relation <> 'current')
        {_TARGET_BASE}
        """,
        (event_id, publication_sequence, catalog_sha),
    ).fetchone()
    return int(row[0]), int(row[1])


def event_targets(
    conn,
    *,
    snapshot_catalog_sha: str,
    canonical_event_id: str,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return a bounded, snapshot-scoped page of exact Event source positions.

    Ordering is ``(current before mention, stream_id, unit_ordinal, span_id)``;
    the opaque cursor binds the snapshot catalog and the Event so a token can
    never be replayed against another snapshot. ``current_count`` and
    ``mention_count`` report the totals across the whole snapshot, so a first
    page never hides that more sources exist.
    """
    catalog_sha = _require_sha(snapshot_catalog_sha, "snapshot catalog_sha")
    event_id = _require_uuid(canonical_event_id, "canonical Event id")
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ReadModelError("limit must be an integer")
    if limit < TARGETS_MIN_LIMIT or limit > TARGETS_MAX_LIMIT:
        raise ReadModelError(
            f"limit must be between {TARGETS_MIN_LIMIT} and {TARGETS_MAX_LIMIT}"
        )
    snapshot = load_snapshot(conn, catalog_sha)
    if event_id not in snapshot.event_ids:
        raise ReadModelNotFound(
            f"canonical Event {event_id} is not a member of snapshot {catalog_sha}"
        )

    clauses = ""
    params: list[Any] = [event_id, snapshot.publication_sequence, catalog_sha]
    if cursor is not None:
        rank, stream_id, ordinal, span_id = _decode_cursor(
            cursor, catalog_sha=catalog_sha, event_id=event_id
        )
        clauses = (
            " AND ((CASE WHEN o.relation = 'current' THEN 0 ELSE 1 END),"
            " o.stream_id, o.unit_ordinal, o.span_id)"
            " > (%s, %s::uuid, %s, %s)"
        )
        params.extend([rank, stream_id, ordinal, span_id])

    rows = conn.execute(
        f"""
        SELECT o.stream_id, o.unit_ordinal, o.relation,
               o.bundle_label, o.record_ref, o.span_id,
               u.unit_id, u.publication_id, u.chapter_id, u.segments,
               b.source_title, o.event_kind,
               p.job_id, p.assembled_bundle_sha256
        {_TARGET_BASE}
        {clauses}
        ORDER BY (CASE WHEN o.relation = 'current' THEN 0 ELSE 1 END),
                 o.stream_id, o.unit_ordinal, o.span_id
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    current_count, mention_count = _target_counts(
        conn,
        catalog_sha=catalog_sha,
        event_id=event_id,
        publication_sequence=snapshot.publication_sequence,
    )

    chapter_titles = _chapter_titles(conn, rows)

    targets: list[dict[str, Any]] = []
    last_key: tuple[int, str, int, str] | None = None
    for row in rows:
        relation = "current" if row[2] == "current" else "mention"
        span_id = row[5]
        excerpt, _more = _clip(
            _require_span_text(row[9], span_id, row[6]),
            TARGET_EXCERPT_CODE_POINTS,
        )
        targets.append(
            {
                "event_id": event_id,
                "catalog_sha": catalog_sha,
                "relation": relation,
                "stream_id": str(row[0]),
                "publication_id": str(row[7]),
                "chapter_id": row[8],
                "chapter_title": chapter_titles.get((str(row[12]), row[13], row[8])),
                "source_title": row[10],
                "unit_id": row[6],
                "span_id": span_id,
                "locator": {
                    "stream_id": str(row[0]),
                    "catalog_sha": catalog_sha,
                    "unit_id": row[6],
                },
                "excerpt": excerpt,
            }
        )
        last_key = (0 if row[2] == "current" else 1, str(row[0]), int(row[1]), span_id)

    next_cursor = None
    if has_more and last_key is not None:
        next_cursor = _encode_cursor(
            catalog_sha=catalog_sha,
            event_id=event_id,
            rank=last_key[0],
            stream_id=last_key[1],
            unit_ordinal=last_key[2],
            span_id=last_key[3],
        )

    page = {
        "event_id": event_id,
        "catalog_sha": catalog_sha,
        "targets": targets,
        "current_count": current_count,
        "mention_count": mention_count,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
    _assert_valid("event_target_page", page)
    return page


# ---------------------------------------------------------------------------
# Contract guard
# ---------------------------------------------------------------------------


def _assert_valid(name: str, value: dict[str, Any]) -> None:
    errors = _reading_contract.reading_response_errors(name, value)
    if errors:
        raise ReadModelError(f"{name} response is invalid: " + "; ".join(errors))


__all__ = [
    "PREVIEW_EXCERPT_CODE_POINTS",
    "PREVIEW_MAX_SOURCES",
    "TARGET_EXCERPT_CODE_POINTS",
    "TARGETS_MAX_LIMIT",
    "event_preview",
    "event_targets",
    "load_snapshot",
]
