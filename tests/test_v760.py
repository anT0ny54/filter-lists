"""Tests for v7.6.0: source-quality gates and failed-run source outcomes."""
import json
import tempfile
import unittest
from pathlib import Path

from _helpers import load_script  # noqa: F401  (adds scripts/ to sys.path)
import config
from health import build_source_reputation, load_outcomes, record_outcomes
from report import evaluate_source_quality, write_report

URL = "https://example.test/a"


def result(url="https://example.test/list", lines=1000, accepted=100, **reasons):
    return {"url": url, "status": "ok", "input_lines": lines, "accepted_lines": accepted,
            "rejection_reasons": reasons}


class SourceQualityTests(unittest.TestCase):
    def test_annoyances_like_feed_is_critical(self):
        out = evaluate_source_quality([result(lines=2743, accepted=1, comment=13, **{"unknown-option": 2712})], None)
        self.assertEqual(out["critical_count"], 1)
        self.assertFalse(out["enforced_failure"])  # advisory by default

    def test_comments_do_not_count_as_rejections(self):
        out = evaluate_source_quality([result(lines=1000, accepted=500, comment=500)], None)
        self.assertEqual(out["count"], 0)

    def test_warning_band_and_min_lines(self):
        self.assertEqual(evaluate_source_quality([result(accepted=650)], None)["warning_count"], 1)
        self.assertEqual(evaluate_source_quality([result(lines=50, accepted=0)], None)["count"], 0)

    def test_fail_on_critical_enforces(self):
        out = evaluate_source_quality([result(accepted=10)], {"fail_on_critical": True})
        self.assertTrue(out["enforced_failure"])

    def test_disabled(self):
        self.assertEqual(evaluate_source_quality([result(accepted=0)], {"enabled": False})["count"], 0)

    def test_policy_validation(self):
        base = config._load_policy
        try:
            config._load_policy = lambda: {"source_quality": {"warn_rejection_rate": 0.9, "critical_rejection_rate": 0.5}}
            with self.assertRaises(ValueError):
                config.load_config()
            config._load_policy = lambda: {"source_quality": {"warn_rate": 0.1}}
            with self.assertRaises(ValueError):
                config.load_config()
        finally:
            config._load_policy = base

    def test_shipped_policy_loads_quality_section(self):
        self.assertTrue(config.load_config().source_quality["enabled"])


class OutcomeHistoryTests(unittest.TestCase):
    def _record(self, root, when, ok, status="success"):
        record_outcomes(root / "source-outcomes.json", history_dir=root / "history", generated_at=when,
                        status=status, build_id="b", results=[{"url": URL, "status": "ok" if ok else "failed"}])

    def test_failed_runs_persist_and_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for day in ("01", "02", "03"):
                self._record(root, f"2026-10-{day}T00:00:00+00:00", False, "failed")
            rep = build_source_reputation(root / "history", [{"url": URL, "status": "ok"}],
                                          generated_at="2026-10-04T00:00:00+00:00")[URL]
            self.assertEqual((rep["observations"], rep["failures"], rep["consecutive_failures"]), (4, 3, 0))

    def test_same_day_reruns_are_one_observation_and_failure_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._record(root, "2026-10-01T01:00:00+00:00", True)
            self._record(root, "2026-10-01T02:00:00+00:00", True)
            self._record(root, "2026-10-02T01:00:00+00:00", False, "failed")
            self._record(root, "2026-10-02T02:00:00+00:00", True)
            rep = build_source_reputation(root / "history", [], generated_at="2026-10-03T00:00:00+00:00")[URL]
            self.assertEqual((rep["observations"], rep["failures"]), (2, 1))

    def test_bootstrap_from_successful_history_when_no_outcomes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "history").mkdir()
            (root / "history" / "x.json").write_text(json.dumps({
                "status": "success", "generated_at": "2026-10-01T00:00:00+00:00",
                "sources": {"results": [{"url": URL, "status": "ok"}]}}))
            self.assertEqual(len(load_outcomes(root / "source-outcomes.json", root / "history")), 1)
            self._record(root, "2026-10-02T00:00:00+00:00", False, "failed")
            self.assertEqual(len(load_outcomes(root / "source-outcomes.json", root / "history")), 2)

    def test_failed_report_records_outcomes_but_not_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_report(root / "latest.json", source_stats={"root_requested": 1, "root_successful": 0, "results": [
                {"url": URL, "status": "failed", "depth": 0, "path": None, "bytes": 0, "reason": "timeout"}]},
                rule_stats={"unique_rules": 0}, elapsed_seconds=0.1, source_urls=[URL], build_id="a" * 64,
                status="failed")
            runs = json.loads((root / "source-outcomes.json").read_text())["runs"]
            self.assertEqual(runs[0]["outcomes"], {URL: False})
            self.assertEqual(runs[0]["status"], "failed")
            self.assertFalse((root / "history").exists())


if __name__ == "__main__":
    unittest.main()
