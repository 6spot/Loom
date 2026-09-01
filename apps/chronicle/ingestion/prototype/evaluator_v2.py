"""Evaluator v2 for Chronicle model-backed ingestion.

Hard checks cover provable contract/grounding failures. Semantic evaluation is
lenient about transport IDs, normalized/raw titles, evidence-span length, and
configured representation aliases because the current human gold fixture is
non-exhaustive.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _items(bundle: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = bundle.get(name)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _identity(item: dict[str, Any]) -> str | None:
    value = item.get("temp_id") or item.get("id")
    return str(value) if value is not None else None


def _entity_maps(bundle: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    labels: dict[str, str] = {}
    types: dict[str, str] = {}
    for item in _items(bundle, "entities"):
        identity = _identity(item)
        name = item.get("canonical_name")
        if identity and isinstance(name, str):
            labels[identity] = name
            types[identity] = str(item.get("type") or "")
    return labels, types


def _event_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in _items(bundle, "events"):
        identity = _identity(item)
        if identity:
            result[identity] = item
    return result


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


def _overlap(left: set[Any], right: set[Any]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _shared_phrase(left: str, right: str, size: int = 2) -> bool:
    if not left or not right:
        return False
    punctuation = "，。；：、,.!?！？"
    compact_left = "".join(ch for ch in left if not ch.isspace() and ch not in punctuation)
    compact_right = "".join(ch for ch in right if not ch.isspace() and ch not in punctuation)
    if len(compact_left) < size or len(compact_right) < size:
        return False
    grams = {
        compact_left[index : index + size]
        for index in range(len(compact_left) - size + 1)
    }
    return any(
        compact_right[index : index + size] in grams
        for index in range(len(compact_right) - size + 1)
    )


def _event_features(event: dict[str, Any], entity_labels: dict[str, str]) -> dict[str, Any]:
    participant_names: set[str] = set()
    participant_roles: set[tuple[str, str]] = set()
    for participant in event.get("participants") or []:
        if not isinstance(participant, dict):
            continue
        ref = str(participant.get("entity_ref"))
        name = entity_labels.get(ref, ref)
        participant_names.add(name)
        participant_roles.add((name, str(participant.get("role") or "")))
    places = {
        entity_labels.get(str(ref), str(ref)) for ref in event.get("places") or []
    }
    return {
        "type": event.get("type"),
        "time": _time_signature(event),
        "participant_names": participant_names,
        "participant_roles": participant_roles,
        "places": places,
        "title": str(event.get("title") or ""),
    }


def _event_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    score = 0.0
    same_type = left["type"] == right["type"]
    if same_type:
        score += 0.35
    left_time = left["time"]
    right_time = right["time"]
    if left_time[0] is not None and left_time[0] == right_time[0]:
        score += 0.10
    if left_time[2] is not None and left_time[2] == right_time[2]:
        score += 0.05
    if left_time[4] is not None and left_time[4] == right_time[4]:
        score += 0.10
    score += 0.25 * _overlap(left["participant_names"], right["participant_names"])
    score += 0.10 * _overlap(left["places"], right["places"])
    score += 0.05 * _overlap(left["participant_roles"], right["participant_roles"])
    if same_type and _shared_phrase(left["title"], right["title"]):
        score += 0.15
    return min(score, 1.0)


@dataclass(frozen=True)
class EventMatch:
    actual_id: str
    expected_id: str
    score: float


def match_events(
    actual: dict[str, Any], expected: dict[str, Any], threshold: float = 0.60
) -> tuple[list[EventMatch], list[str], list[str]]:
    actual_labels, _ = _entity_maps(actual)
    expected_labels, _ = _entity_maps(expected)
    actual_events = _event_map(actual)
    expected_events = _event_map(expected)
    candidates: list[tuple[float, str, str]] = []
    for actual_id, left in actual_events.items():
        left_features = _event_features(left, actual_labels)
        for expected_id, right in expected_events.items():
            score = _event_similarity(left_features, _event_features(right, expected_labels))
            if score >= threshold:
                candidates.append((score, actual_id, expected_id))
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
        str(item.get("title"))
        for identity, item in expected_events.items()
        if identity not in used_expected
    ]
    additional = [
        str(item.get("title"))
        for identity, item in actual_events.items()
        if identity not in used_actual
    ]
    return matches, missing, additional


def _predicate_policy(config: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    claim = config.get("claim") if isinstance(config.get("claim"), dict) else {}
    predicates = claim.get("predicates") if isinstance(claim.get("predicates"), dict) else {}
    allowed = {str(value) for value in predicates.get("allowed", [])}
    aliases = {
        str(key): str(value) for key, value in (predicates.get("aliases") or {}).items()
    }
    return allowed, aliases


def _canonical_predicate(value: Any, aliases: dict[str, str]) -> str:
    text = str(value or "")
    return aliases.get(text, text)


def _event_titles(bundle: dict[str, Any]) -> dict[str, str]:
    return {
        identity: str(item.get("title"))
        for identity, item in _event_map(bundle).items()
    }


def _semantic_ref(
    ref: Any,
    predicate: str,
    entity_labels: dict[str, str],
    entity_types: dict[str, str],
    event_labels: dict[str, str],
    event_remap: dict[str, str] | None = None,
) -> tuple[str, str] | None:
    if not isinstance(ref, dict):
        return None
    kind = ref.get("kind")
    identity = str(ref.get("ref"))
    if kind == "entity_ref":
        name = entity_labels.get(identity, identity)
        entity_type = entity_types.get(identity, "")
        if predicate == "held_office" and entity_type == "office":
            return ("value", name)
        if predicate == "gained_territory" and entity_type in {"place", "polity"}:
            return ("value", name)
        return ("entity", name)
    if kind == "event_ref":
        mapped = event_remap.get(identity, identity) if event_remap else identity
        return ("event", event_labels.get(mapped, mapped))
    if kind == "literal":
        value = str(ref.get("value"))
        if predicate in {"held_office", "gained_territory"}:
            return ("value", value)
        return ("literal", value)
    return None


def _evidence_overlap(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    return _overlap(set(left), set(right))


def _semantic_value_similarity(
    left: tuple[str, str] | None, right: tuple[str, str] | None
) -> float:
    if left == right:
        return 1.0
    if left is None or right is None:
        return 0.0
    left_kind, left_value = left
    right_kind, right_value = right
    if left_value == right_value:
        return 0.9
    if left_value and right_value and (
        left_value in right_value or right_value in left_value
    ):
        if left_kind == right_kind or {left_kind, right_kind} <= {
            "literal",
            "value",
            "entity",
        }:
            return 0.85
    return 0.0


def _claim_features(
    claim: dict[str, Any],
    entity_labels: dict[str, str],
    entity_types: dict[str, str],
    event_labels: dict[str, str],
    aliases: dict[str, str],
    event_remap: dict[str, str] | None = None,
) -> dict[str, Any]:
    predicate = _canonical_predicate(claim.get("predicate"), aliases)
    evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
    return {
        "subject": _semantic_ref(
            claim.get("subject"),
            predicate,
            entity_labels,
            entity_types,
            event_labels,
            event_remap,
        ),
        "predicate": predicate,
        "object": _semantic_ref(
            claim.get("object"),
            predicate,
            entity_labels,
            entity_types,
            event_labels,
            event_remap,
        )
        if claim.get("object") is not None
        else None,
        "evidence": str(evidence.get("text") or ""),
    }


def _claim_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    score = 0.0
    if left["predicate"] == right["predicate"]:
        score += 0.35
    score += 0.30 * _semantic_value_similarity(left["subject"], right["subject"])
    score += 0.20 * _semantic_value_similarity(left["object"], right["object"])
    score += 0.15 * _evidence_overlap(left["evidence"], right["evidence"])
    return min(score, 1.0)


@dataclass(frozen=True)
class CompositeClaimMatch:
    expected_index: int
    actual_indices: tuple[int, ...]
    expected_evidence: str
    actual_evidence: tuple[str, ...]


@dataclass(frozen=True)
class ClaimMatchResult:
    matched: int
    direct_matched: int
    composite_matched: int
    missing: tuple[str, ...]
    additional: tuple[str, ...]
    composite_matches: tuple[CompositeClaimMatch, ...]


def _composite_claim_matches(
    actual_features: list[dict[str, Any]],
    expected_features: list[dict[str, Any]],
    used_actual: set[int],
    used_expected: set[int],
) -> list[CompositeClaimMatch]:
    matches: list[CompositeClaimMatch] = []
    for expected_index, expected in enumerate(expected_features):
        if expected_index in used_expected:
            continue
        expected_evidence = expected["evidence"]
        if not expected_evidence:
            continue
        candidates: list[int] = []
        same_predicate = False
        covered_length = 0
        for actual_index, actual in enumerate(actual_features):
            if actual_index in used_actual:
                continue
            evidence = actual["evidence"]
            if not evidence or evidence not in expected_evidence:
                continue
            if (
                actual["predicate"] == expected["predicate"]
                or _semantic_value_similarity(actual["subject"], expected["subject"])
                >= 0.85
                or _semantic_value_similarity(actual["object"], expected["object"])
                >= 0.85
            ):
                candidates.append(actual_index)
                covered_length += len(evidence)
                same_predicate = same_predicate or (
                    actual["predicate"] == expected["predicate"]
                )
        if len(candidates) < 2 or not same_predicate:
            continue
        if covered_length / max(len(expected_evidence), 1) < 0.50:
            continue
        selected = tuple(candidates)
        for index in selected:
            used_actual.add(index)
        used_expected.add(expected_index)
        matches.append(
            CompositeClaimMatch(
                expected_index=expected_index,
                actual_indices=selected,
                expected_evidence=expected_evidence,
                actual_evidence=tuple(
                    actual_features[index]["evidence"] for index in selected
                ),
            )
        )
    return matches


def match_claims_detailed(
    actual: dict[str, Any],
    expected: dict[str, Any],
    config: dict[str, Any],
    event_matches: list[EventMatch],
    threshold: float = 0.65,
) -> ClaimMatchResult:
    actual_labels, actual_types = _entity_maps(actual)
    expected_labels, expected_types = _entity_maps(expected)
    expected_event_labels = _event_titles(expected)
    event_remap = {match.actual_id: match.expected_id for match in event_matches}
    _allowed, aliases = _predicate_policy(config)
    actual_claims = _items(actual, "claims")
    expected_claims = _items(expected, "claims")
    actual_features = [
        _claim_features(
            item,
            actual_labels,
            actual_types,
            expected_event_labels,
            aliases,
            event_remap,
        )
        for item in actual_claims
    ]
    expected_features = [
        _claim_features(
            item,
            expected_labels,
            expected_types,
            expected_event_labels,
            aliases,
        )
        for item in expected_claims
    ]
    candidates: list[tuple[float, int, int]] = []
    for left_index, left in enumerate(actual_features):
        for right_index, right in enumerate(expected_features):
            score = _claim_similarity(left, right)
            if score >= threshold:
                candidates.append((score, left_index, right_index))
    candidates.sort(reverse=True)
    used_actual: set[int] = set()
    used_expected: set[int] = set()
    direct = 0
    for _score, left_index, right_index in candidates:
        if left_index in used_actual or right_index in used_expected:
            continue
        used_actual.add(left_index)
        used_expected.add(right_index)
        direct += 1

    composite = _composite_claim_matches(
        actual_features, expected_features, used_actual, used_expected
    )
    missing = tuple(
        expected_features[index]["evidence"]
        for index in range(len(expected_features))
        if index not in used_expected
    )
    additional = tuple(
        actual_features[index]["evidence"]
        for index in range(len(actual_features))
        if index not in used_actual
    )
    return ClaimMatchResult(
        matched=len(used_expected),
        direct_matched=direct,
        composite_matched=len(composite),
        missing=missing,
        additional=additional,
        composite_matches=tuple(composite),
    )


def match_claims(
    actual: dict[str, Any],
    expected: dict[str, Any],
    config: dict[str, Any],
    event_matches: list[EventMatch],
    threshold: float = 0.65,
) -> tuple[int, list[str], list[str]]:
    result = match_claims_detailed(
        actual, expected, config, event_matches, threshold
    )
    return result.matched, list(result.missing), list(result.additional)


def _entity_semantic_matches(
    actual: dict[str, Any], expected: dict[str, Any]
) -> tuple[int, list[str], list[str], list[dict[str, Any]]]:
    actual_entities = _items(actual, "entities")
    expected_entities = _items(expected, "entities")
    actual_by_name = {
        str(item.get("canonical_name")): item for item in actual_entities
    }
    expected_by_name = {
        str(item.get("canonical_name")): item for item in expected_entities
    }
    used_actual: set[str] = set()
    used_expected: set[str] = set()
    matches: list[dict[str, Any]] = []

    for name in sorted(set(actual_by_name) & set(expected_by_name)):
        used_actual.add(name)
        used_expected.add(name)
        matches.append({"actual": name, "expected": name, "mode": "exact"})

    for expected_name, expected_item in expected_by_name.items():
        if expected_name in used_expected:
            continue
        expected_type = str(expected_item.get("type") or "")
        candidates = []
        for actual_name, actual_item in actual_by_name.items():
            if actual_name in used_actual:
                continue
            if str(actual_item.get("type") or "") != expected_type:
                continue
            if expected_name in actual_name or actual_name in expected_name:
                candidates.append(actual_name)
        if len(candidates) == 1:
            actual_name = candidates[0]
            used_actual.add(actual_name)
            used_expected.add(expected_name)
            matches.append(
                {
                    "actual": actual_name,
                    "expected": expected_name,
                    "mode": "surface_containment",
                }
            )

    missing = sorted(set(expected_by_name) - used_expected)
    additional = sorted(set(actual_by_name) - used_actual)
    return len(used_expected), missing, additional, matches


def hard_checks(
    bundle: dict[str, Any], raw: str, config: dict[str, Any]
) -> dict[str, list[str]]:
    entity_ids = {
        identity
        for item in _items(bundle, "entities")
        if (identity := _identity(item))
    }
    event_ids = {
        identity
        for item in _items(bundle, "events")
        if (identity := _identity(item))
    }
    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    source_id = _identity(source)
    allowed_predicates, aliases = _predicate_policy(config)

    grounding: list[str] = []
    references: list[str] = []
    time_precision: list[str] = []
    predicate_errors: list[str] = []
    assessment: list[str] = []

    for index, entity in enumerate(_items(bundle, "entities"), 1):
        mentions = (
            entity.get("mentions") if isinstance(entity.get("mentions"), list) else []
        )
        mention_texts = [
            str(mention.get("text"))
            for mention in mentions
            if isinstance(mention, dict) and mention.get("text")
        ]
        canonical = str(entity.get("canonical_name") or "")
        if canonical not in raw and not any(text in raw for text in mention_texts):
            grounding.append(
                f"entity[{index}] {canonical!r} has no source-grounded mention"
            )

    def check_time(owner: str, value: Any) -> None:
        if not isinstance(value, dict):
            return
        source_calendar = (
            value.get("source_calendar")
            if isinstance(value.get("source_calendar"), dict)
            else {}
        )
        normalized = (
            value.get("normalized")
            if isinstance(value.get("normalized"), dict)
            else None
        )
        if (
            source_calendar.get("system") != "chinese_lunisolar_regnal"
            or normalized is None
        ):
            return
        time_config = (
            config.get("time") if isinstance(config.get("time"), dict) else {}
        )
        normalization = (
            time_config.get("normalization")
            if isinstance(time_config.get("normalization"), dict)
            else {}
        )
        if (
            normalization.get("forbid_unverified_month_conversion")
            and normalized.get("month") is not None
        ):
            time_precision.append(
                f"{owner} fabricates Gregorian month from traditional calendar"
            )
        if (
            normalization.get("forbid_unverified_day_conversion")
            and normalized.get("day") is not None
        ):
            time_precision.append(
                f"{owner} fabricates Gregorian day from traditional calendar"
            )

    for index, event in enumerate(_items(bundle, "events"), 1):
        event_id = _identity(event) or f"event[{index}]"
        for participant in event.get("participants") or []:
            if isinstance(participant, dict):
                ref = str(participant.get("entity_ref"))
                if ref not in entity_ids:
                    references.append(f"{event_id} references missing entity {ref}")
        for ref in event.get("places") or []:
            if str(ref) not in entity_ids:
                references.append(
                    f"{event_id} references missing place entity {ref}"
                )
        parent = event.get("parent_event_ref")
        if parent is not None and str(parent) not in event_ids:
            references.append(
                f"{event_id} references missing parent event {parent}"
            )
        check_time(event_id, event.get("time"))

    for index, claim in enumerate(_items(bundle, "claims"), 1):
        claim_id = _identity(claim) or f"claim[{index}]"
        evidence = (
            claim.get("evidence")
            if isinstance(claim.get("evidence"), dict)
            else {}
        )
        evidence_text = str(evidence.get("text") or "")
        if not evidence_text or evidence_text not in raw:
            grounding.append(
                f"{claim_id} evidence is not an exact SOURCE TEXT substring: {evidence_text!r}"
            )
        if source_id is not None and str(evidence.get("source_ref")) != source_id:
            references.append(
                f"{claim_id} references unknown source {evidence.get('source_ref')}"
            )
        for field in ("subject", "object"):
            ref = claim.get(field)
            if not isinstance(ref, dict):
                continue
            kind = ref.get("kind")
            identity = str(ref.get("ref"))
            if kind == "entity_ref" and identity not in entity_ids:
                references.append(
                    f"{claim_id}.{field} references missing entity {identity}"
                )
            if kind == "event_ref" and identity not in event_ids:
                references.append(
                    f"{claim_id}.{field} references missing event {identity}"
                )
        canonical = _canonical_predicate(claim.get("predicate"), aliases)
        if allowed_predicates and canonical not in allowed_predicates:
            predicate_errors.append(
                f"{claim_id} uses predicate outside configured vocabulary: {claim.get('predicate')}"
            )
        status = (
            (claim.get("assessment") or {}).get("status")
            if isinstance(claim.get("assessment"), dict)
            else None
        )
        if status != "unassessed":
            assessment.append(
                f"{claim_id} assessment must start unassessed, got {status!r}"
            )
        check_time(claim_id, claim.get("time"))

    return {
        "grounding": grounding,
        "reference_integrity": references,
        "time_precision": time_precision,
        "predicate_vocabulary": predicate_errors,
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
        (
            matched_entities,
            missing_entities,
            additional_entities,
            entity_matches,
        ) = _entity_semantic_matches(bundle, expected)
        expected_entity_count = len(_items(expected, "entities"))
        event_matches, missing_events, additional_events = match_events(
            bundle, expected
        )
        claim_result = match_claims_detailed(
            bundle, expected, config, event_matches
        )
        expected_events = _items(expected, "events")
        expected_claims = _items(expected, "claims")
        semantic = {
            "performed": True,
            "gold_is_exhaustive": False,
            "entities": {
                "gold_expected": expected_entity_count,
                "gold_matched": matched_entities,
                "gold_recall": round(
                    matched_entities / expected_entity_count, 3
                )
                if expected_entity_count
                else None,
                "missing_gold": missing_entities,
                "additional_output": additional_entities,
                "matches": entity_matches,
            },
            "events": {
                "gold_expected": len(expected_events),
                "gold_matched": len(event_matches),
                "gold_recall": round(
                    len(event_matches) / len(expected_events), 3
                )
                if expected_events
                else None,
                "missing_gold": missing_events,
                "additional_output": additional_events,
                "matches": [asdict(match) for match in event_matches],
            },
            "claims": {
                "gold_expected": len(expected_claims),
                "gold_matched": claim_result.matched,
                "gold_recall": round(
                    claim_result.matched / len(expected_claims), 3
                )
                if expected_claims
                else None,
                "direct_matched": claim_result.direct_matched,
                "composite_matched": claim_result.composite_matched,
                "missing_gold_evidence": list(claim_result.missing),
                "additional_output_evidence": list(claim_result.additional),
                "composite_matches": [
                    asdict(match) for match in claim_result.composite_matches
                ],
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
            "entities": len(_items(bundle, "entities")),
            "events": len(_items(bundle, "events")),
            "claims": len(_items(bundle, "claims")),
            "warnings": len(bundle.get("warnings") or [])
            if isinstance(bundle.get("warnings"), list)
            else 0,
        },
    }
