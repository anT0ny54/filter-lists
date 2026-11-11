# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** release notes are reconstructed from repository contents, generated reports, and verification results where no git history is available.

## [Unreleased]

### Maintenance review, pass 2 (builder version remains 7.6.0)

Every file in the project was re-read, except the intentionally excluded `filters.txt` payload. The full suite (272 tests) passes. The shipped list validates with 0 errors, and every one of its 170,768 rules normalizes to itself, so the Build-ID and published `filters.txt` are unchanged by this pass.

#### Fixed

- **Ordinary element-hiding rules rejected from untrusted sources** (`scripts/normalize.py`): a `#$#` snippet check matched any line containing that text, including inside a CSS attribute. For example, `example.com##div[data-x="#$#"]` was reported as `abp-security-restricted-feature` and dropped from every source without `trusted_abp_features`. Feature detection now uses the parsed cosmetic separator (`cosmetic_separator()`), and the matching snippet, extended-CSS and extended-CSS-disabled rejection reasons use the same separator.

#### Removed

- Duplicated unknown-option test in `_option_list_reason()` and `_normalize_network_with_reason()`; both now call `_is_unknown_option()`.
- Unreachable `"blank"` entry in `uses_restricted_abp_feature()`.
- Redundant `import config` inside `test_v753.py`.

#### Changed

- `tests/test_v760.py`: the local variable that shadowed the `config` module is renamed `cfg`.
- `README.md`: documents separator-aware feature gating.

#### Tests

- `tests/test_normalize.py`: two new cases under `SeparatorScopeTests`. One checks that marker text inside a CSS attribute is not a snippet; one checks that a real `#$#` snippet still requires trust.

#### Verified

- Full unit suite: 272 tests, all passing.
- Shipped `filters.txt`: validates with 0 errors.
- Structured fuzzing and cross-module symbol scan from the previous pass remain clean.
