"""Source-grounded additions-only coverage review for Chronicle model-v0."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from model_v0 import ModelProvider, ModelV0Error, parse_model_response


def coverage_units(raw: str) -> list[dict[str, str]]:
    """Build a deterministic textual-order checklist from source clauses."""
    parts = re.split(r"[，。；！？\n]+", raw)
    units: list[dict[str, str]] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        units.append({"unit_id": f"u{len(units) + 1:03d}", "text": text})
    return units


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
    units_text = json.dumps(coverage_units(raw), ensure_ascii=False, indent=2)
    return f"""You are Chronicle coverage-v0.2, a closed-book coverage reviewer.

Your task is NOT to reinterpret history and NOT to rewrite PASS-1 data.
Audit every AUDIT UNIT against PASS-1 STAGED BUNDLE and return only
source-supported additions that are genuinely missing from pass 1.

NON-NEGOTIABLE RULES
1. Use only SOURCE TEXT plus explicit DOCUMENT CONTEXT. Never add background historical knowledge.
2. Do not optimize toward any external reference answer. None is provided.
3. PASS-1 records are immutable. Never repeat, delete, rename, merge, rephrase, or replace an existing record.
4. Entity presence alone NEVER proves that an action/state transition is covered.
5. For an explicit action/state transition to be `covered`, cite at least one existing PASS-1 Event or Claim
   that semantically represents that action/state transition. Entity-only refs are insufficient.
6. If an AUDIT UNIT contains an explicit historically meaningful action/state transition that lacks adequate
   Event/Claim coverage, mark it `gap` and add the minimum missing records needed.
7. `context_only` is only for a unit that carries chronology/topic/context and contains no historical action,
   state transition, relationship assertion, appointment, death, succession, surrender, attack, movement,
   battle/outcome, epidemic/effect, territorial change, or comparable assertion.
8. Every added Claim.evidence.text must be an exact SOURCE TEXT substring.
9. Use only canonical Claim predicates allowed by INGESTION POLICY. Do not emit configured aliases.
10. Preserve traditional/regnal time expressions and never fabricate Gregorian month/day precision.
11. Keep entity/event resolution deferred; do not invent canonical UUIDs.
12. Existing temp IDs may be referenced exactly as they appear in PASS-1 STAGED BUNDLE.
13. New records must use job-local provisional temp IDs with the normal ent_/evt_/clm_ prefixes.
14. Return one JSON object only with exactly five arrays: audit, entities, events, claims, warnings.
15. Zero additions is valid only when every non-context audit unit is `covered` by specific PASS-1 Event/Claim refs.

OUTPUT PATCH SHAPE
{{
  "audit": [
    {{
      "unit_id": "u001",
      "status": "covered | gap | context_only",
      "pass1_refs": ["evt_...", "clm_..."],
      "addition_refs": ["evt_...", "clm_..."],
      "note": "brief source-grounded coverage reason"
    }}
  ],
  "entities": [/* only missing Entity records */],
  "events": [/* only missing Event records */],
  "claims": [/* only missing Claim records */],
  "warnings": [/* only new warnings caused by additions */]
}}

AUDIT REQUIREMENTS
- Return exactly one audit row for every AUDIT UNIT, in the same order.
- `covered`: pass1_refs must contain at least one existing evt_ or clm_ ID.
- `gap`: addition_refs must contain at least one new ent_/evt_/clm_ ID returned in this same patch.
- `context_only`: both ref arrays must be empty.
- Do not cite an Entity alone as proof that an action is covered.
- One source unit may need multiple additions, and one addition may cover multiple closely related units.

The individual Entity/Event/Claim/Warning objects must conform to the corresponding
object definitions in OUTPUT JSON SCHEMA. Do not return source or schema_version.

DOCUMENT CONTEXT
{context_text}

INGESTION POLICY
{config_text}

OUTPUT JSON SCHEMA
{schema_text}

AUDIT UNITS (MACHINE-DERIVED, TEXTUAL ORDER)
{units_text}

PASS-1 STAGED BUNDLE (IMMUTABLE)
{initial_text}

SOURCE TEXT
---BEGIN SOURCE---
{raw}
---END SOURCE---
"""


def _identity(item: dict[str, Any]) -> str | None:
    value = item.get("temp_id") or item.get("id")
    return str(value) if value is not None else None


def _all_ids(items: list[dict[str, Any]]) -> set[str]:
    return {
        identity
        for item in items
        if isinstance(item, dict) and (identity := _identity(item))
    }


def parse_coverage_response(
    text: str,
    raw: str,
    initial_bundle: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    value = parse_model_response(text)
    allowed = {"audit", "entities", "events", "claims", "warnings"}
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ModelV0Error(
            "coverage response must use the audit+additions protocol; unexpected key(s): "
            + ", ".join(unexpected)
        )

    audit = value.get("audit")
    if not isinstance(audit, list) or any(not isinstance(item, dict) for item in audit):
        raise ModelV0Error("coverage response field 'audit' must be an array of objects")

    additions: dict[str, list[dict[str, Any]]] = {}
    for name in ("entities", "events", "claims", "warnings"):
        items = value.get(name, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ModelV0Error(f"coverage response field {name!r} must be an array of objects")
        additions[name] = items

    expected_units = coverage_units(raw)
    expected_ids = [item["unit_id"] for item in expected_units]
    actual_ids = [str(item.get("unit_id") or "") for item in audit]
    if actual_ids != expected_ids:
        raise ModelV0Error(
            "coverage audit must contain every machine-derived unit exactly once and in order"
        )

    pass1_event_ids = _all_ids(
        [item for item in initial_bundle.get("events", []) if isinstance(item, dict)]
    )
    pass1_claim_ids = _all_ids(
        [item for item in initial_bundle.get("claims", []) if isinstance(item, dict)]
    )
    valid_coverage_refs = pass1_event_ids | pass1_claim_ids

    added_ids = (
        _all_ids(additions["entities"])
        | _all_ids(additions["events"])
        | _all_ids(additions["claims"])
    )

    for row in audit:
        unit_id = str(row.get("unit_id"))
        status = row.get("status")
        pass1_refs = row.get("pass1_refs", [])
        addition_refs = row.get("addition_refs", [])
        note = row.get("note")
        if status not in {"covered", "gap", "context_only"}:
            raise ModelV0Error(f"{unit_id} has invalid coverage status: {status!r}")
        if not isinstance(pass1_refs, list) or any(not isinstance(ref, str) for ref in pass1_refs):
            raise ModelV0Error(f"{unit_id}.pass1_refs must be an array of strings")
        if not isinstance(addition_refs, list) or any(
            not isinstance(ref, str) for ref in addition_refs
        ):
            raise ModelV0Error(f"{unit_id}.addition_refs must be an array of strings")
        if not isinstance(note, str) or not note.strip():
            raise ModelV0Error(f"{unit_id}.note must be a non-empty string")

        if status == "covered":
            if not pass1_refs:
                raise ModelV0Error(
                    f"{unit_id} is covered but cites no PASS-1 Event/Claim"
                )
            invalid = sorted(set(pass1_refs) - valid_coverage_refs)
            if invalid:
                raise ModelV0Error(
                    f"{unit_id} covered refs must be existing PASS-1 Event/Claim IDs: "
                    + ", ".join(invalid)
                )
            if addition_refs:
                raise ModelV0Error(f"{unit_id} is covered but also cites additions")
        elif status == "gap":
            if not addition_refs:
                raise ModelV0Error(f"{unit_id} is gap but cites no addition")
            invalid = sorted(set(addition_refs) - added_ids)
            if invalid:
                raise ModelV0Error(
                    f"{unit_id} gap refs must point to additions returned in the same patch: "
                    + ", ".join(invalid)
                )
        else:
            if pass1_refs or addition_refs:
                raise ModelV0Error(
                    f"{unit_id} is context_only and must not cite coverage/addition refs"
                )

    return audit, additions


def parse_coverage_additions(text: str) -> dict[str, list[dict[str, Any]]]:
    """Legacy parser retained only for tests/debugging of raw patch shape."""
    value = parse_model_response(text)
    allowed = {"entities", "events", "claims", "warnings"}
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ModelV0Error(
            "legacy coverage additions parser received unexpected key(s): "
            + ", ".join(unexpected)
        )
    result: dict[str, list[dict[str, Any]]] = {}
    for name in ("entities", "events", "claims", "warnings"):
        items = value.get(name, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ModelV0Error(f"coverage response field {name!r} must be an array of objects")
        result[name] = items
    return result


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
        "protocol": "audit+additions-only",
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


def audit_summary(audit: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"covered": 0, "gap": 0, "context_only": 0}
    gap_units: list[str] = []
    for row in audit:
        status = str(row.get("status"))
        if status in counts:
            counts[status] += 1
        if status == "gap":
            gap_units.append(str(row.get("unit_id")))
    return {
        "units": len(audit),
        "status_counts": counts,
        "gap_units": gap_units,
    }


class CoverageV02Extractor:
    """Run one provider-backed audit+additions review over an existing staged bundle."""

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
        self.last_response: str | None = None
        self.last_audit: list[dict[str, Any]] = []

    def prompt(self, initial_bundle: dict[str, Any]) -> str:
        return build_coverage_prompt(
            self.raw, self.context, self.config, self.schema, initial_bundle
        )

    def review(
        self, initial_bundle: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        response = self.provider.complete(self.prompt(initial_bundle))
        self.last_response = response
        audit, additions = parse_coverage_response(response, self.raw, initial_bundle)
        self.last_audit = audit
        result, stats = merge_coverage_additions(initial_bundle, additions, self.config)
        stats["audit"] = audit_summary(audit)
        return result, stats


def object_counts(bundle: dict[str, Any]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for name in ("entities", "events", "claims", "warnings"):
        value = bundle.get(name)
        counts[name] = len(value) if isinstance(value, list) else None
    return counts
