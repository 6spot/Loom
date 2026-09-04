"""Chronicle C1-T5 structure detection, semantic segmentation, and context state.

Application-owned product logic (Architecture Amendment 0006): pure
deterministic text processing with no database, model, or network access.
Persistence helpers in this module take a caller-owned connection and reuse
the C1-T1 control-plane store (``control_plane.py``); they never touch Loom
Runtime/World/Timeline/Work/Binding state.

Contract summary:

- Offsets are **character offsets into the normalized revision text** (the
  ``str`` returned by ``documents.decode_source``: strict UTF-8, one leading
  BOM stripped, CRLF/CR normalized to LF). The unit is recorded as
  ``OFFSET_UNIT`` on every plan/checkpoint so a reader never mistakes it
  for byte offsets into the stored file. ``text[start:end]`` reconstructs
  the exact chunk; ``content_sha256`` (SHA-256 over the UTF-8 bytes of that
  slice) proves it.
- Segmentation is a pure function of ``(text, config, versions)``. Unchanged
  input plus the same ``SEGMENTATION_VERSION`` reproduces identical
  sections, chunks, hashes, and context states; ``plan_sha256`` in the
  manifest is the reproducibility proof.
- Natural boundaries win: detected headings open sections; paragraphs, then
  lines, then sentence punctuation, then a deterministic hard cut bound the
  chunk size. Blind fixed-size slicing is only the final fallback for a
  unit that exceeds the budget on its own.
- Chunk overlap defaults to zero duplicated characters. Cross-boundary
  continuity travels in the versioned ``ContextState`` (bounded previous /
  next boundary strings plus inherited time, entity/place surfaces, recent
  events, and explicitly uncertain coreference hints) instead of
  RAG-style heavy overlap.
- Chunks are processing units, never historical identity/truth boundaries:
  every chunk checkpoint carries ``authoritative: False``. Context state is
  a processing aid for C1-T6 extraction; it never becomes historical
  authority and never invents precision — inherited time keeps the original
  expression verbatim with ``scope: "inherited"``, and coreference links
  are flagged ``uncertain: true`` surface hints.
- Deterministic fallback: a document with no detectable structure becomes
  one ``document``-kind section (``fallback: "single-section"`` in the
  manifest). No model is called in C1-T5 (``MODEL_VERSION`` records the
  deterministic pipeline); model/prompt version slots exist so C1-T6 can
  fill them without changing this schema.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from common import PersistenceConflict, PersistenceError

#: Version of the segmentation algorithm itself (sections + chunk plans).
SEGMENTATION_VERSION = "c1t5-v1"

#: Version of the structure-detection pattern set.
STRUCTURE_VERSION = "c1t5-struct-v1"

#: Version of the ContextState input/output schema.
CONTEXT_VERSION = "c1t5-ctx-v1"

#: No model is called in C1-T5; the deterministic pipeline is the fallback.
#: C1-T6 extraction records its real model version alongside these slots.
MODEL_VERSION = "none-deterministic-v1"

#: No prompt is rendered in C1-T5; the slot stays versioned for C1-T6.
PROMPT_VERSION = "none-c1t5-v1"

#: Offset unit for every source_start/source_end produced here.
OFFSET_UNIT = "chars-normalized-utf8"

#: Marker proving chunks are processing units, never historical authority.
NON_AUTHORITATIVE_NOTE = (
    "chunk is a model-processing unit, not a historical identity/truth "
    "boundary; canonical identity remains owned by the C0 "
    "staged/resolution/canonical path"
)


# ---------------------------------------------------------------------------
# Configuration and budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentationConfig:
    """TunableKnobs for one segmentation run; persisted verbatim in checkpoints."""

    max_chunk_chars: int = 2000
    overlap_chars: int = 0
    boundary_context_chars: int = 200
    max_input_chars: int = 8000
    reserved_prompt_chars: int = 1500
    reserved_context_chars: int = 1000
    reserved_output_chars: int = 1500
    max_entities: int = 16
    max_places: int = 16
    max_events: int = 8
    max_time_exprs: int = 8

    def __post_init__(self) -> None:
        for name in (
            "max_chunk_chars",
            "boundary_context_chars",
            "max_input_chars",
            "reserved_prompt_chars",
            "reserved_context_chars",
            "reserved_output_chars",
            "max_entities",
            "max_places",
            "max_events",
            "max_time_exprs",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise PersistenceError(f"{name} must be a non-negative integer")
        if self.max_chunk_chars < 1:
            raise PersistenceError("max_chunk_chars must be a positive integer")
        if self.overlap_chars > self.max_chunk_chars:
            raise PersistenceError("overlap_chars must not exceed max_chunk_chars")
        reserved = (
            self.reserved_prompt_chars
            + self.reserved_context_chars
            + self.reserved_output_chars
        )
        if reserved >= self.max_input_chars:
            raise PersistenceError(
                "reserved prompt/context/output space "
                f"({reserved} chars) must leave room for chunk text "
                f"within max_input_chars ({self.max_input_chars})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_chunk_chars": self.max_chunk_chars,
            "overlap_chars": self.overlap_chars,
            "boundary_context_chars": self.boundary_context_chars,
            "max_input_chars": self.max_input_chars,
            "reserved_prompt_chars": self.reserved_prompt_chars,
            "reserved_context_chars": self.reserved_context_chars,
            "reserved_output_chars": self.reserved_output_chars,
            "max_entities": self.max_entities,
            "max_places": self.max_places,
            "max_events": self.max_events,
            "max_time_exprs": self.max_time_exprs,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SegmentationConfig":
        if not isinstance(value, dict):
            raise PersistenceError("segmentation config must be a JSON object")
        try:
            return cls(**{k: value[k] for k in cls().to_dict() if k in value})
        except TypeError as exc:
            raise PersistenceError(f"invalid segmentation config: {exc}") from exc


def check_budgets(
    chunk_chars: int, context_chars: int, config: SegmentationConfig
) -> dict[str, Any]:
    """Account prompt/context/chunk/output space against the input budget.

    Returns a report dict; ``fits`` is False (fail closed downstream) when
    the chunk plus serialized context plus reserves exceed ``max_input``.
    """
    if chunk_chars < 0 or context_chars < 0:
        raise PersistenceError("budget inputs must be non-negative integers")
    total = (
        config.reserved_prompt_chars
        + context_chars
        + chunk_chars
        + config.reserved_output_chars
    )
    return {
        "max_input_chars": config.max_input_chars,
        "reserved_prompt_chars": config.reserved_prompt_chars,
        "context_chars": context_chars,
        "chunk_chars": chunk_chars,
        "reserved_output_chars": config.reserved_output_chars,
        "total_chars": total,
        "headroom_chars": config.max_input_chars - total,
        "fits": total <= config.max_input_chars,
    }


def ensure_budgets(
    chunk_chars: int, context_chars: int, config: SegmentationConfig
) -> dict[str, Any]:
    """Like :func:`check_budgets` but raises instead of returning ``fits``."""
    report = check_budgets(chunk_chars, context_chars, config)
    if not report["fits"]:
        raise PersistenceError(
            "chunk plus context exceeds the configured model input budget: "
            f"total {report['total_chars']} > max {config.max_input_chars} "
            f"(prompt reserve {config.reserved_prompt_chars}, context "
            f"{context_chars}, chunk {chunk_chars}, output reserve "
            f"{config.reserved_output_chars})"
        )
    return report


# ---------------------------------------------------------------------------
# Structure detection
# ---------------------------------------------------------------------------

_HEADING_PATTERNS: tuple[tuple[str, str], ...] = (
    # (kind, regex); first match in this order wins for a line.
    ("heading", r"^#{1,6}\s+(?P<label>.+?)\s*$"),
    ("volume", r"^(?P<label>卷.+?)\s*$"),
    (
        "chapter",
        r"^第[一二三四五六七八九十百千零\d\s]+[章回卷篇節部集](?P<label>.*)$",
    ),
    (
        "biography",
        r"^(?P<label>.{0,40}?(?:本紀|列傳|世家|載記|列传|本纪))"
        r"(?:第[一二三四五六七八九十百千零\d\s]+)?(?:\s|$|：|:)",
    ),
    (
        "treatise",
        r"^(?P<label>.{0,40}?(?:志|書|表|紀|传|誌))"
        r"(?:第[一二三四五六七八九十百千零\d\s]+)?(?:\s|$|：|:)",
    ),
)

_SENTENCE_END = re.compile(r"[^。！？!?…；;\n]+[。！？!?…；;\n]?|\n")


@dataclass(frozen=True)
class Section:
    section_index: int
    kind: str
    label: str
    source_start: int
    source_end: int


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    """Return ``(start, end, line)`` for every line; ``end`` excludes ``\\n``."""
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for raw in text.split("\n"):
        spans.append((pos, pos + len(raw), raw))
        pos += len(raw) + 1
    return spans


def _classify_heading(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    for kind, pattern in _HEADING_PATTERNS:
        match = re.match(pattern, stripped)
        if match is not None:
            label = match.groupdict().get("label", "") or stripped
            label = " ".join(label.strip().split())
            if not label:
                label = stripped
            return kind, label[:120]
    return None


def detect_structure(text: str) -> tuple[list[Section], dict[str, Any]]:
    """Detect volume/chapter/biography/heading boundaries in ``text``.

    Returns ``(sections, report)`` where ``report`` records the structure
    version, the per-kind counts, and whether the deterministic single-
    section fallback was used. Heading lines open the section they head;
    leading text before the first heading forms a ``preamble`` section only
    when it holds non-whitespace content.
    """
    if not isinstance(text, str):
        raise PersistenceError("revision text must be a string")
    if text == "":
        section = Section(0, "document", "全文", 0, 0)
        return [section], {
            "structure_version": STRUCTURE_VERSION,
            "heading_count": 0,
            "kinds": {"document": 1},
            "fallback": "single-section",
        }
    boundaries: list[tuple[int, str, str]] = []  # (offset, kind, label)
    for start, end, line in _line_spans(text):
        hit = _classify_heading(line)
        if hit is not None:
            kind, label = hit
            boundaries.append((start, kind, label))
    if not boundaries:
        section = Section(0, "document", "全文", 0, len(text))
        return [section], {
            "structure_version": STRUCTURE_VERSION,
            "heading_count": 0,
            "kinds": {"document": 1},
            "fallback": "single-section",
        }
    sections: list[Section] = []
    kinds: dict[str, int] = {}
    if boundaries[0][0] > 0 and text[: boundaries[0][0]].strip():
        sections.append(Section(0, "preamble", "序文", 0, boundaries[0][0]))
        kinds["preamble"] = 1
    for position, (start, kind, label) in enumerate(boundaries):
        end = (
            boundaries[position + 1][0]
            if position + 1 < len(boundaries)
            else len(text)
        )
        sections.append(
            Section(len(sections), kind, label, start, end)
        )
        kinds[kind] = kinds.get(kind, 0) + 1
    return sections, {
        "structure_version": STRUCTURE_VERSION,
        "heading_count": len(boundaries),
        "kinds": kinds,
        "fallback": None,
    }


# ---------------------------------------------------------------------------
# Semantic segmentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkPlan:
    chunk_index: int
    section_index: int
    source_start: int
    source_end: int
    overlap_prev_chars: int
    content_sha256: str
    boundary_head: str
    boundary_tail: str


def _split_units(block: str) -> list[str]:
    """Split a block into paragraph units, keeping trailing blank lines out."""
    units = [unit for unit in block.split("\n\n") if unit != ""]
    return units or [block]


def _split_sentences(unit: str) -> list[str]:
    pieces = [m.group(0) for m in _SENTENCE_END.finditer(unit) if m.group(0)]
    return pieces or [unit]


def _hard_cut(piece: str, limit: int) -> list[str]:
    return [piece[i : i + limit] for i in range(0, len(piece), limit)] or [""]


def _cut_block(block: str, limit: int) -> list[str]:
    """Cut one over-limit block on paragraph/line/sentence bounds, else hard."""
    chunks: list[str] = []
    for unit in _split_units(block):
        if len(unit) <= limit:
            chunks.append(unit)
            continue
        for line in unit.split("\n"):
            if len(line) <= limit:
                chunks.append(line)
                continue
            for sentence in _split_sentences(line):
                if len(sentence) <= limit:
                    chunks.append(sentence)
                else:
                    chunks.extend(_hard_cut(sentence, limit))
    return [c for c in chunks if c != ""] or [""]


def segment_section(
    text: str, section: Section, start_index: int, config: SegmentationConfig
) -> list[ChunkPlan]:
    """Segment one section, preferring natural boundaries over fixed cuts."""
    body = text[section.source_start : section.source_end]
    if body.strip() == "":
        return []
    limit = config.max_chunk_chars
    # Greedy accumulate paragraph units; an over-limit unit is cut finely.
    pieces: list[str] = []
    current = ""
    for unit in _split_units(body):
        if len(unit) > limit:
            if current != "":
                pieces.append(current)
                current = ""
            pieces.extend(_cut_block(unit, limit))
        elif current == "":
            current = unit
        elif len(current) + 2 + len(unit) <= limit:
            current = current + "\n\n" + unit
        else:
            pieces.append(current)
            current = unit
    if current != "":
        pieces.append(current)

    plans: list[ChunkPlan] = []
    cursor = section.source_start
    for position, piece in enumerate(pieces):
        # Locate the piece from the cursor so identical repeated text still
        # maps to exact offsets. Any skipped gap must be separator
        # whitespace (paragraph/line breaks consumed by splitting); it is
        # attributed to the previous chunk so chunks tile their section
        # exactly. Anything else is input/position drift: fail closed.
        found = text.find(piece, cursor, section.source_end)
        if found < 0:  # pragma: no cover - defensive; pieces came from body
            raise PersistenceError("segmentation lost its source position")
        gap = text[cursor:found]
        if gap.strip() != "":
            raise PersistenceError(
                "segmentation would leave source bytes uncovered; "
                "refusing to fork the locator history"
            )
        if plans and gap != "":
            previous = plans[-1]
            plans[-1] = ChunkPlan(
                chunk_index=previous.chunk_index,
                section_index=previous.section_index,
                source_start=previous.source_start,
                source_end=found,
                overlap_prev_chars=previous.overlap_prev_chars,
                content_sha256=sha256_text(text[previous.source_start : found]),
                boundary_head=previous.boundary_head,
                boundary_tail=text[
                    max(previous.source_start, found - config.boundary_context_chars) : found
                ],
            )
        start, end = found, found + len(piece)
        overlap = 0
        if position > 0 and config.overlap_chars > 0:
            overlap = min(config.overlap_chars, start - section.source_start)
            start -= overlap
            overlap = found - start
        head = text[start : min(end, start + config.boundary_context_chars)]
        tail = text[max(start, end - config.boundary_context_chars) : end]
        plans.append(
            ChunkPlan(
                chunk_index=start_index + len(plans),
                section_index=section.section_index,
                source_start=start,
                source_end=end,
                overlap_prev_chars=overlap,
                content_sha256=sha256_text(text[start:end]),
                boundary_head=head,
                boundary_tail=tail,
            )
        )
        cursor = found + len(piece)
    # Attribute trailing separator whitespace to the final chunk so the
    # section is tiled exactly (sections tile the revision; chunks tile
    # their section; nothing is silently uncovered).
    if plans and cursor < section.source_end:
        trailing = text[cursor : section.source_end]
        if trailing.strip() != "":  # pragma: no cover - defensive
            raise PersistenceError(
                "segmentation would leave source bytes uncovered; "
                "refusing to fork the locator history"
            )
        previous = plans[-1]
        plans[-1] = ChunkPlan(
            chunk_index=previous.chunk_index,
            section_index=previous.section_index,
            source_start=previous.source_start,
            source_end=section.source_end,
            overlap_prev_chars=previous.overlap_prev_chars,
            content_sha256=sha256_text(text[previous.source_start : section.source_end]),
            boundary_head=previous.boundary_head,
            boundary_tail=text[
                max(
                    previous.source_start,
                    section.source_end - config.boundary_context_chars,
                ) : section.source_end
            ],
        )
    return plans


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SegmentationResult:
    sections: list[Section] = field(default_factory=list)
    chunks: list[ChunkPlan] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def segment_revision(
    text: str,
    source_sha256: str,
    config: SegmentationConfig | None = None,
) -> SegmentationResult:
    """Turn one normalized revision text into sections + chunk plans.

    Pure function of ``(text, source_sha256, config, versions)``: the same
    inputs always produce the same manifest ``plan_sha256``.
    """
    if not isinstance(text, str) or text == "":
        raise PersistenceError("revision text must be a non-empty string")
    if not isinstance(source_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source_sha256
    ):
        raise PersistenceError("source_sha256 must be a lowercase hex SHA-256 string")
    config = config or SegmentationConfig()
    sections, structure_report = detect_structure(text)
    chunks: list[ChunkPlan] = []
    for section in sections:
        chunks.extend(
            segment_section(text, section, start_index=len(chunks), config=config)
        )
    if not chunks:  # pragma: no cover - defensive; non-empty text always chunks
        raise PersistenceError("segmentation produced no chunks for non-empty text")
    plan_rows = [
        [
            c.section_index,
            c.source_start,
            c.source_end,
            c.overlap_prev_chars,
            c.content_sha256,
        ]
        for c in chunks
    ]
    manifest = {
        "segmentation_version": SEGMENTATION_VERSION,
        "structure_version": STRUCTURE_VERSION,
        "context_version": CONTEXT_VERSION,
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "offset_unit": OFFSET_UNIT,
        "config": config.to_dict(),
        "source_sha256": source_sha256,
        "source_chars": len(text),
        "section_count": len(sections),
        "chunk_count": len(chunks),
        "structure": structure_report,
        "plan_sha256": hashlib.sha256(
            json.dumps(
                plan_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "authoritative": False,
        "authority_note": NON_AUTHORITATIVE_NOTE,
    }
    return SegmentationResult(sections=sections, chunks=chunks, manifest=manifest)


# ---------------------------------------------------------------------------
# Context state (forward continuity across chunk boundaries)
# ---------------------------------------------------------------------------

_ERA_TIME = (
    r"(?:建安|黃初|太和|青龍|景初|正始|嘉平|甘露|景元|咸熙|章武|建興|延熙"
    r"|景耀|炎興|黃武|黃龍|嘉禾|赤烏|太元|神鳳|黃初|建武|永平|元和|章和"
    r"|永元|延熹|熹平|光和|中平|初平|興平|建興|永安|景耀)"
)
_TIME_PATTERNS: tuple[tuple[str, str], ...] = (
    ("year", _ERA_TIME + r"?[十百千\d一二三四五六七八九零〇]+\s*年"),
    ("year", r"[\u4e00-\u9fff]{1,4}元年"),
    ("month", r"[正二三四五六七八九十冬臘][月]"),
    ("day", r"初?[一二三四五六七八九十\d]+\s*[日号號]"),
)

_MENTION_BEFORE_VERB = re.compile(
    r"([\u4e00-\u9fff]{2,5})(?=曰|字|謂|為|乃|即|率|領|攻|破|斬|殺|降|迎|拜|封|使"
    r"|遣|召|見|與|及|戰|圍|守|屯|征|伐|救|討|平|定|克|取|盟|朝|詔|赦|築|渡|還|歸"
    r"|走|奔|擒|獲|獻|舉|反|叛|遷|立|廢|崩|薨|卒|敗|勝|葬|襲|拒|據|代)"
)
#: Leading function/kinship characters stripped from a raw mention span while
#: it stays longer than two characters. The extractor is a surface heuristic
#: (C1-T6 owns real identity), but "其將張遼" should at least surface "張遼"
#: rather than the whole governing phrase.
_MENTION_LEAD_STRIP = frozenset(list("其之子將母父兄弟子妹臣兵眾軍將"))

_COURTESY_NAME = re.compile(
    r"([\u4e00-\u9fff]{2})\s*字\s*([\u4e00-\u9fff]{1,2})"
)
_PLACE_SUFFIX = re.compile(
    r"([\u4e00-\u9fff]{2,5})(?=城|郡|州|縣|都|京|江|河|山|關|塞|津|渡|營|寨|宮|殿|陵|墓|寺|觀|市|鎮|村|堡|口|峽|谷|原|野|澤|湖|海|島|洲|橋|門|街|巷|府|衙|縣|鄉|里)"
)
_PRONOUNS = frozenset(
    list("之其彼伊渠厥斯是") + ["吾", "我", "余", "朕", "孤", "公", "卿", "汝", "爾", "爾等"]
)
_ACTION_VERBS = tuple(
    "戰攻破斬殺降圍守屯遷立廢崩薨卒征伐救敗勝盟朝聘宴詔赦築決渡還歸走奔擒獲獻封拜"
    "除免起舉反叛討平定克取入出至到過經會葬祭襲"
)


def extract_time_expressions(text: str, limit: int = 8) -> list[str]:
    """Return verbatim time-expression spans, in order, deduplicated."""
    found: list[str] = []
    for _kind, pattern in _TIME_PATTERNS:
        for match in re.finditer(pattern, text):
            span = match.group(0)
            if span not in found:
                found.append(span)
            if len(found) >= limit:
                return found
    return found


def _clean_mention(span: str) -> str:
    """Strip leading function/kinship characters from a mention span."""
    while len(span) > 2 and span[0] in _MENTION_LEAD_STRIP:
        span = span[1:]
    return span


def extract_candidate_mentions(text: str, limit: int = 16) -> list[str]:
    """Return conservative person-mention surface candidates (ordered, unique).

    Heuristic hints only: a 2–5 character CJK run immediately governing a
    speech/action verb, or a ``X字Y`` courtesy-name construction. Leading
    governing particles (其子/其將/其母/…) are stripped so the surfaced hint
    names the person, not the phrase. C1-T6 contract extraction owns real
    Entity identity; these never do.
    """
    found: list[str] = []
    for match in _MENTION_BEFORE_VERB.finditer(text):
        span = _clean_mention(match.group(1))
        if span not in found:
            found.append(span)
        if len(found) >= limit:
            return found
    for match in _COURTESY_NAME.finditer(text):
        for group in match.groups():
            if group not in found:
                found.append(group)
            if len(found) >= limit:
                return found
    return found


def extract_candidate_places(text: str, limit: int = 16) -> list[str]:
    """Return conservative place-mention surface candidates (ordered, unique)."""
    found: list[str] = []
    for match in _PLACE_SUFFIX.finditer(text):
        span = match.group(1)
        if span not in found:
            found.append(span)
        if len(found) >= limit:
            return found
    return found


def extract_event_snippets(text: str, limit: int = 8) -> list[str]:
    """Return verbatim sentences holding an action verb (ordered, oldest last)."""
    events: list[str] = []
    for sentence in _split_sentences(text):
        clean = sentence.strip()
        if len(clean) >= 4 and any(verb in clean for verb in _ACTION_VERBS):
            snippet = clean[:160]
            if snippet not in events:
                events.append(snippet)
    return events[-limit:]


def find_pronoun_hints(
    text: str, prior_mentions: list[str], chunk_index: int
) -> list[dict[str, Any]]:
    """Link pronouns to the nearest prior surface mention as uncertain hints.

    ``prior_mentions`` is the ordered candidate list inherited from earlier
    chunks; mentions introduced earlier in ``text`` itself take precedence.
    Every hint carries ``uncertain: true``: it is a processing aid for
    C1-T6, never a resolution decision.
    """
    hints: list[dict[str, Any]] = []
    live: list[str] = list(prior_mentions)
    # Mention-introduction events, ordered by position, so a left-to-right
    # scan sees exactly the mentions that precede each pronoun (inherited
    # ones plus ones introduced earlier in this same chunk).
    events: list[tuple[int, str]] = []  # (pos, value)
    for match in _MENTION_BEFORE_VERB.finditer(text):
        events.append((match.start(), _clean_mention(match.group(1))))
    for match in _COURTESY_NAME.finditer(text):
        for group in match.groups():
            events.append((match.start(), group))
    events.sort(key=lambda item: item[0])
    event_cursor = 0
    pos = 0
    while pos < len(text):
        while event_cursor < len(events) and events[event_cursor][0] < pos:
            value = events[event_cursor][1]
            if value not in live:
                live.append(value)
            event_cursor += 1
        hit: str | None = None
        two = text[pos : pos + 2]
        if two in _PRONOUNS and len(two) == 2:
            hit = two
        elif text[pos] in _PRONOUNS:
            hit = text[pos]
        if hit is not None:
            if live:
                hints.append(
                    {
                        "pronoun": hit,
                        "pronoun_chunk": chunk_index,
                        "antecedent_hint": live[-1],
                        "uncertain": True,
                        "basis": "nearest-prior-surface",
                    }
                )
            pos += len(hit)
        else:
            pos += 1
    return hints


def initial_context() -> dict[str, Any]:
    """Return the empty ContextState input for the first chunk of a revision."""
    return {
        "version": CONTEXT_VERSION,
        "chunk_index": -1,
        "inherited_time": [],
        "active_entities": [],
        "active_places": [],
        "recent_events": [],
        "coreference_hints": [],
        "prev_tail": "",
        "next_head": "",
        "authoritative": False,
        "authority_note": (
            "context state is a processing aid, not historical authority; "
            "hints stay uncertain until C1-T6/C1-T7 extraction and resolution"
        ),
    }


def _merge_surfaces(
    previous: list[dict[str, Any]],
    fresh: list[str],
    chunk_index: int,
    limit: int,
) -> list[dict[str, Any]]:
    merged = list(previous)
    known = [item["text"] for item in merged]
    for span in fresh:
        if span in known:
            for item in merged:
                if item["text"] == span:
                    item["count"] += 1
                    item["last_seen_chunk"] = chunk_index
        else:
            merged.append(
                {
                    "text": span,
                    "first_seen_chunk": chunk_index,
                    "last_seen_chunk": chunk_index,
                    "count": 1,
                }
            )
            known.append(span)
    # Keep the most recently seen; drop the oldest first (bounded memory).
    merged.sort(key=lambda item: (item["last_seen_chunk"], item["count"]))
    return merged[-limit:] if limit >= 0 else merged


def advance_context(
    previous_output: dict[str, Any],
    chunk_text: str,
    chunk_index: int,
    config: SegmentationConfig | None = None,
) -> dict[str, dict[str, Any]]:
    """Advance ContextState across one chunk boundary.

    Returns ``{"input": ..., "output": ...}`` where ``input`` is the exact
    state the chunk inherited and ``output`` is the state it forwards.
    Time expressions are never normalized or given invented precision: a
    chunk without an explicit expression inherits the previous one verbatim
    with ``scope: "inherited"``; a chunk with none anywhere yields an empty
    list (uncertainty preserved, not filled).
    """
    config = config or SegmentationConfig()
    if not isinstance(previous_output, dict):
        raise PersistenceError("previous context state must be a JSON object")
    if previous_output.get("version") != CONTEXT_VERSION:
        raise PersistenceError(
            "context state version mismatch: expected "
            f"{CONTEXT_VERSION}, got {previous_output.get('version')!r}"
        )
    if not isinstance(chunk_text, str) or chunk_text == "":
        raise PersistenceError("chunk text must be a non-empty string")
    state_in = copy.deepcopy(previous_output)

    explicit = extract_time_expressions(chunk_text, limit=config.max_time_exprs)
    if explicit:
        inherited_time = [
            {"text": span, "scope": "explicit", "source_chunk": chunk_index}
            for span in explicit
        ]
    elif previous_output.get("inherited_time"):
        inherited_time = [
            {
                "text": item["text"],
                "scope": "inherited",
                "source_chunk": item["source_chunk"],
            }
            for item in previous_output["inherited_time"][-config.max_time_exprs :]
        ]
    else:
        inherited_time = []

    prior_mention_texts = [
        item["text"] for item in previous_output.get("active_entities", [])
    ]
    fresh_mentions = extract_candidate_mentions(
        chunk_text, limit=config.max_entities
    )
    active_entities = _merge_surfaces(
        previous_output.get("active_entities", []),
        fresh_mentions,
        chunk_index,
        config.max_entities,
    )
    active_places = _merge_surfaces(
        previous_output.get("active_places", []),
        extract_candidate_places(chunk_text, limit=config.max_places),
        chunk_index,
        config.max_places,
    )
    fresh_events = extract_event_snippets(chunk_text, limit=config.max_events)
    recent = list(previous_output.get("recent_events", []))
    for snippet in fresh_events:
        if snippet not in [item["text"] for item in recent]:
            recent.append({"text": snippet, "source_chunk": chunk_index})
    recent_events = recent[-config.max_events :]

    hints = find_pronoun_hints(chunk_text, prior_mention_texts, chunk_index)

    bound = config.boundary_context_chars
    state_out = {
        "version": CONTEXT_VERSION,
        "chunk_index": chunk_index,
        "inherited_time": inherited_time,
        "active_entities": active_entities,
        "active_places": active_places,
        "recent_events": recent_events,
        "coreference_hints": hints,
        # Bounded boundary context: this chunk's tail travels forward as the
        # next chunk's prev_tail. The next_head slot is filled by
        # context_chain (which knows the following chunk's head); a lone
        # advance leaves it empty rather than inventing lookahead.
        "prev_tail": chunk_text[-bound:] if bound > 0 else "",
        "next_head": "",
        "authoritative": False,
        "authority_note": (
            "context state is a processing aid, not historical authority; "
            "hints stay uncertain until C1-T6/C1-T7 extraction and resolution"
        ),
    }
    return {"input": state_in, "output": state_out}


def context_chain(
    plan: SegmentationResult,
    text: str,
    config: SegmentationConfig | None = None,
) -> list[dict[str, dict[str, Any]]]:
    """Run :func:`advance_context` over every chunk plan in order.

    ``pair[i]["output"]`` is always ``pair[i+1]["input"]``'s forward state
    (same version, ``chunk_index`` stepped by the plan), so the chain is
    auditable and replayable chunk by chunk.
    """
    config = config or SegmentationConfig()
    pairs: list[dict[str, dict[str, Any]]] = []
    state = initial_context()
    heads = [
        text[c.source_start : c.source_end][: config.boundary_context_chars]
        if config.boundary_context_chars > 0
        else ""
        for c in plan.chunks
    ]
    for position, chunk in enumerate(plan.chunks):
        chunk_text = text[chunk.source_start : chunk.source_end]
        pair = advance_context(state, chunk_text, chunk.chunk_index, config)
        # Forward lookahead stitching: each output names the bounded head of
        # the chunk that follows it (empty for the final chunk).
        pair["output"]["next_head"] = (
            heads[position + 1] if position + 1 < len(heads) else ""
        )
        # Budget gate: serialized output context must fit its reserve.
        context_chars = len(
            json.dumps(pair["output"], ensure_ascii=False, sort_keys=True)
        )
        report = ensure_budgets(len(chunk_text), context_chars, config)
        pair["output"]["budget"] = report
        pairs.append(pair)
        state = pair["output"]
    return pairs


# ---------------------------------------------------------------------------
# Persistence (idempotent section/chunk + checkpoint writes)
# ---------------------------------------------------------------------------


def chunk_locator(
    *,
    job_id: uuid.UUID,
    revision_id: uuid.UUID,
    revision_no: int,
    source_sha256: str,
    chunk: ChunkPlan,
    section_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Return the exact source locator later extraction/evidence must cite."""
    return {
        "job_id": str(job_id),
        "revision_id": str(revision_id),
        "revision_no": int(revision_no),
        "source_sha256": source_sha256,
        "section_index": chunk.section_index,
        "section_id": None if section_id is None else str(section_id),
        "chunk_index": chunk.chunk_index,
        "source_start": chunk.source_start,
        "source_end": chunk.source_end,
        "offset_unit": OFFSET_UNIT,
        "content_sha256": chunk.content_sha256,
        "overlap_prev_chars": chunk.overlap_prev_chars,
        "segmentation_version": SEGMENTATION_VERSION,
    }


def chunk_checkpoint(
    *,
    locator: dict[str, Any],
    context: dict[str, dict[str, Any]],
    manifest_ref: dict[str, Any],
) -> dict[str, Any]:
    """Build the persisted per-chunk checkpoint (offsets, never full text)."""
    return {
        "segmentation_version": SEGMENTATION_VERSION,
        "context_version": CONTEXT_VERSION,
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "locator": locator,
        "context_input": context["input"],
        "context_output": context["output"],
        "boundary_head": manifest_ref.get("boundary_head", ""),
        "boundary_tail": manifest_ref.get("boundary_tail", ""),
        "manifest_plan_sha256": manifest_ref.get("plan_sha256"),
        "authoritative": False,
        "authority_note": NON_AUTHORITATIVE_NOTE,
    }


def ensure_sections(
    conn,
    *,
    job_id: uuid.UUID,
    plan: SegmentationResult,
) -> list[uuid.UUID]:
    """Persist a plan's sections idempotently; returns section ids in order.

    Existing ``(job, index)`` rows are reused; a stored row whose label or
    offsets disagree with the deterministic plan fails closed with
    ``PersistenceConflict`` instead of forking the locator history.
    """
    # Local import: the pure core above stays importable without psycopg.
    import control_plane

    if not isinstance(plan, SegmentationResult):
        raise PersistenceError("plan must be a SegmentationResult")
    section_ids: list[uuid.UUID] = []
    for section in plan.sections:
        try:
            section_ids.append(
                control_plane.create_section(
                    conn,
                    job_id=job_id,
                    section_index=section.section_index,
                    label=section.label,
                    source_start=section.source_start,
                    source_end=section.source_end,
                )
            )
        except PersistenceConflict:
            row = conn.execute(
                """
                SELECT section_id, label, source_start, source_end
                FROM chronicle.ingestion_sections
                WHERE job_id = %s AND section_index = %s
                """,
                (job_id, section.section_index),
            ).fetchone()
            if row is None:  # pragma: no cover - conflict implies a row
                raise PersistenceError(
                    f"section {section.section_index} vanished for job {job_id}"
                )
            if (
                row[1] != section.label
                or int(row[2]) != section.source_start
                or int(row[3]) != section.source_end
            ):
                raise PersistenceConflict(
                    f"section {section.section_index} of job {job_id} already "
                    "persisted with different locators; refusing to fork "
                    "segmentation history (input or version drift)"
                )
            section_ids.append(row[0])
    return section_ids


def ensure_chunks(
    conn,
    *,
    job_id: uuid.UUID,
    plan: SegmentationResult,
    section_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """Persist a plan's chunks idempotently; returns chunk ids in plan order.

    ``section_ids`` may be supplied from :func:`ensure_sections`; when
    omitted they are re-read from the database so a resumed ``segment``
    stage never depends on worker memory. Offset/hash drift fails closed.
    """
    import control_plane

    if not isinstance(plan, SegmentationResult):
        raise PersistenceError("plan must be a SegmentationResult")
    if section_ids is None:
        rows = conn.execute(
            """
            SELECT section_id FROM chronicle.ingestion_sections
            WHERE job_id = %s ORDER BY section_index
            """,
            (job_id,),
        ).fetchall()
        if len(rows) != len(plan.sections):
            raise PersistenceError(
                f"job {job_id} has {len(rows)} sections but the plan "
                f"needs {len(plan.sections)}; run the structure stage first"
            )
        section_ids = [row[0] for row in rows]
    if len(section_ids) != len(plan.sections):
        raise PersistenceError("section_ids must align with the plan sections")
    by_section = {s.section_index: sid for s, sid in zip(plan.sections, section_ids)}
    chunk_ids: list[uuid.UUID] = []
    for chunk in plan.chunks:
        try:
            chunk_ids.append(
                control_plane.record_chunk(
                    conn,
                    job_id=job_id,
                    section_id=by_section[chunk.section_index],
                    chunk_index=chunk.chunk_index,
                    source_start=chunk.source_start,
                    source_end=chunk.source_end,
                    # Whole-revision identity travels in the manifest and the
                    # locator; the chunk row's own source_sha256 pins the
                    # exact slice bytes it was segmented from.
                    source_sha256=chunk.content_sha256,
                    content_sha256=chunk.content_sha256,
                )
            )
        except PersistenceConflict:
            row = conn.execute(
                """
                SELECT chunk_id, source_start, source_end,
                       source_sha256, content_sha256
                FROM chronicle.ingestion_chunks
                WHERE job_id = %s AND chunk_index = %s
                """,
                (job_id, chunk.chunk_index),
            ).fetchone()
            if row is None:  # pragma: no cover - conflict implies a row
                raise PersistenceError(
                    f"chunk {chunk.chunk_index} vanished for job {job_id}"
                )
            if (
                int(row[1]) != chunk.source_start
                or int(row[2]) != chunk.source_end
                or row[3] != chunk.content_sha256
                or row[4] != chunk.content_sha256
            ):
                raise PersistenceConflict(
                    f"chunk {chunk.chunk_index} of job {job_id} already "
                    "persisted with different locators; refusing to fork "
                    "segmentation history (input or version drift)"
                )
            chunk_ids.append(row[0])
    return chunk_ids


def ensure_sections_chunks(
    conn,
    *,
    job_id: uuid.UUID,
    plan: SegmentationResult,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Persist a whole segmentation plan idempotently; resume-safe on re-entry.

    Convenience wrapper over :func:`ensure_sections` + :func:`ensure_chunks`
    for callers (and tests) that apply the plan in one step.
    """
    section_ids = ensure_sections(conn, job_id=job_id, plan=plan)
    return section_ids, ensure_chunks(conn, job_id=job_id, plan=plan,
                                      section_ids=section_ids)
