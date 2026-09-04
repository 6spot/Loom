"""Chronicle C1-T3 document upload, immutable revisions, and source storage.

Application-owned product persistence (Architecture Amendment 0006):
everything here uses only ``CHRONICLE_DATABASE_URL`` and the
``chronicle.*`` tables from the registered migration root
(``apps/chronicle/persistence/migrations/``). It never reads or writes
Loom Runtime/World/Timeline/Work/Binding state, never imports
``loom-storage``/``PgStorage``, and never consumes the Loom engine
connection contract.

Scope (C1-T3 stop condition): only controlled UTF-8 text (``.txt`` /
``.md``) is accepted. Anything that cannot be represented as controlled
UTF-8 text is rejected so a later task can own the adapter.

Durability model:

- The PostgreSQL row is the revision identity/metadata authority.
- The filesystem file under the Chronicle-owned data directory is the
  source-byte authority, addressed by a relative ``storage_key`` (never a
  machine-specific absolute path, so content survives restart/redeploy
  through the supported Chronicle data volume).
- Writes are atomic: bytes land in a temp sibling, are fsynced, then
  atomically renamed. A DB failure removes the temp file; a crash between
  commit and rename leaves a row whose ``storage_status`` reads
  ``missing``, which the next identical upload repairs instead of
  duplicating.
- Replacement is always a new revision row; revision rows are DB-trigger
  immutable, so history is never overwritten or deleted.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from common import PersistenceError

#: Controlled upload formats only: extension -> canonical media type.
ALLOWED_FORMATS: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
}

#: Default per-file upload ceiling (10 MiB), overridable via
#: CHRONICLE_MAX_UPLOAD_BYTES.
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: Longest accepted original filename (filesystem-portable bound).
MAX_FILENAME_LEN = 255


def max_upload_bytes(env: dict[str, str] | None = None) -> int:
    """Return the configured per-file upload ceiling in bytes."""
    source = env if env is not None else os.environ
    raw = (source.get("CHRONICLE_MAX_UPLOAD_BYTES") or "").strip()
    if not raw:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise PersistenceError(
            "CHRONICLE_MAX_UPLOAD_BYTES must be a positive integer"
        ) from exc
    if value < 1:
        raise PersistenceError(
            "CHRONICLE_MAX_UPLOAD_BYTES must be a positive integer"
        )
    return value


def storage_dir_from_env(env: dict[str, str] | None = None) -> Path:
    """Return the configured Chronicle-owned source data directory."""
    source = env if env is not None else os.environ
    raw = (source.get("CHRONICLE_SOURCE_DIR") or "").strip()
    if not raw:
        return Path.cwd() / "chronicle-sources"
    return Path(raw).expanduser()


def sanitize_filename(value: Any) -> str:
    """Validate an uploader-supplied filename down to a plain basename."""
    if not isinstance(value, str):
        raise PersistenceError("filename must be a string")
    name = value.strip()
    if not name or len(name) > MAX_FILENAME_LEN:
        raise PersistenceError("filename must be 1-255 characters")
    if (
        "/" in name
        or "\\" in name
        or name in (".", "..")
        or name.startswith(".")
        or ".." in name
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in name)
    ):
        raise PersistenceError(f"unsafe filename {value!r}")
    return name


def media_type_for_filename(filename: str) -> str:
    """Resolve the canonical media type for a controlled upload format."""
    ext = Path(filename).suffix.lower()
    try:
        return ALLOWED_FORMATS[ext]
    except KeyError as exc:
        raise PersistenceError(
            f"unsupported upload format for {filename!r}: only {sorted(ALLOWED_FORMATS)} are accepted"
        ) from exc


def decode_source(data: bytes) -> str:
    """Strictly decode upload bytes to normalized controlled text.

    Rejects non-UTF-8 input, strips one leading BOM, and normalizes
    CRLF/CR line endings to LF so downstream byte/char locators and hashes
    stay deterministic. The stored file keeps the original bytes verbatim;
    the hash is over those bytes.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise PersistenceError("upload content must be bytes")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PersistenceError(f"upload is not valid UTF-8: {exc}") from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def storage_key_for(document_id: uuid.UUID, revision_id: uuid.UUID, filename: str) -> str:
    """Derive the relative storage key for one revision's source file."""
    ext = Path(filename).suffix.lower() or ".txt"
    return f"documents/{document_id}/{revision_id}{ext}"


def resolve_storage_path(storage_dir: Path | str, storage_key: str) -> Path:
    """Resolve a relative storage key inside the data directory.

    Defense in depth: keys are server-derived, but resolution still refuses
    absolute keys, ``..`` segments, and backslashes so a corrupted row can
    never address outside the Chronicle-owned directory.
    """
    if not isinstance(storage_key, str) or not storage_key:
        raise PersistenceError("storage_key must be a non-empty string")
    if storage_key.startswith("/") or ".." in storage_key or "\\" in storage_key:
        raise PersistenceError(f"unsafe storage key {storage_key!r}")
    base = Path(storage_dir).expanduser().resolve()
    candidate = (base / Path(*storage_key.split("/"))).resolve()
    if candidate != base and base not in candidate.parents:
        raise PersistenceError(f"storage key escapes the data directory: {storage_key!r}")
    return candidate


def write_source_file(storage_dir: Path | str, storage_key: str, data: bytes) -> Path:
    """Atomically persist source bytes: temp + fsync + rename.

    Returns the final absolute path. A half-written file is never visible
    at the final path: readers either see the complete previous file or,
    after rename, the complete new one.
    """
    dest = resolve_storage_path(storage_dir, storage_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".tmp-{uuid.uuid4().hex}"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise PersistenceError(f"failed to store source file: {exc}") from exc
    return dest


def remove_path_safely(path: Path) -> None:
    """Best-effort unlink used for failure cleanup; never raises."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def storage_status(storage_dir: Path | str, storage_key: str) -> str:
    """Report whether a revision's source file is present on disk."""
    try:
        path = resolve_storage_path(storage_dir, storage_key)
    except PersistenceError:
        return "missing"
    return "present" if path.is_file() else "missing"


def read_revision_bytes(storage_dir: Path | str, storage_key: str) -> bytes:
    """Read one revision's exact stored source bytes."""
    path = resolve_storage_path(storage_dir, storage_key)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PersistenceError(
            f"source file for storage key {storage_key!r} is unavailable: {exc}"
        ) from exc


def _revision_dict(row: Any, *, status: str, storage_dir: Path | str) -> dict[str, Any]:
    (
        revision_id,
        document_id,
        revision_no,
        source_sha256,
        source_bytes,
        source_media_type,
        supersedes_revision_id,
        created_at,
        filename,
        content_chars,
        language,
        source_label,
        storage_key,
    ) = row
    return {
        "revision_id": str(revision_id),
        "document_id": str(document_id),
        "revision_no": int(revision_no),
        "status": status,
        "filename": filename,
        "source_media_type": source_media_type,
        "source_sha256": source_sha256,
        "source_bytes": int(source_bytes),
        "content_chars": int(content_chars),
        "language": language,
        "source_label": source_label,
        "storage_key": storage_key,
        "storage_status": storage_status(storage_dir, storage_key),
        "supersedes_revision_id": (
            None if supersedes_revision_id is None else str(supersedes_revision_id)
        ),
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


def source_locator(revision: dict[str, Any]) -> dict[str, Any]:
    """Return the provenance locator later chunks/evidence must cite.

    The locator pins the exact source bytes (revision identity + SHA-256 +
    byte length) plus the whole-file span, so future segmentation can
    address ``[source_start, source_end)`` sub-ranges of auditable bytes.
    """
    source_bytes = int(revision["source_bytes"])
    return {
        "document_id": revision["document_id"],
        "revision_id": revision["revision_id"],
        "revision_no": int(revision["revision_no"]),
        "source_sha256": revision["source_sha256"],
        "source_bytes": source_bytes,
        "content_chars": int(revision["content_chars"]),
        "storage_key": revision["storage_key"],
        "source_start": 0,
        "source_end": source_bytes,
    }


_REVISION_COLUMNS = (
    "r.revision_id, r.document_id, r.revision_no, r.source_sha256,"
    " r.source_bytes, r.source_media_type, r.supersedes_revision_id,"
    " r.created_at, r.filename, r.content_chars, r.language,"
    " r.source_label, r.storage_key"
)


def upload_revision(
    conn,
    *,
    storage_dir: Path | str,
    document_id: uuid.UUID,
    filename: str,
    data: bytes,
    language: str | None = None,
    source_label: str | None = None,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> dict[str, Any]:
    """Validate, store, and record one immutable document revision.

    Replacement-safe: a new upload for the same document appends a fresh
    revision row and leaves prior rows untouched. An identical byte upload
    is idempotent: the tip revision is returned with ``duplicate: True``
    (repairing its file when the file went missing) instead of appending a
    redundant row.
    """
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise PersistenceError("max_bytes must be a positive integer")
    if not isinstance(data, (bytes, bytearray)):
        raise PersistenceError("upload content must be bytes")
    data = bytes(data)
    if len(data) > max_bytes:
        raise PersistenceError(
            f"upload of {len(data)} bytes exceeds the {max_bytes}-byte limit"
        )
    name = sanitize_filename(filename)
    media_type = media_type_for_filename(name)
    text = decode_source(data)
    if language is not None and (not isinstance(language, str) or not language):
        raise PersistenceError("language must be a non-empty string when given")
    if source_label is not None and (
        not isinstance(source_label, str) or not source_label
    ):
        raise PersistenceError("source_label must be a non-empty string when given")

    sha256 = hashlib.sha256(data).hexdigest()
    revision_id = uuid.uuid4()
    storage_key = storage_key_for(document_id, revision_id, name)
    dest = resolve_storage_path(storage_dir, storage_key)
    # Stage bytes to a temp sibling first so a DB failure leaves no visible
    # partial file behind.
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".tmp-{revision_id.hex}"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        remove_path_safely(tmp)
        raise PersistenceError(f"failed to stage upload: {exc}") from exc

    try:
        with conn.transaction():
            doc = conn.execute(
                "SELECT title FROM chronicle.documents WHERE document_id = %s FOR UPDATE",
                (document_id,),
            ).fetchone()
            if doc is None:
                raise PersistenceError(f"unknown document {document_id}")
            tip = conn.execute(
                f"SELECT {_REVISION_COLUMNS} FROM chronicle.document_revisions r"
                " WHERE r.document_id = %s ORDER BY r.revision_no DESC LIMIT 1",
                (document_id,),
            ).fetchone()
            if tip is not None and tip[3] == sha256:
                # Idempotent duplicate: same bytes as the tip. Keep the
                # single tip row and make sure its file is (again) present.
                return _duplicate_result(tip, tmp, storage_dir)
            revision_no = 1 if tip is None else int(tip[2]) + 1
            supersedes = None if tip is None else tip[0]
            created = conn.execute(
                """
                INSERT INTO chronicle.document_revisions(
                    revision_id, document_id, revision_no,
                    source_sha256, source_bytes, source_media_type,
                    supersedes_revision_id,
                    filename, storage_key, content_chars, language, source_label
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING created_at
                """,
                (
                    revision_id,
                    document_id,
                    revision_no,
                    sha256,
                    len(data),
                    media_type,
                    supersedes,
                    name,
                    storage_key,
                    len(text),
                    language,
                    source_label,
                ),
            ).fetchone()
    except Exception:
        # The row never committed: remove the staged bytes.
        remove_path_safely(tmp)
        raise

    try:
        os.replace(tmp, dest)
    except OSError as exc:
        # The row committed but the file is not yet at its final path.
        # Remove the staged temp bytes so failed publishes cannot
        # accumulate orphan full-size copies; the row stays committed with
        # storage_status "missing", and the next identical upload repairs
        # the final file via the duplicate path.
        remove_path_safely(tmp)
        raise PersistenceError(
            f"revision {revision_id} recorded but source file publish failed: {exc}"
        ) from exc
    result = {
        "revision_id": str(revision_id),
        "document_id": str(document_id),
        "revision_no": revision_no,
        "status": "active",
        "filename": name,
        "source_media_type": media_type,
        "source_sha256": sha256,
        "source_bytes": len(data),
        "content_chars": len(text),
        "language": language,
        "source_label": source_label,
        "storage_key": storage_key,
        "storage_status": "present",
        "supersedes_revision_id": (
            None if supersedes is None else str(supersedes)
        ),
        "created_at": created[0].isoformat() if created else None,
        "duplicate": False,
    }
    return result


def _duplicate_result(tip, tmp: Path, storage_dir) -> dict[str, Any]:
    """Return the tip row for identical content, repairing its file.

    The staged temp bytes belong to the tip's storage key (the fresh
    revision UUID is discarded), so a retry after an interrupted first
    write restores the tip file instead of orphaning a second one.
    """
    tip_dest = resolve_storage_path(storage_dir, tip[12])
    tip_dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(tmp, tip_dest)
        file_status = "present"
    except OSError:
        remove_path_safely(tmp)
        file_status = storage_status(storage_dir, tip[12])
    result = _revision_dict(tip, status="active", storage_dir=storage_dir)
    result["storage_status"] = file_status
    result["duplicate"] = True
    return result


def get_document(conn, *, document_id: uuid.UUID, storage_dir: Path | str) -> dict[str, Any]:
    """Return one document with its active revision and revision count."""
    doc = conn.execute(
        "SELECT document_id, title, created_at FROM chronicle.documents WHERE document_id = %s",
        (document_id,),
    ).fetchone()
    if doc is None:
        raise PersistenceError(f"unknown document {document_id}")
    count = conn.execute(
        "SELECT count(*) FROM chronicle.document_revisions WHERE document_id = %s",
        (document_id,),
    ).fetchone()[0]
    tip = conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM chronicle.document_current_revisions r"
        " WHERE r.document_id = %s",
        (document_id,),
    ).fetchone()
    return {
        "document_id": str(doc[0]),
        "title": doc[1],
        "created_at": doc[2].isoformat() if doc[2] is not None else None,
        "revision_count": int(count),
        "active_revision": (
            None
            if tip is None
            else _revision_dict(tip, status="active", storage_dir=storage_dir)
        ),
    }


def list_documents(conn, *, storage_dir: Path | str) -> list[dict[str, Any]]:
    """List every document with revision counts (no file reads)."""
    rows = conn.execute(
        """
        SELECT d.document_id, d.title, d.created_at,
               count(r.revision_id),
               max(r.revision_no),
               (SELECT r2.source_sha256 FROM chronicle.document_revisions r2
                WHERE r2.document_id = d.document_id
                ORDER BY r2.revision_no DESC LIMIT 1)
        FROM chronicle.documents d
        LEFT JOIN chronicle.document_revisions r ON r.document_id = d.document_id
        GROUP BY d.document_id
        ORDER BY d.created_at, d.document_id
        """
    ).fetchall()
    return [
        {
            "document_id": str(row[0]),
            "title": row[1],
            "created_at": row[2].isoformat() if row[2] is not None else None,
            "revision_count": int(row[3]),
            "active_revision_no": None if row[4] is None else int(row[4]),
            "active_source_sha256": row[5],
        }
        for row in rows
    ]


def revision_history(
    conn, *, document_id: uuid.UUID, storage_dir: Path | str
) -> list[dict[str, Any]]:
    """Return every revision of a document, oldest first, with status."""
    exists = conn.execute(
        "SELECT 1 FROM chronicle.documents WHERE document_id = %s",
        (document_id,),
    ).fetchone()
    if exists is None:
        raise PersistenceError(f"unknown document {document_id}")
    rows = conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM chronicle.document_revisions r"
        " WHERE r.document_id = %s ORDER BY r.revision_no",
        (document_id,),
    ).fetchall()
    history = [
        _revision_dict(
            row,
            status="active" if index == len(rows) - 1 else "superseded",
            storage_dir=storage_dir,
        )
        for index, row in enumerate(rows)
    ]
    return history


def get_revision(
    conn, *, revision_id: uuid.UUID, storage_dir: Path | str
) -> dict[str, Any]:
    """Return one revision with its active/superseded status."""
    row = conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM chronicle.document_revisions r"
        " WHERE r.revision_id = %s",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown revision {revision_id}")
    tip_no = conn.execute(
        "SELECT max(revision_no) FROM chronicle.document_revisions WHERE document_id = %s",
        (row[1],),
    ).fetchone()[0]
    return _revision_dict(
        row,
        status="active" if int(row[2]) == int(tip_no) else "superseded",
        storage_dir=storage_dir,
    )
