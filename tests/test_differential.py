"""Tests for the optional external-engine differential harness."""
import contextlib
import io
import os
import unittest
from unittest.mock import patch

from _helpers import load_script


differential = load_script("differential.py", "differential_tests")


class DifferentialHarnessTests(unittest.TestCase):
    def test_missing_engine_is_reported_as_a_fixture_failure(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"FILTER_ENGINE_CMD": "missing-engine {input}"}),
            patch.object(differential.subprocess, "run", side_effect=FileNotFoundError("engine not found")) as run,
            contextlib.redirect_stdout(output),
        ):
            result = differential.main()

        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, len(list(differential.CORPUS.glob("*.txt"))))
        self.assertIn("could not start engine: engine not found", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
