"""Shared Studio/public source reader for C2-R1-T10 (read-only).

Single resolver used by the Studio review contexts/sources endpoints and
reused later by the public chapter API (T14). It never copies a second
verbatim-source implementation.

Contract summary (review-workflow §4 + chapter-production §2.2/§7):

- Read raw bytes by the exact revision storage key, verify the source
  hash, then decode (one BOM strip, CRLF/CR -> LF) and work in Unicode
  code-point coordinates. The browser never slices raw bytes.
- Server-side window is ±400 code points; chapter pages are at most
  16,000 code points. Responses carry bounds/hash/has_more/next_cursor
  and server-cut highlight segments.
- An anchor is accepted only when it belongs to the review's frozen
  member set with exact artifact/revision/hash match. Same text at a
  different location or revision is never substituted. Missing files
  and hash/range drift are 409s, never a silent fallback to a newer
  revision. Unknown/unconfigured revisions on old partial fixtures are
  reported ``unavailable`` with the original direct Claim preserved.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

WINDOW_RADIUS = 400
CHAPTER_PAGE_MAX = 16000
CONTEXT_CURSOR_VERSION = 1
SOURCE_CURSOR_VERSION = 1


class SourceUnavailable(Exception):
    """Revision bytes are missing (409 source_unavailable)."""


class SourceMismatch(Exception):
    """Hash/range drift on an otherwise addressed source (409 source_mismatch)."""


class BadCursor(ValueError):
    """Opaque cursor or paging parameter is invalid (400)."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def context_id_for(review_id: str, bundle: str, ref: str) -> str:
    digest = hashlib.sha256(
        f"{review_id}\x00{bundle}\x00{ref}".encode("utf-8")
    ).hexdigest()
    return "ctx_" + digest[:16]


# ---------------------------------------------------------------------------
# Cursors (opaque, scope-bound)
# ---------------------------------------------------------------------------


def _b64encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str, *, what: str) -> dict[str, Any]:
    try:
        padded = raw + ("=" * (-len(raw) % 4))
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadCursor(f"{what} cursor is not valid: {exc}") from exc
    if not isinstance(payload, dict):
        raise BadCursor(f"{what} cursor is not valid")
    return payload


def encode_context_cursor(
    *, review_id: str, group_id: str | None, offset: int
) -> str:
    return _b64encode(
        {
            "v": CONTEXT_CURSOR_VERSION,
            "review_id": str(review_id),
            "group_id": group_id,
            "offset": int(offset),
        }
    )


def decode_context_cursor(
    raw: str, *, review_id: str, group_id: str | None
) -> int:
    payload = _b64decode(raw, what="context")
    if payload.get("v") != CONTEXT_CURSOR_VERSION:
        raise BadCursor("context cursor version is not supported")
    if str(payload.get("review_id") or "") != str(review_id):
        raise BadCursor("context cursor belongs to a different review")
    if (payload.get("group_id") if "group_id" in payload else None) != group_id:
        raise BadCursor("context cursor belongs to a different group scope")
    offset = payload.get("offset")
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        raise BadCursor("context cursor carries an invalid offset")
    return offset


def encode_source_cursor(
    *, review_id: str, anchor_id: str, view: str, offset: int
) -> str:
    return _b64encode(
        {
            "v": SOURCE_CURSOR_VERSION,
            "review_id": str(review_id),
            "anchor_id": str(anchor_id),
            "view": str(view),
            "offset": int(offset),
        }
    )


def decode_source_cursor(
    raw: str, *, review_id: str, anchor_id: str, view: str
) -> int:
    payload = _b64decode(raw, what="source")
    if payload.get("v") != SOURCE_CURSOR_VERSION:
        raise BadCursor("source cursor version is not supported")
    if str(payload.get("review_id") or "") != str(review_id):
        raise BadCursor("source cursor belongs to a different review")
    if str(payload.get("anchor_id") or "") != str(anchor_id):
        raise BadCursor("source cursor belongs to a different anchor")
    if str(payload.get("view") or "") != str(view):
        raise BadCursor("source cursor belongs to a different view")
    offset = payload.get("offset")
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        raise BadCursor("source cursor carries an invalid offset")
    return offset


# ---------------------------------------------------------------------------
# Revision byte reads (exact revision, hash-verified, then decoded)
# ---------------------------------------------------------------------------


def _decode_normalized(data: bytes) -> str:
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceMismatch(f"source bytes are not valid UTF-8: {exc}") from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_revision_text(
    source_dir: Path | str | None,
    storage_key: str,
    expected_source_sha256: str,
) -> str:
    """Read one revision's normalized text by its exact storage key.

    Raises :class:`SourceUnavailable` when the file is missing and
    :class:`SourceMismatch` when the stored bytes no longer match the
    revision hash. Never falls back to another revision.
    """
    try:
        import documents  # type: ignore
    except ImportError:  # pragma: no cover - read_api always ships persistence
        import sys

        persistence = Path(__file__).resolve().parent.parent / "persistence"
        if str(persistence) not in sys.path:
            sys.path.insert(0, str(persistence))
        import documents  # type: ignore

    if not isinstance(storage_key, str) or not storage_key:
        raise SourceUnavailable("revision has no configured storage key")
    base = Path(source_dir) if source_dir else documents.storage_dir_from_env()
    try:
        path = documents.resolve_storage_path(base, storage_key)
    except Exception as exc:
        raise SourceUnavailable(f"source storage key is not readable: {exc}") from exc
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SourceUnavailable(f"source file is missing: {exc}") from exc
    if sha256_bytes(data) != expected_source_sha256:
        raise SourceMismatch(
            "source bytes no longer match the revision hash; "
            "refusing to substitute another version"
        )
    return _decode_normalized(data)


def verify_anchor(anchor: dict[str, Any], text: str) -> None:
    """Fail closed when an anchor no longer addresses this exact text."""
    try:
        start, end = int(anchor["start"]), int(anchor["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceMismatch("anchor has no integer start/end") from exc
    if isinstance(start, bool) or isinstance(end, bool):
        raise SourceMismatch("anchor has no integer start/end")
    if not (0 <= start < end <= len(text)):
        raise SourceMismatch(
            f"anchor range [{start},{end}) is outside this revision text "
            f"({len(text)} chars)"
        )
    quote = anchor.get("quote")
    expected_quote_sha = anchor.get("quote_sha256")
    actual = text[start:end]
    if isinstance(quote, str) and quote and actual != quote:
        raise SourceMismatch("anchor quote no longer matches this revision text")
    if (
        isinstance(expected_quote_sha, str)
        and expected_quote_sha
        and sha256_text(actual) != expected_quote_sha
    ):
        raise SourceMismatch("anchor quote hash no longer matches this revision text")


# ---------------------------------------------------------------------------
# Server-side slices + highlight segments (code-point coordinates)
# ---------------------------------------------------------------------------


def highlight_segments(
    text: str, slice_start: int, slice_end: int, anchor_start: int, anchor_end: int
) -> list[dict[str, Any]]:
    """Cut server-side highlight segments for one anchor inside a slice."""
    lo = max(slice_start, anchor_start)
    hi = min(slice_end, anchor_end)
    segments: list[dict[str, Any]] = []
    if lo >= hi:
        segments.append({"text": text[slice_start:slice_end], "highlight": False})
        return segments
    if lo > slice_start:
        segments.append({"text": text[slice_start:lo], "highlight": False})
    segments.append({"text": text[lo:hi], "highlight": True})
    if hi < slice_end:
        segments.append({"text": text[hi:slice_end], "highlight": False})
    return segments


def window_for(
    text: str, start: int, end: int, *, radius: int = WINDOW_RADIUS
) -> dict[str, Any]:
    if radius < 0:
        raise BadCursor("window radius must be non-negative")
    slice_start = max(0, start - radius)
    slice_end = min(len(text), end + radius)
    return {
        "slice_start": slice_start,
        "slice_end": slice_end,
        "text": text[slice_start:slice_end],
        "segments": highlight_segments(text, slice_start, slice_end, start, end),
    }


def _remapped_chapter_ref(prefix: str, chapter_index: int, local: str) -> str:
    """Revision-scoped temp ID shared with T07 assembly (no second mapping).

    Mirrors ``assembly._remapped_chapter_id`` so the read path resolves the
    exact same refs without reimplementing the namespace elsewhere.
    """
    try:
        import assembly  # type: ignore

        return assembly._remapped_chapter_id(prefix, chapter_index, local)
    except (ImportError, AttributeError):
        pass
    import re as _re

    match = _re.match(r"^(src|ent|evt|clm)_(\d+)$", local or "")
    if match and match.group(1) == prefix:
        number = int(match.group(2))
    else:
        number = 0
    return f"{prefix}_{chapter_index:03d}{number:03d}"


def frozen_member_refs(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Collect the frozen (bundle, ref) member set of one review payload.

    Covers chapter_pair (single member, both ends), published_batch
    (every member, both ends) and legacy single-candidate payloads
    (left/right only). Order is deterministic; duplicates collapse.
    """
    seen: set[tuple[str, str]] = set()
    ordered: list[dict[str, str]] = []

    def _add(side: Any) -> None:
        if not isinstance(side, dict):
            return
        bundle, ref = side.get("bundle"), side.get("ref")
        if not isinstance(bundle, str) or not bundle:
            return
        if not isinstance(ref, str) or not ref:
            return
        if (bundle, ref) in seen:
            return
        seen.add((bundle, ref))
        ordered.append({"bundle": bundle, "ref": ref})

    members = payload.get("members")
    if isinstance(members, list) and members:
        for member in members:
            if not isinstance(member, dict):
                continue
            _add(member.get("left"))
            _add(member.get("right"))
    else:
        _add(payload.get("left"))
        _add(payload.get("right"))
    ordered.sort(key=lambda item: (item["bundle"], item["ref"]))
    return ordered


def group_member_refs(
    payload: dict[str, Any], group_id: str | None
) -> list[dict[str, str]] | None:
    """Return the frozen refs for one group, or None when group is unknown."""
    if group_id is None:
        return None
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return None
    for group in groups:
        if not isinstance(group, dict):
            continue
        if group.get("review_group_id") != group_id:
            continue
        seen: set[tuple[str, str]] = set()
        ordered: list[dict[str, str]] = []
        for member in group.get("members") or []:
            if not isinstance(member, dict):
                continue
            for side in (member.get("left"), member.get("right")):
                if not isinstance(side, dict):
                    continue
                bundle, ref = side.get("bundle"), side.get("ref")
                if not isinstance(bundle, str) or not isinstance(ref, str):
                    continue
                if (bundle, ref) in seen:
                    continue
                seen.add((bundle, ref))
                ordered.append({"bundle": bundle, "ref": ref})
        ordered.sort(key=lambda item: (item["bundle"], item["ref"]))
        return ordered
    return None


def load_chapter_lookup(conn, *, job_id: Any) -> dict[str, Any]:
    """Index accepted chapter artifacts of one job for evidence lookup.

    Returns ``{"by_ref": ..., "anchors_by_record": ..., "anchors_by_id": ...}``
    where ``by_ref[revision_ref]`` carries chapter/artifact/revision/source
    provenance and ``anchors_by_record[revision_ref]`` lists the exact
    anchors bound to that record (record_sources + mention + translation
    selections, deduped by anchor_id). Empty when the job predates
    chapter artifacts (old partial fixtures stay ``unavailable``).
    """
    rows = conn.execute(
        """
        SELECT artifact_sha256, chapter_id, chapter_index, payload
        FROM chronicle.chapter_artifacts
        WHERE job_id = %s
        ORDER BY chapter_index, chapter_id
        """,
        (job_id,),
    ).fetchall()
    by_ref: dict[str, dict[str, Any]] = {}
    anchors_by_record: dict[str, list[dict[str, Any]]] = {}
    anchors_by_id: dict[str, dict[str, Any]] = {}
    anchor_records: dict[str, set[str]] = {}

    def _attach_anchor(revision_ref: str, anchor: dict[str, Any]) -> None:
        if not isinstance(anchor, dict):
            return
        anchor_id = anchor.get("anchor_id")
        if not isinstance(anchor_id, str) or not anchor_id:
            return
        bucket = anchors_by_record.setdefault(revision_ref, [])
        if all(item.get("anchor_id") != anchor_id for item in bucket):
            bucket.append(anchor)
        anchors_by_id.setdefault(anchor_id, anchor)
        anchor_records.setdefault(anchor_id, set()).add(revision_ref)

    for artifact_sha256, chapter_id, chapter_index, payload in rows:
        artifact = payload if isinstance(payload, dict) else {}
        candidate = artifact.get("candidate") if isinstance(artifact, dict) else {}
        if not isinstance(candidate, dict):
            continue
        try:
            chapter_index_int = int(chapter_index)
        except (TypeError, ValueError):
            continue
        bundle = candidate.get("bundle") if isinstance(candidate.get("bundle"), dict) else {}
        source_title = bundle.get("source", {}).get("title") if isinstance(bundle.get("source"), dict) else None
        revision_id = artifact.get("revision_id")
        source_sha256 = artifact.get("source_sha256")
        normalized_sha256 = artifact.get("normalized_sha256")
        anchors: list[dict[str, Any]] = (
            artifact.get("anchors") if isinstance(artifact.get("anchors"), list) else []
        )
        anchor_by_quote_key: dict[tuple[int, int, str], dict[str, Any]] = {}
        for anchor in anchors:
            if not isinstance(anchor, dict):
                continue
            try:
                key = (int(anchor.get("start", -1)), int(anchor.get("end", -1)), str(anchor.get("quote_sha256")))
            except (TypeError, ValueError):
                continue
            anchor_by_quote_key.setdefault(key, anchor)
            anchors_by_id.setdefault(str(anchor.get("anchor_id") or ""), anchor)

        def _register(prefix: str, local: Any) -> str | None:
            if not isinstance(local, str) or not local:
                return None
            return _remapped_chapter_ref(prefix, chapter_index_int, local)

        for collection, prefix in (
            ("entities", "ent"),
            ("events", "evt"),
            ("claims", "clm"),
        ):
            records = bundle.get(collection) if isinstance(bundle, dict) else None
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                local = record.get("temp_id")
                revision_ref = _register(prefix, local)
                if revision_ref is None:
                    continue
                by_ref.setdefault(
                    revision_ref,
                    {
                        "chapter_id": chapter_id,
                        "chapter_index": chapter_index_int,
                        "chapter_title": chapter_id,
                        "artifact_sha256": artifact_sha256,
                        "revision_id": revision_id,
                        "source_sha256": source_sha256,
                        "normalized_sha256": normalized_sha256,
                        "source_title": source_title
                        if isinstance(source_title, str) and source_title
                        else None,
                        "kind": "entity" if prefix == "ent" else "event"
                        if prefix == "evt"
                        else "claim",
                    },
                )
        # Record sources: exact per-record provenance (mandatory path).
        for entry in candidate.get("record_sources") or []:
            if not isinstance(entry, dict):
                continue
            revision_ref = _register("ent", entry.get("record_ref"))
            if revision_ref is None or revision_ref not in by_ref:
                revision_ref = _register("evt", entry.get("record_ref"))
            if revision_ref is None or revision_ref not in by_ref:
                # Fall back to either namespace when the local prefix is
                # ambiguous; only accept refs already registered above.
                continue
            for selection in entry.get("selections") or []:
                if not isinstance(selection, dict):
                    continue
                quote = selection.get("quote")
                occurrence = selection.get("occurrence")
                matched: dict[str, Any] | None = None
                if isinstance(quote, str) and quote:
                    from hashlib import sha256 as _sha256

                    quote_sha = _sha256(quote.encode("utf-8")).hexdigest()
                    for anchor in anchors:
                        if not isinstance(anchor, dict):
                            continue
                        if anchor.get("quote_sha256") == quote_sha and anchor.get(
                            "occurrence"
                        ) == occurrence:
                            matched = anchor
                            break
                if matched is not None:
                    _attach_anchor(revision_ref, matched)
        # Mentions: surface evidence targeting one entity.
        for mention in candidate.get("mentions") or []:
            if not isinstance(mention, dict):
                continue
            selection = mention.get("selection") if isinstance(mention.get("selection"), dict) else None
            anchor: dict[str, Any] | None = None
            if selection is not None:
                quote = selection.get("quote")
                occurrence = selection.get("occurrence")
                if isinstance(quote, str) and quote:
                    from hashlib import sha256 as _sha256

                    quote_sha = _sha256(quote.encode("utf-8")).hexdigest()
                    for item in anchors:
                        if not isinstance(item, dict):
                            continue
                        if item.get("quote_sha256") == quote_sha and item.get(
                            "occurrence"
                        ) == occurrence:
                            anchor = item
                            break
            targets: list[str] = []
            for local in [mention.get("target_ref"), *(mention.get("candidate_refs") or [])]:
                revision_ref = _register("ent", local)
                if revision_ref is not None and revision_ref in by_ref:
                    targets.append(revision_ref)
            for revision_ref in targets:
                if anchor is not None:
                    _attach_anchor(revision_ref, anchor)
        # Translation blocks: entity/event refs keep chapter-scoped anchors.
        for block in (candidate.get("translation") or {}).get("blocks") or []:
            if not isinstance(block, dict):
                continue
            source_ids = block.get("source_block_ids") if isinstance(block.get("source_block_ids"), list) else []
            block_anchors: list[dict[str, Any]] = []
            for source_block_id in source_ids:
                for anchor in anchors:
                    if isinstance(anchor, dict) and anchor.get("first_block_id") == source_block_id and anchor.get(
                        "last_block_id"
                    ) == source_block_id:
                        block_anchors.append(anchor)
            refs: list[str] = []
            for ref in (block.get("entity_refs") or []) + (block.get("event_refs") or []):
                if not isinstance(ref, dict):
                    continue
                kind = ref.get("kind")
                prefix = "ent" if kind == "entity" else "evt" if kind == "event" else None
                if prefix is None:
                    continue
                revision_ref = _register(prefix, ref.get("ref"))
                if revision_ref is not None and revision_ref in by_ref:
                    refs.append(revision_ref)
            for revision_ref in refs:
                for anchor in block_anchors:
                    _attach_anchor(revision_ref, anchor)

    for bucket in anchors_by_record.values():
        bucket.sort(
            key=lambda item: (
                int(item.get("start", 0)),
                int(item.get("end", 0)),
                str(item.get("anchor_id")),
            )
        )
    return {
        "by_ref": by_ref,
        "anchors_by_record": anchors_by_record,
        "anchors_by_id": anchors_by_id,
        "anchor_records": {key: sorted(value) for key, value in anchor_records.items()},
    }


def chapter_page_for(
    text: str,
    offset: int,
    *,
    limit: int = CHAPTER_PAGE_MAX,
    anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise BadCursor("chapter cursor offset must be a non-negative integer")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise BadCursor("chapter page limit must be a positive integer")
    if offset > len(text):
        raise BadCursor("chapter cursor is past the end of this chapter")
    slice_end = min(len(text), offset + limit)
    segments: list[dict[str, Any]] | None = None
    if anchor is not None:
        try:
            a_start, a_end = int(anchor["start"]), int(anchor["end"])
        except (KeyError, TypeError, ValueError):
            a_start, a_end = -1, -1
        if a_end > offset and a_start < slice_end:
            segments = highlight_segments(text, offset, slice_end, a_start, a_end)
    if segments is None:
        segments = [{"text": text[offset:slice_end], "highlight": False}]
    has_more = slice_end < len(text)
    return {
        "slice_start": offset,
        "slice_end": slice_end,
        "text": text[offset:slice_end],
        "segments": segments,
        "has_more": has_more,
    }
