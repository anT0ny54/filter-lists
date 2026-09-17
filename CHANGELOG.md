# Changelog

## Unreleased (maintenance)

Non-functional audit pass. Nothing here changes `normalize.py`/`merge.py`
rule behavior, `BUILDER_VERSION`, or the generated `filters.txt`.

- `.gitattributes` actually removed the `.go`/`.ts`/`.tsx`/`.js`/`.jsx` line-ending
  rules: V7.5.2 documented this cleanup below, but the entries were still
  present; confirmed no files with those extensions exist anywhere in the
  repository and removed them.
- Fixed `tests/test_fetch.py`: an `if __name__ == "__main__":` guard sat
  between two test classes, so running the file directly
  (`python3 tests/test_fetch.py`) silently skipped `FetchBudgetWaveTests`.
  `python3 -m unittest discover` was unaffected. Moved the guard to the end
  of the file.
- Fixed `validate.py`'s sortedness check, which compared `casefold()` only
  and so could miss a file whose two rules share a casefold but are in the
  wrong tie-break order (`merge.py` sorts by `(casefold(), x)`, not
  `casefold()` alone). The check now compares the same tuple key `merge.py`
  writes with. Added `tests/test_validate.py` to cover both the violation
  and the correctly-ordered case.

## V7.5.2

- Tightened strict ABP network grammar for one-sided/domain anchors and escaped literal pipes.
- Rejected whitespace around network-filter option tokens while preserving spaces inside CSP values.
- Canonicalized `domain=` and `sitekey=` value lists to remove order/duplicate redundancy.
- Removed unused imports/constants and corrected builder/version metadata drift.
- Corrected documentation/version drift without changing the generated V7.5.2 rule set.
- Consolidated `BUILDER_VERSION`, which had drifted into three independent copies (`merge.py`, `report.py`, and a hardcoded string in `fetch.py`'s User-Agent), into a single definition in `config.py`; `merge.py`, `report.py`, `validate.py`, and `fetch.py` now all import it.
- Wired the previously unused `policy.PROFILE_NAME` into the build report instead of a second, separately maintained `"strict-abp"` string literal in `report.py`.
- Replaced a hand-typed duplicate of `TYPE_OPTIONS`'s members inside `policy.INVERSE_OPTIONS` with a derived set, so the two can no longer silently drift apart; verified behavior-identical before and after.
- Removed hardcoded patch-version numbers from module docstrings and README section headers that had to be manually kept in sync on every release.
- Corrected a README/CHANGELOG claim that GitHub Actions are pinned to immutable commit SHAs; the workflows actually pin to major version tags (`@v5`), and the documentation now says so.
- Removed `.gitattributes` line-ending rules for languages (`.go`, `.ts`, `.tsx`, `.js`, `.jsx`) that have no files anywhere in this repository.

## V7.5.1

- Fixed test HTTP-server teardown to call `server_close()` and remove the temporary fixture directory, eliminating the `ResourceWarning` from the fetch test suite.
- Added a true `merge.py` end-to-end test using a local HTTP server and the real `collect_sources()` + `analyze_files()` pipeline, including a bounded `!#include` child source.
- Verified the full suite remains deterministic and free of the previous socket warning.
- Kept the release profile strictly `strict-abp`; no engine-specific syntax was added.

## V7.5.0

- **Strict-ABP remains the only release profile.**
- Added end-to-end `merge.py` tests covering successful publication, source-health failure, required-source failure, and anomaly-enforced failure.
- Verified successful builds archive exactly one successful report and failed builds do not archive failed reports.
- Verified output/report/profile/provenance flow through the real `merge.py` orchestration path.

## V7.4.0

- Fixed the successful-build anomaly handling path in `scripts/merge.py` so report data is always loaded before inspection.
- Kept the project on the `strict-abp` profile; uBlock/AdGuard-only procedural syntax remains rejected.
- Made generated-list validation derive its expected version from the builder version instead of a second hard-coded version string.
- Regenerated build artifacts after the V7.4 update so provenance, Build-ID, and version metadata stay aligned.

## V7.3.0

- Compatibility and reproducibility hardening.
- Added per-source input/accepted/rejected/duplicate/unique-rule statistics.
- Added per-source rejection-reason diagnostics.
- Added SHA-256 content hashes for successful downloaded sources.
- Added previous-build anomaly detection for source bytes, line counts, rule counts, and rejection-rate shifts.
- Added warning/critical anomaly severity while keeping normal upstream content changes publishable.
- Added deterministic Unicode and syntax fuzz/property tests for the normalizer.
- Added anomaly-policy validation to centralized `policies.yaml` configuration.
- Expanded report schema from 3 to 4.
- Added historical successful build reports under `reports/history/`.
- Added rolling source reputation and health tracking.
- Added optional `anomaly_detection.fail_on_warning`.
- Added source registry/policy/content provenance to reports and generated headers.
- Added schema 5 report documentation.
- Added compatibility/syntax policy documentation and matrix.
- Added curated real-world syntax corpus tests.
- Added optional external-engine differential harness.
- Expanded deterministic fuzzing to 5,000 iterations per property.
- Added stdlib performance benchmark.
- Improved README landing section and reliability documentation.

## v7.1.1 — Source-health, retry, and validator hardening

- Fixed the V7.1 global-budget scheduling bug that falsely counted queued root sources as failures when the worker pool exceeded the safe byte reservation capacity.
- Process downloads in budget-safe waves sized from the remaining global byte budget.
- Added bounded curl retries for transient transport/HTTP failures, with Retry-After support left to curl's retry handling and no blanket retry of permanent HTTP errors.
- Made fetch timeouts deadline-aware across retries.
- Added explicit root-source failure diagnostics to CI output.
- Added regression tests for budget-safe queueing and parallelism limits.
- Kept the strict ABP-compatible syntax gate unchanged and non-negotiable.

## v7.1 — Strict ABP hardening

- Enforced a conservative strict ABP network-filter grammar gate.
- Preserved ABP regex filters without incorrectly applying Python regex semantics.
- Continued to reject uBlock/AdGuard-only procedural and extended-exception syntax.
- Added strict YAML boolean/integer validation for source configuration.
- Added concurrent global-download budget reservation and deadline-aware download timeouts.
- Added regression tests for malformed regex envelopes, whitespace, interior pipe syntax, and configuration typing.

## v7.0 — P0–P3 hardening

- Fixed root-source health accounting so nested `!#include` sources cannot inflate success ratios.
- Centralized operational limits in `policies.yaml`.
- Added global source-count and download-byte budgets.
- Added canonical URL handling for include-cycle detection.
- Added full Build-ID recomputation during generated-list validation.
- Fixed deterministic sorting when case-folded rule names collide.
- Added offline fetch/integration regression tests.
- Pinned GitHub Actions to major version tags instead of `@main`/`@master`.
- Removed `sources.txt` from workflow triggers because it is generated output.
- Expanded build reporting for root/nested source health and traversal limits.

## V6.6

- Made `sources.yaml` the single authoritative source registry; `sources.txt` is now a generated compatibility mirror.
- Added centralized configuration validation in `scripts/config.py`.
- Added required-source health checks and raised the default minimum source success ratio to 80%.
- Added per-source status data to build reports without storing temporary file paths.
- Added deterministic build IDs derived from source/config policy plus normalized rule content.
- Added V6.6 output metadata and stronger generated-list validation.
- Added a pull-request validation workflow.
- Added canonicalization idempotence and build-hash regression tests.
- Improved rejection reason granularity.
- Removed the duplicated active V5 implementation/test copy.
- Preserved the existing strict-ABP normalization behavior as the compatibility baseline.
