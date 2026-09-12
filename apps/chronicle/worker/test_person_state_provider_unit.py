"""Unit contracts for the C2-R3-T02 person-state provider wiring (no network).

The deployment chapter provider must request the 0.3 person-state structured
output by default, keep the chapter transport envelope (4 MiB response cap,
explicit output token budget), and return model text that the T01
``person_state_contract`` validator accepts. The frozen 0.1/0.2 formats stay
reachable for their regression paths. The development fixture provider is
checked against the same strict projection and the same T01 validator.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
PERSISTENCE = HERE.parent / "persistence"
if str(PERSISTENCE) not in sys.path:
    sys.path.insert(0, str(PERSISTENCE))

import extraction_model_schema as S  # noqa: E402
import fixture_model  # noqa: E402
import model_provider  # noqa: E402

CHAPTER_TEXT = "建安三年，策授瑜建威中郎將。瑜為前部大督。權遣瑜還。"
CHAPTER_ID = "ch_" + "c3" * 12


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.raw if amount < 0 else self.raw[:amount]


def chapter_request() -> dict:
    text_hash = hashlib.sha256(CHAPTER_TEXT.encode("utf-8")).hexdigest()
    return {
        "chapter_id": CHAPTER_ID,
        "chapter_index": 0,
        "revision_id": "rev-c2r3-provider-fixture",
        "source_sha256": text_hash,
        "normalized_sha256": text_hash,
        "normalized_text": CHAPTER_TEXT,
        "blocks": [
            {"block_id": "b_001", "kind": "body", "start": 0, "end": 14},
            {"block_id": "b_002", "kind": "body", "start": 14, "end": 26},
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
        "schema_versions": {"candidate": "0.3", "bundle": "0.1"},
    }


def fixture_pack_payload() -> dict:
    return {
        "schema": "chronicle.chapter-fixture-pack",
        "version": "0.1",
        "model_version": "chronicle-c2r3-provider-fixture-v1",
        "chapters": [
            {
                "chapter_id": CHAPTER_ID,
                "revision_id": "rev-c2r3-provider-fixture",
                "source_title": "三國志·吳書·周瑜傳",
                "translation_text": "建安三年，孫策授周瑜建威中郎將。周瑜任前部大督。",
                "entities": [
                    {"name": "周瑜", "type": "person", "mention": "瑜"},
                    {"name": "孫權", "type": "person", "mention": "權"},
                ],
                "event": {"type": "appointment", "title": "授建威中郎將"},
                "predicate": "appointed_to",
            }
        ],
    }


def fixture_model_instance() -> "fixture_model.FixturePersonStateChapterModel":
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "chapter-pack.json"
    path.write_text(
        json.dumps(fixture_pack_payload(), ensure_ascii=False), encoding="utf-8"
    )
    return fixture_model.models_from_person_state_chapter_fixture_pack(path)


def fixture_person_state_candidate() -> dict:
    return fixture_model_instance().build_for_request(chapter_request())


class PersonStateProviderTests(unittest.TestCase):
    def test_chapter_factory_defaults_to_person_state_format(self) -> None:
        provider = model_provider.build_chapter_model(
            "chapter-live", "https://gateway.example/v1/responses"
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"status": "completed", "output_text": '{"ok":true}'})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual('{"ok":true}', provider.complete("chapter source"))

        self.assertEqual(4 * 1024 * 1024, provider.max_response_bytes)
        body = captured["body"]
        self.assertEqual(65536, body["max_output_tokens"])
        self.assertEqual(
            model_provider.PRODUCTION_CHAPTER_CANDIDATE_VERSION, "0.3"
        )
        fmt = body["text"]["format"]
        self.assertEqual("chronicle_chapter_candidate", fmt["name"])
        self.assertTrue(fmt["strict"])
        dumped = json.dumps(fmt["schema"])
        self.assertIn('"person_states"', dumped)
        self.assertIn('"reading"', dumped)
        self.assertIn("chronicle.chapter-candidate", dumped)
        self.assertIn('"const": "0.3"', dumped)
        self.assertNotIn("canonical_id", dumped)

    def test_chapter_factory_can_request_legacy_0_2_format(self) -> None:
        provider = model_provider.build_chapter_model(
            "chapter-live",
            "https://gateway.example/v1/responses",
            candidate_version="0.2",
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"status": "completed", "output_text": "{}"})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            provider.complete("chapter source")

        dumped = json.dumps(captured["body"]["text"]["format"]["schema"])
        self.assertIn('"reading"', dumped)
        self.assertNotIn('"person_states"', dumped)
        self.assertIn('"const": "0.2"', dumped)

    def test_0_1_format_stays_reachable(self) -> None:
        provider = model_provider.build_chapter_model(
            "chapter-live",
            "https://gateway.example/v1/responses",
            candidate_version="0.1",
        )
        self.assertIsNotNone(provider.text_format)
        dumped = json.dumps(provider.text_format["schema"])
        self.assertNotIn('"reading"', dumped)
        self.assertNotIn('"person_states"', dumped)

    def test_projection_requires_person_states_and_version_0_3(self) -> None:
        schema = S.person_state_chapter_candidate_model_schema()
        Draft202012Validator.check_schema(schema)
        self.assertIn("person_states", schema["required"])
        self.assertIn("reading", schema["required"])
        self.assertEqual("0.3", schema["properties"]["version"]["const"])
        person_states = schema["properties"]["person_states"]
        self.assertEqual(
            [
                "phases",
                "phase_orders",
                "unit_phases",
                "facts",
                "continuities",
                "disagreements",
            ],
            person_states["required"],
        )

    def test_projection_carries_no_program_generated_fields(self) -> None:
        dumped = json.dumps(S.person_state_chapter_candidate_model_schema())
        for forbidden in (
            "anchor_id",
            "quote_sha256",
            "canonical_id",
            "candidate_ids",
            "stream_id",
            "unit_id",
            "publication_id",
            "request_fingerprint",
            "supported",
            "certainty",
            "url",
        ):
            self.assertNotIn(forbidden, dumped, f"program-bound field {forbidden!r} leaked")

    def test_provider_output_is_accepted_by_person_state_validator(self) -> None:
        import person_state_contract as PS

        request = chapter_request()
        candidate = fixture_person_state_candidate()
        provider = model_provider.build_chapter_model(
            "chapter-live", "https://gateway.example/v1/responses"
        )
        payload = {
            "status": "completed",
            "output_text": json.dumps(candidate, ensure_ascii=False),
        }
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            raw = provider.complete("chapter source")
        parsed = json.loads(raw)
        self.assertEqual("0.3", parsed["version"])
        report = PS.validate_person_state_candidate(request, parsed)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))


class PersonStateFixtureProviderTests(unittest.TestCase):
    def test_fixture_provider_declares_0_3_and_emits_person_states(self) -> None:
        model = fixture_model_instance()
        self.assertEqual(model.candidate_version, "0.3")
        self.assertTrue(model.name.endswith(fixture_model.PERSON_STATE_CHAPTER_MODEL_SUFFIX))
        candidate = model.build_for_request(chapter_request())
        self.assertEqual(candidate["version"], "0.3")
        self.assertIn("reading", candidate)
        person_states = candidate["person_states"]
        self.assertTrue(person_states["phases"])
        self.assertTrue(person_states["facts"])
        block_ids = [b["block_id"] for b in candidate["translation"]["blocks"]]
        self.assertEqual(
            [u["block_id"] for u in person_states["unit_phases"]], block_ids
        )

    def test_fixture_candidate_matches_projection_and_validator(self) -> None:
        import person_state_contract as PS

        request = chapter_request()
        candidate = fixture_person_state_candidate()
        projection = Draft202012Validator(S.person_state_chapter_candidate_model_schema())
        projection_errors = sorted(
            error.message for error in projection.iter_errors(candidate)
        )
        self.assertEqual([], projection_errors)
        report = PS.validate_person_state_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))

    def test_fixture_provider_completes_from_production_prompt(self) -> None:
        import chapter_prompt as P
        import person_state_contract as PS

        request = chapter_request()
        model = fixture_model_instance()
        raw = model.complete(P.render_chapter_prompt(request))
        candidate = json.loads(raw)
        self.assertEqual("0.3", candidate["version"])
        report = PS.validate_person_state_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
