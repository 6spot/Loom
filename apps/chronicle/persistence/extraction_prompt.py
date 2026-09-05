"""Bounded model-facing prompt contract for Chronicle chunk extraction.

This module contains only deterministic prompt rendering/diagnostic compaction.
Canonical validation remains owned by ``extraction.py`` and the canonical JSON
Schema; these guides are model-facing assistance, never alternate schemas or
authority layers.
"""

from __future__ import annotations

import json
import re
from typing import Any

PROMPT_VERSION = "c1t6-prompt-v3"

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

MODEL_CONTRACT_CORE = r'''CANONICAL BUNDLE SHAPE (exact field names)
schema_version="0.1"; use temp_id only, never `id`.
source={temp_id,kind:"source",source_type,title,language,extraction}
entity={temp_id,kind:"entity",type,canonical_name,aliases,mentions,resolution,extraction}
event={temp_id,kind:"event",type,title,time,participants:[{entity_ref,role}],places:[temp-id,...],extraction}
claim={temp_id,kind:"claim",subject:{kind,ref},predicate,object,time,evidence:{text,source_ref,locator},assessment:{status:"unassessed"},extraction}
warning={type,severity,message,refs?}; extraction={method:"model",job_id:null|string,confidence:null|0..1}.
Event.type must be one of: political, administrative, military, battle, movement, retreat, death, birth, succession, appointment, surrender, diplomatic, epidemic, territorial_change, economic, cultural, other.
No events[].claims; no singular place; participants use entity_ref. SECTION/DOCUMENT/CONTEXT keys are metadata, not record fields.'''

_MAX_CORRECTION_ERRORS = 20
_MAX_CORRECTION_DIAGNOSTIC_CHARS = 1800
_MAX_ONE_DIAGNOSTIC_CHARS = 280
_INDEX_PATH_RE = re.compile(r"/(?:0|[1-9][0-9]*)(?=/|:|$)")
_TEMP_ID_RE = re.compile(r"\b(src|ent|evt|clm)_[0-9]{3,}\b")
_WS_RE = re.compile(r"\s+")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _diagnostic_signature(value: str) -> str:
    value = _INDEX_PATH_RE.sub("/*", value)
    return _TEMP_ID_RE.sub(lambda match: f"{match.group(1)}_*", value)


def compact_validation_errors(errors: list[str]) -> list[str]:
    """Bound only model-facing repair diagnostics; keep full history untouched."""
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
            "omitted from this repair prompt; full report remains in ChunkRun history."
        )
        if chars + len(note) + 1 <= _MAX_CORRECTION_DIAGNOSTIC_CHARS + 160:
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
) -> str:
    """Render the full v3 initial/preferred-correction prompt."""
    correction = ""
    if validation_errors is not None:
        candidate_note = ""
        if previous_candidate is not None:
            candidate_note = "\nPREVIOUS CANDIDATE\n" + _json(previous_candidate) + "\n"
        correction = (
            "\nCORRECTION RE-ASK\n"
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


def render_compact_correction_prompt(
    *,
    chunk_text: str,
    section: dict[str, Any],
    document: dict[str, Any],
    context_input: dict[str, Any],
    validation_errors: list[str],
) -> str:
    """Render a smaller repair envelope while retaining full source/context."""
    return f'''Chronicle COMPACT CORRECTION RE-ASK. Return one complete compact JSON object only.
{MODEL_CONTRACT_CORE}
REPAIR RULES: source/context only; no outside facts; exact Claim evidence substring; inherited context is never evidence/authority; ambiguity stays unresolved; no canonical IDs; assessment=unassessed; no invented normalized month/day/year; preserve distinct facts; ontology_gap when predicate does not fit.
VALIDATION DIAGNOSTICS
{_json(validation_errors)}
PRIOR CANDIDATE BODY OMITTED to preserve the fixed input budget; it remains in ChunkRun history.
SECTION
{_json(section)}
DOCUMENT
{_json(document)}
INHERITED CONTEXT (full bounded state; interpretation only)
{_json(context_input)}
CHUNK SOURCE TEXT
---BEGIN CHUNK---
{chunk_text}
---END CHUNK---
'''
