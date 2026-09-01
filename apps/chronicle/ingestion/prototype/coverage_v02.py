"""Source-grounded audit+additions coverage review for Chronicle model-v0."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from model_v0 import ModelProvider, ModelV0Error, parse_model_response


_AUDIT_STATUSES = {"covered", "gap", "context_only"}
_CLAIM_STATUSES = {"covered", "gap", "not_applicable"}
_COLLECTIONS = ("entities", "events", "claims", "warnings")
_CN_MONTH_VALUES = {
    "正": 1,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}
_MONTH_RE = re.compile(
    r"(?P<marker>(?:春|夏|秋|冬)?(?:闰)?(?P<month>正|十一|十二|十|[一二三四五六七八九])月)"
)


def coverage_units(raw: str) -> list[dict[str, str]]:
    """Build a deterministic textual-order checklist from source clauses."""
    parts = re.split(r"[，。；！？\n]+", raw)
    units: list[dict[str, str]] = []
    for part in parts:
        text = part.strip()
        if text:
            units.append({"unit_id": f"u{len(units) + 1:03d}", "text": text})
    return units


def coverage_unit_contexts(raw: str) -> dict[str, dict[str, Any]]:
    """Derive only explicit/inherited source-month hints; never Gregorian dates."""
    contexts: dict[str, dict[str, Any]] = {}
    current_month: int | None = None
    current_marker: str | None = None
    for unit in coverage_units(raw):
        match = _MONTH_RE.search(unit["text"])
        if match:
            current_month = _CN_MONTH_VALUES[match.group("month")]
            current_marker = match.group("marker")
        contexts[unit["unit_id"]] = {
            "source_month_hint": current_month,
            "source_month_marker": current_marker,
        }
    return contexts


def _audit_units_for_prompt(raw: str) -> list[dict[str, Any]]:
    contexts = coverage_unit_contexts(raw)
    result: list[dict[str, Any]] = []
    for unit in coverage_units(raw):
        row: dict[str, Any] = dict(unit)
        context = contexts[unit["unit_id"]]
        if context["source_month_hint"] is not None:
            row.update(context)
        result.append(row)
    return result


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
    units_text = json.dumps(_audit_units_for_prompt(raw), ensure_ascii=False, indent=2)
    return f"""You are Chronicle coverage-v0.2, a closed-book coverage reviewer.

Your task is NOT to reinterpret history and NOT to rewrite PASS-1 data.
Audit every AUDIT UNIT against PASS-1 STAGED BUNDLE and return only
source-supported additions that are genuinely missing from pass 1.

NON-NEGOTIABLE RULES
1. Use only SOURCE TEXT plus explicit DOCUMENT CONTEXT. Never add background historical knowledge.
2. Do not optimize toward any external reference answer. None is provided.
3. PASS-1 records are immutable. Never repeat, delete, rename, merge, rephrase, or replace an existing record.
4. Entity presence alone NEVER proves that an action/state transition/assertion is covered.
5. Event coverage and Claim coverage are DIFFERENT. An Event never substitutes for a Claim.
6. Every non-context factual unit must receive an explicit Claim coverage decision.
7. If an allowed canonical predicate can faithfully express the source assertion, Claim coverage is required:
   - office/appointment: held_office or appointed
   - death: died
   - succession: succeeded
   - surrender: surrendered_to
   - attack: attacked
   - battle/fighting/outcome: fought or outcome
   - epidemic/effect: affected
   - territory acquisition: gained_territory
   - movement/stationing/return/retreat: moved_to, stationed_at, returned_to, or retreated
   - sending forces/support: sent_forces or supported
   - creation/abolition: created or abolished
8. claim_status may be `not_applicable` only when NO allowed canonical predicate can faithfully express the unit.
   claim_note must state that ontology limitation. Do not use not_applicable merely to avoid adding a Claim.
9. For an explicit occurrence/state transition to be overall `covered`, cite an existing PASS-1 Event or Claim
   that semantically represents it. Entity-only refs are insufficient.
10. If either Event coverage or required Claim coverage is missing, overall status must be `gap` and the patch
    must add the minimum missing records.
11. Every added Claim.evidence.text must be an exact SOURCE TEXT substring.
12. Use only canonical Claim predicates allowed by INGESTION POLICY. Do not emit configured aliases.
13. AUDIT UNIT source_month_hint is a literal source-calendar inheritance hint, not a Gregorian conversion.
    Any added Event/Claim tied to that unit must preserve the same chinese_lunisolar_regnal source month.
    Its normalized Gregorian month/day must remain null unless a verified converter exists.
14. Keep entity/event resolution deferred; do not invent canonical UUIDs.
15. Existing temp IDs may be referenced exactly as they appear in PASS-1 STAGED BUNDLE.
16. New records must use job-local provisional temp IDs with the normal ent_/evt_/clm_ prefixes.
17. Return one JSON object only with exactly five arrays: audit, entities, events, claims, warnings.
18. Zero additions is valid only when every non-context audit unit proves both overall coverage and required
    Claim coverage with specific PASS-1 refs.

OUTPUT PATCH SHAPE
{{
  "audit": [
    {{
      "unit_id": "u001",
      "status": "covered | gap | context_only",
      "pass1_refs": ["evt_...", "clm_..."],
      "addition_refs": ["evt_...", "clm_..."],
      "claim_status": "covered | gap | not_applicable",
      "claim_refs": ["clm_..."],
      "claim_note": "why Claim is covered/missing/not representable",
      "note": "brief source-grounded overall coverage reason"
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
- `context_only`: both overall ref arrays must be empty and claim_status must be not_applicable.
- claim_status `covered`: claim_refs must cite existing PASS-1 clm_ IDs.
- claim_status `gap`: claim_refs must cite new clm_ IDs returned in this same patch; overall status must be gap.
- claim_status `not_applicable`: claim_refs must be empty and claim_note must explain why no allowed predicate fits.
- Do not cite an Entity alone as proof that an action/assertion is covered.
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


def _validate_audit_month_grounding(
    audit: list[dict[str, Any]],
    additions: dict[str, list[dict[str, Any]]],
    raw: str,
) -> None:
    contexts = coverage_unit_contexts(raw)
    refs_to_months: dict[str, set[int]] = {}
    for row in audit:
        month = contexts[str(row.get("unit_id"))]["source_month_hint"]
        if month is None:
            continue
        for ref in row.get("addition_refs", []):
            refs_to_months.setdefault(str(ref), set()).add(int(month))
        for ref in row.get("claim_refs", []):
            if str(row.get("claim_status")) == "gap":
                refs_to_months.setdefault(str(ref), set()).add(int(month))

    for collection in ("events", "claims"):
        for item in additions[collection]:
            identity = _identity(item)
            if not identity or identity not in refs_to_months:
                continue
            months = refs_to_months[identity]
            if len(months) != 1:
                raise ModelV0Error(
                    f"coverage addition {identity} spans conflicting source-month hints: {sorted(months)}"
                )
            expected_month = next(iter(months))
            time = item.get("time")
            source_calendar = (
                time.get("source_calendar")
                if isinstance(time, dict) and isinstance(time.get("source_calendar"), dict)
                else None
            )
            if not isinstance(source_calendar, dict):
                raise ModelV0Error(
                    f"coverage addition {identity} must preserve source month {expected_month}"
                )
            if source_calendar.get("system") != "chinese_lunisolar_regnal":
                raise ModelV0Error(
                    f"coverage addition {identity} must use chinese_lunisolar_regnal source calendar"
                )
            actual_month = source_calendar.get("month")
            if actual_month != expected_month:
                raise ModelV0Error(
                    f"coverage addition {identity} source month mismatch: expected {expected_month}, got {actual_month!r}"
                )


def parse_coverage_response(
    text: str,
    raw: str,
    initial_bundle: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    value = parse_model_response(text)
    allowed = {"audit", *_COLLECTIONS}
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
    for name in _COLLECTIONS:
        items = value.get(name, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ModelV0Error(f"coverage response field {name!r} must be an array of objects")
        additions[name] = items

    expected_ids = [item["unit_id"] for item in coverage_units(raw)]
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
    added_entity_ids = _all_ids(additions["entities"])
    added_event_ids = _all_ids(additions["events"])
    added_claim_ids = _all_ids(additions["claims"])
    added_ids = added_entity_ids | added_event_ids | added_claim_ids

    for row in audit:
        unit_id = str(row.get("unit_id"))
        status = row.get("status")
        pass1_refs = row.get("pass1_refs", [])
        addition_refs = row.get("addition_refs", [])
        claim_status = row.get("claim_status")
        claim_refs = row.get("claim_refs", [])
        note = row.get("note")
        claim_note = row.get("claim_note")

        if status not in _AUDIT_STATUSES:
            raise ModelV0Error(f"{unit_id} has invalid coverage status: {status!r}")
        if claim_status not in _CLAIM_STATUSES:
            raise ModelV0Error(f"{unit_id} has invalid claim_status: {claim_status!r}")
        for field_name, refs in (
            ("pass1_refs", pass1_refs),
            ("addition_refs", addition_refs),
            ("claim_refs", claim_refs),
        ):
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ModelV0Error(f"{unit_id}.{field_name} must be an array of strings")
        if not isinstance(note, str) or not note.strip():
            raise ModelV0Error(f"{unit_id}.note must be a non-empty string")
        if not isinstance(claim_note, str) or not claim_note.strip():
            raise ModelV0Error(f"{unit_id}.claim_note must be a non-empty string")

        if status == "covered":
            if not pass1_refs:
                raise ModelV0Error(f"{unit_id} is covered but cites no PASS-1 Event/Claim")
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
            if claim_status != "not_applicable" or claim_refs:
                raise ModelV0Error(
                    f"{unit_id} is context_only and Claim coverage must be not_applicable with no refs"
                )

        if claim_status == "covered":
            if not claim_refs:
                raise ModelV0Error(f"{unit_id} Claim is covered but cites no PASS-1 Claim")
            invalid = sorted(set(claim_refs) - pass1_claim_ids)
            if invalid:
                raise ModelV0Error(
                    f"{unit_id} covered Claim refs must be existing PASS-1 Claim IDs: "
                    + ", ".join(invalid)
                )
        elif claim_status == "gap":
            if status != "gap":
                raise ModelV0Error(f"{unit_id} has Claim gap but overall status is not gap")
            if not claim_refs:
                raise ModelV0Error(f"{unit_id} Claim is gap but cites no new Claim")
            invalid = sorted(set(claim_refs) - added_claim_ids)
            if invalid:
                raise ModelV0Error(
                    f"{unit_id} Claim gap refs must point to new Claim IDs: "
                    + ", ".join(invalid)
                )
            if not set(claim_refs) <= set(addition_refs):
                raise ModelV0Error(
                    f"{unit_id} Claim gap refs must also appear in overall addition_refs"
                )
        else:
            if claim_refs:
                raise ModelV0Error(f"{unit_id} Claim is not_applicable but cites Claim refs")

    _validate_audit_month_grounding(audit, additions, raw)
    return audit, additions


def parse_coverage_additions(text: str) -> dict[str, list[dict[str, Any]]]:
    """Legacy parser retained only for tests/debugging of raw patch shape."""
    value = parse_model_response(text)
    allowed = set(_COLLECTIONS)
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ModelV0Error(
            "legacy coverage additions parser received unexpected key(s): "
            + ", ".join(unexpected)
        )
    result: dict[str, list[dict[str, Any]]] = {}
    for name in _COLLECTIONS:
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
            (str(item.get("entity_ref")), str(item.get("role") or "").strip())
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
    for name in _COLLECTIONS:
        result.setdefault(name, [])

    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    source_id = _identity(source)
    entity_gen = _id_generator(result["entities"], "ent")
    event_gen = _id_generator(result["events"], "evt")
    claim_gen = _id_generator(result["claims"], "clm")
    entity_map: dict[str, str] = {}
    event_map: dict[str, str] = {}
    predicate_aliases = _predicate_aliases(config)
    stats = {
        "protocol": "audit+claim-coverage+additions-only",
        "proposed": {name: len(additions.get(name, [])) for name in _COLLECTIONS},
        "added": {name: 0 for name in _COLLECTIONS},
        "skipped_duplicates": {name: 0 for name in _COLLECTIONS},
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
                if isinstance(participant.get("role"), str):
                    participant["role"] = participant["role"].strip()
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
    status_counts = {status: 0 for status in ("covered", "gap", "context_only")}
    claim_counts = {status: 0 for status in ("covered", "gap", "not_applicable")}
    gap_units: list[str] = []
    claim_gap_units: list[str] = []
    for row in audit:
        status = str(row.get("status"))
        claim_status = str(row.get("claim_status"))
        if status in status_counts:
            status_counts[status] += 1
        if claim_status in claim_counts:
            claim_counts[claim_status] += 1
        if status == "gap":
            gap_units.append(str(row.get("unit_id")))
        if claim_status == "gap":
            claim_gap_units.append(str(row.get("unit_id")))
    return {
        "units": len(audit),
        "status_counts": status_counts,
        "gap_units": gap_units,
        "claim_status_counts": claim_counts,
        "claim_gap_units": claim_gap_units,
    }


class CoverageV02Extractor:
    """Run one provider-backed claim-aware audit+additions review."""

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
    for name in _COLLECTIONS:
        value = bundle.get(name)
        counts[name] = len(value) if isinstance(value, list) else None
    return counts
