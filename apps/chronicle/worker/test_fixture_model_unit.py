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


if __name__ == "__main__":
    unittest.main()
