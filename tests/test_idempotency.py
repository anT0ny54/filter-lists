"""Normalization idempotency, consolidated from per-file duplicates.

Replaces identical checks that used to live in test_corpus.py,
test_properties.py, test_v70.py and test_v754.py. Every former input is
preserved: the curated corpus files plus each file's explicit rule list.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import normalize_rule  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

EXPLICIT_RULES = [
    # from test_properties.py
    "||example.com^",
    "@@||example.com^$document",
    "||example.com^$script,third-party",
    "example.com##.ad",
    r"/foo\$bar/",
    # from test_v70.py
    "||example.com^$THIRD-PARTY,IMAGE",
    "@@||example.com^$SCRIPT,domain=example.com",
    "B.com,a.com,B.com##.ad",
    # from test_v754.py
    "/ads/banner.gif",
    "/ads/*$image,domain=a.xn--p1ai",
    "b.xn--p1ai,a.com##.ad",
]


class NormalizeIdempotencyTests(unittest.TestCase):
    def test_normalize_is_idempotent(self):
        rules = list(EXPLICIT_RULES)
        for path in sorted(CORPUS_DIR.glob("*.txt")):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped:
                    rules.append(stripped)
        for rule in dict.fromkeys(rules):
            with self.subTest(rule=rule):
                normalized = normalize_rule(rule)
                if normalized is not None:
                    self.assertEqual(normalize_rule(normalized), normalized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
