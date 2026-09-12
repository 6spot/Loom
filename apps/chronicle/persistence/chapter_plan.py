"""Chronicle C2-R1-T03 natural-chapter planning (application-owned).

Pure deterministic planning that keeps one whole biography — or one
Markdown natural chapter with its sub-headings — as a single
comprehension unit, per ``chapter-production.md`` section 2. Consumes
the T01 model (``chapter_contract.PLAN_VERSION`` / ``OFFSET_UNIT`` /
``ChapterLimits``) and the frozen T02 upload shape (``.txt`` single
chapter / ``.md`` ``#`` book + ``##`` natural chapters). No database,
network, or model access (Amendment 0006); no worker changes.

``plan_chapters(text, revision_locator, filename)`` is a pure function
of its inputs: the same normalized text plus the same revision binding
always reproduces identical chapters, blocks, hashes, and
``plan_sha256``.

Frozen entries (only these two):

- ``.txt``: the whole file is one natural chapter. Inner letter
  titles, quotations, or ``第十三``-style prose never re-split it, and
  no Markdown heading is interpreted at all.
- ``.md``: one optional ``# book`` title plus one chapter per ``##``
  title. ``###`` and deeper sub-headings stay inside their chapter.
  With no ``##`` the file is one chapter. A repeated identical ``#``
  book title is tolerated; conflicting ``#`` titles reject as
  ``chapter_structure_ambiguous``.

Coordinates use ``chars-normalized-utf8``: Python ``str`` code-point
half-open intervals ``[start, end)`` over the normalized full text.
Chapter ranges tile the file contiguously from 0 with no overlap and
no dropped bytes: the ``#`` book line and blank runs are registered as
``heading``/``separator`` blocks, never discarded. Blocks tile each
chapter exactly (heading line / maximal blank run / maximal paragraph
run); ``required_block_ids`` holds every non-empty ``body`` block, so
T05 translation coverage can prove no source paragraph was left
unassociated.

Capacity is enforced per whole chapter against ``ChapterLimits``: an
over-limit chapter fails the entire plan with an explicit
``chapter_over_limit_unsupported`` error. The input text is never
truncated or re-split into smaller chunks to fit the budget, and it is
never mutated — the caller still holds the full source alongside the
error.

Planned blocks use absolute file coordinates. ``build_chapter_request``
slices one chapter and re-bases its blocks to chapter-relative
coordinates, producing the program-owned request shape consumed by
T01 ``validate_chapter_candidate``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePath
from typing import Any

from chapter_contract import (
    CANDIDATE_VERSION,
    OFFSET_UNIT,
    PLAN_VERSION,
    ChapterLimits,
)
from common import PersistenceError, canonical_json_bytes

#: Frozen upload entries: single-chapter txt / natural-chapter md.
SUPPORTED_SUFFIXES = (".txt", ".md")

#: Title of a substantive preface chapter (content before the first ``##``).
PREFACE_TITLE = "前言"

#: Machine-readable failure codes (each message carries this prefix).
CODE_EMPTY_TEXT = "chapter_plan_empty_text"
CODE_BAD_LOCATOR = "chapter_plan_bad_locator"
CODE_HASH_DRIFT = "chapter_plan_hash_drift"
CODE_UNSUPPORTED_FORMAT = "chapter_plan_unsupported_format"
CODE_STRUCTURE_AMBIGUOUS = "chapter_structure_ambiguous"
CODE_DUPLICATE_CHAPTER = "chapter_duplicate_title"
CODE_BODYLESS_CHAPTER = "chapter_without_body_unsupported"
CODE_OVER_LIMIT = "chapter_over_limit_unsupported"

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

#: ``# book`` title line (up to three leading spaces per CommonMark).
_BOOK_HEADING_RE = re.compile(r"^ {0,3}#\s+(?P<title>.+?)\s*$")
#: ``## chapter`` title line.
_CHAPTER_HEADING_RE = re.compile(r"^ {0,3}##\s+(?P<title>.+?)\s*$")
#: Any ATX heading line (levels 1-6) used only for block kinds inside md.
_ANY_HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+\S")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chapter_id_for(
    *,
    revision_id: str,
    source_sha256: str,
    start: int,
    end: int,
    plan_version: str = PLAN_VERSION,
) -> str:
    """Derive the stable chapter identity (chapter-production.md section 2.2).

    ``ch_`` + the first 24 hex chars of the canonical JSON hash over
    ``(revision_id, source_sha256, start, end, plan_version)``. The ID is
    not a historical identity; it binds one immutable revision range.
    """
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "revision_id": revision_id,
                "source_sha256": source_sha256,
                "start": start,
                "end": end,
                "plan_version": plan_version,
            }
        )
    ).hexdigest()
    return "ch_" + digest[:24]


def _split_lines(text: str) -> list[tuple[int, int, str]]:
    """Split ``text`` on LF only into ``(start, end, content)`` lines.

    The newline character belongs to its line, so concatenating every
    ``text[start:end]`` slice reproduces ``text`` exactly. A trailing
    empty part after a final newline contributes nothing and is dropped.
    """
    spans: list[tuple[int, int, str]] = []
    parts = text.split("\n")
    pos = 0
    for index, part in enumerate(parts):
        if index < len(parts) - 1:
            spans.append((pos, pos + len(part) + 1, part))
            pos += len(part) + 1
        elif part:
            spans.append((pos, pos + len(part), part))
    return spans


def _require_locator(revision_locator: Any) -> dict[str, Any]:
    """Validate the revision binding carried by every plan/chapter."""
    if not isinstance(revision_locator, dict):
        raise PersistenceError(
            f"{CODE_BAD_LOCATOR}: revision_locator must be a JSON object "
            f"with revision_id/source_sha256/normalized_sha256, "
            f"got {type(revision_locator).__name__}"
        )
    revision_id = revision_locator.get("revision_id")
    if not isinstance(revision_id, str) or not revision_id:
        raise PersistenceError(
            f"{CODE_BAD_LOCATOR}: revision_locator requires a non-empty "
            "revision_id string"
        )
    for key in ("source_sha256", "normalized_sha256"):
        value = revision_locator.get(key)
        if not isinstance(value, str) or not _HEX64_RE.match(value):
            raise PersistenceError(
                f"{CODE_BAD_LOCATOR}: revision_locator {key!r} must be a "
                "lowercase hex SHA-256 string"
            )
    document_id = revision_locator.get("document_id")
    if document_id is not None and (
        not isinstance(document_id, str) or not document_id
    ):
        raise PersistenceError(
            f"{CODE_BAD_LOCATOR}: revision_locator document_id must be a "
            "non-empty string when present"
        )
    return {
        "revision_id": revision_id,
        "document_id": document_id,
        "source_sha256": revision_locator["source_sha256"],
        "normalized_sha256": revision_locator["normalized_sha256"],
    }


def _require_filename(filename: Any) -> str:
    """Return the frozen entry suffix (``.txt`` / ``.md``) or fail closed."""
    if not isinstance(filename, str) or not filename:
        raise PersistenceError(
            f"{CODE_UNSUPPORTED_FORMAT}: filename must be a non-empty string"
        )
    suffix = PurePath(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise PersistenceError(
            f"{CODE_UNSUPPORTED_FORMAT}: {filename!r} is not a frozen "
            "chapter entry (expected .txt single-chapter or .md "
            "natural-chapter input); refusing to guess"
        )
    return suffix


def _build_blocks(
    *,
    text: str,
    start: int,
    end: int,
    spans: list[tuple[int, int, str]],
    first_block_seq: int,
    chapter_index: int,
    detect_headings: bool,
) -> tuple[list[dict[str, Any]], int]:
    """Tile ``[start, end)`` into heading/separator/body blocks.

    Maximal runs of blank lines form one ``separator`` block; maximal
    runs of content lines form one ``body`` block (newlines included, so
    concatenation reproduces the chapter exactly). In ``.md`` an ATX
    heading line is its own ``heading`` block; in ``.txt`` heading
    detection stays off so letter titles and quoted headings remain
    ``body`` content under translation coverage. Returns
    ``(blocks, next_block_seq)`` with plan-global sequential block IDs.
    """
    in_range = [
        (span_start, span_end, content)
        for span_start, span_end, content in spans
        if span_start >= start and span_end <= end
    ]
    if not in_range or in_range[0][0] != start or in_range[-1][1] != end:
        raise PersistenceError(  # pragma: no cover - construction guarantees this
            f"{CODE_BODYLESS_CHAPTER}: chapter {chapter_index} line tiling "
            f"does not cover [{start},{end}) (fail closed)"
        )
    # Group lines into (kind, lines) runs.
    runs: list[tuple[str, list[tuple[int, int, str]]]] = []
    for span in in_range:
        _, _, content = span
        if detect_headings and _ANY_HEADING_RE.match(content):
            kind = "heading"
        elif content.strip() == "":
            kind = "separator"
        else:
            kind = "body"
        # Heading lines always stand alone; blank/content lines merge
        # only with the same kind.
        if kind == "heading" or not runs or runs[-1][0] != kind:
            runs.append((kind, [span]))
        else:
            runs[-1][1].append(span)
    blocks: list[dict[str, Any]] = []
    seq = first_block_seq
    for kind, run in runs:
        block_start = run[0][0]
        block_end = run[-1][1]
        blocks.append(
            {
                "block_id": f"b_{seq:03d}",
                "kind": kind,
                "start": block_start,
                "end": block_end,
                "content_sha256": sha256_text(text[block_start:block_end]),
            }
        )
        seq += 1
    return blocks, seq


def _verify_tiling(
    *, text: str, chapters: list[dict[str, Any]], filename: str
) -> None:
    """Fail closed on any overlap, gap, or unrecoverable byte range."""
    if not chapters:
        raise PersistenceError(
            f"{CODE_BODYLESS_CHAPTER}: plan for {filename!r} holds no chapters"
        )
    cursor = 0
    seen_blocks: set[str] = set()
    for chapter in chapters:
        start, end = chapter["start"], chapter["end"]
        if start != cursor:
            raise PersistenceError(
                f"{CODE_BODYLESS_CHAPTER}: chapter {chapter['chapter_index']} "
                f"starts at {start} but file coverage ends at {cursor} "
                "(gap or overlap; fail closed)"
            )
        if not (0 <= start < end <= len(text)):
            raise PersistenceError(
                f"{CODE_BODYLESS_CHAPTER}: chapter {chapter['chapter_index']} "
                f"range [{start},{end}) is outside the normalized text "
                f"({len(text)} chars)"
            )
        assembled = ""
        for block in chapter["blocks"]:
            block_id = block["block_id"]
            if block_id in seen_blocks:
                raise PersistenceError(
                    f"{CODE_BODYLESS_CHAPTER}: duplicate block_id "
                    f"{block_id!r} (fail closed)"
                )
            seen_blocks.add(block_id)
            assembled += text[block["start"]:block["end"]]
            if block["content_sha256"] != sha256_text(
                text[block["start"]:block["end"]]
            ):
                raise PersistenceError(
                    f"{CODE_BODYLESS_CHAPTER}: block {block_id!r} hash does "
                    "not match its range (fail closed)"
                )
        if assembled != text[start:end]:
            raise PersistenceError(
                f"{CODE_BODYLESS_CHAPTER}: chapter {chapter['chapter_index']} "
                "blocks do not reconstruct the chapter range (fail closed)"
            )
        required = chapter["required_block_ids"]
        body_ids = {
            block["block_id"]
            for block in chapter["blocks"]
            if block["kind"] == "body" and text[block["start"]:block["end"]].strip()
        }
        if set(required) != body_ids:
            raise PersistenceError(
                f"{CODE_BODYLESS_CHAPTER}: chapter {chapter['chapter_index']} "
                "required_block_ids must list exactly the non-empty body "
                "blocks (fail closed)"
            )
        cursor = end
    if cursor != len(text):
        raise PersistenceError(
            f"{CODE_BODYLESS_CHAPTER}: chapters cover [0,{cursor}) but the "
            f"file holds {len(text)} chars (trailing bytes dropped; "
            "fail closed)"
        )


def plan_chapters(
    text: str,
    revision_locator: dict[str, Any],
    filename: str,
    limits: ChapterLimits | None = None,
) -> dict[str, Any]:
    """Plan the natural chapters of one normalized revision text.

    ``text`` is the normalized full text (LF only, e.g. via
    ``documents.decode_source`` or
    ``chapter_contract.normalize_source_bytes``). ``revision_locator``
    carries ``revision_id`` / ``source_sha256`` / ``normalized_sha256``
    (plus optional ``document_id``); the text hash is re-verified so a
    drifted input fails closed instead of planning the wrong bytes.
    ``filename`` selects the frozen entry (``.txt`` / ``.md``,
    case-insensitive). ``limits`` defaults to ``ChapterLimits()``.

    Returns ``{"version", "plan_sha256", revision binding, "chapters"}``
    where each chapter holds ``chapter_id`` / ``chapter_index`` /
    ``title`` / absolute ``[start, end)`` / ``blocks[]`` /
    ``required_block_ids[]``. Raises :class:`PersistenceError` — never a
    partial plan — on empty input, locator/hash problems, unsupported
    formats, conflicting book titles, duplicate chapters, body-less
    chapters, or over-limit chapters.
    """
    if not isinstance(text, str) or text == "":
        raise PersistenceError(
            f"{CODE_EMPTY_TEXT}: revision text must be a non-empty string"
        )
    locator = _require_locator(revision_locator)
    suffix = _require_filename(filename)
    if limits is None:
        limits = ChapterLimits()
    elif not isinstance(limits, ChapterLimits):
        raise PersistenceError(
            f"{CODE_BAD_LOCATOR}: limits must be a ChapterLimits"
        )
    if sha256_text(text) != locator["normalized_sha256"]:
        raise PersistenceError(
            f"{CODE_HASH_DRIFT}: normalized_sha256 does not match the "
            "input text (wrong revision bytes; refusing to plan)"
        )

    spans = _split_lines(text)
    detect_headings = suffix == ".md"

    # Structural scan (.md only): first ``#`` sets the book title, every
    # ``##`` opens a chapter. ``###`` and deeper never split; prose such
    # as 书信名 or 第十三 cannot match these ATX patterns by construction.
    book_title: str | None = None
    book_titles: set[str] = set()
    chapter_heads: list[tuple[int, str]] = []  # (line start offset, title)
    if detect_headings:
        for span_start, _, content in spans:
            chapter_match = _CHAPTER_HEADING_RE.match(content)
            if chapter_match is not None:
                title = chapter_match.group("title").strip()
                if title:
                    chapter_heads.append((span_start, title))
                continue
            book_match = _BOOK_HEADING_RE.match(content)
            if book_match is not None:
                title = book_match.group("title").strip()
                if title:
                    book_titles.add(title)
                    if book_title is None:
                        book_title = title
        if len(book_titles) > 1:
            raise PersistenceError(
                f"{CODE_STRUCTURE_AMBIGUOUS}: conflicting level-1 book "
                f"titles {sorted(book_titles)} in {filename!r}; refusing "
                "to guess the work boundary"
            )

    stem = PurePath(filename).stem or filename
    # Chapter shells: (title, start). Preface owns [0, first head) only
    # when it holds substantive content beyond the book line/blanks.
    shells: list[tuple[str, int]] = []
    if suffix == ".txt" or not chapter_heads:
        title = book_title if (suffix == ".md" and book_title) else stem
        shells.append((title, 0))
    else:
        first_start = chapter_heads[0][0]
        substantive_lines = [
            content
            for span_start, _span_end, content in spans
            if span_start < first_start
            and not _BOOK_HEADING_RE.match(content)
        ]
        if "".join(substantive_lines).strip():
            shells.append((PREFACE_TITLE, 0))
            for head_start, head_title in chapter_heads:
                shells.append((head_title, head_start))
        else:
            shells.append((chapter_heads[0][1], 0))
            for head_start, head_title in chapter_heads[1:]:
                shells.append((head_title, head_start))

    seen_titles: set[str] = set()
    for title, _ in shells:
        if title in seen_titles:
            raise PersistenceError(
                f"{CODE_DUPLICATE_CHAPTER}: duplicate chapter title "
                f"{title!r} in {filename!r}; refusing to emit ambiguous "
                "chapter identities"
            )
        seen_titles.add(title)

    chapters: list[dict[str, Any]] = []
    seq = 1
    for index, (title, start) in enumerate(shells):
        end = shells[index + 1][1] if index + 1 < len(shells) else len(text)
        blocks, seq = _build_blocks(
            text=text,
            start=start,
            end=end,
            spans=spans,
            first_block_seq=seq,
            chapter_index=index,
            detect_headings=detect_headings,
        )
        required = [
            block["block_id"]
            for block in blocks
            if block["kind"] == "body"
            and text[block["start"]:block["end"]].strip()
        ]
        if not required:
            raise PersistenceError(
                f"{CODE_BODYLESS_CHAPTER}: chapter {index} ({title!r}) "
                f"holds no body text in [{start},{end}); a chapter without "
                "translatable body cannot enter translation coverage"
            )
        chapter_chars = end - start
        if chapter_chars > limits.max_source_chars:
            raise PersistenceError(
                f"{CODE_OVER_LIMIT}: chapter {index} ({title!r}) holds "
                f"{chapter_chars} chars, exceeding max_source_chars "
                f"({limits.max_source_chars}); the whole chapter is "
                "unsupported and the source text is left intact (no "
                "truncation, no re-splitting into smaller chunks)"
            )
        chapters.append(
            {
                "chapter_id": chapter_id_for(
                    revision_id=locator["revision_id"],
                    source_sha256=locator["source_sha256"],
                    start=start,
                    end=end,
                ),
                "chapter_index": index,
                "title": title,
                "start": start,
                "end": end,
                "chars": chapter_chars,
                "offset_unit": OFFSET_UNIT,
                "revision_id": locator["revision_id"],
                "document_id": locator["document_id"],
                "source_sha256": locator["source_sha256"],
                "normalized_sha256": locator["normalized_sha256"],
                "plan_version": PLAN_VERSION,
                "content_sha256": sha256_text(text[start:end]),
                "blocks": blocks,
                "required_block_ids": required,
            }
        )

    _verify_tiling(text=text, chapters=chapters, filename=filename)

    plan_sha256 = plan_sha256_for(
        {
            "version": PLAN_VERSION,
            "revision_id": locator["revision_id"],
            "source_sha256": locator["source_sha256"],
            "normalized_sha256": locator["normalized_sha256"],
            "chapters": chapters,
        }
    )
    return {
        "version": PLAN_VERSION,
        "plan_sha256": plan_sha256,
        "revision_id": locator["revision_id"],
        "document_id": locator["document_id"],
        "source_sha256": locator["source_sha256"],
        "normalized_sha256": locator["normalized_sha256"],
        "normalized_chars": len(text),
        "filename": filename,
        "chapter_count": len(chapters),
        "chapters": chapters,
    }


def plan_sha256_for(plan: dict[str, Any]) -> str:
    """Recompute the canonical T03 plan hash from a plan object.

    The hash is the single authority for plan integrity: it covers
    ``version``, the revision binding and the complete ``chapters`` array,
    including every chapter's ``blocks`` (with each ``content_sha256``) and
    ``required_block_ids``. A caller that holds a plan can therefore verify
    it against a persisted ``plan_sha256`` without re-reading the source
    text; tampering with any covered field changes the recomputation even
    when the supplied ``plan_sha256`` string is left untouched.
    """
    if not isinstance(plan, dict):
        raise PersistenceError("chapter plan must be a JSON object")
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "version": plan.get("version"),
                "revision_id": plan.get("revision_id"),
                "source_sha256": plan.get("source_sha256"),
                "normalized_sha256": plan.get("normalized_sha256"),
                "chapters": plan.get("chapters"),
            }
        )
    ).hexdigest()


def build_chapter_request(
    plan: dict[str, Any],
    chapter_index: int,
    text: str,
    limits: ChapterLimits | None = None,
    *,
    candidate_version: str = CANDIDATE_VERSION,
) -> dict[str, Any]:
    """Build the T01 program-owned request for one planned chapter.

    Slices ``text[chapter.start:chapter.end]`` and re-bases blocks to
    chapter-relative coordinates, producing the request shape consumed
    by ``chapter_contract.validate_chapter_candidate`` (absolute plan
    coordinates are never handed to the model contract). The normalized
    hash binding is re-verified; any drift fails closed.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("chapters"), list):
        raise PersistenceError(
            f"{CODE_BAD_LOCATOR}: plan must be a plan_chapters() result dict"
        )
    chapters = plan["chapters"]
    if (
        not isinstance(chapter_index, int)
        or isinstance(chapter_index, bool)
        or not (0 <= chapter_index < len(chapters))
    ):
        raise PersistenceError(
            f"{CODE_BAD_LOCATOR}: chapter_index {chapter_index!r} is "
            f"outside [0,{len(chapters)})"
        )
    if not isinstance(text, str) or text == "":
        raise PersistenceError(f"{CODE_EMPTY_TEXT}: revision text is required")
    if sha256_text(text) != plan.get("normalized_sha256"):
        raise PersistenceError(
            f"{CODE_HASH_DRIFT}: plan normalized_sha256 does not match "
            "the supplied text (wrong revision bytes)"
        )
    chapter = chapters[chapter_index]
    start, end = chapter["start"], chapter["end"]
    if not (0 <= start < end <= len(text)):
        raise PersistenceError(
            f"{CODE_BODYLESS_CHAPTER}: chapter {chapter_index} range "
            f"[{start},{end}) is outside the supplied text "
            f"({len(text)} chars)"
        )
    if limits is None:
        limits = ChapterLimits()
    elif not isinstance(limits, ChapterLimits):
        raise PersistenceError(
            f"{CODE_BAD_LOCATOR}: limits must be a ChapterLimits"
        )
    blocks = []
    for block in chapter["blocks"]:
        relative = {
            "block_id": block["block_id"],
            "kind": block["kind"],
            "start": block["start"] - start,
            "end": block["end"] - start,
            "content_sha256": sha256_text(text[block["start"]:block["end"]]),
        }
        if relative["content_sha256"] != block["content_sha256"]:
            raise PersistenceError(  # pragma: no cover - defensive
                f"{CODE_HASH_DRIFT}: block {block['block_id']!r} hash does "
                "not match the supplied text"
            )
        blocks.append(relative)
    from chapter_contract import CANDIDATE_VERSIONS

    if candidate_version not in CANDIDATE_VERSIONS:
        raise PersistenceError(f"unregistered chapter candidate version {candidate_version!r}")
    request = {
        "chapter_id": chapter["chapter_id"],
        "chapter_index": chapter["chapter_index"],
        "title": chapter["title"],
        "revision_id": plan["revision_id"],
        "document_id": plan.get("document_id"),
        "source_sha256": plan["source_sha256"],
        "normalized_sha256": plan["normalized_sha256"],
        "normalized_text": text[start:end],
        "blocks": blocks,
        "required_block_ids": list(chapter["required_block_ids"]),
        "plan_version": PLAN_VERSION,
        "limits": limits.to_dict(),
        "schema_versions": {
            "candidate": candidate_version,
            "bundle": "0.1",
        },
    }
    if candidate_version == "0.4":
        from staged_chapter_contract import build_source_scope

        request["chapter_start"] = start
        request["chapter_end"] = end
        request["revision_normalized_sha256"] = plan["normalized_sha256"]
        request["normalized_sha256"] = sha256_text(request["normalized_text"])
        request["source_scope"] = build_source_scope(request)
        request["required_block_ids"] = list(request["source_scope"]["body_block_ids"])
    return request
