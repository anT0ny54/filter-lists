# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** this file was written from the repository contents (code, comments, tests, docs, and generated reports). No git history was available, so releases before 7.5.4 are reconstructed from code comments and test names, and no release dates are claimed. Dates appear only where a generated report records them.

## [Unreleased]

Maintenance pass: documentation reconciled with the code, test-suite cleanup, and one small fetch-loop optimization. `BUILDER_VERSION` remains `7.6.0`; report schema (5), policy schema (3) and sources schema (1) are unchanged.

### Fixed
- **README / CHANGELOG consistency.** The 7.6.0 entry claimed the README was rewritten with the DNS and Bandwidth Hero sections moved to a "Related projects (not part of this repository)" note, but they were still inline top-level README sections. This is now actually done: README.md has a `Related projects (not part of this repository)` section with an explicit disclaimer, and the DNS/Bandwidth Hero content lives under it.
- **Dead in-page anchor** in the Source configuration section of the README: the link now points to `#-source-quality`, matching the `## 🔍 Source quality` heading.
- **Documentation coverage for over-broad patterns.** `docs/SYNTAX-POLICY.md` (Rejected section) and `docs/COMPATIBILITY.md` (output-policy matrix) now document the option-less over-broad-pattern rejection (`*`, `||`, `^`, `@@*` with no options), matching the code, README and tests.
- **Version-marker audit.** Re-checked the builder-version markers: README, this changelog and `config.BUILDER_VERSION` all agree on `7.6.0`; no stale "current builder" tag remains on an older release.

### Changed
- **Extended-CSS naming aligned** across README, `docs/SYNTAX-POLICY.md` and `docs/COMPATIBILITY.md`: all three now list the same supported set — `:has()`, `:has-text()`, `:-abp-has()`, `:-abp-properties()`, `:-abp-contains()`, `:not()` and `:xpath()`.
- **Test module isolation:** `tests/test_v753.py` and `tests/test_v760.py` now load `merge.py` through `_helpers.load_script()` (fresh module instance), like `test_cleanup.py`, `test_merge.py` and `test_regressions.py`, instead of sharing one `import merge` object whose patched module globals could leak between tests if ordering or parallelism ever changes.
- **`canonical_url` imports** in tests now consistently come from `config` (where the function is defined); `tests/test_fetch.py` no longer relies on `fetch.py`'s re-export.
- **`fetch.collect_sources`** now creates a single `ThreadPoolExecutor` (sized to `parallelism`) and reuses it across all download waves of all batches, instead of constructing and tearing down a new pool per wave.
- **Shared test helpers:** new `_helpers.setup_config_root()` centralizes the repeated temp-dir + `sources.yaml`/`policies.yaml` + `patch(SOURCE_REGISTRY/POLICY_FILE)` + `load_config()` setup used across seven test files, and `tests/test_v760.py` now uses the existing `_helpers.setup_merge_root()` instead of hand-rolling the same module-global patching.
- The four copies of the normalization-idempotency check (`test_corpus.py`, `test_properties.py`, `test_v70.py`, `test_v754.py`) were consolidated into one parameterized test (`tests/test_idempotency.py`) covering every former input, including the curated corpus files.

### Removed
- **`tests/test_policy.py`** — its three tests were exact duplicates of `test_merge.py::test_ubo_snippet_is_rejected`, `test_merge.py::test_unknown_ubo_option_rejected` and `test_merge.py::test_rewrite_requires_domain`; coverage is unchanged.
- Dead `import importlib.util` in `tests/test_regressions.py` (module loading is handled by `_helpers.load_script`).
- One stray blank line in `scripts/normalize.py` between the import block and `default_max_rule_length()` (three blank lines reduced to the PEP 8 standard two).
