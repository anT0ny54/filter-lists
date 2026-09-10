import random
import string
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule
from report import detect_anomalies


class PropertyAndFuzzTests(unittest.TestCase):
    def test_normalizer_never_raises_on_deterministic_unicode_fuzz(self):
        rng = random.Random(0xF17E)
        alphabet = string.printable + "é中🙂\u0000\u0007\u001f\ufeff"
        for _ in range(1000):
            value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 501)))
            result = normalize_rule(value)
            self.assertTrue(result is None or isinstance(result, str))

    def test_normalization_is_idempotent(self):
        rules = [
            "||example.com^",
            "@@||example.com^$document",
            "||example.com^$script,third-party",
            "example.com##.ad",
            r"/foo\$bar/",
        ]
        for rule in rules:
            normalized = normalize_rule(rule)
            self.assertIsNotNone(normalized)
            self.assertEqual(normalize_rule(normalized), normalized)

    def test_normalizer_is_deterministic_for_fuzzed_input(self):
        rng = random.Random(0xC0DE)
        alphabet = string.ascii_letters + string.digits + "|$^/\\#@,.:_-"
        for _ in range(1000):
            value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 251)))
            self.assertEqual(normalize_rule(value), normalize_rule(value))

    def test_anomaly_detector_flags_large_source_change(self):
        previous = {"build_id": "old", "sources": {"results": [{
            "url": "https://example.test/list", "status": "ok", "bytes": 1000,
            "input_lines": 1000, "unique_rules": 900, "rejection_rate": 0.1, "sha256": "a" * 64,
        }]}}
        current = [{
            "url": "https://example.test/list", "status": "ok", "bytes": 100,
            "input_lines": 100, "unique_rules": 80, "rejection_rate": 0.6, "sha256": "b" * 64,
        }]
        result = detect_anomalies(current, previous, {
            "enabled": True, "max_bytes_change_ratio": 0.75,
            "max_rule_count_change_ratio": 0.75, "max_rejection_rate_change": 0.25,
            "min_lines": 100,
        })
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["warning_count"], 1)
        self.assertIn("bytes-change", result["items"][0]["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
