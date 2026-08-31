"""Evaluator v2 for Chronicle model-backed ingestion.

The evaluator intentionally separates provable contract/grounding failures from
semantic differences against a non-exhaustive human gold fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _items(bundle: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = bundle.get(name)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _identity(item: dict[str, Any]) -> str | None:
    value = item.get("temp_id") or item.get("id")
    return str(value) if value is not None else None


def _label_maps(bundle: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    entity_labels: dict[str, str] = {}
    event_items: dict[str, dict[str, Any]] = {}
    for entity in _items(bundle, "entities"):
        identity = _identity(entity)
        name = entity.get("canonical_name")
        if identity and isinstance(name, str):
            entity_labels[identity] = name
    for event in _items(bundle, "events"):
        identity = _identity(event)
        if identity:
            event_items[identity] = event
    return entity_labels, event_items


def _time_signature(event: dict[str, Any]) -> tuple[Any, ...]:
    time = event.get("time")
    if not isinstance(time, dict):
        return (None, None, None, None, None)
    source = time.get("source_calendar") if isinstance(time.get("source_calendar"), dict) else {}
    normalized = time.get("normalized") if isinstance(time.get("normalized"), dict) else {}
    return (
        normalized.get("year"),
        source.get("era"),
        source.get("era_year"),
        source.get("season"),
        source.get("month"),
    )


def _event_features(event: dict[str, Any], entity_labels: dict[str, str]) -> dict[str, Any]:
    participants: set[tuple[str, str]] = set()
    participant_names: set[str] = set()
    for participant in event.get("participants") or []:
        if not isinstance(participant, dict):
            continue
        ref = str(participant.get("entity_ref"))
        name = entity_labels.get(ref, ref)
        role = str(participant.get("role") or "")
        participants.add((name, role))
        participant_names.add(name)
    places = {
        entity_labels.get(str(ref), str(ref)) for ref in (event.get("places") or [])
    }
    return {
        "type": event.get("type"),
        "time": _time_signature(event),
        "participants": participants,
        "participant_names": participant_names,
        "places": places,
        "title": event.get("title"),
    }


def _jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _event_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    score = 0.0
    if left["type"] == right["type"]:
        score += 0.35
    left_time = left["time"]
    right_time = right["time"]
    if left_time[0] is not None and left_time[0] == right_time[0]:
        score += 0.10
    if left_time[2] is not None and left_time[2] == right_time[2]:
        score += 0.05
    if left_time[4] is not None and left_time[4] == right_time[4]:
        score += 0.10
    score += 0.25 * _jaccard(left["participant_names"], right["participant_names"])
    score += 0.10 * _jaccard(left["places"], right["places"])
    if left["participants"] and right["participants"]:
        score += 0.05 * _jaccard(left["participants"], right["participants"])
    return min(score, 1.0)


@dataclass(frozen=True)
class EventMatch:
    actual_id: str
    expected_id: str
    score: float


def match_events(
    actual: dict[str, Any], expected: dict[str, Any], threshold: float = 0.60
) -> tuple[list[EventMatch], list[str], list[str]]:
    actual_labels, _ = _label_maps(actual)
    expected_labels, _ = _label_maps(expected)
    actual_events = [event for event in _items(actual, "events") if _identity(event)]
    expected_events = [event for event in _items(expected, "events") if _identity(event)]
    candidates: list[tuple[float, str, str]] = []
    for left in actual_events:
        left_id = _identity(left)
        assert left_id is not None
        left_features = _event_features(left, actual_labels)
        for right in expected_events:
            right_id = _identity(right)
            assert right_id is not None
            score = _event_similarity(left_features, _event_features(right, expected_labels))
            if score >= threshold:
                candidates.append((score, left_id, right_id))
    candidates.sort(reverse=True)
    used_actual: set[str] = set()
    used_expected: set[str] = set()
    matches: list[EventMatch] = []
    for score, actual_id, expected_id in candidates:
        if actual_id in used_actual or expected_id in used_expected:
            continue
        used_actual.add(actual_id)
        used_expected.add(expected_id)
        matches.append(EventMatch(actual_id, expected_id, round(score, 3)))
    missing = [
        str(event.get("title"))
        for event in expected_events
        if _identity(event) not in used_expected
    ]
    additional = [
        str(event.get("title"))
        for event in actual_events
        if _identity(event) not in used_actual
    ]
    return matches, missing, additional


def _predicate_policy(config: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    claim = config.get("claim") if isinstance(config.get("claim"), dict) else {}
    predicates = claim.get("predicates") if isinstance(claim.get("predicates"), dict) else {}
    allowed = {str(value) for value in predicates.get("allowed", [])}
    aliases = {
        str(key): str(value)
        for key, value in (predicates.get("aliases") or {}).items()
    }
    return allowed, aliases


def _canonical_predicate(value: Any, aliases: dict[str, str]) -> str:
    text = str(value or "")
    return aliases.get(text, text)


def _ref_label(
    ref: Any,
    entity_labels: dict[str, str],
    event_labels: dict[str, str],
    event_remap: dict[str, str] | None = None,
) -> tuple[str, str] | None:
    if not isinstance(ref, dict):
        return None
    kind = ref.get("kind")
    identity = str(ref.get("ref"))
    if kind == "entity_ref":
        return ("entity", entity_labels.get(identity, identity))
    if kind == "event_ref":
        mapped = event_remap.get(identity, identity) if event_remap else identity
        return ("event", event_labels.get(mapped, mapped))
    if kind == "literal":
        return ("literal", str(ref.get("value")))
    return None


def _evidence_overlap(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    left_chars = set(left)
    right_chars = set(right)
    return _jaccard(left_chars, right_chars)


def _claim_features(
    claim: dict[str, Any],
    entity_labels: dict[str, str],
    event_labels: dict[str, str],
    aliases: dict[str, str],
    event_remap: dict[str, str] | None = None,
) -> dict[str, Any]:
    evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
    return {
        "subject": _ref_label(claim.get("subject"), entity_labels, event_labels, event_remap),
        "predicate": _canonical_predicate(claim.get("predicate"), aliases),
        "object": _ref_label(claim.get("object"), entity_labels, event_labels, event_remap)
        if claim.get("object") is not None
        else None,
        "evidence": str(evidence.get("text") or ""),
    }


def _claim_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    score = 0.0
    if left["predicate"] == right["predicate"]:
        score += 0.35
    if left["subject"] == right["subject"]:
        score += 0.30
    if left["object"] == right["object"]:
        score += 0.20
    score += 0.15 * _evidence_overlap(left["evidence"], right["evidence"])
    return min(score, 1.0)


def match_claims(
    actual: dict[str, Any],
    expected: dict[str, Any],
    config: dict[str, Any],
    event_matches: list[EventMatch],
    threshold: float = 0.70,
) -> tuple[int, list[str], list[str]]:
    actual_entities, actual_events = _label_maps(actual)
    expected_entities, expected_events = _label_maps(expected)
    expected_event_titles = {
        identity: str(item.get("title")) for identity, item in expected_events.items()
    }
    actual_event_remap = {
        match.actual_id: match.expected_id for match in event_matches
    }
    allowed, aliases = _predicate_policy(config)
    _ = allowed
    actual_claims = _items(actual, "claims")
    expected_claims = _items(expected, "claims")
    candidates: list[tuple[float, int, int]] = []
    for left_index, left in enumerate(actual_claims):
        left_features = _claim_features(
            left,
            actual_entities,
            expected_event_titles,
            aliases,
            actual_event_remap,
        )
        for right_index, right in enumerate(expected_claims):
            right_features = _claim_features(
                right,
                expected_entities,
                expected_event_titles,
                aliases,
            )
            score = _claim_similarity(left_features, right_features)
            if score >= threshold:
                candidates.append((score, left_index, right_index))
    candidates.sort(reverse=True)
    used_actual: set[int] = set()
    used_expected: set[int] = set()
    for score, left_index, right_index in candidates:
        if left_index in used_actual or right_index in used_expected:
            continue
        used_actual.add(left_index)
        used_expected.add(right_index)
    missing = [
        str((claim.get("evidence") or {}).get("text"))
        for index, claim in enumerate(expected_claims)
        if index not in used_expected
    ]
    additional = [
        str((claim.get("evidence") or {}).get("text"))
        for index, claim in enumerate(actual_claims)
        if index not in used_actual
    ]
    return len(used_expected), missing, additional


def hard_checks(
    bundle: dict[str, Any], raw: str, config: dict[str, Any]
) -> dict[str, list[str]]:
    entity_ids = {identity for item in _items(bundle, "entities") if (identity := _identity(item))}
    event_ids = {identity for item in _items(bundle, "events") if (identity := _identity(item))}
    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    source_id = _identity(source)
    allowed_predicates, aliases = _predicate_policy(config)

    grounding: list[str] = []
    references: list[str] = []
    time_precision: list[str] = []
    predicate: list[str] = []
    assessment: list[str] = []

    for index, entity in enumerate(_items(bundle, "entities"), 1):
        mentions = entity.get("mentions") if isinstance(entity.get("mentions"), list) else []
        mention_texts = [
            str(mention.get("text"))
            for mention in mentions
            if isinstance(mention, dict) and mention.get("text")
        ]
        canonical = str(entity.get("canonical_name") or "")
        if canonical not in raw and not any(text in raw for text in mention_texts):
            grounding.append(f"entity[{index}] {canonical!r} has no source-grounded mention")

    def check_time(owner: str, time: Any) -> None:
        if not isinstance(time, dict):
            return
        source_calendar = time.get("source_calendar") if isinstance(time.get("source_calendar"), dict) else {}
        normalized = time.get("normalized") if isinstance(time.get("normalized"), dict) else None
        if source_calendar.get("system") != "chinese_lunisolar_regnal" or normalized is None:
            return
        normalization = ((config.get("time") or {}).get("normalization") or {})
        if normalization.get("forbid_unverified_month_conversion") and normalized.get("month") is not None:
            time_precision.append(f"{owner} fabricates Gregorian month from traditional calendar")
        if normalization.get("forbid_unverified_day_conversion") and normalized.get("day") is not None:
            time_precision.append(f"{owner} fabricates Gregorian day from traditional calendar")

    for index, event in enumerate(_items(bundle, "events"), 1):
        event_id = _identity(event) or f"event[{index}]"
        for participant in event.get("participants") or []:
            if isinstance(participant, dict):
                ref = str(participant.get("entity_ref"))
                if ref not in entity_ids:
                    references.append(f"{event_id} references missing entity {ref}")
        for ref in event.get("places") or []:
            if str(ref) not in entity_ids:
                references.append(f"{event_id} references missing place entity {ref}")
        parent = event.get("parent_event_ref")
        if parent is not None and str(parent) not in event_ids:
            references.append(f"{event_id} references missing parent event {parent}")
        check_time(event_id, event.get("time"))

    for index, claim in enumerate(_items(bundle, "claims"), 1):
        claim_id = _identity(claim) or f"claim[{index}]"
        evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
        text = str(evidence.get("text") or "")
        if text not in raw:
            grounding.append(f"{claim_id} evidence is not an exact SOURCE TEXT substring: {text!r}")
        if source_id is not None and str(evidence.get("source_ref")) != source_id:
            references.append(f"{claim_id} references unknown source {evidence.get('source_ref')}")
        for field in ("subject", "object"):
            ref = claim.get(field)
            if not isinstance(ref, dict):
                continue
            kind = ref.get("kind")
            identity = str(ref.get("ref"))
            if kind == "entity_ref" and identity not in entity_ids:
                references.append(f"{claim_id}.{field} references missing entity {identity}")
            if kind == "event_ref" and identity not in event_ids:
                references.append(f"{claim_id}.{field} references missing event {identity}")
        canonical = _canonical_predicate(claim.get("predicate"), aliases)
        if allowed_predicates and canonical not in allowed_predicates:
            predicate.append(f"{claim_id} uses predicate outside configured vocabulary: {claim.get('predicate')}")
        status = (claim.get("assessment") or {}).get("status") if isinstance(claim.get("assessment"), dict) else None
        if status != "unassessed":
            assessment.append(f"{claim_id} assessment must start unassessed, got {status!r}")
        check_time(claim_id, claim.get("time"))

    return {
        "grounding": grounding,
        "reference_integrity": references,
        "time_precision": time_precision,
        "predicate_vocabulary": predicate,
        "initial_assessment": assessment,
    }


def evaluation_report_v2(
    bundle: dict[str, Any],
    raw: str,
    config: dict[str, Any],
    schema_errors: list[str],
    expected: dict[str, Any] | None,
    extractor: str,
    provider: str | None,
) -> dict[str, Any]:
    hard = hard_checks(bundle, raw, config)
    hard_count = len(schema_errors) + sum(len(values) for values in hard.values())
    semantic: dict[str, Any] = {"performed": expected is not None}
    if expected is not None:
        expected_entity_names = {
            str(item.get("canonical_name")) for item in _items(expected, "entities")
        }
        actual_entity_names = {
            str(item.get("canonical_name")) for item in _items(bundle, "entities")
        }
        matched_entities = expected_entity_names & actual_entity_names
        event_matches, missing_events, additional_events = match_events(bundle, expected)
        matched_claims, missing_claims, additional_claims = match_claims(
            bundle, expected, config, event_matches
        )
        semantic = {
            "performed": True,
            "gold_is_exhaustive": False,
            "entities": {
                "gold_expected": len(expected_entity_names),
                "gold_matched": len(matched_entities),
                "gold_recall": round(len(matched_entities) / len(expected_entity_names), 3)
                if expected_entity_names
                else None,
                "missing_gold": sorted(expected_entity_names - actual_entity_names),
                "additional_output": sorted(actual_entity_names - expected_entity_names),
            },
            "events": {
                "gold_expected": len(_items(expected, "events")),
                "gold_matched": len(event_matches),
                "gold_recall": round(len(event_matches) / len(_items(expected, "events")), 3)
                if _items(expected, "events")
                else None,
                "missing_gold": missing_events,
                "additional_output": additional_events,
                "matches": [match.__dict__ for match in event_matches],
            },
            "claims": {
                "gold_expected": len(_items(expected, "claims")),
                "gold_matched": matched_claims,
                "gold_recall": round(matched_claims / len(_items(expected, "claims")), 3)
                if _items(expected, "claims")
                else None,
                "missing_gold_evidence": missing_claims,
                "additional_output_evidence": additional_claims,
            },
        }
    return {
        "schema": "chronicle.ingestion-evaluation",
        "version": "0.2",
        "extractor": extractor,
        "provider": provider,
        "hard_failures": {
            "passed": hard_count == 0,
            "count": hard_count,
            "schema_validation": schema_errors,
            **hard,
        },
        "semantic_evaluation": semantic,
        "counts": {
            name: len(_items(bundle, name)) if name != "warnings" else len(bundle.get("warnings") or [])
            for name in ("entities", "events", "claims", "warnings")
        },
    }
