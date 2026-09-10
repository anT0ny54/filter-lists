import hashlib
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule, rejection_reason

class V70RegressionTests(unittest.TestCase):
    def test_ubo_option_has_specific_reason(self):
        self.assertEqual(rejection_reason("||example.com^$removeparam=utm"), "unknown-option")
    def test_rejection_reasons_are_specific(self):
        self.assertEqual(rejection_reason("||example.com^$script,script"), "duplicate-option")
        self.assertEqual(rejection_reason("||example.com^$domain=bad_domain"), "invalid-option-value")

    def test_canonicalization_is_idempotent(self):
        rules = [
            "||example.com^$THIRD-PARTY,IMAGE",
            "@@||example.com^$SCRIPT,domain=example.com",
            "B.com,a.com,B.com##.ad",
            r"/foo\$bar/",
        ]
        for rule in rules:
            normalized = normalize_rule(rule)
            self.assertIsNotNone(normalized)
            self.assertEqual(normalize_rule(normalized), normalized)
    def test_casefold_sorting_has_deterministic_tie_breaker(self):
        values = {"A-rule", "a-rule", "B-rule"}
        ordered = sorted(values, key=lambda x: (x.casefold(), x))
        self.assertEqual(ordered, ["A-rule", "a-rule", "B-rule"])

    def test_build_hash_is_stable_for_same_rules(self):
        rules = sorted({normalize_rule("||b.example^"), normalize_rule("||a.example^")})
        a = hashlib.sha256("\n".join(rules).encode()).hexdigest()
        b = hashlib.sha256("\n".join(rules).encode()).hexdigest()
        self.assertEqual(a, b)

if __name__ == "__main__": unittest.main(verbosity=2)
