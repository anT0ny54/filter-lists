# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** this file was written from the repository contents (code, comments, tests, docs, and generated reports). No git history was available, so every release section below is **reconstructed** from code comments, test names/docstrings and documentation, and no release dates are claimed. Dates appear only where a generated report records them. The older sections list what the code and tests provably contain; they may be incomplete.

## [Unreleased]

### Maintenance pass (2026-10-20; 222 tests, all passing; version unchanged at 7.6.0)

#### Fixed
- **Misplaced `if __name__ == "__main__"` blocks in two test files** (`tests/test_hardening.py`, `tests/test_regressions.py`): move each entry point after the last test class so direct execution runs every test (CI discovery was unaffected).
- **Malformed inline-style blocks** (`scripts/normalize.py`): reject extra/nested braces instead of allowing an earlier declaration block to masquerade as selector text.
- **Strict YAML typing** (`scripts/config.py`): schema versions must be actual integers (not booleans or floats), and source `name`, `url`, and `category` fields must be strings rather than being silently coerced.
- **Ineffective cosmetic policy combinations** (`scripts/config.py`): fail fast when snippet/extended-CSS/inline-style options are enabled with cosmetics disabled, or when `allow_abp_remove_action` is enabled while inline-style rules are disabled.
- **Cumulative redirect download budget** (`scripts/fetch.py`): each redirect hop is limited by the per-source budget remaining after earlier redirect bodies.
- **Persisted anomaly baseline** (`.github/workflows/update.yml`): include `reports/baseline.json` in successful generated-output publication so the builder's slim-baseline fallback survives CI runs.

#### Verified
- Full-repository review excluded `filters.txt` as requested, checked source/config/test/workflow/doc code, checked imports and public script-level definitions for obvious dead code, and parsed all JSON report files. Byte compilation passes and the full suite passes **222/222**. `BUILDER_VERSION` remains `7.6.0`; report schema 5, policy schema 3, and source schema 1 are unchanged.

#### Changed
- **README source-quality snapshot refreshed** to `reports/latest.json` generated 2026-10-19: 230,119 input lines, 200,164 accepted, 174,777 unique rules, overall rejection rate 13.02%; the table now clearly distinguishes plain and effective rejection rates.

