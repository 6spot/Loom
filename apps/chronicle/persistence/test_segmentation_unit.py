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

    def test_hierarchy_depth_and_parent_are_deterministic(self) -> None:
        _, _, plan = _fixture_plan()
        by_kind = {s.kind: s for s in plan.sections}
        volume = by_kind["volume"]
        self.assertEqual((volume.depth, volume.parent_section_index), (0, None))
        for kind in ("treatise", "biography"):
            child = by_kind[kind]
            self.assertEqual(child.depth, 1)
            self.assertEqual(child.parent_section_index, volume.section_index)

    def test_markdown_levels_nest(self) -> None:
        text = "# 史記\n\n## 本紀\n\n文字甲。\n\n## 列傳\n\n文字乙。\n"
        plan = S.segment_revision(
            text, hashlib.sha256(b"m").hexdigest(), SegmentationConfig()
        )
        kinds = [(s.kind, s.depth, s.parent_section_index) for s in plan.sections]
        self.assertEqual(kinds[0][0], "heading")
        self.assertEqual(kinds[0][1], 0)
        self.assertIsNone(kinds[0][2])
        # `## 本紀` classifies as biography at depth 1 under the title.
        self.assertEqual(plan.sections[1].parent_section_index, 0)
        self.assertEqual(plan.sections[2].parent_section_index, 0)

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

    def test_context_reserve_counts_alongside_actual_context(self) -> None:
        # D-1 boundary: every reserve plus the actuals must fit. With
        # max=300, prompt=50, context reserve=100, output=50, chunk=100 and
        # serialized context=100, the accounted total is 400 > 300.
        config = SegmentationConfig(
            max_chunk_chars=100,
            max_input_chars=300,
            reserved_prompt_chars=50,
            reserved_context_chars=100,
            reserved_output_chars=50,
        )
        report = S.check_budgets(100, 100, config)
        self.assertEqual(report["total_chars"], 400)
        self.assertEqual(report["headroom_chars"], -100)
        self.assertFalse(report["fits"])
        with self.assertRaises(PersistenceError):
            S.ensure_budgets(100, 100, config)

    def test_chain_contexts_fit_their_reserve(self) -> None:
        text, config, plan = _fixture_plan()
        pairs = S.context_chain(plan, text, config)
        self.assertTrue(pairs)
        for pair in pairs:
            self.assertTrue(pair["output"]["budget"]["fits"])



    def test_long_pronoun_dense_context_is_trimmed_to_budget(self) -> None:
        # Regression for the C1-T17 real-machine failure: a complete
        # long-form historical source produced dozens of uncertain pronoun
        # hints in its first ~2K-char chunk and overflowed ContextState before
        # extraction could begin.
        sentence = (
            "建安十三年，曹操谓刘备曰：吾与汝共论天下，其志如此，"
            "公何以处之？先主曰：吾不忍也。"
        )
        text = sentence * 180
        self.assertGreater(len(text), 7000)

        config = SegmentationConfig()
        plan = S.segment_revision(
            text,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            config,
        )
        self.assertGreaterEqual(len(plan.chunks), 4)

        first = plan.chunks[0]
        first_text = text[first.source_start : first.source_end]
        raw_hints = S.find_pronoun_hints(first_text, [], first.chunk_index)
        self.assertGreater(len(raw_hints), config.max_coreference_hints)

        pairs = S.context_chain(plan, text, config)
        capacity = S._forward_context_capacity(config)

        for pair in pairs:
            out = pair["output"]
            serialized = len(
                json.dumps(out, ensure_ascii=False, sort_keys=True)
            )
            accounted = int(out["budget"]["context_chars"])

            self.assertTrue(out["budget"]["fits"])
            self.assertLessEqual(serialized, accounted)
            self.assertLessEqual(accounted, capacity)
            self.assertTrue(
                S.check_budgets(
                    config.max_chunk_chars,
                    accounted,
                    config,
                )["fits"]
            )

        self.assertLess(
            len(pairs[0]["output"]["coreference_hints"]),
            len(raw_hints),
        )

        for before, after in zip(pairs, pairs[1:]):
            self.assertEqual(after["input"], before["output"])


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

    def test_zero_caps_mean_empty_collections(self) -> None:
        # D-7: zero caps disable tracking; they must not leak one item,
        # the whole list (via [-0:]), or any inherited state.
        config = SegmentationConfig(
            max_chunk_chars=50,
            boundary_context_chars=0,
            max_entities=0,
            max_places=0,
            max_events=0,
            max_time_exprs=0,
        )
        text = "建安十三年，曹操率大軍至荊州。劉表卒。"
        pair = S.advance_context(S.initial_context(), text, 0, config)
        out = pair["output"]
        self.assertEqual(out["inherited_time"], [])
        self.assertEqual(out["active_entities"], [])
        self.assertEqual(out["active_places"], [])
        self.assertEqual(out["recent_events"], [])
        self.assertEqual(out["prev_tail"], "")
        self.assertEqual(S.extract_time_expressions(text, 0), [])
        self.assertEqual(S.extract_candidate_mentions(text, 0), [])
        self.assertEqual(S.extract_candidate_places(text, 0), [])
        self.assertEqual(S.extract_event_snippets(text, 0), [])
        # And a zero cap drops even previously tracked state on advance.
        first = S.advance_context(
            S.initial_context(), text, 0, SegmentationConfig()
        )["output"]
        self.assertTrue(first["active_entities"])
        second = S.advance_context(first, text, 1, config)["output"]
        self.assertEqual(second["active_entities"], [])
        self.assertEqual(second["inherited_time"], [])

    def test_separator_coverage_never_exceeds_chunk_bound(self) -> None:
        # D-8: the exact boundary — separator whitespace stays covered
        # without pushing any persisted range past max_chunk_chars.
        text = "abcdefghij\n\nklmnopqrst"
        config = SegmentationConfig(
            max_chunk_chars=10, boundary_context_chars=4
        )
        plan = S.segment_revision(
            text, hashlib.sha256(b"b8").hexdigest(), config
        )
        ranges = [(c.source_start, c.source_end) for c in plan.chunks]
        self.assertTrue(len(ranges) >= 2)
        for start, end in ranges:
            self.assertLessEqual(end - start, config.max_chunk_chars)
        self.assertEqual("".join(text[s:e] for s, e in ranges), text)

    def test_overlap_is_clamped_to_the_chunk_bound(self) -> None:
        # D-8 companion: explicit overlap backs up only while the
        # persisted range still respects max_chunk_chars.
        text = "0123456789\n\nab"
        config = SegmentationConfig(
            max_chunk_chars=10, overlap_chars=8, boundary_context_chars=4
        )
        plan = S.segment_revision(
            text, hashlib.sha256(b"b8o").hexdigest(), config
        )
        for chunk in plan.chunks:
            self.assertLessEqual(
                chunk.source_end - chunk.source_start, config.max_chunk_chars
            )
        self.assertEqual(plan.chunks[1].overlap_prev_chars, 6)
        self.assertEqual(
            plan.chunks[1].source_end - plan.chunks[1].source_start, 10
        )

    def test_forwarded_inputs_fit_the_window(self) -> None:
        # D-9: the gate covers the actual forwarded bytes, so every
        # chunk's real input (previous output, budget report attached)
        # plus its own text fits the configured window — and a window
        # the forwarded state cannot honor fails closed instead of
        # reporting a fit the next input cannot keep.
        text = "曹操率軍。\n\n曹操敗走。\n\n曹操降。"
        base = dict(
            max_chunk_chars=10,
            boundary_context_chars=10,
            reserved_prompt_chars=0,
            reserved_context_chars=0,
            reserved_output_chars=0,
        )
        config = SegmentationConfig(max_input_chars=800, **base)
        plan = S.segment_revision(
            text, hashlib.sha256(b"b9").hexdigest(), config
        )
        self.assertGreaterEqual(len(plan.chunks), 3)
        pairs = S.context_chain(plan, text, config)
        for pair in pairs:
            chunk_text = text[
                plan.chunks[pair["output"]["chunk_index"]].source_start :
                plan.chunks[pair["output"]["chunk_index"]].source_end
            ]
            input_chars = len(
                json.dumps(pair["input"], ensure_ascii=False, sort_keys=True)
            )
            report = S.check_budgets(len(chunk_text), input_chars, config)
            self.assertTrue(
                report["fits"],
                msg=f"chunk input exceeds window: {report}",
            )
        tight = SegmentationConfig(max_input_chars=600, **base)
        with self.assertRaises(PersistenceError):
            S.context_chain(plan, text, tight)

    def test_oversized_inherited_state_is_gated_before_advance(self) -> None:
        # D-10: an already oversized inherited ContextState must fail at
        # the input gate before the current chunk is allowed to advance or
        # shrink it. Ctx-v2 normally prevents producing such a state, but
        # the gate remains mandatory for persisted/resumed/corrupt input.
        config = SegmentationConfig(
            max_chunk_chars=100,
            boundary_context_chars=0,
            max_input_chars=4755,
            reserved_prompt_chars=0,
            reserved_context_chars=0,
            reserved_output_chars=0,
        )

        state = S.initial_context()
        state["coreference_hints"] = [
            {
                "pronoun": "其",
                "pronoun_chunk": 0,
                "antecedent_hint": "曹操" * 20,
                "uncertain": True,
                "basis": "nearest-prior-surface",
            }
            for _ in range(60)
        ]

        chunk_text = "x" * 100
        context_chars = len(
            json.dumps(state, ensure_ascii=False, sort_keys=True)
        )
        report = S.check_budgets(
            len(chunk_text), context_chars, config
        )
        self.assertFalse(report["fits"])

        with self.assertRaises(PersistenceError):
            S._ensure_input_budgets(state, chunk_text, config)

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

    def test_repeated_entity_does_not_mutate_prior_output(self) -> None:
        # D-2 regression: 曹操 appears in both chunks, so advancing the
        # second chunk increments a count. The first chunk's already
        # produced output must stay byte-identical (persisted chain stays
        # replayable): pairs[1].input == pairs[0].output exactly.
        text = "曹操率軍至荊州。\n\n曹操敗走，舉軍而降。"
        config = SegmentationConfig(max_chunk_chars=16, boundary_context_chars=10)
        plan = S.segment_revision(
            text, hashlib.sha256(b"r").hexdigest(), config
        )
        self.assertGreater(len(plan.chunks), 1)
        pairs = S.context_chain(plan, text, config)
        self.assertEqual(pairs[1]["input"], pairs[0]["output"])
        first_entities = {
            e["text"]: e["count"]
            for e in pairs[0]["output"]["active_entities"]
        }
        self.assertEqual(first_entities.get("曹操"), 1)
        second_entities = {
            e["text"]: e["count"]
            for e in pairs[1]["output"]["active_entities"]
        }
        self.assertEqual(second_entities.get("曹操"), 2)

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
