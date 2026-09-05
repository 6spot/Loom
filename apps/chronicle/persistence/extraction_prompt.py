"""Bounded model-facing prompt contract for Chronicle chunk extraction.

This module contains only deterministic prompt rendering/diagnostic compaction.
Canonical validation remains owned by ``extraction.py`` and the canonical JSON
Schema; this guide is model-facing assistance, never an alternate schema or
authority layer.
"""

from __future__ import annotations

import json
import re
from typing import Any

PROMPT_VERSION = "c1t6-prompt-v3"

# The model must not infer the canonical record shape from prose or from SECTION /
# DOCUMENT metadata. Keep this deliberately compact so the existing 8K input
# budget still has room for the immutable source chunk and bounded ContextState.
MODEL_CONTRACT_GUIDE = r'''CANONICAL BUNDLE SHAPE (field names are exact; this is shape guidance, not source facts)
Output schema_version MUST be "0.1". Internal Chronicle contract versions are NOT output schema versions.
Use temp_id only (src_001 / ent_001 / evt_001 / clm_001); NEVER emit canonical `id`.
source: {temp_id,kind:"source",source_type,title,language,extraction,...optional source fields}
entity: {temp_id,kind:"entity",type,canonical_name,aliases,mentions:[{text,contextual?}],resolution:{status,canonical_id?,candidate_ids?},extraction,...optional fields}
event: {temp_id,kind:"event",type,title,time,participants:[{entity_ref,role}],places:[entity-temp-id,...],extraction,...optional summary/parent_event_ref}
claim: {temp_id,kind:"claim",subject:REF,predicate,object:null|REF|LITERAL,time,evidence:{text,source_ref,locator},assessment:{status:"unassessed",note?},extraction}
warning: {type,severity:"info"|"warning"|"error",message,refs?}
REF: {kind:"entity_ref"|"event_ref",ref:temp-id}
LITERAL: {kind:"literal",value:any-json-value}
extraction: {method:"model",job_id:null|string,confidence:null|0..1}
time: null OR {original_text,source_calendar:{system,era?,era_year?,season?,month?,day?,inherited_fields:[]},normalized:null|{calendar:"proleptic_gregorian",year,month,day,precision,conversion_status,approximate?}}
Allowed entity.type: person, place, polity, organization, army, office, group, other.
Allowed event.type: political, administrative, military, battle, movement, retreat, death, birth, succession, appointment, surrender, diplomatic, epidemic, territorial_change, economic, cultural, other.
source_calendar.system: chinese_lunisolar_regnal, proleptic_gregorian, unknown.
Do NOT put `claims` inside events. Do NOT use singular `place`; use `places` array. Participant key is `entity_ref`, never `ref`.
SECTION/DOCUMENT/CONTEXT are input metadata only: do not copy arbitrary keys such as label, section_index, or kind into canonical records. SECTION.label may be used as evidence.locator.section.'''

_MAX_CORRECTION_ERRORS = 32
_MAX_CORRECTION_DIAGNOSTIC_CHARS = 3000
_MAX_ONE_DIAGNOSTIC_CHARS = 360
_INDEX_PATH_RE = re.compile(r"/(?:0|[1-9][0-9]*)(?=/|:|$)")
_WS_RE = re.compile(r"\s+")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _diagnostic_signature(value: str) -> str:
    """Collapse record indexes so repeated schema-shape errors deduplicate."""
    return _INDEX_PATH_RE.sub("/*", value)


def compact_validation_errors(errors: list[str]) -> list[str]:
    """Return a bounded representative diagnostic set for one correction ask.

    The full deterministic validation report remains persisted in ChunkRun
    history. Only the model-facing repair diagnostics are compacted. Umbrella
    JSON-Schema messages that stringify an entire invalid object are skipped in
    favor of their specific child errors, repeated array-index paths are
    wildcarded/deduplicated, and the result has fixed item/character budgets.
    """
    if not isinstance(errors, list):
        return []

    kept: list[str] = []
    seen: set[str] = set()
    chars = 0
    omitted = 0

    for raw in errors:
        if not isinstance(raw, str) or not raw:
            continue
        text = _WS_RE.sub(" ", raw).strip()
        # jsonschema umbrella anyOf/oneOf messages contain full object reprs and
        # are both huge and less actionable than the specific child errors that
        # follow them in the deterministic report.
        if " is not valid under any of the given schemas" in text:
            omitted += 1
            continue
        text = _diagnostic_signature(text)
        if len(text) > _MAX_ONE_DIAGNOSTIC_CHARS:
            text = text[: _MAX_ONE_DIAGNOSTIC_CHARS - 24].rstrip() + " … [diagnostic shortened]"
        if text in seen:
            omitted += 1
            continue
        projected = chars + len(text) + (1 if kept else 0)
        if len(kept) >= _MAX_CORRECTION_ERRORS or projected > _MAX_CORRECTION_DIAGNOSTIC_CHARS:
            omitted += 1
            continue
        seen.add(text)
        kept.append(text)
        chars = projected

    if omitted:
        note = (
            f"diagnostic_summary: {omitted} additional/repeated validator errors "
            "are omitted from this repair prompt; regenerate the complete bundle "
            "against CANONICAL BUNDLE SHAPE. The full report is retained in "
            "ChunkRun history."
        )
        if chars + len(note) + 1 <= _MAX_CORRECTION_DIAGNOSTIC_CHARS + 220:
            kept.append(note)
    return kept


def render_extraction_prompt(
    *,
    chunk_text: str,
    section: dict[str, Any],
    document: dict[str, Any],
    context_input: dict[str, Any],
    boundary_head: str,
    boundary_tail: str,
    validation_errors: list[str] | None = None,
    previous_candidate: dict[str, Any] | None = None,
    omit_previous_candidate: bool = False,
) -> str:
    """Render the bounded v3 initial/correction prompt."""
    correction = ""
    if validation_errors is not None:
        title = "COMPACT CORRECTION RE-ASK" if omit_previous_candidate else "CORRECTION RE-ASK"
        candidate_note = ""
        if omit_previous_candidate:
            candidate_note = (
                "\nPRIOR CANDIDATE BODY OMITTED to preserve the fixed input budget; "
                "its raw response/candidate remain in ChunkRun history. Regenerate "
                "the complete bundle.\n"
            )
        elif previous_candidate is not None:
            candidate_note = "\nPREVIOUS CANDIDATE\n" + _json(previous_candidate) + "\n"
        correction = (
            "\n" + title + "\n"
            "The prior bundle failed deterministic validation. Repair every listed "
            "issue, regenerate one complete bundle, and obey CANONICAL BUNDLE SHAPE. "
            "Do not fabricate evidence/precision or delete unrelated grounded facts.\n"
            "VALIDATION DIAGNOSTICS\n"
            + _json(validation_errors)
            + "\n"
            + candidate_note
        )

    return f'''You are Chronicle source-grounded chunk extraction. Return exactly one compact JSON object and no prose/Markdown.

{MODEL_CONTRACT_GUIDE}

GROUNDING / AUTHORITY RULES
- Use only CHUNK SOURCE TEXT plus explicit SECTION/DOCUMENT metadata and bounded INHERITED CONTEXT. Never add outside historical knowledge.
- INHERITED CONTEXT is interpretation aid only, never evidence or authority. Every Claim.evidence.text must be an exact CHUNK SOURCE TEXT substring.
- Create source-grounded entities needed by represented facts. Names/titles are attributes, never identity; ambiguity stays unresolved with a warning.
- An inherited-only entity is allowed only when its surface exists in INHERITED CONTEXT and an inherited_entity_context warning names it.
- Distinct occurrences remain distinct Events; Claims are explicit source assertions, not Events. Avoid semantic duplicates.
- Use a faithful configured predicate when possible; otherwise emit ontology_gap instead of forcing meaning. Claim assessment always starts unassessed.
- Preserve explicit/safely inherited traditional time verbatim. Inherited time lists inherited_fields. Never invent normalized month/day; normalized year is allowed only when DOCUMENT supplies the verified mapping. If unsafe/unknown, use null.
- Warnings describe the final returned bundle. Compact JSON must not drop a distinct source-grounded fact.
{correction}
SECTION
{_json(section)}
DOCUMENT
{_json(document)}
INHERITED CONTEXT (processing aid only; not evidence/authority)
{_json(context_input)}
BOUNDARY CONTEXT (interpretation only; not evidence)
{_json({"boundary_head": boundary_head, "boundary_tail": boundary_tail})}
CHUNK SOURCE TEXT
---BEGIN CHUNK---
{chunk_text}
---END CHUNK---
'''
