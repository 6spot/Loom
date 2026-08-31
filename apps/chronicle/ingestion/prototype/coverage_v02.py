"""Source-grounded second-pass coverage review for Chronicle model-v0."""

from __future__ import annotations

import json
from typing import Any

from model_v0 import ModelProvider, normalize_model_bundle, parse_model_response


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
    initial_text = json.dumps(
        initial_bundle, ensure_ascii=False, indent=2, sort_keys=True
    )
    return f"""You are Chronicle coverage-v0.2, a closed-book coverage reviewer.

Your task is NOT to reinterpret history and NOT to rewrite for style.
Audit the SOURCE TEXT sentence-by-sentence against PASS-1 STAGED BUNDLE and
return one complete revised Chronicle v0.1 JSON bundle.

NON-NEGOTIABLE RULES
1. Use only SOURCE TEXT plus explicit DOCUMENT CONTEXT. Never add background historical knowledge.
2. Do not optimize toward any external reference answer. None is provided.
3. Preserve valid pass-1 records. Do not delete, rename, merge, or rewrite a valid record merely for style.
4. For every explicit action, state transition, appointment, death, succession, surrender, attack,
   movement, battle/outcome, epidemic/effect, territorial change, or other historically meaningful
   assertion in SOURCE TEXT, check whether the staged bundle contains the needed Entity/Event/Claim.
5. Add missing records only when directly supported by SOURCE TEXT.
6. Every Claim.evidence.text must be an exact SOURCE TEXT substring.
7. Use only canonical Claim predicates allowed by INGESTION POLICY. Do not emit configured aliases.
8. Preserve traditional/regnal time expressions and never fabricate Gregorian month/day precision.
9. Keep entity/event resolution deferred; do not invent canonical UUIDs.
10. Return one complete revised JSON object only, satisfying OUTPUT JSON SCHEMA.

COVERAGE AUDIT METHOD
- Walk the source in textual order.
- Identify each explicit historically meaningful action or state change.
- For each one, verify relevant entities exist.
- Verify an Event exists when the source describes an occurrence/state transition.
- Verify one or more Claims capture the source assertion when appropriate.
- Prefer atomic claims; multiple atomic Claims may cover one longer source sentence.
- Extra source-grounded detail is acceptable; unsupported detail is forbidden.

DOCUMENT CONTEXT
{context_text}

INGESTION POLICY
{config_text}

OUTPUT JSON SCHEMA
{schema_text}

PASS-1 STAGED BUNDLE
{initial_text}

SOURCE TEXT
---BEGIN SOURCE---
{raw}
---END SOURCE---
"""


class CoverageV02Extractor:
    """Run one provider-backed coverage review over an existing staged bundle."""

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
            self.raw,
            self.context,
            self.config,
            self.schema,
            initial_bundle,
        )

    def review(self, initial_bundle: dict[str, Any]) -> dict[str, Any]:
        response = self.provider.complete(self.prompt(initial_bundle))
        parsed = parse_model_response(response)
        return normalize_model_bundle(
            parsed,
            self.fixture_name,
            job_id="model-v0+coverage-v0.2",
        )


def object_counts(bundle: dict[str, Any]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for name in ("entities", "events", "claims", "warnings"):
        value = bundle.get(name)
        counts[name] = len(value) if isinstance(value, list) else None
    return counts
