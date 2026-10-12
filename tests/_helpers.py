"""Shared test helpers (loaders, validate.main() runner, merge tmp-root fixture)."""
import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_script(filename: str, module_name: str):
    """Load scripts/<filename> as a fresh module named `module_name`."""
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_validate(validate_module, path):
    """Invoke validate.main() on `path`; return (exit_code, captured_stdout)."""
    buffer = io.StringIO()
    old_argv = sys.argv
    sys.argv = ["validate.py", str(path)]
    try:
        with contextlib.redirect_stdout(buffer):
            code = validate_module.main()
    finally:
        sys.argv = old_argv
    return code, buffer.getvalue()


def setup_merge_root(testcase, merge_module, sources_yaml: str) -> Path:
    """Point merge's module-level paths at a throwaway root and seed it.

    Writes sources.yaml / policies.yaml / custom-rules.txt and registers
    cleanup on `testcase`. Returns the root path.
    """
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    testcase.tmp = tmp
    root = Path(tmp.name)
    merge_module.ROOT = root
    merge_module.CUSTOM_RULES = root / "custom-rules.txt"
    merge_module.OUTPUT = root / "filters.txt"
    merge_module.REPORT = root / "reports" / "latest.json"
    merge_module.HISTORY_DIR = root / "reports" / "history"
    merge_module.BASELINE_FILE = root / "reports" / "baseline.json"
    merge_module.SOURCES_TXT = root / "sources.txt"
    (root / "reports").mkdir(parents=True)
    (root / "sources.yaml").write_text(sources_yaml, encoding="utf-8")
    (root / "policies.yaml").write_text("limits: {}\n", encoding="utf-8")
    merge_module.CUSTOM_RULES.write_text("||custom.example^\n", encoding="utf-8")
    return root


def setup_config_root(testcase, config_module, *, sources_yaml=None, policies_yaml=None):
    """Point config's registry paths at a throwaway root and seed it.

    Centralizes the temp-dir + sources.yaml/policies.yaml +
    patch(SOURCE_REGISTRY/POLICY_FILE) + load_config() pattern repeated
    across many test files. Returns the root path; the real registry paths
    are restored after the test.
    """
    saved_registry = config_module.SOURCE_REGISTRY
    saved_policy = config_module.POLICY_FILE
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    testcase.addCleanup(setattr, config_module, "SOURCE_REGISTRY", saved_registry)
    testcase.addCleanup(setattr, config_module, "POLICY_FILE", saved_policy)
    root = Path(tmp.name)
    config_module.SOURCE_REGISTRY = root / "sources.yaml"
    config_module.POLICY_FILE = root / "policies.yaml"
    (root / "sources.yaml").write_text(
        sources_yaml if sources_yaml is not None else
        "sources:\n  - name: a\n    url: https://a.test/l.txt\n", encoding="utf-8")
    (root / "policies.yaml").write_text(
        policies_yaml if policies_yaml is not None else "limits: {}\n", encoding="utf-8")
    return root
