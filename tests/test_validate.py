import contextlib
import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate.py"
spec = importlib.util.spec_from_file_location("validate", SCRIPT)
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

from config import BUILDER_VERSION, config_fingerprint, load_config, source_manifest_sha256  # noqa: E402
from normalize import normalize_rule  # noqa: E402


class ValidateSortednessTests(unittest.TestCase):
    """`filters.txt` must be sorted by the same (casefold, raw) key merge.py
    uses when writing it. Two rules that share a casefold (only case
    differs) can be in file order that satisfies a casefold-only comparison
    while still violating the real tie-break, so the check must compare the
    full sort key rather than casefold() alone."""

    def _run(self, rule_order):
        config = load_config()
        rules = {normalize_rule(r) for r in rule_order}
        self.assertEqual(len(rules), len(rule_order), "fixture rules must normalize to distinct values")
        canonical_order = sorted(rules, key=lambda x: (x.casefold(), x))
        build_id = hashlib.sha256(
            (config_fingerprint(config) + "\n" + "\n".join(canonical_order)).encode()
        ).hexdigest()
        lines = [
            "! Title: Test",
            f"! Version: v{BUILDER_VERSION}-{build_id[:12]}",
            f"! Build-ID: {build_id}",
            f"! Source manifest SHA-256: {source_manifest_sha256(config)}",
            f"! Total rules: {len(rules)}",
            "!",
            *rule_order,
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "filters.txt"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = self._invoke(path)
        return exit_code, buffer.getvalue()

    @staticmethod
    def _invoke(path):
        old_argv = sys.argv
        sys.argv = ["validate.py", str(path)]
        try:
            return validate.main()
        finally:
            sys.argv = old_argv

    def test_tie_break_violation_within_same_casefold_is_flagged(self):
        # Correct order per merge.py's (casefold, x) key is ["||A-rule.example^", "||a-rule.example^"]
        # (uppercase sorts first). Writing them the other way around only
        # differs in the tie-break, so a casefold()-only comparison would
        # miss it.
        exit_code, output = self._run(["||a-rule.example^", "||A-rule.example^"])
        self.assertIn("[UNSORTED]", output)
        self.assertEqual(exit_code, 1)

    def test_correct_tie_break_order_is_accepted(self):
        exit_code, output = self._run(["||A-rule.example^", "||a-rule.example^"])
        self.assertNotIn("[UNSORTED]", output)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
