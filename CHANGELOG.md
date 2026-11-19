# Changelog

Only the latest release/modified log is kept here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — Round 7 audit and concurrent download-budget scheduling fix (2026-11-19; builder version 7.6.2)

### Fixed

- `scripts/fetch.py`: do not mark the global download budget exhausted while concurrent requests still hold temporary byte reservations. Wait for the active wave to complete and release reservations, then stop queued sources only when actual transferred bytes have consumed the global ceiling. This avoids falsely failing a completed build when transfers finish below their reserved caps.
- `tests/test_fetch.py`: add regressions for a four-child include wave that reuses unused reservations and an exact-budget include cycle that must not be mistaken for unattempted work, a source-limit cutoff that must not be mislabeled as byte-budget exhaustion, and distinct failure reasons when both global limits apply in one batch.

### Changed

- README clarifies that the global budget is assessed after active requests finish and unused reservations are released, and documents the new regression coverage.

### Reviewed

- Reapplied `filter-lists-modified-files-round6.zip` over the original `filter-lists-main.zip` before reviewing the merged project.
- Read all 60 in-scope files before judgement. Excluded root `filters.txt` and every `*/reports/history/*` file as requested.
- Rechecked the fetch scheduler and its callers, normalization/merge/report/publishing paths, tests, workflows, configuration, reports, and documentation. No additional safely removable dead code was established; prior parser, publication, report-cleanup, and download-budget CI protections were retained.

### Verified

- Full unit suite: **323 tests passed** (including reservation reuse, exact-budget include cycles, and source-limit/budget status separation).
- Python compilation, shell syntax, YAML/JSON parsing, source registry consistency, and local Markdown link checks: passed.
- Benchmark completed; measurements are informational and environment-dependent. Optional external-engine differential testing was skipped because `FILTER_ENGINE_CMD` is not configured.
- Generated filter data and report snapshots were not regenerated.
