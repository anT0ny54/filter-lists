import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule, rejection_reason, rule_sort_key

class V70RegressionTests(unittest.TestCase):
    def test_ubo_option_has_specific_reason(self):
        self.assertEqual(rejection_reason("||example.com^$removeparam=utm"), "unknown-option")
    def test_rejection_reasons_are_specific(self):
        self.assertEqual(rejection_reason("||example.com^$script,script"), "duplicate-option")
        self.assertEqual(rejection_reason("||example.com^$domain=bad_domain"), "invalid-option-value")

    def test_casefold_sorting_has_deterministic_tie_breaker(self):
        # Set iteration order is arbitrary; rule_sort_key must still give one order.
        values = ["B-rule", "a-rule", "A-rule"]
        self.assertEqual(sorted(values, key=rule_sort_key), ["A-rule", "a-rule", "B-rule"])
        self.assertEqual(sorted(reversed(values), key=rule_sort_key), ["A-rule", "a-rule", "B-rule"])

    def test_normalization_does_not_depend_on_input_spelling_of_equal_rules(self):
        # Equal rules written differently must collapse to one canonical string,
        # which is what makes deduplication and the Build-ID stable.
        spellings = ["||a.example^$THIRD-PARTY,SCRIPT", "||a.example^$script,third-party", "  ||a.example^$Script,Third-Party  "]
        self.assertEqual(len({normalize_rule(x) for x in spellings}), 1)

if __name__ == "__main__": unittest.main(verbosity=2)
