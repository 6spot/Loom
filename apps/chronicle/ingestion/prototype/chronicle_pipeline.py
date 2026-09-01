#!/usr/bin/env python3
"""Contract-first Chronicle production ingestion prototype.

Production path:
source -> one contract-first extraction -> deterministic validation -> optional
one bounded patch repair -> deterministic revalidation -> staged output.

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
    parser.add_argument(
        "--repair-candidate-output",
        type=Path,
        help="save the complete deterministic repair candidate even when it fails revalidation",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--raw-repair-response",
        type=Path,
        help="save the raw model repair patch response",
    )
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
        # Never leave a stale prior success at the requested output path when this run fails.
        if args.output.exists():
            args.output.unlink()

        raw = (args.fixture / "raw.txt").read_text(encoding="utf-8")
        context = load_yaml(args.fixture / "context.yaml")
        config = load_yaml(args.config)
        schema = json.loads(args.schema.read_text(encoding="utf-8"))

        if args.model_command:
            provider = CommandModelProvider(args.model_command, args.model_timeout)
        else:
            provider = ReplayModelProvider(args.model_response)

        initial_bundle = ContractV0Extractor(
            raw, context, config, schema, args.fixture.name, provider
        ).extract()
        initial_counts = _counts(initial_bundle)
        if args.initial_output:
            dump_json(initial_bundle, args.initial_output)

        initial_validation = _validate(initial_bundle, raw, config, schema)
        final_bundle = initial_bundle
        final_validation = initial_validation
        repair_meta = {
            "attempted": False,
            "attempts": 0,
            "provider": None,
            "accepted": False,
            "protocol": None,
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
            candidate_bundle, raw_repair, patch_stats = repair_once(
                repair_provider,
                raw,
                context,
                config,
                schema,
                initial_bundle,
                errors,
                args.fixture.name,
            )
            if args.raw_repair_response:
                args.raw_repair_response.write_text(raw_repair, encoding="utf-8")
            if args.repair_candidate_output:
                dump_json(candidate_bundle, args.repair_candidate_output)

            candidate_validation = _validate(candidate_bundle, raw, config, schema)
            final_validation = candidate_validation
            repair_meta = {
                "attempted": True,
                "attempts": 1,
                "provider": repair_provider.name,
                "input_error_count": initial_validation["count"],
                "accepted": candidate_validation["passed"],
                "protocol": patch_stats["protocol"],
                "patch": patch_stats,
                "candidate_counts": _counts(candidate_bundle),
            }
            if candidate_validation["passed"]:
                final_bundle = candidate_bundle

        output_written = final_validation["passed"]
        if output_written:
            dump_json(final_bundle, args.output)

        report = {
            "schema": "chronicle.ingestion-run",
            "version": "0.3",
            "extractor": f"contract-v{CONTRACT_VERSION}",
            "provider": provider.name,
            "pipeline": "contract-first-single-extraction-bounded-patch-repair",
            "initial_validation": initial_validation,
            "repair": repair_meta,
            "final_validation": final_validation,
            "initial_counts": initial_counts,
            "counts": _counts(final_bundle) if output_written else None,
            "output_written": output_written,
        }
        dump_json(report, args.report)

        print(
            f"chronicle validation: initial={initial_validation['count']} "
            f"repair_attempted={repair_meta['attempted']} "
            f"repair_accepted={repair_meta['accepted']} "
            f"final={final_validation['count']} "
            f"({'PASS' if final_validation['passed'] else 'FAIL'})",
            file=sys.stderr,
        )
        if repair_meta["attempted"]:
            print(
                f"chronicle counts: initial={initial_counts} "
                f"candidate={repair_meta['candidate_counts']} "
                f"output={_counts(final_bundle) if output_written else None}",
                file=sys.stderr,
            )
            print(
                "chronicle repair patch: "
                f"replaced={repair_meta['patch']['replaced']} "
                f"added={repair_meta['patch']['added']} "
                f"removed_warnings={repair_meta['patch']['removed_warnings']}",
                file=sys.stderr,
            )
        if not final_validation["passed"]:
            for error in flatten_validation_errors(final_validation):
                print(f"validation: {error}", file=sys.stderr)
            print(
                "chronicle output not written because final validation failed",
                file=sys.stderr,
            )
            return 1
        return 0
    except (OSError, json.JSONDecodeError, ModelV0Error) as exc:
        print(f"chronicle pipeline error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
