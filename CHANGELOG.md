# Changelog

Only the latest change set is kept here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — ABP inverse-option grammar correction (2026-11-19; builder version 7.6.1)

### Fixed

- `scripts/policy.py` and `scripts/normalize.py`: inverse (`~`) forms now apply to every ABP request type, including `font`, `media`, and `popup`. The exception-only options `document`, `elemhide`, `generichide`, and `genericblock` no longer accept inverse forms. The documented `$addheader=...,document` blocking-rule exception remains supported.
- Added regression coverage for every inverse request type and for rejecting inverse exception-only options on both blocking and exception filters.

### Changed

- Bumped the centralized builder version to `7.6.1` because the corrected grammar can change the generated rule set.
- Updated the README and compatibility documentation to distinguish request types from exception-only options and to identify the checked-in v7.6.0 report as a pre-7.6.1 snapshot.

### Reviewed

- Read all 60 in-scope files in the combined base archive plus the prior modified-files patch. As requested, `filters.txt` and every `*/reports/history/*` file were excluded.
- Rechecked production code, tests, workflows, source and policy configuration, checked-in reports, and documentation. The inverse-option mismatch was confirmed against the current Adblock Plus filter syntax reference; no additional reproducible defect or safe production-code removal was established.

### Verified

- Full unit suite: **312 tests passed**.
- Python byte-compilation, shell syntax, and YAML parsing: passed.
- Two-phase benchmark (3 repeats): normalization ~263,436 lines/s; representative merge ~259,337 lines/s.
- Optional differential engine test: skipped as designed because `FILTER_ENGINE_CMD` is not configured.
- The checked-in `reports/latest.json` and historical report artifacts were not regenerated; the latest report remains the previous v7.6.0 build snapshot.
