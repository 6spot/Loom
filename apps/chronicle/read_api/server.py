#!/usr/bin/env python3
"""Minimal HTTP/JSON adapter over Chronicle's PostgreSQL read repository."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import psycopg

from read_common import ReadModelError
from repository import ChronicleReadRepository
from router import dispatch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle read API v0")
    parser.add_argument("--database-url", default=os.environ.get("CHRONICLE_DATABASE_URL"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    return parser


def handler_class(database_url: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ChronicleReadAPI/0.1"

        def _handle(self) -> None:
            split = urlsplit(self.path)
            try:
                if split.path == "/healthz":
                    status, payload = dispatch(None, self.command, split.path, split.query)
                else:
                    with psycopg.connect(database_url) as conn:
                        with conn.transaction():
                            conn.execute("SET TRANSACTION READ ONLY")
                            status, payload = dispatch(
                                ChronicleReadRepository(conn), self.command, split.path, split.query
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
            body = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def log_message(self, fmt: str, *args) -> None:
            print(f"chronicle read api: {self.address_string()} {fmt % args}")

    return Handler


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        raise ReadModelError(
            "Chronicle database URL is required via --database-url or CHRONICLE_DATABASE_URL"
        )
    server = ThreadingHTTPServer((args.host, args.port), handler_class(args.database_url))
    print(f"chronicle read api: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
