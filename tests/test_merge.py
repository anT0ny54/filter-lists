import functools
import http.server
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urljoin

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge.py"
spec = importlib.util.spec_from_file_location("merge", SCRIPT)
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


class ABPStrictTests(unittest.TestCase):
    def test_network_exception_is_preserved(self):
        rule = "@@||Example.COM^$SCRIPT,domain=example.com|~ads.example.com"
        self.assertEqual(merge.normalize_rule(rule), "@@||Example.COM^$domain=example.com|~ads.example.com,script")

    def test_cosmetic_exception_is_preserved(self):
        self.assertEqual(merge.normalize_rule("Example.COM,foo.com#@#.ad-banner"), "Example.COM,foo.com#@#.ad-banner")

    def test_extended_css_is_preserved(self):
        rule = "example.com#?#div:-abp-has(.ad)"
        self.assertEqual(merge.normalize_rule(rule), rule)

    def test_ubo_extended_exception_is_rejected(self):
        self.assertIsNone(merge.normalize_rule("example.com#?@#.ad"))

    def test_ubo_snippet_is_rejected(self):
        self.assertIsNone(merge.normalize_rule("example.com##+js(set-constant, foo, true)"))

    def test_regex_with_dollar_is_preserved(self):
        for rule in (r"/foo\$bar/", r"/foo$/", r"/foo$/$match-case"):
            self.assertEqual(merge.normalize_rule(rule), rule)

    def test_options_are_case_normalized_and_sorted(self):
        self.assertEqual(merge.normalize_rule("||example.com^$THIRD-PARTY,IMAGE"), "||example.com^$image,third-party")

    def test_csp_option_is_preserved(self):
        rule = "||example.com^$csp=script-src: 'none'"
        self.assertEqual(merge.normalize_rule(rule), rule)

    def test_duplicate_options_rejected(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$script,script"))

    def test_unknown_ubo_option_rejected(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$removeparam=utm_source"))

    def test_document_only_exception(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$document"))
        self.assertEqual(merge.normalize_rule("@@||example.com^$document"), "@@||example.com^$document")

    def test_rewrite_requires_domain(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$rewrite=abp-resource:blank-js"))
        self.assertEqual(merge.normalize_rule("||example.com^$rewrite=abp-resource:blank-js,domain=example.com"), "||example.com^$domain=example.com,rewrite=abp-resource:blank-js")

    def test_comments_and_hosts_are_rejected(self):
        self.assertIsNone(merge.normalize_rule("! comment"))
        self.assertIsNone(merge.normalize_rule("0.0.0.0 ads.example.com"))

    def test_include_url_resolution(self):
        self.assertEqual(urljoin("https://example.com/lists/main.txt", "../child.txt"), "https://example.com/child.txt")


class MergeMainE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        merge.ROOT = root
        merge.CUSTOM_RULES = root / "custom-rules.txt"
        merge.OUTPUT = root / "filters.txt"
        merge.REPORT = root / "reports" / "latest.json"
        merge.HISTORY_DIR = root / "reports" / "history"
        merge.SOURCES_TXT = root / "sources.txt"
        (root / "reports").mkdir(parents=True)
        (root / "sources.yaml").write_text("""sources:
  - name: fixture
    url: https://fixture.test/list.txt
    category: test
    priority: 1
    required: true
""", encoding="utf-8")
        (root / "policies.yaml").write_text("""limits: {}
""", encoding="utf-8")
        merge.CUSTOM_RULES.write_text("||custom.example^\n", encoding="utf-8")
        self.config = SimpleNamespace(
            sources=(SimpleNamespace(name="fixture", url="https://fixture.test/list.txt", category="test", priority=1, required=True, enabled=True),),
            minimum_success_ratio=0.5,
            fail_if_zero_sources=True,
            max_rule_length=100000,
            max_include_depth=5,
            max_download_bytes=1024 * 1024,
            max_total_download_bytes=1024 * 1024,
            max_total_sources=10,
            total_timeout_seconds=10,
            anomaly_detection={"enabled": False, "fail_on_warning": False},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_main_real_local_http_fetch_and_analysis(self):
        with tempfile.TemporaryDirectory(prefix="filter-merge-http-") as server_dir:
            server_root = Path(server_dir)
            (server_root / "main.txt").write_text(
                "! fixture root\n!#include child.txt\n||root.example^\n",
                encoding="utf-8",
            )
            (server_root / "child.txt").write_text(
                "||child.example^$script\n",
                encoding="utf-8",
            )
            handler = functools.partial(
                http.server.SimpleHTTPRequestHandler, directory=str(server_root)
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                source_url = f"{base}/main.txt"
                config = SimpleNamespace(
                    sources=(SimpleNamespace(
                        name="local-fixture", url=source_url, category="test",
                        priority=1, required=True, enabled=True,
                    ),),
                    minimum_success_ratio=1.0,
                    fail_if_zero_sources=True,
                    max_rule_length=100000,
                    max_include_depth=5,
                    max_download_bytes=1024 * 1024,
                    max_total_download_bytes=1024 * 1024,
                    max_total_sources=10,
                    total_timeout_seconds=30,
                    anomaly_detection={"enabled": False, "fail_on_warning": False},
                )
                (merge.ROOT / "sources.yaml").write_text(
                    "sources:\n  - name: local-fixture\n    url: " + source_url + "\n    category: test\n    priority: 1\n    required: true\n",
                    encoding="utf-8",
                )
                with patch.object(merge, "load_config", return_value=config):
                    result = merge.main()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(result, 0)
        output = merge.OUTPUT.read_text(encoding="utf-8")
        self.assertIn("||root.example^", output)
        self.assertIn("||child.example^$script", output)
        report = json.loads(merge.REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["sources"]["root_successful"], 1)
        self.assertEqual(report["sources"]["included_successful"], 1)
        self.assertEqual(report["rules"]["unique_rules"], 3)
        self.assertEqual(report["sources"]["results"][0]["status"], "ok")
        self.assertEqual(len(report["sources"]["results"]), 2)

    def _run(self, *, source_stats=None, rules=None, rule_stats=None, anomaly=None):
        source_stats = source_stats or {
            "root_requested": 1, "root_successful": 1,
            "results": [{"url": self.config.sources[0].url, "status": "ok", "depth": 0, "path": "/fixture.txt", "bytes": 10}],
            "failures": [], "source_limit_reached": False, "timed_out": False,
        }
        rules = rules or {"||example.com^"}
        rule_stats = rule_stats or {"input_lines": 1, "accepted_lines": 1, "rejected_lines": 0, "duplicate_lines": 0, "unique_rules": 1, "rejection_reasons": {}, "per_file": []}
        with patch.object(merge, "load_config", return_value=self.config), \
             patch.object(merge, "collect_sources", return_value=([], source_stats)), \
             patch.object(merge, "analyze_files", return_value=(rules, rule_stats)), \
             patch.object(merge.shutil, "which", return_value="/usr/bin/curl"):
            if anomaly is not None:
                original = merge.write_report
                def write_with_anomaly(*args, **kwargs):
                    original(*args, **kwargs)
                    data = json.loads(merge.REPORT.read_text(encoding="utf-8"))
                    data["anomalies"] = anomaly
                    merge.REPORT.write_text(json.dumps(data), encoding="utf-8")
                writer = write_with_anomaly
            else:
                writer = merge.write_report
            with patch.object(merge, "write_report", side_effect=writer):
                return merge.main()

    def test_main_success_writes_output_report_and_history(self):
        self.assertEqual(self._run(), 0)
        self.assertTrue(merge.OUTPUT.is_file())
        self.assertIn("! Profile: Strict Adblock Plus-compatible syntax;", merge.OUTPUT.read_text(encoding="utf-8"))
        report = json.loads(merge.REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["profile"], "strict-abp")
        self.assertTrue((merge.HISTORY_DIR / f"build-{report['build_id']}.json").is_file())

    def test_main_source_health_failure_does_not_publish_output(self):
        failed = {"root_requested": 1, "root_successful": 0, "results": [{"url": self.config.sources[0].url, "status": "failed", "depth": 0, "path": "/fixture.txt", "reason": "HTTP 500"}], "failures": [{"url": self.config.sources[0].url, "depth": 0, "reason": "HTTP 500"}], "source_limit_reached": False, "timed_out": False}
        self.assertEqual(self._run(source_stats=failed), 1)
        self.assertFalse(merge.OUTPUT.exists())
        report = json.loads(merge.REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")

    def test_main_anomaly_enforced_failure_marks_report_failed_and_does_not_archive(self):
        anomaly = {"enabled": True, "baseline": "old-build", "count": 1, "critical_count": 1, "warning_count": 0, "items": [{"severity": "critical"}], "enforced_failure": True}
        self.assertEqual(self._run(anomaly=anomaly), 1)
        report = json.loads(merge.REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(list(merge.HISTORY_DIR.glob("*.json")), [])

    def test_main_required_source_failure_is_unhealthy_even_with_other_sources(self):
        config = self.config
        optional = SimpleNamespace(name="optional", url="https://optional.test/list.txt", category="test", priority=2, required=False, enabled=True)
        config = SimpleNamespace(**{**config.__dict__, "sources": (config.sources[0], optional)})
        stats = {"root_requested": 2, "root_successful": 1, "results": [
            {"url": config.sources[0].url, "status": "failed", "depth": 0, "path": "/required.txt", "reason": "timeout"},
            {"url": optional.url, "status": "ok", "depth": 0, "path": "/optional.txt", "bytes": 10},
        ], "failures": [{"url": config.sources[0].url, "depth": 0, "reason": "timeout"}], "source_limit_reached": False, "timed_out": False}
        with patch.object(merge, "load_config", return_value=config):
            with patch.object(merge, "collect_sources", return_value=([], stats)):
                with patch.object(merge.shutil, "which", return_value="/usr/bin/curl"):
                    self.assertEqual(merge.main(), 1)
        report = json.loads(merge.REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["sources"]["required_failed"], [config.sources[0].url])


if __name__ == "__main__":
    unittest.main(verbosity=2)
