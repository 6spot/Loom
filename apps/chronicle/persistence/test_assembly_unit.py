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


def _assemble_no_revision(*chunks: dict) -> dict:
    return A.assemble_revision(chunks=list(chunks))


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

    def test_nested_canonical_id_fails_closed(self) -> None:
        # D-3 regression: the C0 schema permits nested resolution
        # identity, so assembly must reject it explicitly instead of
        # copying a canonical assignment into the source-owned bundle.
        bad = _entity("ent_001", "曹操")
        bad["resolution"] = {
            "status": "resolved",
            "canonical_id": "01900000-0000-7000-8000-000000000000",
        }
        with self.assertRaises(PersistenceError):
            _assemble(_chunk(0, entities=[bad]))

    def test_nested_candidate_ids_fail_closed(self) -> None:
        bad = _entity("ent_001", "曹操")
        bad["resolution"] = {
            "status": "ambiguous",
            "candidate_ids": ["01900000-0000-7000-8000-000000000001"],
        }
        with self.assertRaises(PersistenceError):
            _assemble(_chunk(0, entities=[bad]))

    def test_non_unresolved_status_fails_closed(self) -> None:
        bad = _entity("ent_001", "曹操")
        bad["resolution"] = {"status": "resolved"}
        with self.assertRaises(PersistenceError):
            _assemble(_chunk(0, entities=[bad]))

    def test_mixed_revisions_without_revision_arg_fails_closed(self) -> None:
        # D-4 regression: the one-revision contract must hold even when
        # the optional public `revision` argument is omitted.
        with self.assertRaises(PersistenceError):
            _assemble_no_revision(
                _chunk(0, entities=[_entity("ent_001", "曹操")]),
                _chunk(1, entities=[_entity("ent_001", "曹操")], revision_id="rev-2"),
            )

    def test_mixed_source_hashes_without_revision_arg_fails_closed(self) -> None:
        other_locator = _locator(1)
        other_locator["source_sha256"] = "c" * 64
        with self.assertRaises(PersistenceError):
            _assemble_no_revision(
                _chunk(0, entities=[_entity("ent_001", "曹操")]),
                _chunk(1, entities=[_entity("ent_001", "曹操")], locator=other_locator),
            )

    def test_single_revision_without_revision_arg_assembles(self) -> None:
        result = _assemble_no_revision(
            _chunk(0, entities=[_entity("ent_001", "曹操")]),
            _chunk(1, entities=[_entity("ent_001", "孫權")]),
        )
        self.assertEqual("rev-1", result["report"]["revision"]["revision_id"])
        self.assertEqual("a" * 64, result["report"]["revision"]["source_sha256"])

    def test_chunk_without_candidate_fails_closed(self) -> None:
        chunk = _chunk(0)
        del chunk["candidate"]
        with self.assertRaises(PersistenceError):
            _assemble(chunk)


# ---------------------------------------------------------------------------
# Chapter assembly (C2-R1-T07): assemble_chapters(accepted_artifacts, plan)
# ---------------------------------------------------------------------------

_CHAPTER_REVISION = "rev-chapters-1"
_CHAPTER_SOURCE_SHA = "a" * 64
_CHAPTER_NORMALIZED_SHA = "a" * 64


def _chapter_plan(chapter_ids: list[str] | None = None) -> dict:
    ids = chapter_ids if chapter_ids is not None else ["ch_000", "ch_001"]
    chapters = [
        {
            "chapter_id": chapter_id,
            "chapter_index": index,
            "title": f"Chapter {index}",
            "start": index * 10,
            "end": (index + 1) * 10,
        }
        for index, chapter_id in enumerate(ids)
    ]
    return {
        "version": "c2r1-chapters-v1",
        "plan_sha256": "p" * 64,
        "revision_id": _CHAPTER_REVISION,
        "source_sha256": _CHAPTER_SOURCE_SHA,
        "normalized_sha256": _CHAPTER_NORMALIZED_SHA,
        "chapters": chapters,
    }


def _chapter_source(title: str) -> dict:
    source = _source(title=title)
    source["language"] = "zh-CN"
    return source


def _chapter_translation(
    *,
    block_id: str = "t_001",
    text: str = "白話譯文",
    entity_refs: list[str] | None = None,
    event_refs: list[str] | None = None,
) -> dict:
    return {
        "language": "zh-CN",
        "blocks": [
            {
                "block_id": block_id,
                "text": text,
                "source_block_ids": ["b_001"],
                "entity_refs": [{"kind": "entity", "ref": ref} for ref in (entity_refs or [])],
                "event_refs": [{"kind": "event", "ref": ref} for ref in (event_refs or [])],
            }
        ],
    }


def _chapter_mentions(targets: list[str] | None = None) -> list[dict]:
    mentions = []
    for position, target in enumerate(targets or []):
        mentions.append(
            {
                "mention_id": f"m_{position + 1:03d}",
                "surface": "曹操",
                "contextual": False,
                "status": "resolved",
                "target_ref": target,
                "candidate_refs": [],
                "selection": {
                    "first_block_id": "b_001",
                    "last_block_id": "b_001",
                    "quote": "曹操",
                    "occurrence": 1,
                },
            }
        )
    return mentions


def _chapter_record_sources(refs: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "record_ref": ref,
            "record_kind": kind,
            "selections": [
                {
                    "first_block_id": "b_001",
                    "last_block_id": "b_001",
                    "quote": "曹操",
                    "occurrence": 1,
                }
            ],
        }
        for ref, kind in refs
    ]


def _chapter_anchors(chapter_id: str, *, count: int = 1) -> list[dict]:
    return [
        {
            "anchor_id": f"anc_{chapter_id}_{position}",
            "revision_id": _CHAPTER_REVISION,
            "chapter_id": chapter_id,
            "source_sha256": _CHAPTER_SOURCE_SHA,
            "normalized_sha256": _CHAPTER_NORMALIZED_SHA,
            "first_block_id": "b_001",
            "last_block_id": "b_001",
            "quote": "曹操",
            "quote_sha256": "q" * 64,
            "occurrence": 1,
            "start": position,
            "end": position + 2,
        }
        for position in range(count)
    ]


def _chapter_artifact(
    chapter_id: str,
    chapter_index: int,
    *,
    entities: list[dict] | None = None,
    events: list[dict] | None = None,
    claims: list[dict] | None = None,
    translation: dict | None = None,
    mentions: list[dict] | None = None,
    record_sources: list[dict] | None = None,
    revision_id: str = _CHAPTER_REVISION,
    title: str | None = None,
) -> dict:
    entities = entities if entities is not None else [_entity("ent_001", "曹操")]
    events = events if events is not None else []
    claims = claims if claims is not None else []
    default_refs = [(e["temp_id"], "entity") for e in entities]
    default_refs += [(e["temp_id"], "event") for e in events]
    default_refs += [(c["temp_id"], "claim") for c in claims]
    if translation is None:
        translation = _chapter_translation(
            entity_refs=[e["temp_id"] for e in entities],
            event_refs=[e["temp_id"] for e in events],
        )
    if mentions is None:
        mentions = _chapter_mentions([entities[0]["temp_id"]] if entities else [])
    if record_sources is None:
        record_sources = _chapter_record_sources(default_refs)
    candidate = {
        "schema": "chronicle.chapter-candidate",
        "version": "0.1",
        "chapter_id": chapter_id,
        "bundle": {
            "schema_version": "0.1",
            "source": _chapter_source(title or f"Title {chapter_index}"),
            "entities": entities,
            "events": events,
            "claims": claims,
            "warnings": [],
        },
        "translation": translation,
        "mentions": mentions,
        "record_sources": record_sources,
        "warnings": [],
    }
    from common import sha256_json as _sha256_json

    return {
        "schema": "chronicle.chapter-artifact",
        "version": "0.1",
        "chapter_id": chapter_id,
        "revision_id": revision_id,
        "source_sha256": _CHAPTER_SOURCE_SHA,
        "normalized_sha256": _CHAPTER_NORMALIZED_SHA,
        "candidate": candidate,
        "candidate_sha256": _sha256_json(candidate),
        "anchors": _chapter_anchors(chapter_id, count=max(len(default_refs), 1)),
        "request_fingerprint": f"fp-{chapter_id}",
        "producing_run": {"run_id": f"run-{chapter_id}", "model": "m", "prompt_schema_version": "v"},
    }


def _assemble_chapters(*artifacts: dict, plan: dict | None = None) -> dict:
    ids = [a["chapter_id"] for a in artifacts]
    return A.assemble_chapters(
        accepted_artifacts=list(artifacts),
        chapter_plan=plan if plan is not None else _chapter_plan(ids),
    )


class ChapterAssemblyBundleTests(unittest.TestCase):
    def test_same_local_ids_never_collide_and_refs_closed(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        first = _chapter_artifact(
            "ch_000", 0,
            entities=[_entity("ent_001", "曹操")],
            claims=[_claim("clm_001", "ent_001", "died", "操薨")],
        )
        second = _chapter_artifact(
            "ch_001", 1,
            entities=[_entity("ent_001", "孫權")],
            claims=[_claim("clm_001", "ent_001", "appointed", "命瑜督")],
        )
        result = _assemble_chapters(first, second, plan=plan)
        bundle = result["bundle"]
        self.assertEqual("src_001", bundle["source"]["temp_id"])
        self.assertEqual(2, len(bundle["entities"]))
        self.assertEqual(2, len(bundle["claims"]))
        refs = [r["temp_id"] for r in bundle["entities"] + bundle["claims"]]
        self.assertEqual(len(set(refs)), len(refs))
        # Revision-scoped IDs keep chapter namespaces apart.
        self.assertEqual("ent_000001", bundle["entities"][0]["temp_id"])
        self.assertEqual("ent_001001", bundle["entities"][1]["temp_id"])
        # Cross-type refs stay closed after the same mapping.
        entity_set = {e["temp_id"] for e in bundle["entities"]}
        for claim in bundle["claims"]:
            self.assertIn(claim["subject"]["ref"], entity_set)
            self.assertEqual("src_001", claim["evidence"]["source_ref"])
        from jsonschema import Draft202012Validator, FormatChecker

        errors = list(Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(bundle))
        self.assertEqual([], errors)
        for record in [bundle["source"], *bundle["entities"], *bundle["claims"]]:
            self.assertNotIn("id", record)

    def test_translation_and_mentions_point_to_correct_chapter_objects(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        result = _assemble_chapters(
            _chapter_artifact("ch_000", 0, entities=[_entity("ent_001", "曹操")]),
            _chapter_artifact("ch_001", 1, entities=[_entity("ent_001", "孫權")]),
            plan=plan,
        )
        blocks = result["translation_blocks"]
        self.assertEqual(2, len(blocks))
        self.assertEqual("ch_000", blocks[0]["chapter_id"])
        self.assertEqual("ent_000001", blocks[0]["entity_refs"][0]["ref"])
        self.assertEqual("ch_001", blocks[1]["chapter_id"])
        self.assertEqual("ent_001001", blocks[1]["entity_refs"][0]["ref"])
        mentions = result["mentions"]
        self.assertEqual(2, len(mentions))
        by_chapter = {m["chapter_id"]: m for m in mentions}
        self.assertEqual("ent_000001", by_chapter["ch_000"]["target_ref"])
        self.assertEqual("ent_001001", by_chapter["ch_001"]["target_ref"])
        # Anchors never cross chapters.
        for anchor in result["anchors"]:
            self.assertEqual(anchor["chapter_id"] in ("ch_000", "ch_001"), True)
        ch0_anchors = [a for a in result["anchors"] if a["chapter_id"] == "ch_000"]
        ch1_anchors = [a for a in result["anchors"] if a["chapter_id"] == "ch_001"]
        self.assertTrue(ch0_anchors and ch1_anchors)
        # chapter_by_ref / local_to_revision serve T08/T10 lookup.
        report = result["report"]
        self.assertEqual("ch_000", report["chapter_by_ref"]["ent_000001"])
        self.assertEqual("ch_001", report["chapter_by_ref"]["ent_001001"])
        self.assertEqual("ent_000001", report["local_to_revision"]["(0,ent_001)"])
        self.assertEqual("ent_001001", report["local_to_revision"]["(1,ent_001)"])
        self.assertIn("ch_000", report["chapter_artifacts"])
        self.assertIn("ch_001", report["chapter_artifacts"])
        self.assertIn("ent_000001", report["record_provenance"])
        self.assertIn("src_001", report["record_provenance"])

    def test_translation_without_claim_is_preserved(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        first = _chapter_artifact("ch_000", 0, entities=[_entity("ent_001", "曹操")], claims=[])
        first["candidate"]["record_sources"] = _chapter_record_sources([("ent_001", "entity")])
        from common import sha256_json as _sha256_json

        first["candidate_sha256"] = _sha256_json(first["candidate"])
        result = _assemble_chapters(
            first,
            _chapter_artifact("ch_001", 1, entities=[_entity("ent_001", "孫權")], claims=[]),
            plan=plan,
        )
        # No claims anywhere, but both translation blocks survive.
        self.assertEqual(0, len(result["bundle"]["claims"]))
        self.assertEqual(2, len(result["translation_blocks"]))
        texts = sorted(b["text"] for b in result["translation_blocks"])
        self.assertEqual(["白話譯文", "白話譯文"], texts)

    def test_intra_chapter_shared_object_not_split(self) -> None:
        plan = _chapter_plan(["ch_000"])
        artifact = _chapter_artifact(
            "ch_000", 0,
            entities=[_entity("ent_001", "曹操")],
            claims=[
                _claim("clm_001", "ent_001", "died", "操薨"),
                _claim("clm_002", "ent_001", "ruled", "操領兗州"),
            ],
        )
        result = _assemble_chapters(artifact, plan=plan)
        self.assertEqual(1, len(result["bundle"]["entities"]))
        self.assertEqual(2, len(result["bundle"]["claims"]))
        entity_ref = result["bundle"]["entities"][0]["temp_id"]
        for claim in result["bundle"]["claims"]:
            self.assertEqual(entity_ref, claim["subject"]["ref"])

    def test_cross_chapter_same_name_stays_independent_single_source(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        result = _assemble_chapters(
            _chapter_artifact("ch_000", 0, entities=[_entity("ent_001", "曹操")]),
            _chapter_artifact("ch_001", 1, entities=[_entity("ent_001", "曹操")]),
            plan=plan,
        )
        # Same surface across chapters: two independent revision refs, no
        # automatic merge at this stage (T08 decides candidacy later).
        self.assertEqual(2, len(result["bundle"]["entities"]))
        refs = [e["temp_id"] for e in result["bundle"]["entities"]]
        self.assertNotEqual(refs[0], refs[1])
        # One revision keeps exactly one source bundle.
        self.assertEqual("src_001", result["bundle"]["source"]["temp_id"])
        sources = [r for r in [result["bundle"]["source"]] if r["temp_id"] == "src_001"]
        self.assertEqual(1, len(sources))

    def test_rerun_is_byte_deterministic_regardless_of_input_order(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        first = _chapter_artifact("ch_000", 0, entities=[_entity("ent_001", "曹操")])
        second = _chapter_artifact("ch_001", 1, entities=[_entity("ent_001", "孫權")])
        forward = _assemble_chapters(first, second, plan=plan)
        backward = _assemble_chapters(second, first, plan=plan)
        repeated = _assemble_chapters(copy.deepcopy(first), copy.deepcopy(second), plan=copy.deepcopy(plan))
        self.assertEqual(canonical_json_bytes(forward), canonical_json_bytes(backward))
        self.assertEqual(canonical_json_bytes(forward), canonical_json_bytes(repeated))


class ChapterAssemblyFailureTests(unittest.TestCase):
    def test_missing_chapter_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        with self.assertRaises(PersistenceError):
            _assemble_chapters(_chapter_artifact("ch_000", 0), plan=plan)

    def test_extra_chapter_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000"])
        with self.assertRaises(PersistenceError):
            _assemble_chapters(
                _chapter_artifact("ch_000", 0),
                _chapter_artifact("ch_001", 1),
                plan=plan,
            )

    def test_duplicate_chapter_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        with self.assertRaises(PersistenceError):
            _assemble_chapters(
                _chapter_artifact("ch_000", 0),
                _chapter_artifact("ch_000", 0),
                plan=plan,
            )

    def test_mixed_revision_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        with self.assertRaises(PersistenceError):
            _assemble_chapters(
                _chapter_artifact("ch_000", 0),
                _chapter_artifact("ch_001", 1, revision_id="rev-other"),
                plan=plan,
            )

    def test_unaccepted_product_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        bad = _chapter_artifact("ch_000", 0)
        bad["schema"] = "chronicle.chapter-candidate"
        with self.assertRaises(PersistenceError):
            _assemble_chapters(bad, _chapter_artifact("ch_001", 1), plan=plan)

    def test_tampered_candidate_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        bad = _chapter_artifact("ch_000", 0)
        bad["candidate"]["translation"]["blocks"][0]["text"] = "纂改後的譯文"
        with self.assertRaises(PersistenceError):
            _assemble_chapters(bad, _chapter_artifact("ch_001", 1), plan=plan)

    def test_cross_chapter_anchor_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000", "ch_001"])
        bad = _chapter_artifact("ch_000", 0)
        bad["anchors"][0]["chapter_id"] = "ch_001"
        with self.assertRaises(PersistenceError):
            _assemble_chapters(bad, _chapter_artifact("ch_001", 1), plan=plan)

    def test_dangling_translation_ref_fails_closed(self) -> None:
        plan = _chapter_plan(["ch_000"])
        artifact = _chapter_artifact("ch_000", 0, entities=[_entity("ent_001", "曹操")])
        artifact["candidate"]["translation"]["blocks"][0]["entity_refs"] = [
            {"kind": "entity", "ref": "ent_999"}
        ]
        with self.assertRaises(PersistenceError):
            _assemble_chapters(artifact, plan=plan)


if __name__ == "__main__":
    unittest.main()
