#!/usr/bin/env python3
"""Run Chronicle coverage-v0.2 over an existing model-v0 staged bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chronicle_ingest import dump_json, load_yaml, validate_bundle
from coverage_v02 import CoverageV02Extractor, object_counts
from evaluator_v2 import evaluation_report_v2
from model_v0 import CommandModelProvider, ModelV0Error, ReplayModelProvider


def _semantic_missing_count(report: dict) -> int:
    semantic = report.get("semantic_evaluation") or {}
    if not semantic.get("performed"):
        return 0
    return (
        len((semantic.get("entities") or {}).get("missing_gold") or [])
        + len((semantic.get("events") or {}).get("missing_gold") or [])
        + len((semantic.get("claims") or {}).get("missing_gold_evidence") or [])
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run coverage-v0.2 over an existing Chronicle pass-1 bundle"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    providers = parser.add_mutually_exclusive_group(required=True)
    providers.add_argument("--model-command")
    providers.add_argument("--model-response", type=Path)
    parser.add_argument("--model-timeout", type=int, default=180)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--raw-response",
        type=Path,
        help="save the raw coverage provider response for audit/debugging",
    )
    parser.add_argument("--no-gold", action="store_true")
    parser.add_argument("--gold-strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw = (args.fixture / "raw.txt").read_text(encoding="utf-8")
        context = load_yaml(args.fixture / "context.yaml")
        config = load_yaml(args.config)
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        initial = json.loads(args.input.read_text(encoding="utf-8"))
        provider = (
            CommandModelProvider(args.model_command, args.model_timeout)
            if args.model_command
            else ReplayModelProvider(args.model_response)
        )
        extractor = CoverageV02Extractor(
            raw,
            context,
            config,
            schema,
            args.fixture.name,
            provider,
        )
        final, merge_stats = extractor.review(initial)
        if args.raw_response is not None:
            args.raw_response.write_text(extractor.last_response or "", encoding="utf-8")

        schema_errors = validate_bundle(final, schema)
        expected = None if args.no_gold else load_yaml(args.fixture / "expected.yaml")
        report = evaluation_report_v2(
            final,
            raw,
            config,
            schema_errors=schema_errors,
            expected=expected,
            extractor="model-v0",
            provider=provider.name,
        )
        audit = merge_stats.pop("audit", None)
        report["coverage_pass"] = {
            "performed": True,
            "protocol": "audit+claim-coverage+additions-only",
            "initial_counts": object_counts(initial),
            "final_counts": object_counts(final),
            "audit": audit,
            "merge": merge_stats,
            "input": str(args.input),
            "raw_response": str(args.raw_response) if args.raw_response else None,
        }
        dump_json(final, args.output)
        dump_json(report, args.report)

        hard = report["hard_failures"]
        print(
            f"coverage-v0.2 hard failures: {hard['count']} "
            f"({'PASS' if hard['passed'] else 'FAIL'})",
            file=sys.stderr,
        )
        semantic = report.get("semantic_evaluation") or {}
        if semantic.get("performed"):
            print(
                "coverage-v0.2 gold recall: "
                + ", ".join(
                    f"{name}={(semantic.get(name) or {}).get('gold_matched')}/"
                    f"{(semantic.get(name) or {}).get('gold_expected')} "
                    f"({(semantic.get(name) or {}).get('gold_recall')})"
                    for name in ("entities", "events", "claims")
                ),
                file=sys.stderr,
            )
        print(
            f"coverage-v0.2 counts: {report['coverage_pass']['initial_counts']} -> "
            f"{report['coverage_pass']['final_counts']}",
            file=sys.stderr,
        )
        if audit:
            print(
                "coverage-v0.2 audit: "
                f"units={audit['units']} status_counts={audit['status_counts']} "
                f"gap_units={audit['gap_units']}",
                file=sys.stderr,
            )
            print(
                "coverage-v0.2 claim audit: "
                f"status_counts={audit['claim_status_counts']} "
                f"gap_units={audit['claim_gap_units']}",
                file=sys.stderr,
            )
        print(
            "coverage-v0.2 merge: "
            f"proposed={merge_stats['proposed']} "
            f"added={merge_stats['added']} "
            f"skipped_duplicates={merge_stats['skipped_duplicates']}",
            file=sys.stderr,
        )
        if not hard["passed"]:
            return 1
        if args.gold_strict and _semantic_missing_count(report):
            return 1
        return 0
    except (OSError, json.JSONDecodeError, ModelV0Error) as exc:
        print(f"chronicle coverage error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
