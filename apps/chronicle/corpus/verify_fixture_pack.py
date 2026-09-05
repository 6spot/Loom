"""Fail-closed verification for Chronicle source-bound development fixtures.

This verifier runs *after* ``source_pack.py prepare``. It proves that every
frozen extraction rule is still an exact substring of the immutable prepared
source bytes it names before any worker is allowed to consume the pack.

It deliberately validates no historical semantics beyond that source binding;
normal C1 extraction/presentation validators remain authoritative for the
fixture provider output itself.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


class FixtureVerificationError(RuntimeError):
    pass


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureVerificationError(f"cannot read {description} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FixtureVerificationError(f"{description} must be a JSON object")
    return payload


def verify(
    *, source_pack_path: Path, fixture_pack_path: Path, prepared_dir: Path
) -> dict[str, Any]:
    source_pack = _load_json(source_pack_path, "source pack")
    fixture_pack = _load_json(fixture_pack_path, "fixture pack")
    if source_pack.get("schema") != "chronicle.corpus-source-pack":
        raise FixtureVerificationError("unsupported source-pack schema")
    if fixture_pack.get("schema") != "chronicle.model-fixture-pack":
        raise FixtureVerificationError("unsupported fixture-pack schema")

    sources = source_pack.get("sources")
    rules = (fixture_pack.get("extraction") or {}).get("rules")
    if not isinstance(sources, list) or not sources:
        raise FixtureVerificationError("source pack has no sources")
    if not isinstance(rules, list) or not rules:
        raise FixtureVerificationError("fixture pack has no extraction rules")

    by_title: dict[str, Path] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise FixtureVerificationError("invalid source-pack entry")
        title = source.get("title")
        filename = source.get("filename")
        if not isinstance(title, str) or not title or not isinstance(filename, str) or not filename:
            raise FixtureVerificationError("source-pack entry requires title/filename")
        by_title[title] = prepared_dir / filename

    missing_documents: list[str] = []
    missing_evidence: list[str] = []
    invalid_mentions: list[str] = []
    counts: Counter[str] = Counter()
    for rule in rules:
        if not isinstance(rule, dict):
            raise FixtureVerificationError("fixture extraction rule must be an object")
        rule_id = str(rule.get("id") or "<missing-id>")
        title = rule.get("document")
        evidence = rule.get("evidence")
        if not isinstance(title, str) or title not in by_title:
            missing_documents.append(rule_id)
            continue
        if not isinstance(evidence, str) or not evidence:
            missing_evidence.append(rule_id)
            continue
        path = by_title[title]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FixtureVerificationError(
                f"cannot read prepared source {path}: {exc}"
            ) from exc
        if evidence not in text:
            missing_evidence.append(rule_id)
            continue

        specs: list[dict[str, Any]] = []
        if isinstance(rule.get("subject"), dict):
            specs.append(rule["subject"])
        obj = rule.get("object")
        if isinstance(obj, dict) and obj.get("kind") == "entity" and isinstance(obj.get("entity"), dict):
            specs.append(obj["entity"])
        for spec in specs:
            mention = spec.get("mention") or spec.get("name")
            if not isinstance(mention, str) or not mention or mention not in evidence:
                invalid_mentions.append(f"{rule_id}:{mention!r}")
        counts[title] += 1

    missing_rule_documents = sorted(set(by_title) - set(counts))
    under_dense = sorted(title for title, count in counts.items() if count < 3)
    errors: list[str] = []
    if missing_documents:
        errors.append("rules name unknown Documents: " + ", ".join(sorted(missing_documents)))
    if missing_evidence:
        errors.append(
            "rules lack exact evidence in pinned prepared bytes: "
            + ", ".join(sorted(missing_evidence))
        )
    if invalid_mentions:
        errors.append("rules have ungrounded mentions: " + ", ".join(sorted(invalid_mentions)))
    if missing_rule_documents:
        errors.append(
            "source Documents have no fixture rules: " + ", ".join(missing_rule_documents)
        )
    if under_dense:
        errors.append(
            "source Documents have fewer than three fixture rules: " + ", ".join(under_dense)
        )
    if errors:
        raise FixtureVerificationError("; ".join(errors))

    return {
        "schema": "chronicle.model-fixture-verification",
        "version": "0.1",
        "model_version": fixture_pack.get("model_version"),
        "documents": len(by_title),
        "rules": len(rules),
        "rules_by_document": dict(sorted(counts.items())),
        "passed": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-pack", type=Path, required=True)
    parser.add_argument("--fixture-pack", type=Path, required=True)
    parser.add_argument("--prepared-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = verify(
            source_pack_path=args.source_pack,
            fixture_pack_path=args.fixture_pack,
            prepared_dir=args.prepared_dir,
        )
    except FixtureVerificationError as exc:
        print(f"chronicle fixture verification: FAIL: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
