"""Offline model-resolution experiment; never used by the production worker."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_PERSISTENCE = Path(__file__).resolve().parents[2] / "persistence"
if str(_PERSISTENCE) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE))

from identity_candidates import apply_resolution_decisions
from model_v0 import ModelProvider, parse_model_response


def build_resolution_prompt(candidates: dict[str, Any]) -> str:
    payload = json.dumps(candidates, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""You are Chronicle resolution-v0.1, a closed-world cross-source resolver.

TASK
Adjudicate only the candidate pairs supplied below. The two source bundles were already independently extracted and must remain immutable.

RULES
1. Use only the supplied candidate records and signals. Do not add outside historical knowledge.
2. `same_entity` means both Entity records refer to the same historical identity, not merely the same name or role.
3. `same_occurrence` means both Event records describe the same underlying historical occurrence, even when wording, emphasis, or granularity differs slightly.
4. `related_occurrence` means the Events are historically connected or part of the same sequence/campaign but are not the same occurrence.
5. Use `not_same` when the records clearly describe different identities/occurrences.
6. Use `uncertain` when the supplied evidence is insufficient. Do not guess.
7. Resolution confidence measures confidence in this link decision only. It is not historical-truth confidence.
8. Do not invent canonical UUIDs, rewrite temp IDs, merge records, or create new historical facts.
9. Return every supplied candidate_id exactly once and no unknown candidate_id.
10. Return exactly one JSON object and no prose.

OUTPUT FORMAT
{{
  "entity_decisions": [
    {{"candidate_id": "ec_001", "decision": "same_entity|not_same|uncertain", "confidence": 0.0, "rationale": "brief source-bounded reason"}}
  ],
  "event_decisions": [
    {{"candidate_id": "vc_001", "decision": "same_occurrence|related_occurrence|not_same|uncertain", "confidence": 0.0, "rationale": "brief source-bounded reason"}}
  ]
}}

CANDIDATES
{payload}
"""


def resolve_with_provider(
    candidates: dict[str, Any], provider: ModelProvider
) -> tuple[dict[str, Any], str]:
    if not (
        candidates.get("entity_candidates") or candidates.get("event_candidates")
    ):
        empty = {
            "entity_decisions": [],
            "event_decisions": [],
        }
        return apply_resolution_decisions(candidates, empty), ""
    raw = provider.complete(build_resolution_prompt(candidates))
    response = parse_model_response(raw)
    return apply_resolution_decisions(candidates, response), raw
