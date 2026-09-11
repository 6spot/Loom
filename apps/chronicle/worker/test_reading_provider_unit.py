"""Unit contracts for the C2-R2-T03 reading chapter provider wiring (no network).

The deployment chapter provider must request the 0.2 reading structured
output by default, keep the chapter transport envelope (4 MiB response cap,
explicit output token budget), and return model text that the T01
``reading_contract`` validator accepts. The 0.1 format stays reachable for
the preserved first-round regression path.
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

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
PERSISTENCE = HERE.parent / "persistence"
if str(PERSISTENCE) not in sys.path:
    sys.path.insert(0, str(PERSISTENCE))

import model_provider  # noqa: E402

CHAPTER_TEXT = "建安十三年，曹操屯江陵。周瑜敗操於赤壁。"
CHAPTER_ID = "ch_" + "e5" * 12


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
        "revision_id": "rev-c2r2-provider-fixture",
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
        "schema_versions": {"candidate": "0.2", "bundle": "0.1"},
    }


def fixture_reading_candidate() -> dict:
    import fixture_model

    payload = {
        "schema": "chronicle.chapter-fixture-pack",
        "version": "0.1",
        "model_version": "chronicle-c2r2-provider-fixture-v1",
        "chapters": [
            {
                "chapter_id": CHAPTER_ID,
                "revision_id": "rev-c2r2-provider-fixture",
                "source_title": "三國志·蜀書·先主傳",
                "translation_text": "建安十三年曹操屯兵江陵，周瑜於赤壁破操。",
                "entities": [
                    {"name": "曹操", "type": "person", "mention": "曹操"},
                    {"name": "周瑜", "type": "person", "mention": "周瑜"},
                ],
                "event": {"type": "battle", "title": "赤壁之戰"},
                "predicate": "stationed_at",
            }
        ],
    }
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "chapter-pack.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    model = fixture_model.models_from_reading_chapter_fixture_pack(path)
    return model.build_for_request(chapter_request())


class ReadingProviderTests(unittest.TestCase):
    def test_chapter_factory_defaults_to_reading_format(self) -> None:
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
        fmt = body["text"]["format"]
        self.assertEqual(model_provider.PRODUCTION_CHAPTER_CANDIDATE_VERSION, "0.2")
        dumped = json.dumps(fmt["schema"])
        self.assertIn('"reading"', dumped)
        self.assertIn("chronicle.chapter-candidate", dumped)
        self.assertIn('"const": "0.2"', dumped)
        self.assertNotIn("canonical_id", dumped)

    def test_chapter_factory_can_request_legacy_0_1_format(self) -> None:
        provider = model_provider.build_chapter_model(
            "chapter-live",
            "https://gateway.example/v1/responses",
            candidate_version="0.1",
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"status": "completed", "output_text": "{}"})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            provider.complete("chapter source")

        dumped = json.dumps(captured["body"]["text"]["format"]["schema"])
        self.assertNotIn('"reading"', dumped)
        self.assertIn('"const": "0.1"', dumped)

    def test_provider_output_is_accepted_by_reading_validator(self) -> None:
        import reading_contract as R

        request = chapter_request()
        candidate = fixture_reading_candidate()
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
        self.assertEqual("0.2", parsed["version"])
        report = R.validate_reading_annotations(request, parsed)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))

    def test_incomplete_length_output_is_not_completion(self) -> None:
        provider = model_provider.build_chapter_model(
            "chapter-live", "https://gateway.example/v1/responses"
        )
        payload = {
            "status": "incomplete",
            "incomplete_details": {"reason": "length"},
            "output_text": '{"schema":"chronicle.chapter-candidate","version":"0.2"',
        }
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            with self.assertRaisesRegex(
                model_provider.ModelProviderError, "did not complete"
            ):
                provider.complete("chapter source")


if __name__ == "__main__":
    unittest.main()
