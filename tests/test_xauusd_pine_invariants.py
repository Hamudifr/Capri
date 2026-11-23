import re
import unittest
from pathlib import Path


class PineScoreCapacityTests(unittest.TestCase):
    def test_minimum_score_cannot_exceed_available_score_components(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "research" / "xauusd" / "Gold_Intelligence_v1.pine").read_text(encoding="utf-8")

        max_match = re.search(r'minScore\s*=\s*input\.int\([^)]*maxval\s*=\s*(\d+)', source)
        self.assertIsNotNone(max_match, "minScore must declare an explicit maxval")
        max_score = int(max_match.group(1))

        bull = re.search(r"int\s+bullScore\s*=\s*(.+)", source)
        bear = re.search(r"int\s+bearScore\s*=\s*(.+)", source)
        self.assertIsNotNone(bull)
        self.assertIsNotNone(bear)

        bull_terms = re.findall(r"\((\w+)\s*\?\s*1\s*:\s*0\)", bull.group(1))
        bear_terms = re.findall(r"\((\w+)\s*\?\s*1\s*:\s*0\)", bear.group(1))
        self.assertEqual(len(bull_terms), len(bear_terms), "bullish and bearish scoring capacity must match")
        self.assertLessEqual(max_score, len(bull_terms), "minScore maxval exceeds achievable score")

    def test_default_minimum_score_is_reachable_with_default_filter_settings(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "research" / "xauusd" / "Gold_Intelligence_v1.pine").read_text(encoding="utf-8")

        default_match = re.search(r'minScore\s*=\s*input\.int\((\d+)', source)
        self.assertIsNotNone(default_match, "minScore must declare an explicit default")
        default_score = int(default_match.group(1))

        bull = re.search(r"int\s+bullScore\s*=\s*(.+)", source)
        self.assertIsNotNone(bull)
        terms = re.findall(r"\((\w+)\s*\?\s*1\s*:\s*0\)", bull.group(1))

        optional_filters = {"usdTailwind": "useUsd", "yieldTailwind": "useYield"}
        enabled = {}
        for input_name in optional_filters.values():
            match = re.search(rf"{input_name}\s*=\s*input\.bool\((true|false)", source)
            self.assertIsNotNone(match, f"{input_name} must declare a default")
            enabled[input_name] = match.group(1) == "true"

        default_capacity = sum(
            1 for term in terms
            if term not in optional_filters or enabled[optional_filters[term]]
        )
        self.assertLessEqual(
            default_score,
            default_capacity,
            "default minScore cannot be reached with default optional filters",
        )


    def test_rule_based_indicator_does_not_brand_itself_as_ai(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "research" / "xauusd" / "Gold_Intelligence_v1.pine").read_text(encoding="utf-8")

        shorttitle = re.search(r'shorttitle\s*=\s*"([^"]+)"', source)
        self.assertIsNotNone(shorttitle, "indicator must declare a short title")
        self.assertNotIn(
            "AI",
            shorttitle.group(1).upper(),
            "a rule-based score with no trained model must not be branded as AI",
        )


if __name__ == "__main__":
    unittest.main()
