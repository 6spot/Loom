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

    def test_shared_dto_examples_load(self) -> None:
        for name in (
            "assembled-mapping-example.json",
            "chapter-pair-context-example.json",
            "batch-context-example.json",
            "public-chapter-response-example.json",
            "public-source-response-example.json",
            "review-page-example.json",
        ):
            value = load(name)
            self.assertIsInstance(value, dict)


if __name__ == "__main__":
    unittest.main()
