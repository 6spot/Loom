"""Source-grounded additions-only coverage review for Chronicle model-v0."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from model_v0 import ModelProvider, ModelV0Error, parse_model_response


def build_coverage_prompt(
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
    initial_bundle: dict[str, Any],
) -> str:
    context_text = json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
    config_text = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True)
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
    initial_text = json.dumps(initial_bundle, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""You are Chronicle coverage-v0.2, a closed-book coverage reviewer.

Your task is NOT to reinterpret history and NOT to rewrite PASS-1 data.
Audit SOURCE TEXT sentence-by-sentence against PASS-1 STAGED BUNDLE and return
ONLY source-supported additions that are missing from pass 1.

NON-NEGOTIABLE RULES
1. Use only SOURCE TEXT plus explicit DOCUMENT CONTEXT. Never add background historical knowledge.
2. Do not optimize toward any external reference answer. None is provided.
3. PASS-1 records are immutable. Never repeat, delete, rename, merge, rephrase, or replace an existing record.
4. For every explicit action, state transition, appointment, death, succession, surrender, attack,
   movement, battle/outcome, epidemic/effect, territorial change, or other historically meaningful
   assertion in SOURCE TEXT, check whether pass 1 already contains adequate Entity/Event/Claim coverage.
5. Return an addition only when pass 1 lacks that information.
6. Every added Claim.evidence.text must be an exact SOURCE TEXT substring.
7. Use only canonical Claim predicates allowed by INGESTION POLICY. Do not emit configured aliases.
8. Preserve traditional/regnal time expressions and never fabricate Gregorian month/day precision.
9. Keep entity/event resolution deferred; do not invent canonical UUIDs.
10. Existing temp IDs may be referenced exactly as they appear in PASS-1 STAGED BUNDLE.
11. New records must use job-local provisional temp IDs with the normal ent_/evt_/clm_ prefixes.
12. Return one JSON object only with exactly these four arrays: entities, events, claims, warnings.

OUTPUT PATCH SHAPE
{{
  "entities": [/* only missing Entity records */],
  "events": [/* only missing Event records */],
  "claims": [/* only missing Claim records */],
  "warnings": [/* only new warnings caused by additions */]
}}

The individual Entity/Event/Claim/Warning objects must conform to the corresponding
object definitions in OUTPUT JSON SCHEMA. Do not return source or schema_version.

COVERAGE AUDIT METHOD
- Walk the source in textual order.
- Identify each explicit historically meaningful action or state change.
- First ask whether pass 1 already covers it semantically, even if titles/evidence spans differ.
- Only when it is genuinely missing, add the minimum Entity/Event/Claim records needed.
- Prefer atomic claims.
- Extra source-grounded detail is acceptable only when it fills an actual pass-1 gap.

DOCUMENT CONTEXT
{context_text}

INGESTION POLICY
{config_text}

OUTPUT JSON SCHEMA
{schema_text}

PASS-1 STAGED BUNDLE (IMMUTABLE)
{initial_text}

SOURCE TEXT
---BEGIN SOURCE---
{raw}
---END SOURCE---
"""


def parse_coverage_additions(text: str) -> dict[str, list[dict[str, Any]]]:
    value = parse_model_response(text)
    allowed = {"entities", "events", "claims", "warnings"}
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ModelV0Error(
            "coverage response must be additions-only; unexpected key(s): "
            + ", ".join(unexpected)
        )
    result: dict[str, list[dict[str, Any]]] = {}
    for name in ("entities", "events", "claims", "warnings"):
        items = value.get(name, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ModelV0Error(f"coverage response field {name!r} must be an array of objects")
        result[name] = items
    return result


def _identity(item: dict[str, Any]) -> str | None:
    value = item.get("temp_id") or item.get("id")
    return str(value) if value is not None else None


def _id_generator(items: list[dict[str, Any]], prefix: str):
    highest = 0
    for item in items:
        identity = _identity(item) or ""
        match = re.fullmatch(rf"{re.escape(prefix)}_(\d+)", identity)
        if match:
            highest = max(highest, int(match.group(1)))
    number = highest + 1
    while True:
        yield f"{prefix}_{number:03d}"
        number += 1


def _model_extraction(existing: Any) -> dict[str, Any]:
    confidence = existing.get("confidence") if isinstance(existing, dict) else None
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = None
    return {
        "method": "model",
        "job_id": "model-v0+coverage-v0.2",
        "confidence": confidence,
    }


def _time_key(value: Any) -> str:
    if not isinstance(value, dict):
        return "null"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    participants = tuple(
        sorted(
            (str(item.get("entity_ref")), str(item.get("role") or ""))
            for item in event.get("participants") or []
            if isinstance(item, dict)
        )
    )
    places = tuple(sorted(str(ref) for ref in event.get("places") or []))
    sparse_title = str(event.get("title") or "") if not participants and not places else ""
    return (
        event.get("type"),
        _time_key(event.get("time")),
        participants,
        places,
        sparse_title,
    )


def _ref_key(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    if value.get("kind") in {"entity_ref", "event_ref"}:
        return (value.get("kind"), str(value.get("ref")))
    if value.get("kind") == "literal":
        return ("literal", json.dumps(value.get("value"), ensure_ascii=False, sort_keys=True))
    return None


def _predicate_aliases(config: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(config, dict):
        return {}
    claim = config.get("claim") if isinstance(config.get("claim"), dict) else {}
    predicates = claim.get("predicates") if isinstance(claim.get("predicates"), dict) else {}
    aliases = predicates.get("aliases") if isinstance(predicates.get("aliases"), dict) else {}
    return {str(key): str(value) for key, value in aliases.items()}


def _claim_core_key(claim: dict[str, Any], aliases: dict[str, str]) -> tuple[Any, ...]:
    predicate = str(claim.get("predicate") or "")
    return (
        _ref_key(claim.get("subject")),
        aliases.get(predicate, predicate),
        _ref_key(claim.get("object")) if claim.get("object") is not None else None,
        _time_key(claim.get("time")),
    )


def _evidence_text(claim: dict[str, Any]) -> str:
    evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
    return str(evidence.get("text") or "")


def _claim_duplicate(
    candidate: dict[str, Any],
    existing: list[dict[str, Any]],
    aliases: dict[str, str],
) -> bool:
    core = _claim_core_key(candidate, aliases)
    evidence = _evidence_text(candidate)
    for item in existing:
        if _claim_core_key(item, aliases) != core:
            continue
        prior = _evidence_text(item)
        if evidence == prior or (evidence and prior and (evidence in prior or prior in evidence)):
            return True
    return False


def _rewrite_ref(ref: Any, entity_map: dict[str, str], event_map: dict[str, str]) -> Any:
    if not isinstance(ref, str):
        return ref
    return entity_map.get(ref, event_map.get(ref, ref))


def merge_coverage_additions(
    initial_bundle: dict[str, Any],
    additions: dict[str, list[dict[str, Any]]],
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge additions without modifying any existing pass-1 object."""

    result = copy.deepcopy(initial_bundle)
    result.setdefault("entities", [])
    result.setdefault("events", [])
    result.setdefault("claims", [])
    result.setdefault("warnings", [])

    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    source_id = _identity(source)
    entity_gen = _id_generator(result["entities"], "ent")
    event_gen = _id_generator(result["events"], "evt")
    claim_gen = _id_generator(result["claims"], "clm")

    entity_map: dict[str, str] = {}
    event_map: dict[str, str] = {}
    predicate_aliases = _predicate_aliases(config)
    stats = {
        "protocol": "additions-only",
        "proposed": {
            name: len(additions.get(name, []))
            for name in ("entities", "events", "claims", "warnings")
        },
        "added": {name: 0 for name in ("entities", "events", "claims", "warnings")},
        "skipped_duplicates": {
            name: 0 for name in ("entities", "events", "claims", "warnings")
        },
    }

    entity_by_key = {
        (str(item.get("type") or ""), str(item.get("canonical_name") or "")): _identity(item)
        for item in result["entities"]
        if isinstance(item, dict) and _identity(item)
    }
    for proposed in additions.get("entities", []):
        old_id = _identity(proposed)
        key = (
            str(proposed.get("type") or ""),
            str(proposed.get("canonical_name") or ""),
        )
        existing_id = entity_by_key.get(key)
        if existing_id:
            if old_id:
                entity_map[old_id] = existing_id
            stats["skipped_duplicates"]["entities"] += 1
            continue
        item = copy.deepcopy(proposed)
        new_id = next(entity_gen)
        if old_id:
            entity_map[old_id] = new_id
        item.pop("id", None)
        item["temp_id"] = new_id
        item["extraction"] = _model_extraction(item.get("extraction"))
        item.setdefault("resolution", {"status": "unresolved"})
        result["entities"].append(item)
        entity_by_key[key] = new_id
        stats["added"]["entities"] += 1

    existing_event_keys = {
        _event_key(item): _identity(item)
        for item in result["events"]
        if isinstance(item, dict) and _identity(item)
    }
    pending_events: list[dict[str, Any]] = []
    for proposed in additions.get("events", []):
        item = copy.deepcopy(proposed)
        old_id = _identity(item)
        for participant in item.get("participants") or []:
            if isinstance(participant, dict):
                participant["entity_ref"] = _rewrite_ref(
                    participant.get("entity_ref"), entity_map, event_map
                )
        item["places"] = [
            _rewrite_ref(ref, entity_map, event_map) for ref in item.get("places") or []
        ]
        key = _event_key(item)
        existing_id = existing_event_keys.get(key)
        if existing_id:
            if old_id:
                event_map[old_id] = existing_id
            stats["skipped_duplicates"]["events"] += 1
            continue
        new_id = next(event_gen)
        if old_id:
            event_map[old_id] = new_id
        item.pop("id", None)
        item["temp_id"] = new_id
        item["extraction"] = _model_extraction(item.get("extraction"))
        pending_events.append(item)
        existing_event_keys[key] = new_id
        stats["added"]["events"] += 1

    for item in pending_events:
        if item.get("parent_event_ref") is not None:
            item["parent_event_ref"] = _rewrite_ref(
                item.get("parent_event_ref"), entity_map, event_map
            )
        result["events"].append(item)

    existing_claims = [item for item in result["claims"] if isinstance(item, dict)]
    for proposed in additions.get("claims", []):
        item = copy.deepcopy(proposed)
        for field in ("subject", "object"):
            ref = item.get(field)
            if isinstance(ref, dict) and ref.get("kind") in {"entity_ref", "event_ref"}:
                ref["ref"] = _rewrite_ref(ref.get("ref"), entity_map, event_map)
        evidence = item.get("evidence")
        if isinstance(evidence, dict) and source_id is not None and not evidence.get("source_ref"):
            evidence["source_ref"] = source_id
        if _claim_duplicate(item, existing_claims, predicate_aliases):
            stats["skipped_duplicates"]["claims"] += 1
            continue
        item.pop("id", None)
        item["temp_id"] = next(claim_gen)
        item["extraction"] = _model_extraction(item.get("extraction"))
        item.setdefault("assessment", {"status": "unassessed"})
        result["claims"].append(item)
        existing_claims.append(item)
        stats["added"]["claims"] += 1

    warning_keys = {
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in result["warnings"]
        if isinstance(item, dict)
    }
    for proposed in additions.get("warnings", []):
        item = copy.deepcopy(proposed)
        if isinstance(item.get("refs"), list):
            item["refs"] = [
                _rewrite_ref(ref, entity_map, event_map) for ref in item["refs"]
            ]
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key in warning_keys:
            stats["skipped_duplicates"]["warnings"] += 1
            continue
        result["warnings"].append(item)
        warning_keys.add(key)
        stats["added"]["warnings"] += 1

    return result, stats


class CoverageV02Extractor:
    """Run one provider-backed additions-only review over an existing staged bundle."""

    def __init__(
        self,
        raw: str,
        context: dict[str, Any],
        config: dict[str, Any],
        schema: dict[str, Any],
        fixture_name: str,
        provider: ModelProvider,
    ):
        self.raw = raw
        self.context = context
        self.config = config
        self.schema = schema
        self.fixture_name = fixture_name
        self.provider = provider

    def prompt(self, initial_bundle: dict[str, Any]) -> str:
        return build_coverage_prompt(
            self.raw, self.context, self.config, self.schema, initial_bundle
        )

    def review(
        self, initial_bundle: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        response = self.provider.complete(self.prompt(initial_bundle))
        additions = parse_coverage_additions(response)
        return merge_coverage_additions(initial_bundle, additions, self.config)


def object_counts(bundle: dict[str, Any]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for name in ("entities", "events", "claims", "warnings"):
        value = bundle.get(name)
        counts[name] = len(value) if isinstance(value, list) else None
    return counts
