"""Chronicle C1-T7 source assembly and within-book resolution (application-owned).

Pure deterministic logic with no database, model, or network access
(Architecture Amendment 0006). The durable worker path lives in
``apps/chronicle/worker/ingestion_worker.py`` (``assemble`` stage) on the
C1-T1 control-plane tables behind ``CHRONICLE_DATABASE_URL``.

Contract summary (GitHub Issue #496):

- Many independently extracted chunk outputs from one immutable document
  revision are assembled into one revision-scoped staged bundle that
  satisfies the reused C0 Source/Entity/Event/Claim contract
  (``CONTRACT_VERSION``) and the canonical JSON Schema. No canonical
  identity is assigned: every assembled record keeps a ``temp_id`` and
  the bundle carries no ``id`` anywhere.
- Chunk-local temp IDs (``ent_001`` in chunk 0 vs ``ent_001`` in chunk 1)
  are remapped into revision-scoped temp IDs
  (``ent_000001``-style) so independent chunk namespaces can never
  collide. Every reference (claim subject/object, event participants /
  places / parent, evidence source links) is rewritten through the same
  mapping.
- The per-chunk ``source`` records merge into one revision-scoped
  ``src_001``. Chunk evidence locators keep the C0 shape unchanged; the
  originating chunk/run/revision coordinates travel in the assembly
  report's per-record provenance map, so every assembled record traces
  back to its immutable revision and originating chunk/run.
- Boundary-induced duplicate extraction (the same assertion extracted in
  two adjacent chunks because of boundary context or limited overlap) is
  detected by exact-signature match and suppressed deterministically
  (first chunk wins) only when the chunk locators verify the overlap:
  intersecting source spans or declared boundary overlap characters.
  Adjacent non-overlapping repeats and distant repetitions survive as
  distinct occurrences and are recorded as preserved repeats.
  Suppression is recorded with evidence, never silent.
- Within-book Entity/Event candidate linking is conservative and reuses
  the C0 resolution decision vocabulary (``same_entity`` /
  ``uncertain``; ``same_occurrence`` / ``uncertain``). A shared name
  alone never proves identity: same-name records stay ``uncertain``
  unless stronger source-bounded evidence exists (a second shared
  stable surface, or co-reference proven by a suppressed boundary
  duplicate both records participated in). Ambiguous same-name
  occurrences across types, and genuine repeated occurrences, are
  never merged.
- The assembly artifact (bundle + within-book links + report) is fully
  deterministic: rerunning over unchanged accepted chunk outputs yields
  byte-identical canonical JSON. No timestamps, UUIDs, or randomness
  appear anywhere in the artifact.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from common import PersistenceError, canonical_json_bytes, sha256_json

try:
    from extraction import canonical_schema
except ImportError:  # pragma: no cover - standalone import without sibling
    canonical_schema = None  # type: ignore[assignment]

#: Version of this source-assembly pipeline step.
ASSEMBLY_VERSION = "c1t7-v1"

#: Reused C0 contract-first extraction contract (contract_v0 / repair_v0).
CONTRACT_VERSION = "0.2"

#: Reused C0 staged-bundle schema version.
SCHEMA_VERSION = "0.1"

#: Schema marker for the within-book link set emitted beside the bundle.
LINKS_SCHEMA = "chronicle.within-book-links"
LINKS_VERSION = "0.1"

#: Schema marker for the assembly report emitted beside the bundle.
REPORT_SCHEMA = "chronicle.source-assembly-report"
REPORT_VERSION = "0.1"

#: Control-plane artifact type for the persisted assembly output.
ARTIFACT_TYPE = "assembled-source-bundle"

#: Marker proving the assembled bundle is source-owned processing output.
NON_AUTHORITATIVE_NOTE = (
    "assembled source bundle is deterministic processing output over one "
    "immutable document revision, not historical authority; canonical "
    "identity remains owned by the C0 staged/resolution/canonical path"
)

#: Deterministic rule confidences for within-book link decisions. These
#: measure confidence in the link decision only (C0 resolution direction),
#: never historical-truth confidence.
CONFIDENCE_SAME_ENTITY_EXACT_NAME = 0.9
CONFIDENCE_UNCERTAIN = 0.5
CONFIDENCE_SAME_OCCURRENCE_DUPLICATE = 1.0

_TEMP_ID_RE = re.compile(r"^(src|ent|evt|clm)_(\d+)$")

# Event types narrow enough that same-type + shared participant +
# compatible time is worth an uncertain candidate even when a chunk
# omits the place (C0 resolution direction, reused within one book).
_LOW_AMBIGUITY_EVENT_TYPES = {
    "birth",
    "death",
    "epidemic",
    "retreat",
    "surrender",
}

_EVENT_TYPE_GROUPS = (
    {"movement", "retreat"},
    {"military", "battle"},
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _require_chunk_index(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PersistenceError("chunk_index must be a non-negative integer")
    return value


def _records(candidate: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = candidate.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise PersistenceError(f"chunk candidate {name} must be an array")
    for item in value:
        if not isinstance(item, dict):
            raise PersistenceError(f"chunk candidate {name} must hold JSON objects")
    return list(value)


def _identity(record: dict[str, Any]) -> str:
    value = record.get("temp_id")
    if not isinstance(value, str) or not value:
        raise PersistenceError("assembled record requires a temp_id")
    return value


def _stable_entity_surfaces(entity: dict[str, Any]) -> set[str]:
    """Exact stable surfaces: canonical name, aliases, non-contextual mentions."""
    surfaces: set[str] = set()
    name = entity.get("canonical_name")
    if isinstance(name, str) and name:
        surfaces.add(name)
    for alias in entity.get("aliases") or []:
        if isinstance(alias, str) and alias:
            surfaces.add(alias)
    for mention in entity.get("mentions") or []:
        if not isinstance(mention, dict) or mention.get("contextual"):
            continue
        text = mention.get("text")
        if isinstance(text, str) and text:
            surfaces.add(text)
    return surfaces


def _event_time_signature(event: dict[str, Any]) -> dict[str, Any]:
    time = event.get("time")
    if not isinstance(time, dict):
        return {
            "original_text": None,
            "era": None,
            "era_year": None,
            "season": None,
            "month": None,
            "normalized_year": None,
        }
    source = time.get("source_calendar") if isinstance(time.get("source_calendar"), dict) else {}
    normalized = time.get("normalized") if isinstance(time.get("normalized"), dict) else {}
    month = source.get("month")
    return {
        "original_text": time.get("original_text"),
        "era": source.get("era"),
        "era_year": source.get("era_year"),
        "season": source.get("season"),
        "month": month if isinstance(month, int) and not isinstance(month, bool) else None,
        "normalized_year": normalized.get("year"),
    }


def _time_compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    ltime = _event_time_signature(left)
    rtime = _event_time_signature(right)
    if (
        ltime["normalized_year"] is not None
        and rtime["normalized_year"] is not None
        and ltime["normalized_year"] != rtime["normalized_year"]
    ):
        return False
    if ltime["era"] and rtime["era"] and ltime["era"] != rtime["era"]:
        return False
    if (
        ltime["era_year"] is not None
        and rtime["era_year"] is not None
        and ltime["era_year"] != rtime["era_year"]
    ):
        return False
    if ltime["season"] and rtime["season"] and ltime["season"] != rtime["season"]:
        return False
    if (
        ltime["month"] is not None
        and rtime["month"] is not None
        and ltime["month"] != rtime["month"]
    ):
        return False
    return True


def _event_type_compatible(left_type: Any, right_type: Any) -> bool:
    if isinstance(left_type, str) and left_type == right_type:
        return True
    return any(left_type in group and right_type in group for group in _EVENT_TYPE_GROUPS)


def _remapped_id(prefix: str, chunk_index: int, local: str) -> str:
    """Deterministic revision-scoped temp ID satisfying the C0 pattern."""
    match = _TEMP_ID_RE.match(local)
    if match and match.group(1) == prefix:
        number = int(match.group(2))
    else:
        number = 0
    if chunk_index > 999 or number > 999:
        raise PersistenceError(
            f"chunk {chunk_index} record {local!r} exceeds the revision-scoped ID space"
        )
    return f"{prefix}_{chunk_index:03d}{number:03d}"


def _spans_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Whether two chunk locators carry verified overlap/boundary evidence.

    True only when the source spans intersect (shared source bytes the
    same evidence could come from) or the later chunk declares boundary
    overlap characters from segmentation. Merely adjacent
    non-overlapping spans are not duplicate evidence: a genuine
    repeated passage there must survive as distinct occurrences.
    """

    def _span(locator: dict[str, Any]) -> tuple[int, int] | None:
        start, end = locator.get("source_start"), locator.get("source_end")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and start < end
        ):
            return start, end
        return None

    first_span, second_span = _span(first), _span(second)
    if first_span is not None and second_span is not None:
        if first_span[0] < second_span[1] and second_span[0] < first_span[1]:
            return True
    overlap_prev = second.get("overlap_prev_chars")
    if (
        isinstance(overlap_prev, int)
        and not isinstance(overlap_prev, bool)
        and overlap_prev > 0
    ):
        return True
    return False


def _claim_surface_key(ref: Any, entity_names: dict[str, str], event_sigs: dict[str, str]) -> Any:
    if not isinstance(ref, dict):
        return None
    kind, identity = ref.get("kind"), ref.get("ref")
    if kind == "entity_ref" and isinstance(identity, str):
        return ("entity", entity_names.get(identity, identity))
    if kind == "event_ref" and isinstance(identity, str):
        return ("event", event_sigs.get(identity, identity))
    return ("literal", canonical_json_bytes(ref).decode("utf-8"))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_chunk_input(chunk: dict[str, Any]) -> dict[str, Any]:
    """Check one accepted chunk output; return normalized accessors."""
    if not isinstance(chunk, dict):
        raise PersistenceError("assembly chunk input must be a JSON object")
    chunk_index = _require_chunk_index(chunk.get("chunk_index"))
    candidate = chunk.get("candidate")
    if not isinstance(candidate, dict):
        raise PersistenceError(f"chunk {chunk_index} is missing its accepted candidate")
    locator = chunk.get("locator")
    if not isinstance(locator, dict):
        raise PersistenceError(f"chunk {chunk_index} is missing its source locator")
    if locator.get("chunk_index") != chunk_index:
        raise PersistenceError(
            f"chunk {chunk_index} locator names chunk {locator.get('chunk_index')!r}"
        )
    for key in ("revision_id", "source_sha256", "content_sha256"):
        if not isinstance(locator.get(key), str) or not locator.get(key):
            raise PersistenceError(f"chunk {chunk_index} locator is missing {key}")
    run_attempt = chunk.get("run_attempt")
    if not isinstance(run_attempt, int) or isinstance(run_attempt, bool) or run_attempt < 1:
        raise PersistenceError(f"chunk {chunk_index} run_attempt must be a positive integer")
    model_version = chunk.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise PersistenceError(f"chunk {chunk_index} model_version must be a non-empty string")

    source = candidate.get("source")
    if not isinstance(source, dict):
        raise PersistenceError(f"chunk {chunk_index} candidate is missing its source")

    def _reject_canonical(records: list[dict[str, Any]], kind: str) -> None:
        for record in records:
            if "id" in record:
                raise PersistenceError(
                    f"chunk {chunk_index} {kind} record must not carry canonical "
                    f"identity ({record.get('id')!r}); temp IDs only"
                )

    entities = _records(candidate, "entities")
    events = _records(candidate, "events")
    claims = _records(candidate, "claims")
    warnings = _records(candidate, "warnings")
    _reject_canonical([source], "source")
    _reject_canonical(entities, "entity")
    _reject_canonical(events, "event")
    _reject_canonical(claims, "claim")

    seen: set[str] = set()
    for record in [source, *entities, *events, *claims]:
        temp_id = record.get("temp_id")
        if not isinstance(temp_id, str) or not temp_id:
            raise PersistenceError(f"chunk {chunk_index} record requires a temp_id")
        if temp_id in seen:
            raise PersistenceError(f"chunk {chunk_index} carries duplicate temp_id {temp_id!r}")
        seen.add(temp_id)

    source_ref = source.get("temp_id")
    for record in claims:
        evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
        if evidence.get("source_ref") != source_ref:
            raise PersistenceError(
                f"chunk {chunk_index} claim {record.get('temp_id')!r} references "
                "unknown source"
            )
    return {
        "chunk_index": chunk_index,
        "candidate": candidate,
        "locator": locator,
        "run_attempt": run_attempt,
        "model_version": model_version,
        "source": source,
        "entities": entities,
        "events": events,
        "claims": claims,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def assemble_revision(
    *,
    chunks: list[dict[str, Any]],
    document: dict[str, Any] | None = None,
    revision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble accepted chunk outputs into one source-owned bundle.

    Returns ``{"bundle", "within_book_links", "report"}``. Every step is
    deterministic over the inputs: unchanged accepted chunk outputs
    produce byte-identical canonical JSON. Failures raise
    :class:`PersistenceError` (fail closed) instead of producing a
    partially merged bundle.
    """
    if not isinstance(chunks, list) or not chunks:
        raise PersistenceError("assembly requires at least one accepted chunk output")
    document = dict(document or {})
    revision = dict(revision or {})

    normalized = [_validate_chunk_input(chunk) for chunk in chunks]
    normalized.sort(key=lambda item: item["chunk_index"])
    indexes = [item["chunk_index"] for item in normalized]
    if len(set(indexes)) != len(indexes):
        raise PersistenceError(f"assembly chunk indexes are not unique: {indexes}")

    revision_id = revision.get("revision_id")
    source_sha256 = revision.get("source_sha256")
    if (revision_id is not None and not isinstance(revision_id, str)) or (
        source_sha256 is not None and not isinstance(source_sha256, str)
    ):
        raise PersistenceError("revision identity must use string fields")
    for item in normalized:
        locator = item["locator"]
        if revision_id is not None and locator.get("revision_id") != revision_id:
            raise PersistenceError(
                f"chunk {item['chunk_index']} belongs to revision "
                f"{locator.get('revision_id')!r}, not {revision_id!r}; refusing to "
                "mix revisions in one source bundle"
            )
        if source_sha256 is not None and locator.get("source_sha256") != source_sha256:
            raise PersistenceError(
                f"chunk {item['chunk_index']} source hash does not match the "
                "revision source hash; refusing to assemble"
            )
    if revision_id is None:
        revision_id = normalized[0]["locator"]["revision_id"]
    if source_sha256 is None:
        source_sha256 = normalized[0]["locator"]["source_sha256"]
    revision_no = revision.get("revision_no")

    # -- remap chunk-local temp IDs into one revision-scoped namespace --
    id_map: dict[tuple[int, str], str] = {}
    provenance: dict[str, dict[str, Any]] = {}

    def _register(chunk_index: int, prefix: str, records: list[dict[str, Any]]) -> None:
        for position, record in enumerate(records):
            old = _identity(record)
            match = _TEMP_ID_RE.match(old)
            local = old if (match and match.group(1) == prefix) else f"{prefix}_{position + 1:03d}"
            new = _remapped_id(prefix, chunk_index, local)
            if new in provenance:
                raise PersistenceError(f"remapped ID collision at {new!r} (fail closed)")
            id_map[(chunk_index, old)] = new

    for item in normalized:
        _register(item["chunk_index"], "ent", item["entities"])
        _register(item["chunk_index"], "evt", item["events"])
        _register(item["chunk_index"], "clm", item["claims"])

    # -- merge sources into one revision-scoped src_001 ------------------
    first_source = normalized[0]["source"]
    titles = []
    for item in normalized:
        title = item["source"].get("title")
        if isinstance(title, str) and title and title not in titles:
            titles.append(title)
    merged_title = document.get("title") if isinstance(document.get("title"), str) and document.get("title") else titles[0] if titles else ""
    if not merged_title:
        raise PersistenceError("assembled source requires a title")
    merged_source = copy.deepcopy(first_source)
    merged_source["temp_id"] = "src_001"
    merged_source["title"] = merged_title
    for item in normalized:
        id_map[(item["chunk_index"], _identity(item["source"]))] = "src_001"

    # -- rewrite records through the mapping ------------------------------
    by_chunk_entity_name: dict[int, dict[str, str]] = {}
    staged_entities: list[tuple[int, dict[str, Any]]] = []
    staged_events: list[tuple[int, dict[str, Any]]] = []
    staged_claims: list[tuple[int, dict[str, Any]]] = []

    for item in normalized:
        chunk_index = item["chunk_index"]

        def _map(old: Any) -> Any:
            if isinstance(old, str) and (chunk_index, old) in id_map:
                return id_map[(chunk_index, old)]
            return old

        names: dict[str, str] = {}
        for entity in item["entities"]:
            record = copy.deepcopy(entity)
            record["temp_id"] = id_map[(chunk_index, _identity(entity))]
            # Keyed by revision-scoped ID: staged records below already
            # carry remapped references.
            names[record["temp_id"]] = str(entity.get("canonical_name") or "")
            staged_entities.append((chunk_index, record))
        by_chunk_entity_name[chunk_index] = names

        for event in item["events"]:
            record = copy.deepcopy(event)
            record["temp_id"] = id_map[(chunk_index, _identity(event))]
            participants = []
            for participant in record.get("participants") or []:
                if isinstance(participant, dict):
                    participant = dict(participant)
                    participant["entity_ref"] = _map(participant.get("entity_ref"))
                participants.append(participant)
            record["participants"] = participants
            record["places"] = [_map(ref) for ref in record.get("places") or []]
            if record.get("parent_event_ref") is not None:
                record["parent_event_ref"] = _map(record.get("parent_event_ref"))
            staged_events.append((chunk_index, record))

        for claim in item["claims"]:
            record = copy.deepcopy(claim)
            record["temp_id"] = id_map[(chunk_index, _identity(claim))]
            for field in ("subject", "object"):
                ref = record.get(field)
                if isinstance(ref, dict) and ref.get("kind") in ("entity_ref", "event_ref"):
                    ref = dict(ref)
                    ref["ref"] = _map(ref.get("ref"))
                    record[field] = ref
            evidence = dict(record.get("evidence") or {})
            evidence["source_ref"] = "src_001"
            record["evidence"] = evidence
            staged_claims.append((chunk_index, record))

    # -- suppress boundary-induced duplicate claims ------------------------
    # Event references are compared by occurrence signature (type, title,
    # time, participant/place surfaces), not by chunk-local ID, so a claim
    # pair stays comparable even when both chunks extracted the event.
    event_sig_by_new: dict[str, str] = {}
    for index, record in staged_events:
        names = by_chunk_entity_name[index]
        participants = sorted(
            names.get(p.get("entity_ref"), str(p.get("entity_ref")))
            for p in record.get("participants") or []
            if isinstance(p, dict)
        )
        places = sorted(names.get(ref, str(ref)) for ref in record.get("places") or [])
        event_sig_by_new[record["temp_id"]] = canonical_json_bytes(
            (
                record.get("type"),
                str(record.get("title") or "").strip(),
                _event_time_signature(record),
                tuple(participants),
                tuple(places),
            )
        ).decode("utf-8")

    def _claim_key(chunk_index: int, record: dict[str, Any]) -> tuple[Any, ...]:
        names = by_chunk_entity_name[chunk_index]
        evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
        time = record.get("time")
        time_key = canonical_json_bytes(time).decode("utf-8") if time is not None else None
        return (
            record.get("predicate"),
            evidence.get("text"),
            _claim_surface_key(record.get("subject"), names, event_sig_by_new),
            _claim_surface_key(record.get("object"), names, event_sig_by_new),
            time_key,
        )

    claim_keys = [(index, record, _claim_key(index, record)) for index, record in staged_claims]
    suppressed_claims: set[str] = set()
    suppressions: list[dict[str, Any]] = []
    preserved_repeats: list[dict[str, Any]] = []
    locator_by_chunk = {item["chunk_index"]: item["locator"] for item in normalized}

    def _preserve(kind: str, left: dict[str, Any], left_index: int,
                  right: dict[str, Any], right_index: int, reason: str) -> None:
        preserved_repeats.append(
            {
                "kind": kind,
                "left_ref": left["temp_id"],
                "left_chunk": left_index,
                "right_ref": right["temp_id"],
                "right_chunk": right_index,
                "reason": reason,
            }
        )

    for position in range(len(claim_keys)):
        left_index, left, left_key = claim_keys[position]
        if left["temp_id"] in suppressed_claims:
            continue
        for later in range(position + 1, len(claim_keys)):
            right_index, right, right_key = claim_keys[later]
            if right["temp_id"] in suppressed_claims or right_key != left_key:
                continue
            if right_index != left_index + 1:
                # Genuine repetition at a distance: keep both, record it.
                _preserve("claim", left, left_index, right, right_index,
                          "matching assertions in non-adjacent chunks")
                continue
            if not _spans_overlap(locator_by_chunk[left_index], locator_by_chunk[right_index]):
                # Adjacent chunks, identical assertion, but no verified
                # span overlap or boundary overlap: a genuine repeated
                # passage must survive as a distinct occurrence.
                _preserve("claim", left, left_index, right, right_index,
                          "no verified span overlap between adjacent chunks")
                continue
            # Same assertion extracted on both sides of one verified
            # overlapping chunk boundary: keep the first, suppress the
            # later duplicate.
            suppressed_claims.add(right["temp_id"])
            evidence = right.get("evidence") if isinstance(right.get("evidence"), dict) else {}
            suppressions.append(
                {
                    "kind": "claim",
                    "kept_ref": left["temp_id"],
                    "kept_chunk": left_index,
                    "suppressed_ref": right["temp_id"],
                    "suppressed_chunk": right_index,
                    "decision": "same_occurrence",
                    "confidence": CONFIDENCE_SAME_OCCURRENCE_DUPLICATE,
                    "signature": {
                        "predicate": right.get("predicate"),
                        "evidence_text": evidence.get("text"),
                    },
                }
            )

    # -- suppress boundary-induced duplicate events (rewire refs) -----------
    def _event_key(chunk_index: int, record: dict[str, Any]) -> str:
        return event_sig_by_new[record["temp_id"]]

    event_keys = [(index, record, _event_key(index, record)) for index, record in staged_events]
    suppressed_events: dict[str, str] = {}
    for position in range(len(event_keys)):
        left_index, left, left_key = event_keys[position]
        if left["temp_id"] in suppressed_events:
            continue
        for later in range(position + 1, len(event_keys)):
            right_index, right, right_key = event_keys[later]
            if right["temp_id"] in suppressed_events or right_key != left_key:
                continue
            if right_index != left_index + 1:
                _preserve("event", left, left_index, right, right_index,
                          "matching occurrences in non-adjacent chunks")
                continue
            if not _spans_overlap(locator_by_chunk[left_index], locator_by_chunk[right_index]):
                _preserve("event", left, left_index, right, right_index,
                          "no verified span overlap between adjacent chunks")
                continue
            suppressed_events[right["temp_id"]] = left["temp_id"]
            suppressions.append(
                {
                    "kind": "event",
                    "kept_ref": left["temp_id"],
                    "kept_chunk": left_index,
                    "suppressed_ref": right["temp_id"],
                    "suppressed_chunk": right_index,
                    "decision": "same_occurrence",
                    "confidence": CONFIDENCE_SAME_OCCURRENCE_DUPLICATE,
                    "signature": {
                        "type": right.get("type"),
                        "title": right.get("title"),
                    },
                }
            )
    suppressions.sort(key=lambda s: (s["suppressed_chunk"], s["suppressed_ref"]))
    preserved_repeats.sort(
        key=lambda r: (r["right_chunk"], r["right_ref"], r["left_ref"])
    )

    # Entity pairs proven to co-refer by a suppressed boundary duplicate:
    # when two claims were verified to be the same assertion, their
    # entity subjects/objects denote the same participant of the same
    # occurrence. This is the only suppression-derived identity signal;
    # a shared name alone never proves identity.
    claim_by_ref = {record["temp_id"]: record for _, record in staged_claims}
    proven_same: dict[frozenset, dict[str, str]] = {}

    def _entity_ref_of(claim: dict[str, Any] | None, field: str) -> str | None:
        if not isinstance(claim, dict):
            return None
        ref = claim.get(field)
        if isinstance(ref, dict) and ref.get("kind") == "entity_ref":
            identity = ref.get("ref")
            return identity if isinstance(identity, str) else None
        return None

    for suppression in suppressions:
        if suppression["kind"] != "claim":
            continue
        kept = claim_by_ref.get(suppression["kept_ref"])
        suppressed = claim_by_ref.get(suppression["suppressed_ref"])
        for field in ("subject", "object"):
            left_ref = _entity_ref_of(kept, field)
            right_ref = _entity_ref_of(suppressed, field)
            if left_ref and right_ref and left_ref != right_ref:
                proven_same[frozenset((left_ref, right_ref))] = {
                    "kept_ref": suppression["kept_ref"],
                    "suppressed_ref": suppression["suppressed_ref"],
                }

    def _rewire_event_ref(value: Any) -> Any:
        return suppressed_events.get(value, value) if isinstance(value, str) else value

    final_entities = [record for _, record in staged_entities]
    final_events = []
    for _, record in staged_events:
        if record["temp_id"] in suppressed_events:
            continue
        if record.get("parent_event_ref") is not None:
            record["parent_event_ref"] = _rewire_event_ref(record.get("parent_event_ref"))
        final_events.append(record)
    final_claims = []
    for _, record in staged_claims:
        if record["temp_id"] in suppressed_claims:
            continue
        for field in ("subject", "object"):
            ref = record.get(field)
            if isinstance(ref, dict) and ref.get("kind") == "event_ref":
                ref = dict(ref)
                ref["ref"] = _rewire_event_ref(ref.get("ref"))
                record[field] = ref
        final_claims.append(record)

    # -- provenance for every surviving record ------------------------------
    for item in normalized:
        chunk_index = item["chunk_index"]
        locator = item["locator"]
        for record in [item["source"], *item["entities"], *item["events"], *item["claims"]]:
            old = _identity(record)
            new = id_map[(chunk_index, old)]
            if new == "src_001":
                continue
            if new in suppressed_claims or new in suppressed_events:
                continue
            provenance[new] = {
                "chunk_index": chunk_index,
                "chunk_temp_id": old,
                "run_attempt": item["run_attempt"],
                "model_version": item["model_version"],
                "revision_id": locator["revision_id"],
                "revision_no": revision_no,
                "source_sha256": locator["source_sha256"],
                "content_sha256": locator["content_sha256"],
            }
    provenance["src_001"] = {
        "chunk_index": None,
        "chunk_temp_id": None,
        "run_attempt": None,
        "model_version": None,
        "revision_id": revision_id,
        "revision_no": revision_no,
        "source_sha256": source_sha256,
        "content_sha256": None,
        "merged_from_chunks": indexes,
    }

    # -- conservative within-book candidate linking --------------------------
    entity_index: dict[str, tuple[int, dict[str, Any]]] = {}
    for chunk_index, record in staged_entities:
        entity_index[record["temp_id"]] = (chunk_index, record)

    links: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_warnings: set[str] = set()

    def _warn(warning: dict[str, Any]) -> None:
        key = canonical_json_bytes(warning).decode("utf-8")
        if key not in seen_warnings:
            seen_warnings.add(key)
            warnings.append(warning)

    # Passthrough chunk warnings (deduplicated; refs remapped where possible).
    for item in normalized:
        chunk_index = item["chunk_index"]
        for warning in item["warnings"]:
            warning = copy.deepcopy(warning)
            refs = []
            for ref in warning.get("refs") or []:
                mapped = id_map.get((chunk_index, ref))
                if mapped is not None and mapped not in suppressed_claims and mapped not in suppressed_events:
                    refs.append(mapped)
            if refs or "refs" not in warning:
                if refs:
                    warning["refs"] = refs
                elif "refs" in warning:
                    del warning["refs"]
            elif "refs" in warning:
                del warning["refs"]
            _warn(warning)

    # Entity links across chunks: same type + shared stable surface.
    entity_refs = sorted(entity_index)
    for left_pos in range(len(entity_refs)):
        for right_pos in range(left_pos + 1, len(entity_refs)):
            left_ref, right_ref = entity_refs[left_pos], entity_refs[right_pos]
            left_chunk, left = entity_index[left_ref]
            right_chunk, right = entity_index[right_ref]
            if left_chunk == right_chunk:
                continue  # one chunk's own namespace is the extractor's business
            if left.get("type") != right.get("type"):
                left_name = str(left.get("canonical_name") or "")
                right_name = str(right.get("canonical_name") or "")
                if left_name and left_name == right_name:
                    _warn(
                        {
                            "type": "ambiguous_same_name",
                            "severity": "warning",
                            "message": (
                                f"Same surface {left_name!r} appears as "
                                f"{left.get('type')} ({left_ref}) and "
                                f"{right.get('type')} ({right_ref}); kept "
                                "distinct without evidence for identity."
                            ),
                            "refs": [left_ref, right_ref],
                        }
                    )
                continue
            shared = sorted(_stable_entity_surfaces(left) & _stable_entity_surfaces(right))
            if not shared:
                continue
            # A shared name alone never proves identity (C0 direction):
            # same-name records stay uncertain unless stronger
            # source-bounded evidence exists — either a second shared
            # stable surface beyond the name, or co-reference proven by
            # a suppressed boundary duplicate both records participated in.
            left_name = str(left.get("canonical_name") or "")
            same_name = bool(left_name) and left_name == str(right.get("canonical_name") or "")
            extra = sorted(s for s in shared if not (same_name and s == left_name))
            proof = proven_same.get(frozenset((left_ref, right_ref)))
            if same_name and (extra or proof is not None):
                if proof is not None:
                    rationale = (
                        f"Both records participate in one verified boundary-duplicate "
                        f"occurrence ({proof['kept_ref']} ~ {proof['suppressed_ref']}); "
                        f"shared canonical surface {left_name!r}."
                    )
                    signals = [
                        f"exact canonical surface: {left_name}",
                        f"co-subjects of duplicate occurrence {proof['kept_ref']}",
                    ]
                    confidence = CONFIDENCE_SAME_OCCURRENCE_DUPLICATE
                else:
                    rationale = (
                        f"Same entity type {left.get('type')!r} with exact canonical "
                        f"surface {left_name!r} plus a second shared stable surface "
                        f"({', '.join(extra)}) in one revision."
                    )
                    signals = [
                        f"same entity type: {left.get('type')}",
                        f"exact canonical surface: {left_name}",
                        "second shared stable surface: " + ", ".join(extra),
                    ]
                    confidence = CONFIDENCE_SAME_ENTITY_EXACT_NAME
                links.append(
                    {
                        "left": {"chunk_index": left_chunk, "ref": left_ref},
                        "right": {"chunk_index": right_chunk, "ref": right_ref},
                        "kind": "entity",
                        "decision": "same_entity",
                        "confidence": confidence,
                        "rationale": rationale,
                        "signals": signals,
                    }
                )
            else:
                links.append(
                    {
                        "left": {"chunk_index": left_chunk, "ref": left_ref},
                        "right": {"chunk_index": right_chunk, "ref": right_ref},
                        "kind": "entity",
                        "decision": "uncertain",
                        "confidence": CONFIDENCE_UNCERTAIN,
                        "rationale": (
                            "Shared stable surface without stronger identity evidence; "
                            "a shared name alone never proves identity, so the "
                            "records are kept distinct for review."
                        ),
                        "signals": ["shared stable surface: " + ", ".join(shared)],
                    }
                )

    # Event links across chunks: compatible time + participant/place overlap.
    name_of = {ref: str(rec.get("canonical_name") or "") for ref, (_, rec) in entity_index.items()}

    def _participants(record: dict[str, Any]) -> set[str]:
        result: set[str] = set()
        for participant in record.get("participants") or []:
            if isinstance(participant, dict):
                ref = participant.get("entity_ref")
                if isinstance(ref, str) and ref in name_of and name_of[ref]:
                    result.add(name_of[ref])
        return result

    def _places(record: dict[str, Any]) -> set[str]:
        result: set[str] = set()
        for ref in record.get("places") or []:
            if isinstance(ref, str):
                result.add(name_of.get(ref, ref))
        return result

    surviving_events = [record for record in final_events]
    for left_pos in range(len(surviving_events)):
        for right_pos in range(left_pos + 1, len(surviving_events)):
            left, right = surviving_events[left_pos], surviving_events[right_pos]
            left_chunk = provenance[left["temp_id"]]["chunk_index"]
            right_chunk = provenance[right["temp_id"]]["chunk_index"]
            if left_chunk == right_chunk:
                continue
            if not _time_compatible(left, right):
                continue
            participant_overlap = sorted(_participants(left) & _participants(right))
            if not participant_overlap:
                continue
            place_overlap = sorted(_places(left) & _places(right))
            same_type = left.get("type") == right.get("type") and isinstance(left.get("type"), str)
            narrow = same_type and left.get("type") in _LOW_AMBIGUITY_EVENT_TYPES
            anchored = (
                _event_type_compatible(left.get("type"), right.get("type"))
                and bool(place_overlap)
            )
            if not (narrow or anchored):
                continue
            signals = [f"compatible event types: {left.get('type')} / {right.get('type')}"]
            if narrow:
                signals.append(f"low-ambiguity same event type: {left.get('type')}")
            signals.append("shared participants: " + ", ".join(participant_overlap))
            if place_overlap:
                signals.append("shared places: " + ", ".join(place_overlap))
            links.append(
                {
                    "left": {"chunk_index": left_chunk, "ref": left["temp_id"]},
                    "right": {"chunk_index": right_chunk, "ref": right["temp_id"]},
                    "kind": "event",
                    "decision": "uncertain",
                    "confidence": CONFIDENCE_UNCERTAIN,
                    "rationale": (
                        "Cross-chunk occurrences share participants and "
                        "compatible time but the evidence is insufficient to "
                        "call them the same occurrence; kept distinct for review."
                    ),
                    "signals": signals,
                }
            )

    links.sort(key=lambda link: (link["left"]["ref"], link["right"]["ref"], link["kind"]))
    for position, link in enumerate(links, 1):
        link["candidate_id"] = f"wc_{position:03d}"
    for link in links:
        if link["decision"] == "uncertain":
            _warn(
                {
                    "type": "unresolved_within_book_identity",
                    "severity": "warning",
                    "message": (
                        f"Within-book {link['kind']} candidate {link['candidate_id']} "
                        f"({link['left']['ref']} ~ {link['right']['ref']}) remains "
                        "uncertain; records kept distinct."
                    ),
                    "refs": [link["left"]["ref"], link["right"]["ref"]],
                }
            )
    for suppression in suppressions:
        _warn(
            {
                "type": "duplicate_suppressed",
                "severity": "info",
                "message": (
                    f"Boundary duplicate {suppression['kind']} "
                    f"{suppression['suppressed_ref']} (chunk "
                    f"{suppression['suppressed_chunk']}) suppressed into "
                    f"{suppression['kept_ref']} (chunk {suppression['kept_chunk']})."
                ),
                "refs": [suppression["kept_ref"]],
            }
        )
    for repeat in preserved_repeats:
        if repeat["right_chunk"] != repeat["left_chunk"] + 1:
            continue
        _warn(
            {
                "type": "repeated_assertion_preserved",
                "severity": "info",
                "message": (
                    f"Matching {repeat['kind']} {repeat['left_ref']} (chunk "
                    f"{repeat['left_chunk']}) and {repeat['right_ref']} (chunk "
                    f"{repeat['right_chunk']}) preserved as distinct: "
                    f"{repeat['reason']}."
                ),
                "refs": [repeat["left_ref"], repeat["right_ref"]],
            }
        )

    warnings.sort(
        key=lambda w: (
            str(w.get("type") or ""),
            str(w.get("message") or ""),
            canonical_json_bytes(w.get("refs") or []).decode("utf-8"),
        )
    )

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "source": merged_source,
        "entities": final_entities,
        "events": final_events,
        "claims": final_claims,
        "warnings": warnings,
    }
    validate_assembled_bundle(bundle)

    within_book_links = {
        "schema": LINKS_SCHEMA,
        "version": LINKS_VERSION,
        "assembly_version": ASSEMBLY_VERSION,
        "contract_version": CONTRACT_VERSION,
        "revision_id": revision_id,
        "source_sha256": source_sha256,
        "entity_links": [link for link in links if link["kind"] == "entity"],
        "event_links": [link for link in links if link["kind"] == "event"],
        "authoritative": False,
        "authority_note": NON_AUTHORITATIVE_NOTE,
    }

    counts_in = {
        "chunks": len(normalized),
        "entities": sum(len(item["entities"]) for item in normalized),
        "events": sum(len(item["events"]) for item in normalized),
        "claims": sum(len(item["claims"]) for item in normalized),
    }
    report = {
        "schema": REPORT_SCHEMA,
        "version": REPORT_VERSION,
        "assembly_version": ASSEMBLY_VERSION,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "revision": {
            "revision_id": revision_id,
            "revision_no": revision_no,
            "source_sha256": source_sha256,
        },
        "inputs": [
            {
                "chunk_index": item["chunk_index"],
                "run_attempt": item["run_attempt"],
                "model_version": item["model_version"],
                "content_sha256": item["locator"]["content_sha256"],
                "locator": copy.deepcopy(item["locator"]),
                "counts": {
                    "entities": len(item["entities"]),
                    "events": len(item["events"]),
                    "claims": len(item["claims"]),
                    "warnings": len(item["warnings"]),
                },
            }
            for item in normalized
        ],
        "counts": {
            "in": counts_in,
            "out": {
                "entities": len(final_entities),
                "events": len(final_events),
                "claims": len(final_claims),
                "warnings": len(warnings),
            },
            "suppressed_claims": sum(1 for s in suppressions if s["kind"] == "claim"),
            "suppressed_events": sum(1 for s in suppressions if s["kind"] == "event"),
            "preserved_repeats": len(preserved_repeats),
            "entity_links": sum(1 for link in links if link["kind"] == "entity"),
            "event_links": sum(1 for link in links if link["kind"] == "event"),
            "unresolved_links": sum(1 for link in links if link["decision"] == "uncertain"),
        },
        "duplicate_suppressions": suppressions,
        "preserved_repeats": preserved_repeats,
        "unresolved_links": [link["candidate_id"] for link in links if link["decision"] == "uncertain"],
        "record_provenance": provenance,
        "merged_source_titles": titles,
        "bundle_sha256": sha256_json(bundle),
        "links_sha256": sha256_json(within_book_links),
        "authoritative": False,
        "authority_note": NON_AUTHORITATIVE_NOTE,
    }

    return {
        "bundle": bundle,
        "within_book_links": within_book_links,
        "report": report,
    }


def artifact_canonical_bytes(artifact: dict[str, Any]) -> bytes:
    """Canonical bytes for hashing/persistence of the assembly artifact."""
    if not isinstance(artifact, dict):
        raise PersistenceError("assembly artifact must be a JSON object")
    return canonical_json_bytes(artifact)


def validate_assembled_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate the assembled bundle against the canonical C0 schema.

    Returns a deterministic report (fail closed: schema violations raise
    :class:`PersistenceError` instead of returning a soft report).
    """
    if canonical_schema is None:  # pragma: no cover - import fallback
        raise PersistenceError("canonical Chronicle schema is unavailable")
    if not isinstance(bundle, dict):
        raise PersistenceError("assembled bundle must be a JSON object")
    schema = canonical_schema()
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    found = sorted(validator.iter_errors(bundle), key=lambda e: list(e.absolute_path))
    errors = []
    for error in found:
        where = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{where}: {error.message}")
    if errors:
        raise PersistenceError(
            "assembled bundle failed the canonical C0 schema: " + "; ".join(errors)
        )
    return {
        "schema": "chronicle.source-assembly-validation",
        "version": "0.1",
        "assembly_version": ASSEMBLY_VERSION,
        "contract_version": CONTRACT_VERSION,
        "passed": True,
        "count": 0,
        "errors": [],
    }
