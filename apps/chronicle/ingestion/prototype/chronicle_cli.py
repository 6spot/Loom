#!/usr/bin/env python3
"""Unified Chronicle v0.1 ingestion prototype CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from chronicle_ingest import (
    IngestionError,
    RulesV0Extractor,
    compare_bundle,
    dump_json,
    load_yaml,
    validate_bundle,
)
from evaluator_v2 import evaluation_report_v2
from model_v0 import (
    CommandModelProvider,
    ModelV0Error,
    ModelV0Extractor,
    ReplayModelProvider,
    build_model_prompt,
    compare_model_bundle,
    evaluation_report,
)


def _load_inputs(
    fixture: Path, schema_path: Path, config_path: Path | None
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    raw = (fixture / "raw.txt").read_text(encoding="utf-8")
    context = load_yaml(fixture / "context.yaml")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    config = load_yaml(config_path) if config_path is not None else None
    return raw, context, schema, config


def _provider(args: argparse.Namespace):
    if args.model_command:
        return CommandModelProvider(args.model_command, args.model_timeout)
    if args.model_response:
        return ReplayModelProvider(args.model_response)
    raise IngestionError(
        "model-v0 requires exactly one provider: --model-command or --model-response"
    )


def _load_gold(fixture: Path, no_gold: bool) -> dict[str, Any] | None:
    if no_gold:
        return None
    return load_yaml(fixture / "expected.yaml")


def _semantic_missing_count(report: dict[str, Any]) -> int:
    semantic = report.get("semantic_evaluation") or {}
    if not semantic.get("performed"):
        return 0
    return (
        len((semantic.get("entities") or {}).get("missing_gold") or [])
        + len((semantic.get("events") or {}).get("missing_gold") or [])
        + len((semantic.get("claims") or {}).get("missing_gold_evidence") or [])
    )


def _print_v2(report: dict[str, Any]) -> None:
    hard = report["hard_failures"]
    print(
        f"evaluator-v2 hard failures: {hard['count']} ({'PASS' if hard['passed'] else 'FAIL'})",
        file=sys.stderr,
    )
    for category in (
        "schema_validation",
        "grounding",
        "reference_integrity",
        "time_precision",
        "predicate_vocabulary",
        "initial_assessment",
    ):
        for message in hard.get(category) or []:
            print(f"hard/{category}: {message}", file=sys.stderr)

    semantic = report.get("semantic_evaluation") or {}
    if not semantic.get("performed"):
        return
    parts = []
    for collection in ("entities", "events", "claims"):
        data = semantic.get(collection) or {}
        parts.append(
            f"{collection}={data.get('gold_matched')}/{data.get('gold_expected')}"
            f" ({data.get('gold_recall')})"
        )
    print("evaluator-v2 gold recall: " + ", ".join(parts), file=sys.stderr)
    print(
        "evaluator-v2 additional output: "
        f"entities={len((semantic.get('entities') or {}).get('additional_output') or [])}, "
        f"events={len((semantic.get('events') or {}).get('additional_output') or [])}, "
        f"claims={len((semantic.get('claims') or {}).get('additional_output_evidence') or [])}",
        file=sys.stderr,
    )


def _run(args: argparse.Namespace) -> int:
    needs_config = args.extractor == "model-v0"
    if needs_config and args.config is None:
        raise IngestionError("model-v0 requires --config")
    raw, context, schema, config = _load_inputs(args.fixture, args.schema, args.config)

    provider_name = None
    if args.extractor == "rules-v0":
        bundle = RulesV0Extractor(raw, context, args.fixture.name).extract()
    else:
        provider = _provider(args)
        provider_name = provider.name
        assert config is not None
        bundle = ModelV0Extractor(
            raw, context, config, schema, args.fixture.name, provider
        ).extract()

    schema_errors = validate_bundle(bundle, schema)
    expected = _load_gold(args.fixture, args.no_gold)
    dump_json(bundle, args.output)

    if args.extractor == "rules-v0":
        gold_mismatches = (
            compare_bundle(bundle, expected) if expected is not None else None
        )
        if args.report:
            dump_json(
                evaluation_report(
                    bundle,
                    extractor=args.extractor,
                    provider=provider_name,
                    schema_errors=schema_errors,
                    gold_mismatches=gold_mismatches,
                ),
                args.report,
            )
        for message in schema_errors:
            print(f"schema: {message}", file=sys.stderr)
        for message in gold_mismatches or []:
            print(f"gold: {message}", file=sys.stderr)
        if schema_errors or gold_mismatches:
            return 1
        print("chronicle ingestion fixture passed", file=sys.stderr)
        return 0

    assert config is not None
    report = evaluation_report_v2(
        bundle,
        raw,
        config,
        schema_errors=schema_errors,
        expected=expected,
        extractor="model-v0",
        provider=provider_name,
    )
    if args.report:
        dump_json(report, args.report)
    _print_v2(report)
    if not report["hard_failures"]["passed"]:
        return 1
    if args.gold_strict and _semantic_missing_count(report):
        return 1
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    raw, _context, schema, config = _load_inputs(args.fixture, args.schema, args.config)
    assert config is not None
    bundle = json.loads(args.input.read_text(encoding="utf-8"))
    schema_errors = validate_bundle(bundle, schema)
    expected = _load_gold(args.fixture, args.no_gold)
    report = evaluation_report_v2(
        bundle,
        raw,
        config,
        schema_errors=schema_errors,
        expected=expected,
        extractor="model-v0",
        provider="existing-staged-output",
    )
    dump_json(report, args.report)
    _print_v2(report)
    if not report["hard_failures"]["passed"]:
        return 1
    if args.gold_strict and _semantic_missing_count(report):
        return 1
    return 0


def _prompt(args: argparse.Namespace) -> int:
    raw, context, schema, config = _load_inputs(args.fixture, args.schema, args.config)
    assert config is not None
    sys.stdout.write(build_model_prompt(raw, context, config, schema))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle v0.1 ingestion prototype")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="extract, validate, and evaluate a fixture")
    run.add_argument("--fixture", required=True, type=Path)
    run.add_argument("--schema", required=True, type=Path)
    run.add_argument("--config", type=Path)
    run.add_argument("--extractor", choices=["rules-v0", "model-v0"], default="rules-v0")
    providers = run.add_mutually_exclusive_group()
    providers.add_argument(
        "--model-command",
        help="external model command; prompt on stdin, response on stdout",
    )
    providers.add_argument(
        "--model-response",
        type=Path,
        help="replay a captured model response without invoking a provider",
    )
    run.add_argument("--model-timeout", type=int, default=180)
    run.add_argument("--output", type=Path)
    run.add_argument("--report", type=Path)
    run.add_argument("--no-gold", action="store_true")
    run.add_argument(
        "--gold-strict",
        action="store_true",
        help="fail model-v0 when required gold content is missing; extra output is not failure",
    )

    evaluate = commands.add_parser(
        "evaluate", help="evaluate an existing staged model bundle without calling a model"
    )
    evaluate.add_argument("--input", required=True, type=Path)
    evaluate.add_argument("--fixture", required=True, type=Path)
    evaluate.add_argument("--schema", required=True, type=Path)
    evaluate.add_argument("--config", required=True, type=Path)
    evaluate.add_argument("--report", type=Path)
    evaluate.add_argument("--no-gold", action="store_true")
    evaluate.add_argument("--gold-strict", action="store_true")

    prompt = commands.add_parser(
        "prompt", help="render the exact closed-book model-v0 prompt"
    )
    prompt.add_argument("--fixture", required=True, type=Path)
    prompt.add_argument("--schema", required=True, type=Path)
    prompt.add_argument("--config", required=True, type=Path)

    validate = commands.add_parser("validate", help="validate staged JSON")
    validate.add_argument("--input", required=True, type=Path)
    validate.add_argument("--schema", required=True, type=Path)

    compare = commands.add_parser("compare", help="compare staged JSON with human gold")
    compare.add_argument("--input", required=True, type=Path)
    compare.add_argument("--expected", required=True, type=Path)
    compare.add_argument(
        "--model-semantics",
        action="store_true",
        help="use the legacy v0.1 ID-independent exact semantic comparison",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "evaluate":
            return _evaluate(args)
        if args.command == "prompt":
            return _prompt(args)
        if args.command == "validate":
            errors = validate_bundle(
                json.loads(args.input.read_text(encoding="utf-8")),
                json.loads(args.schema.read_text(encoding="utf-8")),
            )
            for message in errors:
                print(message, file=sys.stderr)
            return int(bool(errors))
        if args.command == "compare":
            actual = json.loads(args.input.read_text(encoding="utf-8"))
            expected = load_yaml(args.expected)
            compare = compare_model_bundle if args.model_semantics else compare_bundle
            mismatches = compare(actual, expected)
            for message in mismatches:
                print(message, file=sys.stderr)
            return int(bool(mismatches))
        raise AssertionError(args.command)
    except (IngestionError, ModelV0Error, OSError, json.JSONDecodeError) as exc:
        print(f"chronicle ingestion error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
