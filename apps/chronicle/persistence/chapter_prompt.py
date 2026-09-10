"""Chronicle C2-R1-T05 whole-chapter joint prompt (application-owned).

Pure deterministic prompt rendering for one complete natural chapter, per
``chapter-production.md`` sections 3-4. No database, network, or model
access (Amendment 0006); no worker changes. Transport retries belong to
T06; this module only renders the model-facing text consumed through the
``model.complete(prompt) -> str`` boundary owned by
``chapter_extraction.py``.

Every rendered prompt carries the *whole* chapter: all blocks with their
absolute chapter-relative ranges, the full normalized text verbatim
(including the chapter tail), source/plan metadata, the C0
type/predicate/time rules, and the joint candidate shape. A correction
re-ask carries the same whole chapter plus a bounded diagnostic list and
the previous candidate, and still requires one complete regenerated
chapter product — never a patch of one failed segment.
"""

from __future__ import annotations

import json
import re
from typing import Any

from common import PersistenceError

#: Version of the whole-chapter prompt template rendered here. Bound into
#: the producing run of every accepted artifact.
PROMPT_VERSION = "c2r1-chapter-prompt-v8"

#: Joint candidate marker the model must emit (T01 contract).
CANDIDATE_SCHEMA = "chronicle.chapter-candidate"
CANDIDATE_VERSION = "0.1"

#: Offset unit for every block coordinate in the rendered chapter.
OFFSET_UNIT = "chars-normalized-utf8"

JOINT_PRODUCT_GUIDE = r'''JOINT PRODUCT SHAPE (field names are exact; this is shape guidance, not source facts)
Emit exactly one JSON object with schema="chronicle.chapter-candidate", version="0.1",
and chapter_id copied verbatim from CHAPTER REQUEST. Required top-level keys:
bundle, translation, mentions, record_sources, warnings.
bundle: {schema_version:"0.1", source, entities[], events[], claims[], warnings[]}.
Use temp_id only (src_*/ent_*/evt_*/clm_*), numbered sequentially from 001
within each kind (ent_001, ent_002, ...; the numeric part must stay within
000-999 so assembly can remap it); NEVER emit canonical `id`,
canonical_id, or candidate_ids.
source: {temp_id:"src_*", kind:"source", source_type, title, language, extraction}.
entity: {temp_id:"ent_*", kind:"entity", type, canonical_name, aliases[], mentions:[{text}],
  resolution:{status:"unresolved"}, extraction}.
event: {temp_id:"evt_*", kind:"event", type, title, time, participants:[{entity_ref,role}],
  places:[entity-temp-id,...], parent_event_ref, extraction}.
claim: {temp_id:"clm_*", kind:"claim", subject:{kind,ref}, predicate,
  object:{kind,ref}|{kind:literal,value}, time,
  evidence:{text,source_ref,locator}, assessment:{status:"unassessed"}, extraction}.
  subject/object entity|event references are {kind,ref} naming an existing
  temp_id; a non-entity/event claim object is {kind:literal,value} with the
  literal text in value (never a ref key, never a bare string).
  subject must not be a literal.
translation: {language:"zh-CN", blocks:[{block_id, text, source_block_ids[],
  entity_refs:[{kind:"entity",ref}], event_refs:[{kind:"event",ref}]}]}.
Every translation block needs a unique block_id, non-empty text, and a non-empty
source_block_ids[] naming chapter blocks. Array order is meaningful.
mentions[]: {mention_id, surface, contextual, status, target_ref, candidate_refs[], selection}.
selection: {first_block_id, last_block_id, quote, occurrence} — both blocks in this
chapter in legal order; quote matches the covered source text verbatim; occurrence
counts from 1 within that window.
record_sources[]: {record_ref, record_kind, selections[]} — every Entity/Event/Claim
needs a non-empty selections[] entry; claim evidence.text must equal its first
selection quote and evidence.source_ref must name the bundle source.
warnings[]: {type, message} — a warning never substitutes for structural validity.
extraction: {method:"model", job_id, confidence}. time: null OR
{original_text, source_calendar:{system,era?,era_year?,month?,day?,inherited_fields:[]},
 normalized:null|{calendar, year, month, day, precision, conversion_status}}.
Allowed entity.type: person, place, polity, organization, army, office, group, other.
Allowed event.type: political, administrative, military, battle, movement, retreat,
death, birth, succession, appointment, surrender, diplomatic, epidemic,
territorial_change, economic, cultural, other.
source_calendar.system: chinese_lunisolar_regnal, proleptic_gregorian, unknown.
predicate uses snake_case (for example stationed_at); claim subject must not be a literal.
Do NOT copy CHAPTER REQUEST metadata keys (block kinds, hashes, limits) into records.'''

REFERENCE_RULES = r'''SAME-CHAPTER REFERENCE RULES
- One confirmed appellation shares one local temp_id within this chapter: when the
  chapter confirms 曹操 and 操 name the same person, both mentions resolve to the
  same Entity (target_ref points at one ent_* record; aliases need chapter-text support).
- An unresolvable reference stays unresolved: use status "unresolved" with
  target_ref null (candidate_refs may be empty). A genuinely ambiguous surface
  uses status "ambiguous" with target_ref null and at least two valid
  candidate_refs. Never force an uncertain surface onto the most familiar person.
- Prefer resolved over unresolved whenever the chapter confirms the referent:
  if the chapter text confirms who or what a mention denotes (for example
  先主 in 先主傳, or 曹公/操 where the chapter confirms 曹操), resolve the
  mention to that Entity with target_ref. Reserve "unresolved" strictly for
  references the chapter genuinely leaves unidentified; hedging every mention
  as unresolved when referents are confirmed evades the linkage the bundle
  exists to record.
- Contextual forms such as 公 / 王 stay contextual mentions; they must not become
  stable global aliases of any Entity.
- Every mention surface must equal its selection.quote exactly.
  surface is the mention occurrence text, never the entity display name:
  copy selection.quote character-for-character into surface (a quote
  '曹公征徐州' takes surface '曹公征徐州', not '曹公'; a quote '備' takes
  surface '備', not '劉備'). A shortened, expanded, or normalized surface
  is a grounding failure even when it names the right person.
- Entity resolution stays unresolved in this product: emit
  resolution:{status:"unresolved"} on every entity. Never invent
  canonical_id, candidate_ids, or another status value such as "new";
  identity is decided later in Studio review, never in this chapter product.'''

TRANSLATION_RULES = r'''FULL-TEXT FAITHFUL TRANSLATION RULES
- Translate the WHOLE chapter body text and every embedded annotation that exists
  in the source, in order. Do not substitute an introductory summary for the full
  text, and do not drop the tail of the chapter.
- Keep attribution: renderings such as 某书记载 / 裴松之按 stay with the passage
  they belong to. Never rewrite a cited book's view or disagreement as the
  author's own assertion.
- Keep persons/places/polities, event time and participant roles, and source
  evidence grounded in the chapter text. Every required source block listed in
  REQUIRED BLOCKS must appear in at least one translation block's source_block_ids.
- Time precision is never invented: normalized month/day stay null; a normalized
  year appears only with an exact verified source mapping, otherwise null.
- VERBATIM GROUNDING PROCEDURE (no exceptions):
  (a) every selection.quote (mentions and record_sources alike) must be copied
  character-for-character from CHAPTER BLOCKS or FULL CHAPTER TEXT; never
  paraphrase, abbreviate, merge, or complete a passage, and never emit a quote
  you cannot find as an exact substring;
  (b) set first_block_id/last_block_id to the block(s) whose [start:end) range
  actually encloses the quote, in legal order; count occurrence only inside
  that window; never guess a block id;
  (c) time.original_text must be the temporal expression EXACTLY as written in
  the source: do NOT prepend or append era, year, season, month, day, or 干支
  from surrounding context. Context-derived fields belong ONLY in
  source_calendar (era/era_year/month/day) and inherited_fields; anything not
  verbatim must not appear in original_text.
  (d) never convert script forms: the chapter source is Traditional; every
  quote, mention surface, alias, and time.original_text must reuse the exact
  source characters. A Simplified character where the source has Traditional
  (or vice versa) is a grounding failure, not a spelling variant.'''

_MAX_CORRECTION_ERRORS = 20
_MAX_CORRECTION_DIAGNOSTIC_CHARS = 1800
_MAX_ONE_DIAGNOSTIC_CHARS = 280
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
    # Only schema index paths are generalized ("/bundle/entities/0" -> "/*").
    # Record temp ids (ent_*/evt_*/clm_*/src_*/b_*) are repair pointers into
    # the PREVIOUS CANDIDATE carried in the same prompt: masking them to
    # "ent_*" collapses distinct records into one signature, so the dedup
    # below drops all but one failing record and the model can no longer
    # tell which record each diagnostic belongs to. Live evidence (C2-R1-T19)
    # showed anchor/time failures surviving correction exactly for this
    # reason; keep the ids verbatim.
    return _INDEX_PATH_RE.sub("/*", value)


def compact_validation_errors(errors: list[str]) -> list[str]:
    """Bound model-facing repair diagnostics; full history stays untouched.

    The complete validator report remains in the extraction attempt
    history. Only this compacted copy is sent back to the model so a long
    tail of repeated schema paths cannot consume the correction budget.
    Record temp ids stay verbatim so every diagnostic remains mapped to
    its failing record (see _diagnostic_signature).
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
            "omitted from this repair prompt; full report remains in attempt history."
        )
        if chars + len(note) + 1 <= _MAX_CORRECTION_DIAGNOSTIC_CHARS + 160:
            kept.append(note)
    return kept


def _require_request(request: Any) -> dict[str, Any]:
    """Check the program-owned chapter request shape needed for rendering."""
    if not isinstance(request, dict):
        raise PersistenceError("chapter request must be a JSON object")
    for key in (
        "chapter_id",
        "revision_id",
        "source_sha256",
        "normalized_sha256",
        "normalized_text",
        "blocks",
        "required_block_ids",
    ):
        if request.get(key) in (None, ""):
            raise PersistenceError(f"chapter request is missing {key!r}")
    text = request["normalized_text"]
    if not isinstance(text, str) or text == "":
        raise PersistenceError("chapter request normalized_text must be non-empty")
    blocks = request["blocks"]
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError("chapter request blocks must be a non-empty array")
    for block in blocks:
        if not isinstance(block, dict):
            raise PersistenceError("chapter request block must be an object")
        if not isinstance(block.get("block_id"), str) or not block["block_id"]:
            raise PersistenceError("chapter request block requires block_id")
    required = request["required_block_ids"]
    if not isinstance(required, list) or not required:
        raise PersistenceError("required_block_ids must be a non-empty array")
    return request


def _render_blocks(request: dict[str, Any]) -> str:
    """Render every chapter block with its range and full text."""
    text = request["normalized_text"]
    lines: list[str] = []
    for block in request["blocks"]:
        block_id = block["block_id"]
        kind = block.get("kind", "body")
        start, end = block.get("start"), block.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not (0 <= start < end <= len(text))
        ):
            raise PersistenceError(
                f"request block {block_id!r} range [{start},{end}) is outside "
                f"the chapter text ({len(text)} chars)"
            )
        content = text[start:end]
        lines.append(
            f"[{block_id} kind={kind} range={start}:{end} "
            f"offset_unit={OFFSET_UNIT}]\n{content}\n---END {block_id}---"
        )
    return "\n".join(lines)


def render_chapter_prompt(
    request: dict[str, Any],
    *,
    validation_errors: list[str] | None = None,
    previous_candidate: dict[str, Any] | None = None,
) -> str:
    """Render the whole-chapter joint translation/extraction prompt.

    The prompt always carries the complete chapter — every block and the
    full normalized text verbatim, including the tail — for both the
    initial call and the single bounded correction. A correction appends
    the compacted diagnostics plus the previous candidate and requires one
    complete regenerated chapter product.
    """
    request = _require_request(request)
    if validation_errors is not None and previous_candidate is None:
        raise PersistenceError("a correction re-ask requires the previous candidate")
    if validation_errors is not None and not isinstance(validation_errors, list):
        raise PersistenceError("validation_errors must be a list of strings")

    correction = ""
    if validation_errors is not None:
        diagnostics = compact_validation_errors(validation_errors)
        correction = (
            "\nCORRECTION RE-ASK\n"
            "The prior chapter product failed deterministic validation. Return one "
            "complete corrected chapter product covering the SAME whole chapter below: "
            "full faithful translation plus the joint bundle, mentions, and "
            "record_sources. Repair every listed issue. Do NOT translate only the "
            "failed segment and splice it back, and do NOT drop the chapter tail.\n"
            "VALIDATION DIAGNOSTICS\n"
            + _json(diagnostics)
            + "\nPREVIOUS CANDIDATE\n"
            + _json(previous_candidate)
            + "\n"
        )

    header = {
        "chapter_id": request["chapter_id"],
        "chapter_index": request.get("chapter_index"),
        "title": request.get("title"),
        "revision_id": request["revision_id"],
        "document_id": request.get("document_id"),
        "source_sha256": request["source_sha256"],
        "normalized_sha256": request["normalized_sha256"],
        "plan_version": request.get("plan_version"),
        "limits": request.get("limits"),
        "schema_versions": request.get("schema_versions"),
        "prompt_version": PROMPT_VERSION,
    }
    return f'''You are Chronicle whole-chapter joint translation and extraction. Return exactly one compact JSON object and no prose/Markdown.

{JOINT_PRODUCT_GUIDE}

{REFERENCE_RULES}

{TRANSLATION_RULES}
{correction}
CHAPTER REQUEST
{_json(header)}

REQUIRED BLOCKS (every listed block must be covered by translation source_block_ids)
{_json(request["required_block_ids"])}

CHAPTER BLOCKS (the whole chapter; ranges use {OFFSET_UNIT})
{_render_blocks(request)}

FULL CHAPTER TEXT (verbatim; the chapter tail below is part of the input)
---BEGIN CHAPTER---
{request["normalized_text"]}
---END CHAPTER---
'''
