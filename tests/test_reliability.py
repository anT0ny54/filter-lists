import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from health import build_source_reputation
from report import detect_anomalies, write_report


class ReliabilityTests(unittest.TestCase):
    def test_source_reputation_tracks_history_and_current_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp)
            old = {"status": "success", "sources": {"results": [{"url": "https://example.test/a", "status": "ok"}]}}
            (history / "001.json").write_text(json.dumps(old), encoding="utf-8")
            current = [{"url": "https://example.test/a", "status": "failed"}]
            result = build_source_reputation(history, current)
            item = result["https://example.test/a"]
            self.assertEqual(item["observations"], 2)
            self.assertEqual(item["success_rate"], 0.5)
            self.assertEqual(item["consecutive_failures"], 1)

    def test_warning_can_be_enforced(self):
        previous = {"status": "success", "build_id": "old", "sources": {"results": [{
            "url": "https://example.test/list", "status": "ok", "bytes": 1000, "input_lines": 1000,
            "unique_rules": 900, "rejection_rate": 0.1, "sha256": "a" * 64}]}}
        current = [{"url": "https://example.test/list", "status": "ok", "bytes": 500, "input_lines": 1000,
                   "unique_rules": 900, "rejection_rate": 0.1, "sha256": "b" * 64}]
        result = detect_anomalies(current, previous, {"enabled": True, "max_bytes_change_ratio": 0.25,
            "max_rule_count_change_ratio": 0.75, "max_rejection_rate_change": 0.25, "min_lines": 100,
            "fail_on_warning": True})
        self.assertEqual(result["warning_count"], 1)
        self.assertTrue(result["enforced_failure"])

    def test_failed_report_is_not_a_future_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latest.json"
            write_report(path, source_stats={"root_requested": 1, "root_successful": 0, "results": []},
                         rule_stats={"unique_rules": 0}, elapsed_seconds=0.1, source_urls=["https://example.test"],
                         build_id="a" * 64, status="failed")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "failed")
            self.assertEqual(data["anomalies"]["baseline"], "none")

if __name__ == "__main__":
    unittest.main(verbosity=2)
