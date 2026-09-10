import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule


class RealWorldCorpusTests(unittest.TestCase):
    def test_curated_corpus_contains_only_supported_rules(self):
        root = Path(__file__).resolve().parents[1] / "tests" / "corpus"
        accepted = rejected = 0
        for path in sorted(root.glob("*.txt")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("!"):
                    continue
                normalized = normalize_rule(line)
                if normalized is None:
                    rejected += 1
                else:
                    accepted += 1
        self.assertGreaterEqual(accepted, 8)
        self.assertEqual(rejected, 0)

    def test_corpus_normalization_is_idempotent(self):
        root = Path(__file__).resolve().parents[1] / "tests" / "corpus"
        for path in sorted(root.glob("*.txt")):
            for line in path.read_text(encoding="utf-8").splitlines():
                normalized = normalize_rule(line)
                if normalized is not None:
                    self.assertEqual(normalize_rule(normalized), normalized)

if __name__ == "__main__":
    unittest.main(verbosity=2)
