import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize import normalize_rule, normalize_rule_with_reason, rejection_reason

class NormalizeTests(unittest.TestCase):
    def test_empty_option_delimiter_is_rejected(self):
        self.assertIsNone(normalize_rule("||example.com^$"))

    def test_terminal_escaped_dollar_is_literal_pattern_data(self):
        rule = r"foo\$"
        self.assertEqual(normalize_rule(rule), rule)
        self.assertEqual(normalize_rule_with_reason(rule), (rule, None))

    def test_terminal_dollar_after_even_backslash_run_is_an_empty_delimiter(self):
        rule = r"foo\\$"
        self.assertIsNone(normalize_rule(rule))
        self.assertEqual(normalize_rule_with_reason(rule), (None, "invalid-network-rule"))

    def test_webbundle_request_type_and_inverse_are_supported(self):
        for rule in ("||example.com^$webbundle", "||example.com^$~webbundle"):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)

    def test_abp_forbidden_addheader_names_are_rejected_case_insensitively(self):
        names = (
            "x-content-type-options",
            "x-download-options",
            "x-frame-options",
            "x-permitted-cross-domain-policies",
            "x-powered-by",
            "x-xss-protection",
        )
        for name in names:
            for candidate in (name, name.upper()):
                rule = f"||example.com^$addheader={candidate}:value"
                with self.subTest(header=candidate):
                    self.assertIsNone(normalize_rule(rule))
                    self.assertEqual(rejection_reason(rule), "invalid-option-value")
        allowed = "||example.com^$addheader=X-Example:value"
        self.assertEqual(normalize_rule(allowed), allowed)
    def test_long_rule_is_rejected(self):
        self.assertIsNone(normalize_rule("||example.com^" + ("x" * 100001)))

    def test_one_sided_pipe_anchors_are_valid_and_interior_pipes_rejected(self):
        self.assertEqual(normalize_rule("|https://example.com/ads"), "|https://example.com/ads")
        self.assertEqual(normalize_rule("https://example.com/ads|"), "https://example.com/ads|")
        self.assertEqual(normalize_rule("|https://example.com/ads|"), "|https://example.com/ads|")
        self.assertEqual(normalize_rule(r"||example.com/path\|part"), r"||example.com/path\|part")
        self.assertIsNone(normalize_rule("https://example.com/a|b"))
        self.assertIsNone(normalize_rule("|||example.com"))

    def test_option_whitespace_is_rejected(self):
        self.assertIsNone(normalize_rule("||example.com^$script, image"))
        self.assertIsNone(normalize_rule("||example.com^$script ,image"))
        self.assertIsNone(normalize_rule("||example.com^$script,domain =example.com"))
        self.assertEqual(normalize_rule("||example.com^$csp=script-src 'none'"), "||example.com^$csp=script-src 'none'")

    def test_rejection_reason_is_specific(self):
        self.assertEqual(rejection_reason("0.0.0.0 ads.example.com"), "hosts-format")

    def test_extended_css_requires_domain(self):
        self.assertIsNone(normalize_rule("#?#div:-abp-has(.ad)"))
        self.assertEqual(
            normalize_rule("example.com#?#div:-abp-has(.ad)"),
            "example.com#?#div:-abp-has(.ad)",
        )
        self.assertEqual(
            rejection_reason("#?#div:-abp-has(.ad)"),
            "extended-css-domain-required",
        )

    def test_has_text_alias_is_supported_in_extended_css(self):
        rule = "example.com#?#div:has-text(Advertisement)"
        self.assertEqual(normalize_rule(rule), rule)
        self.assertNotEqual(rejection_reason(rule), "ubo-only-syntax")

    def test_has_text_requires_extended_css_separator(self):
        rule = "example.com##div:has-text(Advertisement)"
        self.assertIsNone(normalize_rule(rule))
        self.assertEqual(rejection_reason(rule), "extended-css-selector-requires-#?#")

    def test_cosmetic_domains_are_sorted_and_deduplicated(self):
        self.assertEqual(normalize_rule("B.COM,a.com,b.com##.ad"), "a.com,b.com##.ad")

    def test_inverse_document_and_elemhide_are_valid_abp_options(self):
        for rule in (
            "||example.com^$~document",
            "||example.com^$~elemhide",
            "@@||example.com^$~document",
            "@@||example.com^$~elemhide",
        ):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)

    def test_exception_only_options_remain_rejected_on_blocking_rules(self):
        for option in ("document", "elemhide", "generichide", "genericblock"):
            rule = f"||example.com^${option}"
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule))
                self.assertEqual(rejection_reason(rule), "context-invalid-option")

    def test_duplicate_option_names_with_different_values_are_rejected(self):
        self.assertIsNone(normalize_rule("||example.com^$domain=a.com,domain=b.com"))
        self.assertEqual(
            rejection_reason("||example.com^$domain=a.com,domain=b.com"),
            "duplicate-option",
        )

    def test_duplicate_option_name_with_inverse_modifier_is_rejected(self):
        rule = "||example.com^$third-party,~third-party"
        self.assertIsNone(normalize_rule(rule))
        self.assertEqual(rejection_reason(rule), "duplicate-option")

    def test_domain_option_is_canonicalized_case_insensitively(self):
        self.assertEqual(
            normalize_rule("||example.com^$domain=B.COM|a.com"),
            "||example.com^$domain=b.com|a.com",
        )

    def test_strict_network_grammar_rejects_interior_pipe(self):
        self.assertIsNone(normalize_rule("||example.com|/ads"))

    def test_strict_network_grammar_rejects_whitespace(self):
        self.assertIsNone(normalize_rule("||example.com/foo bar"))

    def test_regex_envelope_is_validated_without_python_regex_semantics(self):
        self.assertIsNotNone(normalize_rule(r"/foo\$bar/"))
        # Starts *and* ends with `/` but the closing slash is escaped, so the
        # regex envelope is malformed.
        self.assertIsNone(normalize_rule(r"/unterminated\/"))
        self.assertIsNone(normalize_rule("//"))

    def test_leading_slash_without_closing_slash_is_a_path_pattern(self):
        # ABP only treats a filter as a regex when it both starts and ends
        # with `/`; `/ads/banner.gif` is an ordinary (very common) pattern.
        for rule in ("/unterminated", "/ads/banner.gif", "/adframe.", "/banner/*/img^", "@@/ads/banner.gif"):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)
        self.assertEqual(normalize_rule("/ads/*$image,domain=a.com"), "/ads/*$domain=a.com,image")
        # A lone slash would match nearly every URL and stays rejected.
        self.assertIsNone(normalize_rule("/"))

    def test_idn_punycode_tld_is_accepted_in_domains(self):
        self.assertEqual(normalize_rule("example.xn--p1ai##.ad"), "example.xn--p1ai##.ad")
        self.assertEqual(
            normalize_rule("||x.com^$domain=a.xn--p1ai|b.com"),
            "||x.com^$domain=a.xn--p1ai|b.com",
        )
        self.assertIsNone(normalize_rule("example.xn--##.ad"))

    def test_regex_payload_may_contain_whitespace(self):
        self.assertEqual(normalize_rule(r"/foo bar/"), r"/foo bar/")

    def test_unmatched_opening_brace_in_style_block_is_rejected(self):
        self.assertIsNone(normalize_rule("example.com##div { color: red"))

    def test_unmatched_closing_brace_in_cosmetic_body_is_rejected(self):
        self.assertIsNone(normalize_rule("example.com##div }"))

    def test_trailing_text_after_style_block_is_rejected(self):
        self.assertIsNone(normalize_rule("example.com##div { color: red } trailing"))

    def test_well_formed_inline_style_remains_accepted(self):
        rule = "example.com##div { display: none }"
        self.assertEqual(normalize_rule(rule), rule)

    def test_inline_style_block_requires_at_least_one_declaration(self):
        for rule in (
            "example.com##div { ; }",
            "example.com##div { ;; }",
            "example.com##div {    ;   }",
        ):
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule))

    def test_inline_style_hex_colors_use_css_valid_lengths(self):
        for color in ("#123", "#1234", "#123456", "#12345678"):
            rule = f"example.com##div {{ background-color: {color} }}"
            with self.subTest(color=color):
                self.assertEqual(normalize_rule(rule), rule)
        for color in ("#12345", "#1234567"):
            rule = f"example.com##div {{ background-color: {color} }}"
            with self.subTest(color=color):
                self.assertIsNone(normalize_rule(rule))

    def test_multiple_or_nested_style_blocks_are_rejected(self):
        for rule in (
            "example.com##div { color: red } { display: none }",
            "example.com##div { color: red { display: none }",
            "example.com##div } { display: none }",
            "example.com##div { display: none; content: }",
        ):
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule))

class SeparatorScopeTests(unittest.TestCase):
    """Inline styles and extended-only pseudo-classes are tied to their separator."""

    def test_inline_style_block_rejected_on_exception_and_snippet_separators(self):
        for rule in (
            "example.com#@#div { display: none }",
            "example.com#$#div { display: none }",
        ):
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule))
                self.assertEqual(rejection_reason(rule), "invalid-cosmetic-rule")

    def test_inline_style_block_still_accepted_on_element_hiding_and_extended_css(self):
        for rule in (
            "example.com##div { display: none }",
            "example.com#?#div:-abp-has(.ad) { display: none }",
        ):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)

    def test_abp_extended_pseudo_classes_require_extended_css_separator(self):
        for rule in (
            "example.com##div:-abp-has(.ad)",
            "example.com##div:-abp-contains(Ad)",
            "example.com##div:-abp-properties(x)",
            "example.com#@#div:-abp-has(.ad)",
        ):
            with self.subTest(rule=rule):
                self.assertIsNone(normalize_rule(rule))
                self.assertEqual(rejection_reason(rule), "extended-css-selector-requires-#?#")

    def test_marker_text_inside_css_attribute_is_not_a_snippet(self):
        # `#$#` inside an attribute value is not a snippet separator, so an
        # untrusted source may still use this ordinary element-hiding rule.
        rule = 'example.com##div[data-x="#$#"]'
        self.assertEqual(normalize_rule_with_reason(rule, trusted_abp_features=False), (rule, None))
        self.assertEqual(normalize_rule(rule), rule)

    def test_real_snippet_still_requires_trust(self):
        rule = "a.com#$#abort-on-property-read x"
        self.assertEqual(
            normalize_rule_with_reason(rule, trusted_abp_features=False),
            (None, "abp-security-restricted-feature"),
        )

    def test_abp_snippet_exception_is_supported_with_or_without_domain(self):
        for rule in (
            "example.com#@$#abort-on-property-read x",
            "#@$#abort-on-property-read x",
        ):
            with self.subTest(rule=rule):
                self.assertEqual(normalize_rule(rule), rule)
                self.assertEqual(
                    normalize_rule_with_reason(rule, trusted_abp_features=False),
                    (rule, None),
                )

    def test_snippet_exception_cannot_carry_inline_style_block(self):
        rule = "example.com#@$#div { display: none }"
        self.assertIsNone(normalize_rule(rule))
        self.assertEqual(rejection_reason(rule), "invalid-cosmetic-rule")

    def test_native_has_stays_valid_on_element_hiding(self):
        rule = "example.com##div:has(> .ad)"
        self.assertEqual(normalize_rule(rule), rule)


if __name__ == "__main__":
    unittest.main(verbosity=2)
