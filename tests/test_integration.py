import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from report import analyze_files, write_report


class PipelineIntegrationTests(unittest.TestCase):
    def test_fixture_pipeline_is_deterministic(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "tests" / "fixtures" / "sample-filter.txt"
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            rules, stats = analyze_files([fixture], max_rule_length=100_000)
            self.assertEqual(rules, {
                "||example.com^$script,third-party",
                "@@||example.com^$document",
                "example.com##.ad",
                "example.com#?#div:-abp-has(.sponsor)",
            })
            self.assertEqual(stats["unique_rules"], 4)
            self.assertEqual(stats["rejection_reasons"]["hosts-format"], 1)
            self.assertEqual(stats["rejection_reasons"]["ubo-only-syntax"], 1)
            write_report(report, source_stats={"root_requested": 1, "root_successful": 1}, rule_stats=stats, elapsed_seconds=0.01, source_urls=["https://example.test/list"], build_id="a" * 64)
            data = json.loads(report.read_text())
            self.assertEqual(data["schema"], 5)
            self.assertEqual(data["rules"]["unique_rules"], 4)
            self.assertIn("source_reputation", data)
            self.assertEqual(data["status"], "success")


if __name__ == "__main__":
    unittest.main(verbosity=2)
