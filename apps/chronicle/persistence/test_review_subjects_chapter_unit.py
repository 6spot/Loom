"""Chapter review plan unit tests: chapter_pair + published_batch (no PostgreSQL).

Covers the T08 frozen plan: per-candidate chapter_pair subjects, mixed
pair/batch exact-once coverage without tripping the legacy-mix guard,
plan fingerprint stability and tamper rejection, pair fan-out (no group
overrides), dismissed-as-uncertain, and bridge rejection when a
cross-chapter same chain would join two published canonical IDs.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
import unittest.mock
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import review_subjects as S  # noqa: E402
from common import (  # noqa: E402
    PersistenceConflict,
    PersistenceError,
    canonical_json_bytes,
    sha256_json,
)


def _link(candidate_id: str, left: tuple[str, str], right: tuple[str, str]) -> dict:
    return {
        "candidate_id": candidate_id,
        "left": {"bundle": left[0], "ref": left[1]},
        "right": {"bundle": right[0], "ref": right[1]},
        "decision": "uncertain",
        "confidence": 0.5,
        "rationale": "保守初始判断：跨章同名候选待人工审核",
        "signals": ["shared stable surface: 曹操"],
    }


def _within_resolution() -> dict:
    return {
        "schema": "chronicle.resolution-links",
        "version": "0.2",
        "scope": "within_revision",
        "left_bundle": {"label": "bund", "source_ref": "src_001", "source_title": "合裝本"},
        "right_bundle": {"label": "bund", "source_ref": "src_001", "source_title": "合裝本"},
        "entity_links": [_link("ec_001", ("bund", "ent_a1"), ("bund", "ent_b1"))],
        "event_links": [],
        "warnings": [],
    }


def _cross_resolution(
    left_bundle: str, left_ref: str, right_ref: str, candidate_id: str = "ec_001"
) -> dict:
    return {
        "schema": "chronicle.resolution-links",
        "version": "0.2",
        "scope": "cross_source",
        "left_bundle": {
            "label": left_bundle,
            "source_ref": "src_001",
            "source_title": left_bundle,
        },
        "right_bundle": {"label": "bund", "source_ref": "src_001", "source_title": "合裝本"},
        "entity_links": [_link(candidate_id, (left_bundle, left_ref), ("bund", right_ref))],
        "event_links": [],
        "warnings": [],
    }


def _catalog(groups: list[tuple[str, list[tuple[str, str]]]]) -> dict:
    return {
        "schema": "chronicle.canonical-catalog",
        "version": "0.1",
        "canonical_entities": [
            {
                "canonical_id": canonical_id,
                "representations": [
                    {"bundle": bundle, "ref": ref} for bundle, ref in members
                ],
            }
            for canonical_id, members in groups
        ],
        "canonical_events": [],
    }


def _chapters() -> dict[str, str]:
    return {"ent_a1": "ch_A", "ent_b1": "ch_B"}


def _plan_inputs(**overrides):
    bundle_sha = "a" * 64
    base_sha = "b" * 64
    params = {
        "job_id": uuid.uuid4(),
        "revision_id": uuid.uuid4(),
        "assembled_bundle_sha256": bundle_sha,
        "base_catalog_sha256": base_sha,
        "resolutions": [_within_resolution()],
        "catalog": None,
        "within_book_links": None,
        "chapter_by_ref": _chapters(),
    }
    params.update(overrides)
    return params


class ChapterPairSubjectTests(unittest.TestCase):
    def test_each_candidate_gets_one_staged_pair(self) -> None:
        subjects = S.build_chapter_pair_subjects(
            [_within_resolution()], chapter_by_ref=_chapters()
        )
        self.assertEqual(len(subjects), 1)
        subject = subjects[0]
        self.assertEqual(subject["review_mode"], "chapter_pair")
        self.assertEqual(subject["link_kind"], "entity")
        self.assertEqual(subject["member_count"], 1)
        self.assertTrue(subject["review_subject_id"].startswith("rp_"))
        payload = S.chapter_pair_payload(subject, plan_fingerprint="f" * 64)
        self.assertEqual(payload["scope"], "resolution")
        self.assertEqual(payload["review_mode"], "chapter_pair")
        self.assertEqual(payload["left"], {"bundle": "bund", "ref": "ent_a1"})
        self.assertEqual(payload["right"], {"bundle": "bund", "ref": "ent_b1"})
        self.assertEqual(
            payload["allowed_decisions"], ["same_entity", "not_same", "uncertain"]
        )
        self.assertIsNone(payload["decision"])

    def test_pair_decision_fans_out_to_only_that_candidate(self) -> None:
        subject = S.build_chapter_pair_subjects(
            [_within_resolution()], chapter_by_ref=_chapters()
        )[0]
        payload = S.chapter_pair_payload(subject)
        payload["decision"] = {
            "decision": "same_entity",
            "confidence": 0.9,
            "rationale": "兩章同名且字號一致",
        }
        entries = S.decision_entries_for_payload(payload, status="resolved")
        self.assertEqual(list(entries), [subject["candidate_key"]])
        self.assertEqual(entries[subject["candidate_key"]]["decision"], "same_entity")

    def test_pair_rejects_group_overrides_and_unknown_mode(self) -> None:
        subject = S.build_chapter_pair_subjects(
            [_within_resolution()], chapter_by_ref=_chapters()
        )[0]
        payload = S.chapter_pair_payload(subject)
        with self.assertRaises(PersistenceError):
            S.normalize_group_decisions(
                payload,
                [
                    {
                        "review_group_id": "rg_x",
                        "decision": "not_same",
                        "confidence": 0.9,
                        "rationale": "例外探針",
                    }
                ],
            )
        bad = dict(payload)
        bad["review_mode"] = "legacy_mixed"
        with self.assertRaises(PersistenceConflict):
            S.open_chapter_review_plan(
                __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(),
                job_id=uuid.uuid4(),
                plan={
                    "version": S.REVIEW_PLAN_VERSION,
                    "job_id": str(uuid.uuid4()),
                    "plan_fingerprint": "f" * 64,
                    "pair_payloads": [bad],
                    "batch_payloads": [],
                },
            )

    def test_dismissed_pair_collects_as_uncertain(self) -> None:
        subject = S.build_chapter_pair_subjects(
            [_within_resolution()], chapter_by_ref=_chapters()
        )[0]
        payload = S.chapter_pair_payload(subject)
        entries = S.decision_entries_for_payload(payload, status="dismissed")
        self.assertEqual(
            entries[subject["candidate_key"]]["decision"], "uncertain"
        )

    def test_same_chapter_pair_is_rejected(self) -> None:
        within = _within_resolution()
        with self.assertRaises(PersistenceError):
            S.build_chapter_pair_subjects(
                [within],
                chapter_by_ref={"ent_a1": "ch_A", "ent_b1": "ch_A"},
            )


class MixedPlanTests(unittest.TestCase):
    def _mixed(self):
        cross = _cross_resolution("old", "ent_a", "ent_a1")
        catalog = _catalog([("canon-a", [("old", "ent_a")])])
        return cross, catalog

    def test_pair_and_batch_coexist_with_exact_coverage(self) -> None:
        cross, catalog = self._mixed()
        params = _plan_inputs(resolutions=[_within_resolution(), cross], catalog=catalog)
        plan = S.build_chapter_review_plan(**params)
        self.assertEqual(plan["version"], "c2r1-review-plan-v1")
        self.assertEqual(len(plan["pair_payloads"]), 1)
        self.assertEqual(len(plan["batch_payloads"]), 1)
        covered = sorted(
            key
            for payload in plan["pair_payloads"] + plan["batch_payloads"]
            for key in S._payload_candidate_keys(payload)
        )
        expected = sorted(
            item["candidate_key"]
            for item in S._candidate_members([_within_resolution(), cross])
        )
        self.assertEqual(covered, expected)

    def test_legacy_and_pair_mix_is_rejected(self) -> None:
        legacy = {
            "schema": "chronicle.resolution-links",
            "version": "0.1",
            "left_bundle": {"label": "old", "source_ref": "src_001", "source_title": "o"},
            "right_bundle": {"label": "new", "source_ref": "src_001", "source_title": "n"},
            "entity_links": [_link("ec_001", ("old", "ent_a"), ("new", "ent_n"))],
            "event_links": [],
            "warnings": [],
        }
        with self.assertRaises(PersistenceConflict):
            S.build_chapter_review_plan(
                **_plan_inputs(resolutions=[_within_resolution(), legacy], catalog=None)
            )

    def test_fingerprint_is_stable_and_tamper_evident(self) -> None:
        cross, catalog = self._mixed()
        params = _plan_inputs(resolutions=[_within_resolution(), cross], catalog=catalog)
        first = S.build_chapter_review_plan(**params)
        second = S.build_chapter_review_plan(
            **{**params, "resolutions": [cross, _within_resolution()]}
        )
        self.assertEqual(first["plan_fingerprint"], second["plan_fingerprint"])
        # Fingerprint excludes decisions: resolving does not move it.
        resolved = copy.deepcopy(first)
        resolved["pair_payloads"][0]["decision"] = {
            "decision": "same_entity",
            "confidence": 0.9,
            "rationale": "已審核",
        }
        again = S.validate_chapter_review_plan(
            first,
            [_within_resolution(), cross],
            job_id=params["job_id"],
            revision_id=params["revision_id"],
            assembled_bundle_sha256=params["assembled_bundle_sha256"],
            base_catalog_sha256=params["base_catalog_sha256"],
        )
        self.assertEqual(again, first["plan_fingerprint"])
        with self.assertRaises(PersistenceConflict):
            S.validate_chapter_review_plan(
                first,
                [_within_resolution()],
                job_id=params["job_id"],
                revision_id=params["revision_id"],
                assembled_bundle_sha256=params["assembled_bundle_sha256"],
                base_catalog_sha256=params["base_catalog_sha256"],
            )

    def test_plan_bytes_are_deterministic(self) -> None:
        cross, catalog = self._mixed()
        params = _plan_inputs(resolutions=[_within_resolution(), cross], catalog=catalog)
        self.assertEqual(
            canonical_json_bytes(S.build_chapter_review_plan(**params)),
            canonical_json_bytes(
                S.build_chapter_review_plan(
                    **{**params, "resolutions": [cross, _within_resolution()]}
                )
            ),
        )


class BridgeRejectionTests(unittest.TestCase):
    def _reviews(
        self, plan: dict, decisions: dict[str, str]
    ) -> list[tuple[object, str, dict]]:
        rows = []
        for payload in plan["pair_payloads"] + plan["batch_payloads"]:
            key = S._payload_candidate_keys(payload)[0]
            decided = copy.deepcopy(payload)
            decided["decision"] = {
                "decision": decisions.get(key, "uncertain"),
                "confidence": 0.9,
                "rationale": "圖驗證探針",
            }
            rows.append((uuid.uuid4(), "resolved", decided))
        return rows

    def test_cross_chapter_same_chain_bridging_two_published_ids_is_rejected(
        self,
    ) -> None:
        within = _within_resolution()
        cross_a = _cross_resolution("old-a", "ent_a", "ent_a1")
        cross_b = _cross_resolution("old-b", "ent_b", "ent_b1")
        resolutions = [within, cross_a, cross_b]
        catalog = _catalog(
            [
                ("canon-a", [("old-a", "ent_a")]),
                ("canon-b", [("old-b", "ent_b")]),
            ]
        )
        params = _plan_inputs(
            resolutions=resolutions, catalog=catalog, chapter_by_ref=_chapters()
        )
        plan = S.build_chapter_review_plan(**params)
        members = {item["candidate_key"]: item for item in S._candidate_members(resolutions)}
        pair_key = next(
            key for key, member in members.items() if member["left"]["ref"] == "ent_a1"
        )
        decisions = {key: "same_entity" for key in members}
        reviews = self._reviews(plan, decisions)
        proposed_id, _, proposed_payload = next(
            (rid, status, payload)
            for rid, status, payload in reviews
            if pair_key in S._payload_candidate_keys(payload)
        )
        with self.assertRaises(S.CanonicalIdentityConflict):
            S.validate_entity_review_decision_graph(
                resolutions=resolutions,
                reviews=reviews,
                proposed_review_id=proposed_id,
                proposed_payload=proposed_payload,
                catalog=catalog,
                within_book_links=None,
            )

    def test_not_same_breaks_the_bridge(self) -> None:
        within = _within_resolution()
        cross_a = _cross_resolution("old-a", "ent_a", "ent_a1")
        cross_b = _cross_resolution("old-b", "ent_b", "ent_b1")
        resolutions = [within, cross_a, cross_b]
        catalog = _catalog(
            [
                ("canon-a", [("old-a", "ent_a")]),
                ("canon-b", [("old-b", "ent_b")]),
            ]
        )
        params = _plan_inputs(
            resolutions=resolutions, catalog=catalog, chapter_by_ref=_chapters()
        )
        plan = S.build_chapter_review_plan(**params)
        members = {item["candidate_key"]: item for item in S._candidate_members(resolutions)}
        cross_b_key = next(
            key for key, member in members.items() if member["left"]["ref"] == "ent_b"
        )
        decisions = {key: "same_entity" for key in members}
        decisions[cross_b_key] = "not_same"
        reviews = self._reviews(plan, decisions)
        pair_key = next(
            key for key, member in members.items() if member["left"]["ref"] == "ent_a1"
        )
        proposed_id, _, proposed_payload = next(
            (rid, status, payload)
            for rid, status, payload in reviews
            if pair_key in S._payload_candidate_keys(payload)
        )
        # No bridge: the remaining same-links touch only canon-a.
        S.validate_entity_review_decision_graph(
            resolutions=resolutions,
            reviews=reviews,
            proposed_review_id=proposed_id,
            proposed_payload=proposed_payload,
            catalog=catalog,
            within_book_links=None,
        )


class FrozenPlanTamperTests(unittest.TestCase):
    def _mixed_plan(self):
        cross = _cross_resolution("old", "ent_a", "ent_a1")
        catalog = _catalog([("canon-a", [("old", "ent_a")])])
        params = _plan_inputs(
            resolutions=[_within_resolution(), cross], catalog=catalog
        )
        plan = S.build_chapter_review_plan(**params)
        return plan, params, [_within_resolution(), cross]

    def _persisted(self, plan: dict) -> dict:
        """Simulate a persistence round-trip like the restore path sees."""
        return json.loads(json.dumps(plan))

    def _validate(self, plan, params, resolutions) -> str:
        return S.validate_chapter_review_plan(
            plan,
            resolutions,
            job_id=params["job_id"],
            revision_id=params["revision_id"],
            assembled_bundle_sha256=params["assembled_bundle_sha256"],
            base_catalog_sha256=params["base_catalog_sha256"],
        )

    def test_deleted_pair_payload_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        del tampered["pair_payloads"][0]
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_tampered_pair_candidate_id_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["pair_payloads"][0]["candidate_id"] = "ec_999"
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_tampered_pair_left_ref_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["pair_payloads"][0]["left"] = {"bundle": "bund", "ref": "ent_b1"}
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_tampered_pair_member_endpoint_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["pair_payloads"][0]["members"][0]["left"]["ref"] = "tampered"
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_tampered_pair_subject_id_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["pair_payloads"][0]["review_subject_id"] = "rp_tampered"
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_tampered_batch_group_member_endpoint_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["batch_payloads"][0]["groups"][0]["members"][0]["left"][
            "ref"
        ] = "tampered"
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_tampered_batch_subject_member_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["published_batch_subjects"][0]["members"][0]["left"][
            "ref"
        ] = "tampered"
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_tampered_batch_signals_fail_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["batch_payloads"][0]["signals"] = ["forged evidence"]
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_deleted_batch_payload_fails_restore(self) -> None:
        plan, params, resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        del tampered["batch_payloads"][0]
        with self.assertRaises(PersistenceConflict):
            self._validate(tampered, params, resolutions)

    def test_open_rejects_plan_missing_its_pair(self) -> None:
        plan, _params, _resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        del tampered["pair_payloads"][0]
        conn = unittest.mock.MagicMock()
        with self.assertRaises(PersistenceConflict):
            S.open_chapter_review_plan(
                conn, job_id=uuid.UUID(plan["job_id"]), plan=tampered
            )

    def test_open_rejects_tampered_pair_fingerprint(self) -> None:
        plan, _params, _resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["pair_payloads"][0]["plan_fingerprint"] = "0" * 64
        conn = unittest.mock.MagicMock()
        with self.assertRaises(PersistenceConflict):
            S.open_chapter_review_plan(
                conn, job_id=uuid.UUID(plan["job_id"]), plan=tampered
            )

    def test_open_rejects_tampered_pair_member_endpoint(self) -> None:
        plan, _params, _resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["pair_payloads"][0]["members"][0]["left"]["ref"] = "tampered"
        conn = unittest.mock.MagicMock()
        with self.assertRaises(PersistenceConflict):
            S.open_chapter_review_plan(
                conn, job_id=uuid.UUID(plan["job_id"]), plan=tampered
            )

    def test_open_rejects_tampered_batch_group_member(self) -> None:
        plan, _params, _resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["batch_payloads"][0]["groups"][0]["members"][0]["left"][
            "ref"
        ] = "tampered"
        conn = unittest.mock.MagicMock()
        with self.assertRaises(PersistenceConflict):
            S.open_chapter_review_plan(
                conn, job_id=uuid.UUID(plan["job_id"]), plan=tampered
            )

    def test_open_rejects_tampered_pair_subject_id(self) -> None:
        plan, _params, _resolutions = self._mixed_plan()
        tampered = self._persisted(plan)
        tampered["pair_payloads"][0]["review_subject_id"] = "rp_tampered"
        conn = unittest.mock.MagicMock()
        with self.assertRaises(PersistenceConflict):
            S.open_chapter_review_plan(
                conn, job_id=uuid.UUID(plan["job_id"]), plan=tampered
            )


if __name__ == "__main__":
    unittest.main()
