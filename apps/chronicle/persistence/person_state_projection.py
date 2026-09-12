"""Chronicle C2-R3-T04 person-state projection compiler.

This is the T04-owned, pre-publication pure compiler described by
``apps/chronicle/docs/person-state-reading.md`` sections 2-4 and the
C2-R3-T04 task note. It turns the C2-R3-T03 assembled and remapped
``person_states`` evidence plus the reviewed assessment overlay into the
single operational rule set shared by publication, the read API and the
review preview:

- :func:`compile_person_state_projection` derives the effective phases of
  ``office`` / ``title`` / ``affiliation`` facts and the two-tier
  ``clear | uncertain`` certainty from *reviewed* assessments only. It
  never lets model confidence, wall-clock time or the latest catalog
  change an answer, never leaks a future title into the current
  identity, and never turns a recommendation / posthumous / self-styled
  attest into a current office.
- :func:`compile_person_state_disagreements` compiles a bounded,
  immutable cross-source disagreement index for one catalog, keeping both
  sides' evidence and adding only recorded reasons.

Both functions are pure: no database, network, model, UUID allocation or
system time. Identical inputs produce byte-identical canonical JSON and
the same ``projection_sha256``; every array has a fixed sort order.

Contractual inputs
------------------

``evidence`` is the assembled and remapped person-state namespace (the
``person_states`` block returned by
:func:`person_state_assembly.assemble_person_state_evidence`, accepted
either directly or wrapped under ``person_states``). Facts may carry the
flat projection provenance produced by the T03 remap
(``chapter_id`` / ``revision_id`` / ``chapter_publication_id`` /
``anchor_ids``) or an ``origin`` block with the same fields.

``assessments`` maps a program-owned reference (``fact_ref``,
``assertion_id``) to one of ``supported | uncertain | disputed |
rejected``. An unassessed fact is treated as ``uncertain``; a phase
precedence edge or continuity that is not explicitly ``supported`` is
not used, so unproven order cannot become a current identity.

``canonical_map`` resolves a local ``person_ref`` / ``value_ref`` /
``target_ref`` to a canonical id. Missing person mappings fail closed
(diagnostic ``unknown_person``). An optional ``labels`` sub-map (or
``reading_manifest["entity_labels"]``) supplies display labels for values
whose local reference has already been resolved.

``reading_manifest`` selects the unit phase context: ``current_phase_id``
(or ``phase_id``) plus an optional ``unit_phase`` binding carrying
``mode`` and ``phase_ids``. ``single`` keeps one phase, ``process`` shows
every phase in the span, ``ambiguous`` returns the material without
asserting a unity, and ``unknown`` never carries a previous phase
forward.
"""

from __future__ import annotations

from typing import Any

import person_state_contract as _contract
from common import PersistenceError, canonical_json_bytes, sha256_json

#: Projection schema marker (not a model-generatable document).
PROJECTION_SCHEMA = "chronicle.person-state-projection"

#: Compiler version; it enters the projection fingerprint and the
#: published person-state manifest (see ``person-state-reading.md`` §4).
PROJECTION_VERSION = "c2r3-person-state-projection-v1"

_PLACE_DIMENSIONS = tuple(_contract.PLACE_DIMENSIONS)
_OPERATIONS = tuple(_contract.OPERATIONS)
_QUALIFICATIONS = tuple(_contract.QUALIFICATIONS)
_ATTRIBUTIONS = tuple(_contract.ATTRIBUTIONS)
_ASSESSMENTS = tuple(_contract.ASSESSMENTS)
_REASON_CODES = tuple(_contract.REASON_CODES)
_PHASE_MODES = tuple(_contract.PHASE_MODES)
_UNLIMITED_QUALIFICATIONS = tuple(_contract.UNLIMITED_QUALIFICATIONS)

#: Qualifications that never establish a current office (they only attest
#: to a limited, source-attributed record; see §2 and §3.2).
_NEVER_CURRENT_QUALIFICATIONS = _UNLIMITED_QUALIFICATIONS + ("self_designation",)

#: Attributions whose claim is reported rather than narrated, so it never
#: becomes the current identity without an independent source.
_NEVER_CURRENT_ATTRIBUTIONS = ("quotation", "hearsay")


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _ref_str(value: Any) -> str | None:
    """Return the local reference from a typed ref or plain string."""
    if isinstance(value, dict):
        ref = value.get("ref")
        return ref if isinstance(ref, str) and ref else None
    if isinstance(value, str) and value:
        return value
    return None


def _fact_ref(fact: dict[str, Any]) -> str | None:
    """Return a fact's program-owned ref (``fact_ref`` or assembled ``fact_id``)."""
    for key in ("fact_ref", "fact_id"):
        value = fact.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _person_local(fact: dict[str, Any]) -> str | None:
    return (
        _ref_str(fact.get("person_ref"))
        or (fact.get("person_key") if isinstance(fact.get("person_key"), str) else None)
    )


def _resolve_person(fact: dict[str, Any], canonical_map: dict[str, Any]) -> tuple[str | None, str | None]:
    local = _person_local(fact)
    if local is None:
        return None, None
    mapped = canonical_map.get(local)
    if isinstance(mapped, str) and mapped:
        return local, mapped
    return local, None


def _canonical_id(ref: Any, canonical_map: dict[str, Any]) -> str | None:
    local = _ref_str(ref)
    if local is None:
        return None
    mapped = canonical_map.get(local)
    if isinstance(mapped, str) and mapped:
        return mapped
    return None


def _entity_labels(canonical_map: dict[str, Any], reading_manifest: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    embedded = canonical_map.get("labels") if isinstance(canonical_map, dict) else None
    if isinstance(embedded, dict):
        labels.update({k: v for k, v in embedded.items() if isinstance(k, str) and isinstance(v, str)})
    manifest_labels = reading_manifest.get("entity_labels")
    if isinstance(manifest_labels, dict):
        labels.update(
            {k: v for k, v in manifest_labels.items() if isinstance(k, str) and isinstance(v, str)}
        )
    return labels


def _display(ref: Any, labels: dict[str, str], fallback: Any) -> str | None:
    if not labels:
        return fallback if isinstance(fallback, str) else None
    local = _ref_str(ref)
    if local is None:
        return fallback if isinstance(fallback, str) else None
    label = labels.get(local)
    if isinstance(label, str) and label:
        return label
    return fallback if isinstance(fallback, str) else local


def _assessment_for(assessments: Any, ref: str) -> str:
    """Return the reviewed assessment for a fact (default uncertain)."""
    if not isinstance(assessments, dict):
        return "uncertain"
    value = assessments.get(ref)
    if value is None:
        return "uncertain"
    if value not in _ASSESSMENTS:
        raise PersistenceError(f"unknown assessment {value!r} for {ref!r}")
    return value


def _assertion_assessment(assessments: Any, ref: Any) -> str:
    """Return the reviewed assessment for an order/continuity assertion.

    An assertion without a reviewed assessment is not proven (not
    ``supported``); nothing is inferred merely because a model emitted it.
    """
    if not isinstance(ref, str) or not ref:
        return "uncertain"
    if not isinstance(assessments, dict):
        return "uncertain"
    value = assessments.get(ref)
    if value is None:
        return "uncertain"
    if value not in _ASSESSMENTS:
        raise PersistenceError(f"unknown assessment {value!r} for {ref!r}")
    return value


def _origin(fact: dict[str, Any]) -> dict[str, Any]:
    origin = fact.get("origin") if isinstance(fact.get("origin"), dict) else {}
    chapter_id = fact.get("chapter_id") or origin.get("chapter_id")
    revision_id = fact.get("revision_id") or origin.get("origin_revision_id")
    publication_id = fact.get("chapter_publication_id") or origin.get("chapter_publication_id")
    anchors = fact.get("anchor_ids")
    if not isinstance(anchors, list):
        anchors = origin.get("anchor_ids")
    return {
        "chapter_id": chapter_id if isinstance(chapter_id, str) else None,
        "revision_id": revision_id if isinstance(revision_id, str) else None,
        "chapter_publication_id": publication_id if isinstance(publication_id, str) else None,
        "anchor_ids": [a for a in (anchors or []) if isinstance(a, str)],
    }


# ---------------------------------------------------------------------------
# Phase order (a strict partial order, never a body-order guess)
# ---------------------------------------------------------------------------


def _proven_edges(
    phase_orders: list[dict[str, Any]], assessments: Any
) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for order in phase_orders:
        earlier = order.get("earlier_phase_ref")
        later = order.get("later_phase_ref")
        if not isinstance(earlier, str) or not isinstance(later, str) or earlier == later:
            continue
        if _assertion_assessment(assessments, order.get("assertion_id")) != "supported":
            continue
        edges.append((earlier, later))
    return edges


def _descendants(phase_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, set[str]]:
    known = set(phase_ids)
    adj: dict[str, set[str]] = {phase_id: set() for phase_id in phase_ids}
    for earlier, later in edges:
        if earlier in known and later in known:
            adj[earlier].add(later)
    descendants: dict[str, set[str]] = {}
    for phase_id in phase_ids:
        seen: set[str] = set()
        stack = list(adj[phase_id])
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(adj[node])
        descendants[phase_id] = seen
    for phase_id in phase_ids:
        if phase_id in descendants[phase_id]:
            raise PersistenceError(
                f"phase precedence forms a cycle at {phase_id!r} (fail closed)"
            )
    return descendants


def _relation_to_current(
    phase: str | None,
    current_phases: set[str],
    descendants: dict[str, set[str]],
    mode: str,
) -> str:
    if mode == "unknown" or not current_phases:
        return "unknown"
    if phase is None:
        return "unknown"
    if phase in current_phases:
        return "ambiguous" if mode == "ambiguous" else "eq"
    before = any(current in descendants.get(phase, set()) for current in current_phases)
    after = any(phase in descendants.get(current, set()) for current in current_phases)
    if before and not after:
        return "before"
    if after and not before:
        return "after"
    return "unknown"


def _continuity_covers(
    continuity: dict[str, Any], current_phases: set[str], descendants: dict[str, set[str]]
) -> bool:
    start = continuity.get("start_phase_ref")
    end = continuity.get("end_phase_ref")
    if not isinstance(start, str):
        return False
    for current in current_phases:
        if current != start and current not in descendants.get(start, set()):
            continue
        if end is None:
            return True
        if isinstance(end, str) and current != end and end in descendants.get(current, set()):
            return True
    return False


def _current_context(reading_manifest: dict[str, Any]) -> tuple[str, set[str], str | None]:
    mode = "single"
    phase_ids: list[str] = []
    unit_phase = reading_manifest.get("unit_phase")
    binding: dict[str, Any] | None = None
    if isinstance(unit_phase, dict):
        if "mode" in unit_phase or "phase_ids" in unit_phase:
            binding = unit_phase
        else:
            unit_id = reading_manifest.get("unit_id")
            candidate = unit_phase.get(unit_id) if isinstance(unit_id, str) else None
            if isinstance(candidate, dict):
                binding = candidate
            elif len(unit_phase) == 1:
                only = next(iter(unit_phase.values()))
                if isinstance(only, dict):
                    binding = only
    if isinstance(binding, dict):
        candidate_mode = binding.get("mode")
        if candidate_mode in _PHASE_MODES:
            mode = candidate_mode
        phase_ids = [p for p in binding.get("phase_ids") or [] if isinstance(p, str)]
    current = reading_manifest.get("current_phase_id") or reading_manifest.get("phase_id")
    if not phase_ids and isinstance(current, str):
        phase_ids = [current]
    if not isinstance(current, str):
        current = phase_ids[0] if phase_ids else None
    if mode == "unknown":
        phase_ids = []
        current = None
    return mode, set(phase_ids), current


# ---------------------------------------------------------------------------
# State keys and record projection
# ---------------------------------------------------------------------------


def _state_key(fact: dict[str, Any], canonical_map: dict[str, Any], labels: dict[str, str]) -> tuple[str, ...]:
    """The program-owned state key from §3.2.

    The key is ``person / dimension / value-or-object id / relation /
    necessary qualification``. Display names, seniority and assumptions
    about concurrent office never participate, so a new appointment can
    never overwrite an unrelated one.
    """
    person, person_id = _resolve_person(fact, canonical_map)
    dimension = fact.get("dimension")
    relation = fact.get("relation")
    if dimension == "affiliation":
        target = _ref_str(fact.get("target_ref")) or _ref_str(fact.get("target"))
        value = ""
    else:
        value = _ref_str(fact.get("value_ref")) or _display(
            fact.get("value_ref"), labels, fact.get("value")
        )
        value = value or ""
        target = ""
    qualification = fact.get("qualification")
    if qualification not in _QUALIFICATIONS:
        qualification = "ordinary"
    return (
        str(person_id or person or ""),
        str(dimension or ""),
        str(value),
        str(relation or ""),
        str(target or ""),
        str(qualification),
    )


def _core_key(key: tuple[str, ...]) -> tuple[str, ...]:
    """The key fields an ``end`` must match to close a record.

    Qualification is intentionally excluded from the *closing* match so an
    ordinary grant can be closed by an ordinary end, while a reported /
    self-styled end is handled separately and never silently closes a
    narrated tenure (see §3.2).
    """
    return key[:5]


def _source_fact(fact: dict[str, Any], fact_ref: str, phase: str | None) -> dict[str, Any]:
    origin = _origin(fact)
    return {
        "chapter_publication_id": origin["chapter_publication_id"],
        "chapter_id": origin["chapter_id"],
        "revision_id": origin["revision_id"],
        "fact_ref": fact_ref,
        "claim_refs": [r for r in (_ref_str(c) for c in fact.get("claim_refs") or []) if r],
        "phase_id": phase,
        "anchor_ids": origin["anchor_ids"],
    }


def _change_record(
    fact: dict[str, Any],
    fact_ref: str,
    person_id: str,
    person_local: str | None,
    phase: str | None,
    from_phase: str | None,
    certainty: str,
    reasons: list[str],
) -> dict[str, Any]:
    origin = _origin(fact)
    return {
        "item_id": _contract.item_id_for(
            chapter_id=str(origin["chapter_id"] or ""),
            fact_ref=fact_ref,
            dimension=str(fact.get("dimension")),
            phase_id=str(phase or ""),
            person_ref=str(person_local or person_id),
            operation=str(fact.get("operation")),
        ),
        "person_id": person_id,
        "dimension": fact.get("dimension"),
        "value": fact.get("value"),
        "relation": fact.get("relation"),
        "target": fact.get("target"),
        "operation": fact.get("operation"),
        "qualification": fact.get("qualification"),
        "from_phase_id": from_phase,
        "to_phase_id": phase,
        "certainty": certainty,
        "reason_codes": sorted(set(reasons)),
        "reason_text": _contract._reason_text(sorted(set(reasons))),
        "source_facts": [_source_fact(fact, fact_ref, phase)],
    }


def _item_certainty(reasons: list[str]) -> str:
    return "uncertain" if reasons else "clear"


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def _normalize_evidence(evidence: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    nested = evidence.get("person_states")
    source = nested if isinstance(nested, dict) else evidence
    return {
        "phases": _objects(source.get("phases")),
        "phase_orders": _objects(source.get("phase_orders")),
        "unit_phases": _objects(source.get("unit_phases")),
        "facts": _objects(source.get("facts")),
        "continuities": _objects(source.get("continuities")),
        "disagreements": _objects(source.get("disagreements")),
    }


def compile_person_state_projection(
    evidence: dict[str, Any],
    assessments: dict[str, Any],
    canonical_map: dict[str, Any],
    reading_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compile the immutable person-state projection from assessed evidence.

    Only reviewed facts participate. ``certainty`` is ``clear`` only when a
    ``supported`` fact's phase is the current phase (or inside a proven
    continuity / proven tenure span) with no applicable disagreement;
    anything else is ``uncertain`` with stable reason codes. Facts in a
    phase proven later than the current phase (``phase_not_reached``),
    explicitly rejected facts and recommendation / posthumous / self-styled
    attestations never enter the current identity. Pure: no DB, network,
    model, UUID or system time.
    """
    if not isinstance(evidence, dict):
        raise PersistenceError("evidence must be a JSON object")
    if not isinstance(assessments, dict):
        raise PersistenceError("assessments must be a JSON object")
    if not isinstance(canonical_map, dict):
        raise PersistenceError("canonical_map must be a JSON object")
    if not isinstance(reading_manifest, dict):
        raise PersistenceError("reading_manifest must be a JSON object")

    limits = _contract.PersonStateLimits()
    parts = _normalize_evidence(evidence)
    phases = parts["phases"]
    phase_orders = parts["phase_orders"]
    facts = parts["facts"]
    continuities = parts["continuities"]
    disagreements = parts["disagreements"]

    assertions = len(phase_orders) + len(continuities) + len(disagreements)
    if len(phases) > limits.max_phases:
        raise PersistenceError(f"person-state projection exceeds max_phases {limits.max_phases}")
    if len(facts) > limits.max_facts:
        raise PersistenceError(f"person-state projection exceeds max_facts {limits.max_facts}")
    if assertions > limits.max_assertions:
        raise PersistenceError(
            f"person-state projection exceeds max_assertions {limits.max_assertions}"
        )

    labels = _entity_labels(canonical_map, reading_manifest)

    phase_ids = sorted(
        {p["phase_id"] for p in phases if isinstance(p.get("phase_id"), str)}
    )
    # Display ordinals follow only proven precedence; ties keep the
    # deterministic topological position (never a caller's dict order).
    ordered, cycle_errors = _contract.phase_topological_order(
        [{"phase_id": pid} for pid in phase_ids],
        [
            {"assertion_id": str(i), "earlier_phase_ref": e, "later_phase_ref": l}
            for i, (e, l) in enumerate(_proven_edges(phase_orders, assessments))
            if e in set(phase_ids) and l in set(phase_ids)
        ],
    )
    if cycle_errors:
        raise PersistenceError("person-state phase order is invalid: " + "; ".join(cycle_errors))
    ordinals = {phase_id: index for index, phase_id in enumerate(ordered)}

    descendants = _descendants(phase_ids, _proven_edges(phase_orders, assessments))

    mode, current_phases, current_phase_id = _current_context(reading_manifest)
    disputed_facts: set[str] = set()
    for disagreement in disagreements:
        for ref in disagreement.get("fact_refs") or []:
            if isinstance(ref, str):
                disputed_facts.add(ref)

    supported_continuities = [
        c
        for c in continuities
        if _assertion_assessment(assessments, c.get("assertion_id")) == "supported"
    ]

    diagnostics: list[dict[str, Any]] = []

    def diagnostic(fact_ref: str, code: str, person_id: str | None) -> None:
        diagnostics.append({"fact_ref": fact_ref, "code": code, "person_id": person_id})

    ordered_facts = sorted(
        (f for f in facts if _fact_ref(f) is not None),
        key=lambda f: (
            ordinals.get(f.get("phase_ref"), 1 << 30),
            str(_fact_ref(f)),
        ),
    )

    # -- pass 1: project every non-end fact into a record -------------------
    records: list[dict[str, Any]] = []
    end_facts: list[dict[str, Any]] = []
    for fact in ordered_facts:
        fact_ref = _fact_ref(fact) or ""
        person_local, person_id = _resolve_person(fact, canonical_map)
        if person_id is None:
            diagnostic(fact_ref, "unknown_person", None)
            continue
        phase = fact.get("phase_ref") if isinstance(fact.get("phase_ref"), str) else None
        if phase is None or phase not in set(phase_ids):
            diagnostic(fact_ref, "unknown_phase", person_id)
            continue
        assessment = _assessment_for(assessments, fact_ref)
        if assessment == "rejected":
            diagnostic(fact_ref, "rejected", person_id)
            continue
        operation = fact.get("operation")
        if operation not in _OPERATIONS:
            diagnostic(fact_ref, "invalid_operation", person_id)
            continue
        if operation == "end":
            end_facts.append(
                {
                    "fact": fact,
                    "fact_ref": fact_ref,
                    "person_id": person_id,
                    "person_local": person_local,
                    "phase": phase,
                    "assessment": assessment,
                    "key": _state_key(fact, canonical_map, labels),
                }
            )
            continue
        position = _relation_to_current(phase, current_phases, descendants, mode)
        if position == "after":
            diagnostic(fact_ref, "phase_not_reached", person_id)
            continue
        records.append(
            {
                "fact": fact,
                "fact_ref": fact_ref,
                "person_id": person_id,
                "person_local": person_local,
                "phase": phase,
                "assessment": assessment,
                "key": _state_key(fact, canonical_map, labels),
                "position": position,
                "ended": False,
                "ended_phase": None,
                "covered_by_end": False,
            }
        )

    # -- pass 2: let only a proven, narrated end close an earlier record ----
    end_records: list[dict[str, Any]] = []
    for end in sorted(end_facts, key=lambda e: (ordinals.get(e["phase"], 1 << 30), e["fact_ref"])):
        assessment = end["assessment"]
        fact = end["fact"]
        qualification = fact.get("qualification")
        attribution = fact.get("attribution")
        closes = (
            assessment == "supported"
            and qualification in (None, "ordinary")
            and attribution not in _NEVER_CURRENT_ATTRIBUTIONS
        )
        from_phase: str | None = None
        if closes:
            core = _core_key(end["key"])
            matched: list[dict[str, Any]] = []
            for record in records:
                if record["ended"]:
                    continue
                if record["person_id"] != end["person_id"]:
                    continue
                if _core_key(record["key"]) != core:
                    continue
                if end["phase"] != record["phase"] and end["phase"] not in descendants.get(
                    record["phase"], set()
                ):
                    # The end is not proven after this record.
                    continue
                matched.append(record)
            matched.sort(key=lambda r: (ordinals.get(r["phase"], 1 << 30), r["fact_ref"]))
            for record in matched:
                record["ended"] = True
                record["ended_phase"] = end["phase"]
            if matched:
                last = matched[-1]
                from_phase = last["phase"]
                if _relation_to_current(end["phase"], current_phases, descendants, mode) in (
                    "eq",
                    "before",
                    "ambiguous",
                ) or (mode == "unknown" and not current_phases):
                    for record in matched:
                        record["record_ended_before_current"] = True
                else:
                    # The proven end lies after the current phase, so the
                    # tenure is shown as spanning the current phase.
                    for record in matched:
                        record["covered_by_end"] = True
        reasons = _end_reasons(assessment, qualification, attribution)
        end_records.append(
            _change_record(
                fact,
                end["fact_ref"],
                end["person_id"],
                end["person_local"],
                end["phase"],
                from_phase,
                _item_certainty(reasons),
                reasons,
            )
        )

    # -- pass 3: emit fresh records as items -------------------------------
    items: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = list(end_records)
    people_items: dict[str, list[dict[str, Any]]] = {}

    for record in records:
        fact = record["fact"]
        fact_ref = record["fact_ref"]
        phase = record["phase"]
        assessment = record["assessment"]
        qualification = fact.get("qualification") if fact.get("qualification") in _QUALIFICATIONS else "ordinary"
        attribution = fact.get("attribution") if fact.get("attribution") in _ATTRIBUTIONS else "narrator"
        position = record["position"]

        reasons: list[str] = []
        if record.get("record_ended_before_current"):
            # A proven end before the current phase removes the fact from
            # the current identity but leaves it a clear historical record.
            current = False
        else:
            current = False
            if assessment == "supported":
                if position == "eq":
                    current = True
                elif position == "before":
                    if _continuity_covers_records(
                        fact_ref, current_phases, descendants, supported_continuities
                    ):
                        current = True
                    elif record.get("covered_by_end"):
                        current = True
                    else:
                        reasons.append("tenure_unproven")
            if position == "unknown" or position == "ambiguous":
                reasons.append("order_unknown")

        if assessment == "disputed":
            reasons.append("source_disagreement")
        elif assessment == "uncertain":
            reasons.append("evidence_uncertain")
        if fact_ref in disputed_facts and "source_disagreement" not in reasons:
            reasons.append("source_disagreement")
        if qualification in _NEVER_CURRENT_QUALIFICATIONS:
            reasons.append("attribution_uncertain")
        if attribution in ("quotation", "annotation", "hearsay") and "attribution_uncertain" not in reasons:
            reasons.append("attribution_uncertain")

        never_current = (
            qualification in _NEVER_CURRENT_QUALIFICATIONS
            or attribution in _NEVER_CURRENT_ATTRIBUTIONS
        )
        if never_current:
            current = False

        reasons = sorted(set(reasons))
        certainty = _item_certainty(reasons)
        origin = _origin(fact)
        source_facts = [_source_fact(fact, fact_ref, phase)]
        value = fact.get("value")
        if not isinstance(value, str) or not value:
            value = _display(fact.get("value_ref"), labels, None)
        target = fact.get("target")
        if not isinstance(target, str) or not target:
            target = _display(fact.get("target_ref") or fact.get("target"), labels, None)

        item = {
            "item_id": _contract.item_id_for(
                chapter_id=str(origin["chapter_id"] or ""),
                fact_ref=fact_ref,
                dimension=str(fact.get("dimension")),
                phase_id=str(phase),
                person_ref=str(record["person_local"] or record["person_id"]),
                operation=str(fact.get("operation")),
            ),
            "person_id": record["person_id"],
            "person_ref": record["person_local"],
            "dimension": fact.get("dimension"),
            "value": value,
            "value_id": _canonical_id(fact.get("value_ref"), canonical_map),
            "relation": fact.get("relation"),
            "target": target,
            "target_id": _canonical_id(fact.get("target_ref"), canonical_map),
            "operation": fact.get("operation"),
            "qualification": qualification,
            "attribution": attribution,
            "certainty": certainty,
            "reason_codes": reasons,
            "reason_text": _contract._reason_text(reasons),
            "phase_ids": [phase],
            "phase_id": phase,
            "current": current,
            "ended": bool(record.get("ended")),
            "source_facts": source_facts,
            "evidence_count": len(origin["anchor_ids"])
            or len(source_facts[0]["claim_refs"])
            or 1,
        }
        items.append(item)
        people_items.setdefault(record["person_id"], []).append(item)
        if fact.get("operation") == "start":
            changes.append(
                _change_record(
                    fact,
                    fact_ref,
                    record["person_id"],
                    record["person_local"],
                    phase,
                    record.get("from_phase"),
                    certainty,
                    reasons,
                )
            )

    people_changes: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        people_changes.setdefault(change["person_id"], []).append(change)

    # -- places (administration / control) keep the same certainty rules ---
    place_items: list[dict[str, Any]] = []
    for fact in ordered_facts:
        fact_ref = _fact_ref(fact) or ""
        dimension = fact.get("dimension")
        if dimension not in _PLACE_DIMENSIONS:
            continue
        phase = fact.get("phase_ref") if isinstance(fact.get("phase_ref"), str) else None
        if phase is None or phase not in set(phase_ids):
            continue
        assessment = _assessment_for(assessments, fact_ref)
        if assessment == "rejected":
            continue
        position = _relation_to_current(phase, current_phases, descendants, mode)
        if position == "after":
            continue
        reasons = []
        current = assessment == "supported" and position == "eq"
        if assessment == "disputed":
            reasons.append("source_disagreement")
        elif assessment == "uncertain":
            reasons.append("evidence_uncertain")
        if position in ("unknown", "ambiguous"):
            reasons.append("order_unknown")
        reasons = sorted(set(reasons))
        origin = _origin(fact)
        place_items.append(
            {
                "item_id": _contract.item_id_for(
                    chapter_id=str(origin["chapter_id"] or ""),
                    fact_ref=fact_ref,
                    dimension=str(dimension),
                    phase_id=str(phase),
                    person_ref=str(_ref_str(fact.get("person_ref")) or ""),
                    operation=str(fact.get("operation")),
                ),
                "place_ref": _ref_str(fact.get("person_ref")) or fact.get("person_ref"),
                "dimension": dimension,
                "value": fact.get("value") or _display(fact.get("value_ref"), labels, None),
                "certainty": _item_certainty(reasons),
                "reason_codes": reasons,
                "reason_text": _contract._reason_text(reasons),
                "phase_ids": [phase],
                "current": current,
                "source_facts": [_source_fact(fact, fact_ref, phase)],
            }
        )
    place_items.sort(key=lambda entry: entry["item_id"])

    # -- per-person summaries ---------------------------------------------
    compiled_people: dict[str, dict[str, Any]] = {}
    for person_id in sorted(set(people_items) | set(people_changes)):
        person_states = sorted(
            people_items.get(person_id, []),
            key=lambda entry: (str(entry["dimension"]), entry["item_id"]),
        )
        person_changes = sorted(
            people_changes.get(person_id, []), key=lambda entry: entry["item_id"]
        )
        codes = sorted({code for entry in person_states + person_changes for code in entry["reason_codes"]})
        current_items = [entry for entry in person_states if entry["current"]]
        compiled_people[person_id] = {
            "person_id": person_id,
            "phase_mode": mode,
            "certainty": "uncertain" if any(
                entry["certainty"] == "uncertain" for entry in person_states + person_changes
            ) else "clear",
            "reason_codes": codes,
            "items": [entry["item_id"] for entry in person_states],
            "item_ids": [entry["item_id"] for entry in person_states],
            "states": person_states,
            "changes": person_changes,
            "current_item_ids": [entry["item_id"] for entry in current_items],
        }

    units: dict[str, dict[str, Any]] = {}
    for binding in parts["unit_phases"]:
        block_id = binding.get("block_id")
        if not isinstance(block_id, str):
            continue
        binding_phases = {p for p in binding.get("phase_refs") or [] if isinstance(p, str)}
        units[block_id] = {
            "phase_mode": binding.get("mode"),
            "phase_ids": sorted(binding_phases),
            "people": [
                entry["item_id"]
                for entry in items
                if entry["phase_id"] in binding_phases
            ],
        }

    diagnostics.sort(key=lambda entry: (entry["code"], entry["fact_ref"], str(entry["person_id"])))

    result: dict[str, Any] = {
        "schema": PROJECTION_SCHEMA,
        "version": _contract.PERSON_STATE_VERSION,
        "contract_version": _contract.CONTRACT_VERSION,
        "compiler_version": PROJECTION_VERSION,
        "current_phase_id": current_phase_id,
        "phase_mode": mode,
        "phase_order": ordered,
        "phase_ordinals": ordinals,
        "people": compiled_people,
        "units": units,
        "items": sorted(items, key=lambda entry: (entry["person_id"], entry["item_id"])),
        "changes": sorted(
            changes, key=lambda entry: (entry["person_id"], entry["to_phase_id"] or "", entry["item_id"])
        ),
        "places": place_items,
        "diagnostics": diagnostics,
        "counts": {
            "people": len(compiled_people),
            "items": len(items),
            "changes": len(changes),
            "places": len(place_items),
            "diagnostics": len(diagnostics),
        },
    }
    result["projection_sha256"] = sha256_json(result)
    if len(canonical_json_bytes(result)) > limits.json_max_bytes:
        raise PersistenceError(
            f"person-state projection exceeds json_max_bytes {limits.json_max_bytes}"
        )
    return result


def _continuity_covers_records(
    fact_ref: str,
    current_phases: set[str],
    descendants: dict[str, set[str]],
    continuities: list[dict[str, Any]],
) -> bool:
    for continuity in continuities:
        if continuity.get("fact_ref") != fact_ref:
            continue
        if _continuity_covers(continuity, current_phases, descendants):
            return True
    return False


def _end_reasons(assessment: str, qualification: Any, attribution: Any) -> list[str]:
    reasons: list[str] = []
    if assessment == "disputed":
        reasons.append("source_disagreement")
    elif assessment != "supported":
        reasons.append("evidence_uncertain")
    if qualification in _NEVER_CURRENT_QUALIFICATIONS:
        reasons.append("attribution_uncertain")
    if qualification == "reported":
        reasons.append("attribution_uncertain")
    if attribution in ("quotation", "annotation", "hearsay"):
        reasons.append("attribution_uncertain")
    return sorted(set(reasons))


# ---------------------------------------------------------------------------
# Cross-source disagreement index
# ---------------------------------------------------------------------------


def compile_person_state_disagreements(
    base_index: list[dict[str, Any]],
    reviewed_links: list[dict[str, Any]],
    catalog_membership: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compile a bounded, immutable, deterministic disagreement index.

    Only reviewed links whose facts are members of the frozen catalog are
    selected. Different offices or same-year phases are *not* turned into
    conflicts here: only explicitly recorded links participate. New links
    can add recorded explanations and uncertain reasons; they can never
    promote a previously uncertain claim to clear on their own (the
    projection owns certainty). Every side keeps its own source
    publication, phase and Claim attribution. Output is sorted by
    disagreement id.
    """
    if not isinstance(base_index, list):
        raise PersistenceError("base_index must be a JSON array")
    if not isinstance(reviewed_links, list):
        raise PersistenceError("reviewed_links must be a JSON array")
    if not isinstance(catalog_membership, dict):
        raise PersistenceError("catalog_membership must be a JSON object")
    catalog_sha = catalog_membership.get("catalog_sha")
    if not isinstance(catalog_sha, str) or not catalog_sha:
        raise PersistenceError("catalog_membership requires catalog_sha")

    members = catalog_membership.get("fact_refs")
    member_set = set(m for m in members if isinstance(m, str)) if isinstance(members, list) else None
    facts = catalog_membership.get("facts") if isinstance(catalog_membership.get("facts"), dict) else {}

    limits = _contract.PersonStateLimits()
    links: dict[str, dict[str, Any]] = {}
    for link in list(base_index) + list(reviewed_links):
        if not isinstance(link, dict):
            continue
        fact_refs = sorted({r for r in link.get("fact_refs") or [] if isinstance(r, str)})
        if len(fact_refs) < 2:
            continue
        if member_set is not None and not set(fact_refs) <= member_set:
            continue
        raw_topic = link.get("topic")
        topic = raw_topic.strip() if isinstance(raw_topic, str) and raw_topic.strip() else " / ".join(fact_refs)
        reason_codes = sorted({r for r in link.get("reason_codes") or [] if r in _REASON_CODES})
        if not reason_codes:
            reason_codes = ["source_disagreement"]
        link_id = _contract.disagreement_id_for(
            catalog_sha=catalog_sha, fact_refs=fact_refs, topic=topic
        )
        phase_ids = sorted({p for p in link.get("phase_ids") or [] if isinstance(p, str)})
        sides = _link_sides(link, fact_refs, facts)
        candidate = {
            "disagreement_id": link_id,
            "catalog_sha": catalog_sha,
            "topic": topic,
            "fact_refs": fact_refs,
            "phase_ids": phase_ids,
            "reason_codes": reason_codes,
            "sides": sides,
        }
        existing = links.get(link_id)
        if existing is not None:
            candidate["reason_codes"] = sorted(
                set(existing["reason_codes"]) | set(candidate["reason_codes"])
            )
            candidate["phase_ids"] = sorted(set(existing["phase_ids"]) | set(candidate["phase_ids"]))
            candidate["sides"] = _merge_sides(existing["sides"], candidate["sides"])
        links[link_id] = candidate

    result = [links[key] for key in sorted(links)]
    if len(result) > limits.max_assertions:
        raise PersistenceError(
            f"person-state disagreement index exceeds max_assertions {limits.max_assertions}"
        )
    return result


def _link_sides(
    link: dict[str, Any], fact_refs: list[str], facts: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep both recorded sides with their source/phase/Claim attribution."""
    provided = link.get("sides")
    if isinstance(provided, list):
        sides = [_normalize_side(side) for side in provided if isinstance(side, dict)]
        if sides:
            return _merge_sides([], sides)
    grouped: dict[str, dict[str, Any]] = {}
    for fact_ref in fact_refs:
        record = facts.get(fact_ref) if isinstance(facts.get(fact_ref), dict) else {}
        publication = record.get("source_publication_id")
        group = publication if isinstance(publication, str) else ""
        side = grouped.setdefault(
            group,
            {
                "source_publication_id": publication if isinstance(publication, str) else None,
                "fact_refs": [],
                "phase_ids": [],
                "claim_refs": [],
            },
        )
        side["fact_refs"].append(fact_ref)
        side["phase_ids"].extend(p for p in record.get("phase_ids") or [] if isinstance(p, str))
        side["claim_refs"].extend(c for c in record.get("claim_refs") or [] if isinstance(c, str))
    return _merge_sides([], list(grouped.values()))


def _normalize_side(side: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_publication_id": side.get("source_publication_id")
        if isinstance(side.get("source_publication_id"), str)
        else None,
        "fact_refs": sorted({r for r in side.get("fact_refs") or [] if isinstance(r, str)}),
        "phase_ids": sorted({p for p in side.get("phase_ids") or [] if isinstance(p, str)}),
        "claim_refs": sorted({c for c in side.get("claim_refs") or [] if isinstance(c, str)}),
    }


def _merge_sides(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for side in list(existing) + list(incoming):
        normalized = _normalize_side(side)
        key = (
            str(normalized["source_publication_id"] or ""),
            tuple(normalized["fact_refs"]),
        )
        current = merged.get(key)
        if current is None:
            merged[key] = normalized
            continue
        current["phase_ids"] = sorted(set(current["phase_ids"]) | set(normalized["phase_ids"]))
        current["claim_refs"] = sorted(set(current["claim_refs"]) | set(normalized["claim_refs"]))
    return [merged[key] for key in sorted(merged)]


__all__ = [
    "PROJECTION_SCHEMA",
    "PROJECTION_VERSION",
    "compile_person_state_disagreements",
    "compile_person_state_projection",
]
