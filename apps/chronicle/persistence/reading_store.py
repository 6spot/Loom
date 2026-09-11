"""Chronicle C2-R2-T05 continuous-reading stream store (application-owned).

Narrow, immutable persistence for the reading projection fixed by
``continuous-reading.md`` sections 4-5 behind ``CHRONICLE_DATABASE_URL``
(Architecture Amendment 0006):

- :func:`persist_reading_stream` records one compiled reading stream — the
  stream metadata, ordered units, time-axis groups and event occurrences —
  in the *caller's* already-open transaction. It never opens a second
  transaction, never commits, and never acquires a second worker lease: the
  unique publish transaction (and its catalog advisory lock) belongs to T06.
- The write is idempotent on ``revision_id`` only when the *complete*
  normalized compiled input matches: replaying the same units, groups,
  occurrences and publication bindings returns the same ``stream_id``;
  changing any of them — even while keeping the manifest bytes — raises
  :class:`PersistenceConflict`. A missing chapter publication, a publication
  from another revision or another catalog, a cross-revision unit, a dangling
  time group and an event representation that the origin catalog payload does
  not list are all rejected fail-closed before any row is written (the 0007
  triggers are the second fence).
- ``read_reading_stream`` / ``list_reading_streams`` / ``read_reading_unit``
  / ``read_reading_units`` / ``read_reading_groups`` / ``read_event_occurrences``
  are SELECT-only, bounded helpers. Ordinal pages use indexed keyset ranges
  with ``limit + 1``; event reverse lookup uses the
  ``reading_event_occurrences_event_idx`` index. No helper reads the whole
  body corpus and slices it in Python. Every helper accepts an optional
  snapshot catalog and then enforces ``_require_visible_stream``.

Snapshot visibility (``continuous-reading.md`` section 5) is decided by two
immutable facts, never by wall-clock time:

1. the snapshot catalog's own ``publication_sequence`` bounds which streams
   are in range (``origin.publication_sequence <= snapshot``); and
2. the snapshot catalog *payload* is the member authority for event
   occurrences — the global representation tables are never consulted.

``reading_units`` never copies translation text: the body stays in the
first-round ``chapter_publications`` row referenced by ``publication_id``.
Catalogs stay owned by :mod:`canonical_store`; chapter rows stay owned by
:mod:`chapter_store`.

The accepted compiled stream is a plain JSON object produced by the T04
compiler and documented in ``apps/chronicle/docs/persistence.md``. The test
fixture loads one directly; that is a test-only loading path, not a second
production success path.
"""

from __future__ import annotations

import re
import secrets
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import reading_contract  # noqa: E402
from common import (  # noqa: E402
    PersistenceConflict,
    PersistenceError,
    parse_uuid7,
    sha256_json,
)

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

#: Event kinds that may be reverse-indexed. Ambiguous / unresolved spans have
#: no canonical target and are deliberately absent from the index.
OCCURRENCE_KINDS = ("span", "current")

#: Relations copied from the T01 contract; the store never invents one.
OCCURRENCE_RELATIONS = tuple(reading_contract.SPAN_RELATIONS)


# ---------------------------------------------------------------------------
# Small validators / id helpers
# ---------------------------------------------------------------------------


def _new_id() -> uuid.UUID:
    """Generate an RFC 9562 UUIDv7 for one immutable reading row."""
    unix_ms = time.time_ns() // 1_000_000
    if unix_ms >= 1 << 48:
        raise PersistenceError("current Unix millisecond timestamp does not fit UUIDv7")
    random_bits = secrets.randbits(74)
    value = (
        (unix_ms << 80)
        | (0x7 << 76)
        | ((random_bits >> 62) << 64)
        | (0b10 << 62)
        | (random_bits & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value)


def _require_uuid(value: Any, description: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PersistenceError(f"{description} must be a UUID, got {value!r}") from exc


def _require_uuid7(value: Any, description: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return parse_uuid7(str(value), description)
    return parse_uuid7(value, description)


def _require_sha(value: Any, description: str) -> str:
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


def _require_bool(value: Any, description: str) -> bool:
    if not isinstance(value, bool):
        raise PersistenceError(f"{description} must be a boolean")
    return value


# ---------------------------------------------------------------------------
# Compiled-stream validation (fail closed before any row is written)
# ---------------------------------------------------------------------------


def _normalize_compiled_stream(conn, stream: dict[str, Any]) -> dict[str, Any]:
    """Validate a compiled stream and return its normalized form.

    Every program-owned identity and every cross-reference is checked here,
    before the caller's transaction writes anything. The 0007 triggers repeat
    the referential checks at the database, but a failure must never leave a
    half-written stream inside the caller's transaction.
    """
    _require_object(stream, "compiled stream")
    # revision/document identity is owned by the control plane (UUIDv4 today);
    # only the new reading rows are UUIDv7 by contract.
    revision_id = _require_uuid(stream.get("revision_id"), "stream revision_id")
    document_id = _require_uuid(stream.get("document_id"), "stream document_id")
    catalog_sha = _require_sha(stream.get("origin_catalog_sha"), "stream origin_catalog_sha")
    manifest = _require_object(stream.get("manifest"), "stream manifest")
    manifest_sha = sha256_json(manifest)
    supplied_manifest_sha = stream.get("manifest_sha")
    if supplied_manifest_sha is not None and supplied_manifest_sha != manifest_sha:
        raise PersistenceError(
            "stream manifest_sha does not match the supplied manifest bytes"
        )

    raw_publications = _require_list(
        stream.get("chapter_publication_ids"), "stream chapter_publication_ids"
    )
    if not raw_publications:
        raise PersistenceError("stream chapter_publication_ids must not be empty")
    publications: list[uuid.UUID] = []
    for index, value in enumerate(raw_publications):
        publications.append(
            _require_uuid7(value, f"stream chapter_publication_ids[{index}]")
        )
    if len(set(publications)) != len(publications):
        raise PersistenceError("stream chapter_publication_ids must not repeat")

    # The catalog must exist and its immutable payload is the member authority.
    catalog_row = conn.execute(
        "SELECT payload FROM chronicle.canonical_catalogs WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if catalog_row is None:
        raise PersistenceConflict(
            f"stream origin catalog {catalog_sha} is not persisted"
        )
    membership = _catalog_event_membership(_require_object(catalog_row[0], "catalog payload"))

    # Every chapter publication must exist, be unique, belong to this very
    # revision/document, and have been published under the stream's origin
    # catalog. Array elements cannot carry a foreign key, so the store proves it
    # here; a publication from a later catalog must never enter an earlier
    # snapshot.
    publication_rows = conn.execute(
        """
        SELECT publication_id, revision_id, document_id, artifact_sha256, chapter_id, payload,
               catalog_sha256
        FROM chronicle.chapter_publications
        WHERE publication_id = ANY (%s)
        """,
        (publications,),
    ).fetchall()
    by_publication = {row[0]: row for row in publication_rows}
    for publication_id in publications:
        row = by_publication.get(publication_id)
        if row is None:
            raise PersistenceConflict(
                f"stream chapter publication {publication_id} is not persisted"
            )
        if row[1] != revision_id or row[2] != document_id:
            raise PersistenceConflict(
                f"stream chapter publication {publication_id} belongs to another revision/document"
            )
        if row[6] != catalog_sha:
            raise PersistenceConflict(
                f"stream chapter publication {publication_id} was published under catalog "
                f"{row[6]}, not origin catalog {catalog_sha}"
            )

    revision_row = conn.execute(
        "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
        (revision_id,),
    ).fetchone()
    if revision_row is None:
        raise PersistenceConflict(f"stream revision {revision_id} is not persisted")
    if revision_row[0] != document_id:
        raise PersistenceConflict(
            f"stream document {document_id} does not match revision {revision_id}"
        )

    units = _normalize_units(stream.get("units"), by_publication)
    groups = _normalize_groups(stream.get("groups"), units)
    occurrences = _normalize_occurrences(
        stream.get("event_occurrences"), units, membership
    )

    # The stream lists its chapter publications in reading order; the units must
    # visit exactly that ordered chapter sequence with no surprise or omission.
    unit_chapter_order: list[uuid.UUID] = []
    for unit in units:
        if unit["publication_id"] not in unit_chapter_order:
            unit_chapter_order.append(unit["publication_id"])
    if unit_chapter_order != publications:
        raise PersistenceError(
            "stream chapter_publication_ids must equal the ordered publications of the units"
        )

    normalized = {
        "revision_id": revision_id,
        "document_id": document_id,
        "origin_catalog_sha": catalog_sha,
        "manifest": manifest,
        "manifest_sha": manifest_sha,
        "chapter_publication_ids": publications,
        "units": units,
        "groups": groups,
        "event_occurrences": occurrences,
    }
    normalized["content_sha256"] = _content_sha256(normalized)
    return normalized


def _content_sha256(normalized: dict[str, Any]) -> str:
    """Digest the complete normalized compiled input, not just the manifest.

    A replay may reuse a stream only when this digest matches the stored one;
    changing any unit, group, occurrence or publication binding — even with an
    identical manifest — is an immutability conflict.
    """
    return sha256_json(
        {
            "revision_id": str(normalized["revision_id"]),
            "document_id": str(normalized["document_id"]),
            "origin_catalog_sha": normalized["origin_catalog_sha"],
            "manifest_sha": normalized["manifest_sha"],
            "manifest": normalized["manifest"],
            "chapter_publication_ids": [
                str(value) for value in normalized["chapter_publication_ids"]
            ],
            "units": [
                {
                    "ordinal": unit["ordinal"],
                    "unit_id": unit["unit_id"],
                    "publication_id": str(unit["publication_id"]),
                    "artifact_sha256": unit["artifact_sha256"],
                    "chapter_id": unit["chapter_id"],
                    "block_id": unit["block_id"],
                    "text_hash": unit["text_hash"],
                    "group_id": unit["group_id"],
                    "narrative_time": unit["narrative_time"],
                    "segments": unit["segments"],
                    "context_entities": unit["context_entities"],
                    "source_anchor_ids": unit["source_anchor_ids"],
                    "continues_previous": unit["continues_previous"],
                }
                for unit in normalized["units"]
            ],
            "groups": normalized["groups"],
            "event_occurrences": [
                {
                    "unit_id": occurrence["unit_id"],
                    "ordinal": occurrence["ordinal"],
                    "event_kind": occurrence["event_kind"],
                    "span_id": occurrence["span_id"],
                    "canonical_event_id": str(occurrence["canonical_event_id"]),
                    "relation": occurrence["relation"],
                    "bundle_label": occurrence["bundle_label"],
                    "record_ref": occurrence["record_ref"],
                }
                for occurrence in normalized["event_occurrences"]
            ],
        }
    )


def _catalog_event_membership(payload: dict[str, Any]) -> set[tuple[str, str, str]]:
    """Return the exact ``(canonical_id, bundle, ref)`` member set.

    Read only from the immutable catalog payload: later global representation
    rows must never widen an old snapshot.
    """
    members: set[tuple[str, str, str]] = set()
    events = payload.get("canonical_events")
    if not isinstance(events, list):
        return members
    for event in events:
        if not isinstance(event, dict):
            continue
        canonical_id = event.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id:
            continue
        for representation in event.get("representations") or []:
            if not isinstance(representation, dict):
                continue
            bundle = representation.get("bundle")
            ref = representation.get("ref")
            if isinstance(bundle, str) and bundle and isinstance(ref, str) and ref:
                members.add((canonical_id.lower(), bundle, ref))
    return members


def _translation_blocks(publication_payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = publication_payload.get("translation_blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError(
            "chapter publication carries no complete translation_blocks; "
            "reading units cannot cite an empty body"
        )
    return [block for block in blocks if isinstance(block, dict)]


def _normalize_units(
    raw_units: Any, by_publication: dict[uuid.UUID, tuple]
) -> list[dict[str, Any]]:
    units = _require_list(raw_units, "stream units")
    normalized: list[dict[str, Any]] = []
    seen_unit_ids: set[str] = set()
    blocks_cache: dict[uuid.UUID, set[Any]] = {}
    for index, unit in enumerate(units):
        unit = _require_object(unit, f"stream units[{index}]")
        ordinal = unit.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise PersistenceError(f"stream units[{index}].ordinal must be a non-negative integer")
        if ordinal != index:
            raise PersistenceError("stream unit ordinals must be contiguous from 0")
        unit_id = _require_text(unit.get("unit_id"), f"stream units[{index}].unit_id")
        if unit_id in seen_unit_ids:
            raise PersistenceError(f"stream repeats unit_id {unit_id!r}")
        seen_unit_ids.add(unit_id)
        publication_id = _require_uuid7(
            unit.get("publication_id"), f"stream units[{index}].publication_id"
        )
        publication_row = by_publication.get(publication_id)
        if publication_row is None:
            raise PersistenceConflict(
                f"stream unit {unit_id!r} cites unpublished chapter publication {publication_id}"
            )
        artifact_sha256 = _require_sha(
            unit.get("artifact_sha256"), f"stream units[{index}].artifact_sha256"
        )
        if artifact_sha256 != publication_row[3]:
            raise PersistenceConflict(
                f"stream unit {unit_id!r} artifact does not match its chapter publication"
            )
        chapter_id = _require_text(unit.get("chapter_id"), f"stream units[{index}].chapter_id")
        if chapter_id != publication_row[4]:
            raise PersistenceConflict(
                f"stream unit {unit_id!r} chapter does not match its chapter publication"
            )
        block_id = _require_text(unit.get("block_id"), f"stream units[{index}].block_id")
        if publication_id not in blocks_cache:
            blocks_cache[publication_id] = {
                block.get("block_id")
                for block in _translation_blocks(
                    _require_object(publication_row[5], "publication payload")
                )
            }
        if block_id not in blocks_cache[publication_id]:
            raise PersistenceConflict(
                f"stream unit {unit_id!r} block {block_id!r} is not in its chapter publication"
            )
        normalized.append(
            {
                "ordinal": ordinal,
                "unit_id": unit_id,
                "publication_id": publication_id,
                "artifact_sha256": artifact_sha256,
                "chapter_id": chapter_id,
                "block_id": block_id,
                "text_hash": _require_sha(unit.get("text_hash"), f"stream units[{index}].text_hash"),
                "group_id": _require_text(unit.get("group_id"), f"stream units[{index}].group_id"),
                "narrative_time": _require_object(
                    unit.get("narrative_time"), f"stream units[{index}].narrative_time"
                ),
                "segments": _require_list(unit.get("segments"), f"stream units[{index}].segments"),
                "context_entities": _require_list(
                    unit.get("context_entities"), f"stream units[{index}].context_entities"
                ),
                "source_anchor_ids": _require_list(
                    unit.get("source_anchor_ids"), f"stream units[{index}].source_anchor_ids"
                ),
                "continues_previous": _require_bool(
                    unit.get("continues_previous"), f"stream units[{index}].continues_previous"
                ),
            }
        )
    if not normalized:
        raise PersistenceError("stream units must not be empty")
    return normalized


def _normalize_groups(raw_groups: Any, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = _require_list(raw_groups, "stream groups")
    normalized: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    by_ordinal = {unit["ordinal"]: unit for unit in units}
    for index, group in enumerate(groups):
        group = _require_object(group, f"stream groups[{index}]")
        ordinal = group.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise PersistenceError(f"stream groups[{index}].ordinal must be a non-negative integer")
        if ordinal != index:
            raise PersistenceError("stream group ordinals must be contiguous from 0")
        group_id = _require_text(group.get("group_id"), f"stream groups[{index}].group_id")
        if group_id in seen_group_ids:
            raise PersistenceError(f"stream repeats group_id {group_id!r}")
        seen_group_ids.add(group_id)
        first = group.get("first_unit_ordinal")
        last = group.get("last_unit_ordinal")
        if not isinstance(first, int) or not isinstance(last, int):
            raise PersistenceError(f"stream groups[{index}] first/last unit ordinals must be integers")
        if first > last or first not in by_ordinal or last not in by_ordinal:
            raise PersistenceError(f"stream groups[{index}] covers an invalid ordinal range")
        if group.get("first_unit_id") != by_ordinal[first]["unit_id"]:
            raise PersistenceError(f"stream groups[{index}].first_unit_id does not match the unit")
        if group.get("last_unit_id") != by_ordinal[last]["unit_id"]:
            raise PersistenceError(f"stream groups[{index}].last_unit_id does not match the unit")
        if group.get("unit_count") != last - first + 1:
            raise PersistenceError(f"stream groups[{index}].unit_count does not match its range")
        for unit_ordinal in range(first, last + 1):
            if by_ordinal[unit_ordinal]["group_id"] != group_id:
                raise PersistenceError(
                    f"stream groups[{index}] covers a unit with a different group_id"
                )
        precision = group.get("precision")
        if precision not in ("day", "month", "year", "range", "mixed", "unknown", "approximate"):
            raise PersistenceError(f"stream groups[{index}].precision {precision!r} is invalid")
        normalized.append(
            {
                "ordinal": ordinal,
                "group_id": group_id,
                "first_unit_ordinal": first,
                "last_unit_ordinal": last,
                "first_unit_id": by_ordinal[first]["unit_id"],
                "last_unit_id": by_ordinal[last]["unit_id"],
                "unit_count": group["unit_count"],
                "year_key": _require_text(group.get("year_key"), f"stream groups[{index}].year_key"),
                "period_key": _require_text(group.get("period_key"), f"stream groups[{index}].period_key"),
                "year_label": group.get("year_label"),
                "period_label": _require_text(group.get("period_label"), f"stream groups[{index}].period_label"),
                "precision": precision,
                "observations": _require_list(
                    group.get("observations"), f"stream groups[{index}].observations"
                ),
                "continues_previous": _require_bool(
                    group.get("continues_previous"), f"stream groups[{index}].continues_previous"
                ),
            }
        )
    if not normalized:
        raise PersistenceError("stream groups must not be empty")
    return normalized


def _normalize_occurrences(
    raw_occurrences: Any,
    units: list[dict[str, Any]],
    membership: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    occurrences = _require_list(raw_occurrences, "stream event_occurrences")
    unit_ordinals = {unit["unit_id"]: unit["ordinal"] for unit in units}
    normalized: list[dict[str, Any]] = []
    for index, occurrence in enumerate(occurrences):
        occurrence = _require_object(occurrence, f"stream event_occurrences[{index}]")
        unit_id = _require_text(
            occurrence.get("unit_id"), f"stream event_occurrences[{index}].unit_id"
        )
        if unit_id not in unit_ordinals:
            raise PersistenceError(
                f"stream event_occurrences[{index}] cites unknown unit {unit_id!r}"
            )
        event_kind = occurrence.get("event_kind")
        if event_kind not in OCCURRENCE_KINDS:
            raise PersistenceError(
                f"stream event_occurrences[{index}].event_kind must be one of {OCCURRENCE_KINDS}"
            )
        span_id = occurrence.get("span_id")
        if event_kind == "span":
            span_id = _require_text(
                span_id, f"stream event_occurrences[{index}].span_id"
            )
        elif span_id is not None:
            raise PersistenceError(
                f"stream event_occurrences[{index}] current marker must not carry span_id"
            )
        relation = occurrence.get("relation")
        if relation not in OCCURRENCE_RELATIONS:
            raise PersistenceError(
                f"stream event_occurrences[{index}].relation {relation!r} is invalid"
            )
        canonical_event_id = _require_uuid7(
            occurrence.get("canonical_event_id"),
            f"stream event_occurrences[{index}].canonical_event_id",
        )
        bundle_label = _require_text(
            occurrence.get("bundle_label"), f"stream event_occurrences[{index}].bundle_label"
        )
        record_ref = _require_text(
            occurrence.get("record_ref"), f"stream event_occurrences[{index}].record_ref"
        )
        if (str(canonical_event_id).lower(), bundle_label, record_ref) not in membership:
            raise PersistenceConflict(
                f"stream event occurrence {bundle_label}:{record_ref} is not a member "
                "of the stream's origin catalog snapshot"
            )
        normalized.append(
            {
                "unit_id": unit_id,
                "ordinal": unit_ordinals[unit_id],
                "event_kind": event_kind,
                "span_id": span_id,
                "canonical_event_id": canonical_event_id,
                "relation": relation,
                "bundle_label": bundle_label,
                "record_ref": record_ref,
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# Write entry (caller owns the transaction; no commit, no lease)
# ---------------------------------------------------------------------------


def persist_reading_stream(conn, stream: dict[str, Any]) -> uuid.UUID:
    """Persist one compiled reading stream inside the caller's transaction.

    The caller already holds the unique publish transaction (and, for worker
    writes, the job lease and the catalog advisory lock). This function never
    opens a transaction, never commits and never acquires a lease, so T06 can
    commit the catalog, every chapter publication and the whole reading index
    atomically.

    Return value is the immutable ``stream_id``. Replaying the identical
    compiled manifest for the same revision returns the existing id with no
    new rows; different bytes for an already-published revision raise
    :class:`PersistenceConflict` (``immutable_stream_conflict``).
    """
    normalized = _normalize_compiled_stream(conn, stream)
    revision_id = normalized["revision_id"]
    manifest = normalized["manifest"]
    manifest_sha = normalized["manifest_sha"]
    content_sha256 = normalized["content_sha256"]

    existing = conn.execute(
        "SELECT stream_id, manifest_sha, manifest, content_sha256"
        " FROM chronicle.reading_streams WHERE revision_id = %s",
        (revision_id,),
    ).fetchone()
    if existing is not None:
        if (
            existing[1] == manifest_sha
            and existing[2] == manifest
            and existing[3] == content_sha256
        ):
            return existing[0]
        raise PersistenceConflict(
            f"immutable_stream_conflict: revision {revision_id} already has reading stream "
            f"{existing[0]} with different compiled bytes"
        )

    stream_id = _new_id()
    try:
        with conn.transaction(savepoint_name="reading_stream_insert"):
            conn.execute(
                """
                INSERT INTO chronicle.reading_streams(
                    stream_id, revision_id, document_id, origin_catalog_sha,
                    manifest_sha, content_sha256, chapter_publication_ids,
                    unit_count, group_count, manifest
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    stream_id,
                    revision_id,
                    normalized["document_id"],
                    normalized["origin_catalog_sha"],
                    manifest_sha,
                    content_sha256,
                    normalized["chapter_publication_ids"],
                    len(normalized["units"]),
                    len(normalized["groups"]),
                    Jsonb(manifest),
                ),
            )
            _insert_units(conn, stream_id=stream_id, units=normalized["units"])
            _insert_groups(conn, stream_id=stream_id, groups=normalized["groups"])
            _insert_occurrences(
                conn, stream_id=stream_id, occurrences=normalized["event_occurrences"]
            )
    except Exception as exc:  # noqa: BLE001 - race recovery below
        from psycopg import errors as _errors

        if isinstance(exc, _errors.UniqueViolation):
            row = conn.execute(
                "SELECT stream_id, manifest_sha, manifest, content_sha256"
                " FROM chronicle.reading_streams WHERE revision_id = %s",
                (revision_id,),
            ).fetchone()
            if (
                row is not None
                and row[1] == manifest_sha
                and row[2] == manifest
                and row[3] == content_sha256
            ):
                return row[0]
            raise PersistenceConflict(
                f"immutable_stream_conflict: revision {revision_id} is already published "
                "with different compiled bytes"
            ) from exc
        raise
    return stream_id


def _insert_units(conn, *, stream_id: uuid.UUID, units: list[dict[str, Any]]) -> None:
    for unit in units:
        conn.execute(
            """
            INSERT INTO chronicle.reading_units(
                stream_id, ordinal, unit_id, publication_id, artifact_sha256,
                chapter_id, block_id, text_hash, group_id, narrative_time, segments,
                context_entities, source_anchor_ids, continues_previous
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                stream_id,
                unit["ordinal"],
                unit["unit_id"],
                unit["publication_id"],
                unit["artifact_sha256"],
                unit["chapter_id"],
                unit["block_id"],
                unit["text_hash"],
                unit["group_id"],
                Jsonb(unit["narrative_time"]),
                Jsonb(unit["segments"]),
                Jsonb(unit["context_entities"]),
                Jsonb(unit["source_anchor_ids"]),
                unit["continues_previous"],
            ),
        )


def _insert_groups(conn, *, stream_id: uuid.UUID, groups: list[dict[str, Any]]) -> None:
    for group in groups:
        conn.execute(
            """
            INSERT INTO chronicle.reading_time_groups(
                stream_id, ordinal, group_id, first_unit_ordinal, last_unit_ordinal,
                first_unit_id, last_unit_id, unit_count, year_key, period_key,
                year_label, period_label, precision, observations, continues_previous
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                stream_id,
                group["ordinal"],
                group["group_id"],
                group["first_unit_ordinal"],
                group["last_unit_ordinal"],
                group["first_unit_id"],
                group["last_unit_id"],
                group["unit_count"],
                group["year_key"],
                group["period_key"],
                group["year_label"],
                group["period_label"],
                group["precision"],
                Jsonb(group["observations"]),
                group["continues_previous"],
            ),
        )


def _insert_occurrences(
    conn, *, stream_id: uuid.UUID, occurrences: list[dict[str, Any]]
) -> None:
    for occurrence in occurrences:
        conn.execute(
            """
            INSERT INTO chronicle.reading_event_occurrences(
                stream_id, unit_ordinal, event_kind, span_id, canonical_event_id,
                relation, bundle_label, record_ref
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                stream_id,
                occurrence["ordinal"],
                occurrence["event_kind"],
                occurrence["span_id"],
                occurrence["canonical_event_id"],
                occurrence["relation"],
                occurrence["bundle_label"],
                occurrence["record_ref"],
            ),
        )


# ---------------------------------------------------------------------------
# Snapshot visibility (catalog payload member authority + sequence range)
# ---------------------------------------------------------------------------


def _snapshot_sequence(conn, catalog_sha: Any) -> int:
    catalog_sha = _require_sha(catalog_sha, "snapshot catalog_sha")
    row = conn.execute(
        "SELECT publication_sequence FROM chronicle.canonical_catalogs"
        " WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown snapshot catalog {catalog_sha}")
    return int(row[0])


def _require_visible_stream(conn, *, stream_id: uuid.UUID, snapshot_catalog_sha: str) -> int:
    snapshot_sequence = _snapshot_sequence(conn, snapshot_catalog_sha)
    row = conn.execute(
        """
        SELECT origin.publication_sequence
        FROM chronicle.reading_streams s
        JOIN chronicle.canonical_catalogs origin
          ON origin.artifact_sha256 = s.origin_catalog_sha
        WHERE s.stream_id = %s
        """,
        (stream_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown reading stream {stream_id}")
    if int(row[0]) > snapshot_sequence:
        raise PersistenceError(
            f"reading stream {stream_id} is not visible in snapshot {snapshot_catalog_sha}"
        )
    return snapshot_sequence


# ---------------------------------------------------------------------------
# SELECT-only bounded reads
# ---------------------------------------------------------------------------


def read_reading_stream(
    conn, *, stream_id: uuid.UUID, snapshot_catalog_sha: str | None = None
) -> dict[str, Any]:
    """Return one stream's metadata, ordered chapter publications and manifest."""
    stream_id = _require_uuid(stream_id, "stream_id")
    if snapshot_catalog_sha is not None:
        _require_visible_stream(
            conn, stream_id=stream_id, snapshot_catalog_sha=snapshot_catalog_sha
        )
    row = conn.execute(
        """
        SELECT s.stream_id, s.revision_id, s.document_id, s.origin_catalog_sha,
               s.manifest_sha, s.chapter_publication_ids, s.unit_count,
               s.group_count, s.manifest, r.revision_no, s.created_at
        FROM chronicle.reading_streams s
        JOIN chronicle.document_revisions r ON r.revision_id = s.revision_id
        WHERE s.stream_id = %s
        """,
        (stream_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown reading stream {stream_id}")
    return {
        "stream_id": str(row[0]),
        "revision_id": str(row[1]),
        "document_id": str(row[2]),
        "origin_catalog_sha": row[3],
        "manifest_sha": row[4],
        "chapter_publication_ids": [str(value) for value in row[5]],
        "unit_count": int(row[6]),
        "group_count": int(row[7]),
        "manifest": row[8],
        "revision_no": int(row[9]),
        "created_at": row[10].isoformat() if row[10] is not None else None,
    }


def list_reading_streams(
    conn, *, snapshot_catalog_sha: str, limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    """List streams published no later than the snapshot catalog, in order."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
        raise PersistenceError("limit must be an integer between 1 and 100")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise PersistenceError("offset must be a non-negative integer")
    snapshot_sequence = _snapshot_sequence(conn, snapshot_catalog_sha)
    rows = conn.execute(
        """
        SELECT s.stream_id, s.revision_id, s.document_id, s.origin_catalog_sha,
               s.manifest_sha, s.unit_count, s.group_count, r.revision_no, s.created_at
        FROM chronicle.reading_streams s
        JOIN chronicle.document_revisions r ON r.revision_id = s.revision_id
        JOIN chronicle.canonical_catalogs origin
          ON origin.artifact_sha256 = s.origin_catalog_sha
        WHERE origin.publication_sequence <= %s
        ORDER BY s.document_id, r.revision_no, s.stream_id
        LIMIT %s OFFSET %s
        """,
        (snapshot_sequence, limit + 1, offset),
    ).fetchall()
    items = [
        {
            "stream_id": str(row[0]),
            "revision_id": str(row[1]),
            "document_id": str(row[2]),
            "origin_catalog_sha": row[3],
            "manifest_sha": row[4],
            "unit_count": int(row[5]),
            "group_count": int(row[6]),
            "revision_no": int(row[7]),
            "created_at": row[8].isoformat() if row[8] is not None else None,
        }
        for row in rows[:limit]
    ]
    return {"items": items, "has_more": len(rows) > limit}


def read_reading_unit(
    conn,
    *,
    stream_id: uuid.UUID,
    unit_id: str,
    snapshot_catalog_sha: str | None = None,
) -> dict[str, Any]:
    """Return one exact unit without scanning from the start of the stream.

    When ``snapshot_catalog_sha`` is supplied the stream must be visible in
    that snapshot, exactly like the ordinal page helper, so a locate/read on a
    later stream can never leak through an older exploration snapshot.
    """
    stream_id = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    if snapshot_catalog_sha is not None:
        _require_visible_stream(
            conn, stream_id=stream_id, snapshot_catalog_sha=snapshot_catalog_sha
        )
    row = conn.execute(
        _UNIT_SELECT + " WHERE stream_id = %s AND unit_id = %s",
        (stream_id, unit_id),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown reading unit {unit_id} in stream {stream_id}")
    return _unit_row_to_dict(row)


_UNIT_SELECT = """
    SELECT ordinal, unit_id, publication_id, artifact_sha256, chapter_id,
           block_id, text_hash, group_id, narrative_time, segments,
           context_entities, source_anchor_ids, continues_previous
    FROM chronicle.reading_units
"""


def _unit_row_to_dict(row: tuple) -> dict[str, Any]:
    return {
        "ordinal": int(row[0]),
        "unit_id": row[1],
        "publication_id": str(row[2]),
        "artifact_sha256": row[3],
        "chapter_id": row[4],
        "block_id": row[5],
        "text_hash": row[6],
        "group_id": row[7],
        "narrative_time": row[8],
        "segments": row[9],
        "context_entities": row[10],
        "source_anchor_ids": row[11],
        "continues_previous": row[12],
    }


def read_reading_units(
    conn,
    *,
    stream_id: uuid.UUID,
    limit: int = 20,
    after_ordinal: int | None = None,
    before_ordinal: int | None = None,
    snapshot_catalog_sha: str | None = None,
) -> dict[str, Any]:
    """Return a bounded ordinal page using an indexed keyset range.

    ``after_ordinal`` walks forward, ``before_ordinal`` walks backward; the
    two are mutually exclusive. The query fetches ``limit + 1`` rows to report
    ``has_more`` and never reads the rest of the stream.
    """
    stream_id = _require_uuid(stream_id, "stream_id")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
        raise PersistenceError("limit must be an integer between 1 and 50")
    if after_ordinal is not None and before_ordinal is not None:
        raise PersistenceError("after_ordinal and before_ordinal are mutually exclusive")
    for value, name in ((after_ordinal, "after_ordinal"), (before_ordinal, "before_ordinal")):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise PersistenceError(f"{name} must be None or a non-negative integer")
    if snapshot_catalog_sha is not None:
        _require_visible_stream(
            conn, stream_id=stream_id, snapshot_catalog_sha=snapshot_catalog_sha
        )
    else:
        exists = conn.execute(
            "SELECT 1 FROM chronicle.reading_streams WHERE stream_id = %s", (stream_id,)
        ).fetchone()
        if exists is None:
            raise PersistenceError(f"unknown reading stream {stream_id}")

    clauses = ["stream_id = %s"]
    params: list[Any] = [stream_id]
    descending = before_ordinal is not None
    if after_ordinal is not None:
        clauses.append("ordinal > %s")
        params.append(after_ordinal)
    if before_ordinal is not None:
        clauses.append("ordinal < %s")
        params.append(before_ordinal)
    direction = "DESC" if descending else "ASC"
    rows = conn.execute(
        _UNIT_SELECT + f" WHERE {' AND '.join(clauses)} ORDER BY ordinal {direction} LIMIT %s",
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    if descending:
        rows = list(reversed(rows))
    return {
        "stream_id": str(stream_id),
        "items": [_unit_row_to_dict(row) for row in rows],
        "has_more": has_more,
    }


def read_reading_groups(
    conn,
    *,
    stream_id: uuid.UUID,
    limit: int = 50,
    after_group_ordinal: int | None = None,
    before_group_ordinal: int | None = None,
    snapshot_catalog_sha: str | None = None,
) -> dict[str, Any]:
    """Return a bounded time-axis group page in reading order."""
    stream_id = _require_uuid(stream_id, "stream_id")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
        raise PersistenceError("limit must be an integer between 1 and 100")
    if after_group_ordinal is not None and before_group_ordinal is not None:
        raise PersistenceError("after_group_ordinal and before_group_ordinal are mutually exclusive")
    for value, name in (
        (after_group_ordinal, "after_group_ordinal"),
        (before_group_ordinal, "before_group_ordinal"),
    ):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise PersistenceError(f"{name} must be None or a non-negative integer")
    if snapshot_catalog_sha is not None:
        _require_visible_stream(
            conn, stream_id=stream_id, snapshot_catalog_sha=snapshot_catalog_sha
        )
    else:
        exists = conn.execute(
            "SELECT 1 FROM chronicle.reading_streams WHERE stream_id = %s", (stream_id,)
        ).fetchone()
        if exists is None:
            raise PersistenceError(f"unknown reading stream {stream_id}")

    clauses = ["stream_id = %s"]
    params: list[Any] = [stream_id]
    descending = before_group_ordinal is not None
    if after_group_ordinal is not None:
        clauses.append("ordinal > %s")
        params.append(after_group_ordinal)
    if before_group_ordinal is not None:
        clauses.append("ordinal < %s")
        params.append(before_group_ordinal)
    direction = "DESC" if descending else "ASC"
    rows = conn.execute(
        f"""
        SELECT ordinal, group_id, first_unit_ordinal, last_unit_ordinal,
               first_unit_id, last_unit_id, unit_count, year_key, period_key,
               year_label, period_label, precision, observations, continues_previous
        FROM chronicle.reading_time_groups
        WHERE {' AND '.join(clauses)}
        ORDER BY ordinal {direction}
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    if descending:
        rows = list(reversed(rows))
    items = [
        {
            "ordinal": int(row[0]),
            "group_id": row[1],
            "first_unit_ordinal": int(row[2]),
            "last_unit_ordinal": int(row[3]),
            "first_unit_id": row[4],
            "last_unit_id": row[5],
            "unit_count": int(row[6]),
            "year_key": row[7],
            "period_key": row[8],
            "year_label": row[9],
            "period_label": row[10],
            "precision": row[11],
            "observations": row[12],
            "continues_previous": row[13],
        }
        for row in rows
    ]
    return {"stream_id": str(stream_id), "items": items, "has_more": has_more}


def read_event_occurrences(
    conn,
    *,
    snapshot_catalog_sha: str,
    canonical_event_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Return bounded, snapshot-scoped positions of one canonical event.

    Membership is read from the snapshot catalog *payload* only: a later
    representation for the same canonical id is invisible to an older
    snapshot even though the global representation table would resolve it.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
        raise PersistenceError("limit must be an integer between 1 and 100")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise PersistenceError("offset must be a non-negative integer")
    canonical_event_id = _require_uuid7(canonical_event_id, "canonical_event_id")
    snapshot_sequence = _snapshot_sequence(conn, snapshot_catalog_sha)
    rows = conn.execute(
        """
        SELECT o.stream_id, o.unit_ordinal, o.event_kind, o.span_id,
               o.canonical_event_id, o.relation, o.bundle_label, o.record_ref,
               u.unit_id, u.publication_id, u.chapter_id, u.block_id
        FROM chronicle.reading_event_occurrences o
        JOIN chronicle.reading_units u
          ON u.stream_id = o.stream_id AND u.ordinal = o.unit_ordinal
        JOIN chronicle.reading_streams s ON s.stream_id = o.stream_id
        JOIN chronicle.canonical_catalogs origin
          ON origin.artifact_sha256 = s.origin_catalog_sha
        JOIN chronicle.canonical_catalogs snapshot
          ON snapshot.artifact_sha256 = %s
        WHERE o.canonical_event_id = %s
          AND origin.publication_sequence <= %s
          AND EXISTS (
              SELECT 1
              FROM jsonb_array_elements(snapshot.payload -> 'canonical_events') AS ev
              CROSS JOIN LATERAL jsonb_array_elements(ev -> 'representations') AS rep
              WHERE ev ->> 'canonical_id' = o.canonical_event_id::text
                AND rep ->> 'bundle' = o.bundle_label
                AND rep ->> 'ref' = o.record_ref
          )
        ORDER BY o.stream_id, o.unit_ordinal, o.event_kind, o.span_id
        LIMIT %s OFFSET %s
        """,
        (snapshot_catalog_sha, canonical_event_id, snapshot_sequence, limit + 1, offset),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "stream_id": str(row[0]),
            "unit_ordinal": int(row[1]),
            "event_kind": row[2],
            "span_id": row[3],
            "canonical_event_id": str(row[4]),
            "relation": row[5],
            "bundle_label": row[6],
            "record_ref": row[7],
            "unit_id": row[8],
            "publication_id": str(row[9]),
            "chapter_id": row[10],
            "block_id": row[11],
        }
        for row in rows
    ]
    return {
        "canonical_event_id": str(canonical_event_id),
        "catalog_sha": snapshot_catalog_sha,
        "items": items,
        "has_more": has_more,
    }


__all__ = [
    "OCCURRENCE_KINDS",
    "OCCURRENCE_RELATIONS",
    "list_reading_streams",
    "persist_reading_stream",
    "read_event_occurrences",
    "read_reading_groups",
    "read_reading_stream",
    "read_reading_unit",
    "read_reading_units",
]
