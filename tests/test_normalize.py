import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule, rejection_reason

class NormalizeTests(unittest.TestCase):
    def test_empty_option_delimiter_is_rejected(self):
        self.assertIsNone(normalize_rule("||example.com^$"))
    def test_long_rule_is_rejected(self):
        self.assertIsNone(normalize_rule("||example.com^" + ("x" * 100001)))
    def test_rejection_reason_is_specific(self):
        self.assertEqual(rejection_reason("0.0.0.0 ads.example.com"), "hosts-format")
    def test_cosmetic_domains_are_sorted_and_deduplicated(self):
        self.assertEqual(normalize_rule("B.com,a.com,B.com##.ad"), "a.com,B.com##.ad")

if __name__ == "__main__":
    unittest.main(verbosity=2)
