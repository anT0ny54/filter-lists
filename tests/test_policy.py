import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule

class PolicyTests(unittest.TestCase):
    def test_ubo_procedural_rejected(self):
        self.assertIsNone(normalize_rule("example.com##+js(set-constant, foo, true)"))
    def test_unknown_option_rejected(self):
        self.assertIsNone(normalize_rule("||example.com^$removeparam=x"))
    def test_rewrite_needs_domain(self):
        self.assertIsNone(normalize_rule("||example.com^$rewrite=abp-resource:blank-js"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
