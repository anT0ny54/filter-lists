"""Regression tests for the maintenance audit (BUILDER_VERSION stays 7.6.0).

Each class pins one defect that was reproduced against the previous code.
"""
import hashlib
import json
import random
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from _helpers import load_script, run_validate, setup_config_root  # noqa: E402  (also puts scripts/ on sys.path)

import config
import fetch
from config import BUILDER_VERSION, config_fingerprint, load_config, source_manifest_sha256
from normalize import normalize_rule, normalize_rule_with_reason, rejection_reason, rule_sort_key
from parser import classify, clean_line
from health import history_reports
from report import write_report

validate = load_script("validate.py", "validate_hardening")
URL = "https://example.test/a"


class RemoveActionSwitchTests(unittest.TestCase):
    """`allow_abp_remove_action: false` must hold wherever `remove` appears."""

    OFF = {**config.RULE_POLICY_DEFAULTS, "allow_abp_remove_action": False}
    REMOVE_RULES = (
        "example.com##.a {remove: true}",
        "example.com##.a {margin: 0; remove: true}",
        "example.com##.a {margin: 0; REMOVE : true}",
        "example.com##.a {remove\t: true}",
    )

    def test_remove_is_rejected_in_any_position_when_switch_is_off(self):
        for rule in self.REMOVE_RULES:
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule, rule_policy=self.OFF))

    def test_remove_is_accepted_when_switch_is_on(self):
        for rule in self.REMOVE_RULES:
            with self.subTest(rule=rule):
                self.assertIsNotNone(normalize_rule(rule))

    def test_other_inline_styles_unaffected_by_switch(self):
        rule = "example.com##.a {margin: 0}"
        self.assertEqual(normalize_rule(rule, rule_policy=self.OFF), rule)


class BomHandlingTests(unittest.TestCase):
    CASES = ("  \ufeffads.js$script", "\ufeff ads.js", "\ufeff\ufeffads.js", "\ufeff  \ufeffads.js", "\t\ufeff\tads.js")

    def test_clean_line_strips_bom_and_whitespace_in_any_order(self):
        for raw in self.CASES:
            with self.subTest(raw=raw):
                self.assertFalse(clean_line(raw).startswith(("\ufeff", " ", "\t")))
                self.assertEqual(clean_line(clean_line(raw)), clean_line(raw))
        self.assertEqual(clean_line("\ufeff"), "")

    def test_accepted_rules_never_keep_a_leading_bom(self):
        for raw in self.CASES:
            with self.subTest(raw=raw):
                rule = normalize_rule(raw)
                self.assertIsNotNone(rule)
                self.assertFalse(rule.startswith("\ufeff"))
                self.assertEqual(normalize_rule(rule), rule)

    def test_classifier_and_normalizer_agree(self):
        self.assertEqual(classify("  \ufeff! comment").kind, "comment")
        self.assertEqual(rejection_reason("  \ufeff! comment"), "comment")

    def test_bom_fuzz_is_idempotent(self):
        rng = random.Random(0xB0B)
        tokens = ["||", "a.com", ",", "##", ".ad", "$", "script", "domain=", "~", " ", "\t", "\ufeff", "^", "x"]
        for _ in range(20000):
            raw = "".join(rng.choice(tokens) for _ in range(rng.randrange(1, 9)))
            rule = normalize_rule(raw)
            if rule is not None:
                self.assertEqual(normalize_rule(rule), rule, repr(raw))


class UntrustedCommentTests(unittest.TestCase):
    def test_comments_mentioning_restricted_features_stay_comments(self):
        for line in ("! see $header= in the docs", "! snippets use #$# syntax", "  ! $addheader= note"):
            with self.subTest(line=line):
                self.assertEqual(normalize_rule_with_reason(line, trusted_abp_features=False), (None, "comment"))
                self.assertEqual(rejection_reason(line, trusted_abp_features=False), "comment")

    def test_directive_mentioning_restricted_feature_stays_directive(self):
        self.assertEqual(rejection_reason("!#if x $header=y", trusted_abp_features=False), "directive")

    def test_real_restricted_rules_are_still_rejected(self):
        for line in ("||a.com^$script,header=x", "a.com#$#abort-on-property-read x"):
            with self.subTest(line=line):
                self.assertEqual(rejection_reason(line, trusted_abp_features=False), "abp-security-restricted-feature")


class PolicyKeyTypeTests(unittest.TestCase):
    def test_non_string_rule_key_is_a_clean_configuration_error(self):
        setup_config_root(self, config, sources_yaml="sources: []\n", policies_yaml="rules:\n  1: true\n  a: true\n")
        with self.assertRaisesRegex(ValueError, "unknown rule policies: 1, a"):
            config.load_config()


class DownloadBomTests(unittest.TestCase):
    def _check(self, data: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.txt"
            path.write_bytes(data)
            return fetch.validate_download(path, 1 << 20, reject_html_error_pages=True)

    def test_bom_prefixed_html_error_page_is_rejected(self):
        page = b"\xef\xbb\xbf<!DOCTYPE html><html><body>error page here</body></html>\n"
        self.assertEqual(self._check(page), (False, "html-or-error-page"))
        self.assertEqual(self._check(b"\xef\xbb\xbf  \n<html><body>x</body></html>\n"), (False, "html-or-error-page"))

    def test_bom_prefixed_real_list_is_accepted(self):
        self.assertEqual(self._check(b"\xef\xbb\xbf||a.example^\n||b.example^\n"), (True, ""))

    def test_include_on_first_line_after_bom_is_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.txt"
            path.write_bytes(b"\xef\xbb\xbf!#include child.txt\n||a.example^\n")
            self.assertEqual(fetch.include_urls(path, "https://e.test/x/main.txt"), ["https://e.test/x/child.txt"])


class ReputationScopeTests(unittest.TestCase):
    def test_report_lists_reputation_only_for_current_sources(self):
        gone = "https://example.test/disabled"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outcomes = root / "source-outcomes.json"
            outcomes.write_text(json.dumps({"schema": 1, "runs": [{
                "generated_at": "2026-10-01T00:00:00+00:00", "status": "success", "build_id": "b",
                "outcomes": {URL: True, gone: True}}]}), encoding="utf-8")
            write_report(root / "latest.json", source_stats={"root_requested": 1, "root_successful": 1, "results": [
                {"url": URL, "status": "ok", "depth": 0, "path": "p", "bytes": 20}]},
                rule_stats={"unique_rules": 1}, elapsed_seconds=0.1, source_urls=[URL], build_id="a" * 64,
                history_dir=root / "history", outcomes_path=outcomes)
            data = json.loads((root / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data["source_reputation"]), {URL})
        self.assertEqual(data["source_reputation"][URL]["observations"], 2)


class NonObjectReportJsonTests(unittest.TestCase):
    def test_history_reports_skips_json_that_is_not_an_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp)
            (history / "list.json").write_text("[1, 2]", encoding="utf-8")
            (history / "scalar.json").write_text("3", encoding="utf-8")
            (history / "ok.json").write_text(json.dumps({"status": "success", "generated_at": "2026-10-01"}), encoding="utf-8")
            self.assertEqual([r["generated_at"] for r in history_reports(history)], ["2026-10-01"])

    def test_load_previous_report_ignores_non_object_latest_json(self):
        merge = load_script("merge.py", "merge_hardening")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            merge.REPORT = root / "latest.json"
            merge.HISTORY_DIR = root / "history"
            merge.BASELINE_FILE = root / "baseline.json"
            merge.REPORT.write_text("[1, 2]", encoding="utf-8")
            self.assertIsNone(merge.load_previous_report())


class ValidateVersionHeaderTests(unittest.TestCase):
    def _run(self, extra_version_lines):
        cfg = load_config()
        rule = "||dup-version.example^"
        build_id = hashlib.sha256((config_fingerprint(cfg) + "\n" + normalize_rule(rule)).encode()).hexdigest()
        version = f"! Version: v{BUILDER_VERSION}-{build_id[:12]}"
        lines = [version, *extra_version_lines, f"! Build-ID: {build_id}",
                 f"! Source manifest SHA-256: {source_manifest_sha256(cfg)}", "! Total rules: 1", "!", rule]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "filters.txt"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return run_validate(validate, path)

    def test_single_version_header_passes(self):
        self.assertEqual(self._run([])[0], 0)

    def test_duplicate_version_header_is_rejected(self):
        code, out = self._run([f"! Version: v{BUILDER_VERSION}-{'0' * 12}"])
        self.assertEqual(code, 1)
        self.assertIn("duplicate '! Version:' header", out)


class FingerprintTests(unittest.TestCase):
    def test_trusted_flag_changes_the_build_fingerprint(self):
        def fingerprint(flag):
            setup_config_root(self, config, sources_yaml=
                f"sources:\n  - {{name: A, url: 'https://a.example/a.txt', trusted_abp_features: {flag}}}\n")
            return config_fingerprint(config.load_config())
        self.assertNotEqual(fingerprint("true"), fingerprint("false"))


class SortKeyTests(unittest.TestCase):
    def test_sort_key_is_case_insensitive_with_raw_tie_break(self):
        self.assertEqual(rule_sort_key("||A.example^"), ("||a.example^", "||A.example^"))
        self.assertLess(rule_sort_key("||A.example^"), rule_sort_key("||a.example^"))
        self.assertLess(rule_sort_key("||a.example^"), rule_sort_key("||B.example^"))


if __name__ == "__main__":
    unittest.main()


class SubmitFailureReservationTests(unittest.TestCase):
    """A pool.submit() failure must release its download-budget reservation.

    Regression: the reservation was taken before submit and never released,
    so with a fully reserved budget every later request was refused as
    "global-download-budget-exhausted" and the wave accounting stalled.
    """

    def test_submit_failure_releases_reservation_and_records_failure(self):
        import concurrent.futures
        calls = {"n": 0}
        real_pool = concurrent.futures.ThreadPoolExecutor

        class FlakyPool:
            def __init__(self, max_workers=None):
                # Capture the real class before the patch: the patch replaces
                # the attribute on the module, so a lookup here would recurse.
                self._real = real_pool(max_workers=max_workers)

            def submit(self, fn, *args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("pool closed")
                return self._real.submit(fn, *args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._real.__exit__(*exc)
                return False

            def shutdown(self, *args, **kwargs):
                self._real.shutdown(*args, **kwargs)

        def fake_download(url, output, timeout, max_download_bytes):
            output.write_text("||a.example^\n! enough padding for validation\n", encoding="utf-8")
            return True, "", output.stat().st_size

        urls = ["https://a.example/one.txt", "https://b.example/two.txt"]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(concurrent.futures, "ThreadPoolExecutor", FlakyPool), \
                mock.patch.object(fetch, "download", fake_download):
            files, stats = fetch.collect_sources(
                urls, Path(tmp), time.monotonic(), 2, lambda msg: None,
                total_timeout=30, max_include_depth=0,
                max_download_bytes=1 << 20, max_total_download_bytes=1 << 20,
                max_total_sources=10,
            )

        # The leaked reservation (1 MiB of a 1 MiB budget) would have refused
        # the second request with "global-download-budget-exhausted".
        self.assertFalse(stats["budget_exhausted"])
        self.assertEqual(stats["requested"], 2)
        self.assertEqual(stats["successful"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(len(files), 1)
        failure = [r for r in stats["results"] if r["status"] == "failed"]
        self.assertEqual(len(failure), 1)
        self.assertTrue(failure[0]["reason"].startswith("submit-failed"), failure[0]["reason"])
        success = [r for r in stats["results"] if r["status"] == "ok"]
        self.assertEqual([r["url"] for r in success], ["https://b.example/two.txt"])


class DnsPinCacheTests(unittest.TestCase):
    """Validated getaddrinfo pins are cached per (host, port) for the build."""

    def setUp(self):
        fetch._ADDRESS_PIN_CACHE.clear()
        self.addCleanup(fetch._ADDRESS_PIN_CACHE.clear)

    def _fake_infos(self):
        import socket as _socket
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def test_second_lookup_for_same_host_uses_cache(self):
        with mock.patch.object(fetch.socket, "getaddrinfo", side_effect=lambda *a, **k: self._fake_infos()) as resolver:
            first = fetch._public_address_for_url("https://pin-cache-a.example/list.txt")
            second = fetch._public_address_for_url("https://pin-cache-a.example/other.txt")
        self.assertEqual(first, ("93.184.216.34", ""))
        self.assertEqual(second, first)
        self.assertEqual(resolver.call_count, 1)

    def test_different_port_is_a_separate_cache_entry(self):
        with mock.patch.object(fetch.socket, "getaddrinfo", side_effect=lambda *a, **k: self._fake_infos()) as resolver:
            fetch._public_address_for_url("https://pin-cache-b.example/list.txt")
            fetch._public_address_for_url("http://pin-cache-b.example/list.txt")
        self.assertEqual(resolver.call_count, 2)

    def test_resolution_failure_is_cached_as_sticky_within_the_build(self):
        with mock.patch.object(fetch.socket, "getaddrinfo", side_effect=OSError("no dns")) as resolver:
            first = fetch._public_address_for_url("https://pin-cache-c.example/list.txt")
            second = fetch._public_address_for_url("https://pin-cache-c.example/other.txt")
        self.assertEqual(first[0], None)
        self.assertTrue(first[1].startswith("dns-resolution-failed"))
        self.assertEqual(second, first)
        self.assertEqual(resolver.call_count, 1)
