import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS))

import config
import fetch
from config import canonical_url
from fetch import collect_sources, validate_download
from normalize import normalize_rule


class DeterministicFetchTests(unittest.TestCase):
    def test_result_order_is_deterministic_under_out_of_order_completion(self):
        def run(a_delay, z_delay, urls):
            with tempfile.TemporaryDirectory() as tmp:
                def fake_download(url, output, timeout, max_download_bytes):
                    if url.endswith("/a"):
                        time.sleep(a_delay)
                        content = "||a.example^\n! enough padding for validation\n"
                    else:
                        time.sleep(z_delay)
                        content = "||z.example^\n! enough padding for validation\n"
                    output.write_text(content, encoding="utf-8")
                    return True, ""

                with patch.object(fetch, "download", side_effect=fake_download):
                    files, stats = collect_sources(
                        urls,
                        Path(tmp),
                        time.monotonic(),
                        2,
                        lambda _: None,
                        total_timeout=30,
                        max_include_depth=0,
                        max_download_bytes=1024 * 1024,
                        max_total_download_bytes=1024 * 1024,
                        max_total_sources=10,
                    )

            return [p.name for p in files], [item["url"] for item in stats["results"]], stats

        urls = ["https://example.com/a", "https://example.com/z"]
        first_files, first_results, first_stats = run(0.03, 0.0, urls)
        second_files, second_results, second_stats = run(0.0, 0.03, list(reversed(urls)))

        self.assertEqual(first_results, urls)
        self.assertEqual(second_results, list(reversed(urls)))
        self.assertEqual(first_files, ["source-000000.txt", "source-000001.txt"])
        self.assertEqual(second_files, ["source-000000.txt", "source-000001.txt"])
        self.assertEqual(
            first_stats["successful"] + first_stats["failed"],
            first_stats["requested"],
        )
        self.assertEqual(
            first_stats["root_successful"] + first_stats["root_failed"],
            first_stats["root_requested"],
        )
        comparable = lambda items: [
            {key: value for key, value in item.items() if key != "path"}
            for item in items
        ]
        self.assertEqual(
            comparable(second_stats["results"]),
            list(reversed(comparable(first_stats["results"]))),
        )

    def test_validate_download_scans_entire_file_for_nul_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.txt"
            path.write_bytes(
                b"||example.com^\n"
                + b"x" * (256 * 1024)
                + b"\x00"
                + b"y" * 1024
            )
            with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
                ok, reason = validate_download(path, 1024 * 1024)
        self.assertFalse(ok)
        self.assertEqual(reason, "binary-data")


class ConfigRegressionTests(unittest.TestCase):
    def test_canonical_url_removes_default_ports(self):
        self.assertEqual(
            canonical_url("HTTPS://EXAMPLE.com:443/a#fragment"),
            "https://example.com/a",
        )
        self.assertEqual(
            canonical_url("http://example.com:80/a"),
            "http://example.com/a",
        )
        self.assertEqual(
            canonical_url("https://example.com:8443/a"),
            "https://example.com:8443/a",
        )

    def test_duplicate_source_names_are_rejected_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_file = root / "sources.yaml"
            policy_file = root / "policies.yaml"
            source_file.write_text("""sources:
  - name: Example List
    url: https://example.com/one.txt
  - name: example list
    url: https://example.org/two.txt
""", encoding="utf-8")
            policy_file.write_text("""limits: {}
source_health: {}
history: {}
anomaly_detection:
  enabled: false
""", encoding="utf-8")
            with patch.object(config, "SOURCE_REGISTRY", source_file), \
                 patch.object(config, "POLICY_FILE", policy_file):
                with self.assertRaisesRegex(ValueError, "duplicate source name"):
                    config.load_config()

    def test_zero_enabled_sources_can_be_allowed_by_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_file = root / "sources.yaml"
            policy_file = root / "policies.yaml"
            source_file.write_text("sources: []\n", encoding="utf-8")
            policy_file.write_text("""source_health:
  fail_if_zero_sources: false
""", encoding="utf-8")
            with patch.object(config, "SOURCE_REGISTRY", source_file), \
                 patch.object(config, "POLICY_FILE", policy_file):
                loaded = config.load_config()
            self.assertEqual(loaded.sources, ())
            self.assertFalse(loaded.fail_if_zero_sources)


class RulePolicyRegressionTests(unittest.TestCase):
    def normalize_with_rules(self, rules_yaml: str, rule: str):
        with tempfile.TemporaryDirectory() as tmp:
            policy_file = Path(tmp) / "policies.yaml"
            policy_file.write_text(rules_yaml, encoding="utf-8")
            with patch.object(config, "POLICY_FILE", policy_file):
                config.load_rule_policy.cache_clear()
                try:
                    return normalize_rule(rule)
                finally:
                    config.load_rule_policy.cache_clear()

    def test_yaml_can_disable_network_filters(self):
        self.assertIsNone(
            self.normalize_with_rules(
                "rules:\n  allow_network_filters: false\n",
                "||example.com^",
            )
        )
        self.assertEqual(
            self.normalize_with_rules(
                "rules:\n  allow_network_filters: true\n",
                "||example.com^",
            ),
            "||example.com^",
        )

    def test_yaml_can_disable_cosmetic_and_extended_css_filters(self):
        self.assertIsNone(
            self.normalize_with_rules(
                "rules:\n  allow_abp_cosmetic: false\n",
                "example.com##.ad",
            )
        )
        self.assertIsNone(
            self.normalize_with_rules(
                "rules:\n  allow_extended_css: false\n",
                "example.com#?#div:-abp-has(.ad)",
            )
        )

    def test_yaml_can_allow_ubo_only_cosmetic_forms(self):
        self.assertEqual(
            self.normalize_with_rules(
                "rules:\n  reject_ubo_procedural: false\n",
                "example.com##+js(set-constant, foo, true)",
            ),
            "example.com##+js(set-constant, foo, true)",
        )
        self.assertEqual(
            self.normalize_with_rules(
                "rules:\n  reject_ubo_extended_exceptions: false\n",
                "example.com#?@#.ad",
            ),
            "example.com#?@#.ad",
        )

    def test_yaml_can_control_option_and_rewrite_restrictions(self):
        self.assertEqual(
            self.normalize_with_rules(
                "rules:\n  reject_unknown_options: false\n",
                "||example.com^$foo=bar",
            ),
            "||example.com^$foo=bar",
        )
        self.assertEqual(
            self.normalize_with_rules(
                "rules:\n  reject_duplicate_options: false\n",
                "||example.com^$script,script",
            ),
            "||example.com^$script,script",
        )
        self.assertEqual(
            self.normalize_with_rules(
                "rules:\n  require_domain_for_rewrite: false\n",
                "||example.com^$rewrite=abp-resource:blank-js",
            ),
            "||example.com^$rewrite=abp-resource:blank-js",
        )


SCRIPT = SCRIPTS / "merge.py"
spec = importlib.util.spec_from_file_location("merge_for_regressions", SCRIPT)
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


class MergeRegressionTests(unittest.TestCase):
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
        (root / "sources.yaml").write_text("sources: []\n", encoding="utf-8")
        (root / "policies.yaml").write_text("limits: {}\n", encoding="utf-8")
        merge.CUSTOM_RULES.write_text("||custom.example^\n", encoding="utf-8")
        self.base_config = SimpleNamespace(
            sources=(),
            minimum_success_ratio=0.8,
            fail_if_zero_sources=True,
            max_rule_length=100000,
            max_include_depth=5,
            max_download_bytes=1024 * 1024,
            max_total_download_bytes=1024 * 1024,
            max_total_sources=10,
            total_timeout_seconds=10,
            anomaly_detection={"enabled": False, "fail_on_warning": False},
            history_retention=10,
        )
        self.empty_source_stats = {
            "root_requested": 0,
            "root_successful": 0,
            "root_failed": 0,
            "included_requested": 0,
            "included_references": 0,
            "results": [],
            "failures": [],
            "source_limit_reached": False,
            "timed_out": False,
            "budget_exhausted": False,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, config):
        rules = {"||custom.example^"}
        rule_stats = {
            "input_lines": 1,
            "accepted_lines": 1,
            "rejected_lines": 0,
            "duplicate_lines": 0,
            "unique_rules": 1,
            "rejection_reasons": {},
            "per_file": [],
        }
        with patch.object(merge, "load_config", return_value=config), \
             patch.object(merge, "collect_sources", return_value=([], dict(self.empty_source_stats))), \
             patch.object(merge, "analyze_files", return_value=(rules, rule_stats)):
            return merge.main()

    def test_zero_sources_fails_when_policy_requires_sources(self):
        self.assertEqual(self.run_main(self.base_config), 1)
        self.assertFalse(merge.OUTPUT.exists())

    def test_zero_sources_allows_custom_rules_when_policy_permits(self):
        config_obj = SimpleNamespace(**{
            **self.base_config.__dict__,
            "fail_if_zero_sources": False,
        })
        self.assertEqual(self.run_main(config_obj), 0)
        self.assertIn("||custom.example^", merge.OUTPUT.read_text(encoding="utf-8"))

    def test_repeated_build_id_archives_reports_with_different_timestamps(self):
        report = {"status": "success", "generated_at": "2026-01-01T00:00:00+00:00"}
        merge.REPORT.write_text(json.dumps(report), encoding="utf-8")
        merge.archive_successful_report("same-build", retention=10)

        report["generated_at"] = "2026-01-01T01:00:00+00:00"
        merge.REPORT.write_text(json.dumps(report), encoding="utf-8")
        merge.archive_successful_report("same-build", retention=10)

        archived = sorted(merge.HISTORY_DIR.glob("build-same-build-*.json"))
        self.assertEqual(len(archived), 2)
        self.assertEqual(len({path.name for path in archived}), 2)


if __name__ == "__main__":
    unittest.main()
