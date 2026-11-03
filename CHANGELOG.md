# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** release notes are reconstructed from repository contents, generated reports, and verification results where no git history is available.

## [Unreleased]

### Code review pass (2026-11-04, eighth pass; builder version remains 7.6.0)

All files except the intentionally excluded `filters.txt` payload were
read in full, including the entire `tests/` tree, docs, and workflows. The
post-change test suite completed with all tests passing.

#### Fixed

- **History retention tiebreak** (`scripts/merge.py`): `archive_successful_report()`
  now sorts archived reports in two stable passes — timestamps descending via
  `timestamp_sort_key`, filename ascending as the tiebreak. A single
  `reverse=True` sort also reversed the filename order for equal
  `generated_at` values, making retention pruning depend on the glob's
  filesystem-dependent enumeration order instead of being fully deterministic.

#### Verified

- No dead or redundant production code, no cross-module conflicts, and no
  other bugs were found in this pass.
- `fetch.py` `_redirect_location` / `_response_content_encodings`
  `Path`-wrappers are intentionally kept: `tests/test_regressions.py`
  exercises them directly.
- `health.py` reputation thresholds (0.80 watch / 0.95 excellent / 3
  consecutive failures) are intentionally independent of
  `config.DEFAULT_MINIMUM_SUCCESS_RATIO`: the former labels rolling
  reputation, the latter gates the per-build root-source health ratio.
- README needs no change: retention remains "chronological by generated_at",
  which stays accurate after the tiebreak fix.
- `filters.txt` remains excluded from this review and from the modified-file
  archive, as requested.

