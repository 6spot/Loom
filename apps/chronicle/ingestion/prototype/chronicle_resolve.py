#!/usr/bin/env python3
"""Chronicle cross-source resolution/linking CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chronicle_ingest import dump_json, validate_bundle
from model_v0 import CommandModelProvider, ReplayModelProvider
from resolution_v0 import ResolutionV0Error, build_candidate_set, resolve_with_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle cross-source resolution v0.1")
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--left-label", required=True)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--right-label", required=True)
    parser.add_argument("--schema", required=True, type=Path)
    providers = parser.add_mutually_exclusive_group()
    providers.add_argument("--model-command")
    providers.add_argument("--model-response", type=Path)
    parser.add_argument("--model-timeout", type=int, default=180)
    parser.add_argument("--candidates-only", action="store_true")
    parser.add_argument("--candidates-output", type=Path)
    parser.add_argument("--raw-response", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    return parser


def _decision_counts(output: dict) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {"entities": {}, "events": {}}
    for key, collection in (("entities", "entity_links"), ("events", "event_links")):
        for link in output.get(collection) or []:
            decision = link.get("decision")
            if isinstance(decision, str):
                result[key][decision] = result[key].get(decision, 0) + 1
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        left = json.loads(args.left.read_text(encoding="utf-8"))
        right = json.loads(args.right.read_text(encoding="utf-8"))
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        candidates = build_candidate_set(left, args.left_label, right, args.right_label)

        if args.candidates_output:
            dump_json(candidates, args.candidates_output)

        entity_candidate_count = len(candidates["entity_candidates"])
        event_candidate_count = len(candidates["event_candidates"])
        print(
            f"chronicle resolution candidates: entities={entity_candidate_count} events={event_candidate_count}",
            file=sys.stderr,
        )

        if args.candidates_only:
            if args.output:
                dump_json(candidates, args.output)
            return 0

        if not args.model_command and not args.model_response:
            raise ResolutionV0Error(
                "resolution requires --model-command or --model-response unless --candidates-only is used"
            )
        if not args.output:
            raise ResolutionV0Error("resolution requires --output")

        provider = (
            CommandModelProvider(args.model_command, args.model_timeout)
            if args.model_command
            else ReplayModelProvider(args.model_response)
        )
        output, raw_response = resolve_with_provider(candidates, provider)
        if args.raw_response and raw_response:
            args.raw_response.write_text(raw_response, encoding="utf-8")

        schema_errors = validate_bundle(output, schema)
        report = {
            "schema": "chronicle.resolution-run",
            "version": "0.1",
            "provider": provider.name,
            "candidate_counts": {
                "entities": entity_candidate_count,
                "events": event_candidate_count,
            },
            "decision_counts": _decision_counts(output),
            "schema_errors": schema_errors,
            "passed": not schema_errors,
        }
        if args.report:
            dump_json(report, args.report)

        if schema_errors:
            for error in schema_errors:
                print(f"resolution schema: {error}", file=sys.stderr)
            return 1

        dump_json(output, args.output)
        print(
            f"chronicle resolution: PASS decisions={report['decision_counts']}",
            file=sys.stderr,
        )
        return 0
    except (OSError, json.JSONDecodeError, ResolutionV0Error) as exc:
        print(f"chronicle resolution error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
