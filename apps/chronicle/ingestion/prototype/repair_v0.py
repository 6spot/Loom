"""Bounded validator-driven patch repair for Chronicle contract-first ingestion."""

from __future__ import annotations

import copy
import json
from typing import Any

from model_v0 import ModelProvider, ModelV0Error, parse_model_response

_REPLACE_COLLECTIONS = {"source", "entities", "events", "claims"}
_ADD_COLLECTIONS = ("entities", "events", "claims", "warnings")


def build_repair_prompt(
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
    bundle: dict[str, Any],
    validation_errors: list[str],
) -> str:
    """Build a closed-book, patch-only repair prompt from validator errors."""
    return f"""You are Chronicle repair-v0.2.

Correct ONLY the mechanically validated errors listed below.
Do not return a complete staged bundle. Return a minimal repair patch only.
Do not perform a new extraction or coverage review. Do not add unrelated historical facts. Do not optimize toward any human gold/reference answer.
Use only SOURCE TEXT, DOCUMENT CONTEXT, INGESTION POLICY, OUTPUT JSON SCHEMA, CURRENT STAGED BUNDLE, and VALIDATION ERRORS in this prompt.

REPAIR SAFETY RULES
1. CURRENT STAGED BUNDLE is immutable except for records explicitly named in `replace`.
2. Never delete an existing Source, Entity, Event, or Claim.
3. Replace only records directly implicated by VALIDATION ERRORS, and preserve their existing temp_id.
4. Add a new Entity/Event/Claim only when a listed validation error cannot be fixed by correcting an existing record. Use a new non-colliding temp_id.
5. Do not change Event/Claim granularity, historical meaning, time, predicate semantics, or unrelated fields unless a listed validation error requires that exact change.
6. Every Claim evidence must remain an exact SOURCE TEXT substring. Never invent Gregorian month/day precision.
7. If a repair makes an existing warning false or stale, list its exact current message in `remove_warning_messages`. Add a replacement warning only when it is still genuinely needed.
8. Do not create warnings merely to hide validation errors.
9. Return exactly one JSON object with keys `replace`, `add`, and `remove_warning_messages`.

PATCH SHAPE
{{
  "replace": [
    {{
      "collection": "source | entities | events | claims",
      "temp_id": "existing temp id; omit only for source",
      "record": {{"complete corrected record": "..."}}
    }}
  ],
  "add": {{
    "entities": [],
    "events": [],
    "claims": [],
    "warnings": []
  }},
  "remove_warning_messages": ["exact existing warning message"]
}}

VALIDATION ERRORS
{json.dumps(validation_errors, ensure_ascii=False, indent=2)}

DOCUMENT CONTEXT
{json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)}

INGESTION POLICY
{json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True)}

OUTPUT JSON SCHEMA
{json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)}

CURRENT STAGED BUNDLE
{json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True)}

SOURCE TEXT
---BEGIN SOURCE---
{raw}
---END SOURCE---
"""


def _identity(record: dict[str, Any]) -> str | None:
    value = record.get("temp_id") or record.get("id")
    return str(value) if value is not None else None


def _parse_patch(text: str) -> dict[str, Any]:
    patch = parse_model_response(text)
    expected_keys = {"replace", "add", "remove_warning_messages"}
    if set(patch) != expected_keys:
        raise ModelV0Error(
            "repair response must contain exactly replace, add, and remove_warning_messages"
        )
    if not isinstance(patch["replace"], list):
        raise ModelV0Error("repair replace must be an array")
    if not isinstance(patch["add"], dict) or set(patch["add"]) != set(_ADD_COLLECTIONS):
        raise ModelV0Error(
            "repair add must contain exactly entities, events, claims, and warnings arrays"
        )
    for collection in _ADD_COLLECTIONS:
        if not isinstance(patch["add"][collection], list):
            raise ModelV0Error(f"repair add.{collection} must be an array")
    if not isinstance(patch["remove_warning_messages"], list) or not all(
        isinstance(value, str) for value in patch["remove_warning_messages"]
    ):
        raise ModelV0Error("repair remove_warning_messages must be an array of strings")
    return patch


def apply_repair_patch(
    bundle: dict[str, Any], patch: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a repair patch without allowing deletion or implicit bundle rewrite."""
    result = copy.deepcopy(bundle)
    replaced = {collection: 0 for collection in _REPLACE_COLLECTIONS}
    added = {collection: 0 for collection in _ADD_COLLECTIONS}

    existing_ids: set[str] = set()
    source = result.get("source")
    if isinstance(source, dict) and (source_id := _identity(source)):
        existing_ids.add(source_id)
    for collection in ("entities", "events", "claims"):
        for record in result.get(collection) or []:
            if isinstance(record, dict) and (identity := _identity(record)):
                if identity in existing_ids:
                    raise ModelV0Error(f"duplicate existing identity in staged bundle: {identity}")
                existing_ids.add(identity)

    seen_targets: set[tuple[str, str]] = set()
    for change in patch["replace"]:
        if not isinstance(change, dict):
            raise ModelV0Error("repair replace entries must be objects")
        collection = change.get("collection")
        record = change.get("record")
        if collection not in _REPLACE_COLLECTIONS or not isinstance(record, dict):
            raise ModelV0Error("repair replace entry has invalid collection or record")

        if collection == "source":
            current = result.get("source")
            if not isinstance(current, dict):
                raise ModelV0Error("repair cannot replace missing source")
            target_id = _identity(current)
            record_id = _identity(record)
            if not target_id or record_id != target_id:
                raise ModelV0Error("repair source replacement must preserve source identity")
            target_key = ("source", target_id)
            if target_key in seen_targets:
                raise ModelV0Error("repair patch replaces source more than once")
            seen_targets.add(target_key)
            result["source"] = copy.deepcopy(record)
            replaced["source"] += 1
            continue

        target_id = change.get("temp_id")
        if not isinstance(target_id, str) or not target_id:
            raise ModelV0Error(f"repair replacement for {collection} requires temp_id")
        if _identity(record) != target_id:
            raise ModelV0Error(
                f"repair replacement {target_id} must preserve its existing identity"
            )
        target_key = (str(collection), target_id)
        if target_key in seen_targets:
            raise ModelV0Error(f"repair patch replaces {target_id} more than once")
        seen_targets.add(target_key)

        records = result.get(collection)
        if not isinstance(records, list):
            raise ModelV0Error(f"repair cannot replace record in missing {collection}")
        matches = [
            index
            for index, current in enumerate(records)
            if isinstance(current, dict) and _identity(current) == target_id
        ]
        if len(matches) != 1:
            raise ModelV0Error(
                f"repair replacement target {target_id} must identify exactly one existing record"
            )
        records[matches[0]] = copy.deepcopy(record)
        replaced[str(collection)] += 1

    for collection in ("entities", "events", "claims"):
        records = result.get(collection)
        if not isinstance(records, list):
            raise ModelV0Error(f"staged bundle {collection} must be an array")
        for record in patch["add"][collection]:
            if not isinstance(record, dict):
                raise ModelV0Error(f"repair add.{collection} entries must be objects")
            identity = _identity(record)
            if not identity or not str(record.get("temp_id") or "").strip():
                raise ModelV0Error(
                    f"repair add.{collection} record requires a new temp_id"
                )
            if identity in existing_ids:
                raise ModelV0Error(f"repair addition reuses existing identity {identity}")
            existing_ids.add(identity)
            records.append(copy.deepcopy(record))
            added[collection] += 1

    warnings = result.get("warnings")
    if not isinstance(warnings, list):
        raise ModelV0Error("staged bundle warnings must be an array")
    remove_messages = set(patch["remove_warning_messages"])
    available_messages = {
        str(warning.get("message"))
        for warning in warnings
        if isinstance(warning, dict) and warning.get("message") is not None
    }
    unknown_removals = sorted(remove_messages - available_messages)
    if unknown_removals:
        raise ModelV0Error(
            "repair tried to remove unknown warning message(s): " + "; ".join(unknown_removals)
        )
    before_warning_count = len(warnings)
    result["warnings"] = [
        warning
        for warning in warnings
        if not (
            isinstance(warning, dict)
            and str(warning.get("message")) in remove_messages
        )
    ]
    removed_warnings = before_warning_count - len(result["warnings"])
    for warning in patch["add"]["warnings"]:
        if not isinstance(warning, dict):
            raise ModelV0Error("repair add.warnings entries must be objects")
        result["warnings"].append(copy.deepcopy(warning))
        added["warnings"] += 1

    stats = {
        "protocol": "patch-only-v0.2",
        "replaced": replaced,
        "added": added,
        "removed_warnings": removed_warnings,
    }
    return result, stats


def repair_once(
    provider: ModelProvider,
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
    bundle: dict[str, Any],
    validation_errors: list[str],
    fixture_name: str,  # noqa: ARG001 - retained for call-site compatibility
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    prompt = build_repair_prompt(
        raw, context, config, schema, bundle, validation_errors
    )
    response = provider.complete(prompt)
    patch = _parse_patch(response)
    repaired, stats = apply_repair_patch(bundle, patch)
    return repaired, response, stats
