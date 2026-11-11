# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** release notes are reconstructed from repository contents, generated reports, and verification results where no git history is available.

## [Unreleased]

### Maintenance update (builder version remains 7.6.0)

#### Changed

- `scripts/config.py`: the Build-ID formula is defined once in `build_identity()`. `merge.py` (writes the identity) and `validate.py` (recomputes it) both use it, so the two cannot drift apart. The output is byte-identical.
- `scripts/fetch.py`: IP-literal detection and the default-port rule are shared helpers instead of repeated inline logic. Two test-only wrappers (`_redirect_location`, `_response_content_encodings`) were removed; tests call the single-parse `_header_blocks` / `*_from` helpers.
- `scripts/normalize.py` and `scripts/parser.py`: the classifier carries the cosmetic separator, so normalization no longer rescans the line for it. Procedural and extended-CSS pseudo-class checks are skipped when a cosmetic body contains no `(` (every pattern in those regexes requires one).
- `scripts/normalize.py`: removed always-true `bool(parts)` guards in the domain and sitekey validators, a redundant empty-pattern test, and a duplicated restricted-option set (now `RESTRICTED_OPTIONS`).
- `scripts/report.py`, `scripts/merge.py`: packed one-line statements split for readability; no behavioural change.
- `tests/test_v760.py`: removed a redundant in-function import.

#### Fixed

- `README.md`: the source-quality snapshot cited a superseded report (`2026-11-11T03:22:11Z`). It now matches `reports/latest.json` (`2026-11-11T04:15:34Z`): 224,689 input lines, 194,326 accepted, 171,163 unique rules. The AdGuard Social Media row was off by one and is corrected.

#### Verified

- Full test suite: 280 tests passed.
- Normalization equivalence: original and modified `normalize_rule`, `normalize_rule_with_reason`, `rejection_reason`, and `classify` produce identical results on 351,187 inputs (shipped rules, the fixture, and deterministic fuzz).
- `scripts/validate.py filters.txt`: passes with zero errors (Build-ID unchanged).
- Normalization timing on the shipped rule set: roughly 2% faster (0.726 s to 0.712 s median); within noise on the small benchmark fixture.
- Python byte-compilation and `pyflakes` on `scripts/` and `tests/`: clean.

No release or builder-version bump; the current builder remains `7.6.0`.
