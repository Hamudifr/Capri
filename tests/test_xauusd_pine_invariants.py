import re
import unittest
from pathlib import Path


class PineScoreCapacityTests(unittest.TestCase):
    def test_minimum_score_cannot_exceed_available_score_components(self):
        root = Path(__file__).resolve().parents[1]
        source = (
            root / "research" / "xauusd" / "Gold_Intelligence_v1.pine"
        ).read_text(encoding="utf-8")

        max_match = re.search(
            r'minScore\s*=\s*input\.int\([^)]*maxval\s*=\s*(\d+)',
            source,
        )
        self.assertIsNotNone(max_match, "minScore must declare an explicit maxval")
        max_score = int(max_match.group(1))

        bull = re.search(r"int\s+bullScore\s*=\s*(.+)", source)
        bear = re.search(r"int\s+bearScore\s*=\s*(.+)", source)
        self.assertIsNotNone(bull)
        self.assertIsNotNone(bear)

        bull_terms = len(re.findall(r"\?\s*1\s*:\s*0", bull.group(1)))
        bear_terms = len(re.findall(r"\?\s*1\s*:\s*0", bear.group(1)))
        self.assertEqual(
            bull_terms,
            bear_terms,
            "bullish and bearish scoring capacity must match",
        )
        self.assertLessEqual(
            max_score,
            bull_terms,
            "minScore maxval exceeds achievable score",
        )


if __name__ == "__main__":
    unittest.main()
