"""R20 regression: a Reader model must receive the complete output contract."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import presentation as P  # noqa: E402
from common import PersistenceError  # noqa: E402


def context(target_kind: str = "entity", *, uncertainty: bool = False) -> dict:
    return {
        "schema": "chronicle.reader-presentation-context",
        "version": "0.1",
        "target_kind": target_kind,
        "canonical_id": "01a05cd7-439d-7000-933c-d13d77a9dc37",
        "language": "zh-CN",
        "representations": [{"claims": [{"bundle": "wudi", "ref": "clm_008"}]}],
        "constraints": {
            "allowed_claim_refs": ["wudi:clm_008"],
            "requires_uncertainty": uncertainty,
        },
    }


def candidate(target_kind: str = "entity") -> dict:
    return {
        "schema": "chronicle.reader-presentation",
        "version": "0.1",
        "target_kind": target_kind,
        "canonical_id": context(target_kind)["canonical_id"],
        "language": "zh-CN",
        "blocks": [{
            "block_kind": "source_notes",
            "epistemic_mode": "source_report",
            "text": "《武帝纪》记载刘表去世。",
            "claim_refs": [{"bundle": "wudi", "ref": "clm_008"}],
        }],
    }


class PresentationR20ContractTests(unittest.TestCase):
    def test_prompt_provides_exact_output_header_for_both_targets(self) -> None:
        for target_kind in ("entity", "event"):
            with self.subTest(target_kind=target_kind):
                supplied = context(target_kind)
                prompt = P.build_prompt(supplied)
                # The model must not have to infer the output header from the
                # differently named input-context schema (the R20 defect).
                self.assertIn("OUTPUT_HEADER:\n", prompt)
                header = json.loads(prompt.split("OUTPUT_HEADER:\n", 1)[1].split("\n", 1)[0])
                expected = candidate(target_kind)
                del expected["blocks"]
                self.assertEqual(expected, header)
                self.assertEqual(supplied, json.loads(prompt.split("INPUT:\n", 1)[1]))
                for required in ("blocks", "block_kind", "epistemic_mode", "text", "claim_refs", "bundle", "ref"):
                    self.assertIn(required, prompt.split("INPUT:\n", 1)[0])
                for value in (*P.BLOCK_KINDS, *P.EPISTEMIC_MODES):
                    self.assertIn(value, prompt.split("INPUT:\n", 1)[0])

    def test_missing_null_or_wrong_target_is_never_filled_in(self) -> None:
        for target_kind in ("entity", "event"):
            for field in ("target_kind", "canonical_id"):
                other_target = (
                    "event" if target_kind == "entity" else "entity"
                ) if field == "target_kind" else "00000000-0000-4000-8000-000000000001"
                for value in ("missing", None, "wrong-target", other_target):
                    with self.subTest(target=target_kind, field=field, value=value):
                        output = candidate(target_kind)
                        if value == "missing":
                            del output[field]
                        else:
                            output[field] = value
                        model = mock.Mock(name="reader")
                        model.name = "reader-test"
                        model.complete.return_value = json.dumps(output)
                        before = copy.deepcopy(output)
                        with self.assertRaisesRegex(PersistenceError, field):
                            P.generate_candidate(context(target_kind), model)
                        self.assertEqual(before, output)
                        self.assertEqual(1, model.complete.call_count)

    def test_malformed_blocks_and_supports_fail_closed(self) -> None:
        mutations = (
            ("block_kind", "why"),
            ("epistemic_mode", "certain"),
            ("text", " "),
            ("text", "长" * 601),
            ("claim_refs", []),
            ("claim_refs", ["wudi:clm_008"]),
            ("claim_refs", [{"bundle": "wudi", "ref": None}]),
            ("claim_refs", [{"bundle": "wudi", "ref": "clm_other_target"}]),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                output = candidate()
                output["blocks"][0][field] = value
                with self.assertRaises(PersistenceError):
                    P.validate_candidate(output, context())
        for blocks in (None, [], [None], [candidate()["blocks"][0]] * 13):
            with self.subTest(blocks=blocks):
                output = candidate()
                output["blocks"] = blocks
                with self.assertRaises(PersistenceError):
                    P.validate_candidate(output, context())

    def test_uncertainty_stays_required_and_claim_bound(self) -> None:
        supplied = context(uncertainty=True)
        output = candidate()
        with self.assertRaisesRegex(PersistenceError, "omitted an uncertainty block"):
            P.validate_candidate(output, supplied)
        output["blocks"][0]["block_kind"] = "uncertainty"
        with self.assertRaisesRegex(PersistenceError, "epistemic_mode=uncertainty"):
            P.validate_candidate(output, supplied)
        output["blocks"][0]["epistemic_mode"] = "uncertainty"
        output["blocks"][0]["text"] = "现有来源仍有分歧，无法据此确定。"
        normalized = P.validate_candidate(output, supplied)
        self.assertEqual(output["blocks"][0]["claim_refs"], normalized["blocks"][0]["claim_refs"])
        output["blocks"][0]["claim_refs"][0]["ref"] = "clm_other_target"
        with self.assertRaisesRegex(PersistenceError, "outside generation scope"):
            P.validate_candidate(output, supplied)


if __name__ == "__main__":
    unittest.main()
