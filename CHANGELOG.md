# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** this file was written from the repository contents (code, comments, tests, docs, and generated reports). No git history was available, so releases before 7.5.4 are reconstructed from code comments and test names, and no release dates are claimed. Dates appear only where a generated report records them.

## [7.6.0]

Addresses the findings of the v7.5.4 review. `BUILDER_VERSION = "7.6.0"`; report schema (5), policy schema (3) and sources schema (1) are unchanged (new fields/keys are additive and optional).

### Added
- **Source-quality gate.** New `source_quality` section in `policies.yaml` (`enabled`, `min_lines`, `warn_rejection_rate`, `critical_rejection_rate`, `fail_on_critical`). Each build computes a per-source effective rejection rate (comments, blanks and directives excluded), records findings under `source_quality` in the report, and logs `[WARN]` lines. Advisory by default; `fail_on_critical: true` fails the build.
- **Source outcome history.** `reports/source-outcomes.json` records per-source fetch outcomes for every run, including failed builds, and is committed by `update.yml` even when the build fails (only that file).
- Tests in `tests/test_v760.py`.

### Changed
- **Source reputation** now reads the outcome history instead of successful reports only, and counts one observation per source per UTC day (a day succeeds only if all runs that day succeeded). The first run seeds the history from retained successful reports.
- **History retention** now keeps one report per Build-ID (newest wins), so retention counts distinct builds; the previous "archive every repeat" test was replaced accordingly.
- **AdGuard Annoyances disabled** in `sources.yaml` (1 rule accepted from 2,743 lines). No ABP-compatible upstream variant could be verified offline, so none was substituted. `sources.txt` regenerated (32 sources).
- **LICENSE** is now standard MIT plus non-restrictive notices; the contradictory personal-use-only, no-distribution, no-commercial-use, indemnification, governing-law and entire-agreement terms were removed. This is a maintainer-level decision made on request, not legal advice; revert or replace if a restrictive license is intended.
- README rewritten to match the code; unrelated DNS and Bandwidth Hero sections moved to a "Related projects (not part of this repository)" note; this changelog populated.

### Notes
- `filters.txt` and `reports/` were not regenerated in this change (no network access). The source manifest changed, so the next `update.yml` run rebuilds them; `validate.py` against the old `filters.txt` will report a Build-ID/manifest mismatch until then.

## [7.5.4] – current builder

Verified against the repository: `BUILDER_VERSION = "7.5.4"`, report schema 5, policy schema 3, sources schema 1, profile `strict-abp`.

### Configuration
- Unknown keys are rejected in `policies.yaml` (top level, every section, and each `rules:` switch) and in `sources.yaml` (top level and per source), so a typo cannot silently loosen a gate.
- Wrong value types fail with a clean `[ERROR] Configuration` message before any download; policy `version`/`profile` mismatches are rejected.
- `policies.yaml` is loaded lazily so a malformed file no longer crashes at import time.
- `sources.yaml` `version` is validated; a source cannot be both `required` and disabled.
- Per-source `trusted_abp_features` flag (strict boolean), included in the source-manifest hash and Build-ID.
- `FILTER_LISTS_WORKERS` environment override validated (integer ≥ 1); default is 2 workers.

### Parsing and normalization
- Parser: directives are checked before comments; engine-specific separators (`#%#`, `#@%#`, `#@$#`, `#$?#`, `#@$?#`) are classified cosmetic and then rejected; a leading single `#` is rejected as `hash-comment`.
- Rejection of uBO/AdGuard procedural operators beyond `+js(` (`:style()`, `:remove()`, `:upward()`, `:matches-*()`, and others) under `reject_ubo_procedural`.
- Over-broad option-less patterns (`*`, `||`, `^`, `@@*`, …) rejected as `overbroad-pattern`; scoped forms stay valid.
- Regex rules with options (including option values ending in `/`) are split correctly instead of skipping option validation.
- Plain paths beginning with `/` are no longer misread as regex filters; IDN A-label TLDs (`xn--…`) are accepted in domains.
- Restricted ABP features (`header=`, `addheader=`, `#$#`) are rejected from untrusted sources in any option position; `custom-rules.txt` is always trusted.
- A single-pass `normalize_rule_with_reason()` shares classification between normalization and rejection reporting.

### Fetching
- SSRF protection: resolved addresses must be globally routable, DNS answers are pinned with `curl --resolve`, environment proxies bypassed, redirects validated one hop at a time (max 5), permanent 4xx not retried.
- Deadline-aware downloads, deterministic processing order independent of completion order, and a global download budget enforced against the running total.
- Bounded `!#include` traversal (depth, source count, bytes); canonical URL identity for cycle detection.
- Download validation: too small, too large, binary data (also beyond the first chunk), whitespace-only, and HTML/error pages including `HTTP/1.x 4xx/5xx` status lines.

### Build and publication
- `filters.txt` is staged to a temporary file and replaced only after the report and anomaly checks pass; an enforced anomaly keeps the previous list and marks the report `failed`.
- `sources.txt` regenerated as a URL-only mirror of `sources.yaml`.
- Source-health gate uses root sources only (default minimum 80%), required-source, timeout, source-limit and budget checks.
- `enforced_failure` is present in every anomaly result, including first builds and when detection is disabled.

### Reports and validation
- Report schema 5 with per-source diagnostics, SHA-256 hashes, deterministic ordering, provenance hashes, rejection reasons (including `comment`, `blank`, `directive`), anomaly baseline/thresholds, and `source_reputation`.
- Anomaly detection compares against the previous successful report only; sources that failed there are not baselines.
- `validate.py` recomputes the Build-ID and source-manifest hash, checks sort order, canonical form, duplicates, count, UTF-8 validity, and version suffix.
- Successful reports archived to `reports/history/` and retained chronologically (default 10).

### Tests and CI
- Unit, regression, property/fuzz (5,000 iterations per property), corpus, integration, reliability, config, fetch, merge, and validator tests; `benchmark.py` and the optional `differential.py` harness (`FILTER_ENGINE_CMD`, requires `{input}`).
- `update.yml` (daily 03:17 UTC, manual, and path-filtered pushes) tests, builds, validates, asserts report invariants and commits generated files; `validate.yml` for pull requests; `Keep-Alive.yml` on the 1st and 15th monthly.

## Earlier versions (7.0 – 7.5.3)

Reconstructed from `tests/test_v70.py`, `tests/test_v753.py` and code comments; exact release boundaries are unknown.

- **7.0:** specific rejection reasons (e.g. uBO options), idempotent canonicalization, case-fold sorting with a deterministic tie-breaker, stable Build-ID for identical rules.
- **7.5.3:** procedural-cosmetic rejection, engine-specific separator handling, `hash-comment` rejection, staged output, policy-file validation, failed sources excluded from anomaly baselines.
