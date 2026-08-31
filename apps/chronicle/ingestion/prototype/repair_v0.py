"""Bounded validator-driven repair for Chronicle model-v0."""

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
Do not perform a new coverage review. Do not add unrelated historical facts. Do not optimize toward any human gold/reference answer.
Use only SOURCE TEXT, DOCUMENT CONTEXT, INGESTION POLICY, OUTPUT JSON SCHEMA, CURRENT STAGED BUNDLE, and VALIDATION ERRORS in this prompt.
Preserve valid records and their meaning. Keep existing temp IDs/order where practical.
Every Claim evidence must remain an exact SOURCE TEXT substring.
Never invent Gregorian month/day precision.
Return one complete corrected Chronicle staged JSON object only.

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
    return normalize_model_bundle(parsed, fixture_name, job_id="model-v0+repair-v0"), response
