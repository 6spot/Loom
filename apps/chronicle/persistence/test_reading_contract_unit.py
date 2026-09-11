"""Unit tests for the Chronicle C2-R2-T01 reading contract (no PostgreSQL).

Covers the second-round machine contract from continuous-reading.md
sections 2-3 and 5-7: 0.2 candidate reading coverage/reference/time/span
validation with first-round semantics reused verbatim, translation
code-point span resolution (repeated words and astral-plane CJK),
program acceptance (unit IDs, resolved spans, segments), narrative-time
axis grouping, public DTOs and their TypeScript mirror. Pure functions
only: no DB, network, or model calls.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import chapter_contract as C  # noqa: E402
import reading_contract as R  # noqa: E402
from common import PersistenceError  # noqa: E402

FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r2-contract"
READING_TYPES = HERE.parent / "webapp" / "src" / "lib" / "reading-types.ts"

STREAM_ID = "0192f0a0-0000-7000-8000-00000000aa01"
CATALOG_SHA = "a" * 64
PUBLICATION_ID = "0192f0a0-0000-7000-8000-00000000bb02"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def base() -> tuple[dict, dict]:
    return load("request.json"), load("candidate-valid.json")


def assert_rejected(test: unittest.TestCase, report: dict, category: str) -> None:
    test.assertFalse(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
    test.assertTrue(
        report["errors"].get(category),
        f"expected {category} errors, got {json.dumps(report['errors'], ensure_ascii=False)}",
    )


def observation(
    original_text: str,
    *,
    calendar: dict | None = None,
    normalized: dict | None = None,
    precision: str = "year",
) -> dict:
    return R.example_time_observation(
        original_text=original_text,
        source_calendar=calendar,
        normalized=normalized,
        precision=precision,
    )


REG = {
    "system": "chinese_lunisolar_regnal",
    "era": "建安",
    "era_year": 13,
    "season": None,
    "month": None,
    "day": None,
}


def regnal(*, month: int | None = None, era_year: int = 13) -> dict:
    calendar = dict(REG)
    calendar["month"] = month
    calendar["era_year"] = era_year
    return calendar


def gregorian(*, year: int, month: int | None = None) -> tuple[dict, dict, str]:
    calendar = {"system": "proleptic_gregorian"}
    normalized = {
        "calendar": "proleptic_gregorian",
        "year": year,
        "month": month,
        "day": None,
        "precision": "month" if month is not None else "year",
        "conversion_status": "exact" if month is not None else "year_only",
        "approximate": False,
    }
    return calendar, normalized, "month" if month is not None else "year"


def make_unit(ordinal: int, time_observation: dict, *, mode: str = "events") -> dict:
    unit_id = f"ru_{ordinal:024x}"
    narrative = R.narrative_time_display(mode, [time_observation])
    return {
        "unit_id": unit_id,
        "ordinal": ordinal,
        "locator": {"stream_id": STREAM_ID, "catalog_sha": CATALOG_SHA, "unit_id": unit_id},
        "narrative_time": narrative,
    }


class ReadingLimitsTests(unittest.TestCase):
    def test_defaults_match_contract_envelope(self) -> None:
        limits = R.ReadingLimits()
        self.assertEqual(limits.max_block_code_points, 8192)
        self.assertEqual(limits.max_event_spans, 64)
        self.assertEqual(limits.max_context_entities, 128)
        self.assertEqual((limits.min_source_selections, limits.max_source_selections), (1, 16))
        self.assertEqual((limits.page_min_limit, limits.page_max_limit), (1, 50))
        self.assertEqual(limits.group_max_limit, 100)
        self.assertEqual(limits.page_max_bytes, 2 * 1024 * 1024)
        self.assertEqual(limits.unit_max_bytes, 256 * 1024)
        self.assertEqual(limits.preview_max_bytes, 64 * 1024)
        self.assertEqual(limits.preview_max_sources, 8)
        self.assertEqual(limits.preview_excerpt_code_points, 160)


class ReadingCandidateTests(unittest.TestCase):
    def test_valid_candidate_passes_without_chapter_regression(self) -> None:
        request, candidate = base()
        report = R.validate_reading_annotations(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        self.assertEqual(report["errors"]["chapter"], [])
        subset = {k: v for k, v in candidate.items() if k != "reading"} | {"version": "0.1"}
        self.assertTrue(C.validate_chapter_candidate(request, subset)["passed"])

    def test_missing_block_annotation_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-missing-unit.json")
        assert_rejected(
            self, R.validate_reading_annotations(request, candidate), "reading_coverage"
        )

    def test_unknown_event_ref_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-unknown-ref.json")
        assert_rejected(self, R.validate_reading_annotations(request, candidate), "reading_refs")

    def test_cross_chapter_inheritance_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-inherit-cross-chapter.json")
        report = R.validate_reading_annotations(request, candidate)
        assert_rejected(self, report, "reading_time")
        self.assertTrue(
            any("cross-chapter" in message for message in report["errors"]["reading_time"]),
            report["errors"]["reading_time"],
        )

    def test_inheritance_cycle_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-inherit-cycle.json")
        assert_rejected(self, R.validate_reading_annotations(request, candidate), "reading_time")

    def test_retrospective_event_cannot_be_current_time_basis(self) -> None:
        request, _ = base()
        candidate = load("candidate-retrospective-as-time.json")
        assert_rejected(self, R.validate_reading_annotations(request, candidate), "reading_time")

    def test_forged_event_role_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-forged-role.json")
        assert_rejected(self, R.validate_reading_annotations(request, candidate), "reading_context")

    def test_canonical_id_from_model_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-canonical-id.json")
        assert_rejected(self, R.validate_reading_annotations(request, candidate), "canonical_id")

    def test_first_round_semantics_still_enforced(self) -> None:
        # 0.1 alias discipline is reused verbatim inside the 0.2 validator.
        request, candidate = base()
        candidate["bundle"]["entities"][1]["aliases"] = ["武侯"]
        report = R.validate_reading_annotations(request, candidate)
        assert_rejected(self, report, "chapter")

    def test_valid_candidate_without_direct_claim_has_context(self) -> None:
        # 周瑜 has no Claim but is source-supported and appears in context.
        request, candidate = base()
        entity_refs = {
            entity["entity_ref"]
            for unit in candidate["reading"]["units"]
            for entity in unit["context_entities"]
        }
        self.assertIn("ent_002", entity_refs)
        self.assertFalse(
            any(claim["subject"]["ref"] == "ent_002" for claim in candidate["bundle"]["claims"])
        )


class SpanCoordinateTests(unittest.TestCase):
    def test_second_repeated_event_word_resolves_exactly(self) -> None:
        _, candidate = base()
        block = candidate["translation"]["blocks"][1]
        text = block["text"]
        span, error = R.resolve_translation_span(
            text, {"quote": "赤壁", "occurrence": 2}, owner="test"
        )
        self.assertIsNone(error)
        assert span is not None
        self.assertEqual((span["start"], span["end"]), (11, 13))
        self.assertEqual(text[span["start"]:span["end"]], "赤壁")
        # The second 赤壁 is the one in 周瑜在赤壁擊敗曹操.
        self.assertIn("周瑜在赤壁", text[: span["start"] + 2])

    def test_extended_cjk_code_point_span_resolves(self) -> None:
        _, candidate = base()
        text = candidate["translation"]["blocks"][1]["text"]
        span, error = R.resolve_translation_span(
            text, {"quote": "𠀋操", "occurrence": 1}, owner="test"
        )
        self.assertIsNone(error)
        assert span is not None
        self.assertEqual((span["start"], span["end"]), (0, 2))
        self.assertEqual(text[span["start"]:span["end"]], "𠀋操")
        # UTF-16 would count 𠀋 as two units; code points must not.
        self.assertEqual(len("𠀋操"), 2)

    def test_overlapping_spans_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-overlap-span.json")
        assert_rejected(self, R.validate_reading_annotations(request, candidate), "reading_spans")

    def test_bad_translation_occurrence_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-bad-occurrence.json")
        assert_rejected(self, R.validate_reading_annotations(request, candidate), "reading_spans")

    def test_segments_reassemble_translation_block(self) -> None:
        artifact = load("artifact-accepted.json")
        blocks = {b["block_id"]: b["text"] for b in load("candidate-valid.json")["translation"]["blocks"]}
        for unit in artifact["reading_units"]:
            joined = "".join(segment["text"] for segment in unit["segments"])
            self.assertEqual(joined, blocks[unit["block_id"]])
            self.assertEqual(
                sorted(s["span_id"] for s in unit["segments"] if s["kind"] == "event"),
                sorted(s["span_id"] for s in unit["resolved_spans"]),
            )


class AcceptanceTests(unittest.TestCase):
    def test_accept_emits_bound_artifact(self) -> None:
        request, candidate = base()
        producing_run = {"run_id": "r", "model": "m", "prompt_schema_version": "v"}
        artifact = R.accept_reading_candidate(
            request, candidate, producing_run=producing_run
        )
        again = R.accept_reading_candidate(
            request, candidate, producing_run=producing_run
        )
        self.assertEqual(artifact["schema"], "chronicle.chapter-artifact")
        self.assertEqual(artifact["version"], "0.2")
        self.assertEqual(artifact["artifact_sha256"], again["artifact_sha256"])
        self.assertEqual(len(artifact["artifact_sha256"]), 64)
        self.assertEqual(len(artifact["reading_units"]), 3)
        self.assertEqual(
            artifact["reading_sha256"],
            R.sha256_json(candidate["reading"]),
        )
        for unit in artifact["reading_units"]:
            expected = R.unit_id_for(
                revision_id=request["revision_id"],
                chapter_id=request["chapter_id"],
                block_id=unit["block_id"],
                artifact_sha256=artifact["artifact_sha256"],
            )
            self.assertEqual(unit["unit_id"], expected)
        self.assertEqual(
            R._iter_schema_errors(R.artifact_v02_schema(), artifact, registry=R._registry()), []
        )

    def test_accept_rejects_failing_candidate(self) -> None:
        request, _ = base()
        candidate = load("candidate-overlap-span.json")
        with self.assertRaises(PersistenceError):
            R.accept_reading_candidate(
                request, candidate,
                producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
            )

    def test_forged_passing_report_cannot_accept(self) -> None:
        request, _ = base()
        candidate = load("candidate-overlap-span.json")
        with self.assertRaises(PersistenceError):
            R.accept_reading_candidate(
                request, candidate,
                producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
                report={"passed": True, "errors": {}},
            )

    def test_role_value_is_copied_by_program(self) -> None:
        request, candidate = base()
        artifact = R.accept_reading_candidate(
            request, candidate,
            producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
        )
        unit = {u["block_id"]: u for u in artifact["reading_units"]}["t_002"]
        roles = {
            (entity["entity_ref"], role["event_ref"]): role
            for entity in unit["context_entities"]
            for role in entity["event_roles"]
        }
        self.assertEqual(roles[("ent_001", "evt_001")]["role"], "commander")
        self.assertEqual(roles[("ent_001", "evt_001")]["participant_index"], 0)
        self.assertEqual(roles[("ent_002", "evt_001")]["participant_index"], 1)


class TimeGroupingTests(unittest.TestCase):
    def test_consecutive_same_period_merges(self) -> None:
        first = make_unit(0, observation("建安十三年", calendar=regnal()))
        second = make_unit(1, observation("其年", calendar=regnal()))
        groups = R.compile_time_groups([first, second], stream_id=STREAM_ID, catalog_sha=CATALOG_SHA)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["unit_count"], 2)
        self.assertEqual(groups[0]["year_label"], "建安13年")

    def test_year_label_prints_once_and_month_adds_period(self) -> None:
        eighth = make_unit(0, observation("八月", calendar=regnal(month=8), precision="month"))
        ninth = make_unit(1, observation("九月", calendar=regnal(month=9), precision="month"))
        groups = R.compile_time_groups([eighth, ninth], stream_id=STREAM_ID, catalog_sha=CATALOG_SHA)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["year_label"], "建安13年")
        self.assertIsNone(groups[1]["year_label"])
        self.assertNotEqual(groups[0]["period_key"], groups[1]["period_key"])

    def test_year_only_does_not_inherit_month(self) -> None:
        month = make_unit(0, observation("八月", calendar=regnal(month=8), precision="month"))
        year = make_unit(1, observation("建安十三年", calendar=regnal()))
        groups = R.compile_time_groups([month, year], stream_id=STREAM_ID, catalog_sha=CATALOG_SHA)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[1]["period_label"], "（月份未明确）")
        self.assertNotEqual(groups[0]["period_key"], groups[1]["period_key"])

    def test_unknown_is_its_own_group(self) -> None:
        unknown = make_unit(0, observation("", precision="unknown"))
        groups = R.compile_time_groups([unknown], stream_id=STREAM_ID, catalog_sha=CATALOG_SHA)
        self.assertEqual(groups[0]["period_label"], "时间未明确")
        self.assertEqual(groups[0]["year_key"], "unknown")

    def test_leap_month_stays_opaque_and_separate(self) -> None:
        ordinary = observation("八月", calendar=regnal(month=8), precision="month")
        leap = observation("閏八月", calendar=regnal(month=8), precision="month")
        self.assertTrue(R.observation_time_key(leap).period_key.startswith("opaque:"))
        self.assertNotEqual(
            R.observation_time_key(ordinary).period_key,
            R.observation_time_key(leap).period_key,
        )
        units = [make_unit(0, ordinary), make_unit(1, leap)]
        groups = R.compile_time_groups(units, stream_id=STREAM_ID, catalog_sha=CATALOG_SHA)
        self.assertEqual(len(groups), 2)

    def test_exact_gregorian_key_differs_from_regnal(self) -> None:
        calendar, normalized, precision = gregorian(year=208, month=8)
        exact = observation("八月", calendar=calendar, normalized=normalized, precision=precision)
        source = observation("八月", calendar=regnal(month=8), precision="month")
        self.assertNotEqual(
            R.observation_time_key(exact).period_key,
            R.observation_time_key(source).period_key,
        )

    def test_non_consecutive_years_are_not_globally_merged(self) -> None:
        y2008 = make_unit(0, observation("建安十三年", calendar=regnal(era_year=13)))
        y2010 = make_unit(1, observation("建安十五年", calendar=regnal(era_year=15)))
        y2008_again = make_unit(2, observation("建安十三年", calendar=regnal(era_year=13)))
        groups = R.compile_time_groups(
            [y2008, y2010, y2008_again], stream_id=STREAM_ID, catalog_sha=CATALOG_SHA
        )
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0]["year_key"], groups[2]["year_key"])
        self.assertNotEqual(groups[0]["year_key"], groups[1]["year_key"])

    def test_mixed_observations_keep_their_own_key(self) -> None:
        first = observation("建安十三年", calendar=regnal())
        second = observation("建安十四年", calendar=regnal(era_year=14))
        mixed = R.narrative_time_display("mixed", [first, second])
        self.assertTrue(mixed["period_key"].startswith("mixed:"))
        unit_id = f"ru_{0:024x}"
        unit = {
            "unit_id": unit_id,
            "ordinal": 0,
            "locator": {"stream_id": STREAM_ID, "catalog_sha": CATALOG_SHA, "unit_id": unit_id},
            "narrative_time": mixed,
        }
        groups = R.compile_time_groups([unit], stream_id=STREAM_ID, catalog_sha=CATALOG_SHA)
        self.assertEqual(groups[0]["precision"], "mixed")
        self.assertEqual(len(groups[0]["observations"]), 2)

    def test_group_id_binds_first_unit_and_key(self) -> None:
        first = make_unit(0, observation("建安十三年", calendar=regnal()))
        second = make_unit(1, observation("其年", calendar=regnal()))
        groups = R.compile_time_groups([first, second], stream_id=STREAM_ID, catalog_sha=CATALOG_SHA)
        self.assertEqual(
            groups[0]["group_id"],
            R.group_id_for(
                stream_id=STREAM_ID,
                catalog_sha=CATALOG_SHA,
                first_unit_id=first["unit_id"],
                period_key=first["narrative_time"]["period_key"],
            ),
        )

    def test_unit_id_collision_detected(self) -> None:
        units = [
            {"unit_id": "ru_" + "0" * 24, "block_id": "t_001"},
            {"unit_id": "ru_" + "0" * 24, "block_id": "t_002"},
        ]
        self.assertTrue(R.detect_unit_id_collisions(units))


class DtoContractTests(unittest.TestCase):
    EXAMPLES = {
        "reading-locator-example.json": ("reading_locator", "ReadingLocator"),
        "reading-unit-example.json": ("reading_unit", "ReadingUnit"),
        "stream-page-example.json": ("stream_page", "StreamPage"),
        "time-group-example.json": ("time_group", "TimeGroup"),
        "event-preview-example.json": ("event_preview", "EventPreview"),
        "event-target-page-example.json": ("event_target_page", "EventTargetPage"),
    }

    def test_examples_match_schema_and_budget(self) -> None:
        for name, (dto_name, _interface) in self.EXAMPLES.items():
            with self.subTest(example=name):
                value = load(name)
                self.assertEqual(R.reading_response_errors(dto_name, value), [])

    def test_every_dto_has_a_typescript_mirror(self) -> None:
        source = READING_TYPES.read_text(encoding="utf-8")
        for name, (_dto_name, interface) in self.EXAMPLES.items():
            with self.subTest(example=name):
                self.assertIn(f"interface {interface}", source)
                for key in load(name).keys():
                    self.assertIn(key, source, f"{name} field {key!r} missing from reading-types.ts")
        self.assertIn("ReadingWindowCallbacks", source)
        self.assertIn("ReadingControllerCallbacks", source)
        self.assertIn("isReadingLocator", source)

    def test_preview_excerpt_budget_enforced(self) -> None:
        value = load("event-preview-example.json")
        value["sources"][0]["excerpt"] = "字" * 161
        errors = R.reading_response_errors("event_preview", value)
        self.assertTrue(any("excerpt" in message for message in errors))

    def test_locator_type_guard(self) -> None:
        # Mirror of the TS guard lives in Python as schema validation.
        self.assertEqual(R.validate_reading_dto("reading_locator", load("reading-locator-example.json")), [])
        self.assertTrue(
            R.validate_reading_dto(
                "reading_locator",
                {"stream_id": "not-a-uuid", "catalog_sha": "x", "unit_id": "u"},
            )
        )


class FailClosedTypeTests(unittest.TestCase):
    def test_malformed_reading_collections_fail_without_exception(self) -> None:
        request, _ = base()
        cases = [
            ("reading_as_string", lambda c: c.update(reading="x")),
            ("units_as_object", lambda c: c["reading"].update(units={})),
            ("unit_as_string", lambda c: c["reading"].update(units=["x"])),
            ("spans_as_object", lambda c: c["reading"]["units"][1].update(event_spans={})),
            ("context_as_string", lambda c: c["reading"]["units"][1].update(context_entities="x")),
            ("roles_as_object", lambda c: c["reading"]["units"][1]["context_entities"][0].update(event_roles={})),
        ]
        for name, mutate in cases:
            with self.subTest(case=name):
                candidate = base()[1]
                mutate(candidate)
                try:
                    report = R.validate_reading_annotations(request, candidate)
                except (TypeError, AttributeError) as exc:
                    self.fail(f"case {name} raised {type(exc).__name__}: {exc}")
                self.assertFalse(report["passed"], f"case {name} unexpectedly passed")


if __name__ == "__main__":
    unittest.main()
