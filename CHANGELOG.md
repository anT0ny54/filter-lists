# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** release notes are reconstructed from repository contents, generated reports, and verification results where no git history is available.

## [Unreleased]

### Maintenance update (builder version remains 7.6.0)

#### Fixed

- `scripts/report.py`: read/hash failures now count only lines actually observed before the error. An unreadable empty file retains its per-file error and failure rate without creating a synthetic rejected line or making aggregate rejection totals exceed input totals. Hash failures are reported separately from read failures.
- `scripts/report.py`: anomaly detection validates the previous report's source container, result rows, and numeric metrics. Malformed historical entries are skipped instead of crashing the next build, while valid entries remain usable.
- `scripts/fetch.py`: HTML/error-page detection checks a bounded continuation after the initial 64 KiB sample, so markers split across that boundary are rejected.
- `scripts/fetch.py`: only final 2xx responses are accepted after supported redirects; unsolicited `206 Partial Content` and non-redirect 3xx responses are rejected. Post-download SHA-256 read failures are recorded as failed sources instead of aborting the build.
- `scripts/validate.py`: filter-file and build-input read errors are reported as validation failures without an uncaught traceback.

#### Updated

- `README.md`: documents HTTP response validation, post-download hash failures, and validator read-error handling. The source-quality snapshot remains tied to the latest report generated at `2026-11-11T03:22:11Z`.
- Regression tests cover empty and partial source-read failures, hash failures, malformed anomaly baselines, the HTML-marker sample boundary, non-success HTTP statuses, and validator file-read errors.

#### Verified

- Full test suite: 280 tests passed.
- Python byte-compilation: passed.
- Shell syntax checks: passed.

No release or builder-version bump; the current builder remains `7.6.0`.
