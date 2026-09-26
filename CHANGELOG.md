# Changelog

All notable changes to this project are documented here. Format is loosely
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Earlier history was not tracked in this file; entries begin at the current
release. See `docs/SYNTAX-POLICY.md`, `docs/REPORT-SCHEMA.md`, and
`docs/COMPATIBILITY.md` for the detailed, currently-in-force contracts that
the points below summarize.

## v7.5.2 — current

### Configuration & provenance
- Policy limits (`max_rule_length`, `max_include_depth`, `max_download_bytes`,
  `max_total_download_bytes`, `max_total_sources`, `total_timeout_seconds`)
  are loaded once from `policies.yaml`; no script keeps an independent copy.
- `sources.yaml` is the single authoritative source registry; `sources.txt`
  is a generated URL-only compatibility mirror and must not be edited by
  hand.
- Every build publishes a deterministic `Build-ID`, a source-manifest
  SHA-256, and a policy SHA-256 for reproducibility and auditing.

### Fetching & safety
- Fetch targets are resolved and validated as globally-routable addresses
  before curl connects (SSRF protection), with the resolved address pinned
  via `--resolve` so DNS cannot change between validation and connection.
- Redirects are followed one hop at a time, each hop re-validated, up to a
  hard redirect limit.
- Downloads are processed in budget-safe waves so the global byte budget
  can never be oversubscribed; sources still waiting for a wave are queued,
  not treated as failed, unless a hard deadline/budget/source-limit cutoff
  prevents them from ever being attempted.
- `!#include` traversal is bounded by both a per-branch depth limit and a
  global visited-source limit to prevent include-graph explosions.

### Normalization & policy
- Strict Adblock Plus-compatible grammar: rejects uBO procedural filters,
  the uBO-only `#?@#` exception form, snippet injection (`#$#`),
  hosts-file syntax, HTML/error pages, and unknown or duplicate options.
- Canonicalization is deterministic and idempotent; options are
  lower-cased and sorted, and cosmetic domain lists are deduplicated and
  sorted.

### Health, reporting & anomaly detection
- Source health is computed from root sources only; nested `!#include`
  sources are reported separately and never inflate the health ratio.
- Required-source failures, global timeouts, and source-limit/budget
  exhaustion each independently fail the build rather than publishing a
  partial list.
- `reports/latest.json` (schema 5) records per-source diagnostics, a
  rolling source-reputation score, rejection-reason breakdowns, and
  anomaly comparisons against the previous successful report.
- Successful reports are archived under `reports/history/`, pruned to the
  configured retention by `generated_at` rather than by filename.

### Testing
- Regression, property/fuzz (5,000 deterministic iterations per property),
  integration, and curated real-world corpus tests cover parsing,
  normalization, fetch scheduling/security, reporting, and reliability.
- An optional differential-engine harness (`scripts/differential.py`) and a
  dependency-free benchmark (`scripts/benchmark.py`) are available but not
  required for a build.
