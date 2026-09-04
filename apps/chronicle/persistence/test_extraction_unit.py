"""Unit tests for Chronicle C1-T6 context-aware chunk extraction (no PostgreSQL).

Covers bounded request construction, mechanical validation (exact
evidence, inherited time without invented precision, authority
separation), bounded correction with fail-closed behavior, replayable
attempt history, and the inherited-context fixture chain.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (str(HERE),):
    if path not in sys.path:
        sys.path.insert(0, path)

import extraction as X  # noqa: E402
from common import PersistenceError  # noqa: E402

SCHEMA = json.loads(
    (HERE.parent / "ingestion" / "schemas" / "chronicle-v0.1.schema.json").read_text(
        encoding="utf-8"
    )
)
FIXTURE_DIR = HERE.parent / "ingestion" / "fixtures" / "c1t6-inherited-jianan"

ALLOWED_PREDICATES = [
    "held_office",
    "died",
    "succeeded",
    "surrendered_to",
    "attacked",
    "fought",
    "outcome",
    "affected",
    "gained_territory",
    "moved_to",
    "stationed_at",
    "appointed",
    "retreated",
]


class FakeProvider:
    """Scripted chunk-model provider with a call log (no network)."""

    def __init__(self, responses: list[str], name: str = "fake-test-model-v1"):
        self.responses = list(responses)
        self.name = name
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("provider called more times than scripted")
        return self.responses.pop(0)


def section(label: str = "全文") -> dict:
    return {"label": label, "kind": "document", "section_index": 0}


def document(verified_year: int | None = 208) -> dict:
    doc: dict = {"title": "三國志·魏書·武帝紀（節選）", "work": "三國志"}
    if verified_year is not None:
        doc["verified_normalized_year"] = verified_year
    return doc


def context_input(
    inherited: list[dict] | None = None, surfaces: list[str] | None = None
) -> dict:
    return {
        "version": "c1t5-ctx-v1",
        "chunk_index": -1,
        "inherited_time": inherited or [],
        "active_entities": [
            {"text": name, "first_seen_chunk": 0, "last_seen_chunk": 0, "count": 1}
            for name in (surfaces or [])
        ],
        "active_places": [],
        "recent_events": [],
        "coreference_hints": [],
        "prev_tail": "",
        "next_head": "",
        "authoritative": False,
        "authority_note": "test",
    }


def extraction_meta() -> dict:
    return {"method": "model", "job_id": "c1t6-test", "confidence": 0.8}


def time_obj(
    original: str,
    inherited_fields: list[str] | None = None,
    year: int | None = 208,
) -> dict:
    return {
        "original_text": original,
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": 13,
            "season": None,
            "month": None,
            "inherited_fields": inherited_fields or [],
        },
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": year,
            "month": None,
            "day": None,
            "precision": "year",
            "conversion_status": "year_only",
        },
    }


def valid_bundle(
    chunk_text: str,
    evidence: str,
    *,
    time_original: str,
    inherited_fields: list[str] | None = None,
    year: int | None = 208,
    time_value: dict | None = "default",
    claims_assessment: str = "unassessed",
    predicate: str = "died",
    entity_name: str = "劉表",
    entity_mention: str | None = None,
    extra_warnings: list[dict] | None = None,
) -> dict:
    time_block = (
        time_obj(time_original, inherited_fields, year)
        if time_value == "default"
        else time_value
    )
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": "三國志·魏書·武帝紀（節選）",
            "author": "陳壽",
            "language": "lzh",
            "extraction": extraction_meta(),
        },
        "entities": [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": entity_name,
                "aliases": [],
                "mentions": [{"text": entity_mention or entity_name}],
                "resolution": {"status": "unresolved"},
                "extraction": extraction_meta(),
            }
        ],
        "events": [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "death",
                "title": "劉表去世",
                "time": copy.deepcopy(time_block),
                "participants": [{"entity_ref": "ent_001", "role": "subject"}],
                "places": [],
                "extraction": extraction_meta(),
            }
        ],
        "claims": [
            {
                "temp_id": "clm_001",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": predicate,
                "object": None,
                "time": copy.deepcopy(time_block),
                "evidence": {
                    "text": evidence,
                    "source_ref": "src_001",
                    "locator": {"work": "三國志", "section": "全文"},
                },
                "assessment": {"status": claims_assessment},
                "extraction": extraction_meta(),
            }
        ],
        "warnings": list(extra_warnings or []),
    }


CHUNK_0 = "建安十三年，曹操率大軍至荊州。劉表卒，其子劉琮代立。"


def make_request(chunk_text: str = CHUNK_0, **overrides) -> dict:
    locator = {
        "job_id": "00000000-0000-0000-0000-000000000000",
        "revision_id": "00000000-0000-0000-0000-000000000001",
        "revision_no": 1,
        "source_sha256": "0" * 64,
        "section_index": 0,
        "chunk_index": 0,
        "source_start": 0,
        "source_end": len(chunk_text),
        "offset_unit": "chars-normalized-utf8",
        "content_sha256": "1" * 64,
    }
    params: dict = {
        "chunk_text": chunk_text,
        "section": section(),
        "document": document(),
        "context_input": context_input(),
        "boundary_head": "",
        "boundary_tail": "",
        "locator": locator,
    }
    params.update(overrides)
    return X.build_chunk_request(**params)


class RequestTests(unittest.TestCase):
    def test_request_binds_prompt_versions_and_locator(self) -> None:
        request = make_request()
        meta = request["request_meta"]
        self.assertEqual(meta["extraction_version"], "c1t6-v1")
        self.assertEqual(meta["contract_version"], "0.2")
        self.assertEqual(meta["prompt_version"], "c1t6-prompt-v1")
        self.assertEqual(meta["locator"]["chunk_index"], 0)
        self.assertIn(CHUNK_0, request["prompt"])
        self.assertIn("建安十三年", request["prompt"])
        self.assertIn("unassessed", request["prompt"])

    def test_request_rejects_context_version_drift(self) -> None:
        stale = context_input()
        stale["version"] = "c1t5-ctx-v0"
        with self.assertRaises(PersistenceError):
            make_request(context_input=stale)

    def test_request_fails_closed_when_prompt_exceeds_budget(self) -> None:
        config = X.ExtractionConfig(max_prompt_chars=10)
        with self.assertRaises(PersistenceError):
            make_request(config=config)

    def test_request_requires_locator(self) -> None:
        with self.assertRaises(PersistenceError):
            make_request(locator={})


class ValidationTests(unittest.TestCase):
    def validate(self, bundle: dict, chunk_text: str = CHUNK_0, **kwargs) -> dict:
        params: dict = {
            "chunk_text": chunk_text,
            "context_input": context_input(),
            "section_label": "全文",
            "document": document(),
            "schema": SCHEMA,
            "allowed_predicates": ALLOWED_PREDICATES,
        }
        params.update(kwargs)
        return X.validate_chunk_candidate(bundle, **params)

    def test_valid_explicit_time_bundle_passes_schema_and_grounding(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        report = self.validate(bundle)
        self.assertTrue(report["passed"], X.flatten_validation_errors(report))
        self.assertEqual(report["contract_version"], "0.2")

    def test_paraphrased_evidence_fails_grounding(self) -> None:
        bundle = valid_bundle(CHUNK_0, "刘表去世", time_original="建安十三年")
        report = self.validate(bundle)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("exact chunk-text substring" in e for e in report["errors"]["grounding"])
        )

    def test_canonical_identity_is_rejected_not_coerced(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        bundle["entities"][0]["id"] = "01900000-0000-7000-8000-000000000000"
        report = self.validate(bundle)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("canonical identity" in e for e in report["errors"]["structural"])
        )

    def test_non_unassessed_claim_fails(self) -> None:
        bundle = valid_bundle(
            CHUNK_0, "劉表卒", time_original="建安十三年", claims_assessment="supported"
        )
        report = self.validate(bundle)
        self.assertFalse(report["passed"])
        self.assertEqual(1, len(report["errors"]["assessment"]))

    def test_normalized_month_is_fabrication(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        bundle["events"][0]["time"]["normalized"]["month"] = 8
        report = self.validate(bundle)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("fabricates normalized month" in e for e in report["errors"]["time_precision"])
        )

    def test_normalized_year_requires_verified_mapping(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        report = self.validate(bundle, document=document(verified_year=None))
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("document-verified year" in e for e in report["errors"]["time_precision"])
        )

    def test_inherited_time_requires_inherited_fields(self) -> None:
        chunk = "其子劉琮代立，舉州而降。"
        ctx = context_input(
            inherited=[{"text": "建安十三年", "scope": "inherited", "source_chunk": 0}]
        )
        bundle = valid_bundle(
            chunk,
            "其子劉琮代立",
            time_original="建安十三年",
            inherited_fields=[],
            entity_name="劉琮",
        )
        report = self.validate(bundle, chunk_text=chunk, context_input=ctx)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("inherited but lists no inherited_fields" in e for e in report["errors"]["time_precision"])
        )

    def test_inherited_time_with_fields_and_verified_year_passes(self) -> None:
        chunk = "其子劉琮代立，舉州而降。"
        ctx = context_input(
            inherited=[{"text": "建安十三年", "scope": "inherited", "source_chunk": 0}]
        )
        bundle = valid_bundle(
            chunk,
            "其子劉琮代立",
            time_original="建安十三年",
            inherited_fields=["era", "era_year"],
            entity_name="劉琮",
            predicate="succeeded",
        )
        report = self.validate(bundle, chunk_text=chunk, context_input=ctx)
        self.assertTrue(report["passed"], X.flatten_validation_errors(report))

    def test_ungrounded_time_expression_fails(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十四年")
        report = self.validate(bundle)
        self.assertFalse(report["passed"])

    def test_locator_section_mismatch_fails(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        bundle["claims"][0]["evidence"]["locator"]["section"] = "別傳"
        report = self.validate(bundle)
        self.assertFalse(report["passed"])

    def test_inherited_only_entity_requires_warning(self) -> None:
        chunk = "其子劉琮代立，舉州而降。"
        ctx = context_input(
            inherited=[{"text": "建安十三年", "scope": "inherited", "source_chunk": 0}],
            surfaces=["曹操"],
        )
        bundle = valid_bundle(
            chunk,
            "其子劉琮代立",
            time_original="建安十三年",
            inherited_fields=["era", "era_year"],
            entity_name="曹操",
            entity_mention="公",
            predicate="succeeded",
        )
        report = self.validate(bundle, chunk_text=chunk, context_input=ctx)
        self.assertFalse(report["passed"])
        bundle["warnings"].append(
            {
                "type": "inherited_entity_context",
                "severity": "warning",
                "message": "曹操 resolved from inherited context only",
                "refs": ["ent_001"],
            }
        )
        report = self.validate(bundle, chunk_text=chunk, context_input=ctx)
        self.assertTrue(report["passed"], X.flatten_validation_errors(report))

    def test_predicate_outside_vocabulary_fails(self) -> None:
        bundle = valid_bundle(
            CHUNK_0, "劉表卒", time_original="建安十三年", predicate="teleported_to"
        )
        report = self.validate(bundle)
        self.assertFalse(report["passed"])
        self.assertEqual(1, len(report["errors"]["predicate_vocabulary"]))

    def test_authority_claim_is_rejected(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        bundle["authoritative"] = True
        report = self.validate(bundle)
        self.assertFalse(report["passed"])


class ExtractionFlowTests(unittest.TestCase):
    def test_first_try_success_records_single_attempt(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider([json.dumps(bundle, ensure_ascii=False)])
        result = X.extract_chunk(
            provider,
            make_request(),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=SCHEMA,
            allowed_predicates=ALLOWED_PREDICATES,
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(1, len(result["attempts"]))
        self.assertEqual(1, len(provider.prompts))
        self.assertIsNone(result["error"])

    def test_persistent_failure_is_bounded_and_fail_closed(self) -> None:
        bundle = valid_bundle(CHUNK_0, "刘表去世", time_original="建安十三年")
        provider = FakeProvider([json.dumps(bundle, ensure_ascii=False)] * 3)
        result = X.extract_chunk(
            provider,
            make_request(),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=SCHEMA,
            allowed_predicates=ALLOWED_PREDICATES,
            config=X.ExtractionConfig(max_repair_attempts=1),
        )
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["candidate"])
        self.assertEqual(2, len(result["attempts"]))
        self.assertEqual(2, len(provider.prompts))
        self.assertIn("failed closed", result["error"])
        kinds = [a["kind"] for a in result["attempts"]]
        self.assertEqual(["initial", "correction"], kinds)

    def test_correction_success_preserves_both_attempts(self) -> None:
        bad = valid_bundle(CHUNK_0, "刘表去世", time_original="建安十三年")
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider(
            [json.dumps(bad, ensure_ascii=False), json.dumps(good, ensure_ascii=False)]
        )
        result = X.extract_chunk(
            provider,
            make_request(),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=SCHEMA,
            allowed_predicates=ALLOWED_PREDICATES,
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(2, len(result["attempts"]))
        self.assertFalse(result["attempts"][0]["validation"]["passed"])
        self.assertTrue(result["attempts"][1]["validation"]["passed"])

    def test_unparseable_response_fails_closed_without_coercion(self) -> None:
        provider = FakeProvider(["not json at all", "{still not json"])
        result = X.extract_chunk(
            provider,
            make_request(),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            config=X.ExtractionConfig(max_repair_attempts=1),
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(2, len(result["attempts"]))
        self.assertIn("not valid JSON", result["error"])

    def test_schema_none_skips_schema_but_keeps_grounding(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        del bundle["entities"][0]["type"]  # schema violation only
        provider = FakeProvider([json.dumps(bundle, ensure_ascii=False)])
        result = X.extract_chunk(
            provider,
            make_request(),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=None,
            allowed_predicates=ALLOWED_PREDICATES,
        )
        # Structural/grounding checks pass without the schema layer;
        # production binds the schema (worker fails closed without it).
        self.assertTrue(result["accepted"])
        provider2 = FakeProvider([json.dumps(bundle, ensure_ascii=False)] * 2)
        result2 = X.extract_chunk(
            provider2,
            make_request(),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=SCHEMA,
            allowed_predicates=ALLOWED_PREDICATES,
            config=X.ExtractionConfig(max_repair_attempts=1),
        )
        self.assertFalse(result2["accepted"])


class HistoryTests(unittest.TestCase):
    def test_run_round_trip_replays_cleanly(self) -> None:
        bad = valid_bundle(CHUNK_0, "刘表去世", time_original="建安十三年")
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider(
            [json.dumps(bad, ensure_ascii=False), json.dumps(good, ensure_ascii=False)]
        )
        request = make_request()
        result = X.extract_chunk(
            provider,
            request,
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=SCHEMA,
            allowed_predicates=ALLOWED_PREDICATES,
        )
        ctx_out = context_input()
        run = X.build_chunk_run(
            request=request,
            provider_name=provider.name,
            result=result,
            context_output=ctx_out,
        )
        self.assertFalse(run["authoritative"])
        self.assertEqual(2, run["attempt_count"])
        self.assertIsNotNone(run["context_output"])
        self.assertNotIn("context_output", run["candidate"])
        mismatches = X.verify_history(
            run,
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=SCHEMA,
            allowed_predicates=ALLOWED_PREDICATES,
        )
        self.assertEqual([], mismatches)

    def test_tampered_history_is_detected(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider([json.dumps(bundle, ensure_ascii=False)])
        result = X.extract_chunk(
            provider,
            make_request(),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
        )
        run = X.build_chunk_run(
            request=make_request(), provider_name=provider.name, result=result
        )
        run["attempts"][0]["validation"]["passed"] = False
        mismatches = X.verify_history(
            run,
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
        )
        self.assertTrue(mismatches)

    def test_accepted_checkpoint_names_producing_run(self) -> None:
        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        checkpoint = X.build_accepted_checkpoint(
            candidate=bundle,
            run_attempt=2,
            locator={"chunk_index": 0},
        )
        self.assertTrue(checkpoint["accepted"])
        self.assertEqual(2, checkpoint["produced_by_run_attempt"])
        self.assertFalse(checkpoint["authoritative"])
        with self.assertRaises(PersistenceError):
            X.build_accepted_checkpoint(
                candidate=bundle, run_attempt=0, locator={"chunk_index": 0}
            )


class FixtureChainTests(unittest.TestCase):
    def test_fixture_chain_extracts_with_inherited_year(self) -> None:
        import segmentation as S  # noqa: E402

        text = (FIXTURE_DIR / "raw.txt").read_text(encoding="utf-8")
        spec = json.loads((FIXTURE_DIR / "extraction.json").read_text(encoding="utf-8"))
        config = S.SegmentationConfig(**spec["segmentation_config"])
        source_sha = S.sha256_text(text)
        plan = S.segment_revision(text, source_sha, config)
        self.assertGreaterEqual(len(plan.chunks), spec["expect"]["min_chunks"])
        pairs = S.context_chain(plan, text, config)
        doc = spec["document"]

        for position, chunk in enumerate(plan.chunks):
            chunk_text = text[chunk.source_start : chunk.source_end]
            pair = pairs[position]
            # Chain invariant: chunk N+1 inherits exactly chunk N's output.
            if position > 0:
                self.assertEqual(pairs[position - 1]["output"], pair["input"])
            if position > 0:
                inherited = pair["output"]["inherited_time"]
                self.assertTrue(
                    any(
                        item["text"] == spec["expect"]["explicit_time"]
                        and item["scope"] == "inherited"
                        for item in inherited
                    )
                )
            else:
                self.assertTrue(
                    any(
                        item["text"] == spec["expect"]["explicit_time"]
                        and item["scope"] == "explicit"
                        for item in pair["output"]["inherited_time"]
                    )
                )
            locator = S.chunk_locator(
                job_id=__import__("uuid").uuid4(),
                revision_id=__import__("uuid").uuid4(),
                revision_no=1,
                source_sha256=source_sha,
                chunk=chunk,
                section_id=None,
            )
            request = X.build_chunk_request(
                chunk_text=chunk_text,
                section={"label": spec["section_label"], "kind": "document",
                         "section_index": chunk.section_index},
                document=doc,
                context_input=pair["input"],
                boundary_head=chunk.boundary_head,
                boundary_tail=chunk.boundary_tail,
                locator=locator,
            )
            # Canned candidate grounded in the real slice: first sentence
            # as evidence, explicit time only where the year is local.
            first_sentence = chunk_text.split("。")[0] + "。"
            is_explicit = spec["expect"]["explicit_time"] in chunk_text
            fields = [] if is_explicit else ["era", "era_year"]
            bundle = valid_bundle(
                chunk_text,
                first_sentence,
                time_original=spec["expect"]["explicit_time"],
                inherited_fields=fields,
                year=spec["expect"]["verified_year"],
                entity_name="曹操" if "曹操" in chunk_text or "操" in chunk_text else "孫權",
                entity_mention="曹操" if "曹操" in chunk_text else ("操" if "操" in chunk_text else "孫權"),
                predicate="moved_to" if "至" in first_sentence else "died",
            )
            # Claim event title grounding: keep the generic title only
            # when it cannot contradict the chunk month check.
            bundle["events"][0]["title"] = first_sentence[:12]
            bundle["events"][0]["time"] = None
            provider = FakeProvider([json.dumps(bundle, ensure_ascii=False)])
            result = X.extract_chunk(
                provider,
                request,
                chunk_text=chunk_text,
                context_input=pair["input"],
                section_label=spec["section_label"],
                document=doc,
                schema=SCHEMA,
                allowed_predicates=ALLOWED_PREDICATES,
            )
            self.assertTrue(
                result["accepted"],
                f"chunk {position}: {result['error']}",
            )
            run = X.build_chunk_run(
                request=request,
                provider_name=provider.name,
                result=result,
                context_output=pair["output"],
            )
            # ContextState travels beside the candidate, never inside it.
            self.assertNotIn("inherited_time", run["candidate"])
            self.assertEqual(
                pair["output"]["inherited_time"],
                run["context_output"]["inherited_time"],
            )
            mismatches = X.verify_history(
                run,
                chunk_text=chunk_text,
                context_input=pair["input"],
                section_label=spec["section_label"],
                document=doc,
                schema=SCHEMA,
                allowed_predicates=ALLOWED_PREDICATES,
            )
            self.assertEqual([], mismatches)


if __name__ == "__main__":
    unittest.main()
