import unittest

from resolution_model import build_resolution_prompt


class OfflineResolutionPromptTests(unittest.TestCase):
    def test_prompt_is_closed_world_and_non_destructive(self) -> None:
        candidates = {
            "schema": "chronicle.resolution-candidates",
            "version": "0.1",
            "left_bundle": {"label": "a", "source_ref": "src_001", "source_title": "A"},
            "right_bundle": {"label": "b", "source_ref": "src_001", "source_title": "B"},
            "entity_candidates": [],
            "event_candidates": [],
        }
        prompt = build_resolution_prompt(candidates)
        self.assertIn("Use only the supplied candidate records and signals", prompt)
        self.assertIn("must remain immutable", prompt)
        self.assertIn("Do not invent canonical UUIDs", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("human gold", prompt.lower())


if __name__ == "__main__":
    unittest.main()
