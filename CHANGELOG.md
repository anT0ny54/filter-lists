# Changelog

All notable changes to the Filter-Lists compiler are documented here.

## v7.5.4 — 2026-09-30

### Fixed

- **Trusted ABP feature gate now checks every option position.**
  `header=` and `addheader=` were only detected as the *first* option, so
  `||x^$script,header=...` slipped through untrusted sources. The gate now
  uses the real option parser and rejects restricted features in any
  position (`uses_restricted_abp_feature`).

- **Regex-with-options now correctly separated.** A regex filter whose
  option value itself ends in `/` (e.g.
  `/re/$script,header=etag:/^W\"...$/`) was treated as one large regex,
  skipping all option validation. `split_options` now searches for an
  earlier `$` that closes a valid regex envelope and opens a valid option
  list (`_option_split_inside_trailing_slash`).

- **Over-broad pattern rejection.** Option-less patterns made only of `*`,
  `|`, and `^` (`*`, `||`, `^`, `@@*`, ...) would match every request and
  are now rejected. Scoped forms like `*$script,domain=a.com` remain valid
  (`is_overbroad_pattern`).

- **Lazy policy loading.** `_default_max_rule_length()` now resolves at
  call time instead of import time, so a malformed `policies.yaml` no
  longer crashes `import normalize` with a raw traceback before the
  builder's clean `[ERROR] Configuration` handler can run.

- **Differential test placeholder validation.** `differential.py` now
  exits with an error if `FILTER_ENGINE_CMD` lacks the `{input}`
  placeholder, instead of silently running the same command for every
  fixture.

- **`enforced_failure` key always present.** `detect_anomalies` now
  returns `enforced_failure` and `fail_on_warning` on every code path,
  so the first build (no baseline) and `anomaly_detection.enabled: false`
  no longer produce a report that fails the workflow's `is False`
  assertion.

- **Failed sources excluded from anomaly baseline.** A previously failed
  source has 0 bytes/lines, which made every recovery look like a 100%
  anomaly. Only successful previous fetches are now used as the baseline.

### Added

- `trusted_abp_features` per-source flag in `sources.yaml`. ABP
  security-sensitive features (`#$#` snippets, `header=`, `addheader=`)
  are rejected from every source by default and only honoured for sources
  opted in with `trusted_abp_features: true`. `custom-rules.txt` is always
  trusted.

- `fail_if_zero_sources` policy in `policies.yaml:source_health`. When
  true (the default), a build with zero enabled root sources fails
  immediately.

- Staged output: `filters.txt` is written to a temp file and only
  `os.replace`d into place after anomaly checks pass, so an
  anomaly-rejected build can never clobber the last good list.

- `keep-alive.txt` and `Keep-Alive.yml` workflow to prevent fork
  dormancy.

### Tests

- `test_audit.py` — trusted feature gating, regex-with-options,
  parser equivalence across all cosmetic markers.
- `test_audit_followup.py` — over-broad patterns, lazy policy import,
  differential placeholder.
- `test_v754.py` — strict config key validation, parser fast path,
  download validation (HTTP/1.x status lines, NUL beyond first chunk),
  validator hardening (version suffix, encoding), normalization
  idempotency for new forms.

## v7.5.3 — 2026-09-29

### Fixed

- **HTTP/1.x error-page detection.** `HTML_ERROR_PAGE_RE` used a
  single-character class for the HTTP version, so `HTTP/1.1 404` never
  matched and only HTTP/2-style bodies were detected. Fixed to
  `HTTP/[0-9.]+`.

- **`<header` false positive.** Word-boundary (`\b`) added so
  `<header-ish>` content in a legitimate filter list is not rejected as
  an HTML error page.

- **Download validation scans entire file for NUL.** A NUL byte beyond
  the first 64 KiB sample was missed. The validator now continues
  streaming in 1 MiB chunks.

- **`validate_download` does not read entire file for the sample.**
  Confirmed by a test that patches `Path.read_bytes` to raise — only the
  64 KiB sample and chunk stream are used.

### Tests

- `test_v753.py` — procedural cosmetic operators, engine-specific
  separators, anomaly baseline exclusion, staged output, policy file
  validation, default success-ratio consistency.

## v7.5.2 — 2026-09-17

### Added

- Per-source rolling reliability reputation (`health.py`): observations,
  success rate, consecutive failures, and a `poor`/`watch`/`good`/
  `excellent` label in every build report.

- Anomaly detection: byte-change, rule-count-change, and
  rejection-rate-change thresholds compared against the previous
  successful build. Critical anomalies fail the build; warning-level
  anomalies are advisory unless `fail_on_warning: true`.

- Historical report retention: successful reports archived under
  `reports/history/` with chronological retention (default 10).

- Global download budget enforcement: per-source downloads are capped
  and the global byte total is enforced in deterministic submission
  order, so parallel downloads cannot jointly overshoot the budget.

- Download-budget-aware parallelism: the effective concurrency is the
  minimum of the worker count and `max_total_download_bytes /
  max_download_bytes`.

### Fixed

- **Deterministic result ordering.** Network completion order no longer
  decides report-record order, output-file order, or include traversal
  order. Outcomes are processed in deterministic submission order.

- **Deterministic include traversal.** Discovered children are sorted by
  `(depth, canonical_url)` so a global source limit cannot make
  identical builds choose different children depending on timing.

- **`record_unattempted` accounting.** Sources queued but never
  attempted (due to a global limit or timeout) are counted as failures
  with the reason `source-limit`, `global-timeout`, or
  `global-download-budget-exhausted`, so `requested = successful +
  failed` always holds.

- **Canonical URL identity.** Default ports removed, scheme/host
  lowercased, fragments stripped, and non-default ports preserved for
  source deduplication and include-cycle detection.

### Tests

- `test_regressions.py` — deterministic fetch ordering, NUL detection
  beyond first chunk, canonical URL, duplicate source names, zero-source
  policy.
- `test_reliability.py` — source reputation, warning enforcement,
  `enforced_failure` presence, stable report ordering, failed report
  exclusion.

## v7.0.0 — 2026-09-17

### Added

- Strict ABP compatibility profile as the sole output profile.
- Centralized configuration in `config.py` with `BUILDER_VERSION` as a
  single source of truth imported by all modules.
- Strict configuration validation: unknown top-level/section keys in
  `policies.yaml` and `sources.yaml`, wrong value types, mismatched
  policy `version`/`profile`, and duplicate canonical URLs all fail the
  build before any download starts.
- SSRF protection: pre-connection DNS resolution, non-public address
  blocking, DNS pinning via `curl --resolve`, `--noproxy *`, hop-by-hop
  redirect validation.
- Bounded `!#include` traversal with depth, total-source, and
  download-byte limits.
- Deadline-aware fetching: downloads receive only the remaining build
  deadline; permanent 4xx failures are not retried.
- Deterministic Build-ID: SHA-256 of source manifest + policy + custom
  rules + normalized rules.
- Build report schema 5 with per-source diagnostics, content hashes,
  rejection reasons, provenance, and anomaly metadata.
- `validate.py` recomputes the Build-ID from the active configuration
  and checks sort order, encoding, version suffix, and provenance.
- `benchmark.py` with `--multiplier` for stable lines/second.
- `differential.py` optional external-engine corpus harness.
- Curated real-world syntax corpus and sample fixture.
- GitHub Actions: `update.yml` (daily build + publish) and
  `validate.yml` (PR validation).

### Tests

- `test_parser.py`, `test_normalize.py`, `test_policy.py`,
  `test_config.py`, `test_fetch.py`, `test_merge.py`,
  `test_integration.py`, `test_validate.py`, `test_properties.py`,
  `test_corpus.py`, `test_v70.py`.
- Deterministic Unicode/property fuzzing: 5,000 iterations per fuzz
  property.
