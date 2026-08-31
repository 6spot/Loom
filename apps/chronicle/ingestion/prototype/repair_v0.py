"""Bounded validator-driven repair for Chronicle contract-first ingestion."""

from __future__ import annotations

import json
from typing import Any

from model_v0 import ModelProvider, normalize_model_bundle, parse_model_response


def build_repair_prompt(
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
    bundle: dict[str, Any],
    validation_errors: list[str],
) -> str:
    """Build a closed-book repair prompt from deterministic validation errors only."""
    return f"""You are Chronicle repair-v0.

Correct ONLY the mechanically validated errors listed below in the current staged bundle.
Do not perform a new extraction or coverage review. Do not add unrelated historical facts. Do not optimize toward any human gold/reference answer.
Use only SOURCE TEXT, DOCUMENT CONTEXT, INGESTION POLICY, OUTPUT JSON SCHEMA, CURRENT STAGED BUNDLE, and VALIDATION ERRORS in this prompt.

REPAIR RULES
1. Preserve all valid records and their historical meaning. Make the smallest changes needed to satisfy VALIDATION ERRORS.
2. Keep existing temp IDs/order where practical. If a missing referenced Entity must be added to fix reference integrity, add only that source-grounded Entity and rewrite only the necessary references.
3. Do not change Event/Claim granularity or predicate semantics unless a listed validation error requires that change.
4. Every Claim evidence must remain an exact SOURCE TEXT substring.
5. Never invent Gregorian month/day precision.
6. If you change records in a way that makes an existing warning false or stale, update or remove that warning. Warnings in the returned bundle must describe the corrected final bundle, not the pre-repair state.
7. Do not create a new warning merely to hide a validation error.
8. Return one complete corrected Chronicle staged JSON object only.

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


def repair_once(
    provider: ModelProvider,
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
    bundle: dict[str, Any],
    validation_errors: list[str],
    fixture_name: str,
) -> tuple[dict[str, Any], str]:
    prompt = build_repair_prompt(
        raw, context, config, schema, bundle, validation_errors
    )
    response = provider.complete(prompt)
    parsed = parse_model_response(response)
    return normalize_model_bundle(parsed, fixture_name, job_id="contract-v0.2+repair-v0"), response
