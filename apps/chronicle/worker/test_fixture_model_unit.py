"""Unit contracts for Chronicle's explicit C1 development fixture provider."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import extraction  # noqa: E402
import fixture_model  # noqa: E402
import model_provider  # noqa: E402
import presentation  # noqa: E402
from common import PersistenceError  # noqa: E402

PACK = HERE.parent / "corpus" / "c1-t13" / "model-fixture-pack.json"


def context_state() -> dict:
    return {
        "version": extraction.EXPECTED_CONTEXT_VERSION,
        "inherited_time": None,
        "active_entities": [],
        "active_places": [],
        "recent_events": [],
        "coreference_aliases": [],
    }


def extraction_request(chunk_text: str) -> tuple[dict, str]:
    section = {"label": "先主 劉備 / p001", "kind": "paragraph", "section_index": 0}
    document = {"title": "三國志·蜀書·先主傳"}
    prompt = extraction.build_extraction_prompt(
        chunk_text=chunk_text,
        section=section,
        document=document,
        context_input=context_state(),
        boundary_head="",
        boundary_tail="",
    )
    return {"section": section, "document": document, "prompt": prompt}, chunk_text


def presentation_context(*, uncertainty: bool = False) -> dict:
    canonical_id = str(uuid.uuid4())
    claim = {
        "temp_id": "clm_001",
        "kind": "claim",
        "subject": {"kind": "entity_ref", "ref": "ent_001"},
        "predicate": "held_office",
        "object": {"kind": "literal", "value": "徐州"},
        "time": None,
        "evidence": {
            "text": "先主遂領徐州",
            "source_ref": "src_001",
            "locator": {"work": "三國志", "section": "先主 劉備 / p001"},
        },
        "assessment": {"status": "unassessed"},
        "extraction": {"method": "model", "job_id": "fixture", "confidence": 1.0},
    }
    return {
        "schema": "chronicle.reader-presentation-context",
        "version": "0.1",
        "target_kind": "entity",
        "canonical_id": canonical_id,
        "language": "zh-CN",
        "representations": [
            {
                "bundle": "bundle-fixture",
                "ref": "ent_001",
                "source": {"ref": "src_001", "title": "三國志·蜀書·先主傳"},
                "record": {"canonical_name": "劉備"},
                "claims": [
                    {"bundle": "bundle-fixture", "ref": "clm_001", "claim": claim}
                ],
            }
        ],
        "resolution_links": [],
        "constraints": {
            "allowed_claim_refs": ["bundle-fixture:clm_001"],
            "requires_uncertainty": uncertainty,
            "disagreement_detected": uncertainty,
            "uncertain_resolution_detected": False,
        },
        "input_fingerprint": "fixture-input",
    }


class FixturePackTests(unittest.TestCase):
    def test_pack_loads_with_auditable_model_names(self) -> None:
        extraction_model, presentation_model = fixture_model.models_from_fixture_pack(PACK)
        self.assertTrue(extraction_model.name.startswith("fixture:"))
        self.assertTrue(presentation_model.name.startswith("fixture:"))
        self.assertIn("chronicle-c1-t13-source-fixture-v1", extraction_model.name)
        self.assertGreaterEqual(len(extraction_model.rules), 20)

    def test_missing_or_invalid_pack_fails_closed(self) -> None:
        with self.assertRaises(PersistenceError):
            fixture_model.models_from_fixture_pack(PACK.with_name("missing.json"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"schema":"wrong"}', encoding="utf-8")
            with self.assertRaises(PersistenceError):
                fixture_model.models_from_fixture_pack(path)

    def test_exact_source_rule_passes_normal_extraction_validator(self) -> None:
        provider, _ = fixture_model.models_from_fixture_pack(PACK)
        request, chunk_text = extraction_request("建安中，先主遂領徐州。")
        candidate = json.loads(provider.complete(request["prompt"]))
        report = extraction.validate_chunk_candidate(
            candidate,
            chunk_text=chunk_text,
            context_input=context_state(),
            section_label=request["section"]["label"],
            document=request["document"],
            schema=extraction.canonical_schema(),
        )
        self.assertTrue(report["passed"], report)
        self.assertEqual("劉備", candidate["entities"][0]["canonical_name"])
        self.assertEqual("先主", candidate["entities"][0]["mentions"][0]["text"])
        self.assertEqual(
            request["section"]["label"],
            candidate["claims"][0]["evidence"]["locator"]["section"],
        )

    def test_unmatched_chunk_is_valid_empty_bundle_not_invented_history(self) -> None:
        provider, _ = fixture_model.models_from_fixture_pack(PACK)
        request, chunk_text = extraction_request("此段沒有已凍結的開發 fixture 事實。")
        candidate = json.loads(provider.complete(request["prompt"]))
        report = extraction.validate_chunk_candidate(
            candidate,
            chunk_text=chunk_text,
            context_input=context_state(),
            section_label=request["section"]["label"],
            document=request["document"],
            schema=extraction.canonical_schema(),
        )
        self.assertTrue(report["passed"], report)
        self.assertEqual([], candidate["entities"])
        self.assertEqual([], candidate["events"])
        self.assertEqual([], candidate["claims"])

    def test_fixture_rule_with_ungrounded_mention_fails_closed(self) -> None:
        payload = json.loads(PACK.read_text(encoding="utf-8"))
        payload["extraction"]["rules"][0]["subject"]["mention"] = "不存在的人名"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            provider, _ = fixture_model.models_from_fixture_pack(path)
            request, _ = extraction_request("建安中，先主遂領徐州。")
            with self.assertRaisesRegex(PersistenceError, "not present in exact evidence"):
                provider.complete(request["prompt"])

    def test_presentation_passes_normal_validator_and_preserves_uncertainty(self) -> None:
        _, provider = fixture_model.models_from_fixture_pack(PACK)
        for uncertainty in (False, True):
            context = presentation_context(uncertainty=uncertainty)
            candidate = json.loads(provider.complete(presentation.build_prompt(context)))
            validated = presentation.validate_candidate(candidate, context)
            self.assertEqual("zh-CN", validated["language"])
            self.assertTrue(all(block["claim_refs"] for block in validated["blocks"]))
            self.assertEqual(
                uncertainty,
                any(block["block_kind"] == "uncertainty" for block in validated["blocks"]),
            )


class FixtureEnvironmentTests(unittest.TestCase):
    ENV_KEYS = {
        "CHRONICLE_MODEL_FIXTURE_PACK",
        "CHRONICLE_MODEL_ENDPOINT",
        "CHRONICLE_MODEL_API_KEY",
        "CHRONICLE_MODEL_TIMEOUT_SECONDS",
        "CHRONICLE_EXTRACTION_MODEL",
        "CHRONICLE_PRESENTATION_MODEL",
    }

    def clean_env(self, values: dict[str, str] | None = None):
        patch = {key: "" for key in self.ENV_KEYS}
        if values:
            patch.update(values)
        return mock.patch.dict(os.environ, patch, clear=False)

    def test_fixture_env_enables_both_models(self) -> None:
        with self.clean_env({"CHRONICLE_MODEL_FIXTURE_PACK": str(PACK)}):
            extraction_model, presentation_model = model_provider.models_from_env()
        self.assertTrue(extraction_model.name.startswith("fixture:"))
        self.assertTrue(presentation_model.name.startswith("fixture:"))

    def test_fixture_and_external_provider_are_mutually_exclusive(self) -> None:
        with self.clean_env(
            {
                "CHRONICLE_MODEL_FIXTURE_PACK": str(PACK),
                "CHRONICLE_MODEL_ENDPOINT": "https://example.test/v1/responses",
                "CHRONICLE_EXTRACTION_MODEL": "live-model",
            }
        ):
            with self.assertRaisesRegex(PersistenceError, "cannot be combined"):
                model_provider.models_from_env()


# ---------------------------------------------------------------------------
# Chapter fixtures (C2-R1-T06)
# ---------------------------------------------------------------------------

CHAPTER_TEXT = "建安十三年，曹操屯江陵。周瑜敗操於赤壁。"
CHAPTER_ID = "ch_" + "b2" * 12


def chapter_request() -> dict:
    import hashlib

    text_hash = hashlib.sha256(CHAPTER_TEXT.encode("utf-8")).hexdigest()
    return {
        "chapter_id": CHAPTER_ID,
        "chapter_index": 0,
        "revision_id": "rev-t06-fixture-1",
        "source_sha256": text_hash,
        "normalized_sha256": text_hash,
        "normalized_text": CHAPTER_TEXT,
        "blocks": [
            {"block_id": "b_001", "kind": "body", "start": 0, "end": 12},
            {"block_id": "b_002", "kind": "body", "start": 12, "end": 20},
        ],
        "required_block_ids": ["b_001", "b_002"],
        "plan_version": "c2r1-chapters-v1",
        "limits": {
            "max_source_chars": 32768,
            "max_prompt_chars": 262144,
            "max_response_chars": 524288,
            "max_response_bytes": 4194304,
            "max_output_tokens": 65536,
            "max_correction_rounds": 1,
        },
        "schema_versions": {"candidate": "0.1", "bundle": "0.1"},
    }


def chapter_pack_model_version() -> str:
    return "chronicle-c2r1-t06-chapter-fixture-v1"


def chapter_pack_payload(fingerprint: str | None = None) -> dict:
    chapter: dict = {
        "chapter_id": CHAPTER_ID,
        "revision_id": "rev-t06-fixture-1",
        "source_title": "三國志·蜀書·先主傳",
        "translation_text": "建安十三年曹操屯兵江陵，周瑜於赤壁破操。",
        "entities": [
            {"name": "曹操", "type": "person", "mention": "曹操"},
            {"name": "周瑜", "type": "person", "mention": "周瑜"},
        ],
        "event": {"type": "battle", "title": "赤壁之戰"},
        "predicate": "stationed_at",
    }
    if fingerprint is not None:
        chapter["request_fingerprint"] = fingerprint
    return {
        "schema": "chronicle.chapter-fixture-pack",
        "version": "0.1",
        "model_version": chapter_pack_model_version(),
        "chapters": [chapter],
    }


def write_chapter_pack(payload: dict) -> Path:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "chapter-pack.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def chapter_prompt(request: dict) -> str:
    return (
        "chapter system instructions\nCHAPTER_REQUEST\n"
        + json.dumps(request, ensure_ascii=False)
        + "\n---END CHAPTER_REQUEST---\nchapter source follows"
    )


class ChapterFixtureTests(unittest.TestCase):
    def test_chapter_pack_loads_with_auditable_name(self) -> None:
        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(chapter_pack_payload())
        )
        self.assertTrue(model.name.startswith("fixture:"))
        self.assertIn(chapter_pack_model_version(), model.name)
        self.assertIn("chapter", model.name)
        self.assertEqual([CHAPTER_ID], model.chapter_ids())

    def test_chapter_candidate_passes_t01_validator(self) -> None:
        import chapter_contract as C

        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(chapter_pack_payload())
        )
        candidate = json.loads(model.complete(chapter_prompt(chapter_request())))
        report = C.validate_chapter_candidate(chapter_request(), candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        self.assertEqual(CHAPTER_ID, candidate["chapter_id"])

    def test_fixture_and_live_share_candidate_shape(self) -> None:
        import chapter_contract as C
        import extraction_model_schema as S
        from jsonschema import Draft202012Validator

        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(chapter_pack_payload())
        )
        request = chapter_request()
        via_prompt = json.loads(model.complete(chapter_prompt(request)))
        via_request = model.build_for_request(request)
        self.assertEqual(via_request, via_prompt)
        # The live chapter provider is constrained to this strict projection;
        # the fixture must satisfy the same shape so both walk one protocol.
        projection = Draft202012Validator(S.chapter_candidate_model_schema())
        self.assertTrue(projection.is_valid(via_prompt))
        report = C.validate_chapter_candidate(request, via_prompt)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))

    def test_translation_covers_all_required_blocks_with_sources(self) -> None:
        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(chapter_pack_payload())
        )
        candidate = model.build_for_request(chapter_request())
        covered: list[str] = []
        for block in candidate["translation"]["blocks"]:
            covered.extend(block["source_block_ids"])
        self.assertEqual(["b_001", "b_002"], covered)
        bundle = candidate["bundle"]
        refs = (
            [e["temp_id"] for e in bundle["entities"]]
            + [e["temp_id"] for e in bundle["events"]]
            + [c["temp_id"] for c in bundle["claims"]]
        )
        sourced = {entry["record_ref"] for entry in candidate["record_sources"]}
        self.assertEqual(set(refs), sourced)
        for entry in candidate["record_sources"]:
            self.assertTrue(entry["selections"])
        for mention in candidate["mentions"]:
            self.assertEqual(mention["surface"], mention["selection"]["quote"])

    def test_chapter_id_drift_fails_closed(self) -> None:
        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(chapter_pack_payload())
        )
        drifted = chapter_request()
        drifted["chapter_id"] = "ch_" + "c3" * 12
        with self.assertRaisesRegex(PersistenceError, "drift|no chapter"):
            model.build_for_request(drifted)
        with self.assertRaisesRegex(PersistenceError, "drift|no chapter"):
            model.complete(chapter_prompt(drifted))

    def test_unknown_chapter_or_missing_envelope_fails_closed(self) -> None:
        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(chapter_pack_payload())
        )
        with self.assertRaisesRegex(PersistenceError, "missing the CHAPTER_REQUEST"):
            model.complete("plain chapter text without any envelope " + CHAPTER_ID)
        with self.assertRaisesRegex(PersistenceError, "must be non-empty"):
            model.complete("")
        payload = chapter_pack_payload()
        payload["chapters"] = []
        with self.assertRaisesRegex(PersistenceError, "non-empty array"):
            fixture_model.models_from_chapter_fixture_pack(write_chapter_pack(payload))
        bad = chapter_pack_payload()
        bad["schema"] = "wrong"
        with self.assertRaisesRegex(PersistenceError, "schema/version"):
            fixture_model.models_from_chapter_fixture_pack(write_chapter_pack(bad))

    def test_ungrounded_mention_fails_closed(self) -> None:
        payload = chapter_pack_payload()
        payload["chapters"][0]["entities"][0]["mention"] = "不存在的人名"
        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(payload)
        )
        with self.assertRaisesRegex(PersistenceError, "not present in the chapter text"):
            model.build_for_request(chapter_request())

    def test_request_fingerprint_binding(self) -> None:
        import chapter_contract as C

        fingerprint = C.request_fingerprint(chapter_request())
        model = fixture_model.models_from_chapter_fixture_pack(
            write_chapter_pack(chapter_pack_payload(fingerprint=fingerprint))
        )
        candidate = model.build_for_request(chapter_request())
        self.assertEqual(CHAPTER_ID, candidate["chapter_id"])
        tampered = chapter_request()
        tampered["revision_id"] = "rev-tampered"
        with self.assertRaisesRegex(PersistenceError, "fingerprint mismatch"):
            model.build_for_request(tampered)


if __name__ == "__main__":
    unittest.main()
