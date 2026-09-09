import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from parser import classify

class ParserTests(unittest.TestCase):
    def test_classifies_network(self):
        self.assertEqual(classify("||example.com^").kind, "network")
    def test_classifies_cosmetic(self):
        self.assertEqual(classify("example.com##.ad").kind, "cosmetic")
    def test_classifies_comment(self):
        self.assertEqual(classify("! comment").kind, "comment")
    def test_classifies_hosts_as_invalid(self):
        self.assertEqual(classify("0.0.0.0 ads.example.com").reason, "hosts-format")

if __name__ == "__main__":
    unittest.main(verbosity=2)
