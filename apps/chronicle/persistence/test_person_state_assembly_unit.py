"""Unit tests for Chronicle C2-R3-T03 person-state evidence assembly.

Covers the third-round assembly contract from ``person-state-reading.md``
sections 3-4: the accepted 0.3 ``person_states`` block of every chapter is
lifted into one revision namespace, phase/fact/order/continuity/disagreement
local IDs get a chapter-bound namespace, entity/event/Claim references reuse
the same ``(chapter_index, local_ref) -> revision_ref`` map as every other
chapter reference, ``unit_phases`` stay bound to the original translation
block/reading unit, and origin chapter/ref/hash/anchors survive as evidence.
Mixed generations, missing chapters, tampered hashes, dangling refs and
duplicate keys fail closed, and no same-link or name-based merge is
introduced. Pure functions only: no DB, model or network calls.
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

import assembly as A  # noqa: E402
import person_state_assembly as PSA  # noqa: E402
import person_state_contract as PSC  # noqa: E402
from common import PersistenceError, sha256_json  # noqa: E402

REVISION = "rev-r3-t03"
SHA = "a" * 64
NORM = "b" * 64


def _meta() -> dict:
    return {"method": "model", "job_id": "r3-t03", "confidence": 0.8}


def _source(title: str) -> dict:
    return {
        "temp_id": "src_001",
        "kind": "source",
        "source_type": "book",
        "title": title,
        "author": "作者",
        "language": "lzh",
        "extraction": _meta(),
    }


def _entity(temp_id: str, name: str, etype: str = "person") -> dict:
    return {
        "temp_id": temp_id,
        "kind": "entity",
        "type": etype,
        "canonical_name": name,
        "aliases": [],
        "mentions": [{"text": name}],
        "resolution": {"status": "unresolved"},
        "extraction": _meta(),
    }


def _block(block_id: str, text: str, entity_refs: list[str]) -> dict:
    return {
        "block_id": block_id,
        "text": text,
        "source_block_ids": ["b_001"],
        "entity_refs": [{"kind": "entity", "ref": ref} for ref in entity_refs],
        "event_refs": [],
    }


def _reading_unit(block_id: str, text: str, entity_ref: str) -> dict:
    return {
        "unit_id": "ru_" + ("0" * 24),
        "ordinal": 0,
        "block_id": block_id,
        "text_hash": _sha256_text(text),
        "narrative_time": {
            "mode": "unknown",
            "event_refs": [],
            "from_block_id": None,
            "source_selections": [],
        },
        "current_event_refs": [],
        "resolved_spans": [],
        "context_entities": [
            {"entity_ref": entity_ref, "importance": "primary", "event_roles": []}
        ],
        "segments": [{"kind": "text", "text": text}],
    }


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _selection(quote: str) -> dict:
    return {
        "first_block_id": "b_001",
        "last_block_id": "b_001",
        "quote": quote,
        "occurrence": 1,
    }


def _anchor(chapter_id: str, anchor_id: str) -> dict:
    return {
        "anchor_id": anchor_id,
        "revision_id": REVISION,
        "chapter_id": chapter_id,
        "source_sha256": SHA,
        "normalized_sha256": NORM,
        "first_block_id": "b_001",
        "last_block_id": "b_001",
        "quote": "原文",
        "quote_sha256": "q" * 64,
        "occurrence": 1,
        "start": 0,
        "end": 2,
    }


def _anchor_id(counter: int) -> str:
    return "anc_" + f"{counter:016x}"


def _person_states(anchor_counter: int) -> tuple[dict, list[dict], list[dict], int]:
    """Build a small but complete positive person_states block with anchors."""
    anchors: list[dict] = []
    candidates: list[dict] = []

    def add(kind: str, item_ref: str, phase_ids: list[str], fact_refs: list[str]) -> None:
        nonlocal anchor_counter
        anchor_ids = [_anchor_id(anchor_counter)]
        anchor_counter += 1
        anchors.append(_anchor(PERSON_CHAPTER, anchor_ids[0]))
        candidates.append(
            {
                "candidate_key": PSC.candidate_key_for(
                    kind=kind,
                    chapter_id=PERSON_CHAPTER,
                    item_ref=item_ref,
                    anchor_ids=anchor_ids,
                ),
                "kind": kind,
                "item_ref": item_ref,
                "phase_ids": list(phase_ids),
                "anchor_ids": anchor_ids,
                "source_fact_refs": list(fact_refs),
            }
        )

    person_states = {
        "phases": [
            {
                "phase_id": "ph_001",
                "label": "建安三年",
                "event_refs": [],
                "source_selections": [_selection("建安三年")],
            },
            {
                "phase_id": "ph_002",
                "label": "後",
                "event_refs": [],
                "source_selections": [_selection("後")],
            },
        ],
        "phase_orders": [
            {
                "assertion_id": "po_001",
                "earlier_phase_ref": "ph_001",
                "later_phase_ref": "ph_002",
                "source_selections": [_selection("其後")],
            }
        ],
        "unit_phases": [
            {
                "block_id": "t_001",
                "mode": "single",
                "phase_refs": ["ph_001"],
                "source_selections": [_selection("授")],
            }
        ],
        "facts": [
            {
                "fact_id": "pf_001",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_002"},
                "relation": None,
                "target_ref": None,
                "operation": "start",
                "qualification": "ordinary",
                "phase_ref": "ph_001",
                "claim_refs": [],
                "source_selections": [_selection("授")],
                "attribution": "narrator",
            },
            {
                "fact_id": "pf_002",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "affiliation",
                "value_ref": None,
                "relation": "serves",
                "target_ref": {"kind": "entity", "ref": "ent_003"},
                "operation": "attest",
                "qualification": "ordinary",
                "phase_ref": "ph_002",
                "claim_refs": [],
                "source_selections": [_selection("效力")],
                "attribution": "narrator",
            },
        ],
        "continuities": [
            {
                "assertion_id": "pc_001",
                "fact_ref": "pf_001",
                "start_phase_ref": "ph_001",
                "end_phase_ref": "ph_002",
                "source_selections": [_selection("在任")],
            }
        ],
        "disagreements": [
            {
                "assertion_id": "pd_001",
                "topic": "任職月份",
                "fact_refs": ["pf_001", "pf_002"],
                "phase_refs": ["ph_001", "ph_002"],
                "source_selections": [_selection("不同說法")],
            }
        ],
    }
    add("phase", "ph_001", ["ph_001"], [])
    add("phase", "ph_002", ["ph_002"], [])
    add("phase_order", "po_001", ["ph_001", "ph_002"], [])
    add("unit_phase", "t_001", ["ph_001"], [])
    add("fact", "pf_001", ["ph_001"], ["pf_001"])
    add("fact", "pf_002", ["ph_002"], ["pf_002"])
    add("continuity", "pc_001", ["ph_001", "ph_002"], ["pf_001"])
    add("disagreement", "pd_001", ["ph_001", "ph_002"], ["pf_001", "pf_002"])
    return person_states, candidates, anchors, anchor_counter


def _artifact(
    chapter_id: str,
    *,
    entity_name: str = "周瑜",
    person_states: dict,
    candidates: list[dict],
    anchors: list[dict],
    version: str = "0.3",
) -> dict:
    reading = {
        "units": [{"block_id": "t_001"}],
        "warnings": [],
        "context_entities": [],
    }
    candidate = {
        "schema": "chronicle.chapter-candidate",
        "version": "0.3",
        "chapter_id": chapter_id,
        "bundle": {
            "schema_version": "0.1",
            "source": _source(f"Source {chapter_id}"),
            "entities": [
                _entity("ent_001", entity_name),
                _entity("ent_002", "建威中郎將", "office"),
                _entity("ent_003", "孫權", "person"),
            ],
            "events": [],
            "claims": [],
            "warnings": [],
        },
        "translation": {
            "language": "zh-CN",
            "blocks": [_block("t_001", f"{entity_name}受任。", ["ent_001", "ent_003"])],
        },
        "mentions": [],
        "record_sources": [],
        "warnings": [],
        "reading": reading,
        "person_states": person_states,
    }
    core = {
        "schema": "chronicle.chapter-artifact",
        "version": version,
        "chapter_id": chapter_id,
        "revision_id": REVISION,
        "source_sha256": SHA,
        "normalized_sha256": NORM,
        "candidate": candidate,
        "candidate_sha256": sha256_json(candidate),
        "anchors": anchors,
        "request_fingerprint": f"fp-{chapter_id}",
        "producing_run": {
            "run_id": f"run-{chapter_id}",
            "model": "m",
            "prompt_schema_version": "0.3",
        },
        "reading": reading,
        "reading_sha256": sha256_json(reading),
        "person_states": person_states,
        "person_states_sha256": sha256_json(person_states),
        "person_state_candidates": candidates,
    }
    artifact = dict(core)
    artifact["artifact_sha256"] = sha256_json(core)
    artifact["reading_units"] = [
        _reading_unit("t_001", f"{entity_name}受任。", "ent_001")
    ]
    return artifact


PERSON_CHAPTER = "ch_000000000000000000000001"


def _plan(chapter_ids: list[str]) -> dict:
    return {
        "version": "c2r1-chapters-v1",
        "plan_sha256": "p" * 64,
        "revision_id": REVISION,
        "source_sha256": SHA,
        "normalized_sha256": NORM,
        "chapters": [
            {
                "chapter_id": chapter_id,
                "chapter_index": index,
                "title": f"Chapter {index}",
                "start": index * 10,
                "end": (index + 1) * 10,
                "content_sha256": NORM,
            }
            for index, chapter_id in enumerate(chapter_ids)
        ],
    }


def _chapter(chapter_id: str, *, entity_name: str = "周瑜") -> dict:
    global PERSON_CHAPTER
    PERSON_CHAPTER = chapter_id
    person_states, candidates, anchors, _ = _person_states(0)
    return _artifact(
        chapter_id,
        entity_name=entity_name,
        person_states=person_states,
        candidates=candidates,
        anchors=anchors,
    )


def _two_chapters() -> tuple[dict, dict, dict]:
    first = _chapter("ch_000000000000000000000001")
    second = _chapter("ch_000000000000000000000002")
    plan = _plan(
        ["ch_000000000000000000000001", "ch_000000000000000000000002"]
    )
    return first, second, plan


class PersonStateAssemblyTests(unittest.TestCase):
    def test_phase_and_fact_ids_are_chapter_bound(self) -> None:
        first, second, plan = _two_chapters()
        result = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        phase_ids = [record["phase_id"] for record in result["person_states"]["phases"]]
        self.assertIn("ph_000001", phase_ids)
        self.assertIn("ph_001001", phase_ids)
        fact_ids = [record["fact_id"] for record in result["person_states"]["facts"]]
        self.assertIn("pf_000001", fact_ids)
        self.assertIn("pf_001001", fact_ids)
        # The same local fact ID in two chapters can never collide.
        self.assertEqual(len(fact_ids), len(set(fact_ids)))
        self.assertEqual(
            "ph_000001",
            result["report"]["local_to_revision"]["(0,ph_001)"],
        )
        self.assertEqual(
            "pf_001001",
            result["report"]["local_to_revision"]["(1,pf_001)"],
        )

    def test_references_reuse_the_shared_revision_map(self) -> None:
        first, second, plan = _two_chapters()
        result = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        facts = {
            (record["origin"]["chapter_index"], record["origin"]["origin_ref"]): record
            for record in result["person_states"]["facts"]
        }
        first_fact = facts[(0, "pf_001")]
        second_fact = facts[(1, "pf_001")]
        self.assertEqual("ent_000001", first_fact["person_ref"]["ref"])
        self.assertEqual("ent_001001", second_fact["person_ref"]["ref"])
        self.assertEqual("ph_000001", first_fact["phase_ref"])
        self.assertEqual("ph_001001", second_fact["phase_ref"])
        # An office value entity is remapped like any other entity.
        self.assertEqual("ent_000002", first_fact["value_ref"]["ref"])

    def test_unit_phase_stays_bound_to_the_reading_unit_block(self) -> None:
        first, second, plan = _two_chapters()
        result = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        units = result["person_states"]["unit_phases"]
        self.assertEqual(["t_000001", "t_001001"], [u["block_id"] for u in units])
        self.assertEqual(["t_001", "t_001"], [u["chapter_block_id"] for u in units])
        # The unit phase references the remapped phase, not the local one.
        self.assertEqual("ph_000001", units[0]["phase_refs"][0])

    def test_continuities_and_disagreements_remap_their_refs(self) -> None:
        first, _, plan = _two_chapters()
        result = A.assemble_chapters(accepted_artifacts=[first], chapter_plan=_plan([first["chapter_id"]]))
        continuity = result["person_states"]["continuities"][0]
        self.assertEqual("pf_000001", continuity["fact_ref"])
        self.assertEqual("ph_000001", continuity["start_phase_ref"])
        self.assertEqual("ph_000002", continuity["end_phase_ref"])
        disagreement = result["person_states"]["disagreements"][0]
        self.assertEqual(["pf_000001", "pf_000002"], disagreement["fact_refs"])
        self.assertEqual(["ph_000001", "ph_000002"], disagreement["phase_refs"])

    def test_evidence_manifest_preserves_origin_and_anchors(self) -> None:
        first, second, plan = _two_chapters()
        result = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        manifests = {
            manifest["chapter_id"]: manifest for manifest in result["person_state_evidence"]
        }
        self.assertEqual(
            first["artifact_sha256"], manifests[first["chapter_id"]]["artifact_sha256"]
        )
        self.assertEqual(REVISION, manifests[first["chapter_id"]]["origin_revision_id"])
        items = {
            (item["kind"], item["origin_ref"]): item
            for item in manifests[first["chapter_id"]]["items"]
        }
        fact_item = items[("fact", "pf_001")]
        self.assertEqual("pf_000001", fact_item["revision_ref"])
        self.assertTrue(fact_item["anchor_ids"])
        anchor_ids = {anchor["anchor_id"] for anchor in first["anchors"]}
        self.assertTrue(set(fact_item["anchor_ids"]).issubset(anchor_ids))

    def test_no_same_link_or_name_merge_is_introduced(self) -> None:
        first, second, plan = _two_chapters()
        result = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        # Two same-name entities from different chapters stay distinct refs.
        entity_refs = {
            record["person_ref"]["ref"]
            for record in result["person_states"]["facts"]
        }
        self.assertEqual({"ent_000001", "ent_001001"}, entity_refs)
        blob = sha256_json(result["person_states"])
        self.assertNotIn("same_entity", result["person_states"])
        self.assertNotIn("same_occurrence", result["person_states"])
        self.assertTrue(blob)

    def test_rerun_is_byte_deterministic_regardless_of_input_order(self) -> None:
        first, second, plan = _two_chapters()
        one = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        two = A.assemble_chapters(
            accepted_artifacts=[copy.deepcopy(second), copy.deepcopy(first)],
            chapter_plan=copy.deepcopy(plan),
        )
        self.assertEqual(
            sha256_json(one["person_states"]), sha256_json(two["person_states"])
        )
        self.assertEqual(
            sha256_json(one["person_state_evidence"]),
            sha256_json(two["person_state_evidence"]),
        )
        self.assertEqual(
            one["report"]["person_state"]["person_states_sha256"],
            two["report"]["person_state"]["person_states_sha256"],
        )

    def test_0_1_and_0_2_paths_leave_state_empty(self) -> None:
        first, _, _ = _two_chapters()
        plain = copy.deepcopy(first)
        plain["version"] = "0.1"
        plain["candidate"]["version"] = "0.1"
        plain["candidate"].pop("reading", None)
        plain["candidate"].pop("person_states", None)
        plain.pop("reading", None)
        plain.pop("reading_sha256", None)
        plain.pop("reading_units", None)
        plain.pop("person_states", None)
        plain.pop("person_states_sha256", None)
        plain.pop("person_state_candidates", None)
        plain["candidate_sha256"] = sha256_json(plain["candidate"])
        result = A.assemble_chapters(
            accepted_artifacts=[plain], chapter_plan=_plan([plain["chapter_id"]])
        )
        self.assertEqual([], result["person_states"]["phases"])
        self.assertEqual([], result["person_state_evidence"])
        self.assertEqual("0.1", result["report"]["candidate_version"])
        self.assertIsNone(result["report"]["person_state"])


class PersonStateAssemblyFailureTests(unittest.TestCase):
    def test_mixed_generations_fail_closed(self) -> None:
        first, second, _ = _two_chapters()
        plain = copy.deepcopy(first)
        plain["version"] = "0.1"
        plain["candidate"]["version"] = "0.1"
        plain["candidate"].pop("reading", None)
        plain["candidate"].pop("person_states", None)
        plain.pop("reading", None)
        plain.pop("reading_sha256", None)
        plain.pop("reading_units", None)
        plain.pop("person_states", None)
        plain.pop("person_states_sha256", None)
        plain.pop("person_state_candidates", None)
        plain["candidate_sha256"] = sha256_json(plain["candidate"])
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[plain, second],
                chapter_plan=_plan([first["chapter_id"], second["chapter_id"]]),
            )

    def test_missing_chapter_fails_closed(self) -> None:
        first, second, plan = _two_chapters()
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(accepted_artifacts=[first], chapter_plan=plan)

    def test_tampered_person_states_hash_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_states_sha256"] = "0" * 64
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_dangling_phase_ref_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_states"]["facts"][0]["phase_ref"] = "ph_999"
        bad["person_states_sha256"] = sha256_json(bad["person_states"])
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_unknown_block_in_unit_phase_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_states"]["unit_phases"][0]["block_id"] = "t_999"
        bad["person_states_sha256"] = sha256_json(bad["person_states"])
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_duplicate_local_fact_id_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_states"]["facts"].append(
            copy.deepcopy(bad["person_states"]["facts"][0])
        )
        bad["person_states_sha256"] = sha256_json(bad["person_states"])
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_unknown_entity_ref_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_states"]["facts"][0]["person_ref"] = {
            "kind": "entity",
            "ref": "ent_999",
        }
        bad["person_states_sha256"] = sha256_json(bad["person_states"])
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_missing_candidate_metadata_fails_closed(self) -> None:
        # Reviewer regression: dropping a generated candidate entry must not
        # assemble state items with empty anchor ids.
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_state_candidates"].pop()
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_extra_candidate_metadata_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_state_candidates"].append(
            {
                "candidate_key": "psc_" + "0" * 24,
                "kind": "fact",
                "item_ref": "pf_999",
                "phase_ids": ["ph_001"],
                "anchor_ids": [bad["anchors"][0]["anchor_id"]],
                "source_fact_refs": ["pf_999"],
            }
        )
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_duplicate_candidate_metadata_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_state_candidates"].append(
            copy.deepcopy(bad["person_state_candidates"][0])
        )
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_candidate_key_mismatch_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_state_candidates"][0]["candidate_key"] = "psc_" + "0" * 24
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_candidate_phase_ids_mismatch_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_state_candidates"][0]["phase_ids"] = ["ph_999"]
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )

    def test_candidate_anchor_without_payload_fails_closed(self) -> None:
        first, _, _ = _two_chapters()
        bad = copy.deepcopy(first)
        bad["person_state_candidates"][0]["anchor_ids"] = ["anc_" + "f" * 16]
        _refresh_core(bad)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[bad], chapter_plan=_plan([bad["chapter_id"]])
            )


def _refresh_core(artifact: dict) -> None:
    """Recompute the 0.3 artifact core hash after a metadata/state mutation.

    ``person_state_candidates`` is part of the core (bound as of the T03
    review fix), so a mutation to it is reflected in the recomputed hash.
    """
    excluded = {"artifact_sha256", "reading_units"}
    core = {key: value for key, value in artifact.items() if key not in excluded}
    artifact["artifact_sha256"] = sha256_json(core)


class PersonStateAnchorPreservationTests(unittest.TestCase):
    def test_cited_anchors_are_preserved_verbatim(self) -> None:
        # T01 resolves each person-state item's anchors from its own
        # source_selections and now carries their payloads in the accepted
        # artifact; assembly preserves both the ids and the records.
        first, _, _ = _two_chapters()
        cited = first["person_state_candidates"][0]["anchor_ids"]
        result = A.assemble_chapters(
            accepted_artifacts=[first], chapter_plan=_plan([first["chapter_id"]])
        )
        manifest = result["person_state_evidence"][0]
        item = next(
            entry for entry in manifest["items"] if entry["kind"] == "phase"
        )
        self.assertEqual(cited, item["anchor_ids"])
        self.assertEqual(cited, [record["anchor_id"] for record in item["anchors"]])
        for record in item["anchors"]:
            self.assertTrue(record["quote"])
            self.assertLess(record["start"], record["end"])


FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r3-contract"


class RealFixtureAssemblyTests(unittest.TestCase):
    """Mechanism evidence on the T01 accepted fixture (real product shape)."""

    def _fixture_plan(self, artifact: dict) -> dict:
        return {
            "version": "c2r1-chapters-v1",
            "plan_sha256": "p" * 64,
            "revision_id": artifact["revision_id"],
            "source_sha256": artifact["source_sha256"],
            "normalized_sha256": artifact["normalized_sha256"],
            "chapters": [
                {
                    "chapter_id": artifact["chapter_id"],
                    "chapter_index": 0,
                    "title": "fixture",
                    "start": 0,
                    "end": 1,
                    "content_sha256": artifact["normalized_sha256"],
                }
            ],
        }

    def test_t01_accepted_fixture_assembles_into_state_evidence(self) -> None:
        artifact = json.loads(
            (FIXTURES / "artifact-accepted.json").read_text(encoding="utf-8")
        )
        result = A.assemble_chapters(
            accepted_artifacts=[artifact], chapter_plan=self._fixture_plan(artifact)
        )
        states = result["person_states"]
        self.assertEqual("0.3", result["report"]["candidate_version"])
        self.assertEqual(3, len(states["phases"]))
        self.assertEqual(4, len(states["facts"]))
        self.assertEqual(3, len(states["unit_phases"]))
        self.assertEqual(
            [f"ph_00000{i}" for i in (1, 2, 3)],
            [record["phase_id"] for record in states["phases"]],
        )
        first_fact = states["facts"][0]
        self.assertEqual("pf_000001", first_fact["fact_id"])
        self.assertEqual("ent_000002", first_fact["person_ref"]["ref"])
        self.assertEqual("ent_000003", first_fact["value_ref"]["ref"])
        self.assertEqual("ph_000001", first_fact["phase_ref"])
        # unit phases bind the remapped reading-unit block IDs.
        self.assertEqual(
            ["t_000001", "t_000002", "t_000003"],
            [record["block_id"] for record in states["unit_phases"]],
        )
        self.assertEqual(1, len(result["person_state_evidence"]))
        self.assertEqual(
            sha256_json(states),
            result["report"]["person_state"]["person_states_sha256"],
        )

    def test_fixture_assembly_is_repeatable(self) -> None:
        artifact = json.loads(
            (FIXTURES / "artifact-accepted.json").read_text(encoding="utf-8")
        )
        plan = self._fixture_plan(artifact)
        one = A.assemble_chapters(accepted_artifacts=[artifact], chapter_plan=plan)
        two = A.assemble_chapters(
            accepted_artifacts=[copy.deepcopy(artifact)],
            chapter_plan=copy.deepcopy(plan),
        )
        self.assertEqual(
            sha256_json(one["person_states"]), sha256_json(two["person_states"])
        )
        self.assertEqual(
            sha256_json(one["person_state_evidence"]),
            sha256_json(two["person_state_evidence"]),
        )

    def test_every_state_anchor_resolves_to_an_immutable_payload(self) -> None:
        # End-to-end regression (T03 review): every anchor id a
        # person-state candidate cites must resolve to a hash-bound anchor
        # payload carried by the assembled artifact, not just a bare id.
        artifact = json.loads(
            (FIXTURES / "artifact-accepted.json").read_text(encoding="utf-8")
        )
        result = A.assemble_chapters(
            accepted_artifacts=[artifact], chapter_plan=self._fixture_plan(artifact)
        )
        payloads = {
            anchor["anchor_id"]: anchor
            for anchor in result["anchors"]
            if isinstance(anchor, dict) and isinstance(anchor.get("anchor_id"), str)
        }
        cited: set[str] = set()
        for entry in artifact["person_state_candidates"]:
            cited.update(entry["anchor_ids"])
        self.assertTrue(cited)
        self.assertEqual(set(), cited - set(payloads))
        for manifest in result["person_state_evidence"]:
            for item in manifest["items"]:
                self.assertEqual(
                    item["anchor_ids"],
                    [record["anchor_id"] for record in item["anchors"]],
                )
                for record in item["anchors"]:
                    payload = payloads[record["anchor_id"]]
                    self.assertEqual(record, payload)
                    self.assertTrue(record["quote"])
                    self.assertLess(record["start"], record["end"])
        fact = next(
            record
            for record in result["person_states"]["facts"]
            if record["origin"]["anchors"]
        )
        for record in fact["origin"]["anchors"]:
            self.assertIn(record["anchor_id"], fact["origin"]["anchor_ids"])
            self.assertEqual(record, payloads[record["anchor_id"]])
        # A genuinely empty candidate metadata list cannot assemble.
        forged = copy.deepcopy(artifact)
        forged["person_state_candidates"] = []
        _refresh_core(forged)
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(
                accepted_artifacts=[forged], chapter_plan=self._fixture_plan(forged)
            )


class AcceptanceBindingTests(unittest.TestCase):
    """Regression for the T03-review acceptance fixes that T03 depends on."""

    def _accepted(self) -> dict:
        request = json.loads(
            (FIXTURES / "request.json").read_text(encoding="utf-8")
        )
        candidate = json.loads(
            (FIXTURES / "candidate-valid.json").read_text(encoding="utf-8")
        )
        return PSC.accept_person_state_candidate(
            request,
            candidate,
            producing_run={
                "run_id": "r3-regression",
                "model": "unit-test",
                "prompt_schema_version": "0.3",
            },
        )

    def test_accepted_artifact_carries_every_state_anchor_payload(self) -> None:
        artifact = self._accepted()
        payloads = {anchor["anchor_id"] for anchor in artifact["anchors"]}
        cited: set[str] = set()
        for entry in artifact["person_state_candidates"]:
            cited.update(entry["anchor_ids"])
        self.assertTrue(cited)
        self.assertEqual(set(), cited - payloads)

    def test_candidate_metadata_is_hash_bound_by_acceptance(self) -> None:
        artifact = self._accepted()
        tampered = copy.deepcopy(artifact)
        tampered["person_state_candidates"] = tampered["person_state_candidates"][:-1]
        core = {
            key: value
            for key, value in tampered.items()
            if key not in ("artifact_sha256", "reading_units")
        }
        self.assertNotEqual(artifact["artifact_sha256"], sha256_json(core))


class PersonStateHelperTests(unittest.TestCase):
    def test_assembly_module_exposes_public_collections(self) -> None:
        self.assertIn("phases", PSA.STATE_COLLECTIONS)
        self.assertIn("unit_phases", PSA.STATE_COLLECTIONS)


if __name__ == "__main__":
    unittest.main()
