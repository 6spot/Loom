"""Unit tests for Chronicle C1-T5 segmentation and context state.

Pure deterministic tests: no PostgreSQL, no model, no network. Database
round trips for section/chunk persistence live in
``apps/chronicle/worker/test_segmentation_postgres.py``.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import segmentation as S
from segmentation import SegmentationConfig
from common import PersistenceError

FIXTURE_DIR = (
    HERE.parent / "ingestion" / "fixtures" / "c1t5-boundary-continuity"
)


def _fixture_text() -> str:
    raw = (FIXTURE_DIR / "raw.txt").read_bytes()
    text = raw.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _fixture_spec() -> dict:
    return json.loads((FIXTURE_DIR / "expected-context.json").read_text())


def _fixture_plan():
    spec = _fixture_spec()
    text = _fixture_text()
    config = SegmentationConfig(**spec["segmentation_config"])
    sha = hashlib.sha256(b"c1t5-boundary-continuity").hexdigest()
    return text, config, S.segment_revision(text, sha, config)


class StructureTests(unittest.TestCase):
    def test_fixture_detects_volume_treatise_biography(self) -> None:
        text, _, plan = _fixture_plan()
        self.assertGreaterEqual(len(plan.sections), 3)
        kinds = [s.kind for s in plan.sections]
        for expected in ("volume", "treatise", "biography"):
            self.assertIn(expected, kinds)
        labels = [s.label for s in plan.sections]
        self.assertIn("卷一", labels)
        self.assertIn("武帝紀", labels)
        self.assertIn("列傳", labels)

    def test_heading_line_opens_its_section(self) -> None:
        text, _, plan = _fixture_plan()
        offset = text.index("列傳第二")
        section = next(s for s in plan.sections if s.kind == "biography")
        self.assertEqual(section.source_start, offset)

    def test_prose_lines_are_not_headings(self) -> None:
        for line in (
            "建安十三年，曹操率大軍至荊州。",
            "操既定荊州，遂順流而東，欲并吞江東。",
            "孫權領江東，命周瑜為大都督。",
        ):
            self.assertIsNone(S._classify_heading(line), msg=line)

    def test_no_structure_falls_back_to_single_section(self) -> None:
        text = "曹操率軍至荊州。劉表卒，其子立。"
        plan = S.segment_revision(
            text, hashlib.sha256(b"x").hexdigest(), SegmentationConfig()
        )
        self.assertEqual(len(plan.sections), 1)
        self.assertEqual(plan.sections[0].kind, "document")
        self.assertEqual(plan.manifest["structure"]["fallback"], "single-section")

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(PersistenceError):
            S.segment_revision(
                "", hashlib.sha256(b"x").hexdigest(), SegmentationConfig()
            )

    def test_bad_source_sha_is_rejected(self) -> None:
        with self.assertRaises(PersistenceError):
            S.segment_revision("曹操。", "not-a-sha", SegmentationConfig())


class SegmentationTests(unittest.TestCase):
    def test_offsets_reconstruct_exact_source(self) -> None:
        text, _, plan = _fixture_plan()
        for chunk in plan.chunks:
            sliver = text[chunk.source_start : chunk.source_end]
            self.assertTrue(sliver.strip())
            self.assertEqual(
                hashlib.sha256(sliver.encode("utf-8")).hexdigest(),
                chunk.content_sha256,
            )

    def test_chunks_tile_each_section_without_gaps(self) -> None:
        text, _, plan = _fixture_plan()
        for section in plan.sections:
            owned = [c for c in plan.chunks if c.section_index == section.section_index]
            if not owned:
                continue
            joined = "".join(
                text[c.source_start : c.source_end] for c in owned
            )
            self.assertEqual(
                joined, text[section.source_start : section.source_end]
            )

    def test_chunks_respect_the_size_budget(self) -> None:
        text, config, plan = _fixture_plan()
        for chunk in plan.chunks:
            self.assertLessEqual(
                chunk.source_end - chunk.source_start, config.max_chunk_chars
            )

    def test_natural_boundaries_beat_blind_slicing(self) -> None:
        text, config, plan = _fixture_plan()
        blind = [
            (i, min(i + config.max_chunk_chars, len(text)))
            for i in range(0, len(text), config.max_chunk_chars)
        ]
        actual = [(c.source_start, c.source_end) for c in plan.chunks]
        self.assertNotEqual(actual, blind)
        # Every boundary sits on a paragraph/sentence seam, never mid-word
        # of a blind cut: each chunk after the first starts at a section
        # start, a paragraph start, or right after sentence punctuation.
        for chunk in plan.chunks[1:]:
            prev = text[chunk.source_start - 1]
            self.assertIn(prev, "\n。！？!?…；;", msg=text[max(0, chunk.source_start - 8) : chunk.source_end][:32])

    def test_determinism_same_input_same_plan(self) -> None:
        text, config, first = _fixture_plan()
        sha = hashlib.sha256(b"c1t5-boundary-continuity").hexdigest()
        second = S.segment_revision(text, sha, config)
        self.assertEqual(first.manifest["plan_sha256"], second.manifest["plan_sha256"])
        self.assertEqual(
            [(c.source_start, c.source_end) for c in first.chunks],
            [(c.source_start, c.source_end) for c in second.chunks],
        )

    def test_overlap_is_zero_and_explicit_by_default(self) -> None:
        _, _, plan = _fixture_plan()
        for chunk in plan.chunks:
            self.assertEqual(chunk.overlap_prev_chars, 0)

    def test_explicit_overlap_backs_up_within_section(self) -> None:
        text = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥。" * 4
        config = SegmentationConfig(
            max_chunk_chars=40, overlap_chars=8, boundary_context_chars=10
        )
        plan = S.segment_revision(
            text, hashlib.sha256(b"y").hexdigest(), config
        )
        self.assertGreater(len(plan.chunks), 1)
        for chunk in plan.chunks[1:]:
            self.assertEqual(chunk.overlap_prev_chars, 8)

    def test_manifest_records_versions_and_non_authority(self) -> None:
        _, _, plan = _fixture_plan()
        manifest = plan.manifest
        self.assertEqual(manifest["segmentation_version"], S.SEGMENTATION_VERSION)
        self.assertEqual(manifest["structure_version"], S.STRUCTURE_VERSION)
        self.assertEqual(manifest["context_version"], S.CONTEXT_VERSION)
        self.assertEqual(manifest["model_version"], S.MODEL_VERSION)
        self.assertEqual(manifest["prompt_version"], S.PROMPT_VERSION)
        self.assertEqual(manifest["offset_unit"], S.OFFSET_UNIT)
        self.assertFalse(manifest["authoritative"])

    def test_bad_config_is_rejected(self) -> None:
        with self.assertRaises(PersistenceError):
            SegmentationConfig(max_chunk_chars=0)
        with self.assertRaises(PersistenceError):
            SegmentationConfig(overlap_chars=9999, max_chunk_chars=10)
        with self.assertRaises(PersistenceError):
            SegmentationConfig(
                max_input_chars=100,
                reserved_prompt_chars=50,
                reserved_context_chars=40,
                reserved_output_chars=30,
            )


class BudgetTests(unittest.TestCase):
    def test_default_config_leaves_chunk_room(self) -> None:
        config = SegmentationConfig()
        report = S.check_budgets(2000, 500, config)
        self.assertTrue(report["fits"])
        self.assertGreater(report["headroom_chars"], 0)

    def test_oversized_chunk_fails_closed(self) -> None:
        config = SegmentationConfig()
        report = S.check_budgets(7000, 1000, config)
        self.assertFalse(report["fits"])
        with self.assertRaises(PersistenceError):
            S.ensure_budgets(7000, 1000, config)

    def test_chain_contexts_fit_their_reserve(self) -> None:
        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        self.assertTrue(pairs)
        for pair in pairs:
            self.assertTrue(pair["output"]["budget"]["fits"])


class ContextContinuityTests(unittest.TestCase):
    def test_chain_input_matches_previous_output(self) -> None:
        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        self.assertGreater(len(pairs), 1)
        for before, after in zip(pairs, pairs[1:]):
            self.assertEqual(after["input"], before["output"])

    def test_explicit_time_then_verbatim_inheritance(self) -> None:
        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        explicit = [
            (i, p) for i, p in enumerate(pairs)
            if "建安十三年" in text[plan.chunks[i].source_start : plan.chunks[i].source_end]
        ]
        self.assertTrue(explicit)
        first_index, first_pair = explicit[0]
        entry = next(
            item for item in first_pair["output"]["inherited_time"]
            if item["text"] == "建安十三年"
        )
        self.assertEqual(entry["scope"], "explicit")
        self.assertEqual(entry["source_chunk"], first_index)
        # A later chunk without its own time expression inherits verbatim:
        # same text, same origin, no invented precision.
        later = [
            p for i, p in enumerate(pairs)
            if i > first_index
            and "建安十三年" not in text[plan.chunks[i].source_start : plan.chunks[i].source_end]
        ]
        self.assertTrue(later)
        inherited = next(
            item for item in later[0]["output"]["inherited_time"]
            if item["text"] == "建安十三年"
        )
        self.assertEqual(inherited["scope"], "inherited")
        self.assertEqual(inherited["source_chunk"], first_index)

    def test_entities_places_events_survive_boundaries(self) -> None:
        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        last = pairs[-1]["output"]
        surfaces = [e["text"] for e in last["active_entities"]]
        for expected in ("曹操", "劉琮", "張遼", "周瑜"):
            self.assertTrue(
                any(expected in surface for surface in surfaces),
                msg=f"{expected} missing from {surfaces}",
            )
        places = [e["text"] for e in last["active_places"]]
        self.assertTrue(any("荊" in surface for surface in places), msg=places)
        events = [e["text"] for e in last["recent_events"]]
        self.assertTrue(
            any("曹操率大軍至荊州" in event for event in events), msg=events
        )

    def test_coreference_hints_stay_uncertain(self) -> None:
        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        seen = [h for p in pairs for h in p["output"]["coreference_hints"]]
        self.assertTrue(seen)
        for hint in seen:
            self.assertTrue(hint["uncertain"])
            self.assertEqual(hint["basis"], "nearest-prior-surface")

    def test_boundary_context_is_bounded_and_stitched(self) -> None:
        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        bound = config.boundary_context_chars
        for position, pair in enumerate(pairs):
            out = pair["output"]
            self.assertLessEqual(len(out["prev_tail"]), bound)
            self.assertLessEqual(len(out["next_head"]), bound)
            if position + 1 < len(pairs):
                nxt = text[
                    plan.chunks[position + 1].source_start : plan.chunks[
                        position + 1
                    ].source_end
                ][:bound]
                self.assertEqual(out["next_head"], nxt)
            else:
                self.assertEqual(out["next_head"], "")
            self.assertFalse(out["authoritative"])

    def test_pronoun_links_to_prior_chunk_mention(self) -> None:
        # Minimal forced boundary: the second chunk opens with a pronoun
        # whose only available antecedent lives in the first chunk.
        text = "曹操率軍至荊州，劉表卒。\n\n其後大敗而還，舉軍而降。"
        config = SegmentationConfig(max_chunk_chars=24, boundary_context_chars=20)
        plan = S.segment_revision(
            text, hashlib.sha256(b"z").hexdigest(), config
        )
        self.assertGreater(len(plan.chunks), 1)
        pairs = S.context_chain(plan, text, config)
        second = pairs[1]["output"]
        self.assertTrue(second["coreference_hints"])
        first_hint = second["coreference_hints"][0]
        self.assertEqual(first_hint["pronoun"], "其")
        # Nearest prior surface: 劉表 was introduced at the end of the
        # first chunk, so the cross-boundary pronoun resolves to it.
        self.assertEqual(first_hint["antecedent_hint"], "劉表")
        self.assertTrue(first_hint["uncertain"])

    def test_no_time_anywhere_preserves_uncertainty(self) -> None:
        text = "曹操率軍至荊州。\n\n其後大敗而還。"
        config = SegmentationConfig(max_chunk_chars=12, boundary_context_chars=10)
        plan = S.segment_revision(
            text, hashlib.sha256(b"w").hexdigest(), config
        )
        pairs = S.context_chain(plan, text, config)
        for pair in pairs:
            self.assertEqual(pair["output"]["inherited_time"], [])

    def test_version_mismatch_is_rejected(self) -> None:
        bad = S.initial_context()
        bad["version"] = "nope-v0"
        with self.assertRaises(PersistenceError):
            S.advance_context(bad, "曹操率軍。", 0, SegmentationConfig())


class CheckpointContractTests(unittest.TestCase):
    def test_locator_pins_everything_extract_needs(self) -> None:
        import uuid

        text, _, plan = _fixture_plan()
        chunk = plan.chunks[1]
        job_id, revision_id = uuid.uuid4(), uuid.uuid4()
        locator = S.chunk_locator(
            job_id=job_id,
            revision_id=revision_id,
            revision_no=2,
            source_sha256="b" * 64,
            chunk=chunk,
            section_id=uuid.uuid4(),
        )
        self.assertEqual(locator["job_id"], str(job_id))
        self.assertEqual(locator["revision_no"], 2)
        self.assertEqual(locator["source_start"], chunk.source_start)
        self.assertEqual(locator["content_sha256"], chunk.content_sha256)
        self.assertEqual(locator["offset_unit"], S.OFFSET_UNIT)
        self.assertEqual(
            locator["segmentation_version"], S.SEGMENTATION_VERSION
        )

    def test_checkpoint_carries_offsets_not_source_text(self) -> None:
        import uuid

        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        chunk = plan.chunks[1]
        sliver = text[chunk.source_start : chunk.source_end]
        checkpoint = S.chunk_checkpoint(
            locator=S.chunk_locator(
                job_id=uuid.uuid4(),
                revision_id=uuid.uuid4(),
                revision_no=1,
                source_sha256="c" * 64,
                chunk=chunk,
                section_id=None,
            ),
            context=pairs[1],
            manifest_ref={
                "plan_sha256": plan.manifest["plan_sha256"],
                "boundary_head": chunk.boundary_head,
                "boundary_tail": chunk.boundary_tail,
            },
        )
        # The full chunk text is addressable via offsets, never duplicated:
        # only bounded boundary strings may appear.
        dumped = json.dumps(checkpoint, ensure_ascii=False)
        self.assertNotIn(sliver, dumped)
        self.assertFalse(checkpoint["authoritative"])
        self.assertEqual(
            checkpoint["context_output"]["version"], S.CONTEXT_VERSION
        )


if __name__ == "__main__":
    unittest.main()
