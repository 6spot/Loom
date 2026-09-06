#!/usr/bin/env python3
"""TEMP ONLY: patch Chronicle extraction to use canonical schema structured output."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "apps" / "chronicle" / "worker"
PERSIST = ROOT / "apps" / "chronicle" / "persistence"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"{label} anchor not found")


def patch_provider() -> None:
    path = WORKER / "model_provider.py"
    text = path.read_text()
    text = replace_once(
        text,
        "import json\nimport os\nimport time\nfrom dataclasses import dataclass\nfrom typing import Any\n",
        "import json\nimport os\nimport time\nfrom dataclasses import dataclass\nfrom functools import lru_cache\nfrom pathlib import Path\nfrom typing import Any\n",
        "provider imports",
    )
    constants = 'TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 520, 522, 523, 524})\n'
    addition = constants + '\nCANONICAL_SCHEMA_ID = "https://loom.local/chronicle/schemas/chronicle-v0.1.schema.json"\nCANONICAL_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ingestion" / "schemas" / "chronicle-v0.1.schema.json"\nSTRUCTURED_EXTRACTION_SCHEMA_NAME = "chronicle_extraction_bundle"\n\n\n@lru_cache(maxsize=1)\ndef _chronicle_extraction_response_schema() -> dict[str, Any]:\n    """Load the canonical staged-bundle schema for model generation guidance.\n\n    Responses structured output is non-strict because the canonical contract uses\n    JSON-Schema constructs outside the provider strict subset. Chronicle still runs\n    the unchanged canonical validator after generation, so this is generation\n    guidance rather than an alternate acceptance authority.\n    """\n    try:\n        value = json.loads(CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8"))\n    except (OSError, ValueError) as exc:\n        raise PersistenceError(f"canonical Chronicle schema is unreadable: {exc}") from exc\n    if not isinstance(value, dict) or value.get("$id") != CANONICAL_SCHEMA_ID:\n        raise PersistenceError("canonical Chronicle schema failed identity check")\n    return value\n'
    if "STRUCTURED_EXTRACTION_SCHEMA_NAME" not in text:
        if constants not in text:
            raise SystemExit("provider constants anchor not found")
        text = text.replace(constants, addition, 1)

    field_anchor = "    retry_backoff_seconds: float = DEFAULT_MODEL_RETRY_BACKOFF_SECONDS\n"
    field_add = field_anchor + "    response_schema: dict[str, Any] | None = None\n    response_schema_name: str = STRUCTURED_EXTRACTION_SCHEMA_NAME\n"
    if "response_schema: dict[str, Any] | None" not in text:
        if field_anchor not in text:
            raise SystemExit("provider dataclass field anchor not found")
        text = text.replace(field_anchor, field_add, 1)

    validation_anchor = '        if self.retry_backoff_seconds < 0:\n            raise PersistenceError("model retry_backoff_seconds must be non-negative")\n'
    validation_add = validation_anchor + '        if self.response_schema is not None:\n            if not isinstance(self.response_schema, dict):\n                raise PersistenceError("model response_schema must be a JSON object")\n            if not isinstance(self.response_schema_name, str) or not self.response_schema_name.strip():\n                raise PersistenceError("model response_schema_name must be non-empty")\n'
    if "model response_schema must be a JSON object" not in text:
        if validation_anchor not in text:
            raise SystemExit("provider validation anchor not found")
        text = text.replace(validation_anchor, validation_add, 1)

    old_body = '''        body = json.dumps(
            {"model": self.name, "input": prompt},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")'''
    new_body = '''        payload: dict[str, Any] = {"model": self.name, "input": prompt}
        if self.response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": self.response_schema_name,
                    "schema": self.response_schema,
                    "strict": False,
                }
            }
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")'''
    text = replace_once(text, old_body, new_body, "provider request body")

    old_build = '''    def build(name: str | None) -> ResponsesHTTPModel | None:
        if name is None:
            return None
        return ResponsesHTTPModel(
            name=name,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout,
        )

    return build(extraction_name), build(presentation_name)'''
    new_build = '''    def build(
        name: str | None,
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> ResponsesHTTPModel | None:
        if name is None:
            return None
        return ResponsesHTTPModel(
            name=name,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout,
            response_schema=response_schema,
        )

    extraction_schema = (
        _chronicle_extraction_response_schema() if extraction_name is not None else None
    )
    return build(extraction_name, response_schema=extraction_schema), build(presentation_name)'''
    text = replace_once(text, old_build, new_build, "provider environment build")
    path.write_text(text)


def patch_validator() -> None:
    path = PERSIST / "extraction.py"
    text = path.read_text()
    old = "\n".join([
        '    if not isinstance(normalized, dict):',
        '        errors.append(f"{owner} time.normalized must be an object")',
        '        return',
        '    # Normalized precision is never invented at the chunk layer.',
        '    if normalized.get("month") is not None:',
        '        errors.append(f"{owner} fabricates normalized month from traditional calendar")',
        '    if normalized.get("day") is not None:',
        '        errors.append(f"{owner} fabricates normalized day from traditional calendar")',
        '    year = normalized.get("year")',
        '    if year is not None and (verified_year is None or year != verified_year):',
        '        errors.append(',
        '            f"{owner} normalized year {year!r} is not the document-verified year"',
        '        )',
    ])
    new = "\n".join([
        '    if normalized is not None and not isinstance(normalized, dict):',
        '        errors.append(f"{owner} time.normalized must be an object or null")',
        '        return',
        '    # Canonical schema permits normalized=null when no safe conversion exists.',
        '    if isinstance(normalized, dict):',
        '        if normalized.get("month") is not None:',
        '            errors.append(f"{owner} fabricates normalized month from traditional calendar")',
        '        if normalized.get("day") is not None:',
        '            errors.append(f"{owner} fabricates normalized day from traditional calendar")',
        '        year = normalized.get("year")',
        '        if year is not None and (verified_year is None or year != verified_year):',
        '            errors.append(',
        '                f"{owner} normalized year {year!r} is not the document-verified year"',
        '            )',
    ])
    path.write_text(replace_once(text, old, new, "normalized validator"))


def patch_tests() -> None:
    path = WORKER / "test_model_provider_unit.py"
    text = path.read_text()
    marker = "    def test_nested_output_text_is_supported(self) -> None:\n"
    test_name = "test_structured_response_schema_is_sent_non_strict"
    if test_name not in text:
        addition = '''    def test_structured_response_schema_is_sent_non_strict(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            response_schema=schema,
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": '{"x":"ok"}'})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual('{"x":"ok"}', provider.complete("prompt"))
        self.assertEqual(
            {
                "type": "json_schema",
                "name": model_provider.STRUCTURED_EXTRACTION_SCHEMA_NAME,
                "schema": schema,
                "strict": False,
            },
            captured["body"]["text"]["format"],
        )

'''
        if marker not in text:
            raise SystemExit("provider test insertion anchor not found")
        text = text.replace(marker, addition + marker, 1)

    env_assert = '        self.assertEqual("token", extraction.api_key)\n        self.assertIsNone(presentation)\n'
    env_new = '        self.assertEqual("token", extraction.api_key)\n        self.assertEqual(model_provider.CANONICAL_SCHEMA_ID, extraction.response_schema.get("$id"))\n        self.assertIsNone(presentation)\n'
    text = replace_once(text, env_assert, env_new, "provider env schema assertion")
    path.write_text(text)

    path = PERSIST / "test_extraction_unit.py"
    text = path.read_text()
    test_name = "test_canonical_normalized_null_is_not_rejected_by_mechanical_validator"
    if test_name not in text:
        marker = '    def test_paraphrased_evidence_fails_grounding(self) -> None:\n'
        addition = "\n".join([
            '    def test_canonical_normalized_null_is_not_rejected_by_mechanical_validator(self) -> None:',
            '        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")',
            '        bundle["events"][0]["time"]["normalized"] = None',
            '        bundle["claims"][0]["time"]["normalized"] = None',
            '        report = self.validate(bundle)',
            '        self.assertTrue(report["passed"], X.flatten_validation_errors(report))',
            '',
            '',
        ])
        if marker not in text:
            raise SystemExit("extraction test insertion anchor not found")
        text = text.replace(marker, addition + marker, 1)
    path.write_text(text)


def main() -> None:
    patch_provider()
    patch_validator()
    patch_tests()
    print("structured extraction provider patch applied")


if __name__ == "__main__":
    main()
