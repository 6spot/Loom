"""Pure contract tests for the immutable cross-batch history edition."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import history_edition_contract as contract


class HistoryEditionContractTests(unittest.TestCase):
    def test_three_fragments_exceed_single_fragment_capacity_without_merging_facts(self) -> None:
        fixture = contract.contract_fixture()
        edition = fixture["edition"]

        self.assertEqual(3, edition["fragment_count"])
        self.assertEqual(288, edition["paragraph_count"])
        self.assertTrue(all(ref["paragraph_count"] <= contract.MAX_FRAGMENT_PARAGRAPHS for ref in edition["fragments"]))
        self.assertEqual(288, len({paragraph["paragraph_id"] for paragraph in edition["paragraphs"]}))
        # Every source fragment intentionally uses p0/phase0/c0.  The owner
        # version is part of every derived ID and source locator.
        first_paragraphs = [
            paragraph for paragraph in edition["paragraphs"] if paragraph["source"]["paragraph_id"] == "p0"
        ]
        self.assertEqual(3, len(first_paragraphs))
        self.assertEqual(3, len({paragraph["paragraph_id"] for paragraph in first_paragraphs}))
        self.assertEqual(3, len({phase["phase_id"] for phase in edition["phases"] if phase["source"]["phase_id"] == "phase0"}))
        self.assertEqual(3, len({conclusion["conclusion_id"] for conclusion in edition["conclusions"] if conclusion["source"]["conclusion_id"] == "c0"}))

    def test_unknown_dates_are_preserved_and_navigation_stays_curated(self) -> None:
        fixture = contract.contract_fixture()
        edition = fixture["edition"]

        self.assertEqual(3, len(edition["navigation"]))
        self.assertLess(len(edition["navigation"]), edition["paragraph_count"])
        self.assertTrue(all(phase.get("year") is None for phase in edition["phases"]))
        self.assertTrue(all(phase.get("period") is None for phase in edition["phases"]))
        self.assertEqual(
            ["fixture-fragment-001", "fixture-fragment-002", "fixture-fragment-003"],
            [entry["fragment_version"] for entry in edition["navigation"]],
        )

    def test_same_input_and_order_have_same_manifest_and_content_hash(self) -> None:
        first = contract.contract_fixture()
        second = contract.contract_fixture()

        self.assertEqual(first["edition"], second["edition"])
        self.assertEqual(first["edition"]["version"], first["edition"]["manifest_sha256"])
        contract.validate_history_edition(first["edition"], first["fragments"])

    def test_supplied_fragments_must_match_manifest_source_mappings(self) -> None:
        fixture = contract.contract_fixture(paragraphs_per_fragment=2, fragment_count=1)
        edition = copy.deepcopy(fixture["edition"])
        paragraph = edition["paragraphs"][1]
        fragment_version = paragraph["source"]["fragment_version"]
        fake_local_id = "nonexistent-local-paragraph"
        fake_global_id = contract.derive_global_paragraph_id(fragment_version, fake_local_id)
        paragraph["paragraph_id"] = fake_global_id
        paragraph["id"] = fake_global_id
        paragraph["source"] = {
            "fragment_version": fragment_version,
            "paragraph_id": fake_local_id,
        }
        paragraph["source_paragraph_id"] = fake_local_id
        paragraph["content_ref"] = copy.deepcopy(paragraph["source"])
        edition["content_sha256"] = contract.sha256_json({
            "fragments": [item["content_sha256"] for item in edition["fragments"]],
            "paragraphs": edition["paragraphs"],
            "phases": edition["phases"],
            "conclusions": edition["conclusions"],
            "navigation": edition["navigation"],
        })
        edition["manifest_sha256"] = contract._manifest_hash(edition)
        edition["version"] = edition["manifest_sha256"]

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.validate_history_edition(edition, fixture["fragments"])
        self.assertEqual("source_mapping_mismatch", error.exception.code)

    def test_unsupported_fragment_schema_and_version_are_rejected(self) -> None:
        fixture = contract.contract_fixture(fragment_count=1)

        wrong_schema = copy.deepcopy(fixture["fragments"])
        wrong_schema[0]["schema"] = "chronicle.other-publication"
        with self.assertRaises(contract.HistoryEditionError) as schema_error:
            contract.compile_history_edition(wrong_schema)
        self.assertEqual("unsupported_fragment_schema", schema_error.exception.code)

        wrong_version = copy.deepcopy(fixture["fragments"])
        wrong_version[0]["version"] = "0.2"
        with self.assertRaises(contract.HistoryEditionError) as version_error:
            contract.compile_history_edition(wrong_version)
        self.assertEqual("unsupported_fragment_version", version_error.exception.code)

    def test_unpublished_fragment_is_rejected(self) -> None:
        fixture = contract.contract_fixture(fragment_count=1)
        fragment = copy.deepcopy(fixture["fragments"][0])
        fragment["publication_status"] = "draft"

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.compile_history_edition([fragment])
        self.assertEqual("fragment_not_published", error.exception.code)

    def test_missing_reference_is_rejected(self) -> None:
        fixture = contract.contract_fixture(fragment_count=1)
        fragments = copy.deepcopy(fixture["fragments"])
        fragments[0]["paragraphs"][0]["segments"][0]["conclusion_ids"] = ["missing-conclusion"]

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.compile_history_edition(fragments)
        self.assertEqual("missing_reference", error.exception.code)

    def test_duplicate_fragment_is_rejected(self) -> None:
        fixture = contract.contract_fixture(fragment_count=1)

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.compile_history_edition([fixture["fragments"][0], fixture["fragments"][0]])
        self.assertEqual("duplicate_fragment", error.exception.code)

    def test_out_of_bounds_navigation_anchor_is_rejected(self) -> None:
        fixture = contract.contract_fixture(fragment_count=1)
        navigation = copy.deepcopy(fixture["navigation"])
        navigation[0]["paragraph_id"] = "not-in-fragment"

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.compile_history_edition(
                fixture["fragments"],
                navigation=navigation,
            )
        self.assertEqual("anchor_out_of_bounds", error.exception.code)

    def test_local_order_change_is_rejected(self) -> None:
        fixture = contract.contract_fixture(fragment_count=1)
        fragments = copy.deepcopy(fixture["fragments"])
        fragments[0]["paragraphs"][0], fragments[0]["paragraphs"][1] = (
            fragments[0]["paragraphs"][1],
            fragments[0]["paragraphs"][0],
        )

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.compile_history_edition(fragments)
        self.assertEqual("local_order_changed", error.exception.code)

    def test_overlap_and_inversion_remain_pending_boundaries(self) -> None:
        fixture = contract.contract_fixture()
        fragments = copy.deepcopy(fixture["fragments"])

        fragments[1]["coverage"]["start"] = 95
        overlap_reviews = copy.deepcopy(fixture["boundary_reviews"])
        overlap_reviews[0]["geometry"] = "overlap"
        overlap_reviews[0]["status"] = "pending"
        with self.assertRaises(contract.HistoryEditionError) as overlap_error:
            contract.compile_history_edition(fragments, boundary_reviews=overlap_reviews, navigation=fixture["navigation"])
        self.assertEqual("boundary_review_required", overlap_error.exception.code)

        fragments = copy.deepcopy(fixture["fragments"])
        fragments[0]["coverage"]["start"] = 10
        fragments[1]["coverage"]["start"] = 0
        inversion_reviews = copy.deepcopy(fixture["boundary_reviews"])
        inversion_reviews[0]["geometry"] = "inversion"
        inversion_reviews[0]["status"] = "pending"
        with self.assertRaises(contract.HistoryEditionError) as inversion_error:
            contract.compile_history_edition(fragments, boundary_reviews=inversion_reviews, navigation=fixture["navigation"])
        self.assertEqual("boundary_review_required", inversion_error.exception.code)

    def test_incoherent_contiguous_seam_is_not_auto_accepted(self) -> None:
        fixture = contract.contract_fixture()
        reviews = copy.deepcopy(fixture["boundary_reviews"])
        reviews[0]["coherent"] = False

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.compile_history_edition(fixture["fragments"], boundary_reviews=reviews, navigation=fixture["navigation"])
        self.assertEqual("boundary_review_required", error.exception.code)

    def test_cross_fragment_state_and_evidence_are_rejected(self) -> None:
        fixture = contract.contract_fixture(fragment_count=1)
        fragments = copy.deepcopy(fixture["fragments"])
        fragments[0]["paragraphs"][0]["entities"] = [{
            "entity_id": "entity-1",
            "importance": "primary",
            "states": [{"id": "c0", "fragment_version": "other-fragment"}],
        }]
        with self.assertRaises(contract.HistoryEditionError) as state_error:
            contract.compile_history_edition(fragments)
        self.assertEqual("cross_fragment_reference", state_error.exception.code)

        fragments = copy.deepcopy(fixture["fragments"])
        fragments[0]["evidence"][0]["publication_id"] = "other-publication"
        with self.assertRaises(contract.HistoryEditionError) as evidence_error:
            contract.compile_history_edition(fragments)
        self.assertEqual("cross_fragment_reference", evidence_error.exception.code)

    def test_append_requires_current_baseline_and_preserves_old_references(self) -> None:
        fixture = contract.contract_fixture(paragraphs_per_fragment=2)
        previous = contract.compile_history_edition(
            fixture["fragments"][:2],
            boundary_reviews=fixture["boundary_reviews"][:1],
            navigation=fixture["navigation"][:2],
        )
        appended = contract.append_history_edition(
            previous,
            fixture["fragments"],
            baseline_manifest_sha256=previous["manifest_sha256"],
            boundary_reviews=fixture["boundary_reviews"],
            navigation=fixture["navigation"],
        )

        self.assertNotEqual(previous["version"], appended["version"])
        self.assertEqual(previous["fragments"], appended["fragments"][:2])
        self.assertEqual("append", appended["lineage"]["operation"])
        self.assertEqual(6, appended["paragraph_count"])

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.append_history_edition(
                previous,
                fixture["fragments"],
                baseline_manifest_sha256="0" * 64,
                boundary_reviews=fixture["boundary_reviews"],
                navigation=fixture["navigation"],
            )
        self.assertEqual("baseline_changed", error.exception.code)

    def test_replace_requires_explicit_fragment_range_not_years(self) -> None:
        fixture = contract.contract_fixture(paragraphs_per_fragment=2)
        previous = fixture["edition"]
        replacement = copy.deepcopy(fixture["fragments"][1])
        replacement["publication_version"] = "fixture-replacement-002"
        replacement["publication_id"] = "fixture-replacement-publication-002"
        for evidence in replacement["evidence"]:
            evidence["publication_id"] = replacement["publication_id"]
        replacement_navigation = copy.deepcopy(fixture["navigation"])
        replacement_navigation[1]["fragment_version"] = replacement["publication_version"]
        fragments = [fixture["fragments"][0], replacement, fixture["fragments"][2]]
        reviews = copy.deepcopy(fixture["boundary_reviews"])
        reviews[0]["right_fragment_version"] = replacement["publication_version"]
        reviews[0]["review_basis"][1]["fragment_version"] = replacement["publication_version"]
        reviews[1]["left_fragment_version"] = replacement["publication_version"]
        reviews[1]["review_basis"][0]["fragment_version"] = replacement["publication_version"]
        reviews[1]["review_basis"][0]["paragraph_id"] = "p1"

        replaced = contract.replace_history_edition(
            previous,
            fragments,
            replacement_range={
                "start_fragment_version": "fixture-fragment-002",
                "end_fragment_version": "fixture-fragment-002",
            },
            baseline_manifest_sha256=previous["manifest_sha256"],
            boundary_reviews=reviews,
            navigation=replacement_navigation,
        )
        self.assertNotEqual(previous["version"], replaced["version"])
        self.assertEqual(previous["fragments"][0], replaced["fragments"][0])
        self.assertEqual(previous["fragments"][2], replaced["fragments"][2])
        self.assertEqual("replace", replaced["lineage"]["operation"])

        with self.assertRaises(contract.HistoryEditionError) as error:
            contract.replace_history_edition(
                previous,
                fragments,
                replacement_range={"start_year": 200, "end_year": 201},
                baseline_manifest_sha256=previous["manifest_sha256"],
                boundary_reviews=reviews,
                navigation=replacement_navigation,
            )
        self.assertEqual("replacement_range_invalid", error.exception.code)


if __name__ == "__main__":
    unittest.main()
