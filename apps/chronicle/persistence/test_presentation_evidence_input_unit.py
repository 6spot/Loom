"""Reader input must not turn extracted relationships into quoted evidence."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import presentation as P  # noqa: E402


class PresentationEvidenceInputTests(unittest.TestCase):
    def test_unsupported_actor_location_and_title_hints_never_reach_generator(self):
        for kind, quote in (
            ("entity", "留凌统以拒仁"),
            ("entity", "于是大疫，吏士多死者"),
            ("event", "以诸葛亮为丞相"),
        ):
            with self.subTest(kind=kind, quote=quote):
                evidence = {"source_ref": "src_001", "text": quote}
                context = {
                    "schema": "chronicle.reader-presentation-context",
                    "version": "0.1",
                    "target_kind": kind,
                    "canonical_id": "01a05cd7-439d-7000-933c-d13d77a9dc37",
                    "language": "zh-CN",
                    "input_fingerprint": "a" * 64,
                    "representations": [{
                        "bundle": "source", "ref": "ent_001",
                        "record": {"canonical_name": "UNSUPPORTED_TARGET_HINT"},
                        "source": {"ref": "src_001", "title": "史书"},
                        "claims": [{
                            "bundle": "source", "ref": "clm_001",
                            "claim": {
                                "subject": {"kind": "entity_ref", "ref": "UNSUPPORTED_ACTOR"},
                                "predicate": "UNSUPPORTED_RELATION",
                                "object": {"kind": "literal", "value": "UNSUPPORTED_RESULT"},
                                "evidence": evidence,
                                "assessment": {"status": "unassessed"},
                            },
                        }],
                    }],
                    "constraints": {
                        "allowed_claim_refs": ["source:clm_001"],
                        "requires_uncertainty": True,
                        "uncertain_resolution_detected": True,
                    },
                    "resolution_links": [{"relation": "uncertain"}],
                }
                original = copy.deepcopy(context)
                prompt = P.build_prompt(context)
                supplied = json.loads(prompt.split("INPUT:\n", 1)[1])
                self.assertNotIn("UNSUPPORTED_", prompt)
                claim = supplied["representations"][0]["claims"][0]
                self.assertEqual(("source", "clm_001"), (claim["bundle"], claim["ref"]))
                self.assertEqual(evidence, claim["claim"]["evidence"])
                self.assertEqual(context["constraints"], supplied["constraints"])
                self.assertEqual(context["resolution_links"], supplied["resolution_links"])
                self.assertEqual(context["input_fingerprint"], supplied["input_fingerprint"])
                self.assertEqual(original, context)


if __name__ == "__main__":
    unittest.main()
