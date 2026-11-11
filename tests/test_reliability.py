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


    def test_malformed_previous_report_shapes_are_ignored(self):
        for sources in (None, [], {"results": None}, {"results": {"not": "a list"}}):
            with self.subTest(sources=sources):
                result = detect_anomalies(
                    [], {"status": "success", "build_id": "damaged", "sources": sources},
                    {"enabled": True},
                )
                self.assertEqual(result["count"], 0)
                self.assertEqual(result["baseline"], "damaged")

    def test_malformed_baseline_rows_are_skipped_without_hiding_valid_rows(self):
        url = "https://example.test/list"
        good_baseline = {
            "url": url, "status": "ok", "bytes": 1000, "input_lines": 1000,
            "unique_rules": 900, "rejection_rate": 0.1,
        }
        previous = {"status": "success", "build_id": "old", "sources": {"results": [
            None,
            7,
            {"url": "https://bad.example/list", "status": "ok", "bytes": "not-a-number"},
            good_baseline,
            {"url": url, "status": "ok", "bytes": "not-a-number"},
            {"url": url, "status": "ok", "bytes": True, "input_lines": 1000,
             "unique_rules": 900, "rejection_rate": 0.1},
        ]}}
        current = [{
            "url": url, "status": "ok", "bytes": 500, "input_lines": 1000,
            "unique_rules": 900, "rejection_rate": 0.1,
        }]
        result = detect_anomalies(current, previous, {
            "enabled": True, "min_lines": 100, "max_bytes_change_ratio": 0.25,
            "max_rule_count_change_ratio": 0.75, "max_rejection_rate_change": 0.25,
        })
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["url"], url)
        self.assertEqual(result["items"][0]["reasons"], ["bytes-change"])

    def test_enforced_failure_key_present_without_baseline_or_when_disabled(self):
        # update.yml asserts `enforced_failure is False`; it must exist even on
        # the first build (no baseline) and when detection is disabled.
        for policy in ({"enabled": True}, {"enabled": False}):
            for previous in (None, {"status": "failed"}):
                with self.subTest(policy=policy, previous=previous):
                    result = detect_anomalies([], previous, policy)
                    self.assertIs(result["enforced_failure"], False)
                    self.assertIs(result["fail_on_warning"], False)

    def test_report_source_results_are_stably_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latest.json"
            source_stats = {
                "root_requested": 2,
                "root_successful": 2,
                "results": [
                    {"url": "https://example.test/z", "status": "ok", "depth": 0, "path": "z", "bytes": 20},
                    {"url": "https://example.test/a", "status": "ok", "depth": 0, "path": "a", "bytes": 20},
                    {"url": "https://example.test/b-child", "status": "ok", "depth": 1, "path": "b", "bytes": 20},
                ],
            }
            write_report(
                path,
                source_stats=source_stats,
                rule_stats={"unique_rules": 3},
                elapsed_seconds=0.1,
                source_urls=["https://example.test/z", "https://example.test/a"],
                build_id="b" * 64,
                anomaly_policy={"enabled": False},
                history_dir=Path(tmp) / "history",
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            ordered = [(item["depth"], item["url"]) for item in data["sources"]["results"]]
            self.assertEqual(ordered, [
                (0, "https://example.test/a"),
                (0, "https://example.test/z"),
                (1, "https://example.test/b-child"),
            ])

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
