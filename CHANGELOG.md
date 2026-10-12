# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** this file was written from the repository contents (code, comments, tests, docs, and generated reports). No git history was available, so every release section below is **reconstructed** from code comments, test names/docstrings and documentation, and no release dates are claimed. Dates appear only where a generated report records them. The older sections list what the code and tests provably contain; they may be incomplete.

## [Unreleased]

### Follow-up pass (2026-10-12; 208 → 215 tests)

#### Fixed
- **`split_options` dropped the option section of a regex rule with exactly one unescaped `$` before a trailing slash** (`scripts/normalize.py`): `/banner\d/$script` was accepted as one big unvalidated regex. The final `$` is now a candidate split point, so the rule is split and validated (genuine regexes like `/foo$/` still pass through unchanged). Tests: `tests/test_regressions.py::SplitOptionsRegressionTests`.
- **Contradictory cosmetic policy loaded silently** (`scripts/config.py`): `allow_abp_cosmetic: false` masks `allow_abp_snippets` / `allow_extended_css` (`_normalize_line` returns before the sub-feature gates run), so that combination now fails configuration validation with a clear error. Test: `test_yaml_contradictory_cosmetic_policy_is_rejected`.
- **Reservation leak if `pool.submit()` raised** (`scripts/fetch.py`): the per-request download-budget reservation is released, the entry is recorded as failed, and wave accounting continues instead of leaking the reservation. Dedicated regression tests then exposed a residual: a wave whose submissions all failed at submit time abandoned the rest of the batch, so the wave loop now advances through the remaining entries when submissions were attempted but none reached the executor. Tests: `tests/test_hardening.py::SubmitFailureReservationTests`.

#### Changed
- **Default download parallelism 2 → 10** (`scripts/merge.py`): 10 is the ceiling implied by the shipped download budget (`max_total_download_bytes // max_download_bytes`), and the build is network-bound; still capped per build by the budget and overridable with `FILTER_LISTS_WORKERS`. README updated.
- **Network rejections carry their reason from the normalizer** (`scripts/normalize.py`): `_normalize_network_with_reason()` returns the exact reason at the point of failure, so the rejection hot path no longer re-runs `_rejection_reason()`'s full re-validation per rejected line; reason strings are unchanged (pinned by `NetworkReasonConsistencyTests` across every reason branch).
- **`archive_successful_report` scans the history directory once** (`scripts/merge.py`) instead of globbing and JSON-parsing every history file twice; same removals, same retention semantics.
- **Slim anomaly baseline** (`scripts/merge.py`): `reports/baseline.json` (per-source anomaly fields plus build identity only) is written on archive; `load_previous_report()` fallback order is current report → slim baseline → full history scan.
- **DNS pins cached per `(host, port)` per build** (`scripts/fetch.py`): a source and its `!#include` children typically share a host; resolution failures are cached as sticky within the build. Tests: `tests/test_hardening.py::DnsPinCacheTests`.
- **Same-day reruns compacted in `source-outcomes.json`** (`scripts/health.py`): one stored entry per source per UTC day (per-source outcome = AND of the day's runs; newest run's identity kept so `set_outcome_status()` still matches); reputation results are unchanged. README updated.
- **`benchmark.py`**: removed the loop-assigned `accepted`/`unique` accumulators (values taken from the final repeat; the workload is deterministic).

#### Tests
- `tests/test_regressions.py`: contradictory-policy guard, single-`$` split regression, 17-case fast-reason vs `_rejection_reason` consistency matrix.
- `tests/_helpers.py` / `tests/test_hardening.py`: merge-root fixtures also redirect the new `BASELINE_FILE` path.
- `tests/test_hardening.py`: `SubmitFailureReservationTests` (budget reservation released on submit failure; wave with all-submits-failed keeps advancing) and `DnsPinCacheTests` (pin cache hits per host, per-port entries, sticky failure caching).


Audit and maintenance pass over the whole repository (all scripts, tests, workflows, configs and docs read; baseline of 186 tests passing before changes, 208 after). `BUILDER_VERSION` remains `7.6.0`; report schema (5), policy schema (3) and sources schema (1) are unchanged, and `policies.yaml` / `sources.yaml` / `custom-rules.txt` are untouched, so the shipped `filters.txt` still validates and every one of its 172,089 rules normalizes exactly as before.

