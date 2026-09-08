#!/usr/bin/env python3
"""Focused real-provider contract check for Chronicle extraction.

This is intentionally narrower than C1-T17. It exercises the real configured
Responses-compatible provider, the current extraction prompt, JSON parsing,
canonical staged-bundle validation, grounding, time precision, references,
and assessment rules against a committed source fixture.

A PASS must also be non-trivial: the accepted candidate must contain at least
one Entity, Event, and Claim, and at least one Claim must carry exact evidence
from the fixture source. This prevents a structurally valid but empty bundle
from satisfying live-provider prevalidation.

It never prints prompts, raw model output, endpoint credentials, or API keys.
Only bounded metadata, hashes, counts, and compact deterministic validation
summaries are emitted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHRONICLE = HERE.parent
for path in (CHRONICLE / "persistence", CHRONICLE / "worker"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

import extraction as X  # noqa: E402
import extraction_prompt as prompt_contract  # noqa: E402
import model_provider  # noqa: E402

FIXTURE = CHRONICLE / "ingestion" / "fixtures" / "c1t6-inherited-jianan" / "raw.txt"


def _context() -> dict:
    return {
        "version": X.EXPECTED_CONTEXT_VERSION,
        "chunk_index": -1,
        "inherited_time": [],
        "active_entities": [],
        "active_places": [],
        "recent_events": [],
        "coreference_hints": [],
        "prev_tail": "",
        "next_head": "",
        "authoritative": False,
        "authority_note": "live model contract fixture only",
    }


def _attempt_summary(attempt: dict) -> dict:
    raw = attempt.get("raw_response")
    report = attempt.get("validation")
    categories = {}
    compact_diagnostics: list[str] = []
    if isinstance(report, dict):
        categories = {
            name: len(values or [])
            for name, values in (report.get("errors") or {}).items()
        }
        compact_diagnostics = prompt_contract.compact_validation_errors(
            X.flatten_validation_errors(report)
        )
    return {
        "kind": attempt.get("kind"),
        "raw_chars": len(raw) if isinstance(raw, str) else None,
        "raw_response_sha256": attempt.get("raw_response_sha256"),
        "parse_error": bool(attempt.get("parse_error")),
        "validation_passed": report.get("passed") if isinstance(report, dict) else None,
        "validation_count": report.get("count") if isinstance(report, dict) else None,
        "validation_categories": categories,
        "compact_diagnostics": compact_diagnostics,
    }


def _candidate_contract(candidate: object, *, chunk_text: str) -> dict:
    if not isinstance(candidate, dict):
        return {
            "nontrivial": False,
            "entity_count": 0,
            "event_count": 0,
            "claim_count": 0,
            "exact_evidence_claim_count": 0,
        }

    def records(name: str) -> list[dict]:
        value = candidate.get(name)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    entities = records("entities")
    events = records("events")
    claims = records("claims")
    exact_evidence_claims = 0
    for claim in claims:
        evidence = claim.get("evidence")
        text = evidence.get("text") if isinstance(evidence, dict) else None
        if isinstance(text, str) and text and text in chunk_text:
            exact_evidence_claims += 1

    return {
        "nontrivial": bool(entities and events and claims and exact_evidence_claims),
        "entity_count": len(entities),
        "event_count": len(events),
        "claim_count": len(claims),
        "exact_evidence_claim_count": exact_evidence_claims,
    }


def _summary(result: dict, *, chunk_text: str) -> dict:
    attempts = [
        _attempt_summary(attempt)
        for attempt in (result.get("attempts") or [])
        if isinstance(attempt, dict)
    ]
    candidate_contract = _candidate_contract(result.get("candidate"), chunk_text=chunk_text)
    return {
        "schema": "chronicle.live-model-contract",
        "prompt_version": X.PROMPT_VERSION,
        "accepted": bool(result.get("accepted")),
        "nontrivial": candidate_contract["nontrivial"],
        "candidate_counts": {
            "entities": candidate_contract["entity_count"],
            "events": candidate_contract["event_count"],
            "claims": candidate_contract["claim_count"],
            "exact_evidence_claims": candidate_contract["exact_evidence_claim_count"],
        },
        "attempt_count": len(attempts),
        "attempts": attempts,
    }


def main() -> int:
    chunk_text = FIXTURE.read_text(encoding="utf-8").strip()
    document = {
        "title": "三国志·蜀书·先主传",
        "work": "三国志",
        "source_type": "book",
        "verified_normalized_year": 208,
    }
    section = {"label": "全文", "kind": "document", "section_index": 0}
    locator = {
        "job_id": "00000000-0000-0000-0000-000000000000",
        "revision_id": "00000000-0000-0000-0000-000000000001",
        "revision_no": 1,
        "source_sha256": X.sha256_text(chunk_text),
        "section_index": 0,
        "chunk_index": 0,
        "source_start": 0,
        "source_end": len(chunk_text),
        "offset_unit": X.OFFSET_UNIT,
        "content_sha256": X.sha256_text(chunk_text),
    }
    context = _context()
    config = X.ExtractionConfig()
    request = X.build_chunk_request(
        chunk_text=chunk_text,
        section=section,
        document=document,
        context_input=context,
        boundary_head="",
        boundary_tail="",
        locator=locator,
        config=config,
    )

    extraction_model, _ = model_provider.models_from_env()
    if extraction_model is None:
        raise SystemExit("CHRONICLE_EXTRACTION_MODEL/live provider is required")

    result = X.extract_chunk(
        extraction_model,
        request,
        chunk_text=chunk_text,
        context_input=context,
        section_label=section["label"],
        document=document,
        schema=X.require_canonical_schema(None),
        allowed_predicates=None,
        config=config,
    )

    summary = _summary(result, chunk_text=chunk_text)
    summary["model"] = extraction_model.name
    summary["prompt_chars"] = request["request_meta"]["prompt_chars"]
    summary["prompt_sha256"] = request["request_meta"]["prompt_sha256"]
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    if result.get("accepted") and summary["nontrivial"]:
        print("Chronicle live model contract: PASS")
        return 0

    print("Chronicle live model contract: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
