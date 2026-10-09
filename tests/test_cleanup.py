"""Tests for schema-version validation, single-pass rejection reasons, and worker config."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _helpers import load_script  # noqa: E402  (also puts scripts/ on sys.path)

import config
from normalize import normalize_rule, normalize_rule_with_reason, rejection_reason

merge = load_script("merge.py", "merge_cleanup")


class SourcesVersionTests(unittest.TestCase):
    def _load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sources.yaml"
            pol = Path(tmp) / "policies.yaml"
            src.write_text(text, encoding="utf-8")
            pol.write_text("limits: {}\n", encoding="utf-8")
            with patch.object(config, "SOURCE_REGISTRY", src), patch.object(config, "POLICY_FILE", pol):
                return config.load_config()

    def test_future_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sources.yaml: unsupported version 999"):
            self._load("version: 999\nsources:\n  - name: a\n    url: https://a.test/l.txt\n")

    def test_current_and_omitted_version_load(self):
        body = "sources:\n  - name: a\n    url: https://a.test/l.txt\n"
        self.assertTrue(self._load(f"version: {config.SOURCE_SCHEMA_VERSION}\n{body}").sources)
        self.assertTrue(self._load(body).sources)


class RejectionPathTests(unittest.TestCase):
    LINES = [
        "||ok.example^", "! comment", "", "0.0.0.0 host.example", "||a.example^$bogus",
        "||a.example^$script,script", "||a.example^$~script", "##",
        "||" + "x" * 100001,
    ]

    def test_with_reason_matches_separate_calls(self):
        for line in self.LINES:
            with self.subTest(line=line[:40]):
                rule, reason = normalize_rule_with_reason(line)
                self.assertEqual(rule, normalize_rule(line))
                if rule is None:
                    self.assertEqual(reason, rejection_reason(line))
                else:
                    self.assertIsNone(reason)

    def test_unknown_inverse_option_still_rejected(self):
        self.assertEqual(rejection_reason("||a.example^$~notanoption"), "unknown-option")


class WorkersTests(unittest.TestCase):
    def test_default_and_override(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FILTER_LISTS_WORKERS", None)
            self.assertEqual(merge._workers(), merge.DEFAULT_WORKERS)
        with patch.dict(os.environ, {"FILTER_LISTS_WORKERS": "6"}):
            self.assertEqual(merge._workers(), 6)

    def test_invalid_values_rejected(self):
        for bad in ("0", "-1", "many"):
            with self.subTest(bad=bad), patch.dict(os.environ, {"FILTER_LISTS_WORKERS": bad}):
                with self.assertRaises(ValueError):
                    merge._workers()


if __name__ == "__main__":
    unittest.main()
