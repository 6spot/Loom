"""Studio and public HTTP adapters for Chronicle background assets.

The Rust server authenticates the Studio namespace and forwards these routes;
this module owns only the Chronicle application contract.  Public metadata is
edition/paragraph pinned, while public image bytes require an active saved
binding.  Candidate preview bytes are exposed only through the authenticated
Studio route.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
if str(_PERSISTENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE_DIR))

import background_assets as store  # noqa: E402


STUDIO_ASSETS_PREFIX = "/api/v1/studio/background-assets"
STUDIO_BINDINGS_PREFIX = "/api/v1/studio/background-bindings"
PUBLIC_BACKGROUNDS_PREFIX = "/v0/backgrounds"
PUBLIC_ASSETS_PREFIX = "/v0/background-assets"
PUBLIC_RESOURCES_PREFIX = "/v0/background-resources"

# Plural aliases keep the route vocabulary readable to clients while retaining
# one persistence path and one public authorization gate.
STUDIO_ASSET_ALIAS = "/api/v1/studio/backgrounds"
PUBLIC_BACKGROUND_ALIAS = "/v0/background"


class _BadRequest(Exception):
    pass


class _NotFound(Exception):
    pass


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.error",
            "version": "0.1",
            "error": {"code": code, "message": message},
        }
    )


def _query(raw_query: str, allowed: set[str]) -> dict[str, str]:
    values = parse_qs(raw_query, keep_blank_values=True)
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise _BadRequest(f"unknown background query parameter(s): {', '.join(unknown)}")
    result: dict[str, str] = {}
    for key, items in values.items():
        if len(items) != 1:
            raise _BadRequest(f"query parameter {key} must appear once")
        result[key] = items[0]
    return result


def _int(value: str | None, name: str, default: int, *, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if not re.fullmatch(r"[0-9]+", value):
        raise _BadRequest(f"{name} must be an integer")
    result = int(value)
    if result < minimum or result > maximum:
        raise _BadRequest(f"{name} must be between {minimum} and {maximum}")
    return result


def _uuid(value: str, name: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _NotFound(f"{name} was not found") from exc
    if parsed.version != 7:
        raise _NotFound(f"{name} was not found")
    return str(parsed)


def _body(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _BadRequest("request body must be a JSON object") from exc
    if not isinstance(value, dict):
        raise _BadRequest("request body must be a JSON object")
    return value


def _field(payload: dict[str, Any], canonical: str, *aliases: str) -> Any:
    for name in (canonical, *aliases):
        if name in payload:
            return payload[name]
    return None


def _metadata_query(value: str | None) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _BadRequest("metadata query must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise _BadRequest("metadata query must be a JSON object")
    return parsed


def _store_error(exc: store.BackgroundError) -> tuple[int, str, bytes]:
    return _error(exc.status, exc.code, str(exc))


def dispatch_studio(
    conn,
    *,
    storage_dir: Path | str,
    max_upload_bytes: int,
    method: str,
    path: str,
    raw_query: str = "",
    body: bytes = b"",
    content_type: str | None = None,
) -> tuple[int, str, bytes]:
    """Dispatch one authenticated Studio background request."""

    try:
        if path == STUDIO_ASSET_ALIAS or path.startswith(STUDIO_ASSET_ALIAS + "/"):
            path = STUDIO_ASSETS_PREFIX + path[len(STUDIO_ASSET_ALIAS):]
        if path == STUDIO_ASSETS_PREFIX or path.startswith(STUDIO_ASSETS_PREFIX + "/"):
            return _studio_asset_route(
                conn,
                storage_dir=storage_dir,
                max_upload_bytes=max_upload_bytes,
                method=method,
                path=path,
                raw_query=raw_query,
                body=body,
                content_type=content_type,
            )
        if path == STUDIO_BINDINGS_PREFIX or path.startswith(STUDIO_BINDINGS_PREFIX + "/"):
            return _studio_binding_route(
                conn,
                storage_dir=storage_dir,
                method=method,
                path=path,
                raw_query=raw_query,
                body=body,
            )
        raise _NotFound("background Studio route not found")
    except store.BackgroundError as exc:
        return _store_error(exc)
    except _BadRequest as exc:
        return _error(400, "bad_request", str(exc))
    except _NotFound as exc:
        return _error(404, "not_found", str(exc))


def _studio_asset_route(
    conn,
    *,
    storage_dir: Path | str,
    max_upload_bytes: int,
    method: str,
    path: str,
    raw_query: str,
    body: bytes,
    content_type: str | None,
) -> tuple[int, str, bytes]:
    if path == STUDIO_ASSETS_PREFIX:
        if method == "GET":
            query = _query(raw_query, {"source", "era", "limit", "offset"})
            return 200, "application/json; charset=utf-8", _json_bytes(
                store.list_assets(
                    conn,
                    storage_dir=storage_dir,
                    source=query.get("source"),
                    era=query.get("era"),
                    limit=_int(query.get("limit"), "limit", 50, minimum=1, maximum=100),
                    offset=_int(query.get("offset"), "offset", 0, minimum=0, maximum=10_000_000),
                )
            )
        if method == "POST":
            query = _query(raw_query, {"filename", "source", "era", "prompt", "metadata"})
            result = store.create_asset(
                conn,
                data=body,
                storage_dir=storage_dir,
                filename=query.get("filename"),
                content_type=content_type,
                source=query.get("source"),
                era=query.get("era"),
                prompt=query.get("prompt"),
                metadata=_metadata_query(query.get("metadata")),
                max_bytes=max_upload_bytes,
            )
            return 201, "application/json; charset=utf-8", _json_bytes(
                {"schema": "chronicle.background-asset", "version": "0.1", "asset": result}
            )
        raise _BadRequest(f"method {method} is not supported on {path}")

    rest = path[len(STUDIO_ASSETS_PREFIX) + 1:]
    parts = rest.split("/")
    if len(parts) == 2 and parts[1] == "versions":
        if method != "POST":
            raise _BadRequest(f"method {method} is not supported on {path}")
        query = _query(raw_query, {"filename"})
        result = store.create_asset_version(
            conn,
            _uuid(parts[0], "asset"),
            data=body,
            storage_dir=storage_dir,
            filename=query.get("filename"),
            content_type=content_type,
            max_bytes=max_upload_bytes,
        )
        return 201, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.background-asset", "version": "0.1", "asset": result}
        )
    if len(parts) == 2 and parts[1] in {"preview", "content"}:
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        query = _query(raw_query, {"asset_version_id"})
        asset_id = _uuid(parts[0], "asset")
        media, raw = store.read_candidate_asset(
            conn,
            storage_dir=storage_dir,
            asset_id=asset_id,
            asset_version_id=query.get("asset_version_id"),
        )
        return 200, media, raw
    if len(parts) == 1 and parts[0]:
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        query = _query(raw_query, {"asset_version_id"})
        result = store.get_asset(
            conn,
            _uuid(parts[0], "asset"),
            storage_dir=storage_dir,
            asset_version_id=query.get("asset_version_id"),
        )
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.background-asset", "version": "0.1", "asset": result}
        )
    raise _NotFound("background asset route not found")


def _normalise_binding_payload(payload: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
    allowed = {
        "edition_version", "version", "start_paragraph_id", "start_paragraph",
        "end_paragraph_id", "end_paragraph", "asset_id", "asset_version_id",
        "display", "actor", "expected_revision", "expected_etag",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _BadRequest(f"unknown background binding field(s): {', '.join(unknown)}")
    result: dict[str, Any] = {
        "edition_version": _field(payload, "edition_version", "version"),
        "start_paragraph_id": _field(payload, "start_paragraph_id", "start_paragraph"),
        "end_paragraph_id": _field(payload, "end_paragraph_id", "end_paragraph"),
        "asset_id": payload.get("asset_id"),
        "asset_version_id": payload.get("asset_version_id"),
        "display": payload.get("display"),
        "actor": payload.get("actor"),
        "expected_revision": payload.get("expected_revision"),
        "expected_etag": payload.get("expected_etag"),
    }
    if not replace:
        required = ("edition_version", "start_paragraph_id", "end_paragraph_id", "asset_id", "asset_version_id")
        if any(result.get(key) is None for key in required):
            raise _BadRequest("saving a background binding requires edition, paragraph range, asset and asset version")
    elif result["asset_id"] is None or result["asset_version_id"] is None:
        raise _BadRequest("replacing a background binding requires asset and asset version")
    return result


def _studio_binding_route(
    conn,
    *,
    storage_dir: Path | str,
    method: str,
    path: str,
    raw_query: str,
    body: bytes,
) -> tuple[int, str, bytes]:
    if path == STUDIO_BINDINGS_PREFIX:
        if method != "GET" and method != "POST":
            raise _BadRequest(f"method {method} is not supported on {path}")
        if method == "GET":
            query = _query(raw_query, {"edition_version", "version", "paragraph_id", "status", "limit", "offset"})
            edition = query.get("edition_version") or query.get("version")
            result = store.list_bindings(
                conn,
                edition_version=edition,
                paragraph_id=query.get("paragraph_id"),
                status=query.get("status"),
                limit=_int(query.get("limit"), "limit", 50, minimum=1, maximum=100),
                offset=_int(query.get("offset"), "offset", 0, minimum=0, maximum=10_000_000),
            )
            return 200, "application/json; charset=utf-8", _json_bytes(result)
        payload = _normalise_binding_payload(_body(body))
        result = store.create_binding(
            conn,
            edition_version=payload["edition_version"],
            start_paragraph_id=payload["start_paragraph_id"],
            end_paragraph_id=payload["end_paragraph_id"],
            asset_id=payload["asset_id"],
            asset_version_id=payload["asset_version_id"],
            display=payload["display"],
            actor=payload["actor"],
            storage_dir=storage_dir,
        )
        return 201, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.background-binding", "version": "0.1", "binding": result}
        )

    rest = path[len(STUDIO_BINDINGS_PREFIX) + 1:]
    parts = rest.split("/")
    if not parts or not parts[0]:
        raise _NotFound("background binding route not found")
    binding_id = _uuid(parts[0], "binding")
    if len(parts) == 1:
        if method != "GET":
            if method == "DELETE":
                result = store.disable_binding(conn, binding_id)
                return 200, "application/json; charset=utf-8", _json_bytes(
                    {"schema": "chronicle.background-binding", "version": "0.1", "binding": result}
                )
            raise _BadRequest(f"method {method} is not supported on {path}")
        result = store.get_binding(conn, binding_id)
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.background-binding", "version": "0.1", "binding": result}
        )
    if len(parts) == 2 and parts[1] == "audit":
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        return 200, "application/json; charset=utf-8", _json_bytes(
            store.list_binding_audit(conn, binding_id)
        )
    if len(parts) == 2 and parts[1] == "replace":
        if method != "POST":
            raise _BadRequest(f"method {method} is not supported on {path}")
        payload = _normalise_binding_payload(_body(body), replace=True)
        result = store.replace_binding(
            conn,
            binding_id,
            storage_dir=storage_dir,
            asset_id=payload["asset_id"],
            asset_version_id=payload["asset_version_id"],
            display=payload["display"],
            start_paragraph_id=payload["start_paragraph_id"],
            end_paragraph_id=payload["end_paragraph_id"],
            actor=payload["actor"],
            expected_revision=payload["expected_revision"],
            expected_etag=payload["expected_etag"],
        )
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.background-binding", "version": "0.1", "binding": result}
        )
    if len(parts) == 2 and parts[1] in {"disable", "deactivate"}:
        if method != "POST":
            raise _BadRequest(f"method {method} is not supported on {path}")
        payload = _body(body)
        allowed = {"actor", "expected_revision", "expected_etag"}
        if set(payload) - allowed:
            raise _BadRequest("unknown background disable field")
        result = store.disable_binding(
            conn,
            binding_id,
            actor=payload.get("actor"),
            expected_revision=payload.get("expected_revision"),
            expected_etag=payload.get("expected_etag"),
        )
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.background-binding", "version": "0.1", "binding": result}
        )
    raise _NotFound("background binding route not found")


def dispatch_public(conn, *, method: str, path: str, raw_query: str = "") -> tuple[int, dict[str, Any]] | None:
    """Dispatch public JSON metadata routes; bytes use ``dispatch_resource``."""

    if path == PUBLIC_BACKGROUND_ALIAS:
        path = PUBLIC_BACKGROUNDS_PREFIX
    if path == PUBLIC_BACKGROUNDS_PREFIX:
        if method != "GET":
            return 405, {
                "schema": "chronicle.error", "version": "0.1",
                "error": {"code": "method_not_allowed", "message": "only GET is supported"},
            }
        try:
            query = _query(raw_query, {"version", "edition_version", "paragraph_id"})
            edition = query.get("version") or query.get("edition_version")
            if not edition or not query.get("paragraph_id"):
                raise _BadRequest("public background reads require version and paragraph_id")
            binding = store.read_public_binding(
                conn, edition_version=edition, paragraph_id=query["paragraph_id"]
            )
            return 200, {
                "schema": "chronicle.background-read", "version": "0.1",
                "edition_version": edition,
                "paragraph_id": query["paragraph_id"],
                "background": binding,
            }
        except store.BackgroundError as exc:
            return exc.status, {
                "schema": "chronicle.error", "version": "0.1",
                "error": {"code": exc.code, "message": str(exc)},
            }
        except _BadRequest as exc:
            return 400, {
                "schema": "chronicle.error", "version": "0.1",
                "error": {"code": "bad_request", "message": str(exc)},
            }
    # A binding detail is useful for readers that already hold its id, but it
    # still goes through the active edition/paragraph check when supplied.
    if path.startswith(PUBLIC_BACKGROUNDS_PREFIX + "/"):
        rest = path[len(PUBLIC_BACKGROUNDS_PREFIX) + 1:]
        if rest and "/" not in rest:
            try:
                query = _query(raw_query, {"version", "edition_version", "paragraph_id"})
                edition = query.get("version") or query.get("edition_version")
                if not edition or not query.get("paragraph_id"):
                    raise _BadRequest("public binding reads require version and paragraph_id")
                binding = store._public_binding_row(  # noqa: SLF001 - same adapter contract
                    conn,
                    edition_version=edition,
                    paragraph_id=query["paragraph_id"],
                    binding_id=uuid.UUID(_uuid(rest, "binding")),
                )
                if binding is None:
                    raise store.BackgroundNotFound("background binding is not active at this position")
                return 200, {
                    "schema": "chronicle.background-read", "version": "0.1",
                    "edition_version": edition, "paragraph_id": query["paragraph_id"],
                    "background": store.read_public_binding(
                        conn, edition_version=edition, paragraph_id=query["paragraph_id"]
                    ),
                }
            except store.BackgroundError as exc:
                return exc.status, {
                    "schema": "chronicle.error", "version": "0.1",
                    "error": {"code": exc.code, "message": str(exc)},
                }
            except _BadRequest as exc:
                return 400, {
                    "schema": "chronicle.error", "version": "0.1",
                    "error": {"code": "bad_request", "message": str(exc)},
                }
            except _NotFound as exc:
                return 404, {
                    "schema": "chronicle.error", "version": "0.1",
                    "error": {"code": "not_found", "message": str(exc)},
                }
    return None


def dispatch_resource(
    conn,
    *,
    storage_dir: Path | str,
    method: str,
    path: str,
    raw_query: str = "",
) -> tuple[int, str, bytes] | None:
    """Return one public image response, or ``None`` for JSON routes."""

    if path == PUBLIC_ASSETS_PREFIX or path.startswith(PUBLIC_ASSETS_PREFIX + "/"):
        if method != "GET":
            return _error(405, "method_not_allowed", "only GET is supported")
        rest = path[len(PUBLIC_ASSETS_PREFIX):].strip("/")
        if not rest or "/" in rest:
            return _error(404, "not_found", "background resource not found")
        try:
            query = _query(raw_query, {"version", "edition_version", "paragraph_id", "binding_id", "asset_version_id"})
            edition = query.get("version") or query.get("edition_version")
            if not edition or not query.get("paragraph_id"):
                raise _BadRequest("public asset reads require version and paragraph_id")
            media, raw, _meta = store.read_public_asset(
                conn,
                storage_dir=storage_dir,
                asset_id=_uuid(rest, "asset"),
                asset_version_id=query.get("asset_version_id"),
                binding_id=query.get("binding_id"),
                edition_version=edition,
                paragraph_id=query.get("paragraph_id"),
            )
            return 200, media, raw
        except store.BackgroundError as exc:
            return _store_error(exc)
        except (_BadRequest, _NotFound) as exc:
            status = 400 if isinstance(exc, _BadRequest) else 404
            code = "bad_request" if isinstance(exc, _BadRequest) else "not_found"
            return _error(status, code, str(exc))

    if path == PUBLIC_RESOURCES_PREFIX or path.startswith(PUBLIC_RESOURCES_PREFIX + "/"):
        if method != "GET":
            return _error(405, "method_not_allowed", "only GET is supported")
        rest = path[len(PUBLIC_RESOURCES_PREFIX):].strip("/")
        if not rest or "/" in rest:
            return _error(404, "not_found", "background resource not found")
        try:
            query = _query(raw_query, {"version", "edition_version", "paragraph_id"})
            edition = query.get("version") or query.get("edition_version")
            if not edition or not query.get("paragraph_id"):
                raise _BadRequest("public resource reads require version and paragraph_id")
            media, raw, _meta = store.read_public_asset(
                conn,
                storage_dir=storage_dir,
                binding_id=_uuid(rest, "binding"),
                edition_version=edition,
                paragraph_id=query["paragraph_id"],
            )
            return 200, media, raw
        except store.BackgroundError as exc:
            return _store_error(exc)
        except (_BadRequest, _NotFound) as exc:
            status = 400 if isinstance(exc, _BadRequest) else 404
            code = "bad_request" if isinstance(exc, _BadRequest) else "not_found"
            return _error(status, code, str(exc))
    return None


# Names used by the sidecar bootstrap and future clients.
dispatch_studio_backgrounds = dispatch_studio
dispatch_public_backgrounds = dispatch_public
