"""Prepare and ingest pinned historical source packs through Chronicle Studio.

C1-T13 uses this operator tool instead of hand-splitting staged fixtures.  It
has two deliberately separate phases:

``prepare``
    Fetch a pinned Wikisource revision through the MediaWiki parse API, extract
    one complete named biographical section into deterministic UTF-8 text, and
    record the exact bytes/hash that will become Chronicle source evidence.

``ingest``
    Consume only those prepared files, create/reuse Studio Documents, upload
    immutable revisions through the public Studio HTTP boundary, and create or
    reuse ingestion jobs for the exact revision.

The tool never writes staged Entity/Event/Claim JSON.  All historical knowledge
must be produced by the normal worker pipeline after the Studio job is queued.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import error, parse, request

PACK_SCHEMA = "chronicle.corpus-source-pack"
PACK_VERSION = "0.1"
PREPARED_SCHEMA = "chronicle.prepared-source-pack"
PREPARED_VERSION = "0.1"
DEFAULT_WIKISOURCE_ENDPOINT = "https://zh.wikisource.org/w/api.php"
DEFAULT_TIMEOUT_SECONDS = 45.0
MAX_REMOTE_BYTES = 16 * 1024 * 1024
USER_AGENT = "Loom-Chronicle-C1-T13/0.1 (+https://github.com/6spot/Loom)"


class SourcePackError(RuntimeError):
    """Fail-closed source-pack preparation or Studio ingestion error."""


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).strip()


def _clean_block(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


class _SectionTextParser(HTMLParser):
    """Extract rendered paragraph text under one exact h2/h3 heading."""

    _VOID = {"br", "img", "meta", "link", "hr", "input", "source", "wbr"}

    def __init__(self, section: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target = _normalize_heading(section)
        self.heading_tag: str | None = None
        self.heading_parts: list[str] = []
        self.active = False
        self.found = False
        self.finished = False
        self.paragraph_depth = 0
        self.paragraph_parts: list[str] = []
        self.blocks: list[str] = []
        self.skip_depth = 0
        self._skip_starts: list[bool] = []

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        raw = next((value for key, value in attrs if key == "class"), None) or ""
        return set(raw.split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        classes = self._classes(attrs)
        starts_skip = bool(
            self.skip_depth
            or tag in {"script", "style", "noscript"}
            or "mw-editsection" in classes
            or "reference" in classes
        )
        if tag not in self._VOID:
            self._skip_starts.append(starts_skip)
        if starts_skip:
            self.skip_depth += 1
            return
        if self.finished:
            return
        if tag in {"h2", "h3"}:
            self.heading_tag = tag
            self.heading_parts = []
            return
        if tag == "p" and self.active:
            self.paragraph_depth += 1
            if self.paragraph_depth == 1:
                self.paragraph_parts = []
            return
        if tag == "br" and self.active and self.paragraph_depth:
            self.paragraph_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in self._VOID and self._skip_starts:
            started_skip = self._skip_starts.pop()
            if started_skip:
                self.skip_depth = max(0, self.skip_depth - 1)
                return
        if self.skip_depth or self.finished:
            return
        if self.heading_tag == tag:
            heading = _normalize_heading("".join(self.heading_parts))
            if self.active and heading != self.target:
                self.active = False
                self.finished = True
            elif heading == self.target:
                self.active = True
                self.found = True
            self.heading_tag = None
            self.heading_parts = []
            return
        if tag == "p" and self.active and self.paragraph_depth:
            self.paragraph_depth -= 1
            if self.paragraph_depth == 0:
                block = _clean_block("".join(self.paragraph_parts))
                if block:
                    self.blocks.append(block)
                self.paragraph_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth or self.finished:
            return
        if self.heading_tag is not None:
            self.heading_parts.append(data)
        elif self.active and self.paragraph_depth:
            self.paragraph_parts.append(data)

    def result(self) -> str:
        if not self.found:
            raise SourcePackError(f"source section heading not found: {self.target!r}")
        if not self.blocks:
            raise SourcePackError(f"source section contains no paragraphs: {self.target!r}")
        return "\n\n".join(self.blocks).strip() + "\n"


def extract_section_text(html: str, section: str) -> str:
    parser = _SectionTextParser(section)
    parser.feed(html)
    parser.close()
    return parser.result()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourcePackError(f"cannot read source-pack manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourcePackError("source-pack manifest must be a JSON object")
    if payload.get("schema") != PACK_SCHEMA or payload.get("version") != PACK_VERSION:
        raise SourcePackError("unsupported source-pack manifest schema/version")
    acquisition = payload.get("acquisition")
    sources = payload.get("sources")
    if not isinstance(acquisition, dict) or not isinstance(sources, list) or not sources:
        raise SourcePackError("source-pack manifest requires acquisition and non-empty sources")
    keys: set[str] = set()
    filenames: set[str] = set()
    for item in sources:
        if not isinstance(item, dict):
            raise SourcePackError("every source-pack entry must be an object")
        for field in ("key", "title", "filename", "page_title", "section"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise SourcePackError(f"source entry requires non-empty {field}")
        oldid = item.get("oldid")
        if not isinstance(oldid, int) or oldid < 1:
            raise SourcePackError("source entry oldid must be a positive integer")
        if item["key"] in keys:
            raise SourcePackError(f"duplicate source key {item['key']!r}")
        if item["filename"] in filenames:
            raise SourcePackError(f"duplicate source filename {item['filename']!r}")
        if Path(item["filename"]).name != item["filename"] or not item["filename"].endswith(".txt"):
            raise SourcePackError("source filenames must be plain .txt basenames")
        keys.add(item["key"])
        filenames.add(item["filename"])
    return payload


def _fetch_parse_html(endpoint: str, oldid: int, *, timeout: float) -> str:
    query = parse.urlencode(
        {
            "action": "parse",
            "oldid": str(oldid),
            "prop": "text|revid",
            "format": "json",
            "formatversion": "2",
            "disableeditsection": "1",
        }
    )
    req = request.Request(
        endpoint.rstrip("?") + "?" + query,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read(MAX_REMOTE_BYTES + 1)
    except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
        raise SourcePackError(f"Wikisource fetch failed for oldid={oldid}") from exc
    if len(raw) > MAX_REMOTE_BYTES:
        raise SourcePackError(f"Wikisource response too large for oldid={oldid}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourcePackError(f"Wikisource returned invalid JSON for oldid={oldid}") from exc
    parsed = payload.get("parse") if isinstance(payload, dict) else None
    if not isinstance(parsed, dict):
        raise SourcePackError(f"Wikisource parse payload missing for oldid={oldid}")
    if parsed.get("revid") != oldid:
        raise SourcePackError(
            f"Wikisource revision drift: requested {oldid}, got {parsed.get('revid')!r}"
        )
    html = parsed.get("text")
    if not isinstance(html, str) or not html.strip():
        raise SourcePackError(f"Wikisource parsed text missing for oldid={oldid}")
    return html


def _source_label(entry: dict[str, Any], transform_version: str) -> str:
    page = parse.quote(entry["page_title"].replace(" ", "_"), safe="/")
    permanent = (
        "https://zh.wikisource.org/w/index.php?title="
        + page
        + "&oldid="
        + str(entry["oldid"])
    )
    return (
        f"Wikisource {entry['page_title']} oldid={entry['oldid']} "
        f"section={entry['section']} transform={transform_version} source={permanent}"
    )


def prepare_pack(
    manifest: dict[str, Any], output_dir: Path, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    acquisition = manifest["acquisition"]
    endpoint = acquisition.get("endpoint") or DEFAULT_WIKISOURCE_ENDPOINT
    transform_version = acquisition.get("transform_version")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise SourcePackError("acquisition endpoint must be an https URL")
    if not isinstance(transform_version, str) or not transform_version:
        raise SourcePackError("acquisition transform_version is required")

    html_by_oldid: dict[int, str] = {}
    prepared: list[dict[str, Any]] = []
    for entry in manifest["sources"]:
        oldid = entry["oldid"]
        html = html_by_oldid.get(oldid)
        if html is None:
            html = _fetch_parse_html(endpoint, oldid, timeout=timeout)
            html_by_oldid[oldid] = html
        text = extract_section_text(html, entry["section"])
        raw = text.encode("utf-8")
        target = output_dir / entry["filename"]
        target.write_bytes(raw)
        prepared.append(
            {
                "key": entry["key"],
                "title": entry["title"],
                "filename": entry["filename"],
                "language": manifest.get("language", "zh-Hant"),
                "page_title": entry["page_title"],
                "oldid": oldid,
                "section": entry["section"],
                "source_label": _source_label(entry, transform_version),
                "bytes": len(raw),
                "sha256": _sha256(raw),
            }
        )

    report = {
        "schema": PREPARED_SCHEMA,
        "version": PREPARED_VERSION,
        "pack_id": manifest.get("pack_id"),
        "manifest_sha256": _sha256(_json_bytes(manifest)),
        "transform_version": transform_version,
        "sources": prepared,
    }
    (output_dir / "prepared.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


@dataclass
class StudioClient:
    base_url: str
    username: str
    password: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        parsed = parse.urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SourcePackError("Studio base URL must be an absolute http(s) URL")
        self.base_url = self.base_url.rstrip("/")
        if not self.username or not self.password:
            raise SourcePackError("Studio admin username/password are required")

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        content_type: str | None = None,
    ) -> Any:
        url = self.base_url + path
        if query:
            url += "?" + parse.urlencode(query)
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        headers = {"Accept": "application/json", "Authorization": f"Basic {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        req = request.Request(url, data=body if method != "GET" else None, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read(MAX_REMOTE_BYTES + 1)
        except error.HTTPError as exc:
            raise SourcePackError(f"Studio {method} {path} returned HTTP {exc.code}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise SourcePackError(f"Studio {method} {path} failed") from exc
        if len(raw) > MAX_REMOTE_BYTES:
            raise SourcePackError(f"Studio {method} {path} response too large")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourcePackError(f"Studio {method} {path} returned invalid JSON") from exc

    def documents(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/v1/studio/documents")
        items = payload.get("documents") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise SourcePackError("Studio document list has unexpected shape")
        return [item for item in items if isinstance(item, dict)]

    def get_or_create_document(self, title: str) -> tuple[dict[str, Any], bool]:
        matches = [item for item in self.documents() if item.get("title") == title]
        if len(matches) > 1:
            raise SourcePackError(f"multiple Studio documents already use title {title!r}")
        if matches:
            return matches[0], False
        payload = self._request(
            "POST",
            "/api/v1/studio/documents",
            body=_json_bytes({"title": title}),
            content_type="application/json",
        )
        doc = payload.get("document") if isinstance(payload, dict) else None
        if not isinstance(doc, dict):
            raise SourcePackError("Studio create-document response has unexpected shape")
        return doc, True

    def upload_revision(self, document_id: str, source: dict[str, Any], raw: bytes) -> dict[str, Any]:
        payload = self._request(
            "POST",
            f"/api/v1/studio/documents/{document_id}/revisions",
            query={
                "filename": source["filename"],
                "language": source["language"],
                "source_label": source["source_label"],
            },
            body=raw,
            content_type="text/plain",
        )
        revision = payload.get("revision") if isinstance(payload, dict) else None
        if not isinstance(revision, dict) or not isinstance(revision.get("revision_id"), str):
            raise SourcePackError("Studio revision response has unexpected shape")
        return revision

    def jobs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._request(
                "GET",
                "/api/v1/studio/jobs",
                query={"limit": "100", "offset": str(offset)},
            )
            items = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise SourcePackError("Studio job list has unexpected shape")
            rows = [item for item in items if isinstance(item, dict)]
            result.extend(rows)
            if len(rows) < 100:
                return result
            offset += len(rows)

    def get_or_create_job(self, revision_id: str) -> tuple[dict[str, Any], bool]:
        matches = [item for item in self.jobs() if item.get("revision_id") == revision_id]
        if matches:
            matches.sort(key=lambda item: str(item.get("created_at") or ""))
            return matches[-1], False
        payload = self._request(
            "POST",
            "/api/v1/studio/jobs",
            body=_json_bytes({"revision_id": revision_id}),
            content_type="application/json",
        )
        job = payload.get("job") if isinstance(payload, dict) else None
        if not isinstance(job, dict) or not isinstance(job.get("job_id"), str):
            raise SourcePackError("Studio create-job response has unexpected shape")
        return job, True


def load_prepared(source_dir: Path) -> dict[str, Any]:
    path = source_dir / "prepared.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourcePackError(f"cannot read prepared pack {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != PREPARED_SCHEMA:
        raise SourcePackError("prepared source pack has unsupported schema")
    if payload.get("version") != PREPARED_VERSION or not isinstance(payload.get("sources"), list):
        raise SourcePackError("prepared source pack has unsupported version/shape")
    return payload


def ingest_prepared(source_dir: Path, client: StudioClient) -> dict[str, Any]:
    prepared = load_prepared(source_dir)
    results: list[dict[str, Any]] = []
    for source in prepared["sources"]:
        if not isinstance(source, dict):
            raise SourcePackError("prepared source entry must be an object")
        raw = (source_dir / source["filename"]).read_bytes()
        actual_sha = _sha256(raw)
        if actual_sha != source.get("sha256") or len(raw) != source.get("bytes"):
            raise SourcePackError(f"prepared source drift for {source.get('key')!r}")
        document, document_created = client.get_or_create_document(source["title"])
        document_id = document.get("document_id")
        if not isinstance(document_id, str):
            raise SourcePackError("Studio document has no document_id")
        revision = client.upload_revision(document_id, source, raw)
        if revision.get("sha256") not in (None, actual_sha) and revision.get("source_sha256") not in (None, actual_sha):
            raise SourcePackError(f"Studio revision hash disagrees for {source['key']!r}")
        revision_id = revision["revision_id"]
        job, job_created = client.get_or_create_job(revision_id)
        results.append(
            {
                "key": source["key"],
                "title": source["title"],
                "source_sha256": actual_sha,
                "document_id": document_id,
                "document_created": document_created,
                "revision_id": revision_id,
                "revision_no": revision.get("revision_no"),
                "revision_duplicate": bool(revision.get("duplicate")),
                "job_id": job.get("job_id"),
                "job_status": job.get("status"),
                "job_created": job_created,
            }
        )
    return {
        "schema": "chronicle.corpus-ingestion-report",
        "version": "0.1",
        "pack_id": prepared.get("pack_id"),
        "prepared_manifest_sha256": prepared.get("manifest_sha256"),
        "sources": results,
    }


def _default_manifest() -> Path:
    return Path(__file__).resolve().parent / "c1-t13" / "source-pack.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle pinned historical source-pack operator")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_cmd = sub.add_parser("prepare", help="fetch pinned source revisions and write deterministic text")
    prepare_cmd.add_argument("--manifest", type=Path, default=_default_manifest())
    prepare_cmd.add_argument("--output-dir", type=Path, required=True)
    prepare_cmd.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)

    ingest_cmd = sub.add_parser("ingest", help="upload prepared text through Studio and queue ingestion jobs")
    ingest_cmd.add_argument("--source-dir", type=Path, required=True)
    ingest_cmd.add_argument("--base-url", default=os.environ.get("CHRONICLE_BASE_URL", "http://127.0.0.1:8080"))
    ingest_cmd.add_argument("--admin-user", default=os.environ.get("CHRONICLE_ADMIN_USER"))
    ingest_cmd.add_argument("--admin-password", default=os.environ.get("CHRONICLE_ADMIN_PASSWORD"))
    ingest_cmd.add_argument("--report", type=Path, default=None)
    ingest_cmd.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        raise SourcePackError("--timeout must be positive")
    if args.command == "prepare":
        manifest = load_manifest(args.manifest)
        report = prepare_pack(manifest, args.output_dir, timeout=args.timeout)
    else:
        client = StudioClient(
            args.base_url,
            args.admin_user or "",
            args.admin_password or "",
            timeout=args.timeout,
        )
        report = ingest_prepared(args.source_dir, client)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SourcePackError as exc:
        print(f"chronicle source pack: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
