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

#: Whole-chapter prompt template version (0.1 joint product).
#: Persisted earlier runs retain their own template version and fingerprint.
PROMPT_VERSION = "c2r1-chapter-prompt-v11"

#: Reading-annotation (0.2) prompt template version. Bound into the
#: producing run of every accepted 0.2 artifact so 0.1/0.2 runs stay
#: distinguishable in run history.
READING_PROMPT_VERSION = "c2r2-chapter-prompt-v6"

#: Person-state (0.3) prompt template version. Bound into the producing run
#: of every accepted 0.3 artifact so 0.1/0.2/0.3 runs stay distinguishable.
PERSON_STATE_PROMPT_VERSION = "c2r3-chapter-prompt-v4"

#: Joint candidate marker the model must emit (T01 contract).
CANDIDATE_SCHEMA = "chronicle.chapter-candidate"
CANDIDATE_VERSION = "0.1"

#: Reading-annotation candidate version (second round).
READING_CANDIDATE_VERSION = "0.2"

#: Person-state candidate version (third round); registered production.
PERSON_STATE_CANDIDATE_VERSION = "0.3"

#: Every candidate version this renderer can address.
SUPPORTED_CANDIDATE_VERSIONS = (
    CANDIDATE_VERSION,
    READING_CANDIDATE_VERSION,
    PERSON_STATE_CANDIDATE_VERSION,
)

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
- Separate an occurrence from a detail about it. Keep one coherent battle,
  campaign, diplomatic episode, or political transition together when the
  chapter supports that scope; do not create a separate Event for every sentence,
  quotation, evaluation, or background state. A person's office or a place's
  affiliation may be a Claim on that Entity without inventing a new Event.
  Distinct occurrences must remain distinct; do not merge merely because a
  broader title looks cleaner. Preserve source-supported subordinate episodes
  with parent_event_ref where appropriate.
- Extraction records are not public navigation anchors. Important reader entry
  points are selected and reviewed later from the synthesized narrative; do not
  label every appointment, remark, or minor movement as a major event.
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

WHOLE_CHAPTER_SEMANTIC_GUIDE = r'''WHOLE-CHAPTER SEMANTIC CHECK (interpretation guidance, not additional source evidence)
在输出前，以完整章节为一个上下文核对下面各项；只输出最终联合 JSON，不输出分析过程。
- 区分叙事正文、史家按语、不同著作的引文、人物的书信奏表。每处“我／臣／父／其”等
  都从该处叙述者或说话者解释，切换引文后重新确认；不得默认属于传记主人公。
- 古文省略主语时，核对动作的施行者、承受者及评价对象，结合前后文和同章嵌注承接。
  进军、到达、撤退、任命、归附等不能都接到最近出现的人名或主人公身上。被评价者
  和作出评价者、上级和下属、授予者和接受者不可对调。
- 人名简称必须沿本章已出现的全名和上下文消歧；只写名字时，不因主人公姓氏或常识
  补出一个姓。身份能确认再用全名；不能确认则保留原称谓，并在 warnings 说明具体
  疑点。同一人的名、字、尊称或谥号不可误当成同一交接或对话的两个人。
- 古词按当时语境和本章注释解释，注意器物、亲属称谓、官名、虚词、被动及使动结构。
  避免用现代最常见词义直译；若同章已说明该称谓或词义，译文必须与该说明相容。
  不把书名、纬书或典籍类别误译成地点，也不添加原文没有的动机或因果。
- 完整翻译每条现存嵌注，包括举证的历史事例、音读／字义解释、作者署名和不同说法。
  保留注释在相应正文附近的归属，不能仅列出 source_block_ids 代替翻译，也不能以
  “另有异说／作了解释”等一句话替代具体内容。保持原文的怀疑、传闻及引述口吻。
- 通读译文核对叙事连续性：人物在何处、是哪一方军队行动、称谓是否同人、同章解释
  是否自相矛盾。以原文为准修正理解；不得为了消除史料本身的分歧擅自改写史料。
- 联合提取还需要有证据的事实：Event 标识发生的一件事，标题、参与者和角色不能
  代替 Claim 中可核对的断言。逐一检查本章主要人物／地点／政权及重要事件所支持的
  任职、归属、驻地、行动结果等事实，用现有 Claim 的 subject、predicate、object、
  evidence 保存；证据要支持该主体和该断言，保留原文归属，不把劝进、传闻或征兆当
  成已证实事实。没有可支持断言时允许 []，不为了凑数制造 Claim，也不为每个细节
  新建 Event。相同对象沿用同一章内 temp_id；导航锚点由后续综合正文审核选择，
  读取只消费已发布结果。
- 日历成分来自章内其他语句时，保留原文有据的 era／era_year／season／month／day，
  并在 inherited_fields 标记继承的字段。time.original_text 只能是实际连续出现的
  原文日期表达；缩短它以修复引用时，不能忘记同步更新继承声明。
只把当前完整原章作为事实依据；上述指引不是要求补入章外的历史知识。'''

READING_ANNOTATION_GUIDE = r'''READING ANNOTATION SHAPE (0.2 only; every unit is explained by the WHOLE chapter)
Add one top-level "reading" object beside bundle/translation/mentions/record_sources:
reading: {units:[...], warnings:[...]}. reading.units MUST contain exactly one unit per
translation block, in the SAME order, no missing or duplicate block_id.
Read the whole chapter before producing the joint product. Carry its supported
persons, places, polities and coherent events into the bundle and translation refs,
then annotate the translated passages using those same refs. Unknown dates do not
erase the people or places a passage clearly identifies. Empty arrays are legitimate
only where that passage supplies no supported object or event phrase; they are not
a shortcut for an entire biography, campaign, or annalistic chapter.
Use natural paragraph breaks at changes of narrative time or action, usually 80-500
Chinese characters; longer quotations may remain together. This is one whole-chapter
response, never independent paragraph translations. Do not create an Event for each
paragraph or turn minor details into navigation anchors.
Paragraph length is a layout guide, NOT a chapter-length limit: create as many
paragraphs as the complete source needs. Listing a source_block_id does not translate
that block. Preserve the full content of speeches, letters, memorials, decrees and
embedded annotations, including each argument and its attribution. Do not replace
them with statements such as "群臣上表劝进" or "史书有不同记载". Those are summaries,
not translations of the actual memorial or each cited account.
SOURCE DATE FIELDS: in each non-null Event.time.source_calendar, return system, era,
era_year, season, month, day, inherited_fields. Use null for unsupported components;
season is spring|summer|autumn|winter|null, month is 1..12|null, day may preserve a
source sexagenary label. Preserve the regnal era/year even without a Gregorian
conversion (normalized may be null). A date heading may govern the following main
narrative in this same chapter until an explicit transition; record context-derived
components in inherited_fields and ground them in the actual source. Missing a
repeated year is not by itself evidence that the chapter leaves the date unknown.
Keep time.original_text a VERBATIM temporal expression; never stitch a new date
phrase from separate source passages. Do not borrow dates from cited flashbacks or
invent a Gregorian year/month/day. A genuinely undated event keeps time null.
reading unit (field names are exact):
  block_id: the translation block this unit annotates.
  narrative_time: {mode, event_refs[], from_block_id, source_selections[]}.
    mode "events":  the block narrates current events; event_refs lists the events whose
      own source time is observed here, and must be non-empty and a subset of
      current_event_refs; from_block_id is null.
    mode "inherit": the block continues an earlier block's time; from_block_id names an
      EARLIER block of THIS chapter; BOTH event_refs and current_event_refs are empty,
      and event_roles must also be empty. The chain must end at an "events" block.
      If this block narrates a dated event with current_event_refs, use "events"
      instead. Inherit only a source-supported continuation, never a convenient date.
    mode "mixed":   the block deliberately observes several current events at once;
      event_refs lists every current_event_ref and there are at least two.
    mode "unknown": the block has no usable time; event_refs and current_event_refs are
      empty, from_block_id null, source_selections empty.
    Do NOT invent Gregorian time. Keep the event's own source_calendar fields and
    verbatim original_text distinct as described above; when the event has
    no usable time keep it unknown rather than defaulting to a nearby year. A
    retrospective / foreshadow / background span never supplies the unit's current time.
    source_selections must contain 1..16 verbatim source selections for non-unknown
    modes and be empty for unknown.
  current_event_refs: ONLY the events this block is currently narrating (not every event
    mentioned); each must be an existing evt_* in this block's translation event_refs.
  event_spans: a list of {span_id, selection, status, target_ref, candidate_refs,
    relation, source_selections}. span_id is es_001, es_002, ... Each span points at the
    exact words in THIS translation block: selection = {quote, occurrence} where quote
    is copied character-for-character from that unit's translated block text and
    occurrence counts from 1 within that block. status resolved (single target_ref,
    no candidate_refs) | ambiguous (target_ref null, >=2 candidate_refs) | unresolved
    (target_ref null). relation is current | retrospective | foreshadow | background |
    uncertain. Spans must not overlap each other and must not rewrite the block text.
    source_selections (1..16) support the span from the ORIGINAL source. Select the
    translated event name or short occurrence phrase (for example a supported
    battle phrase), not a bare person's name as a proxy for that person's event.
    Include a grounded event phrase when present; use [] if none is supported.
  context_entities: a list of {entity_ref, importance, source_selections,
    event_roles}. entity_ref is an existing ent_* supported by this block's
    entity_refs or by a current event's participants/places; importance is primary|other.
    source_selections (1..16) prove the source supports this object in this block.
    event_roles: [{event_ref, participant_index}] where event_ref is a current_event_ref
    and participant_index is that entity's original participant position in the event
    (0-based); the program copies the role text from the participant record, so never
    write a role string yourself. Find the event whose temp_id equals event_ref,
    then verify event.participants[participant_index].entity_ref equals this
    context entity_ref. Index 0 is not a default. A place in event.places is NOT a
    participant; keep event_roles [] unless that same entity actually occurs in the
    event's participants array. Include the main people/places actually involved
    here, even when narrative_time is unknown or inherit (then event_roles is []).
    Do not include every chapter entity or promote someone mentioned only as distant
    background to primary. Use [] where this passage has no supported context entity.
  Never drop the unit, invent a canonical ID, or move a reading annotation to a
  later page/request. When correcting a failure, retain all supported events,
  context entities and spans; repair the faulty references/selections rather than
  emptying the arrays to avoid validation.
COORDINATE / ID DISCIPLINE: the model writes only block_id, evt_*/ent_* temp refs, span
ids (es_*) and {quote, occurrence} selections. Never write start/end offsets, unit_id,
stream_id, canonical_id, UUIDs, or URLs — the program computes all coordinates and IDs.
READING UNIT EXAMPLE (shape only):
{"block_id":"t_001","narrative_time":{"mode":"events","event_refs":["evt_001"],
 "from_block_id":null,"source_selections":[{"first_block_id":"b_001","last_block_id":"b_001",
 "quote":"建安十三年","occurrence":1}]},"current_event_refs":["evt_001"],
 "event_spans":[{"span_id":"es_001","selection":{"quote":"进驻江陵","occurrence":1},
 "status":"resolved","target_ref":"evt_001","candidate_refs":[],"relation":"current",
 "source_selections":[{"first_block_id":"b_001","last_block_id":"b_001","quote":"屯江陵",
 "occurrence":1}]}],"context_entities":[{"entity_ref":"ent_001","importance":"primary",
 "source_selections":[{"first_block_id":"b_001","last_block_id":"b_001","quote":"曹操",
 "occurrence":1}],"event_roles":[{"event_ref":"evt_001","participant_index":0}]}]}'''

PERSON_STATE_GUIDE = r'''PERSON STATE SHAPE (0.3 only; the same whole chapter, with reading annotations kept)
Add one top-level "person_states" object beside bundle/translation/mentions/record_sources/reading:
person_states: {phases:[], phase_orders:[], unit_phases:[], facts:[], continuities:[], disagreements:[]}.
Every local ref below is chapter-local and must close inside this chapter; never return a canonical
UUID, a supported/certainty verdict, a stream/unit ID or a URL. A fact is candidate evidence only.
  phases[]: {phase_id:"ph_001", label, event_refs:[{kind:"event",ref:"evt_*"}], source_selections:[...]}.
    A phase is one source-supported narrative context inside this chapter (a stretch of narrative,
    not a new calendar). label is a short source label; never invent a year. event_refs names existing
    evt_* this phase narrates (may be empty). source_selections 1..16. At most 512 phases.
  phase_orders[]: {assertion_id:"po_001", earlier_phase_ref:"ph_*", later_phase_ref:"ph_*",
    source_selections:[...]}. Only add an edge when the source itself proves the earlier/later order
    (a later appointment, a before/after turn). Never derive precedence from Gregorian years,
    from "same month", from the chapter's paragraph order, or from a shared canonical event.
    The edges must stay acyclic. No edge for an unknown or disputed order. At most 1024.
  unit_phases[]: exactly one binding per translation block, in the SAME order and with the same
    block_id as translation.blocks. {block_id, mode, phase_refs:[...], source_selections:[...]}.
    mode "single": exactly one phase_ref. mode "process": >=2 ordered phase_refs experienced within
      the block (keep the whole process, never only the last identity). mode "ambiguous": >=1
      phase_ref where the source genuinely leaves several readings. mode "unknown": no phase_refs and
      no source_selections (do not inherit the previous block's phase). A phase is a candidate, so
      every phase must be referenced by at least one unit; never bind a unit to a foreign chapter id.
  facts[]: {fact_id:"pf_001", person_ref:{kind:"entity",ref:"ent_*"}, dimension:office|title|affiliation,
    value_ref:{kind:"entity",ref:"ent_*"}|null, relation:"serves"|"attached_to"|null,
    target_ref:{kind:"entity",ref:"ent_*"}|null, operation:start|end|attest,
    qualification:ordinary|recommendation|self_designation|posthumous|reported, phase_ref:"ph_*",
    claim_refs:[{kind:"claim",ref:"clm_*"}], source_selections:[...],
    attribution:narrator|quotation|annotation|hearsay}. At most 512 facts.
    office/title facts carry a value_ref to an office/other entity and keep relation/target_ref null.
    affiliation facts carry relation serves|attached_to and a target_ref to a person/polity/
    organization (never a place) and keep value_ref null.
    operation start = a source-supported taking-up / attachment; end = the proven end of that exact
    item; attest = only that this record exists in the phase (use it when the source does not prove
    a new start/end). One appointment does not end other offices; a turn of allegiance ends only the
    relation it proves. qualification recommendation or posthumous may ONLY use operation attest and
    must never establish a current office; self_designation/reported keep their qualifier.
    attribution narrator|quotation|annotation|hearsay must match where the record comes from: a
    quoted self-report (for example a memorial saying seals were returned) stays quotation/annotation
    and is never rewritten as the narrator's own fact for the whole realm.
    SUBJECT DISCIPLINE: person_ref is the person the record is about — never an ancestor or father
    (父祖), never a ruler acting on the person, and never the speaker of a quotation. Each fact must
    trace to verbatim source: source_selections 1..16 must quote the chapter text that supports THIS
    subject/value/relation, not a nearby mention of the same surname.
    ROLE vs LONG-TERM STATE: a one-off action role (for example 前部大督 for one campaign) is not a
    lasting office; record lasting offices, titles and relations as facts, and do not turn an action
    role into an office or inherit it into later phases. Different offices/titles/relations coexist;
    do not collapse them to the highest one, and do not let a later title overwrite an earlier phase's
    identity. Acquisition of a new post does not clear the others.
  continuities[]: {assertion_id:"pc_001", fact_ref:"pf_*", start_phase_ref:"ph_*",
    end_phase_ref:"ph_*"|null, source_selections:[...]}. Only claim a proven continuous interval
    when the source supports it; end_phase_ref must be a phase the source proves later than start
    (null means no proven end, which is NOT an open-ended certainty). At most 1024.
  disagreements[]: {assertion_id:"pd_001", topic, fact_refs:[two or more pf_*], phase_refs:[...],
    source_selections:[...]}. Only record a disagreement for the same question and comparable phase
    where the chapter itself gives different claims; different offices, different phases or different
    relations are not disagreements. topic is a short stable label. At most 1024.
  UNASSESSED / ID DISCIPLINE: never return supported, uncertain/disputed/rejected assessments,
    certainty colors, confidence, canonical_id, stream_id, unit_id, publication_id, hashes or URLs.
    The model returns local refs and source support only; the program decides assessment and identity.
PERSON STATE EXAMPLE (shape only, not history): a phase ph_001 grounded on "策授瑜建威中郎將", a
unit_phases single binding to it, and one office fact with person_ref ent_a, value_ref ent_b,
operation "start", qualification "ordinary", attribution "narrator".'''

_MAX_CORRECTION_ERRORS = 20
_MAX_CORRECTION_DIAGNOSTIC_CHARS = 1800
# The reading/state product has more independently grounded fields than 0.1.
# The v4 live failure had 16 errors, but the old 1,800-character envelope hid
# two distinct context selectors. Keep a bounded, versioned envelope that can
# carry this whole repair; the final rendered prompt still obeys ChapterLimits.
_MAX_READING_CORRECTION_DIAGNOSTIC_CHARS = 4096
_MAX_ONE_DIAGNOSTIC_CHARS = 280
_INDEX_PATH_RE = re.compile(r"/(?:0|[1-9][0-9]*)(?=/|:|$)")
_WS_RE = re.compile(r"\s+")
_ANCHOR_MISMATCH_RE = re.compile(
    r"quote occurs (\d+) time\(s\) in (\[[^\]]+\]) but occurrence=(\d+) was requested; "
    r"quote occurs (\d+) time\(s\) chapter-wide, first in block ('[^']+')"
    r": re-point first/last_block_id to the enclosing block\(s\) and recount"
)


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _translation_chars(candidate: Any) -> int:
    """Total translated characters in a previous candidate, or 0 if absent."""
    if not isinstance(candidate, dict):
        return 0
    translation = candidate.get("translation")
    if not isinstance(translation, dict):
        return 0
    blocks = translation.get("blocks")
    if not isinstance(blocks, list):
        return 0
    total = 0
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            total += len(block["text"])
    return total


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


def compact_validation_errors(
    errors: list[str], *, candidate_version: str = CANDIDATE_VERSION
) -> list[str]:
    """Bound model-facing repair diagnostics; full history stays untouched.

    The complete validator report remains in the extraction attempt
    history. Only this compacted copy is sent back to the model so a long
    tail of repeated schema paths cannot consume the correction budget.
    Record temp ids stay verbatim so every diagnostic remains mapped to
    its failing record (see _diagnostic_signature).
    """
    if not isinstance(errors, list):
        return []
    reading_product = candidate_version in (
        READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION,
    )
    budget = (
        _MAX_READING_CORRECTION_DIAGNOSTIC_CHARS
        if reading_product else _MAX_CORRECTION_DIAGNOSTIC_CHARS
    )
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
        # Exact array indices are repair locations too. Distinct invalid rows
        # must not collapse into one /* message in the new reading/state prompt.
        if not reading_product:
            text = _diagnostic_signature(text)
        # Preserve each repair location, both match counts and the correct
        # source block hint without repeating a long generic instruction.
        # R2 live extraction lost every reading diagnostic after repeated anchor
        # failures exhausted this bounded prompt, so the correction could not
        # repair a known context selection. The full report stays unchanged.
        if reading_product:
            def anchor_hint(match: re.Match[str]) -> str:
                window_count, window, occurrence, total, first_block = match.groups()
                # A first match among many is not evidence for the intended
                # passage. Preserve a block hint only for a unique match.
                location = (
                    f", starts in {first_block}"
                    if total == "1" else " (ambiguous; use passage context)"
                )
                return (
                    f"quote: {window_count} matches in {window}, occurrence={occurrence}; "
                    f"{total} chapter matches{location}"
                )
            text = _ANCHOR_MISMATCH_RE.sub(anchor_hint, text)
        if len(text) > _MAX_ONE_DIAGNOSTIC_CHARS:
            text = text[: _MAX_ONE_DIAGNOSTIC_CHARS - 24].rstrip() + " … [diagnostic shortened]"
        if text in seen:
            omitted += 1
            continue
        projected = chars + len(text) + (1 if kept else 0)
        if len(kept) >= _MAX_CORRECTION_ERRORS or projected > budget:
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
        if chars + len(note) + 1 <= budget + 160:
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


def request_candidate_version(request: dict[str, Any]) -> str:
    """Return the candidate version a request must produce.

    Requests that do not declare a candidate version default to the
    registered production version (0.3 person-state joint product); an
    unregistered version fails closed here instead of guessing.
    """
    versions = request.get("schema_versions") if isinstance(request, dict) else None
    if isinstance(versions, dict) and isinstance(versions.get("candidate"), str):
        version = versions["candidate"]
    else:
        version = PERSON_STATE_CANDIDATE_VERSION
    if version not in SUPPORTED_CANDIDATE_VERSIONS:
        raise PersistenceError(f"unsupported chapter-candidate version {version!r}")
    return version


def prompt_version_for(candidate_version: str) -> str:
    """Return the prompt template version bound to a candidate version."""
    if candidate_version == PERSON_STATE_CANDIDATE_VERSION:
        return PERSON_STATE_PROMPT_VERSION
    if candidate_version == READING_CANDIDATE_VERSION:
        return READING_PROMPT_VERSION
    if candidate_version == CANDIDATE_VERSION:
        return PROMPT_VERSION
    raise PersistenceError(f"unsupported chapter-candidate version {candidate_version!r}")


def _joint_guide_for(candidate_version: str) -> str:
    """Render the joint-product shape guide for one candidate version."""
    if candidate_version == CANDIDATE_VERSION:
        return JOINT_PRODUCT_GUIDE
    if candidate_version == PERSON_STATE_CANDIDATE_VERSION:
        return JOINT_PRODUCT_GUIDE.replace(
            'version="0.1"', 'version="0.3"'
        ).replace(
            "bundle, translation, mentions, record_sources, warnings.",
            "bundle, translation, mentions, record_sources, reading, person_states, warnings.",
        )
    return JOINT_PRODUCT_GUIDE.replace(
        'version="0.1"', 'version="0.2"'
    ).replace(
        "bundle, translation, mentions, record_sources, warnings.",
        "bundle, translation, mentions, record_sources, reading, warnings.",
    )


def render_chapter_prompt(
    request: dict[str, Any],
    *,
    validation_errors: list[str] | None = None,
    previous_candidate: dict[str, Any] | None = None,
    preserve_translation: bool = False,
) -> str:
    """Render the whole-chapter joint translation/extraction prompt.

    The prompt always carries the complete chapter — every block and the
    full normalized text verbatim, including the tail — for both the
    initial call and the single bounded correction. A correction appends
    the compacted diagnostics plus the previous candidate and requires one
    complete regenerated chapter product. Requests that declare candidate
    version 0.2 carry the reading-annotation guide; version 0.3 carries the
    reading guide plus the person-state guide; both the initial and the
    correction round explain every unit and phase from the whole chapter.
    """
    request = _require_request(request)
    candidate_version = request_candidate_version(request)
    prompt_version = prompt_version_for(candidate_version)
    joint_guide = _joint_guide_for(candidate_version)
    reading_guide = (
        "\n\n" + READING_ANNOTATION_GUIDE
        if candidate_version in (READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION)
        else ""
    )
    # Semantic guidance belongs to initial/full-chapter generation. A metadata
    # correction has no authority to rewrite the preserved prose, even if the
    # model notices a semantic problem in it; content review remains separate.
    semantic_guide = (
        "\n" + WHOLE_CHAPTER_SEMANTIC_GUIDE + "\n"
        if candidate_version in (READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION)
        and not preserve_translation
        else ""
    )
    if candidate_version in (READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION):
        reading_guide += (
            f"\nFULL-TEXT SCALE: this chapter contains {len(request['normalized_text'])} "
            f"source characters and {len(request['required_block_ids'])} required source blocks. "
            "A full modern-Chinese translation normally needs comparable or greater "
            "space. A much shorter overview is not an acceptable whole-chapter product. "
            "Complete the entire translation first, then annotate it; never trade away "
            "source passages to fit the bundle or reading metadata into the response.\n"
        )
    if candidate_version == PERSON_STATE_CANDIDATE_VERSION:
        reading_guide = reading_guide.replace(
            "READING ANNOTATION SHAPE (0.2 only;",
            "READING ANNOTATION SHAPE (0.3 inherits 0.2;",
            1,
        )
        reading_guide += "\n\n" + PERSON_STATE_GUIDE
    if validation_errors is not None and previous_candidate is None:
        raise PersistenceError("a correction re-ask requires the previous candidate")
    if validation_errors is not None and not isinstance(validation_errors, list):
        raise PersistenceError("validation_errors must be a list of strings")
    if preserve_translation and (
        validation_errors is None or candidate_version == CANDIDATE_VERSION
    ):
        raise PersistenceError("translation preservation requires a 0.2/0.3 correction")

    correction = ""
    if validation_errors is not None:
        diagnostics = compact_validation_errors(validation_errors, candidate_version=candidate_version)
        prev_chars = _translation_chars(previous_candidate)
        if candidate_version == PERSON_STATE_CANDIDATE_VERSION:
            repaired = (
                "the joint bundle, mentions, record_sources, reading annotations "
                "and person_states"
            )
        elif candidate_version == READING_CANDIDATE_VERSION:
            repaired = "the joint bundle, mentions, record_sources and reading annotations"
        else:
            repaired = "the joint bundle, mentions and record_sources"
        preserve = ""
        if preserve_translation:
            preserve = (
                "METADATA CORRECTION ONLY: the reported errors can be repaired without "
                "rewriting the prose. Copy EVERY translation.blocks entry's block_id "
                "and text verbatim, in the same order, from PREVIOUS CANDIDATE. "
                "Do not merge, split, remove, rename, shorten, expand or reword these "
                "blocks; the program compares their IDs, order and exact text. "
                "You may repair source_block_ids, entity_refs, event_refs and all "
                "dependent annotations, including moving a span to the block that "
                "actually contains its quote. Select literal, contiguous quotes; "
                "never rewrite prose to make a reference match. Retain supported "
                "entities, events and annotations; do not empty annotation arrays "
                "to silence errors. When repairing time.original_text, also mark "
                "calendar fields recovered from other source phrases in "
                "inherited_fields; shortening a fabricated date phrase does not "
                "make its retained contextual era/year explicit. This restriction "
                "preserves the draft during metadata repair; it does not certify "
                "translation accuracy or completeness.\n"
            )
        elif prev_chars:
            # Live regression (C2-R1-T19 live rounds): the bounded correction
            # re-ask sometimes returned a condensed summary that still passed
            # structural validation, shrinking a full initial translation
            # (e.g. 16404 chars) to a fraction (e.g. 7318). The contract is
            # unchanged — only the re-ask now names the prior full length and
            # forbids condensing it. Never a validation gate; a repair signal.
            if candidate_version in (READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION):
                dependent_annotations = (
                    "dependent reading annotations and person_states"
                    if candidate_version == PERSON_STATE_CANDIDATE_VERSION
                    else "dependent reading annotations"
                )
                preserve = (
                    f"FIDELITY: {prev_chars} characters is the previous draft's length, "
                    "not evidence that it translates the whole chapter. Keep every "
                    "faithful translated passage, its block_id and order. "
                    "A reference-validation report does not certify completeness: "
                    "check the entire source again and expand any omitted or condensed "
                    "passages, including quoted documents and annotations. Update "
                    f"{dependent_annotations} if expansion is necessary. Never "
                    "shorten the translation while repairing references.\n"
                )
            else:
                preserve = (
                    f"FIDELITY: the previous translation had {prev_chars} characters. "
                    "The corrected product MUST keep the whole translation at that "
                    "full length — faithfully translate every sentence and every "
                    "embedded annotation. Do NOT summarize, condense, shorten, or "
                    "replace any passage with an overview; only repair the listed "
                    "issues while preserving (or lengthening) the full translation.\n"
                    "TRANSLATION IS ALREADY CORRECT: copy the PREVIOUS CANDIDATE's "
                    "translation.blocks through unchanged (same block_ids, same order, "
                    "same full text). Do NOT rewrite, shorten, or re-summarize the "
                    "translation; the diagnostics below concern the joint bundle, "
                    "mentions, record_sources, reading and time fields — repair those "
                    "and keep the translation verbatim.\n"
                )
        correction = (
            "\nCORRECTION RE-ASK\n"
            "The prior chapter product failed deterministic validation. Return one "
            "complete corrected chapter product covering the SAME whole chapter below: "
            "full faithful translation plus " + repaired + ". Repair every listed "
            "issue. Do NOT translate only the failed segment and splice it back, and "
            "do NOT drop the chapter tail.\n"
            + preserve
            + "VALIDATION DIAGNOSTICS\n"
            + _json(diagnostics)
            + "\nPREVIOUS CANDIDATE\n"
            + _json(previous_candidate)
            + "\n"
        )
        if preserve_translation:
            correction += (
                "FINAL REPAIR CHECK: return the complete joint JSON product. Keep "
                "every previous translation block ID, its order and full text "
                "unchanged; repair the listed metadata against the whole chapter.\n"
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
        "prompt_version": prompt_version,
    }
    # Keep the frozen 0.1 rendering byte-for-byte. For reading/state products,
    # put the actual repair task AFTER the complete source, where it is not
    # displaced by another full-chapter translation instruction/input.
    correction_before = correction if candidate_version == CANDIDATE_VERSION else ""
    correction_after = correction if candidate_version != CANDIDATE_VERSION else ""
    return f'''You are Chronicle whole-chapter joint translation and extraction. Return exactly one compact JSON object and no prose/Markdown.

{joint_guide}{reading_guide}

{REFERENCE_RULES}

{TRANSLATION_RULES}
{correction_before}
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
''' + semantic_guide + correction_after
