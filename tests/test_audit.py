"""Regression tests for the v7.5.4 audit fixes."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import config as config_module  # noqa: E402
from normalize import normalize_rule, rejection_reason, split_options  # noqa: E402
from parser import classify  # noqa: E402
from report import analyze_files  # noqa: E402

# A real-world shape that used to be published: the header value ends in "/",
# so the whole rule was mistaken for one big regex and never validated
# (`3p` is not ABP; regex header content is reserved by ABP).
REGEX_WITH_HEADER_REGEX = (
    r'/^https:\/\/d[0-9a-z]{12,13}\.cloudfront\.net\/loader\.min\.js$/'
    r'$script,3p,match-case,header=etag:/^W\/"[0-9a-f]{32}"$/'
)


class TrustedFeatureGateTests(unittest.TestCase):
    def test_header_and_addheader_rejected_in_any_option_position_when_untrusted(self):
        for rule in (
            "||a.com^$header=x",
            "||a.com^$script,header=x",
            "||a.com^$third-party,script,header=x",
            "||a.com^$document,addheader=request:x-a:b",
            "||a.com^$script,HEADER=x",
        ):
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule, trusted_abp_features=False))
                self.assertIsNotNone(normalize_rule(rule, trusted_abp_features=True))
                self.assertEqual(
                    rejection_reason(rule, trusted_abp_features=False),
                    "abp-security-restricted-feature",
                )

    def test_untrusted_gate_does_not_reject_ordinary_rules(self):
        for rule in ("||a.com^$script,third-party", "@@||a.com^$domain=b.com", "/ads/$script"):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule, trusted_abp_features=False), normalize_rule(rule))

    def test_snippets_still_gated(self):
        self.assertIsNone(normalize_rule("a.com#$#abort-on-property-read x", trusted_abp_features=False))

    def test_analyze_files_applies_trust_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.txt"
            path.write_text("||a.com^$script,header=x\n||b.com^\n", encoding="utf-8")
            untrusted, _ = analyze_files([path], trusted_paths=set())
            trusted, _ = analyze_files([path], trusted_paths={path})
        self.assertEqual(untrusted, {"||b.com^"})
        self.assertEqual(trusted, {"||b.com^", "||a.com^$header=x,script"})


class TrustedFlagConfigTests(unittest.TestCase):
    def _load(self, sources_yaml: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sources.yaml").write_text(sources_yaml, encoding="utf-8")
            (root / "policies.yaml").write_text("limits: {}\nsource_health: {}\nhistory: {}\n", encoding="utf-8")
            with patch.object(config_module, "SOURCE_REGISTRY", root / "sources.yaml"), \
                 patch.object(config_module, "POLICY_FILE", root / "policies.yaml"):
                return config_module.load_config()

    def test_trusted_abp_features_is_loaded_from_sources_yaml(self):
        cfg = self._load(
            "sources:\n"
            "  - {name: A, url: 'https://a.example/a.txt', trusted_abp_features: true}\n"
            "  - {name: B, url: 'https://b.example/b.txt'}\n"
        )
        self.assertEqual({s.name: s.trusted_abp_features for s in cfg.sources}, {"A": True, "B": False})

    def test_trusted_abp_features_must_be_boolean(self):
        with self.assertRaisesRegex(ValueError, "trusted_abp_features must be a boolean"):
            self._load("sources:\n  - {name: A, url: 'https://a.example/a.txt', trusted_abp_features: 'yes'}\n")


class RegexWithOptionsTests(unittest.TestCase):
    def test_options_after_regex_are_found_when_value_ends_with_slash(self):
        pattern, options = split_options(REGEX_WITH_HEADER_REGEX)
        self.assertTrue(pattern.endswith("loader\\.min\\.js$/"))
        self.assertEqual(options[0], "script")
        self.assertIn("3p", options)

    def test_misparsed_regex_rule_is_now_rejected(self):
        self.assertIsNone(normalize_rule(REGEX_WITH_HEADER_REGEX))
        self.assertEqual(rejection_reason(REGEX_WITH_HEADER_REGEX), "unknown-option")

    def test_legitimate_regex_rules_are_unchanged(self):
        for rule in (
            r"/ads\.js$/",
            r"/ads/$script",
            r"/a$b/$script,third-party",
            r"@@/ads/$domain=a.com",
        ):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)


class ParserEquivalenceTests(unittest.TestCase):
    def test_every_cosmetic_marker_is_still_classified_cosmetic(self):
        for marker in ("##", "#@#", "#?#", "#$#", "#?@#", "#%#", "#@%#", "#@$#", "#$?#", "#@$?#"):
            with self.subTest(marker=marker):
                self.assertEqual(classify(f"example.com{marker}.x").kind, "cosmetic")

    def test_lines_without_markers_are_network(self):
        self.assertEqual(classify("||example.com^$third-party").kind, "network")
        self.assertEqual(classify("#hosts-style-comment").kind, "invalid")


if __name__ == "__main__":
    unittest.main()
