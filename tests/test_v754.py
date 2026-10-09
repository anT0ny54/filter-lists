import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import config  # noqa: E402
from config import BUILDER_VERSION, config_fingerprint, load_config, source_manifest_sha256  # noqa: E402
from fetch import validate_download  # noqa: E402
from normalize import normalize_rule  # noqa: E402
from parser import classify  # noqa: E402

from _helpers import load_script, run_validate  # noqa: E402

validate = load_script("validate.py", "validate_v754")


class StrictConfigKeyTests(unittest.TestCase):
    def _load(self, sources_yaml="", policy_yaml=""):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sources.yaml"
            pol = Path(tmp) / "policies.yaml"
            src.write_text(sources_yaml or "sources:\n  - name: a\n    url: https://a.test/l.txt\n", encoding="utf-8")
            pol.write_text(policy_yaml or "limits: {}\n", encoding="utf-8")
            with patch.object(config, "SOURCE_REGISTRY", src), patch.object(config, "POLICY_FILE", pol):
                return config.load_config()

    def test_shipped_files_load(self):
        self.assertTrue(load_config().sources)

    def test_misspelled_source_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown keys: requried"):
            self._load("sources:\n  - name: a\n    url: https://a.test/l.txt\n    requried: true\n")

    def test_unknown_sources_top_level_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sources.yaml: unknown keys: soruces"):
            self._load("sources: []\nsoruces: []\n")

    def test_misspelled_policy_keys_are_rejected(self):
        for section, key in (
            ("limits", "max_rule_lenght"),
            ("history", "retenton"),
            ("source_health", "minimum_sucess_ratio"),
            ("anomaly_detection", "max_bytes_change_ration"),
        ):
            with self.subTest(section=section):
                with self.assertRaisesRegex(ValueError, f"{section}: unknown keys: {key}"):
                    self._load(policy_yaml=f"{section}:\n  {key}: 1\n")


class ParserFastPathTests(unittest.TestCase):
    def test_comment_directive_and_bang_hash_lines(self):
        self.assertEqual(classify("! plain").kind, "comment")
        self.assertEqual(classify("!").kind, "comment")
        self.assertEqual(classify("  !#include x.txt").kind, "directive")
        self.assertEqual(classify("!#IF cond").kind, "directive")
        # `!#foo` is not a known directive, so it is an ordinary comment.
        self.assertEqual(classify("!#foo").kind, "comment")


class DownloadValidationTests(unittest.TestCase):
    def _check(self, data: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.txt"
            path.write_bytes(data)
            return validate_download(path, 1024 * 1024, reject_html_error_pages=True)

    def test_http_1x_error_status_line_is_rejected(self):
        for body in (b"HTTP/1.1 404 Not Found\n\nnope nope nope nope", b"HTTP/2 500\n\nerror body here....."):
            with self.subTest(body=body[:14]):
                self.assertEqual(self._check(body), (False, "html-or-error-page"))

    def test_html_lookalike_tags_are_not_rejected(self):
        self.assertEqual(self._check(b"<header-ish>\n||example.com^\n||b.example^\n"), (True, ""))

    def test_whitespace_only_is_empty(self):
        self.assertEqual(self._check(b" \n" * 20), (False, "empty"))

    def test_nul_beyond_first_chunk_is_binary(self):
        self.assertEqual(self._check(b"||a.example^\n" * 6000 + b"\x00"), (False, "binary-data"))


class ValidateHardeningTests(unittest.TestCase):
    def _run(self, header_hash=None, raw_bytes=None):
        cfg = load_config()
        rules = ["||a.example^", "||b.example^"]
        build_id = hashlib.sha256((config_fingerprint(cfg) + "\n" + "\n".join(rules)).encode()).hexdigest()
        lines = [
            f"! Version: v{BUILDER_VERSION}-{header_hash or build_id[:12]}",
            f"! Build-ID: {build_id}",
            f"! Source manifest SHA-256: {source_manifest_sha256(cfg)}",
            f"! Total rules: {len(rules)}",
            *rules,
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "filters.txt"
            path.write_bytes(raw_bytes if raw_bytes is not None else ("\n".join(lines) + "\n").encode())
            return run_validate(validate, path)

    def test_valid_list_passes(self):
        self.assertEqual(self._run()[0], 0)

    def test_version_suffix_must_match_build_id(self):
        code, out = self._run(header_hash="0" * 12)
        self.assertEqual(code, 1)
        self.assertIn("hash suffix does not match Build-ID", out)

    def test_invalid_utf8_is_reported_not_raised(self):
        code, out = self._run(raw_bytes=b"! Version: x\n\xff\xfe||a.example^\n")
        self.assertEqual(code, 1)
        self.assertIn("[ENCODING]", out)


class NormalizeRegressionTests(unittest.TestCase):
    def test_normalization_is_idempotent_for_new_forms(self):
        for rule in ("/ads/banner.gif", "/ads/*$image,domain=a.xn--p1ai", "b.xn--p1ai,a.com##.ad"):
            with self.subTest(rule=rule):
                once = normalize_rule(rule)
                self.assertIsNotNone(once)
                self.assertEqual(normalize_rule(once), once)


if __name__ == "__main__":
    unittest.main()
