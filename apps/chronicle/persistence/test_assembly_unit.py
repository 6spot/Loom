"""Unit tests for Chronicle C1-T7 source assembly (no PostgreSQL).

Covers deterministic merging of validated chunk outputs into one
C0-compatible source bundle, revision-scoped provenance, conservative
within-book Entity/Event linking without canonical assignment,
boundary-duplicate suppression with evidence, ambiguity preservation,
and byte-deterministic reruns.
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

import assembly as A  # noqa: E402
from common import PersistenceError, canonical_json_bytes  # noqa: E402

SCHEMA = json.loads(
    (HERE.parent / "ingestion" / "schemas" / "chronicle-v0.1.schema.json").read_text(
        encoding="utf-8"
    )
)


def _meta() -> dict:
    return {"method": "model", "job_id": "c1t7-unit", "confidence": 0.8}


def _source(title: str = "三國志·魏書·武帝紀（節選）") -> dict:
    return {
        "temp_id": "src_001",
        "kind": "source",
        "source_type": "book",
        "title": title,
        "author": "陳壽",
        "language": "lzh",
        "extraction": _meta(),
    }


def _entity(
    temp_id: str,
    name: str,
    etype: str = "person",
    mentions: list[str] | None = None,
    aliases: list[str] | None = None,
) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "entity",
        "type": etype,
        "canonical_name": name,
        "aliases": list(aliases or []),
        "mentions": [{"text": text} for text in (mentions if mentions is not None else [name])],
        "resolution": {"status": "unresolved"},
        "extraction": _meta(),
    }


def _event(
    temp_id: str,
    title: str,
    etype: str = "other",
    participants: list[str] | None = None,
    places: list[str] | None = None,
    time: dict | None = None,
) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "event",
        "type": etype,
        "title": title,
        "time": time,
        "participants": [
            {"entity_ref": ref, "role": "subject"} for ref in (participants or [])
        ],
        "places": list(places or []),
        "extraction": _meta(),
    }


def _claim(
    temp_id: str,
    subject: str,
    predicate: str,
    evidence: str,
    obj: dict | None = None,
    time: dict | None = None,
) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "claim",
        "subject": {"kind": "entity_ref", "ref": subject},
        "predicate": predicate,
        "object": obj,
        "time": time,
        "evidence": {
            "text": evidence,
            "source_ref": "src_001",
            "locator": {"work": "三國志", "section": "全文"},
        },
        "assessment": {"status": "unassessed"},
        "extraction": _meta(),
    }


def _locator(
    chunk_index: int,
    revision_id: str = "rev-1",
    source_start: int | None = None,
    source_end: int | None = None,
    overlap_prev_chars: int = 0,
) -> dict:
    start = chunk_index * 10 if source_start is None else source_start
    end = chunk_index * 10 + 10 if source_end is None else source_end
    return {
        "job_id": "job-1",
        "revision_id": revision_id,
        "revision_no": 1,
        "source_sha256": "a" * 64,
        "section_index": 0,
        "section_id": None,
        "chunk_index": chunk_index,
        "source_start": start,
        "source_end": end,
        "offset_unit": "chars-normalized-utf8",
        "content_sha256": "b" * 64,
        "overlap_prev_chars": overlap_prev_chars,
        "segmentation_version": "c1t5-seg-v1",
    }


def _chunk(
    chunk_index: int,
    *,
    entities: list[dict] | None = None,
    events: list[dict] | None = None,
    claims: list[dict] | None = None,
    warnings: list[dict] | None = None,
    run_attempt: int = 1,
    revision_id: str = "rev-1",
    locator: dict | None = None,
) -> dict:
    return {
        "chunk_index": chunk_index,
        "candidate": {
            "schema_version": "0.1",
            "source": _source(),
            "entities": entities or [],
            "events": events or [],
            "claims": claims or [],
            "warnings": warnings or [],
        },
        "locator": locator if locator is not None else _locator(chunk_index, revision_id),
        "run_attempt": run_attempt,
        "model_version": "fake-model-v1",
    }


def _assemble(*chunks: dict) -> dict:
    return A.assemble_revision(
        chunks=list(chunks),
        document={"title": "三國志·魏書·武帝紀（節選）"},
        revision={"revision_id": "rev-1", "revision_no": 1, "source_sha256": "a" * 64},
    )


class AssemblyBundleTests(unittest.TestCase):
    def test_two_chunks_merge_into_one_schema_valid_bundle(self) -> None:
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "曹操")],
                   claims=[_claim("clm_001", "ent_001", "died", "操薨")]),
            _chunk(1, entities=[_entity("ent_001", "孫權")],
                   claims=[_claim("clm_001", "ent_001", "appointed", "命瑜督")]),
        )
        bundle = result["bundle"]
        self.assertEqual("0.1", bundle["schema_version"])
        self.assertEqual("src_001", bundle["source"]["temp_id"])
        self.assertEqual(2, len(bundle["entities"]))
        self.assertEqual(2, len(bundle["claims"]))
        # Revision-scoped IDs satisfy the C0 temp-ID pattern and never collide.
        refs = [r["temp_id"] for r in bundle["entities"] + bundle["claims"]]
        self.assertEqual(len(set(refs)), len(refs))
        for ref in refs:
            self.assertRegex(ref, r"^(ent|clm)_[0-9]{3,}$")
        # Canonical schema accepts the assembled bundle.
        from jsonschema import Draft202012Validator, FormatChecker

        errors = list(Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(bundle))
        self.assertEqual([], errors)
        # No canonical identity anywhere.
        for record in [bundle["source"], *bundle["entities"], *bundle["claims"]]:
            self.assertNotIn("id", record)

    def test_provenance_maps_every_record_to_chunk_and_run(self) -> None:
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "曹操")], run_attempt=2),
            _chunk(1, entities=[_entity("ent_001", "孫權")], run_attempt=1),
        )
        provenance = result["report"]["record_provenance"]
        cao = result["bundle"]["entities"][0]["temp_id"]
        sun = result["bundle"]["entities"][1]["temp_id"]
        self.assertEqual(0, provenance[cao]["chunk_index"])
        self.assertEqual("ent_001", provenance[cao]["chunk_temp_id"])
        self.assertEqual(2, provenance[cao]["run_attempt"])
        self.assertEqual("fake-model-v1", provenance[cao]["model_version"])
        self.assertEqual("rev-1", provenance[cao]["revision_id"])
        self.assertEqual("a" * 64, provenance[cao]["source_sha256"])
        self.assertEqual(1, provenance[sun]["chunk_index"])
        self.assertIn("src_001", provenance)

    def test_disjoint_same_name_entities_stay_uncertain(self) -> None:
        # D-1 regression: a shared name alone never proves identity. Two
        # disjoint-chunk records for the same surface stay uncertain,
        # distinct, and reviewable.
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "曹操")]),
            _chunk(2, entities=[_entity("ent_001", "曹操")]),
        )
        links = result["within_book_links"]["entity_links"]
        self.assertEqual(1, len(links))
        self.assertEqual("uncertain", links[0]["decision"])
        self.assertEqual("wc_001", links[0]["candidate_id"])
        self.assertEqual(2, len(result["bundle"]["entities"]))
        for entity in result["bundle"]["entities"]:
            self.assertEqual("unresolved", entity["resolution"]["status"])
            self.assertNotIn("id", entity)
        self.assertIn("wc_001", result["report"]["unresolved_links"])
        self.assertIn(
            "unresolved_within_book_identity",
            [w["type"] for w in result["bundle"]["warnings"]],
        )

    def test_exact_name_plus_shared_alias_links_same_entity(self) -> None:
        # Stronger evidence than the name alone: exact canonical-name
        # agreement plus a second shared stable surface.
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "曹操", aliases=["太祖"])]),
            _chunk(2, entities=[_entity("ent_001", "曹操", aliases=["太祖"])]),
        )
        links = result["within_book_links"]["entity_links"]
        self.assertEqual(1, len(links))
        self.assertEqual("same_entity", links[0]["decision"])
        # Linking never merges records or assigns canonical IDs.
        self.assertEqual(2, len(result["bundle"]["entities"]))
        for entity in result["bundle"]["entities"]:
            self.assertEqual("unresolved", entity["resolution"]["status"])
            self.assertNotIn("id", entity)

    def test_suppressed_duplicate_proves_subject_coreference(self) -> None:
        # When two claims are verified to be the same boundary-duplicate
        # assertion, their entity subjects denote the same participant.
        overlap0 = _locator(0, source_start=0, source_end=20)
        overlap1 = _locator(1, source_start=10, source_end=30)
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "曹操")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")],
                   locator=overlap0),
            _chunk(1, entities=[_entity("ent_001", "曹操")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")],
                   locator=overlap1),
        )
        self.assertEqual(1, len(result["bundle"]["claims"]))
        links = result["within_book_links"]["entity_links"]
        self.assertEqual(1, len(links))
        self.assertEqual("same_entity", links[0]["decision"])
        self.assertIn("duplicate", links[0]["rationale"])

    def test_shared_alias_without_name_agreement_stays_uncertain(self) -> None:
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "曹公", mentions=["曹公", "公"])]),
            _chunk(1, entities=[_entity("ent_001", "曹操", mentions=["曹操", "公"])]),
        )
        links = result["within_book_links"]["entity_links"]
        self.assertEqual(1, len(links))
        self.assertEqual("uncertain", links[0]["decision"])
        self.assertEqual(2, len(result["bundle"]["entities"]))
        self.assertIn("wc_001", result["report"]["unresolved_links"])

    def test_same_name_different_type_kept_distinct_with_warning(self) -> None:
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "江陵", "place")]),
            _chunk(1, entities=[_entity("ent_001", "江陵", "person")]),
        )
        self.assertEqual([], result["within_book_links"]["entity_links"])
        self.assertEqual(2, len(result["bundle"]["entities"]))
        kinds = [w["type"] for w in result["bundle"]["warnings"]]
        self.assertIn("ambiguous_same_name", kinds)

    def test_overlapping_duplicate_claim_suppressed_with_evidence(self) -> None:
        overlap0 = _locator(0, source_start=0, source_end=20)
        overlap1 = _locator(1, source_start=10, source_end=30)
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")],
                   locator=overlap0),
            _chunk(1, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")],
                   locator=overlap1),
        )
        bundle = result["bundle"]
        # Duplicates collapse to one claim; the entity link remains.
        self.assertEqual(1, len(bundle["claims"]))
        self.assertEqual("八月，表卒", bundle["claims"][0]["evidence"]["text"])
        self.assertEqual(1, result["report"]["counts"]["suppressed_claims"])
        suppressions = result["report"]["duplicate_suppressions"]
        self.assertEqual(1, len(suppressions))
        self.assertEqual("claim", suppressions[0]["kind"])
        self.assertEqual("same_occurrence", suppressions[0]["decision"])
        self.assertEqual("died", suppressions[0]["signature"]["predicate"])
        self.assertIn("duplicate_suppressed", [w["type"] for w in bundle["warnings"]])

    def test_adjacent_nonoverlapping_repeat_preserved_distinct(self) -> None:
        # D-2 regression: adjacent spans [0,10]/[10,20] share no source
        # bytes, so an identical assertion is a genuine repeated passage
        # and must survive as two distinct occurrences.
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")]),
            _chunk(1, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")]),
        )
        self.assertEqual(2, len(result["bundle"]["claims"]))
        self.assertEqual(0, result["report"]["counts"]["suppressed_claims"])
        repeats = result["report"]["preserved_repeats"]
        self.assertEqual(1, len(repeats))
        self.assertIn("no verified span overlap", repeats[0]["reason"])
        self.assertIn(
            "repeated_assertion_preserved",
            [w["type"] for w in result["bundle"]["warnings"]],
        )

    def test_boundary_overlap_chars_suppress_duplicate(self) -> None:
        # Declared boundary overlap is sufficient duplicate evidence even
        # when the recorded spans merely touch.
        head = _locator(0, source_start=0, source_end=10)
        tail = _locator(1, source_start=10, source_end=20, overlap_prev_chars=4)
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")],
                   locator=head),
            _chunk(1, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")],
                   locator=tail),
        )
        self.assertEqual(1, len(result["bundle"]["claims"]))
        self.assertEqual(1, result["report"]["counts"]["suppressed_claims"])

    def test_genuine_repeat_in_nonadjacent_chunks_kept_distinct(self) -> None:
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")]),
            _chunk(1, entities=[_entity("ent_001", "孫權")]),
            _chunk(2, entities=[_entity("ent_001", "劉表")],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")]),
        )
        # Non-adjacent repetition is a genuine repeated occurrence candidate:
        # both claims survive and no silent suppression happens.
        self.assertEqual(2, len(result["bundle"]["claims"]))
        self.assertEqual(0, result["report"]["counts"]["suppressed_claims"])
        self.assertEqual(1, len(result["report"]["preserved_repeats"]))

    def test_overlapping_duplicate_event_suppressed_and_claim_rewired(self) -> None:
        evt0 = _event("evt_001", "表卒", "death", participants=["ent_001"])
        evt1 = _event("evt_001", "表卒", "death", participants=["ent_001"])
        overlap0 = _locator(0, source_start=0, source_end=20)
        overlap1 = _locator(1, source_start=10, source_end=30)
        follower = _claim("clm_001", "ent_001", "appointed", "表卒之後")
        follower["subject"] = {"kind": "event_ref", "ref": "evt_001"}
        result = _assemble(
            _chunk(0, entities=[_entity("ent_001", "劉表")], events=[evt0],
                   claims=[_claim("clm_001", "ent_001", "died", "八月，表卒")],
                   locator=overlap0),
            _chunk(1, entities=[_entity("ent_001", "劉表")], events=[evt1],
                   claims=[follower],
                   locator=overlap1),
        )
        self.assertEqual(1, len(result["bundle"]["events"]))
        self.assertEqual(1, result["report"]["counts"]["suppressed_events"])
        kept = result["bundle"]["events"][0]["temp_id"]
        self.assertEqual(kept, result["report"]["duplicate_suppressions"][0]["kept_ref"])
        self.assertEqual(2, len(result["bundle"]["claims"]))
        follower_out = [
            c for c in result["bundle"]["claims"]
            if c["predicate"] == "appointed"
        ][0]
        self.assertEqual(kept, follower_out["subject"]["ref"])

    def test_rerun_is_byte_deterministic(self) -> None:
        chunks = [
            _chunk(1, entities=[_entity("ent_001", "孫權")],
                   claims=[_claim("clm_001", "ent_001", "appointed", "命瑜督")]),
            _chunk(0, entities=[_entity("ent_001", "曹操")],
                   claims=[_claim("clm_001", "ent_001", "died", "操薨")]),
        ]
        first = _assemble(*chunks)
        second = _assemble(*copy.deepcopy(chunks))
        self.assertEqual(
            canonical_json_bytes(first), canonical_json_bytes(second)
        )


class AssemblyFailureTests(unittest.TestCase):
    def test_empty_input_fails_closed(self) -> None:
        with self.assertRaises(PersistenceError):
            A.assemble_revision(chunks=[])

    def test_mixed_revisions_fail_closed(self) -> None:
        with self.assertRaises(PersistenceError):
            _assemble(
                _chunk(0, entities=[_entity("ent_001", "曹操")]),
                _chunk(1, entities=[_entity("ent_001", "曹操")], revision_id="rev-2"),
            )

    def test_duplicate_chunk_index_fails_closed(self) -> None:
        with self.assertRaises(PersistenceError):
            _assemble(
                _chunk(0, entities=[_entity("ent_001", "曹操")]),
                _chunk(0, entities=[_entity("ent_001", "孫權")]),
            )

    def test_canonical_id_in_chunk_fails_closed(self) -> None:
        bad = _entity("ent_001", "曹操")
        bad["id"] = "01900000-0000-7000-8000-000000000000"
        with self.assertRaises(PersistenceError):
            _assemble(_chunk(0, entities=[bad]))

    def test_chunk_without_candidate_fails_closed(self) -> None:
        chunk = _chunk(0)
        del chunk["candidate"]
        with self.assertRaises(PersistenceError):
            _assemble(chunk)


if __name__ == "__main__":
    unittest.main()
