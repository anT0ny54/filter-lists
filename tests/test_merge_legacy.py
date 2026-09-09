#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge.py"
spec = importlib.util.spec_from_file_location("merge", SCRIPT)
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)

class ABPStrictTests(unittest.TestCase):
    def test_network_exception_is_preserved(self):
        rule = "@@||Example.COM^$SCRIPT,domain=example.com|~ads.example.com"
        self.assertEqual(
            merge.normalize_rule(rule),
            "@@||Example.COM^$domain=example.com|~ads.example.com,script",
        )

    def test_cosmetic_exception_is_preserved(self):
        self.assertEqual(
            merge.normalize_rule("Example.COM,foo.com#@#.ad-banner"),
            "Example.COM,foo.com#@#.ad-banner",
        )

    def test_extended_css_is_preserved(self):
        rule = "example.com#?#div:-abp-has(.ad)"
        self.assertEqual(merge.normalize_rule(rule), rule)

    def test_ubo_extended_exception_is_rejected(self):
        self.assertIsNone(merge.normalize_rule("example.com#?@#.ad"))

    def test_ubo_snippet_is_rejected(self):
        self.assertIsNone(merge.normalize_rule("example.com##+js(set-constant, foo, true)"))

    def test_regex_with_dollar_is_preserved(self):
        rule = r"/foo\$bar/"
        self.assertEqual(merge.normalize_rule(rule), rule)
        anchored = r"/foo$/"
        self.assertEqual(merge.normalize_rule(anchored), anchored)
        with_option = r"/foo$/$match-case"
        self.assertEqual(merge.normalize_rule(with_option), with_option)

    def test_options_are_case_normalized_and_sorted(self):
        self.assertEqual(
            merge.normalize_rule("||example.com^$THIRD-PARTY,IMAGE"),
            "||example.com^$image,third-party",
        )

    def test_csp_option_is_preserved(self):
        rule = "||example.com^$csp=script-src: 'none'"
        self.assertEqual(merge.normalize_rule(rule), rule)

    def test_duplicate_options_rejected(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$script,script"))

    def test_unknown_ubo_option_rejected(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$removeparam=utm_source"))

    def test_document_only_exception(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$document"))
        self.assertEqual(
            merge.normalize_rule("@@||example.com^$document"),
            "@@||example.com^$document",
        )

    def test_rewrite_requires_domain(self):
        self.assertIsNone(merge.normalize_rule("||example.com^$rewrite=abp-resource:blank-js"))
        self.assertEqual(
            merge.normalize_rule(
                "||example.com^$rewrite=abp-resource:blank-js,domain=example.com"
            ),
            "||example.com^$domain=example.com,rewrite=abp-resource:blank-js",
        )

    def test_comments_and_hosts_are_rejected(self):
        self.assertIsNone(merge.normalize_rule("! comment"))
        self.assertIsNone(merge.normalize_rule("0.0.0.0 ads.example.com"))

    def test_include_url_resolution(self):
        self.assertEqual(
            merge.urljoin("https://example.com/lists/main.txt", "../child.txt"),
            "https://example.com/child.txt",
        )

if __name__ == "__main__":
    unittest.main(verbosity=2)
