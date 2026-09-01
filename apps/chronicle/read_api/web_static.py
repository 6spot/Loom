"""Safe same-origin static routing for Chronicle's zero-build browser UI."""

from __future__ import annotations

import re
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"

_STATIC_FILES = {
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/search.css": ("search.css", "text/css; charset=utf-8"),
    "/app.mjs": ("app.mjs", "text/javascript; charset=utf-8"),
    "/ui.mjs": ("ui.mjs", "text/javascript; charset=utf-8"),
    "/search_ui.mjs": ("search_ui.mjs", "text/javascript; charset=utf-8"),
    "/route_safe.mjs": ("route_safe.mjs", "text/javascript; charset=utf-8"),
}

_SPA_PATHS = (
    re.compile(r"^/$"),
    re.compile(r"^/timeline/?$"),
    re.compile(r"^/search/?$"),
    re.compile(r"^/events/[^/]+/?$"),
    re.compile(r"^/entities/[^/]+/?$"),
)


def _read(root: Path, filename: str) -> bytes:
    """Read one allowlisted UI file without accepting caller-controlled filesystem paths."""
    return (root / filename).read_bytes()


def web_response(
    method: str,
    path: str,
    *,
    root: Path = WEB_ROOT,
) -> tuple[int, str, bytes]:
    """Return status/content-type/body for one Chronicle browser route.

    Only explicit assets and SPA navigation routes are accepted. No request path
    is ever joined directly to the filesystem, so traversal cannot escape the web
    root. API and health routes are intentionally not handled here.
    """
    if method != "GET":
        return 405, "text/plain; charset=utf-8", b"method not allowed\n"

    asset = _STATIC_FILES.get(path)
    if asset is not None:
        filename, content_type = asset
        try:
            return 200, content_type, _read(root, filename)
        except FileNotFoundError:
            return 404, "text/plain; charset=utf-8", b"not found\n"

    if any(pattern.fullmatch(path) for pattern in _SPA_PATHS):
        try:
            return 200, "text/html; charset=utf-8", _read(root, "index.html")
        except FileNotFoundError:
            return 404, "text/plain; charset=utf-8", b"not found\n"

    return 404, "text/plain; charset=utf-8", b"not found\n"
