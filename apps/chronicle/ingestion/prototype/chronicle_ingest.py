#!/usr/bin/env python3
"""Chronicle v0.1 ingestion prototype.

`rules-v0` is deliberately fixture-scoped. It proves the stable pipeline around
an extractor: raw + document context -> staged bundle -> JSON Schema validation
-> semantic comparison with human gold. A model-backed extractor can replace
`RulesV0Extractor` later without changing those downstream steps.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


class IngestionError(RuntimeError):
    pass


ENTITY_SPECS = [
    ("曹操", "person", [("公", True)]),
    ("刘表", "person", [("刘表", False), ("表", True)]),
    ("刘琮", "person", [("琮", True)]),
    ("刘备", "person", [("刘备", False), ("备", True)]),
    ("孙权", "person", [("孙权", False), ("权", True)]),
    ("文聘", "person", [("文聘", False)]),
    ("张憙", "person", [("张憙", False)]),
    ("新野", "place", [("新野", False)]),
    ("夏口", "place", [("夏口", False)]),
    ("江陵", "place", [("江陵", False)]),
    ("合肥", "place", [("合肥", False)]),
    ("赤壁", "place", [("赤壁", False)]),
    ("荆州", "place", [("荆州", False)]),
    ("江南", "place", [("江南", False)]),
    ("江夏", "place", [("江夏", False)]),
]

EVENT_SPECS = [
    ("appointment", "曹操被任命为丞相", "june", [("曹操", "appointee")], []),
    ("military", "曹操南征刘表", "july", [("曹操", "attacker"), ("刘表", "target")], []),
    ("death", "刘表去世", "august", [("刘表", "subject")], []),
    ("succession", "刘琮继承刘表", "august", [("刘琮", "successor"), ("刘表", "predecessor")], []),
    ("surrender", "刘琮向曹操投降", "september", [("刘琮", "surrendering_party"), ("曹操", "recipient")], []),
    ("movement", "刘备退往夏口", "september", [("刘备", "actor")], ["夏口"]),
    ("appointment", "文聘被任命为江夏太守", "september_inherited_month", [("文聘", "appointee")], ["江夏"]),
    ("military", "孙权攻合肥", "december", [("孙权", "attacker")], ["合肥"]),
    ("battle", "曹操与刘备在赤壁交战失利", "december_battle", [("曹操", "combatant"), ("刘备", "combatant")], ["赤壁"]),
    ("epidemic", "曹操军发生大疫", "epidemic", [("曹操", "affected_side")], []),
    ("movement", "曹操撤军", "retreat", [("曹操", "actor")], []),
    ("territorial_change", "刘备取得荆州、江南诸郡", "territorial", [("刘备", "beneficiary")], ["荆州", "江南"]),
]

CLAIM_SPECS = [
    ("entity", "曹操", "held_office", ("literal", "丞相"), "夏六月，以公为丞相。", "june"),
    ("entity", "刘表", "died", None, "八月，表卒", "august"),
    ("entity", "刘琮", "succeeded", ("entity", "刘表"), "其子琮代", "august"),
    ("entity", "刘琮", "surrendered_to", ("entity", "曹操"), "琮遂降", "september"),
    ("entity", "孙权", "attacked", ("entity", "合肥"), "十二月，孙权为备攻合肥。", "december"),
    ("event", "evt_009", "outcome", ("literal", "曹操军不利"), "公至赤壁，与备战，不利。", "december_battle"),
    ("event", "evt_010", "affected", ("literal", "吏士多死"), "于是大疫，吏士多死者", "epidemic"),
    ("entity", "刘备", "gained_territory", ("entity", "荆州"), "备遂有荆州、江南诸郡。", "territorial"),
    ("entity", "刘备", "gained_territory", ("entity", "江南"), "备遂有荆州、江南诸郡。", "territorial"),
]


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def dump_json(value: Any, path: Path | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        sys.stdout.write(text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def validate_bundle(bundle: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(bundle), key=lambda error: list(error.absolute_path))
    result = []
    for error in errors:
        where = "/".join(str(part) for part in error.absolute_path) or "$"
        result.append(f"{where}: {error.message}")
    return result


def semantic_view(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: semantic_view(child) for key, child in value.items() if key not in {"extraction", "warnings"}}
    if isinstance(value, list):
        return [semantic_view(child) for child in value]
    return value


def compare_bundle(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Compare stable semantics while ignoring extractor diagnostics."""
    mismatches: list[str] = []
    if semantic_view(actual.get("source")) != semantic_view(expected.get("source")):
        mismatches.append("source differs from human gold")

    for collection, key in (("entities", "canonical_name"), ("events", "title")):
        left = {item[key]: semantic_view(item) for item in actual.get(collection, [])}
        right = {item[key]: semantic_view(item) for item in expected.get(collection, [])}
        for name in sorted(right.keys() - left.keys()):
            mismatches.append(f"{collection}: missing {name}")
        for name in sorted(left.keys() - right.keys()):
            mismatches.append(f"{collection}: unexpected {name}")
        for name in sorted(left.keys() & right.keys()):
            if left[name] != right[name]:
                mismatches.append(f"{collection}: {name} differs")

    def claim_key(item: dict[str, Any]) -> str:
        identity = {
            "subject": item.get("subject"),
            "predicate": item.get("predicate"),
            "object": item.get("object"),
            "evidence": (item.get("evidence") or {}).get("text"),
        }
        return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    left = {claim_key(item): semantic_view(item) for item in actual.get("claims", [])}
    right = {claim_key(item): semantic_view(item) for item in expected.get("claims", [])}
    for key in sorted(right.keys() - left.keys()):
        mismatches.append(f"claims: missing {key}")
    for key in sorted(left.keys() - right.keys()):
        mismatches.append(f"claims: unexpected {key}")
    for key in sorted(left.keys() & right.keys()):
        if left[key] != right[key]:
            mismatches.append(f"claims: {key} differs")
    return mismatches


class RulesV0Extractor:
    """Fixture-specific deterministic extractor used only as a V0 harness."""

    def __init__(self, raw: str, context: dict[str, Any], fixture_name: str):
        self.raw = raw
        self.context = context
        self.fixture_name = fixture_name
        chronology = context["chronology"]
        self.era = chronology["default_era"]
        self.era_year = int(chronology["current_era_year"])
        self.year = int(chronology["normalized_year"])
        self.calendar = chronology["source_calendar"]
        self.entity_ids: dict[str, str] = {}

    def _check_input(self) -> None:
        anchors = ("十三年春正月", "夏六月，以公为丞相", "秋七月，公南征刘表", "公至赤壁，与备战，不利")
        missing = [anchor for anchor in anchors if anchor not in self.raw]
        if missing:
            raise IngestionError(f"rules-v0 input is missing fixture anchors: {', '.join(missing)}")
        if self.context.get("schema") != "chronicle.document-context" or self.context.get("version") != "0.1":
            raise IngestionError("rules-v0 requires chronicle.document-context v0.1")
        if self.context["narrative"]["primary_subject"]["canonical_name"] != "曹操":
            raise IngestionError("rules-v0 fixture expects 曹操 as primary subject")

    def _time(self, original: str, season: str | None, month: int | None, inherited: list[str]) -> dict[str, Any]:
        source = {"system": self.calendar, "era": self.era, "era_year": self.era_year, "inherited_fields": inherited}
        if season is not None:
            source["season"] = season
        if month is not None:
            source["month"] = month
        return {
            "original_text": original,
            "source_calendar": source,
            "normalized": {"calendar": "proleptic_gregorian", "year": self.year, "precision": "year", "conversion_status": "year_only"},
        }

    def _times(self) -> dict[str, dict[str, Any]]:
        return {
            "june": self._time("夏六月", "summer", 6, ["era", "era_year"]),
            "july": self._time("秋七月", "autumn", 7, ["era", "era_year"]),
            "august": self._time("八月", "autumn", 8, ["era", "era_year", "season"]),
            "september": self._time("九月", "autumn", 9, ["era", "era_year", "season"]),
            "september_inherited_month": self._time("九月", "autumn", 9, ["era", "era_year", "season", "month"]),
            "december": self._time("十二月", "winter", 12, ["era", "era_year"]),
            "december_battle": self._time("十二月", "winter", 12, ["era", "era_year", "season"]),
            "epidemic": self._time("于是", None, None, ["era", "era_year"]),
            "retreat": self._time("乃引军还", None, None, ["era", "era_year"]),
            "territorial": self._time("遂", None, None, ["era", "era_year"]),
        }

    def _entities(self) -> list[dict[str, Any]]:
        entities = []
        primary = self.context["narrative"]["primary_subject"]["canonical_name"]
        for name, entity_type, mentions in ENTITY_SPECS:
            found = [{"text": text, "contextual": contextual} for text, contextual in mentions if text in self.raw or (name == primary and contextual)]
            if not found:
                continue
            temp_id = f"ent_{len(entities) + 1:03d}"
            self.entity_ids[name] = temp_id
            entities.append({
                "temp_id": temp_id, "kind": "entity", "type": entity_type,
                "canonical_name": name, "aliases": [], "mentions": found,
                "resolution": {"status": "unresolved"},
                "extraction": {"method": "parser", "job_id": "rules-v0", "confidence": None},
            })
        return entities

    def _ref(self, name: str) -> dict[str, Any]:
        return {"kind": "entity_ref", "ref": self.entity_ids[name]}

    def _object(self, spec: tuple[str, Any] | None) -> dict[str, Any] | None:
        if spec is None:
            return None
        kind, value = spec
        return self._ref(value) if kind == "entity" else {"kind": "literal", "value": value}

    def extract(self) -> dict[str, Any]:
        self._check_input()
        entities = self._entities()
        times = self._times()
        events = []
        for event_type, title, time_key, participants, places in EVENT_SPECS:
            events.append({
                "temp_id": f"evt_{len(events) + 1:03d}", "kind": "event", "type": event_type,
                "title": title, "time": copy.deepcopy(times[time_key]),
                "participants": [{"entity_ref": self.entity_ids[name], "role": role} for name, role in participants],
                "places": [self.entity_ids[name] for name in places],
                "extraction": {"method": "parser", "job_id": "rules-v0", "confidence": None},
            })

        title = self.context["source"]["title"]
        section = title.split("·", 1)[1]
        claims = []
        for subject_kind, subject_value, predicate, object_spec, evidence, time_key in CLAIM_SPECS:
            subject = self._ref(subject_value) if subject_kind == "entity" else {"kind": "event_ref", "ref": subject_value}
            claims.append({
                "temp_id": f"clm_{len(claims) + 1:03d}", "kind": "claim", "subject": subject,
                "predicate": predicate, "object": self._object(object_spec), "time": copy.deepcopy(times[time_key]),
                "evidence": {"text": evidence, "source_ref": "src_001", "locator": {"work": self.context["source"].get("work"), "section": section, "fixture": self.fixture_name}},
                "assessment": {"status": "unassessed"},
                "extraction": {"method": "parser", "job_id": "rules-v0", "confidence": None},
            })

        source = {
            "temp_id": "src_001", "kind": "source", "source_type": "book", "title": title,
            "author": self.context["source"].get("author"), "language": self.context["source"]["language"],
            "metadata": {"work": self.context["source"].get("work"), "section": section, "fixture": self.fixture_name},
            "extraction": {"method": "parser", "job_id": "rules-v0", "confidence": None},
        }
        warnings = [
            {"type": "baseline_extractor", "severity": "info", "message": "rules-v0 is fixture-scoped and is not a general historical extractor", "refs": []},
            {"type": "time_precision", "severity": "info", "message": f"traditional months were preserved; only {self.era}{self.era_year}年 was normalized to {self.year}", "refs": [event["temp_id"] for event in events]},
        ]
        return {"schema_version": "0.1", "source": source, "entities": entities, "events": events, "claims": claims, "warnings": warnings}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chronicle v0.1 ingestion prototype")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="extract, validate and compare a committed fixture")
    run.add_argument("--fixture", required=True, type=Path)
    run.add_argument("--schema", required=True, type=Path)
    run.add_argument("--output", type=Path)
    run.add_argument("--no-gold", action="store_true")
    validate = commands.add_parser("validate", help="validate staged JSON")
    validate.add_argument("--input", required=True, type=Path)
    validate.add_argument("--schema", required=True, type=Path)
    compare = commands.add_parser("compare", help="compare staged JSON with human gold YAML")
    compare.add_argument("--input", required=True, type=Path)
    compare.add_argument("--expected", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        raw = (args.fixture / "raw.txt").read_text(encoding="utf-8")
        bundle = RulesV0Extractor(raw, load_yaml(args.fixture / "context.yaml"), args.fixture.name).extract()
        errors = validate_bundle(bundle, json.loads(args.schema.read_text(encoding="utf-8")))
        mismatches = [] if args.no_gold else compare_bundle(bundle, load_yaml(args.fixture / "expected.yaml"))
        dump_json(bundle, args.output)
        for message in errors:
            print(f"schema: {message}", file=sys.stderr)
        for message in mismatches:
            print(f"gold: {message}", file=sys.stderr)
        if errors or mismatches:
            return 1
        print("chronicle ingestion fixture passed", file=sys.stderr)
        return 0
    if args.command == "validate":
        errors = validate_bundle(json.loads(args.input.read_text(encoding="utf-8")), json.loads(args.schema.read_text(encoding="utf-8")))
        for message in errors:
            print(message, file=sys.stderr)
        return int(bool(errors))
    if args.command == "compare":
        mismatches = compare_bundle(json.loads(args.input.read_text(encoding="utf-8")), load_yaml(args.expected))
        for message in mismatches:
            print(message, file=sys.stderr)
        return int(bool(mismatches))
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
