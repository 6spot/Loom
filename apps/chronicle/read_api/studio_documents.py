"""Studio document endpoints for the Chronicle internal sidecar.

These routes live behind the Rust ``chronicle-server`` Studio namespace,
which enforces the single-administrator authentication boundary (C1-T2).
The sidecar itself is never published outside the deployment network; the
Rust proxy authenticates first and forwards only method/path/query/body.

Upload framing is deliberately multipart-free: revision uploads send the
raw file bytes as the request body with the filename and optional
language/source metadata as query parameters, so both the dependency-free
Rust proxy and this stdlib server forward bytes without a MIME parser.

All responses are JSON under a ``chronicle.*`` schema except the
``.../content`` endpoint, which returns the exact stored source bytes with
their canonical media type for audit and later ingestion stages.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import parse_qs

STUDIO_PREFIX = "/api/v1/studio/documents"


def _error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    payload = {
        "schema": "chronicle.error",
        "version": "0.1",
        "error": {"code": code, "message": message},
    }
    return status, "application/json; charset=utf-8", _json_bytes(payload)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise _BadRequest(f"query parameter {name} must appear once")
    return values[0]


class _BadRequest(Exception):
    pass


class _NotFound(Exception):
    pass


def _require_uuid(value: str, description: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _NotFound(f"{description} {value!r} is not a valid UUID") from exc


def dispatch_studio(
    conn,
    documents,
    *,
    storage_dir,
    max_upload_bytes: int,
    method: str,
    path: str,
    raw_query: str = "",
    body: bytes = b"",
    content_type: str | None = None,
) -> tuple[int, str, bytes]:
    """Serve one Studio document request.

    ``documents`` is the ``apps/chronicle/persistence/documents.py`` module
    (passed in so this router stays importable without persistence on
    sys.path). Returns ``(status, content_type, body_bytes)``.
    """
    from common import PersistenceError

    try:
        return _route(
            conn,
            documents,
            storage_dir=storage_dir,
            max_upload_bytes=max_upload_bytes,
            method=method,
            path=path,
            raw_query=raw_query,
            body=body,
            content_type=content_type,
        )
    except _BadRequest as exc:
        return _error(400, "bad_request", str(exc))
    except _NotFound as exc:
        return _error(404, "not_found", str(exc))
    except PersistenceError as exc:
        message = str(exc)
        if message.startswith("unknown "):
            return _error(404, "not_found", message)
        if "exceeds" in message and "limit" in message:
            return _error(413, "payload_too_large", message)
        return _error(400, "bad_request", message)


def _route(
    conn,
    documents,
    *,
    storage_dir,
    max_upload_bytes: int,
    method: str,
    path: str,
    raw_query: str,
    body: bytes,
    content_type: str | None,
) -> tuple[int, str, bytes]:
    query = parse_qs(raw_query, keep_blank_values=True)

    if path == STUDIO_PREFIX:
        if method == "GET":
            items = documents.list_documents(conn, storage_dir=storage_dir)
            return 200, "application/json; charset=utf-8", _json_bytes(
                {"schema": "chronicle.document-list", "version": "0.1", "documents": items}
            )
        if method == "POST":
            return _create_document(conn, body)
        raise _BadRequest(f"method {method} is not supported on {path}")

    prefix = STUDIO_PREFIX + "/"
    if not path.startswith(prefix):
        raise _NotFound("route not found")
    rest = path[len(prefix):]
    if not rest or "/" in rest.strip("/"):
        parts = rest.split("/")
        if len(parts) == 2 and parts[1] == "revisions" and parts[0]:
            document_id = _require_uuid(parts[0], "document")
            if method == "GET":
                history = documents.revision_history(
                    conn, document_id=document_id, storage_dir=storage_dir
                )
                return 200, "application/json; charset=utf-8", _json_bytes(
                    {
                        "schema": "chronicle.revision-list",
                        "version": "0.1",
                        "document_id": str(document_id),
                        "revisions": history,
                    }
                )
            if method == "POST":
                return _upload_revision(
                    conn,
                    documents,
                    document_id=document_id,
                    query=query,
                    body=body,
                    content_type=content_type,
                    storage_dir=storage_dir,
                    max_upload_bytes=max_upload_bytes,
                )
            raise _BadRequest(f"method {method} is not supported on {path}")
        if len(parts) == 3 and parts[1] == "revisions" and parts[0] and parts[2]:
            document_id = _require_uuid(parts[0], "document")
            if method != "GET":
                raise _BadRequest(f"method {method} is not supported on {path}")
            revision = _find_revision(
                conn, documents, document_id=document_id, ref=parts[2],
                storage_dir=storage_dir,
            )
            return 200, "application/json; charset=utf-8", _json_bytes(
                {
                    "schema": "chronicle.revision",
                    "version": "0.1",
                    "revision": revision,
                    "locator": documents.source_locator(revision),
                }
            )
        if (
            len(parts) == 4
            and parts[1] == "revisions"
            and parts[0]
            and parts[2]
            and parts[3] == "content"
        ):
            document_id = _require_uuid(parts[0], "document")
            if method != "GET":
                raise _BadRequest(f"method {method} is not supported on {path}")
            revision = _find_revision(
                conn, documents, document_id=document_id, ref=parts[2],
                storage_dir=storage_dir,
            )
            raw = documents.read_revision_bytes(storage_dir, revision["storage_key"])
            media = revision["source_media_type"] + "; charset=utf-8"
            return 200, media, raw
        if len(parts) == 1 and parts[0]:
            document_id = _require_uuid(parts[0], "document")
            if method != "GET":
                raise _BadRequest(f"method {method} is not supported on {path}")
            # Unknown documents surface as PersistenceError("unknown ..."),
            # which dispatch_studio maps to 404.
            document = documents.get_document(
                conn, document_id=document_id, storage_dir=storage_dir
            )
            return 200, "application/json; charset=utf-8", _json_bytes(
                {"schema": "chronicle.document", "version": "0.1", "document": document}
            )
    else:
        document_id = _require_uuid(rest, "document")
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        document = documents.get_document(
            conn, document_id=document_id, storage_dir=storage_dir
        )
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.document", "version": "0.1", "document": document}
        )
    raise _NotFound("route not found")


def _create_document(conn, body: bytes) -> tuple[int, str, bytes]:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _BadRequest(f"request body must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise _BadRequest("request body must be a JSON object")
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise _BadRequest("document title must be a non-empty string")
    import control_plane

    document_id = control_plane.create_document(conn, title=title.strip())
    return 201, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.document",
            "version": "0.1",
            "document": {
                "document_id": str(document_id),
                "title": title.strip(),
                "revision_count": 0,
                "active_revision": None,
            },
        }
    )


def _upload_revision(
    conn,
    documents,
    *,
    document_id: uuid.UUID,
    query: dict[str, list[str]],
    body: bytes,
    content_type: str | None,
    storage_dir,
    max_upload_bytes: int,
) -> tuple[int, str, bytes]:
    filename = _single(query, "filename")
    if not filename:
        raise _BadRequest("query parameter filename is required")
    language = _single(query, "language")
    source_label = _single(query, "source_label")
    if len(body) > max_upload_bytes:
        return _error(
            413,
            "payload_too_large",
            f"upload of {len(body)} bytes exceeds the {max_upload_bytes}-byte limit",
        )
    if not body:
        raise _BadRequest("upload body must not be empty")
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared in ("text/plain", "text/markdown"):
        expected = documents.media_type_for_filename(documents.sanitize_filename(filename))
        if declared != expected:
            raise _BadRequest(
                f"Content-Type {declared} does not match filename {filename!r}"
                f" (expected {expected})"
            )
    revision = documents.upload_revision(
        conn,
        storage_dir=storage_dir,
        document_id=document_id,
        filename=filename,
        data=body,
        language=language,
        source_label=source_label,
        max_bytes=max_upload_bytes,
    )
    status = 200 if revision.get("duplicate") else 201
    return status, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.revision",
            "version": "0.1",
            "revision": revision,
            "locator": documents.source_locator(revision),
        }
    )


def _find_revision(
    conn, documents, *, document_id: uuid.UUID, ref: str, storage_dir
) -> dict[str, Any]:
    """Resolve a revision by number (``2``) within its document, or by UUID."""
    from common import PersistenceError as _PE

    revision_id: uuid.UUID
    if ref.isdigit() and int(ref) >= 1:
        row = conn.execute(
            "SELECT revision_id FROM chronicle.document_revisions"
            " WHERE document_id = %s AND revision_no = %s",
            (document_id, int(ref)),
        ).fetchone()
        if row is None:
            raise _NotFound(f"revision number {ref!r} does not exist for document")
        revision_id = row[0]
    else:
        try:
            revision_id = uuid.UUID(ref)
        except ValueError as exc:
            raise _NotFound(f"revision {ref!r} is not a revision number or UUID") from exc
    try:
        revision = documents.get_revision(
            conn, revision_id=revision_id, storage_dir=storage_dir
        )
    except _PE as exc:
        raise _NotFound(str(exc)) from exc
    if revision["document_id"] != str(document_id):
        raise _NotFound(f"revision {ref!r} does not belong to document")
    return revision
