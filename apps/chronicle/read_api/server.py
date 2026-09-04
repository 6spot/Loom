#!/usr/bin/env python3
"""Chronicle read API plus same-origin zero-build browser UI host."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

# The C1-T3 document store lives in the registered application persistence
# root next to this sidecar (Architecture Amendment 0006). The sidecar and
# the persistence package ship together in every deployment (Dockerfile
# copies whole apps/chronicle), so a relative bootstrap is stable.
_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
if str(_PERSISTENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE_DIR))

import documents as document_store
from read_common import ReadModelError
from repository import ChronicleReadRepository
from router import dispatch
from studio_documents import STUDIO_PREFIX, dispatch_studio
from studio_jobs import STUDIO_JOBS_PREFIX, dispatch_jobs
from web_static import web_response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle read API and browser UI v0")
    parser.add_argument("--database-url", default=os.environ.get("CHRONICLE_DATABASE_URL"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--storage-dir",
        default=os.environ.get("CHRONICLE_SOURCE_DIR", "./chronicle-sources"),
        help="Chronicle-owned source data directory (relative storage keys resolve here)",
    )
    parser.add_argument(
        "--max-upload-bytes",
        type=int,
        default=None,
        help="per-file upload ceiling; defaults to CHRONICLE_MAX_UPLOAD_BYTES or 10 MiB",
    )
    return parser


def handler_class(
    database_url: str,
    storage_dir: str | Path | None = None,
    max_upload_bytes: int | None = None,
):
    resolved_storage = Path(storage_dir) if storage_dir else document_store.storage_dir_from_env()
    resolved_max = (
        max_upload_bytes
        if max_upload_bytes is not None
        else document_store.max_upload_bytes()
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "Chronicle/0.1"

        def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict) -> None:
            body = (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            self._send_bytes(status, "application/json; charset=utf-8", body)

        def _handle_api(self, path: str, query: str) -> None:
            try:
                if path == "/healthz":
                    status, payload = dispatch(None, self.command, path, query)
                else:
                    with psycopg.connect(database_url) as conn:
                        with conn.transaction():
                            conn.execute("SET TRANSACTION READ ONLY")
                            status, payload = dispatch(
                                ChronicleReadRepository(conn), self.command, path, query
                            )
            except psycopg.Error:
                status, payload = 503, {
                    "schema": "chronicle.error",
                    "version": "0.1",
                    "error": {
                        "code": "database_unavailable",
                        "message": "Chronicle PostgreSQL read failed",
                    },
                }
            self._send_json(status, payload)

        def _method_not_allowed(self) -> None:
            payload = (
                json.dumps(
                    {
                        "schema": "chronicle.error",
                        "version": "0.1",
                        "error": {
                            "code": "method_not_allowed",
                            "message": "only GET and POST are supported",
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            self._send_bytes(405, "application/json; charset=utf-8", payload)

        def _handle_studio_documents(self, path: str, query: str) -> None:
            # Studio document writes run in a read-write transaction (unlike
            # the read-only /v0/* path). Authentication is enforced upstream
            # by the Rust chronicle-server Studio namespace; this sidecar is
            # never published outside the deployment network.
            if self.command not in ("GET", "POST"):
                self._method_not_allowed()
                return
            if self.command == "POST":
                try:
                    declared = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    declared = 0
                if declared > resolved_max + 1:
                    # Refuse to buffer an over-limit body at all.
                    payload = (
                        json.dumps(
                            {
                                "schema": "chronicle.error",
                                "version": "0.1",
                                "error": {
                                    "code": "payload_too_large",
                                    "message": (
                                        f"upload exceeds the {resolved_max}-byte limit"
                                    ),
                                },
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                    self._send_bytes(413, "application/json; charset=utf-8", payload)
                    return
                body = self.rfile.read(declared) if declared > 0 else b""
                media = self.headers.get("Content-Type")
            else:
                body, media = b"", None
            try:
                with psycopg.connect(database_url) as conn:
                    status, content_type, payload = dispatch_studio(
                        conn,
                        document_store,
                        storage_dir=resolved_storage,
                        max_upload_bytes=resolved_max,
                        method=self.command,
                        path=path,
                        raw_query=query,
                        body=body,
                        content_type=media,
                    )
            except psycopg.Error:
                status, content_type, payload = (
                    503,
                    "application/json; charset=utf-8",
                    (
                        '{"schema":"chronicle.error","version":"0.1",'
                        '"error":{"code":"database_unavailable",'
                        '"message":"Chronicle PostgreSQL write failed"}}\n'
                    ).encode("utf-8"),
                )
            self._send_bytes(status, content_type, payload)

        def _handle_studio_jobs(self, path: str, query: str) -> None:
            # Studio job lifecycle operations (C1-T4) run in a read-write
            # transaction. Authentication is enforced upstream by the Rust
            # chronicle-server Studio namespace; this sidecar is never
            # published outside the deployment network.
            if self.command == "POST":
                try:
                    declared = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    declared = 0
                if declared > 65536:
                    # Job operations carry tiny JSON bodies; refuse to
                    # buffer anything larger at all.
                    payload = (
                        json.dumps(
                            {
                                "schema": "chronicle.error",
                                "version": "0.1",
                                "error": {
                                    "code": "payload_too_large",
                                    "message": "job request body exceeds 64 KiB",
                                },
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                    self._send_bytes(413, "application/json; charset=utf-8", payload)
                    return
                body = self.rfile.read(declared) if declared > 0 else b""
            elif self.command == "GET":
                body = b""
            else:
                self._method_not_allowed()
                return
            try:
                import control_plane

                with psycopg.connect(database_url) as conn:
                    status, content_type, payload = dispatch_jobs(
                        conn,
                        control_plane,
                        method=self.command,
                        path=path,
                        raw_query=query,
                        body=body,
                    )
            except psycopg.Error:
                status, content_type, payload = (
                    503,
                    "application/json; charset=utf-8",
                    (
                        '{"schema":"chronicle.error","version":"0.1",'
                        '"error":{"code":"database_unavailable",'
                        '"message":"Chronicle PostgreSQL write failed"}}\n'
                    ).encode("utf-8"),
                )
            self._send_bytes(status, content_type, payload)

        def _handle(self) -> None:
            split = urlsplit(self.path)
            if split.path == "/healthz" or split.path.startswith("/v0/"):
                self._handle_api(split.path, split.query)
                return
            if split.path == STUDIO_PREFIX or split.path.startswith(STUDIO_PREFIX + "/"):
                self._handle_studio_documents(split.path, split.query)
                return
            if split.path == STUDIO_JOBS_PREFIX or split.path.startswith(
                STUDIO_JOBS_PREFIX + "/"
            ):
                self._handle_studio_jobs(split.path, split.query)
                return

            status, content_type, body = web_response(self.command, split.path)
            self._send_bytes(status, content_type, body)

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_PUT(self) -> None:  # noqa: N802
            self._handle()

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle()

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle()

        def log_message(self, fmt: str, *args) -> None:
            print(f"chronicle: {self.address_string()} {fmt % args}")

    return Handler


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        raise ReadModelError(
            "Chronicle database URL is required via --database-url or CHRONICLE_DATABASE_URL"
        )
    if args.max_upload_bytes is not None and args.max_upload_bytes < 1:
        raise ReadModelError("--max-upload-bytes must be a positive integer")
    server = ThreadingHTTPServer(
        (args.host, args.port),
        handler_class(args.database_url, args.storage_dir, args.max_upload_bytes),
    )
    print(f"chronicle: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
