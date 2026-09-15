"""Chronicle-owned background image candidates and saved reading bindings.

The image file and its use in a published history edition are deliberately
separate records.  Uploading an image creates an authenticated Studio
candidate only; it never creates a public resource.  A binding is created (or
changed) only by the explicit save/replace/disable operations below.

This module owns the application PostgreSQL tables from migration 0014 and a
Chronicle-owned filesystem directory.  It does not read or write Loom
Runtime/World/Timeline/Work/Binding authority, and it never calls an image
model.  All public reads must pass through ``read_public_*`` so a guessed
asset id cannot expose an unsaved or disabled candidate.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import time
import uuid
import warnings
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from common import PersistenceError, parse_uuid7


MAX_UPLOAD_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_UPLOAD_BYTES = MAX_UPLOAD_BYTES
MAX_IMAGE_PIXELS = 40_000_000
MAX_FILENAME_LENGTH = 255
MAX_SOURCE_LENGTH = 512
MAX_ERA_LENGTH = 128
MAX_PROMPT_LENGTH = 8_000
MAX_METADATA_BYTES = 32 * 1024

IMAGE_MEDIA_TYPES = {
    "PNG": ("image/png", "png", {".png"}),
    "JPEG": ("image/jpeg", "jpeg", {".jpg", ".jpeg"}),
    "WEBP": ("image/webp", "webp", {".webp"}),
}
MEDIA_TYPE_TO_FORMAT = {
    media: (format_name, extensions)
    for format_name, (media, _canonical, extensions) in IMAGE_MEDIA_TYPES.items()
}

_EDITION_RE = re.compile(r"^[0-9a-f]{64}$")
_PARAGRAPH_RE = re.compile(r"^hp_[0-9a-f]{24}$")


class BackgroundError(PersistenceError):
    """A typed image/binding validation failure for the HTTP adapter."""

    code = "background_error"
    status = 400

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        self.code = code or self.code
        self.details = details
        super().__init__(message)


class BackgroundNotFound(BackgroundError):
    code = "not_found"
    status = 404


class BackgroundConflict(BackgroundError):
    code = "conflict"
    status = 409


class BackgroundPayloadTooLarge(BackgroundError):
    code = "payload_too_large"
    status = 413


class BackgroundValidationError(BackgroundError):
    code = "invalid_background"
    status = 400


def new_uuid7() -> uuid.UUID:
    """Generate a server-owned UUIDv7.

    Python 3.14 supplies ``uuid.uuid7``.  The fallback keeps the module
    usable by older local tooling while preserving the RFC 9562 version and
    variant bits.
    """

    generator = getattr(uuid, "uuid7", None)
    if generator is not None:
        return generator()
    unix_ms = time.time_ns() // 1_000_000
    if unix_ms >= 1 << 48:
        raise BackgroundError("current time cannot be represented as UUIDv7", code="id_generation_failed")
    random_bits = secrets.randbits(74)
    value = (
        (unix_ms << 80)
        | (0x7 << 76)
        | ((random_bits >> 62) << 64)
        | (0b10 << 62)
        | (random_bits & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value)


def _uuid7(value: Any, description: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        parsed = value
    else:
        try:
            parsed = parse_uuid7(str(value), description)
        except PersistenceError as exc:
            raise BackgroundValidationError(str(exc), code="invalid_id") from exc
    if parsed.version != 7:
        raise BackgroundValidationError(f"{description} must be UUIDv7", code="invalid_id")
    return parsed


def max_upload_bytes(env: Mapping[str, str] | None = None) -> int:
    """Return the bounded Studio image upload limit.

    Configuration may lower the product limit for a deployment, but can never
    raise the first-version 8 MiB ceiling.
    """

    source = env if env is not None else os.environ
    raw = str(source.get("CHRONICLE_BACKGROUND_MAX_UPLOAD_BYTES") or "").strip()
    if not raw:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise BackgroundValidationError(
            "CHRONICLE_BACKGROUND_MAX_UPLOAD_BYTES must be a positive integer",
            code="invalid_upload_limit",
        ) from exc
    if value < 1:
        raise BackgroundValidationError(
            "CHRONICLE_BACKGROUND_MAX_UPLOAD_BYTES must be a positive integer",
            code="invalid_upload_limit",
        )
    return min(value, MAX_UPLOAD_BYTES)


def storage_dir_from_env(
    env: Mapping[str, str] | None = None,
    *,
    source_dir: Path | str | None = None,
) -> Path:
    """Return the private, Chronicle-owned background directory."""

    values = env if env is not None else os.environ
    raw = str(values.get("CHRONICLE_BACKGROUND_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    if source_dir is not None:
        return Path(source_dir).expanduser() / "background-assets"
    source = str(values.get("CHRONICLE_SOURCE_DIR") or "").strip()
    if source:
        return Path(source).expanduser() / "background-assets"
    return Path.cwd() / "chronicle-sources" / "background-assets"


def _safe_filename(value: Any, *, default: str | None = None) -> str:
    if value is None and default is not None:
        value = default
    if not isinstance(value, str):
        raise BackgroundValidationError("filename must be a string", code="invalid_filename")
    name = value.strip()
    if not name or len(name) > MAX_FILENAME_LENGTH:
        raise BackgroundValidationError("filename must be 1-255 characters", code="invalid_filename")
    if (
        "/" in name
        or "\\" in name
        or name in {".", ".."}
        or name.startswith(".")
        or ".." in name
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in name)
    ):
        raise BackgroundValidationError("filename must be a plain image basename", code="invalid_filename")
    return name


def _canonical_media_type(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BackgroundValidationError("Content-Type must be a string", code="invalid_media_type")
    media = value.split(";", 1)[0].strip().lower()
    if not media:
        return None
    if media not in MEDIA_TYPE_TO_FORMAT:
        raise BackgroundValidationError(
            "background upload must use image/png, image/jpeg, or image/webp",
            code="unsupported_media_type",
        )
    return media


def validate_image(
    data: bytes,
    *,
    content_type: str | None = None,
    filename: str | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Decode and validate a PNG/JPEG/WebP upload.

    MIME headers and names are hints only.  Pillow verifies the actual image
    format and fully decodes the image before the bytes are accepted.  This
    rejects SVG/HTML, fake MIME types, truncated images and decompression
    bombs instead of trusting request metadata.
    """

    if not isinstance(data, (bytes, bytearray)):
        raise BackgroundValidationError("image content must be bytes", code="invalid_image")
    raw = bytes(data)
    limit = MAX_UPLOAD_BYTES if max_bytes is None else min(int(max_bytes), MAX_UPLOAD_BYTES)
    if len(raw) == 0:
        raise BackgroundValidationError("image content must not be empty", code="invalid_image")
    if len(raw) > limit:
        raise BackgroundPayloadTooLarge(
            f"background upload of {len(raw)} bytes exceeds the {limit}-byte limit"
        )
    declared = _canonical_media_type(content_type)
    supplied_name = _safe_filename(filename) if filename is not None else None

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise BackgroundError(
            "Pillow is required for image validation",
            code="image_decoder_unavailable",
            details=str(exc),
        ) from exc

    try:
        # ``verify`` checks the encoded stream without retaining a lazy image;
        # reopening and ``load`` then proves the actual pixels can be decoded.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with Image.open(BytesIO(raw)) as image:
                detected = str(image.format or "").upper()
                width, height = image.size
                if detected not in IMAGE_MEDIA_TYPES:
                    raise BackgroundValidationError(
                        "only PNG, JPEG, and WebP images are accepted",
                        code="unsupported_image_format",
                    )
                if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
                    raise BackgroundValidationError("image dimensions are invalid", code="invalid_dimensions")
                if width * height > MAX_IMAGE_PIXELS:
                    raise BackgroundValidationError(
                        f"image has {width * height} pixels; the limit is {MAX_IMAGE_PIXELS}",
                        code="pixel_limit_exceeded",
                    )
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                image.load()
                if image.size != (width, height):
                    raise BackgroundValidationError(
                        "image dimensions changed during decode", code="invalid_dimensions"
                    )
    except BackgroundError:
        raise
    except Exception as exc:
        # Pillow uses several decoder-specific OSError subclasses.  The broad
        # final guard intentionally turns every decode failure into a typed
        # client error and never returns decoder internals to a reader.
        raise BackgroundValidationError("image bytes could not be decoded", code="decode_failed") from exc

    media_type, canonical_format, extensions = IMAGE_MEDIA_TYPES[detected]
    if declared is not None and declared != media_type:
        raise BackgroundValidationError(
            f"declared media type {declared!r} does not match the decoded image",
            code="media_type_mismatch",
        )
    if supplied_name is not None:
        suffix = Path(supplied_name).suffix.lower()
        if suffix not in extensions:
            raise BackgroundValidationError(
                f"filename extension does not match the decoded {canonical_format} image",
                code="filename_format_mismatch",
            )
    return {
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "media_type": media_type,
        "image_format": canonical_format,
        "width": width,
        "height": height,
        "byte_size": len(raw),
        "filename": supplied_name or f"upload.{canonical_format if canonical_format != 'jpeg' else 'jpg'}",
    }


def resolve_storage_path(storage_dir: Path | str, storage_key: str) -> Path:
    """Resolve only a server-generated relative key inside the asset volume."""

    if not isinstance(storage_key, str) or not storage_key:
        raise BackgroundValidationError("storage key is empty", code="invalid_storage_key")
    if storage_key.startswith("/") or "\\" in storage_key or any(
        part in {"", ".", ".."} for part in storage_key.split("/")
    ):
        raise BackgroundValidationError("storage key is not a safe relative key", code="invalid_storage_key")
    base = Path(storage_dir).expanduser().resolve()
    candidate = (base / Path(*storage_key.split("/"))).resolve()
    if candidate != base and base not in candidate.parents:
        raise BackgroundValidationError("storage key escapes asset storage", code="invalid_storage_key")
    return candidate


def _write_atomic(storage_dir: Path | str, storage_key: str, data: bytes) -> Path:
    destination = resolve_storage_path(storage_dir, storage_key)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackgroundError("failed to prepare background storage", code="storage_write_failed") from exc
    temporary = destination.parent / f".tmp-{uuid.uuid4().hex}"
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # The file rename is still atomic on filesystems that do not allow
            # directory fsync; the database/public visibility fences remain.
            pass
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise BackgroundError("failed to store background image", code="storage_write_failed") from exc
    return destination


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _copy_json(value: Any) -> Any:
    import copy

    return copy.deepcopy(value)


def _text(value: Any, name: str, *, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BackgroundValidationError(f"{name} must be a non-empty string", code="invalid_metadata")
    result = value.strip()
    if len(result) > max_length:
        raise BackgroundValidationError(f"{name} exceeds its length limit", code="invalid_metadata")
    return result


def _metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BackgroundValidationError("metadata must be a JSON object", code="invalid_metadata")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BackgroundValidationError(
            "metadata must contain only JSON-compatible values", code="invalid_metadata"
        ) from exc
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise BackgroundValidationError("metadata exceeds its size limit", code="invalid_metadata")
    return _copy_json(value)

def _datetime(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (None if value is None else str(value))


def _asset_row(conn, asset_id: uuid.UUID, version_id: uuid.UUID | None = None):
    where = "v.asset_id = %s"
    params: list[Any] = [asset_id]
    if version_id is not None:
        where += " AND v.asset_version_id = %s"
        params.append(version_id)
    return conn.execute(
        """
        SELECT a.asset_id, a.source, a.era, a.prompt, a.metadata, a.created_at,
               v.asset_version_id, v.version_no, v.content_sha256, v.media_type,
               v.image_format, v.original_filename, v.byte_size, v.width, v.height,
               v.storage_key, v.created_at
        FROM chronicle.background_assets a
        JOIN chronicle.background_asset_versions v ON v.asset_id = a.asset_id
        WHERE """ + where + " ORDER BY v.version_no DESC LIMIT 1",
        tuple(params),
    ).fetchone()


def _asset_output(row: Any, *, storage_dir: Path | str, include_internal: bool = False) -> dict[str, Any]:
    if row is None:
        raise BackgroundNotFound("background asset was not found")
    (
        asset_id, source, era, prompt, metadata, created_at,
        version_id, version_no, content_sha, media_type, image_format,
        filename, byte_size, width, height, storage_key, version_created,
    ) = row
    try:
        file_path = resolve_storage_path(storage_dir, str(storage_key))
        present = file_path.is_file()
    except BackgroundError:
        present = False
    result: dict[str, Any] = {
        "asset_id": str(asset_id),
        "asset_version_id": str(version_id),
        "version": int(version_no),
        "source": source,
        "era": era,
        "prompt": prompt,
        "metadata": _copy_json(metadata) if isinstance(metadata, dict) else {},
        "content_sha256": str(content_sha),
        "media_type": media_type,
        "format": image_format,
        "filename": filename,
        "byte_size": int(byte_size),
        "width": int(width),
        "height": int(height),
        "storage_status": "present" if present else "missing",
        "preview_href": f"/api/v1/studio/background-assets/{asset_id}/preview",
        "created_at": _datetime(created_at),
        "version_created_at": _datetime(version_created),
        "candidate": True,
    }
    if include_internal:
        result["storage_key"] = str(storage_key)
    return result


def create_asset(
    conn,
    *,
    data: bytes,
    storage_dir: Path | str,
    filename: str | None = None,
    content_type: str | None = None,
    source: str | None = None,
    era: str | None = None,
    prompt: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Validate, atomically store and register one candidate image."""

    safe_source = _text(source, "source", max_length=MAX_SOURCE_LENGTH)
    safe_era = _text(era, "era", max_length=MAX_ERA_LENGTH)
    safe_prompt = _text(prompt, "prompt", max_length=MAX_PROMPT_LENGTH)
    safe_metadata = _metadata(metadata)
    info = validate_image(
        data,
        content_type=content_type,
        filename=filename,
        max_bytes=max_bytes,
    )
    safe_filename = _safe_filename(filename, default=info["filename"])
    asset_id = new_uuid7()
    version_id = new_uuid7()
    extension = ".jpg" if info["image_format"] == "jpeg" else f".{info['image_format']}"
    storage_key = f"assets/{asset_id}/{version_id}{extension}"
    destination = _write_atomic(storage_dir, storage_key, bytes(data))
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO chronicle.background_assets(asset_id, source, era, prompt, metadata) "
                "VALUES (%s, %s, %s, %s, %s)",
                (asset_id, safe_source, safe_era, safe_prompt, Jsonb(safe_metadata)),
            )
            conn.execute(
                """
                INSERT INTO chronicle.background_asset_versions(
                    asset_version_id, asset_id, version_no, content_sha256,
                    media_type, image_format, original_filename, byte_size,
                    width, height, storage_key
                ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    asset_id,
                    info["content_sha256"],
                    info["media_type"],
                    info["image_format"],
                    safe_filename,
                    info["byte_size"],
                    info["width"],
                    info["height"],
                    storage_key,
                ),
            )
    except Exception:
        # A rolled-back registration must not leave a candidate file that a
        # future implementation could accidentally enumerate as public.
        _remove_file(destination)
        raise
    row = _asset_row(conn, asset_id, version_id)
    return _asset_output(row, storage_dir=storage_dir)


def create_asset_version(
    conn,
    asset_id: uuid.UUID | str,
    *,
    data: bytes,
    storage_dir: Path | str,
    filename: str | None = None,
    content_type: str | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Append one immutable encoded version to an existing candidate asset."""

    parsed_asset = _uuid7(asset_id, "asset_id")
    info = validate_image(
        data,
        content_type=content_type,
        filename=filename,
        max_bytes=max_bytes,
    )
    safe_filename = _safe_filename(filename, default=info["filename"])
    version_id = new_uuid7()
    extension = ".jpg" if info["image_format"] == "jpeg" else f".{info['image_format']}"
    storage_key = f"assets/{parsed_asset}/{version_id}{extension}"
    destination = _write_atomic(storage_dir, storage_key, bytes(data))
    try:
        with conn.transaction():
            parent = conn.execute(
                "SELECT asset_id FROM chronicle.background_assets WHERE asset_id = %s FOR UPDATE",
                (parsed_asset,),
            ).fetchone()
            if parent is None:
                raise BackgroundNotFound("background asset was not found")
            version_no = conn.execute(
                "SELECT coalesce(max(version_no), 0) + 1 "
                "FROM chronicle.background_asset_versions WHERE asset_id = %s",
                (parsed_asset,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO chronicle.background_asset_versions(
                    asset_version_id, asset_id, version_no, content_sha256,
                    media_type, image_format, original_filename, byte_size,
                    width, height, storage_key
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    parsed_asset,
                    version_no,
                    info["content_sha256"],
                    info["media_type"],
                    info["image_format"],
                    safe_filename,
                    info["byte_size"],
                    info["width"],
                    info["height"],
                    storage_key,
                ),
            )
    except Exception:
        _remove_file(destination)
        raise
    row = _asset_row(conn, parsed_asset, version_id)
    return _asset_output(row, storage_dir=storage_dir)


def get_asset(
    conn,
    asset_id: uuid.UUID | str,
    *,
    storage_dir: Path | str,
    asset_version_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    parsed_asset = _uuid7(asset_id, "asset_id")
    parsed_version = _uuid7(asset_version_id, "asset_version_id") if asset_version_id is not None else None
    row = _asset_row(conn, parsed_asset, parsed_version)
    return _asset_output(row, storage_dir=storage_dir)


def list_assets(
    conn,
    *,
    storage_dir: Path | str,
    source: str | None = None,
    era: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise BackgroundValidationError("asset limit must be between 1 and 100", code="invalid_page")
    if type(offset) is not int or offset < 0:
        raise BackgroundValidationError("asset offset must be nonnegative", code="invalid_page")
    clauses: list[str] = []
    params: list[Any] = []
    if source is not None:
        clauses.append("a.source = %s")
        params.append(_text(source, "source", max_length=MAX_SOURCE_LENGTH))
    if era is not None:
        clauses.append("a.era = %s")
        params.append(_text(era, "era", max_length=MAX_ERA_LENGTH))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        """
        SELECT a.asset_id, a.source, a.era, a.prompt, a.metadata, a.created_at,
               v.asset_version_id, v.version_no, v.content_sha256, v.media_type,
               v.image_format, v.original_filename, v.byte_size, v.width, v.height,
               v.storage_key, v.created_at
        FROM chronicle.background_assets a
        JOIN LATERAL (
            SELECT * FROM chronicle.background_asset_versions latest
            WHERE latest.asset_id = a.asset_id
            ORDER BY latest.version_no DESC LIMIT 1
        ) v ON true
        """ + where + " ORDER BY a.created_at DESC, a.asset_id DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    ).fetchall()
    assets = [_asset_output(row, storage_dir=storage_dir) for row in rows]
    return {
        "schema": "chronicle.background-asset-list",
        "version": "0.1",
        "assets": assets,
        "offset": offset,
        "has_more": len(assets) == limit,
    }


def _asset_version_row(conn, asset_version_id: uuid.UUID):
    row = conn.execute(
        """
        SELECT a.asset_id, a.source, a.era, a.prompt, a.metadata,
               v.asset_version_id, v.version_no, v.content_sha256,
               v.media_type, v.image_format, v.original_filename, v.byte_size,
               v.width, v.height, v.storage_key
        FROM chronicle.background_asset_versions v
        JOIN chronicle.background_assets a ON a.asset_id = v.asset_id
        WHERE v.asset_version_id = %s
        """,
        (asset_version_id,),
    ).fetchone()
    if row is None:
        raise BackgroundNotFound("background asset version was not found")
    return row


def _verify_asset_file(conn, storage_dir: Path | str, asset_version_id: uuid.UUID) -> tuple[Any, bytes]:
    row = _asset_version_row(conn, asset_version_id)
    storage_key = str(row[14])
    try:
        path = resolve_storage_path(storage_dir, storage_key)
        raw = path.read_bytes()
    except (OSError, BackgroundError) as exc:
        raise BackgroundValidationError(
            "background asset file is missing or unavailable",
            code="asset_file_missing",
        ) from exc
    if len(raw) != int(row[11]) or hashlib.sha256(raw).hexdigest() != str(row[7]):
        raise BackgroundValidationError(
            "background asset file failed its stored integrity check",
            code="asset_file_corrupt",
        )
    validate_image(
        raw,
        content_type=str(row[8]),
        filename=str(row[10]),
        max_bytes=MAX_UPLOAD_BYTES,
    )
    return row, raw


def _edition_version(value: Any) -> str:
    if not isinstance(value, str) or not _EDITION_RE.fullmatch(value):
        raise BackgroundValidationError("edition_version must be a published SHA-256", code="invalid_edition")
    return value


def _paragraph(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _PARAGRAPH_RE.fullmatch(value):
        raise BackgroundValidationError(f"{name} must be a historical paragraph id", code="invalid_paragraph")
    return value


def _paragraph_range(conn, edition_version: str, start_id: str, end_id: str) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT paragraph_id, ordinal FROM chronicle.history_edition_paragraph_index "
        "WHERE edition_version = %s AND paragraph_id IN (%s, %s)",
        (edition_version, start_id, end_id),
    ).fetchall()
    ordinals = {str(row[0]): int(row[1]) for row in rows}
    if start_id not in ordinals or end_id not in ordinals:
        raise BackgroundValidationError(
            "start and end paragraphs must belong to the selected published edition",
            code="unknown_paragraph",
        )
    start, end = ordinals[start_id], ordinals[end_id]
    if start > end:
        raise BackgroundValidationError(
            "start paragraph must not follow end paragraph",
            code="invalid_paragraph_range",
        )
    return start, end


def normalize_display(value: Any) -> dict[str, Any]:
    """Validate the first-version, JSON-only rendering configuration."""

    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise BackgroundValidationError("display must be a JSON object", code="invalid_display")
    allowed = {"opacity", "position", "scale", "mask"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BackgroundValidationError(
            f"unknown display field(s): {', '.join(str(item) for item in unknown)}",
            code="invalid_display",
        )

    def number(raw: Any, name: str, low: float, high: float) -> float:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise BackgroundValidationError(f"display {name} must be finite", code="invalid_display")
        result = float(raw)
        if result < low or result > high:
            raise BackgroundValidationError(
                f"display {name} must be between {low} and {high}",
                code="invalid_display",
            )
        return result

    opacity = number(value.get("opacity", 0.35), "opacity", 0.0, 1.0)
    scale = number(value.get("scale", 1.0), "scale", 0.1, 4.0)
    position = value.get("position", {"x": 0.5, "y": 0.5})
    if not isinstance(position, dict) or set(position) != {"x", "y"}:
        raise BackgroundValidationError(
            "display position must contain only x and y",
            code="invalid_display",
        )
    normalized_position = {
        "x": number(position["x"], "position.x", 0.0, 1.0),
        "y": number(position["y"], "position.y", 0.0, 1.0),
    }
    mask = value.get("mask")
    normalized_mask: dict[str, Any] | None
    if mask is None:
        normalized_mask = None
    elif isinstance(mask, dict):
        allowed_mask = {"top", "right", "bottom", "left", "shape"}
        unknown_mask = sorted(set(mask) - allowed_mask)
        if unknown_mask:
            raise BackgroundValidationError("unknown display mask field", code="invalid_display")
        normalized_mask = {}
        for key in ("top", "right", "bottom", "left"):
            if key in mask:
                normalized_mask[key] = number(mask[key], f"mask.{key}", 0.0, 1.0)
        if "shape" in mask:
            if mask["shape"] not in {"rect", "gradient"}:
                raise BackgroundValidationError("display mask shape is invalid", code="invalid_display")
            normalized_mask["shape"] = mask["shape"]
    else:
        raise BackgroundValidationError("display mask must be an object or null", code="invalid_display")
    return {
        "opacity": opacity,
        "position": normalized_position,
        "scale": scale,
        "mask": normalized_mask,
    }


def _binding_row(conn, binding_id: uuid.UUID, *, lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    return conn.execute(
        """
        SELECT b.binding_id, b.edition_version, b.start_paragraph_id,
               b.end_paragraph_id, b.start_ordinal, b.end_ordinal,
               b.asset_id, b.asset_version_id, b.display, b.status,
               b.revision, b.etag, b.saved_by, b.created_at, b.updated_at,
               b.disabled_at, a.source, a.era, a.prompt, a.metadata,
               v.version_no, v.content_sha256, v.media_type, v.image_format,
               v.original_filename, v.byte_size, v.width, v.height, v.storage_key
        FROM chronicle.background_bindings b
        JOIN chronicle.background_assets a ON a.asset_id = b.asset_id
        JOIN chronicle.background_asset_versions v ON v.asset_version_id = b.asset_version_id
        WHERE b.binding_id = %s""" + suffix,
        (binding_id,),
    ).fetchone()


def _binding_output(row: Any, *, include_audit: bool = False) -> dict[str, Any]:
    if row is None:
        raise BackgroundNotFound("background binding was not found")
    (
        binding_id, edition_version, start_id, end_id, start_ordinal, end_ordinal,
        asset_id, version_id, display, status, revision, etag, saved_by,
        created_at, updated_at, disabled_at, source, era, prompt, metadata,
        version_no, content_sha, media_type, image_format, filename, byte_size,
        width, height, storage_key,
    ) = row
    result: dict[str, Any] = {
        "binding_id": str(binding_id),
        "edition_version": str(edition_version),
        "start_paragraph_id": str(start_id),
        "end_paragraph_id": str(end_id),
        "start_ordinal": int(start_ordinal),
        "end_ordinal": int(end_ordinal),
        "asset_id": str(asset_id),
        "asset_version_id": str(version_id),
        "asset_version": int(version_no),
        "display": _copy_json(display) if isinstance(display, dict) else {},
        "status": status,
        "active": status == "active",
        "revision": int(revision),
        "etag": str(etag),
        "saved_by": saved_by,
        "created_at": _datetime(created_at),
        "updated_at": _datetime(updated_at),
        "disabled_at": _datetime(disabled_at),
        "asset": {
            "asset_id": str(asset_id),
            "asset_version_id": str(version_id),
            "version": int(version_no),
            "source": source,
            "era": era,
            "prompt": prompt,
            "metadata": _copy_json(metadata) if isinstance(metadata, dict) else {},
            "content_sha256": str(content_sha),
            "media_type": media_type,
            "format": image_format,
            "filename": filename,
            "byte_size": int(byte_size),
            "width": int(width),
            "height": int(height),
            "resource_href": f"/api/v1/public/background-assets/{asset_id}",
        },
    }
    if include_audit:
        result["audit_href"] = f"/api/v1/studio/background-bindings/{binding_id}/audit"
    return result


def _actor(value: Any) -> str:
    if value is None:
        return "studio-admin"
    result = _text(value, "actor", max_length=255)
    assert result is not None
    return result


def _expected_revision(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise BackgroundValidationError("expected_revision must be an integer", code="invalid_revision")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BackgroundValidationError("expected_revision must be an integer", code="invalid_revision") from exc
    if parsed < 1:
        raise BackgroundValidationError("expected_revision must be positive", code="invalid_revision")
    return parsed


def _check_precondition(row: Any, *, expected_revision: Any = None, expected_etag: str | None = None) -> None:
    revision = _expected_revision(expected_revision)
    if revision is not None and int(row[10]) != revision:
        raise BackgroundConflict("background binding revision has changed", code="revision_conflict")
    if expected_etag is not None:
        if not isinstance(expected_etag, str) or expected_etag.strip('"') != str(row[11]).strip('"'):
            raise BackgroundConflict("background binding etag has changed", code="etag_conflict")


def _lock_edition(conn, edition_version: str) -> None:
    row = conn.execute(
        "SELECT edition_version FROM chronicle.history_editions WHERE edition_version = %s FOR SHARE",
        (edition_version,),
    ).fetchone()
    if row is None:
        raise BackgroundValidationError(
            "selected history edition is not published",
            code="unknown_edition",
        )
    # Serialise overlap checks for one immutable edition.  The trigger repeats
    # the lock for writers that bypass this module.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (edition_version,))


def _overlap_exists(
    conn,
    *,
    edition_version: str,
    start_ordinal: int,
    end_ordinal: int,
    exclude_binding_id: uuid.UUID | None = None,
) -> bool:
    clauses = [
        "edition_version = %s",
        "status = 'active'",
        "start_ordinal <= %s",
        "end_ordinal >= %s",
    ]
    params: list[Any] = [edition_version, end_ordinal, start_ordinal]
    if exclude_binding_id is not None:
        clauses.append("binding_id <> %s")
        params.append(exclude_binding_id)
    row = conn.execute(
        "SELECT 1 FROM chronicle.background_bindings WHERE " + " AND ".join(clauses) + " LIMIT 1",
        tuple(params),
    ).fetchone()
    return row is not None


def _insert_audit(
    conn,
    *,
    binding_id: uuid.UUID,
    action: str,
    revision: int,
    actor: str,
    previous_asset_version_id: uuid.UUID | None,
    asset_version_id: uuid.UUID,
    previous_start_paragraph_id: str | None,
    previous_end_paragraph_id: str | None,
    start_paragraph_id: str,
    end_paragraph_id: str,
    display: Mapping[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO chronicle.background_binding_audit(
            audit_id, binding_id, action, revision, actor,
            previous_asset_version_id, asset_version_id,
            previous_start_paragraph_id, previous_end_paragraph_id,
            start_paragraph_id, end_paragraph_id, display
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            new_uuid7(), binding_id, action, revision, actor,
            previous_asset_version_id, asset_version_id,
            previous_start_paragraph_id, previous_end_paragraph_id,
            start_paragraph_id, end_paragraph_id, Jsonb(_copy_json(dict(display))),
        ),
    )


def create_binding(
    conn,
    *,
    edition_version: str,
    start_paragraph_id: str,
    end_paragraph_id: str,
    asset_id: uuid.UUID | str,
    asset_version_id: uuid.UUID | str,
    display: Mapping[str, Any] | None = None,
    actor: str | None = None,
    storage_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Atomically validate and save one active, non-overlapping binding."""

    configured_storage = storage_dir if storage_dir is not None else storage_dir_for_connection(conn)
    return _create_binding(
        conn,
        storage_dir=configured_storage,
        edition_version=edition_version,
        start_paragraph_id=start_paragraph_id,
        end_paragraph_id=end_paragraph_id,
        asset_id=asset_id,
        asset_version_id=asset_version_id,
        display=display,
        actor=actor,
    )


def storage_dir_for_connection(conn) -> Path:
    """Compatibility default for direct store callers.

    HTTP callers pass their configured directory through the explicit
    ``storage_dir`` variants below.  The small helper exists only so the
    public function signatures stay useful to existing direct integrations.
    """

    del conn
    return storage_dir_from_env()


def create_binding_with_storage(
    conn,
    *,
    storage_dir: Path | str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Storage-explicit entry point used by the HTTP adapter."""

    # Keep the implementation above as the compatibility API, while ensuring
    # all real callers use the configured volume and never the process cwd.
    return _create_binding(conn, storage_dir=storage_dir, **kwargs)


def _create_binding(conn, *, storage_dir: Path | str, **kwargs: Any) -> dict[str, Any]:
    edition_version = _edition_version(kwargs["edition_version"])
    start_id = _paragraph(kwargs["start_paragraph_id"], "start_paragraph_id")
    end_id = _paragraph(kwargs["end_paragraph_id"], "end_paragraph_id")
    parsed_asset = _uuid7(kwargs["asset_id"], "asset_id")
    parsed_version = _uuid7(kwargs["asset_version_id"], "asset_version_id")
    normalized_display = normalize_display(kwargs.get("display"))
    saved_by = _actor(kwargs.get("actor"))
    binding_id = new_uuid7()
    with conn.transaction():
        _lock_edition(conn, edition_version)
        version_row, _raw = _verify_asset_file(conn, storage_dir, parsed_version)
        if version_row[0] != parsed_asset:
            raise BackgroundValidationError("asset_id does not match asset_version_id", code="asset_version_mismatch")
        start_ordinal, end_ordinal = _paragraph_range(conn, edition_version, start_id, end_id)
        if _overlap_exists(
            conn,
            edition_version=edition_version,
            start_ordinal=start_ordinal,
            end_ordinal=end_ordinal,
        ):
            raise BackgroundConflict(
                "the selected paragraph range overlaps an active background binding",
                code="overlap_conflict",
            )
        etag = f'"{binding_id}-1"'
        conn.execute(
            """
            INSERT INTO chronicle.background_bindings(
                binding_id, edition_version, start_paragraph_id, end_paragraph_id,
                start_ordinal, end_ordinal, asset_id, asset_version_id, display,
                status, revision, etag, saved_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', 1, %s, %s)
            """,
            (
                binding_id, edition_version, start_id, end_id, start_ordinal, end_ordinal,
                parsed_asset, parsed_version, Jsonb(normalized_display), etag, saved_by,
            ),
        )
        _insert_audit(
            conn, binding_id=binding_id, action="created", revision=1,
            actor=saved_by, previous_asset_version_id=None,
            asset_version_id=parsed_version, previous_start_paragraph_id=None,
            previous_end_paragraph_id=None, start_paragraph_id=start_id,
            end_paragraph_id=end_id, display=normalized_display,
        )
    return _binding_output(_binding_row(conn, binding_id), include_audit=True)


def get_binding(conn, binding_id: uuid.UUID | str) -> dict[str, Any]:
    return _binding_output(_binding_row(conn, _uuid7(binding_id, "binding_id")), include_audit=True)


def list_bindings(
    conn,
    *,
    storage_dir: Path | str | None = None,
    edition_version: str | None = None,
    paragraph_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise BackgroundValidationError("binding limit must be between 1 and 100", code="invalid_page")
    if type(offset) is not int or offset < 0:
        raise BackgroundValidationError("binding offset must be nonnegative", code="invalid_page")
    clauses: list[str] = []
    params: list[Any] = []
    if edition_version is not None:
        clauses.append("b.edition_version = %s")
        params.append(_edition_version(edition_version))
    if paragraph_id is not None:
        paragraph = _paragraph(paragraph_id, "paragraph_id")
        clauses.append("b.start_ordinal <= p.ordinal AND b.end_ordinal >= p.ordinal")
        params.append(paragraph)
    if status is not None:
        if status not in {"active", "disabled", "all"}:
            raise BackgroundValidationError("binding status is invalid", code="invalid_status")
        if status != "all":
            clauses.append("b.status = %s")
            params.append(status)
    join = ""
    if paragraph_id is not None:
        join = (
            " JOIN chronicle.history_edition_paragraph_index p"
            " ON p.edition_version = b.edition_version AND p.paragraph_id = %s"
        )
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        """
        SELECT b.binding_id, b.edition_version, b.start_paragraph_id,
               b.end_paragraph_id, b.start_ordinal, b.end_ordinal,
               b.asset_id, b.asset_version_id, b.display, b.status,
               b.revision, b.etag, b.saved_by, b.created_at, b.updated_at,
               b.disabled_at, a.source, a.era, a.prompt, a.metadata,
               v.version_no, v.content_sha256, v.media_type, v.image_format,
               v.original_filename, v.byte_size, v.width, v.height, v.storage_key
        FROM chronicle.background_bindings b
        JOIN chronicle.background_assets a ON a.asset_id = b.asset_id
        JOIN chronicle.background_asset_versions v ON v.asset_version_id = b.asset_version_id
        """ + join + where + " ORDER BY b.created_at DESC, b.binding_id DESC LIMIT %s OFFSET %s",
        tuple(([paragraph_id] if paragraph_id is not None else []) + params + [limit, offset]),
    ).fetchall()
    items = [_binding_output(row) for row in rows]
    return {
        "schema": "chronicle.background-binding-list",
        "version": "0.1",
        "bindings": items,
        "offset": offset,
        "has_more": len(items) == limit,
    }


def replace_binding(
    conn,
    binding_id: uuid.UUID | str,
    *,
    storage_dir: Path | str,
    asset_id: uuid.UUID | str,
    asset_version_id: uuid.UUID | str,
    display: Mapping[str, Any] | None = None,
    start_paragraph_id: str | None = None,
    end_paragraph_id: str | None = None,
    actor: str | None = None,
    expected_revision: Any = None,
    expected_etag: str | None = None,
) -> dict[str, Any]:
    """Explicitly replace one binding, preserving its audit history."""

    parsed_binding = _uuid7(binding_id, "binding_id")
    parsed_asset = _uuid7(asset_id, "asset_id")
    parsed_version = _uuid7(asset_version_id, "asset_version_id")
    saved_by = _actor(actor)
    with conn.transaction():
        current = _binding_row(conn, parsed_binding, lock=True)
        if current is None:
            raise BackgroundNotFound("background binding was not found")
        _check_precondition(current, expected_revision=expected_revision, expected_etag=expected_etag)
        edition = str(current[1])
        start_id = (
            _paragraph(start_paragraph_id, "start_paragraph_id")
            if start_paragraph_id is not None
            else str(current[2])
        )
        end_id = _paragraph(end_paragraph_id, "end_paragraph_id") if end_paragraph_id is not None else str(current[3])
        normalized_display = normalize_display(display if display is not None else current[8])
        _lock_edition(conn, edition)
        version_row, _raw = _verify_asset_file(conn, storage_dir, parsed_version)
        if version_row[0] != parsed_asset:
            raise BackgroundValidationError("asset_id does not match asset_version_id", code="asset_version_mismatch")
        start_ordinal, end_ordinal = _paragraph_range(conn, edition, start_id, end_id)
        if _overlap_exists(
            conn,
            edition_version=edition,
            start_ordinal=start_ordinal,
            end_ordinal=end_ordinal,
            exclude_binding_id=parsed_binding,
        ):
            raise BackgroundConflict(
                "the replacement range overlaps an active background binding",
                code="overlap_conflict",
            )
        revision = int(current[10]) + 1
        etag = f'"{parsed_binding}-{revision}"'
        conn.execute(
            """
            UPDATE chronicle.background_bindings
            SET start_paragraph_id = %s, end_paragraph_id = %s,
                start_ordinal = %s, end_ordinal = %s, asset_id = %s,
                asset_version_id = %s, display = %s, status = 'active',
                revision = %s, etag = %s, saved_by = %s,
                updated_at = clock_timestamp(), disabled_at = NULL
            WHERE binding_id = %s
            """,
            (
                start_id, end_id, start_ordinal, end_ordinal, parsed_asset,
                parsed_version, Jsonb(normalized_display), revision, etag,
                saved_by, parsed_binding,
            ),
        )
        _insert_audit(
            conn, binding_id=parsed_binding, action="replaced", revision=revision,
            actor=saved_by, previous_asset_version_id=current[7],
            asset_version_id=parsed_version, previous_start_paragraph_id=current[2],
            previous_end_paragraph_id=current[3], start_paragraph_id=start_id,
            end_paragraph_id=end_id, display=normalized_display,
        )
    return _binding_output(_binding_row(conn, parsed_binding), include_audit=True)


def disable_binding(
    conn,
    binding_id: uuid.UUID | str,
    *,
    actor: str | None = None,
    expected_revision: Any = None,
    expected_etag: str | None = None,
) -> dict[str, Any]:
    parsed_binding = _uuid7(binding_id, "binding_id")
    saved_by = _actor(actor)
    with conn.transaction():
        current = _binding_row(conn, parsed_binding, lock=True)
        if current is None:
            raise BackgroundNotFound("background binding was not found")
        _check_precondition(current, expected_revision=expected_revision, expected_etag=expected_etag)
        if current[9] == "disabled":
            return _binding_output(current, include_audit=True)
        revision = int(current[10]) + 1
        etag = f'"{parsed_binding}-{revision}"'
        conn.execute(
            "UPDATE chronicle.background_bindings SET status = 'disabled', revision = %s, etag = %s, "
            "saved_by = %s, updated_at = clock_timestamp(), disabled_at = clock_timestamp() WHERE binding_id = %s",
            (revision, etag, saved_by, parsed_binding),
        )
        _insert_audit(
            conn, binding_id=parsed_binding, action="disabled", revision=revision,
            actor=saved_by, previous_asset_version_id=current[7],
            asset_version_id=current[7], previous_start_paragraph_id=current[2],
            previous_end_paragraph_id=current[3], start_paragraph_id=current[2],
            end_paragraph_id=current[3], display=current[8],
        )
    return _binding_output(_binding_row(conn, parsed_binding), include_audit=True)


def list_binding_audit(conn, binding_id: uuid.UUID | str) -> dict[str, Any]:
    parsed = _uuid7(binding_id, "binding_id")
    if _binding_row(conn, parsed) is None:
        raise BackgroundNotFound("background binding was not found")
    rows = conn.execute(
        """
        SELECT audit_id, action, revision, actor, previous_asset_version_id,
               asset_version_id, previous_start_paragraph_id,
               previous_end_paragraph_id, start_paragraph_id, end_paragraph_id,
               display, created_at
        FROM chronicle.background_binding_audit
        WHERE binding_id = %s ORDER BY revision, audit_id
        """,
        (parsed,),
    ).fetchall()
    return {
        "schema": "chronicle.background-binding-audit",
        "version": "0.1",
        "binding_id": str(parsed),
        "entries": [
            {
                "audit_id": str(row[0]),
                "action": row[1],
                "revision": int(row[2]),
                "actor": row[3],
                "previous_asset_version_id": str(row[4]) if row[4] is not None else None,
                "asset_version_id": str(row[5]),
                "previous_start_paragraph_id": row[6],
                "previous_end_paragraph_id": row[7],
                "start_paragraph_id": row[8],
                "end_paragraph_id": row[9],
                "display": _copy_json(row[10]) if isinstance(row[10], dict) else {},
                "created_at": _datetime(row[11]),
            }
            for row in rows
        ],
    }


def _public_binding_row(
    conn,
    *,
    edition_version: str,
    paragraph_id: str,
    binding_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
) -> Any:
    edition = _edition_version(edition_version)
    paragraph = _paragraph(paragraph_id, "paragraph_id")
    row = conn.execute(
        "SELECT ordinal FROM chronicle.history_edition_paragraph_index "
        "WHERE edition_version = %s AND paragraph_id = %s",
        (edition, paragraph),
    ).fetchone()
    if row is None:
        raise BackgroundNotFound("paragraph is outside this fixed history edition")
    clauses = [
        "b.edition_version = %s", "b.status = 'active'",
        "b.start_ordinal <= %s", "b.end_ordinal >= %s",
    ]
    params: list[Any] = [edition, int(row[0]), int(row[0])]
    if binding_id is not None:
        clauses.append("b.binding_id = %s")
        params.append(binding_id)
    if asset_id is not None:
        clauses.append("b.asset_id = %s")
        params.append(asset_id)
    return conn.execute(
        """
        SELECT b.binding_id, b.edition_version, b.start_paragraph_id,
               b.end_paragraph_id, b.start_ordinal, b.end_ordinal,
               b.asset_id, b.asset_version_id, b.display, b.status,
               b.revision, b.etag, b.saved_by, b.created_at, b.updated_at,
               b.disabled_at, a.source, a.era, a.prompt, a.metadata,
               v.version_no, v.content_sha256, v.media_type, v.image_format,
               v.original_filename, v.byte_size, v.width, v.height, v.storage_key
        FROM chronicle.background_bindings b
        JOIN chronicle.background_assets a ON a.asset_id = b.asset_id
        JOIN chronicle.background_asset_versions v ON v.asset_version_id = b.asset_version_id
        WHERE """ + " AND ".join(clauses) + " ORDER BY b.binding_id LIMIT 1",
        tuple(params),
    ).fetchone()


def _public_binding_output(row: Any) -> dict[str, Any]:
    """Return only reader metadata and display state from an active binding."""

    output = _binding_output(row)
    for private_key in ("saved_by", "created_at", "updated_at", "disabled_at", "audit_href"):
        output.pop(private_key, None)
    output["asset"].pop("prompt", None)
    output["asset"]["resource_href"] = f"/api/v1/public/background-assets/{row[6]}"
    return output


def _public_resource_href(
    asset_id: Any,
    *,
    edition_version: str | None = None,
    paragraph_id: str | None = None,
) -> str:
    href = f"/api/v1/public/background-assets/{asset_id}"
    if edition_version is not None and paragraph_id is not None:
        return f"{href}?version={edition_version}&paragraph_id={paragraph_id}"
    return href


def read_public_binding(
    conn,
    *,
    edition_version: str,
    paragraph_id: str,
) -> dict[str, Any] | None:
    row = _public_binding_row(
        conn, edition_version=edition_version, paragraph_id=paragraph_id
    )
    if row is None:
        return None
    output = _public_binding_output(row)
    href = _public_resource_href(
        row[6], edition_version=edition_version, paragraph_id=paragraph_id
    )
    output["asset"]["resource_href"] = href
    output["image_href"] = href
    return output


def _public_asset_row(
    conn,
    *,
    asset_id: uuid.UUID | None = None,
    asset_version_id: uuid.UUID | None = None,
    binding_id: uuid.UUID | None = None,
    edition_version: str | None = None,
    paragraph_id: str | None = None,
) -> Any:
    if edition_version is not None or paragraph_id is not None:
        if not edition_version or not paragraph_id:
            raise BackgroundValidationError(
                "edition_version and paragraph_id must be supplied together",
                code="invalid_public_locator",
            )
        row = _public_binding_row(
            conn,
            edition_version=edition_version,
            paragraph_id=paragraph_id,
            binding_id=binding_id,
            asset_id=asset_id,
        )
        if row is None:
            raise BackgroundNotFound("no active saved background covers this paragraph")
        if asset_version_id is not None and row[7] != asset_version_id:
            raise BackgroundNotFound("asset version is not the one saved for this paragraph")
        return row
    clauses = ["b.status = 'active'"]
    params: list[Any] = []
    if binding_id is not None:
        clauses.append("b.binding_id = %s")
        params.append(binding_id)
    if asset_id is not None:
        clauses.append("b.asset_id = %s")
        params.append(asset_id)
    if asset_version_id is not None:
        clauses.append("b.asset_version_id = %s")
        params.append(asset_version_id)
    row = conn.execute(
        """
        SELECT b.binding_id, b.edition_version, b.start_paragraph_id,
               b.end_paragraph_id, b.start_ordinal, b.end_ordinal,
               b.asset_id, b.asset_version_id, b.display, b.status,
               b.revision, b.etag, b.saved_by, b.created_at, b.updated_at,
               b.disabled_at, a.source, a.era, a.prompt, a.metadata,
               v.version_no, v.content_sha256, v.media_type, v.image_format,
               v.original_filename, v.byte_size, v.width, v.height, v.storage_key
        FROM chronicle.background_bindings b
        JOIN chronicle.background_assets a ON a.asset_id = b.asset_id
        JOIN chronicle.background_asset_versions v ON v.asset_version_id = b.asset_version_id
        WHERE """ + " AND ".join(clauses) + " ORDER BY b.created_at DESC LIMIT 1",
        tuple(params),
    ).fetchone()
    if row is None:
        raise BackgroundNotFound("background asset is not referenced by an active saved binding")
    return row


def read_public_asset(
    conn,
    *,
    storage_dir: Path | str,
    asset_id: uuid.UUID | str | None = None,
    asset_version_id: uuid.UUID | str | None = None,
    binding_id: uuid.UUID | str | None = None,
    edition_version: str | None = None,
    paragraph_id: str | None = None,
) -> tuple[str, bytes, dict[str, Any]]:
    if edition_version is None or paragraph_id is None:
        raise BackgroundValidationError(
            "public asset reads require edition_version and paragraph_id",
            code="invalid_public_locator",
        )
    parsed_asset = _uuid7(asset_id, "asset_id") if asset_id is not None else None
    parsed_version = _uuid7(asset_version_id, "asset_version_id") if asset_version_id is not None else None
    parsed_binding = _uuid7(binding_id, "binding_id") if binding_id is not None else None
    row = _public_asset_row(
        conn,
        asset_id=parsed_asset,
        asset_version_id=parsed_version,
        binding_id=parsed_binding,
        edition_version=edition_version,
        paragraph_id=paragraph_id,
    )
    _asset_row_value, raw = _verify_asset_file(conn, storage_dir, row[7])
    return str(row[22]), raw, {
        "binding_id": str(row[0]),
        "edition_version": str(row[1]),
        "paragraph_id": paragraph_id,
        "asset_id": str(row[6]),
        "asset_version_id": str(row[7]),
        "revision": int(row[10]),
        "etag": str(row[11]),
    }


def public_binding_for_asset(
    conn,
    *,
    asset_id: uuid.UUID | str,
    edition_version: str | None = None,
    paragraph_id: str | None = None,
) -> dict[str, Any]:
    parsed_asset = _uuid7(asset_id, "asset_id")
    row = _public_asset_row(
        conn,
        asset_id=parsed_asset,
        edition_version=edition_version,
        paragraph_id=paragraph_id,
    )
    output = _public_binding_output(row)
    href = _public_resource_href(
        row[6], edition_version=edition_version, paragraph_id=paragraph_id
    )
    output["asset"]["resource_href"] = href
    output["image_href"] = href
    return output


def read_candidate_asset(
    conn,
    *,
    storage_dir: Path | str,
    asset_id: uuid.UUID | str,
    asset_version_id: uuid.UUID | str | None = None,
) -> tuple[str, bytes]:
    """Read a candidate for the authenticated Studio preview surface."""

    parsed_asset = _uuid7(asset_id, "asset_id")
    parsed_version = _uuid7(asset_version_id, "asset_version_id") if asset_version_id is not None else None
    row = _asset_row(conn, parsed_asset, parsed_version)
    if row is None:
        raise BackgroundNotFound("background asset was not found")
    media, raw = _verify_asset_file(conn, storage_dir, row[6])
    return str(media[8]), raw


# The explicit-storage implementation is the authoritative API.  Keep the
# shorter product names as aliases for direct Python consumers.
upload_asset_version = create_asset_version
save_binding = create_binding_with_storage
create_background_binding = create_binding_with_storage
read_background_binding = get_binding
replace_background_binding = replace_binding
disable_background_binding = disable_binding
