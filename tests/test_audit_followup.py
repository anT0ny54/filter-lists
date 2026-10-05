"""Regression tests for the post-v7.5.4 audit follow-up fixes."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
from normalize import normalize_rule, rejection_reason  # noqa: E402


class OverbroadPatternTests(unittest.TestCase):
    def test_pattern_without_literal_content_is_rejected(self):
        for rule in ("*", "**", "|", "||", "^", "|^", "||^", "||*", "@@*", "@@||", "@@^"):
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule))
                self.assertEqual(rejection_reason(rule), "overbroad-pattern")

    def test_scoped_and_literal_patterns_are_kept(self):
        for rule in ("*$domain=a.com,script", "@@*$domain=a.com", "||a.example^", "|http://a.example|", "a"):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)


class LazyPolicyTests(unittest.TestCase):
    def test_bad_policy_reports_clean_configuration_error_instead_of_import_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "policies.yaml").write_text("bogus: 1\n", encoding="utf-8")
            (root / "sources.yaml").write_text("sources: []\n", encoding="utf-8")
            code = (
                "import sys; sys.path.insert(0, %r)\n"
                "import config\n"
                "from pathlib import Path\n"
                "config.POLICY_FILE = Path(%r); config.SOURCE_REGISTRY = Path(%r)\n"
                "import normalize  # must not raise at import time\n"
                "print('imported')\n"
            ) % (str(ROOT / "scripts"), str(root / "policies.yaml"), str(root / "sources.yaml"))
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("imported", proc.stdout)

    def test_invalid_rule_switch_fails_in_load_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sources.yaml").write_text("sources: []\n", encoding="utf-8")
            (root / "policies.yaml").write_text("rules:\n  allow_network_filterz: true\n", encoding="utf-8")
            with patch.object(config, "SOURCE_REGISTRY", root / "sources.yaml"), \
                 patch.object(config, "POLICY_FILE", root / "policies.yaml"):
                with self.assertRaisesRegex(ValueError, "unknown rule policies"):
                    config.load_config()


class DifferentialPlaceholderTests(unittest.TestCase):
    def test_command_without_input_placeholder_is_an_error(self):
        env = {**os.environ, "FILTER_ENGINE_CMD": "true"}
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "differential.py")],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("{input}", proc.stdout)


if __name__ == "__main__":
    unittest.main()
