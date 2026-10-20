import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule, rejection_reason
from parser import classify
from report import detect_anomalies

import config  # noqa: E402
from _helpers import load_script, setup_config_root  # noqa: E402


class ProceduralCosmeticTests(unittest.TestCase):
    def test_ubo_procedural_operators_are_rejected(self):
        for rule in (
            "example.com##.ad:style(display:none!important)",
            "example.com##.ad:remove()",
            "example.com##.ad:upward(2)",
            "example.com##:matches-path(/x/) .ad",
            "example.com##.ad:matches-css(color: red)",
            "example.com#?#div:xpath(//a)",
        ):
            with self.subTest(rule=rule):
                if "xpath(" in rule:
                    self.assertEqual(normalize_rule(rule), rule)
                else:
                    self.assertIsNone(normalize_rule(rule))
                    self.assertEqual(rejection_reason(rule), "ubo-only-syntax")

    def test_standard_selectors_still_accepted(self):
        for rule in ("example.com##.ad:not(.x)", "example.com##div:has(> .ad)",
                     "example.com#?#div:-abp-has(a)", "example.com#?#div:-abp-contains(Ad)"):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)


class EngineSpecificSeparatorTests(unittest.TestCase):
    def test_adguard_separators_are_not_network_rules(self):
        for rule in ('example.com#%#//scriptlet("x")', 'example.com#@%#//scriptlet("x")',
                     "example.com#@$#body{a:b}", "example.com#$?#body{a:b}"):
            with self.subTest(rule=rule):
                self.assertEqual(classify(rule).kind, "cosmetic")
                self.assertIsNone(normalize_rule(rule))
                self.assertEqual(rejection_reason(rule), "engine-specific-syntax")

    def test_hash_comment_is_rejected(self):
        self.assertIsNone(normalize_rule("#domain.example-note(x)"))
        self.assertEqual(rejection_reason("#domain.example-note(x)"), "hash-comment")

    def test_bom_then_space_is_stripped(self):
        self.assertEqual(normalize_rule("\ufeff ||example.com^"), "||example.com^")


class AnomalyBaselineTests(unittest.TestCase):
    def test_previous_failed_source_is_not_a_baseline(self):
        url = "https://example.test/list.txt"
        previous = {"status": "success", "build_id": "x", "sources": {"results": [
            {"url": url, "status": "failed", "bytes": 0, "input_lines": 0, "unique_rules": 0}]}}
        current = [{"url": url, "status": "ok", "bytes": 10_000, "input_lines": 500,
                    "unique_rules": 400, "rejection_rate": 0.1}]
        result = detect_anomalies(current, previous, {"enabled": True})
        self.assertEqual(result["count"], 0)


class StagedOutputTests(unittest.TestCase):
    def test_stage_does_not_touch_output_until_commit(self):
        merge = load_script("merge.py", "merge_v753")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "filters.txt"
            out.write_text("previous\n", encoding="utf-8")
            merge.OUTPUT = out
            staged = merge.stage_output(["||a.example^"], "0" * 64, manifest_sha256="1" * 64, source_count=1)
            self.assertEqual(out.read_text(encoding="utf-8"), "previous\n")
            merge.commit_output(staged)
            self.assertIn("||a.example^", out.read_text(encoding="utf-8"))
            self.assertFalse(staged.exists())


class PolicyFileValidationTests(unittest.TestCase):
    def _load(self, yaml_text):
        setup_config_root(self, config, policies_yaml=yaml_text)
        return config._load_policy()

    def test_unknown_top_level_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown top-level keys: compatibility"):
            self._load("compatibility: [ABP]\n")

    def test_wrong_profile_or_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported profile"):
            self._load("profile: lenient\n")
        with self.assertRaisesRegex(ValueError, "unsupported version"):
            self._load("version: 99\n")

    def test_matching_profile_and_version_are_accepted(self):
        self.assertEqual(self._load("version: 3\nprofile: strict-abp\n")["profile"], "strict-abp")

    def test_boolean_and_float_schema_versions_are_rejected(self):
        for version in ("true", "3.0"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "version must be an integer"):
                self._load(f"version: {version}\nprofile: strict-abp\n")

    def test_default_success_ratio_matches_shipped_policy(self):
        import yaml
        import config
        shipped = yaml.safe_load((config.ROOT / "policies.yaml").read_text())
        self.assertEqual(config.DEFAULT_MINIMUM_SUCCESS_RATIO, shipped["source_health"]["minimum_success_ratio"])


if __name__ == "__main__":
    unittest.main()
