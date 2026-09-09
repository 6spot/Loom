"""Unit tests for Chronicle C2-R1-T01 chapter contract (no PostgreSQL).

Covers the machine-checkable shared contract from
chapter-production.md sections 2-6 and review-workflow.md sections 2/4:
valid joint product acceptance, translation/bundle presence, tail
coverage, dangling refs, kind matching, occurrence resolution
(BOM/CRLF/extended CJK), hash/chapter binding, same-chapter alias
discipline (曹操/操 vs 公/王), time precision, and resolution v0.2
structure. Pure functions only: no DB, network, or model calls.
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
from common import PersistenceError  # noqa: E402

FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r1-contract"


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


class ChapterLimitsTests(unittest.TestCase):
    def test_defaults_match_contract_envelope(self) -> None:
        limits = C.ChapterLimits()
        self.assertEqual(limits.max_source_chars, 32768)
        self.assertEqual(limits.max_prompt_chars, 262144)
        self.assertEqual(limits.max_response_chars, 524288)
        self.assertEqual(limits.max_response_bytes, 4 * 1024 * 1024)
        self.assertEqual(limits.max_output_tokens, 65536)
        self.assertEqual(limits.max_correction_rounds, 1)

    def test_env_overrides(self) -> None:
        limits = C.ChapterLimits.from_env(
            {"CHRONICLE_CHAPTER_MAX_SOURCE_CHARS": "100", "CHRONICLE_CHAPTER_MAX_OUTPUT_TOKENS": "7"}
        )
        self.assertEqual(limits.max_source_chars, 100)
        self.assertEqual(limits.max_output_tokens, 7)

    def test_correction_rounds_fixed(self) -> None:
        with self.assertRaises(PersistenceError):
            C.ChapterLimits(max_correction_rounds=2)


class CandidateAcceptanceTests(unittest.TestCase):
    def test_valid_candidate_passes_and_accepts(self) -> None:
        request, candidate = base()
        report = C.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        artifact = C.accept_chapter_candidate(
            request, candidate,
            producing_run={"run_id": "run_t", "model": "m", "prompt_schema_version": "v"},
        )
        self.assertEqual(artifact["schema"], "chronicle.chapter-artifact")
        self.assertEqual(artifact["chapter_id"], request["chapter_id"])
        self.assertTrue(artifact["anchors"])
        self.assertEqual(artifact["request_fingerprint"], C.request_fingerprint(request))
        # Anchors bind revision/chapter/hashes and verify against text.
        text = request["normalized_text"]
        for anchor in artifact["anchors"]:
            self.assertEqual(anchor["revision_id"], request["revision_id"])
            self.assertEqual(anchor["chapter_id"], request["chapter_id"])
            self.assertEqual(anchor["source_sha256"], request["source_sha256"])
            self.assertEqual(text[anchor["start"]:anchor["end"]], anchor["quote"])

    def test_translation_only_shape_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-translation-only-shape.json")
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "references")

    def test_bundle_only_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-bundle-only.json")
        report = C.validate_chapter_candidate(request, candidate)
        self.assertFalse(report["passed"])

    def test_missing_tail_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-missing-tail.json")
        assert_rejected(
            self, C.validate_chapter_candidate(request, candidate), "translation_coverage"
        )

    def test_dangling_ref_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-dangling-ref.json")
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "references")

    def test_wrong_kind_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-wrong-kind.json")
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "references")

    def test_canonical_id_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-canonical-id.json")
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "references")

    def test_evidence_mismatch_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-evidence-mismatch.json")
        assert_rejected(
            self, C.validate_chapter_candidate(request, candidate), "record_sources"
        )

    def test_accept_rejects_failing_candidate(self) -> None:
        request, _ = base()
        candidate = load("candidate-dangling-ref.json")
        with self.assertRaises(PersistenceError):
            C.accept_chapter_candidate(
                request, candidate,
                producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
            )


class AnchorCoordinateTests(unittest.TestCase):
    def test_repeated_quote_occurrence_resolves_to_third_cao(self) -> None:
        request, candidate = base()
        anchor, error = C.resolve_selection(
            {"first_block_id": "b_001", "last_block_id": "b_002", "quote": "操", "occurrence": 3},
            request=request,
            blocks_by_id={
                b["block_id"]: {"start": b["start"], "end": b["end"]}
                for b in request["blocks"]
            },
            owner="test",
        )
        self.assertIsNone(error)
        assert anchor is not None
        text = request["normalized_text"]
        self.assertEqual(text[anchor["start"]:anchor["end"]], "操")
        # Third 操 is the one in 敗操於赤壁.
        self.assertIn("敗操於赤壁", text[max(0, anchor["start"] - 2):anchor["end"] + 3])

    def test_bad_occurrence_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-bad-occurrence.json")
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "anchors")

    def test_anchor_miss_hint_points_to_holding_block(self) -> None:
        # Live regression (C2-R1-T19 先主传 chunk 0): 0-hit anchors never
        # said whether the quote exists elsewhere. A misattributed quote
        # must name its chapter-wide count and holding block.
        request, _ = base()
        text = request["normalized_text"]
        blocks = request["blocks"]
        by_id = {b["block_id"]: {"start": b["start"], "end": b["end"]} for b in blocks}
        home = blocks[2]
        quote = text[home["start"]:home["start"] + 6]
        other = blocks[0]["block_id"]
        assert other != home["block_id"]
        _anchor, error = C.resolve_selection(
            {"first_block_id": other, "last_block_id": other, "quote": quote, "occurrence": 1},
            request=request, blocks_by_id=by_id, owner="test",
        )
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("chapter-wide", error)
        self.assertIn(home["block_id"], error)
        self.assertIn("re-point", error)

    def test_anchor_miss_hint_flags_fabricated_quote(self) -> None:
        # A quote occurring nowhere in the chapter must say so explicitly
        # so the correction replaces it instead of shuffling block ids.
        request, _ = base()
        by_id = {b["block_id"]: {"start": b["start"], "end": b["end"]} for b in request["blocks"]}
        _anchor, error = C.resolve_selection(
            {"first_block_id": "b_001", "last_block_id": "b_001", "quote": "子虛烏有先生曰", "occurrence": 1},
            request=request, blocks_by_id=by_id, owner="test",
        )
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("not found anywhere in chapter text", error)
        self.assertIn("replace it", error)

    def test_cross_block_quote_resolves(self) -> None:
        request, candidate = base()
        text = request["normalized_text"]
        b1 = request["blocks"][0]
        quote = text[b1["end"] - 2:b1["end"] + 2]  # spans b_001/b_002 boundary
        anchor, error = C.resolve_selection(
            {"first_block_id": "b_001", "last_block_id": "b_002", "quote": quote, "occurrence": 1},
            request=request,
            blocks_by_id={b["block_id"]: {"start": b["start"], "end": b["end"]} for b in request["blocks"]},
            owner="test",
        )
        self.assertIsNone(error)
        assert anchor is not None
        self.assertEqual(text[anchor["start"]:anchor["end"]], quote)

    def test_bom_crlf_normalization(self) -> None:
        raw = "建安十三年，曹操屯江陵。\r\n操觀兵赤壁。".encode("utf-8")
        text, source_sha, normalized_sha = C.normalize_source_bytes(b"\xef\xbb\xbf" + raw)
        self.assertNotIn("\r", text)
        self.assertFalse(text.startswith("\ufeff"))
        self.assertEqual(text, "建安十三年，曹操屯江陵。\n操觀兵赤壁。")
        self.assertNotEqual(source_sha, normalized_sha)

    def test_extended_cjk_code_point_offsets(self) -> None:
        char = "𠀋"  # U+2000B, astral plane: 1 code point, 2 UTF-16 units, 4 bytes
        text = f"曹操{char}屯江陵。"
        self.assertEqual(len(text), 7)
        anchor_text_index = text.index(char)
        self.assertEqual(anchor_text_index, 2)
        self.assertEqual(text.encode("utf-8").index(char.encode("utf-8")), 6)

    def test_hash_drift_rejected(self) -> None:
        _, candidate = base()
        drifted_request = load("request-hash-drift.json")
        assert_rejected(
            self, C.validate_chapter_candidate(drifted_request, candidate), "identity_binding"
        )

    def test_chapter_drift_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-chapter-drift.json")
        assert_rejected(
            self, C.validate_chapter_candidate(request, candidate), "identity_binding"
        )


class AliasMentionTests(unittest.TestCase):
    def test_same_chapter_cao_shares_entity(self) -> None:
        request, candidate = base()
        report = C.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        targets = {m["mention_id"]: m["target_ref"] for m in candidate["mentions"]}
        self.assertEqual(targets["m_001"], "ent_001")
        self.assertEqual(targets["m_002"], "ent_001")

    def test_ambiguous_requires_no_forced_target(self) -> None:
        request, _ = base()
        candidate = load("candidate-ambiguous-forced-target.json")
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "mentions")

    def test_gong_wang_never_global_alias(self) -> None:
        request, _ = base()
        candidate = load("candidate-global-alias.json")
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "aliases")

    def test_unsupported_alias_rejected(self) -> None:
        request, candidate = base()
        candidate["bundle"]["entities"][1]["aliases"] = ["武侯"]
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "aliases")


class EqualityDiagnosticTests(unittest.TestCase):
    def test_mention_surface_mismatch_shows_both_values(self) -> None:
        # Live regression (C2-R1-T19, candidate 0410b15d): a value-free
        # "surface must equal selection.quote" left the model unable to see
        # which side to copy, and all 10 mentions of a correction round
        # failed at once. The contract is unchanged; the diagnostic now
        # carries both sides.
        request, candidate = base()
        candidate["mentions"][0]["surface"] = "曹公"
        report = C.validate_chapter_candidate(request, candidate)
        assert_rejected(self, report, "mentions")
        messages = report["errors"]["mentions"]
        self.assertTrue(
            any("m_001" in m and "曹公" in m and "曹操" in m for m in messages),
            json.dumps(messages, ensure_ascii=False),
        )

    def test_claim_evidence_mismatch_shows_both_values(self) -> None:
        request, candidate = base()
        candidate["bundle"]["claims"][0]["evidence"]["text"] = "曹操屯江陵矣"
        report = C.validate_chapter_candidate(request, candidate)
        assert_rejected(self, report, "record_sources")
        messages = report["errors"]["record_sources"]
        self.assertTrue(
            any("曹操屯江陵矣" in m and "曹操屯江陵" in m for m in messages),
            json.dumps(messages, ensure_ascii=False),
        )

    def test_long_values_truncated_in_diagnostic(self) -> None:
        rendered = C._diagnostic_value("x" * 500)
        self.assertIn("…", rendered)
        self.assertLessEqual(len(rendered), C._DIAGNOSTIC_VALUE_CHARS + 3)

    def test_matching_values_still_pass(self) -> None:
        request, candidate = base()
        report = C.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))

    def test_entity_resolution_new_rejected_with_actionable_message(self) -> None:
        # Live regression (C2-R1-T19, candidate 26eb34c1): status 'new'
        # sailed through validation and killed the job at assemble.
        request, candidate = base()
        candidate["bundle"]["entities"][0]["resolution"] = {"status": "new"}
        report = C.validate_chapter_candidate(request, candidate)
        assert_rejected(self, report, "references")
        messages = report["errors"]["references"]
        self.assertTrue(
            any("ent_001" in m and "new" in m and "unresolved" in m for m in messages),
            json.dumps(messages, ensure_ascii=False),
        )

    def test_entity_resolution_unresolved_passes_missing_is_schema_error(self) -> None:
        # The candidate schema already requires resolution on entities, so
        # a missing object fails at schema_validation; the new references
        # check only fires on a present-but-wrong status, mirroring the
        # assembler's entities-only rule.
        request, candidate = base()
        report = C.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        candidate2 = base()[1]
        del candidate2["bundle"]["entities"][0]["resolution"]
        report2 = C.validate_chapter_candidate(request, candidate2)
        self.assertFalse(report2["passed"])
        self.assertTrue(report2["errors"]["schema_validation"])
        self.assertFalse(report2["errors"]["references"])


class ClaimObjectShapeTests(unittest.TestCase):
    def test_literal_object_carries_value(self) -> None:
        # Frozen shape across the candidate schema, the API-enforced
        # text_format, and the C0 LITERAL convention: a literal claim
        # object is {"kind": "literal", "value": <text>}. Live regression
        # (C2-R1-T19): the references check demanded a ref key while the
        # schema demanded value, so no literal could pass both gates.
        request, candidate = base()
        candidate["bundle"]["claims"][0]["object"] = {
            "kind": "literal", "value": "白帝城",
        }
        report = C.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))

    def test_literal_object_without_value_rejected(self) -> None:
        request, candidate = base()
        candidate["bundle"]["claims"][0]["object"] = {
            "kind": "literal",
        }
        report = C.validate_chapter_candidate(request, candidate)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("malformed reference" in message for message in report["errors"]["references"]),
            json.dumps(report["errors"]["references"], ensure_ascii=False),
        )

    def test_literal_subject_still_rejected(self) -> None:
        request, candidate = base()
        candidate["bundle"]["claims"][0]["subject"] = {
            "kind": "literal", "value": "白帝城",
        }
        report = C.validate_chapter_candidate(request, candidate)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("must not be a literal" in message for message in report["errors"]["references"]),
            json.dumps(report["errors"]["references"], ensure_ascii=False),
        )


class TimeAndSchemaTests(unittest.TestCase):
    def test_time_source_fields_retained(self) -> None:
        _, candidate = base()
        moment = candidate["bundle"]["events"][0]["time"]
        self.assertIn("original_text", moment)
        self.assertIn("source_calendar", moment)
        self.assertIn("normalized", moment)

    def test_gregorian_month_without_basis_rejected(self) -> None:
        request, _ = base()
        candidate = load("candidate-bad-month.json")
        assert_rejected(
            self, C.validate_chapter_candidate(request, candidate), "time_precision"
        )

    def test_schemas_and_fixture_fields_agree(self) -> None:
        candidate_schema = json.loads(
            (HERE.parent / "ingestion" / "schemas"
             / "chronicle-chapter-candidate-v0.1.schema.json").read_text(encoding="utf-8")
        )
        _, candidate = base()
        top_schema_keys = {"schema", "version", "chapter_id", "bundle", "translation",
                           "mentions", "record_sources", "warnings"}
        self.assertEqual(set(candidate.keys()), top_schema_keys)
        self.assertEqual(
            set(candidate_schema["properties"].keys()), top_schema_keys
        )

    def test_resolution_v02_structure(self) -> None:
        valid = load("resolution-v02-within-revision.json")
        self.assertTrue(C.validate_resolution_v02(valid)["passed"])
        bad_scope = copy.deepcopy(valid)
        bad_scope["scope"] = "within_bundle"
        self.assertFalse(C.validate_resolution_v02(bad_scope)["passed"])
        bad_prefix = copy.deepcopy(valid)
        bad_prefix["entity_links"][0]["candidate_id"] = "vc_001"
        report = C.validate_resolution_v02(bad_prefix)
        self.assertFalse(report["passed"])
        # v0.1 vocabulary preserved: same candidate prefixes, same decisions.
        self.assertIn("candidate_id", json.dumps(valid))

    def test_shared_dto_examples_validate(self) -> None:
        pair = load("chapter-pair-context-example.json")
        self.assertEqual([], C.validate_chapter_pair_context(pair))
        batch = load("batch-context-example.json")
        self.assertEqual([], C.validate_batch_context(batch))
        pub = load("public-chapter-response-example.json")
        self.assertEqual([], C.validate_public_chapter_response(pub))
        page = load("review-page-example.json")
        self.assertEqual([], C.validate_review_page(page))
        # open_count is scope-observed, never derived from the page.
        self.assertNotEqual(page["open_count"], len(page["items"]))
        self.assertIn("observed_at", page)

    def test_incomplete_dto_examples_fail_validators(self) -> None:
        page = load("review-page-example.json")
        bad_page = {k: v for k, v in page.items() if k != "observed_at"}
        self.assertTrue(C.validate_review_page(bad_page))
        batch = load("batch-context-example.json")
        bad_batch = copy.deepcopy(batch)
        del bad_batch["groups"][0]["candidate_keys"]
        self.assertTrue(C.validate_batch_context(bad_batch))
        pub = load("public-chapter-response-example.json")
        bad_pub = {k: v for k, v in pub.items() if k != "source_overview"}
        self.assertTrue(C.validate_public_chapter_response(bad_pub))
        pair = load("chapter-pair-context-example.json")
        bad_pair = copy.deepcopy(pair)
        del bad_pair["left"]["evidence_kind"]
        self.assertTrue(C.validate_chapter_pair_context(bad_pair))
        bad_job = copy.deepcopy(pair)
        del bad_job["right"]["job_id"]
        self.assertTrue(
            any("job_id" in message for message in C.validate_chapter_pair_context(bad_job)),
            json.dumps(C.validate_chapter_pair_context(bad_job), ensure_ascii=False),
        )

    def test_source_descriptor_requires_job_id(self) -> None:
        with self.assertRaises(PersistenceError):
            C.example_source_descriptor(
                context_id="ctx",
                bundle="b",
                bundle_sha256="s",
                record_ref="ent_001",
                job_id="",
                revision_id="r",
                chapter_id="c",
                artifact_sha256="a",
                source_title="t",
                chapter_title="ch",
            )


class ForgedReportTests(unittest.TestCase):
    def test_forged_passing_report_cannot_accept_dangling_candidate(self) -> None:
        request, _ = base()
        candidate = load("candidate-dangling-ref.json")
        with self.assertRaises(PersistenceError):
            C.accept_chapter_candidate(
                request, candidate,
                producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
                report={"passed": True, "errors": {}},
            )

    def test_matching_report_accepts(self) -> None:
        request, candidate = base()
        report = C.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"])
        artifact = C.accept_chapter_candidate(
            request, candidate,
            producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
            report=report,
        )
        self.assertEqual(artifact["chapter_id"], request["chapter_id"])

    def test_stale_report_for_other_candidate_rejected(self) -> None:
        request, candidate = base()
        other = load("candidate-missing-tail.json")
        stale = C.validate_chapter_candidate(request, other)
        with self.assertRaises(PersistenceError):
            C.accept_chapter_candidate(
                request, candidate,
                producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
                report=stale,
            )


class FailClosedTypeTests(unittest.TestCase):
    def test_schema_invalid_ids_fail_closed_without_exception(self) -> None:
        request, candidate = base()
        candidate["translation"]["blocks"][0]["block_id"] = ["t_001"]
        candidate["translation"]["blocks"][0]["source_block_ids"] = ["b_001", ["b_002"]]
        candidate["mentions"][0]["mention_id"] = {"id": 1}
        candidate["mentions"][1]["candidate_refs"] = "ent_001"
        candidate["bundle"]["entities"][0]["temp_id"] = ["ent_001"]
        candidate["record_sources"][0]["record_ref"] = {"ref": "ent_001"}
        try:
            report = C.validate_chapter_candidate(request, candidate)
        except TypeError as exc:
            self.fail(f"validate_chapter_candidate raised TypeError: {exc}")
        self.assertFalse(report["passed"])
        self.assertGreater(report["count"], 0)

    def test_malformed_collections_fail_closed_without_exception(self) -> None:
        cases = [
            ("entity_refs_as_object", lambda c: c["translation"]["blocks"][0].update(entity_refs={})),
            ("event_refs_as_string", lambda c: c["translation"]["blocks"][0].update(event_refs="evt_001")),
            ("participants_as_object", lambda c: c["bundle"]["events"][0].update(participants={})),
            ("places_as_string", lambda c: c["bundle"]["events"][0].update(places="ent_003")),
            ("aliases_as_string", lambda c: c["bundle"]["entities"][0].update(aliases="操")),
            ("alias_item_as_object", lambda c: c["bundle"]["entities"][0].update(aliases=[{}])),
            ("surface_as_array", lambda c: c["mentions"][0].update(surface=["曹操"])),
            ("mentions_as_object", lambda c: c.update(mentions={})),
            ("record_sources_as_string", lambda c: c.update(record_sources="x")),
            ("limits_as_string", None),
        ]
        request, _ = base()
        for name, mutate in cases:
            with self.subTest(case=name):
                req = copy.deepcopy(request)
                _, candidate = base()
                if name == "limits_as_string":
                    req["limits"] = "unlimited"
                else:
                    assert mutate is not None
                    mutate(candidate)
                try:
                    report = C.validate_chapter_candidate(req, candidate)
                except (TypeError, AttributeError) as exc:
                    self.fail(f"case {name} raised {type(exc).__name__}: {exc}")
                self.assertFalse(report["passed"], f"case {name} unexpectedly passed")


class TempIdUniquenessTests(unittest.TestCase):
    def test_duplicate_temp_id_across_entities_rejected(self) -> None:
        request, candidate = base()
        candidate["bundle"]["entities"][1]["temp_id"] = "ent_001"
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "references")

    def test_wrong_prefix_rejected(self) -> None:
        request, candidate = base()
        candidate["bundle"]["entities"][0]["temp_id"] = "evt_001"
        assert_rejected(self, C.validate_chapter_candidate(request, candidate), "references")

    def test_wrong_source_prefix_rejected(self) -> None:
        request, candidate = base()
        candidate["bundle"]["source"]["temp_id"] = "ent_999"
        candidate["bundle"]["claims"][0]["evidence"]["source_ref"] = "ent_999"
        report = C.validate_chapter_candidate(request, candidate)
        self.assertFalse(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        self.assertTrue(
            any("src_" in message for message in report["errors"]["references"]),
            json.dumps(report["errors"]["references"], ensure_ascii=False),
        )


class ResolutionScopeTests(unittest.TestCase):
    def test_cross_source_same_labels_rejected(self) -> None:
        doc = load("resolution-v02-within-revision.json")
        doc = copy.deepcopy(doc)
        doc["scope"] = "cross_source"
        doc["right_bundle"] = dict(doc["left_bundle"])
        report = C.validate_resolution_v02(doc)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("distinct" in message for message in report["errors"]["structural"])
        )

    def test_within_revision_example_still_passes(self) -> None:
        self.assertTrue(
            C.validate_resolution_v02(load("resolution-v02-within-revision.json"))["passed"]
        )


class TranslationOrderTests(unittest.TestCase):
    def test_reversed_translation_blocks_rejected(self) -> None:
        request, candidate = base()
        candidate["translation"]["blocks"] = list(reversed(candidate["translation"]["blocks"]))
        assert_rejected(
            self, C.validate_chapter_candidate(request, candidate), "translation_coverage"
        )

    def test_reversed_source_block_ids_rejected(self) -> None:
        request, candidate = base()
        block = candidate["translation"]["blocks"][0]
        block["source_block_ids"] = list(reversed(block["source_block_ids"]))
        assert_rejected(
            self, C.validate_chapter_candidate(request, candidate), "translation_coverage"
        )


if __name__ == "__main__":
    unittest.main()
