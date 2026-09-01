#!/usr/bin/env python3
"""Chronicle canonical publication CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chronicle_ingest import dump_json, validate_bundle
from publication_v0 import PublicationV0Error, publish_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle canonical publication v0.1")
    parser.add_argument(
        "--bundle",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="staged bundle input; repeat for each source bundle",
    )
    parser.add_argument(
        "--resolution",
        action="append",
        default=[],
        type=Path,
        help="resolution-links JSON input; may be repeated",
    )
    parser.add_argument("--existing-catalog", type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    return parser


def _parse_bundle_args(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise PublicationV0Error(f"--bundle must use LABEL=PATH, got {value!r}")
        label, raw_path = value.split("=", 1)
        label = label.strip()
        raw_path = raw_path.strip()
        if not label or not raw_path:
            raise PublicationV0Error(f"--bundle must use non-empty LABEL=PATH, got {value!r}")
        if label in result:
            raise PublicationV0Error(f"duplicate --bundle label {label!r}")
        result[label] = Path(raw_path)
    if not result:
        raise PublicationV0Error("publication requires at least one --bundle LABEL=PATH")
    return result


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicationV0Error(f"{path} must contain one JSON object")
    return value


def _catalog_ids(catalog: dict | None, field: str) -> set[str]:
    if catalog is None:
        return set()
    return {
        record["canonical_id"]
        for record in catalog.get(field) or []
        if isinstance(record, dict) and isinstance(record.get("canonical_id"), str)
    }


def _representation_count(catalog: dict, field: str) -> int:
    return sum(len(record.get("representations") or []) for record in catalog.get(field) or [])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle_paths = _parse_bundle_args(args.bundle)
        bundles = {label: _load_json(path) for label, path in bundle_paths.items()}
        resolutions = [_load_json(path) for path in args.resolution]
        schema = _load_json(args.schema)
        existing = _load_json(args.existing_catalog) if args.existing_catalog else None

        if existing is not None:
            existing_schema_errors = validate_bundle(existing, schema)
            if existing_schema_errors:
                raise PublicationV0Error(
                    "existing catalog failed canonical schema validation: "
                    + "; ".join(existing_schema_errors)
                )

        catalog = publish_catalog(bundles, resolutions, existing_catalog=existing)
        schema_errors = validate_bundle(catalog, schema)

        existing_entity_ids = _catalog_ids(existing, "canonical_entities")
        existing_event_ids = _catalog_ids(existing, "canonical_events")
        entity_ids = _catalog_ids(catalog, "canonical_entities")
        event_ids = _catalog_ids(catalog, "canonical_events")
        report = {
            "schema": "chronicle.publication-run",
            "version": "0.1",
            "bundles": sorted(bundles),
            "resolution_count": len(resolutions),
            "existing_catalog": existing is not None,
            "canonical_counts": {
                "entities": len(catalog["canonical_entities"]),
                "events": len(catalog["canonical_events"]),
                "event_relations": len(catalog["event_relations"]),
            },
            "representation_counts": {
                "entities": _representation_count(catalog, "canonical_entities"),
                "events": _representation_count(catalog, "canonical_events"),
            },
            "identity_counts": {
                "reused_entities": len(entity_ids & existing_entity_ids),
                "new_entities": len(entity_ids - existing_entity_ids),
                "reused_events": len(event_ids & existing_event_ids),
                "new_events": len(event_ids - existing_event_ids),
            },
            "schema_errors": schema_errors,
            "passed": not schema_errors,
        }
        if args.report:
            dump_json(report, args.report)
        if schema_errors:
            for error in schema_errors:
                print(f"publication schema: {error}", file=sys.stderr)
            return 1

        dump_json(catalog, args.output)
        print(
            "chronicle publication: PASS "
            f"entities={report['canonical_counts']['entities']} "
            f"events={report['canonical_counts']['events']} "
            f"relations={report['canonical_counts']['event_relations']}",
            file=sys.stderr,
        )
        return 0
    except (OSError, json.JSONDecodeError, PublicationV0Error) as exc:
        print(f"chronicle publication error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
