"""Unit tests for Chronicle C2-R2-T04 reading ref remapping in assembly.

Verifies that the reading annotations of accepted 0.2 chapter artifacts
enter the same ``(chapter_index, local_ref) -> revision_ref`` map as every
other chapter reference, that chapter/block/source provenance is kept, and
that missing refs, broken inheritance, tampered reading bytes and mixed
0.1/0.2 generations fail closed. Pure functions only: no DB, model or
network calls.
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
from common import PersistenceError, sha256_json  # noqa: E402

REVISION = "rev-r2-test"
SHA = "a" * 64
NORM = "b" * 64


def _meta() -> dict:
    return {"method": "model", "job_id": "r2-t04", "confidence": 0.8}


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


def _event(
    temp_id: str,
    title: str,
    participants: list[str] | None = None,
    time: dict | None = None,
) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "event",
        "type": "battle",
        "title": title,
        "time": time,
        "participants": [
            {"entity_ref": ref, "role": "subject"} for ref in (participants or [])
        ],
        "places": [],
        "extraction": _meta(),
    }


def _time() -> dict:
    return {
        "original_text": "建安十三年",
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": 13,
            "season": None,
            "month": None,
            "day": None,
        },
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": None,
            "month": None,
            "day": None,
            "precision": "unknown",
            "conversion_status": "unresolved",
            "approximate": False,
        },
    }


def _block(block_id: str, text: str, entity_refs: list[str], event_refs: list[str]) -> dict:
    return {
        "block_id": block_id,
        "text": text,
        "source_block_ids": ["b_001"],
        "entity_refs": [{"kind": "entity", "ref": ref} for ref in entity_refs],
        "event_refs": [{"kind": "event", "ref": ref} for ref in event_refs],
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
        "quote": "曹操",
        "quote_sha256": "q" * 64,
        "occurrence": 1,
        "start": 0,
        "end": 2,
    }


def _reading_unit(
    block_id: str,
    text: str,
    *,
    entity_ref: str = "ent_001",
    event_ref: str = "evt_001",
    from_block_id: str | None = None,
    mode: str = "events",
    context: bool = True,
    role_event_ref: str | None = None,
) -> dict:
    unit = {
        "unit_id": "ru_" + ("0" * 24),
        "block_id": block_id,
        "text_hash": _sha256_text(text),
        "narrative_time": {
            "mode": mode,
            "event_refs": [] if mode in ("inherit", "unknown") else [event_ref],
            "from_block_id": from_block_id,
            "source_selections": [],
        },
        "current_event_refs": [] if mode in ("inherit", "unknown") else [event_ref],
        "resolved_spans": [],
        "context_entities": [],
    }
    if context:
        unit["context_entities"].append(
            {
                "entity_ref": entity_ref,
                "importance": "primary",
                "event_roles": [
                    {
                        "event_ref": role_event_ref or event_ref,
                        "role": "subject",
                        "participant_index": 0,
                    }
                ]
                if mode == "events"
                else [],
            }
        )
    return unit


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _artifact(
    chapter_id: str,
    *,
    entities: list[dict],
    events: list[dict],
    blocks: list[dict],
    reading_units: list[dict],
    version: str = "0.2",
) -> dict:
    candidate = {
        "schema": "chronicle.chapter-candidate",
        "version": "0.2" if version == "0.2" else "0.1",
        "chapter_id": chapter_id,
        "bundle": {
            "schema_version": "0.1",
            "source": _source(f"Source {chapter_id}"),
            "entities": entities,
            "events": events,
            "claims": [],
            "warnings": [],
        },
        "translation": {"language": "zh-CN", "blocks": blocks},
        "mentions": [],
        "record_sources": [],
        "warnings": [],
    }
    artifact = {
        "schema": "chronicle.chapter-artifact",
        "version": version,
        "chapter_id": chapter_id,
        "revision_id": REVISION,
        "source_sha256": SHA,
        "normalized_sha256": NORM,
        "candidate": candidate,
        "anchors": [_anchor(chapter_id, f"anc_{chapter_id}")],
        "request_fingerprint": f"fp-{chapter_id}",
        "producing_run": {"run_id": f"run-{chapter_id}", "model": "m", "prompt_schema_version": "v"},
    }
    if version == "0.2":
        reading = {"units": [{"block_id": unit["block_id"]} for unit in reading_units], "warnings": []}
        candidate["reading"] = reading
        artifact["reading"] = reading
        artifact["reading_sha256"] = sha256_json(reading)
        artifact["reading_units"] = reading_units
    artifact["candidate_sha256"] = sha256_json(candidate)
    return artifact


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


def _two_chapter_artifacts() -> tuple[dict, dict, dict]:
    events = [_event("evt_001", "戰役", participants=["ent_001"], time=_time())]
    first = _artifact(
        "ch_000",
        entities=[_entity("ent_001", "曹操")],
        events=events,
        blocks=[_block("t_001", "曹操出戰。", ["ent_001"], ["evt_001"])],
        reading_units=[_reading_unit("t_001", "曹操出戰。")],
    )
    second = _artifact(
        "ch_001",
        entities=[_entity("ent_001", "曹操"), _entity("ent_002", "周瑜")],
        events=[_event("evt_001", "戰役", participants=["ent_002"], time=_time())],
        blocks=[_block("t_001", "周瑜出戰。", ["ent_002"], ["evt_001"])],
        reading_units=[
            _reading_unit("t_001", "周瑜出戰。", entity_ref="ent_002", event_ref="evt_001")
        ],
    )
    return first, second, _plan(["ch_000", "ch_001"])


class ReadingRemapTests(unittest.TestCase):
    def test_refs_remap_through_same_map_and_blocks_keep_provenance(self) -> None:
        first, second, plan = _two_chapter_artifacts()
        result = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        units = {(unit["chapter_id"], unit["chapter_block_id"]): unit for unit in result["reading_units"]}
        self.assertEqual(2, len(units))
        first_unit = units[("ch_000", "t_001")]
        second_unit = units[("ch_001", "t_001")]
        # The same chapter-local IDs map to distinct revision refs.
        self.assertEqual("t_000001", first_unit["block_id"])
        self.assertEqual("t_001001", second_unit["block_id"])
        self.assertEqual("ent_000001", first_unit["context_entities"][0]["entity_ref"])
        self.assertEqual("ent_001002", second_unit["context_entities"][0]["entity_ref"])
        self.assertEqual("evt_000001", first_unit["narrative_time"]["event_refs"][0])
        self.assertEqual("evt_001001", second_unit["narrative_time"]["event_refs"][0])
        self.assertEqual(
            "evt_000001",
            first_unit["context_entities"][0]["event_roles"][0]["event_ref"],
        )
        # Provenance keys are kept for the compiler.
        self.assertEqual(sha256_json(first), first_unit["artifact_sha256"])
        self.assertEqual("t_001", first_unit["chapter_block_id"])

    def test_inherit_from_block_remaps_to_revision_block(self) -> None:
        events = [_event("evt_001", "戰役", participants=["ent_001"], time=_time())]
        artifact = _artifact(
            "ch_000",
            entities=[_entity("ent_001", "曹操")],
            events=events,
            blocks=[
                _block("t_001", "曹操出戰。", ["ent_001"], ["evt_001"]),
                _block("t_002", "其後續戰。", ["ent_001"], ["evt_001"]),
            ],
            reading_units=[
                _reading_unit("t_001", "曹操出戰。"),
                _reading_unit("t_002", "其後續戰。", mode="inherit", from_block_id="t_001"),
            ],
        )
        result = A.assemble_chapters(accepted_artifacts=[artifact], chapter_plan=_plan(["ch_000"]))
        units = {unit["chapter_block_id"]: unit for unit in result["reading_units"]}
        self.assertEqual("t_000001", units["t_002"]["narrative_time"]["from_block_id"])
        self.assertEqual("inherit", units["t_002"]["narrative_time"]["mode"])

    def test_rerun_is_byte_deterministic(self) -> None:
        first, second, plan = _two_chapter_artifacts()
        one = A.assemble_chapters(accepted_artifacts=[first, second], chapter_plan=plan)
        two = A.assemble_chapters(
            accepted_artifacts=[copy.deepcopy(second), copy.deepcopy(first)], chapter_plan=copy.deepcopy(plan)
        )
        self.assertEqual(sha256_json(one["reading_units"]), sha256_json(two["reading_units"]))
        self.assertEqual(sha256_json(one["bundle"]), sha256_json(two["bundle"]))

    def test_0_1_path_leaves_reading_empty(self) -> None:
        first, second, _ = _two_chapter_artifacts()
        plain = {
            "schema": first["schema"],
            "version": "0.1",
            "chapter_id": first["chapter_id"],
            "revision_id": first["revision_id"],
            "source_sha256": first["source_sha256"],
            "normalized_sha256": first["normalized_sha256"],
            "candidate": {k: v for k, v in first["candidate"].items() if k != "reading"}
            | {"version": "0.1"},
            "anchors": first["anchors"],
            "request_fingerprint": first["request_fingerprint"],
        }
        plain["candidate_sha256"] = sha256_json(plain["candidate"])
        result = A.assemble_chapters(accepted_artifacts=[plain], chapter_plan=_plan(["ch_000"]))
        self.assertEqual([], result["reading_units"])
        self.assertEqual("0.1", result["report"]["candidate_version"])


class ReadingAssemblyFailureTests(unittest.TestCase):
    def test_mixed_generations_fail_closed(self) -> None:
        first, second, _ = _two_chapter_artifacts()
        plain = copy.deepcopy(first)
        plain["version"] = "0.1"
        plain["candidate"]["version"] = "0.1"
        plain["candidate"].pop("reading", None)
        plain.pop("reading", None)
        plain.pop("reading_sha256", None)
        plain.pop("reading_units", None)
        plain["candidate_sha256"] = sha256_json(plain["candidate"])
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(accepted_artifacts=[plain, second], chapter_plan=_plan(["ch_000", "ch_001"]))

    def test_tampered_reading_bytes_fail_closed(self) -> None:
        first, _, _ = _two_chapter_artifacts()
        bad = copy.deepcopy(first)
        bad["reading_sha256"] = "0" * 64
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(accepted_artifacts=[bad], chapter_plan=_plan(["ch_000"]))

    def test_missing_reading_unit_fails_closed(self) -> None:
        first, _, _ = _two_chapter_artifacts()
        bad = copy.deepcopy(first)
        bad["reading_units"] = []
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(accepted_artifacts=[bad], chapter_plan=_plan(["ch_000"]))

    def test_dangling_reading_ref_fails_closed(self) -> None:
        first, _, _ = _two_chapter_artifacts()
        bad = copy.deepcopy(first)
        bad["reading_units"][0]["current_event_refs"] = ["evt_999"]
        bad["reading_units"][0]["narrative_time"]["event_refs"] = ["evt_999"]
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(accepted_artifacts=[bad], chapter_plan=_plan(["ch_000"]))

    def test_broken_inheritance_from_block_fails_closed(self) -> None:
        first, _, _ = _two_chapter_artifacts()
        bad = copy.deepcopy(first)
        bad["reading_units"][0]["narrative_time"] = {
            "mode": "inherit",
            "event_refs": [],
            "from_block_id": "t_999",
            "source_selections": [],
        }
        bad["reading_units"][0]["current_event_refs"] = []
        with self.assertRaises(PersistenceError):
            A.assemble_chapters(accepted_artifacts=[bad], chapter_plan=_plan(["ch_000"]))


if __name__ == "__main__":
    unittest.main()
