#!/usr/bin/env python3
"""Persist accepted Chronicle staged/resolution/canonical artifacts to PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from common import PersistenceError, load_json
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
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--staged-schema", type=Path, default=DEFAULT_STAGED_SCHEMA)
    parser.add_argument("--resolution-schema", type=Path, default=DEFAULT_RESOLUTION_SCHEMA)
    parser.add_argument("--canonical-schema", type=Path, default=DEFAULT_CANONICAL_SCHEMA)
    parser.add_argument("--report", type=Path)
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.database_url:
            raise PersistenceError(
                "Chronicle database URL is required via --database-url or CHRONICLE_DATABASE_URL"
            )
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
