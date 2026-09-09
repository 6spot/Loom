#!/usr/bin/env python3
"""Persist accepted Chronicle staged/resolution/canonical artifacts to PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from jsonschema import Draft202012Validator, FormatChecker

from common import PersistenceError, load_json
from migrations import apply_migrations
from postgres_v0 import persist_to_url


HERE = Path(__file__).resolve().parent
CHRONICLE_ROOT = HERE.parent
DEFAULT_STAGED_SCHEMA = CHRONICLE_ROOT / "ingestion/schemas/chronicle-v0.1.schema.json"
DEFAULT_RESOLUTION_SCHEMA = CHRONICLE_ROOT / "ingestion/schemas/chronicle-resolution-v0.1.schema.json"
DEFAULT_CANONICAL_SCHEMA = CHRONICLE_ROOT / "ingestion/schemas/chronicle-canonical-v0.1.schema.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle PostgreSQL persistence v0")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CHRONICLE_DATABASE_URL"),
        help="Chronicle-owned PostgreSQL URL; defaults to CHRONICLE_DATABASE_URL",
    )
    parser.add_argument(
        "--bundle",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="staged bundle; repeat for each source",
    )
    parser.add_argument(
        "--resolution",
        action="append",
        default=[],
        type=Path,
        help="accepted Resolution Links artifact; may be repeated",
    )
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--staged-schema", type=Path, default=DEFAULT_STAGED_SCHEMA)
    parser.add_argument("--resolution-schema", type=Path, default=DEFAULT_RESOLUTION_SCHEMA)
    parser.add_argument("--canonical-schema", type=Path, default=DEFAULT_CANONICAL_SCHEMA)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--migrate-only",
        action="store_true",
        help=(
            "apply Chronicle schema migrations and report applied versions "
            "without importing any staged/resolution/canonical artifacts; "
            "mutually exclusive with --bundle/--resolution/--catalog"
        ),
    )
    return parser


def _parse_bundles(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise PersistenceError(f"--bundle must use LABEL=PATH, got {value!r}")
        label, raw_path = value.split("=", 1)
        label = label.strip()
        raw_path = raw_path.strip()
        if not label or not raw_path:
            raise PersistenceError(f"--bundle must use non-empty LABEL=PATH, got {value!r}")
        if label in result:
            raise PersistenceError(f"duplicate --bundle label {label!r}")
        result[label] = Path(raw_path)
    if not result:
        raise PersistenceError("at least one --bundle LABEL=PATH is required")
    return result


def _validate(value: dict[str, Any], schema: dict[str, Any], description: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if not errors:
        return
    messages = []
    for error in errors:
        where = "/".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{where}: {error.message}")
    raise PersistenceError(f"{description} failed schema validation: " + "; ".join(messages))


def _dump_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrate_only_to_url(database_url: str) -> list[dict[str, str]]:
    """Apply Chronicle migrations and return applied schema versions.

    This is the canonical migration-only entry point: it reuses the existing
    migration runner, imports no staged/resolution/canonical artifacts, and
    reports only schema results. Re-running against an already-migrated
    database is a no-op returning the recorded versions.
    """
    if not database_url:
        raise PersistenceError("database URL is empty")
    try:
        with psycopg.connect(database_url) as conn:
            apply_migrations(conn)
            rows = conn.execute(
                "SELECT version, checksum FROM chronicle.schema_migrations ORDER BY version"
            ).fetchall()
    except PersistenceError:
        raise
    except psycopg.Error as exc:
        raise PersistenceError(f"Chronicle migration failed: {exc}") from exc
    return [{"version": str(version), "checksum": str(checksum)} for version, checksum in rows]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.database_url:
            raise PersistenceError(
                "Chronicle database URL is required via --database-url or CHRONICLE_DATABASE_URL"
            )
        if args.migrate_only:
            conflicting = []
            if args.bundle:
                conflicting.append("--bundle")
            if args.resolution:
                conflicting.append("--resolution")
            if args.catalog is not None:
                conflicting.append("--catalog")
            if conflicting:
                raise PersistenceError(
                    "--migrate-only cannot be combined with "
                    + ", ".join(conflicting)
                )
            migrations = migrate_only_to_url(args.database_url)
            report = {
                "schema": "chronicle.migration-run",
                "version": "0.1",
                "passed": True,
                "migrations": migrations,
            }
            if args.report:
                _dump_report(report, args.report)
            print(
                "chronicle migrate: PASS "
                f"migrations={len(migrations)} "
                f"versions={[entry['version'] for entry in migrations]}",
                file=sys.stderr,
            )
            return 0
        if args.catalog is None:
            raise PersistenceError("--catalog is required unless --migrate-only is used")
        bundle_paths = _parse_bundles(args.bundle)
        bundles = {label: load_json(path) for label, path in bundle_paths.items()}
        resolutions = [load_json(path) for path in args.resolution]
        catalog = load_json(args.catalog)

        staged_schema = load_json(args.staged_schema)
        resolution_schema = load_json(args.resolution_schema)
        canonical_schema = load_json(args.canonical_schema)
        for label, bundle in bundles.items():
            _validate(bundle, staged_schema, f"bundle {label!r}")
        for index, resolution in enumerate(resolutions):
            _validate(resolution, resolution_schema, f"resolution[{index}]")
        _validate(catalog, canonical_schema, "canonical catalog")

        result = persist_to_url(
            args.database_url,
            bundles=bundles,
            resolutions=resolutions,
            catalog=catalog,
        )
        report = {
            "schema": "chronicle.persistence-run",
            "version": "0.1",
            "passed": True,
            **result.as_dict(),
        }
        if args.report:
            _dump_report(report, args.report)
        totals = result.totals
        print(
            "chronicle persistence: PASS "
            f"import_created={str(result.import_created).lower()} "
            f"bundles={totals['source_bundles']} "
            f"entities={totals['canonical_entities']} "
            f"events={totals['canonical_events']} "
            f"relations={totals['canonical_event_relations']}",
            file=sys.stderr,
        )
        return 0
    except PersistenceError as exc:
        print(f"chronicle persistence error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
