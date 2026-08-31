#!/usr/bin/env python3
"""Contract-first Chronicle production ingestion prototype.

Production path:
source -> one contract-first extraction -> deterministic validation -> optional
one bounded repair -> deterministic revalidation -> staged output.

Human gold / Evaluator v2 are intentionally outside this command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chronicle_ingest import dump_json, load_yaml, validate_bundle
from contract_v0 import CONTRACT_VERSION, ContractV0Extractor
from model_v0 import CommandModelProvider, ModelV0Error, ReplayModelProvider
from repair_v0 import repair_once
from validator_v0 import flatten_validation_errors, validation_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle contract-first ingestion pipeline")
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    providers = parser.add_mutually_exclusive_group(required=True)
    providers.add_argument("--model-command")
    providers.add_argument("--model-response", type=Path)
    parser.add_argument("--repair-response", type=Path)
    parser.add_argument("--model-timeout", type=int, default=180)
    parser.add_argument("--repair-attempts", type=int, choices=[0, 1], default=1)
    parser.add_argument(
        "--initial-output",
        type=Path,
        help="save the normalized contract extraction before any bounded repair",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--raw-repair-response", type=Path)
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
        raw = (args.fixture / "raw.txt").read_text(encoding="utf-8")
        context = load_yaml(args.fixture / "context.yaml")
        config = load_yaml(args.config)
        schema = json.loads(args.schema.read_text(encoding="utf-8"))

        if args.model_command:
            provider = CommandModelProvider(args.model_command, args.model_timeout)
        else:
            provider = ReplayModelProvider(args.model_response)

        bundle = ContractV0Extractor(
            raw, context, config, schema, args.fixture.name, provider
        ).extract()
        initial_counts = _counts(bundle)
        if args.initial_output:
            dump_json(bundle, args.initial_output)

        initial_validation = _validate(bundle, raw, config, schema)
        final_validation = initial_validation
        repair_meta = {
            "attempted": False,
            "attempts": 0,
            "provider": None,
        }

        if not initial_validation["passed"] and args.repair_attempts == 1:
            if args.model_command:
                repair_provider = provider
            elif args.repair_response:
                repair_provider = ReplayModelProvider(args.repair_response)
            else:
                raise ModelV0Error(
                    "validation failed and repair is enabled; replay extraction requires --repair-response or --repair-attempts 0"
                )

            errors = flatten_validation_errors(initial_validation)
            bundle, raw_repair = repair_once(
                repair_provider,
                raw,
                context,
                config,
                schema,
                bundle,
                errors,
                args.fixture.name,
            )
            if args.raw_repair_response:
                args.raw_repair_response.write_text(raw_repair, encoding="utf-8")
            final_validation = _validate(bundle, raw, config, schema)
            repair_meta = {
                "attempted": True,
                "attempts": 1,
                "provider": repair_provider.name,
                "input_error_count": initial_validation["count"],
            }

        final_counts = _counts(bundle)
        report = {
            "schema": "chronicle.ingestion-run",
            "version": "0.2",
            "extractor": f"contract-v{CONTRACT_VERSION}",
            "provider": provider.name,
            "pipeline": "contract-first-single-extraction-bounded-repair",
            "initial_validation": initial_validation,
            "repair": repair_meta,
            "final_validation": final_validation,
            "initial_counts": initial_counts,
            "counts": final_counts,
        }
        dump_json(bundle, args.output)
        dump_json(report, args.report)

        print(
            f"chronicle validation: initial={initial_validation['count']} "
            f"repair_attempted={repair_meta['attempted']} final={final_validation['count']} "
            f"({'PASS' if final_validation['passed'] else 'FAIL'})",
            file=sys.stderr,
        )
        if repair_meta["attempted"]:
            print(
                f"chronicle counts: initial={initial_counts} final={final_counts}",
                file=sys.stderr,
            )
        if not final_validation["passed"]:
            for error in flatten_validation_errors(final_validation):
                print(f"validation: {error}", file=sys.stderr)
            return 1
        return 0
    except (OSError, json.JSONDecodeError, ModelV0Error) as exc:
        print(f"chronicle pipeline error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
