"""Contract-first extraction prompt for Chronicle production ingestion."""

from __future__ import annotations

import json
from typing import Any

from model_v0 import ModelProvider, normalize_model_bundle, parse_model_response


def build_contract_prompt(
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
) -> str:
    return f"""You are Chronicle contract-v0, a source-grounded historical data extraction agent.

TASK
Read the entire SOURCE TEXT from beginning to end and produce one complete Chronicle staged bundle that follows the supplied INGESTION POLICY and OUTPUT JSON SCHEMA.

RESPONSIBILITY
- Chronicle defines the data contract; you are responsible for understanding the source and mapping its explicit historical content into that contract.
- Extract the source comprehensively, not only the most famous or salient events.
- Do not perform a second-pass audit and do not guess what a hidden reference answer might contain.

SEMANTIC RULES
1. Use only SOURCE TEXT plus explicit DOCUMENT CONTEXT. Never add outside historical knowledge.
2. Extract source-grounded Entity records needed by the facts you represent.
3. Create an Event for a distinct historical occurrence or state transition. Do not promote every clause or subordinate detail into a separate Event when a Claim is sufficient.
4. Create Claims for explicit factual assertions when the configured canonical predicate vocabulary can faithfully express them.
5. Event and Claim are different layers: Event models the occurrence; Claim models what this source asserts.
6. Every Claim.evidence.text must be an exact SOURCE TEXT substring.
7. Avoid duplicate Entity/Event/Claim records for the same source assertion.
8. Preserve traditional/regnal time expressions and inherited source-calendar context. You may use a safe normalized year supplied by DOCUMENT CONTEXT, but never fabricate Gregorian month/day precision.
9. Names, titles, pinyin, and dates are attributes, never identity. Use only job-local temp IDs and defer canonical resolution.
10. If a reference is ambiguous, keep it unresolved and emit a warning rather than guessing.
11. Every new Claim assessment starts as `unassessed`; extraction confidence is not historical truth confidence.
12. Return exactly one JSON object satisfying the supplied JSON Schema. No prose.

DOCUMENT CONTEXT
{json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)}

INGESTION POLICY
{json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True)}

OUTPUT JSON SCHEMA
{json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)}

SOURCE TEXT
---BEGIN SOURCE---
{raw}
---END SOURCE---
"""


class ContractV0Extractor:
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

    def prompt(self) -> str:
        return build_contract_prompt(self.raw, self.context, self.config, self.schema)

    def extract(self) -> dict[str, Any]:
        response = self.provider.complete(self.prompt())
        return normalize_model_bundle(
            parse_model_response(response), self.fixture_name, job_id="contract-v0"
        )
