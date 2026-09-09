"""Public chapter directory, full translation and pinned-source API (C2-R1-T14).

Read-only public surface over already-published chapters
(``chapter-production.md`` §7). Python-internal routes are fixed as
``/v0/chapters*`` on the shared public router; ``server.py`` injects the
configured ``storage_dir`` and T17 maps the Rust
``/api/v1/public/chapters*`` frontend paths onto these.

Contract summary:

- Directory lists only published chapters ordered by
  ``(document_id, revision_no, chapter_index, publication_id)`` with a
  stable versioned cursor; ``limit`` is ``1..100`` (default 50).
  Accepted-but-unpublished artifacts never appear here.
- Detail returns the complete ordered translation blocks plus a source
  overview and the precomputed (remapped + canonicalized) object/event
  references. It returns the full text or fails explicitly; it never
  serves a summary/first-paragraph/blurb as the full text and never
  guesses a missing reference mapping.
- Each served block additionally carries the server-owned
  `source_anchor_ids` (anchors whose first/last source block touches the
  block's `source_block_ids`) and each block-level ref carries the
  remapped `revision_ref` joining it to `references[]`; the source `ref`
  is preserved. This is the T17 reader seam: the browser opens sources
  and detail links from these fields without guessing.
- Sources first verify that the anchor belongs to the addressed
  publication (same publication/artifact/revision), then reuse the
  unique T10 ``source_context`` reader. Old pages stay pinned to the
  old revision/hash; identical text under another publication never
  authorizes a read.
- All GETs are read-only: no model calls, no canonical-ID allocation,
  no data repair. Responses larger than the 8 MiB forwarding cap fail
  explicitly instead of being truncated.
"""

from __future__ import annotations

import base64
import json
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import source_context as _source_context

# The chapter store, T01 contract validators and persistence errors live in
# the sibling persistence package (same bootstrap as server.py so this
# module also imports cleanly outside the server process).
_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
if str(_PERSISTENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE_DIR))

import chapter_contract as _chapter_contract  # noqa: E402
import chapter_store as _chapter_store  # noqa: E402
from common import PersistenceError as _PersistenceError  # noqa: E402
from common import sha256_json as _sha256_json  # noqa: E402

#: Rust forwarding cap mirrored here: oversized full texts fail
#: explicitly instead of being truncated mid-response.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

CHAPTERS_PREFIX = "/v0/chapters"
_DIRECTORY_CURSOR_VERSION = 1
_PUBLIC_SOURCE_CURSOR_VERSION = 1
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


class _BadRequest(Exception):
    pass


class _NotFound(Exception):
    pass


class _MethodNotAllowed(Exception):
    pass


class _Conflict(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return status, {
        "schema": "chronicle.error",
        "version": "0.1",
        "error": {"code": code, "message": message},
    }


def _single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise _BadRequest(f"query parameter {name} must appear once")
    return values[0]


# ---------------------------------------------------------------------------
# Opaque cursors (scope-bound, versioned)
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
        raise _BadRequest(f"{what} cursor is not valid: {exc}") from exc
    if not isinstance(payload, dict):
        raise _BadRequest(f"{what} cursor is not valid")
    return payload


def encode_directory_cursor(
    *,
    document_id: str,
    revision_no: int,
    chapter_index: int,
    publication_id: str,
) -> str:
    return _b64encode(
        {
            "v": _DIRECTORY_CURSOR_VERSION,
            "scope": "chapter-directory",
            "document_id": str(document_id),
            "revision_no": int(revision_no),
            "chapter_index": int(chapter_index),
            "publication_id": str(publication_id),
        }
    )


def decode_directory_cursor(raw: str) -> dict[str, Any]:
    payload = _b64decode(raw, what="directory")
    if payload.get("v") != _DIRECTORY_CURSOR_VERSION:
        raise _BadRequest("directory cursor version is not supported")
    if payload.get("scope") != "chapter-directory":
        raise _BadRequest("directory cursor belongs to a different scope")
    try:
        document_id = str(uuid.UUID(str(payload.get("document_id"))))
        publication_id = str(uuid.UUID(str(payload.get("publication_id"))))
        revision_no = int(payload.get("revision_no"))
        chapter_index = int(payload.get("chapter_index"))
    except (ValueError, AttributeError, TypeError) as exc:
        raise _BadRequest("directory cursor carries an invalid sort key") from exc
    if (
        isinstance(revision_no, bool)
        or isinstance(chapter_index, bool)
        or revision_no < 0
        or chapter_index < 0
    ):
        raise _BadRequest("directory cursor carries an invalid sort key")
    return {
        "document_id": document_id,
        "revision_no": revision_no,
        "chapter_index": chapter_index,
        "publication_id": publication_id,
    }


def encode_public_source_cursor(
    *, publication_id: str, anchor_id: str, view: str, offset: int
) -> str:
    return _b64encode(
        {
            "v": _PUBLIC_SOURCE_CURSOR_VERSION,
            "scope": "public-chapter-source",
            "publication_id": str(publication_id),
            "anchor_id": str(anchor_id),
            "view": str(view),
            "offset": int(offset),
        }
    )


def decode_public_source_cursor(
    raw: str, *, publication_id: str, anchor_id: str, view: str
) -> int:
    payload = _b64decode(raw, what="source")
    if payload.get("v") != _PUBLIC_SOURCE_CURSOR_VERSION:
        raise _BadRequest("source cursor version is not supported")
    if payload.get("scope") != "public-chapter-source":
        raise _BadRequest("source cursor belongs to a different scope")
    if str(payload.get("publication_id") or "") != str(publication_id):
        raise _BadRequest("source cursor belongs to a different publication")
    if str(payload.get("anchor_id") or "") != str(anchor_id):
        raise _BadRequest("source cursor belongs to a different anchor")
    if str(payload.get("view") or "") != str(view):
        raise _BadRequest("source cursor belongs to a different view")
    offset = payload.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise _BadRequest("source cursor carries an invalid offset")
    return offset


def check_response_size(payload: dict[str, Any]) -> bytes:
    """Serialize a response or fail explicitly past the forwarding cap.

    Full texts that exceed 8 MiB are reported as an explicit failure;
    they are never truncated into a partial success.
    """
    raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(raw) > MAX_RESPONSE_BYTES:
        raise _Conflict(
            "response_too_large",
            f"complete chapter response is {len(raw)} bytes, above the "
            f"{MAX_RESPONSE_BYTES}-byte forwarding cap; refusing to truncate",
        )
    return raw


# ---------------------------------------------------------------------------
# Publication loading (published rows only; unpublished 404s)
# ---------------------------------------------------------------------------


def _require_publication_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _NotFound(f"unknown publication {value!r}") from exc


def _load_publication(conn, publication_id: uuid.UUID) -> dict[str, Any]:
    try:
        full = _chapter_store.read_published_chapter(conn, publication_id=publication_id)
    except _PersistenceError as exc:
        raise _NotFound(f"unknown publication {publication_id}") from exc
    directory = conn.execute(
        """
        SELECT d.document_id, d.title, r.revision_no, r.filename
        FROM chronicle.documents d
        JOIN chronicle.document_revisions r
          ON r.document_id = d.document_id
        WHERE d.document_id = %s AND r.revision_id = %s
        """,
        (full["document_id"], full["revision_id"]),
    ).fetchone()
    if directory is None:  # pragma: no cover - FK guards this
        raise _Conflict(
            "publication_unavailable",
            f"publication {publication_id} has no readable document binding",
        )
    return {
        **full,
        "document_title": directory[1],
        "revision_no": int(directory[2]),
        "filename": directory[3],
    }


def _load_assembled_output(
    conn, *, job_id: Any, assembled_bundle_sha256: str
) -> dict[str, Any]:
    """Load the exact assembled output one publication was built against.

    A job may hold several ``assembled-source-bundle`` outputs (retries /
    rebuilds); the read path must bind the publication's own
    ``assembled_bundle_sha256`` instead of the newest row, and must verify
    the stored payload still hashes to it. Anything else fails explicitly
    instead of mixing an old translation with a newer object mapping.
    """
    row = conn.execute(
        """
        SELECT payload FROM chronicle.ingestion_outputs
        WHERE job_id = %s AND artifact_type = %s AND artifact_sha256 = %s
        """,
        (job_id, "assembled-source-bundle", assembled_bundle_sha256),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise _Conflict(
            "reference_unavailable",
            "assembled chapter bundle for this publication is not persisted; "
            "refusing to guess reference mappings",
        )
    payload = row[0]
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        raise _Conflict(
            "reference_unavailable",
            "assembled output for this publication carries no bundle; "
            "refusing to guess reference mappings",
        )
    if _sha256_json(bundle) != assembled_bundle_sha256:
        raise _Conflict(
            "reference_unavailable",
            "assembled output payload no longer hashes to this "
            "publication's bundle; refusing to mix versions",
        )
    declared = payload.get("bundle_sha256")
    if (
        isinstance(declared, str)
        and declared
        and declared != assembled_bundle_sha256
    ):
        raise _Conflict(
            "reference_unavailable",
            "assembled output declares a different bundle hash than this "
            "publication; refusing to mix versions",
        )
    return payload


def _chapter_title_from_assembled(
    assembled: dict[str, Any], *, chapter_id: str
) -> str:
    report = assembled.get("report")
    chapters = (
        report.get("plan", {}).get("chapters")
        if isinstance(report, dict)
        else None
    )
    if isinstance(chapters, list):
        for entry in chapters:
            if isinstance(entry, dict) and entry.get("chapter_id") == chapter_id:
                title = entry.get("title")
                if isinstance(title, str) and title:
                    return title
    raise _Conflict(
        "reference_unavailable",
        f"chapter {chapter_id!r} has no recorded title in its assembled "
        "bundle; refusing to substitute an identifier",
    )


def _local_to_revision_map(assembled: dict[str, Any]) -> dict[str, str]:
    mapping = assembled.get("chapter_by_ref")
    report = assembled.get("report")
    local_map: Any = None
    if isinstance(report, dict):
        local_map = report.get("local_to_revision")
    if not isinstance(local_map, dict):
        # Older outputs may carry the map at the top level.
        local_map = assembled.get("local_to_revision")
    if not isinstance(local_map, dict) or not local_map:
        raise _Conflict(
            "reference_unavailable",
            "assembled bundle carries no local-to-revision map; refusing "
            "to guess reference mappings",
        )
    try:
        return {str(key): str(value) for key, value in local_map.items()}
    except (ValueError, TypeError) as exc:  # pragma: no cover - defensive
        raise _Conflict(
            "reference_unavailable",
            f"assembled local-to-revision map is malformed: {exc}",
        ) from exc


def _canonical_maps(conn, *, catalog_sha256: str) -> tuple[dict, dict]:
    row = conn.execute(
        """
        SELECT payload FROM chronicle.canonical_catalogs
        WHERE artifact_sha256 = %s
        """,
        (catalog_sha256,),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise _Conflict(
            "catalog_unavailable",
            "canonical catalog for this publication is not persisted; "
            "refusing to serve references without their catalog",
        )
    catalog = row[0]
    entities: dict[str, dict[str, Any]] = {}
    for record in catalog.get("canonical_entities") or []:
        if not isinstance(record, dict):
            continue
        canonical_id = record.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id:
            continue
        for representation in record.get("representations") or []:
            if not isinstance(representation, dict):
                continue
            bundle, ref = representation.get("bundle"), representation.get("ref")
            if not isinstance(bundle, str) or not isinstance(ref, str):
                continue
            entities.setdefault(
                ref, {"canonical_id": canonical_id, "bundle": bundle, "ref": ref}
            )
    events: dict[str, dict[str, Any]] = {}
    for record in catalog.get("canonical_events") or []:
        if not isinstance(record, dict):
            continue
        canonical_id = record.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id:
            continue
        for representation in record.get("representations") or []:
            if not isinstance(representation, dict):
                continue
            bundle, ref = representation.get("bundle"), representation.get("ref")
            if not isinstance(bundle, str) or not isinstance(ref, str):
                continue
            events.setdefault(
                ref, {"canonical_id": canonical_id, "bundle": bundle, "ref": ref}
            )
    return entities, events


def _display_name(conn, *, bundle: str, ref: str, kind: str) -> str:
    table = (
        "chronicle.staged_entities"
        if kind == "entity"
        else "chronicle.staged_events"
    )
    row = conn.execute(
        f"SELECT payload FROM {table} WHERE bundle_label = %s AND record_ref = %s",
        (bundle, ref),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise _Conflict(
            "reference_unavailable",
            f"reference {bundle}:{ref} has no persisted staged record; "
            "refusing to invent a display label",
        )
    record = row[0]
    if kind == "entity":
        name = record.get("canonical_name") or record.get("name")
    else:
        name = record.get("title") or record.get("name")
    if not isinstance(name, str) or not name:
        raise _Conflict(
            "reference_unavailable",
            f"reference {bundle}:{ref} carries no readable name; refusing "
            "to invent a display label",
        )
    return name


# ---------------------------------------------------------------------------
# Directory
# ---------------------------------------------------------------------------


def _parse_directory(query: dict[str, list[str]]) -> dict[str, Any]:
    unknown = sorted(set(query) - {"limit", "cursor"})
    if unknown:
        raise _BadRequest(f"unsupported query parameters: {unknown}")
    raw_limit = _single(query, "limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else _DEFAULT_LIMIT
    except ValueError as exc:
        raise _BadRequest("limit must be an integer") from exc
    if isinstance(limit, bool) or not 1 <= limit <= _MAX_LIMIT:
        raise _BadRequest(f"limit must be within 1..{_MAX_LIMIT}")
    return {"limit": limit, "cursor_raw": _single(query, "cursor")}


def handle_directory(conn, *, raw_query: str) -> dict[str, Any]:
    spec = _parse_directory(parse_qs(raw_query, keep_blank_values=True))
    params: list[Any] = []
    keyset = ""
    if spec["cursor_raw"] is not None:
        cursor = decode_directory_cursor(spec["cursor_raw"])
        keyset = (
            "AND (d.document_id::text, r.revision_no, a.chapter_index, "
            "p.publication_id::text) > (%s, %s, %s, %s)"
        )
        params.extend(
            [
                cursor["document_id"],
                cursor["revision_no"],
                cursor["chapter_index"],
                cursor["publication_id"],
            ]
        )
    params.append(spec["limit"] + 1)
    rows = conn.execute(
        f"""
        SELECT p.publication_id, p.artifact_sha256, p.catalog_sha256,
               p.assembled_bundle_sha256,
               p.document_id, d.title, p.revision_id, r.revision_no,
               p.job_id, p.chapter_id, a.chapter_index, p.published_at
        FROM chronicle.chapter_publications p
        JOIN chronicle.chapter_artifacts a
          ON a.artifact_sha256 = p.artifact_sha256
        JOIN chronicle.documents d ON d.document_id = p.document_id
        JOIN chronicle.document_revisions r ON r.revision_id = p.revision_id
        WHERE 1 = 1 {keyset}
        ORDER BY d.document_id, r.revision_no, a.chapter_index, p.publication_id
        LIMIT %s
        """,
        tuple(params),
    ).fetchall()
    has_more = len(rows) > spec["limit"]
    page = rows[: spec["limit"]]
    assembled_cache: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    for row in page:
        (
            publication_id,
            artifact_sha256,
            catalog_sha256,
            assembled_bundle_sha256,
            document_id,
            document_title,
            revision_id,
            revision_no,
            job_id,
            chapter_id,
            chapter_index,
            published_at,
        ) = (
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
            row[8], row[9], row[10], row[11],
        )
        # Exact per-publication binding: the same job may hold newer
        # assembled outputs that an old publication must never read.
        cache_key = f"{job_id}:{assembled_bundle_sha256}"
        assembled = assembled_cache.get(cache_key)
        if assembled is None:
            assembled = _load_assembled_output(
                conn,
                job_id=job_id,
                assembled_bundle_sha256=assembled_bundle_sha256,
            )
            assembled_cache[cache_key] = assembled
        items.append(
            {
                "publication_id": str(publication_id),
                "document_id": str(document_id),
                "document_title": document_title,
                "revision_id": str(revision_id),
                "revision_no": int(revision_no),
                "job_id": str(job_id),
                "chapter_id": chapter_id,
                "chapter_index": int(chapter_index),
                "chapter_title": _chapter_title_from_assembled(
                    assembled, chapter_id=chapter_id
                ),
                "artifact_sha256": artifact_sha256,
                "catalog_sha256": catalog_sha256,
                "published_at": published_at.isoformat() if published_at is not None else None,
            }
        )
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_directory_cursor(
            document_id=str(last[4]),
            revision_no=int(last[7]),
            chapter_index=int(last[10]),
            publication_id=str(last[0]),
        )
    return {
        "schema": "chronicle.chapter-directory",
        "version": "0.1",
        "query": {"limit": spec["limit"]},
        "items": items,
        "next_cursor": next_cursor,
    }


# ---------------------------------------------------------------------------
# Detail (complete ordered blocks + precomputed references, or explicit fail)
# ---------------------------------------------------------------------------


def handle_detail(conn, publication_id: uuid.UUID) -> dict[str, Any]:
    full = _load_publication(conn, publication_id)
    publication = full.get("publication")
    if not isinstance(publication, dict):
        raise _Conflict(
            "publication_unavailable",
            f"publication {publication_id} carries no readable payload",
        )
    blocks = publication.get("translation_blocks")
    if not isinstance(blocks, list) or not blocks:
        raise _Conflict(
            "publication_unavailable",
            f"publication {publication_id} carries no complete translation "
            "blocks; refusing to present a summary as the full text",
        )
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            raise _Conflict(
                "publication_unavailable",
                f"publication {publication_id} block #{index} is not a "
                "complete translation block",
            )
    assembled = _load_assembled_output(
        conn,
        job_id=full["job_id"],
        assembled_bundle_sha256=str(full["assembled_bundle_sha256"]),
    )
    chapter_index = int(full["chapter_index"])
    chapter_id = str(full["chapter_id"])
    chapter_title = _chapter_title_from_assembled(assembled, chapter_id=chapter_id)
    local_map = _local_to_revision_map(assembled)
    entity_index, event_index = _canonical_maps(
        conn, catalog_sha256=str(full["catalog_sha256"])
    )

    def _remap(local: Any, *, block_id: str) -> str:
        if not isinstance(local, str) or not local:
            raise _Conflict(
                "reference_unmapped",
                f"publication {publication_id} block {block_id!r} carries "
                "an empty reference; refusing to guess",
            )
        revision_ref = local_map.get(f"({chapter_index},{local})")
        if revision_ref is None:
            raise _Conflict(
                "reference_unmapped",
                f"publication {publication_id} block {block_id!r} reference "
                f"{local!r} has no assembled revision mapping; refusing "
                "to guess",
            )
        return revision_ref

    references_entities: list[dict[str, Any]] = []
    references_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block in blocks:
        block_id = str(block.get("block_id"))
        for entry in list(block.get("entity_refs") or []) + list(
            block.get("event_refs") or []
        ):
            if not isinstance(entry, dict):
                raise _Conflict(
                    "reference_unmapped",
                    f"publication {publication_id} block {block_id!r} "
                    "carries a malformed reference",
                )
            kind = entry.get("kind")
            if kind not in ("entity", "event"):
                raise _Conflict(
                    "reference_unmapped",
                    f"publication {publication_id} block {block_id!r} "
                    f"reference kind {kind!r} is not entity|event",
                )
            revision_ref = _remap(entry.get("ref"), block_id=block_id)
            key = (kind, revision_ref)
            if key in seen:
                continue
            seen.add(key)
            index_map = entity_index if kind == "entity" else event_index
            canonical = index_map.get(revision_ref)
            if canonical is None:
                raise _Conflict(
                    "reference_unmapped",
                    f"publication {publication_id} reference {revision_ref!r} "
                    "has no canonical mapping in this publication's catalog; "
                    "refusing to guess",
                )
            name = _display_name(
                conn,
                bundle=canonical["bundle"],
                ref=revision_ref,
                kind=kind,
            )
            item = {
                "ref": revision_ref,
                "canonical_id": canonical["canonical_id"],
                "block_id": block_id,
                **({"name": name} if kind == "entity" else {"title": name}),
            }
            if kind == "entity":
                references_entities.append(item)
            else:
                references_events.append(item)

    anchors = publication.get("anchors")
    anchor_list = anchors if isinstance(anchors, list) else []
    # T17 reader seam: every translation block carries the server-owned
    # `source_anchor_ids` so the browser can open an anchor's pinned source
    # without guessing. An anchor belongs to a block when the anchor's
    # first/last source block touches one of the block's source_block_ids
    # (whole-block anchors match exactly; selection anchors attach to their
    # boundary blocks). Block-level entity/event refs keep their source
    # `ref` and additionally carry the remapped `revision_ref` that joins
    # them to `references[]` (whose `ref` is the revision namespaced id).
    served_blocks: list[dict[str, Any]] = []
    for block in blocks:
        served = dict(block)
        source_ids = served.get("source_block_ids")
        owned_source_ids = (
            [str(item) for item in source_ids if isinstance(item, str)]
            if isinstance(source_ids, list)
            else []
        )
        anchor_ids: list[str] = []
        for anchor in anchor_list:
            if not isinstance(anchor, dict):
                continue
            anchor_id = anchor.get("anchor_id")
            if not isinstance(anchor_id, str) or not anchor_id:
                continue
            first = anchor.get("first_block_id")
            last = anchor.get("last_block_id")
            if (isinstance(first, str) and first in owned_source_ids) or (
                isinstance(last, str) and last in owned_source_ids
            ):
                if anchor_id not in anchor_ids:
                    anchor_ids.append(anchor_id)
        anchor_ids.sort()
        served["source_anchor_ids"] = anchor_ids
        for refs_key in ("entity_refs", "event_refs"):
            entries = served.get(refs_key)
            if not isinstance(entries, list):
                continue
            annotated: list[Any] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    annotated.append(entry)
                    continue
                local_ref = entry.get("ref")
                revision_ref = (
                    local_map.get(f"({chapter_index},{local_ref})")
                    if isinstance(local_ref, str) and local_ref
                    else None
                )
                annotated_entry = dict(entry)
                annotated_entry["revision_ref"] = revision_ref
                annotated.append(annotated_entry)
            served[refs_key] = annotated
        served_blocks.append(served)
    response = {
        "schema": "chronicle.public-chapter",
        "version": "0.1",
        "publication_id": str(full["publication_id"]),
        "document_id": str(full["document_id"]),
        "document_title": full["document_title"],
        "revision_id": str(full["revision_id"]),
        "revision_no": int(full["revision_no"]),
        "job_id": str(full["job_id"]),
        "chapter_id": chapter_id,
        "chapter_index": chapter_index,
        "chapter_title": chapter_title,
        "artifact_sha256": str(full["artifact_sha256"]),
        "catalog_sha256": str(full["catalog_sha256"]),
        "assembled_bundle_sha256": str(full["assembled_bundle_sha256"]),
        "published_at": full["published_at"],
        "translation_blocks": served_blocks,
        "source_overview": {
            "source_title": full["document_title"],
            "chapter_title": chapter_title,
            "revision_id": str(full["revision_id"]),
            "block_count": len(blocks),
            "anchor_count": len(anchor_list),
        },
        "references": {
            "entities": references_entities,
            "events": references_events,
        },
    }
    errors = _chapter_contract.validate_public_chapter_response(
        {
            "publication_id": response["publication_id"],
            "chapter_id": response["chapter_id"],
            "revision_id": response["revision_id"],
            "translation_blocks": response["translation_blocks"],
            "source_overview": response["source_overview"],
            "references": response["references"],
        }
    )
    if errors:
        raise _Conflict(
            "publication_unavailable",
            "publication detail failed the T01 public-chapter contract: "
            + "; ".join(errors),
        )
    check_response_size(response)
    return response


# ---------------------------------------------------------------------------
# Sources (publication-pinned, via the shared T10 source reader)
# ---------------------------------------------------------------------------


def handle_source(
    conn,
    publication_id: uuid.UUID,
    anchor_id: str,
    *,
    raw_query: str,
    source_dir: Path | str | None,
) -> dict[str, Any]:
    query = parse_qs(raw_query, keep_blank_values=True)
    unknown = sorted(set(query) - {"view", "cursor", "limit"})
    if unknown:
        raise _BadRequest(f"unsupported query parameters: {unknown}")
    view = _single(query, "view") or "window"
    if view not in ("window", "chapter"):
        raise _BadRequest("view must be window|chapter")
    cursor_raw = _single(query, "cursor")
    limit_raw = _single(query, "limit")
    limit = _source_context.CHAPTER_PAGE_MAX
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise _BadRequest("limit must be an integer") from exc
        if view != "chapter":
            raise _BadRequest("limit is only supported for view=chapter")
        if (
            isinstance(limit, bool)
            or not 1 <= limit <= _source_context.CHAPTER_PAGE_MAX
        ):
            raise _BadRequest(
                f"limit must be within 1..{_source_context.CHAPTER_PAGE_MAX}"
            )

    full = _load_publication(conn, publication_id)
    publication = full.get("publication")
    anchors = (
        publication.get("anchors")
        if isinstance(publication, dict)
        else None
    )
    anchor: dict[str, Any] | None = None
    if isinstance(anchors, list):
        for item in anchors:
            if isinstance(item, dict) and item.get("anchor_id") == anchor_id:
                anchor = item
                break
    if anchor is None:
        # Unknown versions and cross-publication anchors never resolve
        # through another publication's bytes.
        raise _NotFound(
            f"source anchor {anchor_id!r} is not part of publication {publication_id}"
        )
    # The anchor must be bound to this exact publication revision/hash;
    # same text under another publication never authorizes this read.
    if str(anchor.get("revision_id") or "") != str(full["revision_id"]):
        raise _Conflict(
            "source_mismatch",
            "anchor revision does not match this publication's revision; "
            "refusing to substitute another version",
        )
    artifact = full.get("artifact") if isinstance(full.get("artifact"), dict) else {}
    expected_sha = str(artifact.get("source_sha256") or "")
    if not expected_sha or str(anchor.get("source_sha256") or "") != expected_sha:
        raise _Conflict(
            "source_mismatch",
            "anchor source hash does not match this publication's revision",
        )
    # Reuse the unique T10 chapter lookup (no second mapping): the anchor
    # must additionally resolve inside this job's accepted chapters.
    lookup = _source_context.load_chapter_lookup(conn, job_id=full["job_id"])
    if anchor_id not in (lookup.get("anchors_by_id") or {}):
        raise _Conflict(
            "source_unavailable",
            f"source anchor {anchor_id!r} is not bound to an accepted "
            "chapter of this publication",
        )
    chapter_id = anchor.get("chapter_id")
    if not isinstance(chapter_id, str) or not chapter_id:
        raise _Conflict("source_unavailable", "anchor has no chapter binding")
    try:
        bounds = _source_context.chapter_bounds(lookup, chapter_id)
    except _source_context.SourceUnavailable as exc:
        raise _Conflict("source_unavailable", str(exc)) from exc
    revision_row = conn.execute(
        """
        SELECT storage_key, source_sha256
        FROM chronicle.document_revisions WHERE revision_id = %s
        """,
        (full["revision_id"],),
    ).fetchone()
    if revision_row is None:
        raise _Conflict(
            "source_unavailable",
            "publication revision is no longer addressable",
        )
    storage_key, revision_sha = revision_row[0], revision_row[1]
    if str(revision_sha or "") != expected_sha:
        raise _Conflict(
            "source_mismatch",
            "publication revision hash drifted; refusing to read the new bytes",
        )
    if not isinstance(storage_key, str) or not storage_key:
        raise _Conflict("source_unavailable", "revision source is not configured")
    try:
        text = _source_context.read_revision_text(
            source_dir, storage_key, expected_sha
        )
    except _source_context.SourceUnavailable as exc:
        raise _Conflict("source_unavailable", str(exc)) from exc
    except _source_context.SourceMismatch as exc:
        raise _Conflict("source_mismatch", str(exc)) from exc
    chapter_start, chapter_end = bounds
    if not 0 <= chapter_start < chapter_end <= len(text):
        raise _Conflict(
            "source_mismatch",
            "recorded chapter boundary is outside this revision text",
        )
    chapter_text = text[chapter_start:chapter_end]
    try:
        _source_context.verify_anchor_in_chapter(anchor, chapter_text)
    except _source_context.SourceMismatch as exc:
        raise _Conflict("source_mismatch", str(exc)) from exc
    anchor_start, anchor_end = int(anchor["start"]), int(anchor["end"])
    rev_start, rev_end = chapter_start + anchor_start, chapter_start + anchor_end
    common = {
        "schema": "chronicle.public-chapter-source",
        "version": "0.1",
        "publication_id": str(full["publication_id"]),
        "anchor_id": anchor_id,
        "revision_id": str(full["revision_id"]),
        "source_sha256": expected_sha,
        "chapter_id": chapter_id,
        "bounds": {},
        "source_hash": _source_context.sha256_text(text),
        "chapter_hash": _source_context.sha256_text(chapter_text),
    }
    if view == "window":
        if cursor_raw is not None:
            raise _BadRequest("cursor is only supported for view=chapter")
        window = _source_context.window_in_chapter(
            chapter_text, anchor_start, anchor_end
        )
        payload = {
            **common,
            "view": "window",
            "bounds": {
                "start": rev_start,
                "end": rev_end,
                "slice_start": chapter_start + window["slice_start"],
                "slice_end": chapter_start + window["slice_end"],
                "chapter_start": chapter_start,
                "chapter_end": chapter_end,
                "chapter_length": len(chapter_text),
            },
            "text": window["text"],
            "segments": window["segments"],
            "has_more": False,
            "next_cursor": None,
        }
        check_response_size(payload)
        return payload
    offset = 0
    if cursor_raw is not None:
        offset = decode_public_source_cursor(
            cursor_raw,
            publication_id=str(full["publication_id"]),
            anchor_id=anchor_id,
            view=view,
        )
    if offset > len(chapter_text):
        raise _BadRequest("chapter cursor is past the end of this chapter")
    try:
        page = _source_context.chapter_page_for(
            chapter_text, offset, limit=limit, anchor=anchor
        )
    except _source_context.BadCursor as exc:
        raise _BadRequest(str(exc)) from exc
    payload = {
        **common,
        "view": "chapter",
        "bounds": {
            "start": rev_start,
            "end": rev_end,
            "slice_start": chapter_start + page["slice_start"],
            "slice_end": chapter_start + page["slice_end"],
            "chapter_start": chapter_start,
            "chapter_end": chapter_end,
            "chapter_length": len(chapter_text),
        },
        "text": page["text"],
        "segments": page["segments"],
        "has_more": page["has_more"],
        "next_cursor": (
            encode_public_source_cursor(
                publication_id=str(full["publication_id"]),
                anchor_id=anchor_id,
                view=view,
                offset=page["slice_end"],
            )
            if page["has_more"]
            else None
        ),
    }
    check_response_size(payload)
    return payload


# ---------------------------------------------------------------------------
# Dispatcher (mounted by the shared public router)
# ---------------------------------------------------------------------------


def dispatch_chapters(
    conn,
    *,
    method: str,
    path: str,
    raw_query: str = "",
    source_dir: Path | str | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        if method != "GET":
            raise _MethodNotAllowed(f"method {method} is not supported on {path}")
        return _route(conn, path=path, raw_query=raw_query, source_dir=source_dir)
    except _BadRequest as exc:
        return _error(400, "bad_request", str(exc))
    except _NotFound as exc:
        return _error(404, "not_found", str(exc))
    except _MethodNotAllowed as exc:
        return _error(405, "method_not_allowed", str(exc))
    except _Conflict as exc:
        return _error(409, exc.code, str(exc))


def _route(
    conn, *, path: str, raw_query: str, source_dir: Path | str | None
) -> tuple[int, dict[str, Any]]:
    if path == CHAPTERS_PREFIX:
        payload = handle_directory(conn, raw_query=raw_query)
        check_response_size(payload)
        return 200, payload
    prefix = CHAPTERS_PREFIX + "/"
    if not path.startswith(prefix):
        raise _NotFound("route not found")
    parts = path[len(prefix):].split("/")
    if len(parts) == 1 and parts[0]:
        publication_id = _require_publication_uuid(parts[0])
        return 200, handle_detail(conn, publication_id)
    if len(parts) == 3 and parts[0] and parts[1] == "sources" and parts[2]:
        publication_id = _require_publication_uuid(parts[0])
        payload = handle_source(
            conn,
            publication_id,
            parts[2],
            raw_query=raw_query,
            source_dir=source_dir,
        )
        return 200, payload
    raise _NotFound("route not found")
