"""Unit tests for the Chronicle C2-R2-T04 reading projection compiler.

Covers ``continuous-reading.md`` sections 2-5: deterministic compilation,
one reading unit per translation block in source order with verbatim text,
canonical binding of the same catalog (never by name), narrative-time
grouping from this source's Event.time, same-chapter inheritance,
current/mention occurrence rows, snapshot discipline, and fail-closed
rejection of contradictions. Pure functions only: no DB, model or network.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import assembly as A  # noqa: E402
import reading_contract as RC  # noqa: E402
import reading_projection as RP  # noqa: E402
from common import PersistenceError, canonical_json_bytes, sha256_json  # noqa: E402

FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r2-contract"

REVISION = "rev-r2-projection"
SHA = "a" * 64
NORM = "b" * 64
BUNDLE_LABEL = "c1rev-r2projection"
CH0 = "ch_000000000000000000000001"
CH1 = "ch_000000000000000000000002"
STREAM = "0192f0a0-0000-7000-8000-00000000aa01"
PUB0 = "0192f0a0-0000-7000-8000-00000000bb01"
PUB1 = "0192f0a0-0000-7000-8000-00000000bb02"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _time(era_year: int = 13, month: int | None = None, original: str | None = None) -> dict:
    return {
        "original_text": original or ("建安十三年" if month is None else f"建安十三年{month}月"),
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": era_year,
            "season": None,
            "month": month,
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


def _gregorian_time(year: int, month: int) -> dict:
    return {
        "original_text": f"{month}月",
        "source_calendar": {
            "system": "proleptic_gregorian",
            "era": None,
            "era_year": None,
            "season": None,
            "month": None,
            "day": None,
        },
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": year,
            "month": month,
            "day": None,
            "precision": "month",
            "conversion_status": "exact",
            "approximate": False,
        },
    }


def _event(
    temp_id: str,
    title: str,
    *,
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
            {"entity_ref": ref, "role": "commander"} for ref in (participants or [])
        ],
        "places": [],
        "extraction": _meta(),
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


def _span(
    span_id: str,
    start: int,
    end: int,
    quote: str,
    *,
    target_ref: str = "evt_001",
    relation: str = "current",
    status: str = "resolved",
    candidate_refs: list[str] | None = None,
) -> dict:
    return {
        "span_id": span_id,
        "block_id": "t_001",
        "start": start,
        "end": end,
        "quote": quote,
        "quote_sha256": sha256_text(quote),
        "status": status,
        "relation": relation,
        "target_ref": target_ref,
        "candidate_refs": list(candidate_refs or []),
    }


def _context(
    entity_ref: str,
    *,
    importance: str = "primary",
    event_ref: str = "evt_001",
    role: str | None = "commander",
    participant_index: int = 0,
) -> dict:
    roles = []
    if role is not None:
        roles.append(
            {"event_ref": event_ref, "role": role, "participant_index": participant_index}
        )
    return {"entity_ref": entity_ref, "importance": importance, "event_roles": roles}


def _unit(
    block_id: str,
    text: str,
    *,
    mode: str = "events",
    event_ref: str = "evt_001",
    event_refs: list[str] | None = None,
    from_block_id: str | None = None,
    spans: list[dict] | None = None,
    contexts: list[dict] | None = None,
) -> dict:
    time_refs: list[str] = []
    if mode in ("events", "mixed"):
        time_refs = list(event_refs if event_refs is not None else [event_ref])
    return {
        "unit_id": "ru_" + ("0" * 24),
        "block_id": block_id,
        "text_hash": sha256_text(text),
        "narrative_time": {
            "mode": mode,
            "event_refs": time_refs,
            "from_block_id": from_block_id,
            "source_selections": [],
        },
        "current_event_refs": time_refs,
        "resolved_spans": list(spans or []),
        "context_entities": list(contexts or []),
    }


def _artifact(
    chapter_id: str,
    *,
    entities: list[dict],
    events: list[dict],
    blocks: list[dict],
    reading_units: list[dict],
) -> dict:
    reading = {"units": [{"block_id": unit["block_id"]} for unit in reading_units], "warnings": []}
    candidate = {
        "schema": "chronicle.chapter-candidate",
        "version": "0.2",
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
        "reading": reading,
    }
    artifact = {
        "schema": "chronicle.chapter-artifact",
        "version": "0.2",
        "chapter_id": chapter_id,
        "revision_id": REVISION,
        "source_sha256": SHA,
        "normalized_sha256": NORM,
        "candidate": candidate,
        "anchors": [_anchor(chapter_id, f"anc_{chapter_id}")],
        "request_fingerprint": f"fp-{chapter_id}",
        "producing_run": {"run_id": f"run-{chapter_id}", "model": "m", "prompt_schema_version": "v"},
        "reading": reading,
        "reading_sha256": sha256_json(reading),
    }
    artifact["candidate_sha256"] = sha256_json(candidate)
    # Accepted 0.2 hash binds the artifact core excluding reading_units
    # (reading_contract.accept_reading_candidate); reading_units never
    # participates in the canonical artifact hash.
    artifact["artifact_sha256"] = sha256_json(artifact)
    artifact["reading_units"] = reading_units
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


def _catalog(
    entity_map: dict[str, str], event_map: dict[str, str], *, label: str = BUNDLE_LABEL
) -> dict:
    return {
        "schema": "chronicle.canonical-catalog",
        "version": "0.1",
        "canonical_entities": [
            {"canonical_id": cid, "representations": [{"bundle": label, "ref": ref}]}
            for ref, cid in entity_map.items()
        ],
        "canonical_events": [
            {"canonical_id": cid, "representations": [{"bundle": label, "ref": ref}]}
            for ref, cid in event_map.items()
        ],
        "event_relations": [],
        "warnings": [],
    }


def _canonical(prefix: str, index: int) -> str:
    return f"0192f0a0-0000-7000-8000-{prefix}{index:011x}"


def _single_chapter(
    *,
    time: dict | None = None,
    mode: str = "events",
    spans: list[dict] | None = None,
    contexts: list[dict] | None = None,
    text: str = "曹操出戰。",
    event_refs: list[str] | None = None,
    from_block_id: str | None = None,
) -> tuple[list[dict], dict, dict]:
    artifact = _artifact(
        CH0,
        entities=[_entity("ent_001", "曹操")],
        events=[_event("evt_001", "戰役", participants=["ent_001"], time=time)],
        blocks=[_block("t_001", text, ["ent_001"], ["evt_001"])],
        reading_units=[
            _unit(
                "t_001",
                text,
                mode=mode,
                event_refs=event_refs,
                from_block_id=from_block_id,
                spans=spans,
                contexts=contexts if contexts is not None else [_context("ent_001")],
            )
        ],
    )
    catalog = _catalog(
        {"ent_000001": _canonical("e", 1)},
        {"evt_000001": _canonical("f", 1)},
    )
    return [artifact], _plan([CH0]), catalog


def _compile(
    artifacts: list[dict],
    plan: dict,
    catalog: dict,
    *,
    publications: dict[str, str] | None = None,
    limits: RC.ReadingLimits | None = None,
) -> dict:
    chapter_ids = [chapter["chapter_id"] for chapter in plan["chapters"]]
    if publications is None:
        publications = {
            chapter_id: (PUB0 if chapter_id == CH0 else PUB1) for chapter_id in chapter_ids
        }
    return RP.compile_reading_projection(
        accepted_artifacts=artifacts,
        chapter_plan=plan,
        catalog=catalog,
        stream_id=STREAM,
        publication_by_chapter=publications,
        bundle_label=BUNDLE_LABEL,
        limits=limits,
    )


def _real_fixture_artifact() -> dict:
    request = json.loads((FIXTURES / "request.json").read_text(encoding="utf-8"))
    candidate = json.loads((FIXTURES / "candidate-valid.json").read_text(encoding="utf-8"))
    return RC.accept_reading_candidate(
        request, candidate, producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"}
    )


class RealFixtureCompilationTests(unittest.TestCase):
    def _compile_real(self) -> dict:
        request = json.loads((FIXTURES / "request.json").read_text(encoding="utf-8"))
        artifact = _real_fixture_artifact()
        plan = {
            "version": "c2r1-chapters-v1",
            "plan_sha256": "p" * 64,
            "revision_id": request["revision_id"],
            "source_sha256": request["source_sha256"],
            "normalized_sha256": request["normalized_sha256"],
            "chapters": [
                {
                    "chapter_id": request["chapter_id"],
                    "chapter_index": 0,
                    "title": "contract chapter",
                    "start": 0,
                    "end": 36,
                    "content_sha256": request["normalized_sha256"],
                }
            ],
        }
        catalog = _catalog(
            {f"ent_{i:06d}": _canonical("e", i) for i in range(1, 5)},
            {f"evt_{i:06d}": _canonical("f", i) for i in range(1, 5)},
            label="c1rev-demo",
        )
        return RP.compile_reading_projection(
            accepted_artifacts=[artifact],
            chapter_plan=plan,
            catalog=catalog,
            stream_id=STREAM,
            publication_by_chapter={request["chapter_id"]: PUB0},
            bundle_label="c1rev-demo",
        )

    def test_real_fixture_compiles_stable(self) -> None:
        first = self._compile_real()
        second = self._compile_real()
        self.assertEqual(
            canonical_json_bytes(first), canonical_json_bytes(second)
        )
        self.assertEqual(3, len(first["units"]))
        self.assertEqual(2, len(first["groups"]))
        self.assertEqual(5, len(first["occurrences"]))

    def test_units_are_one_per_block_in_order_with_verbatim_text(self) -> None:
        projection = self._compile_real()
        assembled = A.assemble_chapters(
            accepted_artifacts=[_real_fixture_artifact()],
            chapter_plan={
                "version": "c2r1-chapters-v1",
                "revision_id": "rev_c2r2_demo_001",
                "source_sha256": json.loads((FIXTURES / "request.json").read_text())["source_sha256"],
                "normalized_sha256": json.loads((FIXTURES / "request.json").read_text())["normalized_sha256"],
                "chapters": [
                    {
                        "chapter_id": "ch_756922e9af0d759d29d7475f",
                        "chapter_index": 0,
                        "content_sha256": json.loads((FIXTURES / "request.json").read_text())["normalized_sha256"],
                    }
                ],
            },
        )
        blocks = {block["block_id"]: block["text"] for block in assembled["translation_blocks"]}
        self.assertEqual(
            [unit["block_id"] for unit in projection["units"]],
            [block["block_id"] for block in assembled["translation_blocks"]],
        )
        for unit in projection["units"]:
            joined = "".join(segment["text"] for segment in unit["segments"])
            self.assertEqual(joined, blocks[unit["block_id"]])
            self.assertEqual(unit["text_hash"], sha256_text(joined))
        self.assertEqual(
            projection["full_text_sha256"],
            sha256_text("".join(units_text(projection))),
        )


def units_text(projection: dict) -> list[str]:
    return ["".join(segment["text"] for segment in unit["segments"]) for unit in projection["units"]]


class CrossChapterRemapTests(unittest.TestCase):
    def test_same_local_ids_remap_to_distinct_canonical_ids(self) -> None:
        first = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[_event("evt_001", "戰役", participants=["ent_001"], time=_time())],
            blocks=[_block("t_001", "曹操出戰。", ["ent_001"], ["evt_001"])],
            reading_units=[_unit("t_001", "曹操出戰。", spans=[_span("es_001", 0, 2, "曹操")], contexts=[_context("ent_001")])],
        )
        second = _artifact(
            CH1,
            entities=[_entity("ent_001", "曹操")],
            events=[_event("evt_001", "戰役", participants=["ent_001"], time=_time())],
            blocks=[_block("t_001", "曹操再戰。", ["ent_001"], ["evt_001"])],
            reading_units=[_unit("t_001", "曹操再戰。", spans=[_span("es_001", 0, 2, "曹操")], contexts=[_context("ent_001")])],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1), "ent_001001": _canonical("e", 2)},
            {"evt_000001": _canonical("f", 1), "evt_001001": _canonical("f", 2)},
        )
        projection = _compile([first, second], _plan([CH0, CH1]), catalog)
        units = {unit["chapter_id"]: unit for unit in projection["units"]}
        self.assertNotEqual(units[CH0]["unit_id"], units[CH1]["unit_id"])
        self.assertNotEqual(
            units[CH0]["context_entities"][0]["canonical_id"],
            units[CH1]["context_entities"][0]["canonical_id"],
        )
        self.assertNotEqual(
            units[CH0]["segments"][0]["span"]["target_event_id"],
            units[CH1]["segments"][0]["span"]["target_event_id"],
        )
        # Same local name/ref never merges across chapters.
        self.assertEqual(
            {"ent_000001", "ent_001001"},
            {unit["context_entities"][0]["entity_ref"] for unit in projection["units"]},
        )

    def test_unknown_ref_is_not_bound_by_name(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操"), _entity("ent_002", "曹操")],
            events=[_event("evt_001", "戰役", participants=["ent_001"], time=_time())],
            blocks=[_block("t_001", "曹操出戰。", ["ent_001", "ent_002"], ["evt_001"])],
            reading_units=[
                _unit(
                    "t_001",
                    "曹操出戰。",
                    contexts=[_context("ent_001"), _context("ent_002", importance="other")],
                )
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)},
            {"evt_000001": _canonical("f", 1)},
        )
        projection = _compile([artifact], _plan([CH0]), catalog)
        contexts = {
            context["entity_ref"]: context["canonical_id"]
            for context in projection["units"][0]["context_entities"]
        }
        self.assertEqual(_canonical("e", 1), contexts["ent_000001"])
        self.assertIsNone(contexts["ent_000002"])


class NarrativeTimeTests(unittest.TestCase):
    def test_same_month_shares_marker_and_month_change_adds_one(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[
                _event("evt_001", "八月事", participants=["ent_001"], time=_time(month=8)),
                _event("evt_002", "九月事", participants=["ent_001"], time=_time(month=9)),
            ],
            blocks=[
                _block("t_001", "八月。", ["ent_001"], ["evt_001"]),
                _block("t_002", "又八月。", ["ent_001"], ["evt_001"]),
                _block("t_003", "九月。", ["ent_001"], ["evt_002"]),
            ],
            reading_units=[
                _unit("t_001", "八月。", event_ref="evt_001", contexts=[]),
                _unit("t_002", "又八月。", event_ref="evt_001", contexts=[]),
                _unit("t_003", "九月。", event_ref="evt_002", contexts=[]),
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)},
            {"evt_000001": _canonical("f", 1), "evt_000002": _canonical("f", 2)},
        )
        projection = _compile([artifact], _plan([CH0]), catalog)
        self.assertEqual(2, len(projection["groups"]))
        self.assertEqual(2, projection["groups"][0]["unit_count"])
        self.assertEqual("建安13年", projection["groups"][0]["year_label"])
        self.assertIsNone(projection["groups"][1]["year_label"])
        self.assertNotEqual(
            projection["groups"][0]["period_key"], projection["groups"][1]["period_key"]
        )
        self.assertFalse(projection["units"][0]["continues_previous"])
        self.assertTrue(projection["units"][1]["continues_previous"])
        self.assertFalse(projection["units"][2]["continues_previous"])

    def test_unknown_is_its_own_group(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[_event("evt_001", "無時間", participants=["ent_001"], time=None)],
            blocks=[_block("t_001", "未詳。", ["ent_001"], ["evt_001"])],
            reading_units=[_unit("t_001", "未詳。", event_ref="evt_001", contexts=[])],
        )
        catalog = _catalog({"ent_000001": _canonical("e", 1)}, {"evt_000001": _canonical("f", 1)})
        projection = _compile([artifact], _plan([CH0]), catalog)
        self.assertEqual("unknown", projection["groups"][0]["year_key"])
        self.assertEqual("时间未明确", projection["groups"][0]["period_label"])

    def test_source_regnal_and_gregorian_keys_never_merge(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[
                _event("evt_001", "史料八月", participants=["ent_001"], time=_time(month=8)),
                _event("evt_002", "公历八月", participants=["ent_001"], time=_gregorian_time(208, 8)),
            ],
            blocks=[
                _block("t_001", "八月。", ["ent_001"], ["evt_001"]),
                _block("t_002", "又八月。", ["ent_001"], ["evt_002"]),
            ],
            reading_units=[
                _unit("t_001", "八月。", event_ref="evt_001", contexts=[]),
                _unit("t_002", "又八月。", event_ref="evt_002", contexts=[]),
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)},
            {"evt_000001": _canonical("f", 1), "evt_000002": _canonical("f", 2)},
        )
        projection = _compile([artifact], _plan([CH0]), catalog)
        self.assertEqual(2, len(projection["groups"]))
        self.assertNotEqual(
            projection["groups"][0]["period_key"], projection["groups"][1]["period_key"]
        )

    def test_flashback_years_keep_narrative_order(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[
                _event("evt_001", "十三年事", participants=["ent_001"], time=_time(era_year=13)),
                _event("evt_002", "十五年事", participants=["ent_001"], time=_time(era_year=15)),
                _event("evt_003", "回溯十三年", participants=["ent_001"], time=_time(era_year=13)),
            ],
            blocks=[
                _block("t_001", "一。", ["ent_001"], ["evt_001"]),
                _block("t_002", "二。", ["ent_001"], ["evt_002"]),
                _block("t_003", "三。", ["ent_001"], ["evt_003"]),
            ],
            reading_units=[
                _unit("t_001", "一。", event_ref="evt_001", contexts=[]),
                _unit("t_002", "二。", event_ref="evt_002", contexts=[]),
                _unit("t_003", "三。", event_ref="evt_003", contexts=[]),
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)},
            {f"evt_{i:06d}": _canonical("f", i) for i in (1, 2, 3)},
        )
        projection = _compile([artifact], _plan([CH0]), catalog)
        self.assertEqual(3, len(projection["groups"]))
        self.assertEqual(
            projection["groups"][0]["year_key"], projection["groups"][2]["year_key"]
        )
        self.assertNotEqual(
            projection["groups"][0]["year_key"], projection["groups"][1]["year_key"]
        )
        self.assertEqual(
            [unit["ordinal"] for unit in projection["units"]], [0, 1, 2]
        )


class InheritanceTests(unittest.TestCase):
    def _two_block_artifact(self, *, first_mode: str = "events") -> dict:
        return _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[_event("evt_001", "戰役", participants=["ent_001"], time=_time())],
            blocks=[
                _block("t_001", "曹操。", ["ent_001"], ["evt_001"] if first_mode != "unknown" else ["evt_001"]),
                _block("t_002", "續。", ["ent_001"], ["evt_001"]),
            ],
            reading_units=[
                _unit("t_001", "曹操。", mode=first_mode, contexts=[]),
                _unit("t_002", "續。", mode="inherit", from_block_id="t_001", contexts=[]),
            ],
        )

    def test_inherit_resolves_to_earlier_unit(self) -> None:
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)}, {"evt_000001": _canonical("f", 1)}
        )
        projection = _compile([self._two_block_artifact()], _plan([CH0]), catalog)
        first, second = projection["units"]
        self.assertEqual("inherit", second["narrative_time"]["mode"])
        self.assertEqual("t_000001", second["narrative_time"]["from_block_id"])
        self.assertEqual(first["narrative_time"]["period_key"], second["narrative_time"]["period_key"])
        self.assertEqual(first["group_id"], second["group_id"])

    def test_inheritance_to_unknown_block_rejected(self) -> None:
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)}, {"evt_000001": _canonical("f", 1)}
        )
        with self.assertRaises(PersistenceError):
            _compile([self._two_block_artifact(first_mode="unknown")], _plan([CH0]), catalog)

    def test_inheritance_cycle_rejected(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[_event("evt_001", "戰役", participants=["ent_001"], time=_time())],
            blocks=[
                _block("t_001", "一。", ["ent_001"], ["evt_001"]),
                _block("t_002", "二。", ["ent_001"], ["evt_001"]),
            ],
            reading_units=[
                _unit("t_001", "一。", mode="inherit", from_block_id="t_002", contexts=[]),
                _unit("t_002", "二。", mode="inherit", from_block_id="t_001", contexts=[]),
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)}, {"evt_000001": _canonical("f", 1)}
        )
        with self.assertRaises(PersistenceError):
            _compile([artifact], _plan([CH0]), catalog)


class OccurrenceAndRoleTests(unittest.TestCase):
    def test_current_and_mention_rows_are_distinguished(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[
                _event("evt_001", "赤壁", participants=["ent_001"], time=_time()),
                _event("evt_002", "舊事", participants=["ent_001"], time=_time()),
            ],
            blocks=[_block("t_001", "赤壁大戰，追憶往事。", ["ent_001"], ["evt_001", "evt_002"])],
            reading_units=[
                _unit(
                    "t_001",
                    "赤壁大戰，追憶往事。",
                    event_refs=["evt_001"],
                    spans=[
                        _span("es_001", 0, 2, "赤壁", target_ref="evt_001", relation="current"),
                        _span("es_002", 7, 9, "往事", target_ref="evt_002", relation="retrospective"),
                    ],
                    contexts=[],
                )
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)},
            {"evt_000001": _canonical("f", 1), "evt_000002": _canonical("f", 2)},
        )
        projection = _compile([artifact], _plan([CH0]), catalog)
        relations = {(row["span_id"], row["relation"]) for row in projection["occurrences"]}
        self.assertEqual({("es_001", "current"), ("es_002", "mention")}, relations)

    def test_context_role_must_be_a_current_event(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[
                _event("evt_001", "現在", participants=["ent_001"], time=_time()),
                _event("evt_002", "過去", participants=["ent_001"], time=_time()),
            ],
            blocks=[_block("t_001", "曹操。", ["ent_001"], ["evt_001", "evt_002"])],
            reading_units=[
                _unit(
                    "t_001",
                    "曹操。",
                    event_refs=["evt_001"],
                    contexts=[_context("ent_001", event_ref="evt_002")],
                )
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)},
            {"evt_000001": _canonical("f", 1), "evt_000002": _canonical("f", 2)},
        )
        with self.assertRaises(PersistenceError):
            _compile([artifact], _plan([CH0]), catalog)

    def test_context_role_without_source_participant_rejected(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[_event("evt_001", "現在", participants=["ent_001"], time=_time())],
            blocks=[_block("t_001", "曹操。", ["ent_001"], ["evt_001"])],
            reading_units=[
                _unit(
                    "t_001",
                    "曹操。",
                    contexts=[
                        {
                            "entity_ref": "ent_001",
                            "importance": "primary",
                            "event_roles": [
                                {"event_ref": "evt_001", "role": None, "participant_index": 0}
                            ],
                        }
                    ],
                )
            ],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)}, {"evt_000001": _canonical("f", 1)}
        )
        with self.assertRaises(PersistenceError):
            _compile([artifact], _plan([CH0]), catalog)


class FailClosedTests(unittest.TestCase):
    def test_future_latest_display_field_rejected(self) -> None:
        with self.assertRaises(PersistenceError):
            RP.assert_no_future_latest_fields({"latest_publication_id": "x"})
        with self.assertRaises(PersistenceError):
            RP.assert_no_future_latest_fields({"groups": [{"future": True}]})

    def test_unit_size_limit_enforced(self) -> None:
        artifacts, plan, catalog = _single_chapter(time=_time())
        with self.assertRaises(PersistenceError):
            _compile(
                artifacts,
                plan,
                catalog,
                limits=RC.ReadingLimits(unit_max_bytes=1),
            )

    def test_missing_publication_rejected(self) -> None:
        artifacts, plan, catalog = _single_chapter(time=_time())
        with self.assertRaises(PersistenceError):
            _compile(artifacts, plan, catalog, publications={})

    def test_canonical_conflict_rejected(self) -> None:
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)},
            {"evt_000001": _canonical("f", 1)},
        )
        catalog["canonical_entities"].append(
            {"canonical_id": _canonical("e", 2), "representations": [{"bundle": BUNDLE_LABEL, "ref": "ent_000001"}]}
        )
        with self.assertRaises(PersistenceError):
            RP.build_canonical_ref_map(catalog, bundle_label=BUNDLE_LABEL)

    def test_non_0_2_artifacts_rejected(self) -> None:
        artifacts, plan, _ = _single_chapter(time=_time())
        plain = copy.deepcopy(artifacts[0])
        plain["candidate"].pop("reading", None)
        plain["candidate"]["version"] = "0.1"
        plain["version"] = "0.1"
        plain.pop("reading", None)
        plain.pop("reading_sha256", None)
        plain.pop("reading_units", None)
        plain["candidate_sha256"] = sha256_json(plain["candidate"])
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)}, {"evt_000001": _canonical("f", 1)}
        )
        with self.assertRaises(PersistenceError):
            _compile([plain], plan, catalog)


class AcceptedHashAndOrderRegressionTests(unittest.TestCase):
    """Regression: accepted canonical hash and source order drive the rows."""

    def test_accepted_artifact_hash_is_used_for_unit_id(self) -> None:
        request = json.loads((FIXTURES / "request.json").read_text(encoding="utf-8"))
        artifact = _real_fixture_artifact()
        projection = RealFixtureCompilationTests()._compile_real()
        self.assertNotEqual(artifact["artifact_sha256"], sha256_json(artifact))
        for unit in projection["units"]:
            self.assertEqual(artifact["artifact_sha256"], unit["artifact_sha256"])
            self.assertEqual(
                RC.unit_id_for(
                    revision_id=request["revision_id"],
                    chapter_id=unit["chapter_id"],
                    block_id=unit["block_id"],
                    artifact_sha256=artifact["artifact_sha256"],
                ),
                unit["unit_id"],
            )

    def test_source_order_is_preserved_for_nonstandard_block_ids(self) -> None:
        artifact = _artifact(
            CH0,
            entities=[_entity("ent_001", "曹操")],
            events=[_event("evt_001", "戰役", participants=["ent_001"], time=_time())],
            blocks=[
                _block("t_100", "第一。", ["ent_001"], ["evt_001"]),
                _block("t_001", "第二。", ["ent_001"], ["evt_001"]),
            ],
            reading_units=[_unit("t_100", "第一。", contexts=[]), _unit("t_001", "第二。", contexts=[])],
        )
        catalog = _catalog(
            {"ent_000001": _canonical("e", 1)}, {"evt_000001": _canonical("f", 1)}
        )
        projection = _compile([artifact], _plan([CH0]), catalog)
        self.assertEqual(["t_000100", "t_000001"], [unit["block_id"] for unit in projection["units"]])
        self.assertEqual(
            ["第一。", "第二。"],
            ["".join(segment["text"] for segment in unit["segments"]) for unit in projection["units"]],
        )


if __name__ == "__main__":
    unittest.main()
