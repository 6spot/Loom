#!/usr/bin/env python3
"""Repair an existing Chronicle staged bundle using deterministic validator errors only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chronicle_ingest import dump_json, load_yaml, validate_bundle
from model_v0 import CommandModelProvider, ModelV0Error, ReplayModelProvider
from repair_v0 import repair_once
from validator_v0 import flatten_validation_errors, validation_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chronicle validator-driven patch repair for an existing staged bundle"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    providers = parser.add_mutually_exclusive_group(required=True)
    providers.add_argument("--model-command")
    providers.add_argument("--model-response", type=Path)
    parser.add_argument("--model-timeout", type=int, default=180)
    parser.add_argument("--raw-repair-response", type=Path)
    parser.add_argument("--repair-candidate-output", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser


def _validate(bundle: dict, raw: str, config: dict, schema: dict) -> dict:
    return validation_report(
        bundle,
        raw,
        config,
        schema_errors=validate_bundle(bundle, schema),
    )


def _counts(bundle: dict) -> dict[str, int]:
    return {
        "entities": len(bundle.get("entities") or []),
        "events": len(bundle.get("events") or []),
        "claims": len(bundle.get("claims") or []),
        "warnings": len(bundle.get("warnings") or []),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.output.exists():
            args.output.unlink()

        raw = (args.fixture / "raw.txt").read_text(encoding="utf-8")
        context = load_yaml(args.fixture / "context.yaml")
        config = load_yaml(args.config)
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        initial_bundle = json.loads(args.input.read_text(encoding="utf-8"))
        initial_validation = _validate(initial_bundle, raw, config, schema)

        if initial_validation["passed"]:
            dump_json(initial_bundle, args.output)
            report = {
                "schema": "chronicle.ingestion-repair-run",
                "version": "0.1",
                "provider": None,
                "protocol": "patch-only-v0.2",
                "repair_attempted": False,
                "initial_validation": initial_validation,
                "final_validation": initial_validation,
                "initial_counts": _counts(initial_bundle),
                "candidate_counts": _counts(initial_bundle),
                "output_written": True,
            }
            dump_json(report, args.report)
            print("chronicle repair: input already valid; no repair needed", file=sys.stderr)
            return 0

        if args.model_command:
            provider = CommandModelProvider(args.model_command, args.model_timeout)
        else:
            provider = ReplayModelProvider(args.model_response)

        candidate, raw_response, patch_stats = repair_once(
            provider,
            raw,
            context,
            config,
            schema,
            initial_bundle,
            flatten_validation_errors(initial_validation),
            args.fixture.name,
        )
        if args.raw_repair_response:
            args.raw_repair_response.write_text(raw_response, encoding="utf-8")
        if args.repair_candidate_output:
            dump_json(candidate, args.repair_candidate_output)

        final_validation = _validate(candidate, raw, config, schema)
        output_written = final_validation["passed"]
        if output_written:
            dump_json(candidate, args.output)

        report = {
            "schema": "chronicle.ingestion-repair-run",
            "version": "0.1",
            "provider": provider.name,
            "protocol": patch_stats["protocol"],
            "repair_attempted": True,
            "patch": patch_stats,
            "initial_validation": initial_validation,
            "final_validation": final_validation,
            "initial_counts": _counts(initial_bundle),
            "candidate_counts": _counts(candidate),
            "output_written": output_written,
        }
        dump_json(report, args.report)

        print(
            f"chronicle repair: initial={initial_validation['count']} "
            f"final={final_validation['count']} "
            f"({'PASS' if final_validation['passed'] else 'FAIL'})",
            file=sys.stderr,
        )
        print(
            f"chronicle repair counts: initial={_counts(initial_bundle)} candidate={_counts(candidate)}",
            file=sys.stderr,
        )
        print(
            "chronicle repair patch: "
            f"replaced={patch_stats['replaced']} added={patch_stats['added']} "
            f"removed_warnings={patch_stats['removed_warnings']}",
            file=sys.stderr,
        )
        if not final_validation["passed"]:
            for error in flatten_validation_errors(final_validation):
                print(f"validation: {error}", file=sys.stderr)
            print(
                "chronicle output not written because repair candidate failed revalidation",
                file=sys.stderr,
            )
            return 1
        return 0
    except (OSError, json.JSONDecodeError, ModelV0Error) as exc:
        print(f"chronicle repair error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
