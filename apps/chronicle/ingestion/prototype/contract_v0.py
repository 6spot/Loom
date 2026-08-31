"""Contract-first extraction prompt for Chronicle production ingestion."""

from __future__ import annotations

import json
from typing import Any

from model_v0 import ModelProvider, normalize_model_bundle, parse_model_response


CONTRACT_VERSION = "0.2"


def build_contract_prompt(
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
) -> str:
    return f"""You are Chronicle contract-v{CONTRACT_VERSION}, a source-grounded historical data extraction agent.

TASK
Read the entire SOURCE TEXT from beginning to end and produce one complete Chronicle staged bundle that follows the supplied INGESTION POLICY and OUTPUT JSON SCHEMA.

RESPONSIBILITY
- Chronicle defines the data contract; you are responsible for understanding the source and mapping its explicit historical content into that contract.
- Extract the source comprehensively, not only the most famous or salient events.
- Do not perform a second-pass coverage audit and do not guess what a hidden reference answer might contain.

SEMANTIC RULES
1. Use only SOURCE TEXT plus explicit DOCUMENT CONTEXT. Never add outside historical knowledge.
2. Extract source-grounded Entity records needed by the facts you represent.
3. Create an Event for a distinct historical occurrence or state transition. Independent actions that would make sense as separate timeline entries should normally be separate Events; do not merge several independent actions merely because they occur in one sentence.
4. Do not promote subordinate attributes or relations into standalone Events when a Claim is sufficient.
5. Create Claims for explicit factual assertions only when one configured canonical predicate faithfully expresses the source meaning.
6. Predicate choice must be semantically exact enough for the source assertion. Do not use a merely related predicate to avoid an ontology gap. For example, movement toward/arrival at a place should use a movement predicate rather than `returned_to` unless the source actually says the subject returned; personally advancing toward a place is not `sent_forces` unless the source actually says forces were sent.
7. If no allowed canonical predicate faithfully represents an explicit assertion, preserve any appropriate Event/Entity representation and emit a warning with type `ontology_gap` describing the missing relation. Do not invent a predicate and do not force the assertion into an unrelated allowed predicate.
8. Event and Claim are different layers: Event models the occurrence; Claim models what this source asserts.
9. Every Claim.evidence.text must be an exact SOURCE TEXT substring.
10. Avoid duplicate Entity/Event/Claim records for the same source assertion.

TIME RULES
11. Preserve explicit and safely inherited traditional/regnal source time. Source-calendar time is data, not display decoration.
12. For every Event that falls under an explicit source month marker or safely inherits the latest source month marker, populate Event.time using `chinese_lunisolar_regnal` rather than leaving time null.
13. Use DOCUMENT CONTEXT for a supplied era / era year / safe normalized year. If a month is inherited from an earlier source marker, include `month` in `source_calendar.inherited_fields`; if era/year are inherited from document context, mark those inherited fields too.
14. `time.original_text` should preserve the relevant source time marker such as `八月` or `十二月`; do not manufacture a Gregorian rendering.
15. A traditional source month number remains a traditional source-calendar month. Never copy it into normalized Gregorian month/day. When only the year conversion is verified, normalized precision remains `year`, normalized month/day remain null, and conversion_status remains `year_only` or another policy-compatible partial state.
16. If the source gives no safe time context for an Event, time may remain null. Never guess.

IDENTITY / PROVENANCE RULES
17. Names, titles, pinyin, and dates are attributes, never identity. Use only job-local temp IDs and defer canonical resolution.
18. If a reference is ambiguous, keep it unresolved and emit a warning rather than guessing.
19. Every new Claim assessment starts as `unassessed`; extraction confidence is not historical truth confidence.
20. Warnings must describe the final bundle you are returning. Do not emit warnings that contradict records already present in that same bundle.
21. Return exactly one JSON object satisfying the supplied JSON Schema. No prose.

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
            parse_model_response(response),
            self.fixture_name,
            job_id=f"contract-v{CONTRACT_VERSION}",
        )
