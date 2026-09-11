"""Check retained real evidence locations, not the truth of historical claims."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class CorroborationCaseTests(unittest.TestCase):
    def test_complete_sources_and_exact_quotes_remain_relocatable(self):
        cases = json.loads((ROOT / 'apps/chronicle/corpus/reading-enhancement/cases.json').read_text())['cases']
        self.assertGreaterEqual(len(cases), 12)
        self.assertEqual(len(cases), len({case['case_id'] for case in cases}))
        self.assertGreaterEqual(sum(case['kind'] == 'real' for case in cases), 8)
        for case in cases:
            with self.subTest(case=case['case_id']):
                self.assertIn(case['kind'], ('real', 'synthetic'))
                self.assertTrue(case['allowed'] and case['forbidden'] and case['reason'])
                for reference in case['sources']:
                    source = (ROOT / reference['path']).read_bytes()
                    self.assertEqual(reference['sha256'], hashlib.sha256(source).hexdigest())
                    self.assertEqual(reference['quote'], source.decode()[reference['start']:reference['end']])
                    self.assertTrue(reference['attribution'])


if __name__ == '__main__':
    unittest.main()
