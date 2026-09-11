"""Chronicle C2-R2-T04 continuous-reading projection compiler.

Pure, deterministic, DB-free and model-free compiler that turns accepted
``chronicle.chapter-artifact / 0.2`` products plus the canonical catalog
into the immutable reading rows the stream store and read API consume
(Architecture Amendment 0006; ``continuous-reading.md`` sections 2-5).

Pipeline::

    accepted 0.2 artifacts (one per chapter)
        │  assembly.assemble_chapters: the same (chapter_index, local_ref)
        │  → revision_ref map used for every other chapter reference
        ▼
    revision-scoped reading units (chapter/block/source provenance kept)
        │  catalog representations of this revision's bundle label
        │  → canonical entity/event IDs
        ▼
    compile_reading_projection → units (ReadingUnit DTO) + time groups
        │                        + current/mention occurrence rows + manifest
        ▼
    pure data rows + manifest_sha256 (persist only; no body re-authority)

Guarantees fixed by the task:

- Reading text is never copied into a new authority: a unit only carries
  ``text_hash`` and program-sliced ``segments`` that reassemble the
  chapter publication's translation block verbatim.
- ``unit_id`` is recomputed from ``(revision_id, chapter_id, remapped
  block_id, chapter artifact_sha256)`` after remapping, so cross-chapter
  duplicate local IDs can never collide.
- Narrative time is compiled from this source's ``Event.time`` only, never
  from a canonical aggregate min/max year; explicit same-chapter
  inheritance, unknown/mixed/original-calendar and opaque leap months each
  keep their own axis key via :mod:`reading_contract`.
- Only consecutive units with the same period key merge; ``group_id``
  binds the first unit and key and never changes with pagination, and
  flashbacks keep their narrative order.
- A contradiction (missing/duplicate block, broken inheritance, a context
  role without source support, an oversized unit, a hash/ID collision) or
  a future/latest display field rejects the whole compile.
"""

from __future__ import annotations

import copy
from typing import Any

import assembly as _assembly
import reading_contract as _reading
from common import PersistenceError, canonical_json_bytes, sha256_json

#: Compiler output marker.
PROJECTION_SCHEMA = "chronicle.reading-projection"
PROJECTION_VERSION = "0.1"

#: Immutable per-stream manifest marker carried by the projection.
MANIFEST_SCHEMA = "chronicle.reading-stream-manifest"
MANIFEST_VERSION = "0.1"

#: Internal occurrence-row marker (event position index).
OCCURRENCE_SCHEMA = "chronicle.reading-event-occurrence"
OCCURRENCE_VERSION = "0.1"

#: Entity kinds accepted by the public ``context_entity_view`` DTO.
_ENTITY_KINDS = frozenset(
    {"person", "place", "polity", "organization", "army", "office", "group", "other"}
)

#: Snapshot discipline: the reading projection must never carry a pointer
#: to a newer/"latest" publication or catalog, only the frozen snapshot.
_FORBIDDEN_DISPLAY_KEYS = frozenset(
    {
        "latest",
        "future",
        "is_latest",
        "is_future",
        "latest_publication",
        "latest_publication_id",
        "future_publication",
        "future_publication_id",
        "latest_catalog",
        "latest_catalog_sha",
        "future_catalog",
    }
)


# ---------------------------------------------------------------------------
# Canonical catalog binding
# ---------------------------------------------------------------------------


def bundle_label_for_revision(revision_id: str) -> str:
    """Revision bundle label used by the canonical catalog.

    Delegates to the single authority (``resolve_publish.new_bundle_label``)
    instead of re-deriving the ``c1rev-<hex12>`` format here.
    """
    from resolve_publish import new_bundle_label  # local import: no DB at module load

    return new_bundle_label(revision_id)


def build_canonical_ref_map(
    catalog: dict[str, Any], *, bundle_label: str
) -> dict[str, dict[str, str]]:
    """Return ``{"entities": {revision_ref: canonical_id}, "events": {...}}``.

    Membership is the source of truth: a revision ref is canonical only if
    the catalog represents it under this revision's ``bundle_label``. A ref
    represented by two different canonical IDs in the same snapshot is a
    contradiction and fails closed; a shared *name* is never used to bind a
    ref, so unknown/unrepresented refs stay unresolved (``None``).
    """
    if not isinstance(catalog, dict):
        raise PersistenceError("canonical catalog must be a JSON object")
    if not isinstance(bundle_label, str) or not bundle_label:
        raise PersistenceError("canonical ref binding requires a bundle_label")
    result: dict[str, dict[str, str]] = {"entities": {}, "events": {}}
    for collection, target in (
        ("canonical_entities", "entities"),
        ("canonical_events", "events"),
    ):
        records = catalog.get(collection) or []
        if not isinstance(records, list):
            raise PersistenceError(f"canonical catalog {collection} must be an array")
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise PersistenceError(f"canonical catalog {collection}[{index}] must be an object")
            canonical_id = record.get("canonical_id")
            if not isinstance(canonical_id, str) or not canonical_id:
                raise PersistenceError(
                    f"canonical catalog {collection}[{index}] is missing its canonical_id"
                )
            representations = record.get("representations") or []
            if not isinstance(representations, list):
                raise PersistenceError(
                    f"canonical catalog {collection}[{index}].representations must be an array"
                )
            for representation in representations:
                if not isinstance(representation, dict):
                    raise PersistenceError(
                        f"canonical catalog {collection}[{index}] representation must be an object"
                    )
                if representation.get("bundle") != bundle_label:
                    continue
                ref = representation.get("ref")
                if not isinstance(ref, str) or not ref:
                    raise PersistenceError(
                        f"canonical catalog representation under {bundle_label!r} needs a ref"
                    )
                existing = result[target].get(ref)
                if existing is not None and existing != canonical_id:
                    raise PersistenceError(
                        f"canonical ref {ref!r} maps to both {existing!r} and "
                        f"{canonical_id!r} in one snapshot (fail closed)"
                    )
                result[target][ref] = canonical_id
    return result


# ---------------------------------------------------------------------------
# Narrative time compilation (this source's Event.time)
# ---------------------------------------------------------------------------


def _observation_precision(
    original: str, source: dict[str, Any] | None, normalized: dict[str, Any] | None
) -> str:
    if isinstance(normalized, dict):
        conversion = normalized.get("conversion_status")
        precision = normalized.get("precision")
        if conversion in ("exact", "year_only") and precision in ("day", "month", "year"):
            return precision
        if precision in ("range", "approximate"):
            return precision
    if "閏" in original or "闰" in original:
        return "month"
    if isinstance(source, dict):
        if source.get("month") is not None:
            return "month"
        if source.get("season"):
            return "month"
        if source.get("era") is not None or source.get("era_year") is not None:
            return "year"
    return "unknown"


def event_time_observation(event_ref: str, event: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a source-local time observation from one Event's ``time``.

    Returns ``None`` when the event carries no usable time text; the caller
    then keeps the unit's time ``unknown`` instead of inventing one.
    """
    if not isinstance(event, dict):
        return None
    time = event.get("time")
    if not isinstance(time, dict):
        return None
    original = time.get("original_text")
    if not isinstance(original, str) or not original:
        return None
    source = time.get("source_calendar")
    source = source if isinstance(source, dict) else None
    normalized = time.get("normalized")
    normalized = normalized if isinstance(normalized, dict) else None
    return {
        "event_ref": event_ref,
        "original_text": original,
        "source_calendar": copy.deepcopy(source),
        "normalized": copy.deepcopy(normalized),
        "precision": _observation_precision(original, source, normalized),
    }


# ---------------------------------------------------------------------------
# Segments / span views / context
# ---------------------------------------------------------------------------


def _span_view(span: dict[str, Any], text: str, event_ids: dict[str, str]) -> dict[str, Any]:
    start = span.get("start")
    end = span.get("end")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or end <= start
        or end > len(text)
    ):
        raise PersistenceError(
            f"reading span {span.get('span_id')!r} has out-of-range coordinates [{start},{end})"
        )
    target_ref = span.get("target_ref")
    target_ref = target_ref if isinstance(target_ref, str) else None
    return {
        "span_id": span.get("span_id"),
        "text": text[start:end],
        "start": start,
        "end": end,
        "status": span.get("status"),
        "relation": span.get("relation"),
        "target_ref": target_ref,
        "target_event_id": event_ids.get(target_ref) if target_ref else None,
        "candidate_refs": list(span.get("candidate_refs") or []),
    }


def build_segments_and_views(
    text: str, resolved_spans: list[dict[str, Any]], event_ids: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Slice one translation block into ordered text/event segments.

    Concatenating every segment ``text`` reproduces the accepted translation
    block verbatim; the browser never re-splits or offsets the string.
    """
    if not isinstance(text, str) or text == "":
        raise PersistenceError("reading unit translation text must be a non-empty string")
    views = [_span_view(span, text, event_ids) for span in resolved_spans if isinstance(span, dict)]
    views.sort(key=lambda view: (view["start"], view["end"]))
    overlap, detail = _reading.spans_overlap(views)
    if overlap:
        raise PersistenceError(f"cannot build reading segments: {detail}")
    segments: list[dict[str, Any]] = []
    cursor = 0
    for view in views:
        if view["start"] > cursor:
            segments.append({"kind": "text", "text": text[cursor:view["start"]]})
        segments.append({"kind": "event", "text": view["text"], "span": copy.deepcopy(view)})
        cursor = view["end"]
    if cursor < len(text):
        segments.append({"kind": "text", "text": text[cursor:]})
    if not segments:
        segments.append({"kind": "text", "text": text})
    joined = "".join(segment["text"] for segment in segments)
    if joined != text:
        raise PersistenceError("reading segments do not reassemble the translation block text")
    return segments, views


def _entity_kind(record: dict[str, Any]) -> str:
    kind = record.get("type")
    return kind if kind in _ENTITY_KINDS else "other"


# ---------------------------------------------------------------------------
# Snapshot discipline
# ---------------------------------------------------------------------------


def assert_no_future_latest_fields(value: Any, path: str = "$") -> None:
    """Fail closed when a projection row carries a newer/latest pointer."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _FORBIDDEN_DISPLAY_KEYS:
                raise PersistenceError(
                    f"{path}.{key} is a future/latest display field; "
                    "the reading projection is bound to one snapshot"
                )
            assert_no_future_latest_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_future_latest_fields(child, f"{path}[{index}]")


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


def _require_string(value: Any, owner: str) -> str:
    if not isinstance(value, str) or not value:
        raise PersistenceError(f"{owner} must be a non-empty string")
    return value


def _anchor_ids_for_block(
    anchors: list[dict[str, Any]], chapter_id: str, source_block_ids: list[str]
) -> list[str]:
    source_set = {block for block in source_block_ids if isinstance(block, str)}
    ids: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict) or anchor.get("chapter_id") != chapter_id:
            continue
        anchor_id = anchor.get("anchor_id")
        if not isinstance(anchor_id, str) or not anchor_id:
            continue
        if anchor.get("first_block_id") in source_set or anchor.get("last_block_id") in source_set:
            ids.add(anchor_id)
    return sorted(ids)


def _compile_narrative_time(
    unit: dict[str, Any],
    *,
    unit_by_block: dict[str, dict[str, Any]],
    event_index: dict[str, dict[str, Any]],
    resolved: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Compile the per-unit narrative-time display/grouping object.

    ``events``/``mixed`` observations come from the mapped time-basis events'
    own ``Event.time``; ``inherit`` reuses the earlier same-chapter unit's
    resolved observations after verifiying the chain terminates at a
    time-bearing mode; ``unknown`` carries no observations.
    """
    mode = unit.get("narrative_time", {}).get("mode")
    current_refs = list(unit.get("current_event_refs") or [])
    time_refs = list(unit.get("narrative_time", {}).get("event_refs") or [])

    def observations_for(refs: list[str]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for ref in refs:
            observation = event_time_observation(ref, event_index.get(ref))
            if observation is not None:
                observations.append(observation)
        return observations

    if mode == "events":
        display = _reading.narrative_time_display(
            "events", observations_for(time_refs), source_event_refs=current_refs
        )
    elif mode == "mixed":
        display = _reading.narrative_time_display(
            "mixed", observations_for(time_refs), source_event_refs=current_refs
        )
    elif mode == "unknown":
        display = _reading.narrative_time_display("unknown", [])
    elif mode == "inherit":
        target = unit.get("narrative_time", {}).get("from_block_id")
        seen: set[str] = set()
        cursor = target
        inherited: list[dict[str, Any]] | None = None
        while isinstance(cursor, str):
            if cursor in seen:
                raise PersistenceError(
                    f"reading inheritance chain forms a cycle at {cursor!r}"
                )
            seen.add(cursor)
            ancestor = unit_by_block.get(cursor)
            if ancestor is None:
                raise PersistenceError(
                    f"reading unit inherits from unknown block {cursor!r} "
                    "(broken inheritance)"
                )
            ancestor_mode = ancestor.get("narrative_time", {}).get("mode")
            if ancestor_mode == "inherit":
                cursor = ancestor.get("narrative_time", {}).get("from_block_id")
                continue
            if ancestor_mode == "events":
                inherited = observations_for(resolved[cursor]["time_refs"])
                break
            raise PersistenceError(
                f"reading inheritance from {target!r} terminates at {ancestor_mode!r} "
                f"block {cursor!r}; it must terminate at an events block"
            )
        if inherited is None:
            raise PersistenceError(
                f"reading inheritance from {target!r} does not terminate at a time-bearing block"
            )
        display = _reading.narrative_time_display(
            "inherit", inherited, from_block_id=target
        )
    else:
        raise PersistenceError(f"reading unit has invalid narrative mode {mode!r}")
    return display


def compile_reading_projection(
    *,
    accepted_artifacts: list[dict[str, Any]],
    chapter_plan: dict[str, Any],
    catalog: dict[str, Any],
    stream_id: str,
    publication_by_chapter: dict[str, str],
    bundle_label: str | None = None,
    limits: _reading.ReadingLimits | None = None,
) -> dict[str, Any]:
    """Compile the immutable reading rows and manifest for one revision.

    See the module docstring for the fixed contracts. Any contradiction
    raises :class:`PersistenceError` (fail closed); a partial projection is
    never returned.
    """
    limits = limits if limits is not None else _reading.ReadingLimits()
    stream_id = _require_string(stream_id, "stream_id")
    if not isinstance(publication_by_chapter, dict):
        raise PersistenceError("publication_by_chapter must be a JSON object")
    revision_id = _require_string(chapter_plan.get("revision_id"), "chapter_plan.revision_id")
    if bundle_label is None:
        bundle_label = bundle_label_for_revision(revision_id)
    canonical = build_canonical_ref_map(catalog, bundle_label=bundle_label)
    event_ids = canonical["events"]
    entity_ids = canonical["entities"]
    catalog_sha = sha256_json(catalog)

    assembled = _assembly.assemble_chapters(
        accepted_artifacts=accepted_artifacts, chapter_plan=chapter_plan
    )
    assembled_reading = assembled.get("reading_units") or []
    if not assembled_reading:
        raise PersistenceError(
            "reading projection requires accepted 0.2 artifacts; "
            "the supplied chapter products carry no reading annotations"
        )

    bundle = assembled["bundle"]
    entity_index = {
        record["temp_id"]: record
        for record in bundle.get("entities") or []
        if isinstance(record, dict) and isinstance(record.get("temp_id"), str)
    }
    event_index = {
        record["temp_id"]: record
        for record in bundle.get("events") or []
        if isinstance(record, dict) and isinstance(record.get("temp_id"), str)
    }
    block_index = {
        record["block_id"]: record
        for record in assembled.get("translation_blocks") or []
        if isinstance(record, dict) and isinstance(record.get("block_id"), str)
    }
    anchors = list(assembled.get("anchors") or [])
    plan_by_id = {
        chapter["chapter_id"]: chapter
        for chapter in chapter_plan.get("chapters") or []
        if isinstance(chapter, dict)
    }
    source_title = bundle.get("source", {}).get("title")

    # Assembly emits units in source order (chapter order, then the chapter's
    # own block order). Keep that order; re-sorting by the generated revision
    # block ID would reorder non-standard source IDs and mask collisions.
    ordered_units = list(assembled_reading)

    # -- coverage: every translation block exactly once, in source order ----
    expected_blocks = [record["block_id"] for record in assembled["translation_blocks"]]
    actual_blocks = [unit.get("block_id") for unit in ordered_units]
    if len(actual_blocks) != len(set(actual_blocks)):
        raise PersistenceError("reading projection repeats a translation block (fail closed)")
    if actual_blocks != expected_blocks:
        raise PersistenceError(
            "reading unit blocks do not match the assembled translation blocks in order"
        )

    raw_by_block: dict[str, dict[str, Any]] = {}
    for unit in ordered_units:
        block_id = unit["block_id"]
        if block_id in raw_by_block:
            raise PersistenceError(f"reading projection repeats block {block_id!r}")
        raw_by_block[block_id] = unit

    # -- base narrative time (inherit resolved against earlier units) -------
    unit_by_block: dict[str, dict[str, Any]] = {}
    resolved_refs: dict[str, dict[str, list[str]]] = {}
    mode_by_block: dict[str, str] = {}
    for unit in ordered_units:
        block_id = unit["block_id"]
        mode_by_block[block_id] = unit["narrative_time"]["mode"]
        resolved_refs[block_id] = {
            "time_refs": list(unit["narrative_time"].get("event_refs") or []),
            "current_refs": list(unit.get("current_event_refs") or []),
        }
        unit_by_block[block_id] = unit

    units: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    unit_canonical_ids: dict[str, str] = {}
    for ordinal, unit in enumerate(ordered_units):
        block_id = unit["block_id"]
        block = block_index.get(block_id)
        if block is None:
            raise PersistenceError(f"reading unit references unknown translation block {block_id!r}")
        chapter_id = unit["chapter_id"]
        chapter_index = unit["chapter_index"]
        artifact_sha256 = unit["artifact_sha256"]
        publication_id = publication_by_chapter.get(chapter_id)
        if not isinstance(publication_id, str) or not publication_id:
            raise PersistenceError(
                f"reading projection has no publication for chapter {chapter_id!r}"
            )
        text = block.get("text")
        if not isinstance(text, str) or not text:
            raise PersistenceError(
                f"translation block {block_id!r} has no text to compile"
            )
        source_block_ids = [
            value for value in block.get("source_block_ids") or [] if isinstance(value, str)
        ]
        anchor_ids = _anchor_ids_for_block(anchors, chapter_id, source_block_ids)
        segments, _views = build_segments_and_views(text, unit.get("resolved_spans") or [], event_ids)
        narrative_time = _compile_narrative_time(
            unit,
            unit_by_block=unit_by_block,
            event_index=event_index,
            resolved=resolved_refs,
        )
        context_entities: list[dict[str, Any]] = []
        for context in unit.get("context_entities") or []:
            if not isinstance(context, dict):
                continue
            entity_ref = context.get("entity_ref")
            record = entity_index.get(entity_ref)
            if record is None:
                raise PersistenceError(
                    f"reading unit {block_id!r} context references unknown entity {entity_ref!r}"
                )
            roles: list[dict[str, Any]] = []
            for role in context.get("event_roles") or []:
                if not isinstance(role, dict):
                    continue
                event_ref = role.get("event_ref")
                if not isinstance(event_ref, str) or event_ref not in event_index:
                    raise PersistenceError(
                        f"reading unit {block_id!r} context role references unknown event "
                        f"{event_ref!r} (unsupported role)"
                    )
                if event_ref not in (unit.get("current_event_refs") or []):
                    raise PersistenceError(
                        f"reading unit {block_id!r} context role event {event_ref!r} "
                        "is not a current event of this unit (unsupported role)"
                    )
                role_value = role.get("role")
                if not isinstance(role_value, str) or not role_value:
                    raise PersistenceError(
                        f"reading unit {block_id!r} context role for {entity_ref!r} "
                        "has no source participant role"
                    )
                roles.append(
                    {
                        "event_ref": event_ref,
                        "role": role_value,
                        "participant_index": role.get("participant_index"),
                    }
                )
            context_entities.append(
                {
                    "entity_ref": entity_ref,
                    "name": record.get("canonical_name"),
                    "canonical_id": entity_ids.get(entity_ref),
                    "kind": _entity_kind(record),
                    "importance": context.get("importance"),
                    "source_anchor_ids": list(anchor_ids),
                    "event_roles": roles,
                }
            )
        unit_id = _reading.unit_id_for(
            revision_id=revision_id,
            chapter_id=chapter_id,
            block_id=block_id,
            artifact_sha256=artifact_sha256,
        )
        if unit_id in unit_canonical_ids:
            raise PersistenceError(f"reading unit_id collision at {unit_id!r} (fail closed)")
        unit_canonical_ids[unit_id] = block_id
        accepted_text_hash = unit.get("text_hash")
        if _reading.sha256_text(text) != accepted_text_hash:
            raise PersistenceError(
                f"reading unit {block_id!r} text hash does not match the accepted block text"
            )
        units.append(
            {
                "unit_id": unit_id,
                "ordinal": ordinal,
                "stream_id": stream_id,
                "catalog_sha": catalog_sha,
                "publication_id": publication_id,
                "chapter_id": chapter_id,
                "block_id": block_id,
                "artifact_sha256": artifact_sha256,
                "text_hash": _reading.sha256_text(text),
                "source_anchor_ids": list(anchor_ids),
                "segments": segments,
                "narrative_time": narrative_time,
                "context_entities": context_entities,
                "group_id": None,
                "continues_previous": False,
            }
        )
        full_text_parts.append(text)

    collisions = _reading.detect_unit_id_collisions(units)
    if collisions:
        raise PersistenceError("; ".join(collisions))

    # -- consecutive time groups and continuation metadata ------------------
    groups = _reading.compile_time_groups(units, stream_id=stream_id, catalog_sha=catalog_sha)
    cursor = 0
    previous_period_key: str | None = None
    for group in groups:
        count = group["unit_count"]
        for unit in units[cursor : cursor + count]:
            unit["group_id"] = group["group_id"]
            continues = previous_period_key is not None and unit["narrative_time"]["period_key"] == previous_period_key
            unit["continues_previous"] = continues
            unit["narrative_time"]["continues_previous"] = continues
            previous_period_key = unit["narrative_time"]["period_key"]
        cursor += count
    if cursor != len(units):
        raise PersistenceError("time groups do not partition the compiled reading units")

    # -- current/mention event occurrence rows ------------------------------
    occurrences = _compile_occurrences(
        units,
        event_index=event_index,
        event_ids=event_ids,
        chapter_title={
            chapter_id: plan_by_id.get(chapter_id, {}).get("title")
            for chapter_id in {unit["chapter_id"] for unit in units}
        },
    )

    full_text_sha256 = _reading.sha256_text("".join(full_text_parts))
    chapter_publications = []
    for chapter in chapter_plan.get("chapters") or []:
        chapter_id = chapter.get("chapter_id")
        publication_id = publication_by_chapter.get(chapter_id)
        if not isinstance(publication_id, str) or not publication_id:
            raise PersistenceError(
                f"reading projection has no publication for chapter {chapter_id!r}"
            )
        chapter_publications.append(
            {
                "chapter_id": chapter_id,
                "chapter_index": chapter.get("chapter_index"),
                "publication_id": publication_id,
                "artifact_sha256": next(
                    (
                        unit["artifact_sha256"]
                        for unit in ordered_units
                        if unit["chapter_id"] == chapter_id
                    ),
                    None,
                ),
                "unit_count": sum(1 for unit in units if unit["chapter_id"] == chapter_id),
            }
        )

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "version": MANIFEST_VERSION,
        "stream_id": stream_id,
        "revision_id": revision_id,
        "catalog_sha": catalog_sha,
        "bundle_label": bundle_label,
        "source_sha256": chapter_plan.get("source_sha256"),
        "normalized_sha256": chapter_plan.get("normalized_sha256"),
        "chapters": chapter_publications,
        "unit_count": len(units),
        "group_count": len(groups),
        "occurrence_count": len(occurrences),
        "full_text_sha256": full_text_sha256,
        "source_title": source_title,
    }

    projection = {
        "schema": PROJECTION_SCHEMA,
        "version": PROJECTION_VERSION,
        "stream_id": stream_id,
        "revision_id": revision_id,
        "catalog_sha": catalog_sha,
        "bundle_label": bundle_label,
        "full_text_sha256": full_text_sha256,
        "manifest": manifest,
        "manifest_sha256": sha256_json(manifest),
        "chapter_publications": chapter_publications,
        "units": units,
        "groups": groups,
        "occurrences": occurrences,
        "counts": {
            "units": len(units),
            "groups": len(groups),
            "occurrences": len(occurrences),
        },
    }
    _validate_projection(projection, limits)
    return projection


def _compile_occurrences(
    units: list[dict[str, Any]],
    *,
    event_index: dict[str, dict[str, Any]],
    event_ids: dict[str, str],
    chapter_title: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compile current/mention event position rows for exact lookup.

    Only resolved spans bound to a canonical event become navigable rows; a
    span without a canonical binding stays in the unit's segments as an
    unresolved mention and never invents a name-based link. Current events
    that carry no span keep an explicit current-event marker row.
    """
    occurrences: list[dict[str, Any]] = []
    for unit in units:
        covered: set[str] = set()
        for segment in unit["segments"]:
            if segment.get("kind") != "event":
                continue
            span = segment.get("span") or {}
            target_ref = span.get("target_ref")
            canonical_id = span.get("target_event_id")
            if not isinstance(target_ref, str) or not isinstance(canonical_id, str):
                continue
            relation = "current" if span.get("relation") == "current" else "mention"
            covered.add(target_ref)
            event = event_index.get(target_ref, {})
            occurrences.append(
                {
                    "schema": OCCURRENCE_SCHEMA,
                    "version": OCCURRENCE_VERSION,
                    "stream_id": unit["stream_id"],
                    "unit_id": unit["unit_id"],
                    "unit_ordinal": unit["ordinal"],
                    "chapter_id": unit["chapter_id"],
                    "publication_id": unit["publication_id"],
                    "block_id": unit["block_id"],
                    "span_id": span.get("span_id"),
                    "event_ref": target_ref,
                    "canonical_event_id": canonical_id,
                    "relation": relation,
                    "chapter_title": chapter_title.get(unit["chapter_id"]),
                    "source_anchor_ids": list(unit["source_anchor_ids"]),
                    "excerpt": span.get("text") or str(event.get("title") or ""),
                }
            )
        for event_ref in unit["narrative_time"].get("event_refs") or []:
            if event_ref in covered:
                continue
            canonical_id = event_ids.get(event_ref)
            if not isinstance(canonical_id, str):
                continue
            event = event_index.get(event_ref, {})
            text = "".join(
                segment["text"] for segment in unit["segments"] if segment.get("kind") == "text"
            )
            occurrences.append(
                {
                    "schema": OCCURRENCE_SCHEMA,
                    "version": OCCURRENCE_VERSION,
                    "stream_id": unit["stream_id"],
                    "unit_id": unit["unit_id"],
                    "unit_ordinal": unit["ordinal"],
                    "chapter_id": unit["chapter_id"],
                    "publication_id": unit["publication_id"],
                    "block_id": unit["block_id"],
                    "span_id": None,
                    "event_ref": event_ref,
                    "canonical_event_id": canonical_id,
                    "relation": "current",
                    "chapter_title": chapter_title.get(unit["chapter_id"]),
                    "source_anchor_ids": list(unit["source_anchor_ids"]),
                    "excerpt": str(event.get("title") or text[:160]),
                }
            )
    occurrences.sort(
        key=lambda row: (
            row["unit_ordinal"],
            row["relation"],
            row["canonical_event_id"],
            row["span_id"] or "",
            row["event_ref"],
        )
    )
    return occurrences


def _validate_projection(projection: dict[str, Any], limits: _reading.ReadingLimits) -> None:
    for unit in projection["units"]:
        if len(canonical_json_bytes(unit)) > limits.unit_max_bytes:
            raise PersistenceError(
                f"reading unit {unit['unit_id']!r} exceeds unit_max_bytes {limits.unit_max_bytes}"
            )
        errors = _reading.validate_reading_dto("reading_unit", unit)
        if errors:
            raise PersistenceError(
                f"compiled reading unit {unit['unit_id']!r} is invalid: " + "; ".join(errors)
            )
    for group in projection["groups"]:
        errors = _reading.validate_reading_dto("time_group", group)
        if errors:
            raise PersistenceError(
                f"compiled time group {group['group_id']!r} is invalid: " + "; ".join(errors)
            )
    assert_no_future_latest_fields(projection)


def projection_canonical_bytes(projection: dict[str, Any]) -> bytes:
    """Canonical bytes for hashing/persistence of a compiled projection."""
    if not isinstance(projection, dict):
        raise PersistenceError("reading projection must be a JSON object")
    return canonical_json_bytes(projection)


__all__ = [
    "MANIFEST_SCHEMA",
    "MANIFEST_VERSION",
    "OCCURRENCE_SCHEMA",
    "OCCURRENCE_VERSION",
    "PROJECTION_SCHEMA",
    "PROJECTION_VERSION",
    "assert_no_future_latest_fields",
    "build_canonical_ref_map",
    "build_segments_and_views",
    "bundle_label_for_revision",
    "compile_reading_projection",
    "event_time_observation",
    "projection_canonical_bytes",
]
