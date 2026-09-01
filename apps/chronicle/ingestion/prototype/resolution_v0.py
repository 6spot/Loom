"""Chronicle cross-source resolution/linking prototype.

Resolution v0 is deliberately non-destructive:
- staged source bundles remain immutable;
- deterministic code only generates conservative candidate pairs;
- a model may adjudicate only those candidates;
- final links never assign canonical UUIDs or rewrite source records.
"""

from __future__ import annotations

import json
from typing import Any

from model_v0 import ModelProvider, ModelV0Error, parse_model_response

RESOLUTION_VERSION = "0.1"


class ResolutionV0Error(ModelV0Error):
    pass


def _record_id(record: dict[str, Any]) -> str:
    value = record.get("temp_id") or record.get("id")
    if not isinstance(value, str) or not value:
        raise ResolutionV0Error("resolution input record is missing identity")
    return value


def _bundle_ref(bundle: dict[str, Any], label: str) -> dict[str, str]:
    source = bundle.get("source")
    if not isinstance(source, dict):
        raise ResolutionV0Error(f"bundle {label!r} is missing source")
    title = source.get("title")
    if not isinstance(title, str) or not title:
        raise ResolutionV0Error(f"bundle {label!r} source is missing title")
    return {
        "label": label,
        "source_ref": _record_id(source),
        "source_title": title,
    }


def _stable_entity_surfaces(entity: dict[str, Any]) -> set[str]:
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


def _entity_snapshot(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "ref": _record_id(entity),
        "type": entity.get("type"),
        "canonical_name": entity.get("canonical_name"),
        "aliases": entity.get("aliases") or [],
        "stable_mentions": [
            m.get("text")
            for m in entity.get("mentions") or []
            if isinstance(m, dict) and not m.get("contextual") and m.get("text")
        ],
    }


def entity_candidates(
    left_bundle: dict[str, Any],
    left_label: str,
    right_bundle: dict[str, Any],
    right_label: str,
) -> list[dict[str, Any]]:
    """Generate conservative cross-bundle Entity identity candidates.

    V0 blocks only same-type records with an exact stable surface in common.
    A candidate is not a merge decision; the resolver must still adjudicate it.
    """

    candidates: list[dict[str, Any]] = []
    for left in left_bundle.get("entities") or []:
        if not isinstance(left, dict):
            continue
        left_surfaces = _stable_entity_surfaces(left)
        if not left_surfaces:
            continue
        for right in right_bundle.get("entities") or []:
            if not isinstance(right, dict) or left.get("type") != right.get("type"):
                continue
            shared = sorted(left_surfaces & _stable_entity_surfaces(right))
            if not shared:
                continue
            signals = [f"same entity type: {left.get('type')}"]
            left_name = left.get("canonical_name")
            right_name = right.get("canonical_name")
            if left_name == right_name and isinstance(left_name, str):
                signals.append(f"exact canonical surface: {left_name}")
            else:
                signals.append("shared stable surface: " + ", ".join(shared))
            candidates.append(
                {
                    "left": {"bundle": left_label, "ref": _record_id(left)},
                    "right": {"bundle": right_label, "ref": _record_id(right)},
                    "signals": signals,
                    "left_record": _entity_snapshot(left),
                    "right_record": _entity_snapshot(right),
                }
            )
    candidates.sort(key=lambda c: (c["left"]["ref"], c["right"]["ref"]))
    for index, candidate in enumerate(candidates, 1):
        candidate["candidate_id"] = f"ec_{index:03d}"
    return candidates


def _entity_name_map(bundle: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entity in bundle.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        ref = entity.get("temp_id") or entity.get("id")
        name = entity.get("canonical_name")
        if isinstance(ref, str) and isinstance(name, str):
            result[ref] = name
    return result


def _event_participants(event: dict[str, Any], names: dict[str, str]) -> set[str]:
    result: set[str] = set()
    for participant in event.get("participants") or []:
        if not isinstance(participant, dict):
            continue
        ref = participant.get("entity_ref")
        if isinstance(ref, str) and ref in names:
            result.add(names[ref])
    return result


def _event_places(event: dict[str, Any], names: dict[str, str]) -> set[str]:
    result: set[str] = set()
    for ref in event.get("places") or []:
        if isinstance(ref, str):
            result.add(names.get(ref, ref))
    return result


def _event_time(event: dict[str, Any]) -> dict[str, Any]:
    time = event.get("time")
    if not isinstance(time, dict):
        return {"normalized_year": None, "era": None, "era_year": None, "season": None, "month": None}
    source = time.get("source_calendar") or {}
    normalized = time.get("normalized") or {}
    return {
        "normalized_year": normalized.get("year") if isinstance(normalized, dict) else None,
        "era": source.get("era") if isinstance(source, dict) else None,
        "era_year": source.get("era_year") if isinstance(source, dict) else None,
        "season": source.get("season") if isinstance(source, dict) else None,
        "month": source.get("month") if isinstance(source, dict) else None,
    }


def _time_compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    lt = _event_time(left)
    rt = _event_time(right)
    if lt["normalized_year"] is not None and rt["normalized_year"] is not None:
        if lt["normalized_year"] != rt["normalized_year"]:
            return False
    if lt["era"] and rt["era"] and lt["era"] != rt["era"]:
        return False
    if lt["era_year"] is not None and rt["era_year"] is not None:
        if lt["era_year"] != rt["era_year"]:
            return False
    return True


_EVENT_TYPE_GROUPS = (
    {"movement", "retreat"},
    {"military", "battle"},
)


def _event_type_compatible(left_type: Any, right_type: Any) -> bool:
    if left_type == right_type and isinstance(left_type, str):
        return True
    return any(left_type in group and right_type in group for group in _EVENT_TYPE_GROUPS)


def _event_snapshot(event: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    return {
        "ref": _record_id(event),
        "type": event.get("type"),
        "title": event.get("title"),
        "time": _event_time(event),
        "participants": sorted(_event_participants(event, names)),
        "places": sorted(_event_places(event, names)),
    }


def event_candidates(
    left_bundle: dict[str, Any],
    left_label: str,
    right_bundle: dict[str, Any],
    right_label: str,
    max_candidates: int = 64,
) -> list[dict[str, Any]]:
    """Generate plausible Event overlap candidates without deciding identity."""

    left_names = _entity_name_map(left_bundle)
    right_names = _entity_name_map(right_bundle)
    ranked: list[tuple[int, dict[str, Any]]] = []

    for left in left_bundle.get("events") or []:
        if not isinstance(left, dict):
            continue
        lp = _event_participants(left, left_names)
        lplaces = _event_places(left, left_names)
        for right in right_bundle.get("events") or []:
            if not isinstance(right, dict) or not _time_compatible(left, right):
                continue
            rp = _event_participants(right, right_names)
            rplaces = _event_places(right, right_names)
            participant_overlap = sorted(lp & rp)
            place_overlap = sorted(lplaces & rplaces)
            type_compatible = _event_type_compatible(left.get("type"), right.get("type"))

            qualifies = (
                (type_compatible and bool(participant_overlap))
                or len(participant_overlap) >= 2
                or (bool(participant_overlap) and bool(place_overlap))
            )
            if not qualifies:
                continue

            score = 0
            signals: list[str] = []
            if type_compatible:
                score += 3
                signals.append(f"compatible event types: {left.get('type')} / {right.get('type')}")
            if participant_overlap:
                score += 2 * len(participant_overlap)
                signals.append("shared participants: " + ", ".join(participant_overlap))
            if place_overlap:
                score += 2 * len(place_overlap)
                signals.append("shared places: " + ", ".join(place_overlap))
            lt = _event_time(left)
            rt = _event_time(right)
            if lt["normalized_year"] is not None and lt["normalized_year"] == rt["normalized_year"]:
                score += 1
                signals.append(f"same normalized year: {lt['normalized_year']}")

            ranked.append(
                (
                    score,
                    {
                        "left": {"bundle": left_label, "ref": _record_id(left)},
                        "right": {"bundle": right_label, "ref": _record_id(right)},
                        "signals": signals,
                        "left_record": _event_snapshot(left, left_names),
                        "right_record": _event_snapshot(right, right_names),
                    },
                )
            )

    ranked.sort(key=lambda item: (-item[0], item[1]["left"]["ref"], item[1]["right"]["ref"]))
    candidates = [item[1] for item in ranked[:max_candidates]]
    for index, candidate in enumerate(candidates, 1):
        candidate["candidate_id"] = f"vc_{index:03d}"
    return candidates


def build_candidate_set(
    left_bundle: dict[str, Any],
    left_label: str,
    right_bundle: dict[str, Any],
    right_label: str,
) -> dict[str, Any]:
    if left_label == right_label:
        raise ResolutionV0Error("left and right bundle labels must be distinct")
    return {
        "schema": "chronicle.resolution-candidates",
        "version": RESOLUTION_VERSION,
        "left_bundle": _bundle_ref(left_bundle, left_label),
        "right_bundle": _bundle_ref(right_bundle, right_label),
        "entity_candidates": entity_candidates(left_bundle, left_label, right_bundle, right_label),
        "event_candidates": event_candidates(left_bundle, left_label, right_bundle, right_label),
    }


def build_resolution_prompt(candidates: dict[str, Any]) -> str:
    payload = json.dumps(candidates, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""You are Chronicle resolution-v0.1, a closed-world cross-source resolver.

TASK
Adjudicate only the candidate pairs supplied below. The two source bundles were already independently extracted and must remain immutable.

RULES
1. Use only the supplied candidate records and signals. Do not add outside historical knowledge.
2. `same_entity` means both Entity records refer to the same historical identity, not merely the same name or role.
3. `same_occurrence` means both Event records describe the same underlying historical occurrence, even when wording, emphasis, or granularity differs slightly.
4. `related_occurrence` means the Events are historically connected or part of the same sequence/campaign but are not the same occurrence.
5. Use `not_same` when the records clearly describe different identities/occurrences.
6. Use `uncertain` when the supplied evidence is insufficient. Do not guess.
7. Resolution confidence measures confidence in this link decision only. It is not historical-truth confidence.
8. Do not invent canonical UUIDs, rewrite temp IDs, merge records, or create new historical facts.
9. Return every supplied candidate_id exactly once and no unknown candidate_id.
10. Return exactly one JSON object and no prose.

OUTPUT FORMAT
{{
  "entity_decisions": [
    {{"candidate_id": "ec_001", "decision": "same_entity|not_same|uncertain", "confidence": 0.0, "rationale": "brief source-bounded reason"}}
  ],
  "event_decisions": [
    {{"candidate_id": "vc_001", "decision": "same_occurrence|related_occurrence|not_same|uncertain", "confidence": 0.0, "rationale": "brief source-bounded reason"}}
  ]
}}

CANDIDATES
{payload}
"""


def _decisions_by_id(
    response: dict[str, Any],
    field: str,
    candidates: list[dict[str, Any]],
    allowed: set[str],
) -> dict[str, dict[str, Any]]:
    raw = response.get(field)
    if not isinstance(raw, list):
        raise ResolutionV0Error(f"resolver response {field} must be an array")
    expected = {c["candidate_id"] for c in candidates}
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ResolutionV0Error(f"resolver response {field} contains a non-object")
        candidate_id = item.get("candidate_id")
        if candidate_id not in expected:
            raise ResolutionV0Error(f"resolver returned unknown {field} candidate_id {candidate_id!r}")
        if candidate_id in result:
            raise ResolutionV0Error(f"resolver returned duplicate candidate_id {candidate_id}")
        decision = item.get("decision")
        confidence = item.get("confidence")
        rationale = item.get("rationale")
        if decision not in allowed:
            raise ResolutionV0Error(f"resolver returned invalid decision {decision!r} for {candidate_id}")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ResolutionV0Error(f"resolver returned invalid confidence for {candidate_id}")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ResolutionV0Error(f"resolver returned empty rationale for {candidate_id}")
        result[candidate_id] = {
            "decision": decision,
            "confidence": float(confidence),
            "rationale": rationale.strip(),
        }
    missing = sorted(expected - result.keys())
    if missing:
        raise ResolutionV0Error("resolver omitted candidate_ids: " + ", ".join(missing))
    return result


def apply_resolution_decisions(
    candidates: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    entity_candidates_list = candidates.get("entity_candidates") or []
    event_candidates_list = candidates.get("event_candidates") or []
    entity_decisions = _decisions_by_id(
        response,
        "entity_decisions",
        entity_candidates_list,
        {"same_entity", "not_same", "uncertain"},
    )
    event_decisions = _decisions_by_id(
        response,
        "event_decisions",
        event_candidates_list,
        {"same_occurrence", "related_occurrence", "not_same", "uncertain"},
    )

    def links(items: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for candidate in items:
            candidate_id = candidate["candidate_id"]
            decision = decisions[candidate_id]
            result.append(
                {
                    "candidate_id": candidate_id,
                    "left": candidate["left"],
                    "right": candidate["right"],
                    "decision": decision["decision"],
                    "confidence": decision["confidence"],
                    "rationale": decision["rationale"],
                    "signals": candidate["signals"],
                }
            )
        return result

    entity_links = links(entity_candidates_list, entity_decisions)
    event_links = links(event_candidates_list, event_decisions)
    warnings: list[dict[str, Any]] = []
    for link in entity_links + event_links:
        if link["decision"] == "uncertain":
            warnings.append(
                {
                    "type": "unresolved_resolution",
                    "message": f"Resolution candidate {link['candidate_id']} remains uncertain.",
                    "refs": [link["candidate_id"]],
                }
            )

    return {
        "schema": "chronicle.resolution-links",
        "version": RESOLUTION_VERSION,
        "left_bundle": candidates["left_bundle"],
        "right_bundle": candidates["right_bundle"],
        "entity_links": entity_links,
        "event_links": event_links,
        "warnings": warnings,
    }


def resolve_with_provider(
    candidates: dict[str, Any], provider: ModelProvider
) -> tuple[dict[str, Any], str]:
    if not (candidates.get("entity_candidates") or candidates.get("event_candidates")):
        empty = {
            "entity_decisions": [],
            "event_decisions": [],
        }
        return apply_resolution_decisions(candidates, empty), ""
    raw = provider.complete(build_resolution_prompt(candidates))
    response = parse_model_response(raw)
    return apply_resolution_decisions(candidates, response), raw
