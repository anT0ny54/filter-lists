## v7.1.1 — Source-health and retry hardening

- Fixed the V7.1 global-budget scheduling bug that falsely counted queued root sources as failures when the worker pool exceeded the safe byte reservation capacity.
- Process downloads in budget-safe waves sized from the remaining global byte budget.
- Added bounded curl retries for transient transport/HTTP failures, with Retry-After support left to curl's retry handling and no blanket retry of permanent HTTP errors.
- Made fetch timeouts deadline-aware across retries.
- Added explicit root-source failure diagnostics to CI output.
- Added regression tests for budget-safe queueing and parallelism limits.
- Kept the strict ABP-compatible syntax gate unchanged and non-negotiable.

# Changelog

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
- Pinned GitHub Actions to immutable commit SHAs.
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
