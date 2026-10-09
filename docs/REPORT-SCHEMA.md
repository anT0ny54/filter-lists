# Build Report Schema

`reports/latest.json` uses schema **5**. Historical reports use the same schema.

## Top-level fields

- `schema`: integer schema version (`5`).
- `status`: `success` or `failed`.
- `generated_at`: UTC ISO-8601 timestamp.
- `builder`: builder version.
- `profile`: compatibility profile.
- `build_id`: deterministic SHA-256 identity of configuration plus normalized rules.
- `source_count`: enabled root source count.
- `provenance`: source registry, policy, and source-manifest hashes.
- `sources`: fetch and per-source parsing statistics.
- `source_reputation`: rolling success/failure score by URL, one observation per UTC day, built from `reports/source-outcomes.json` (all runs, including failed) plus the current run.
- `source_quality`: per-source rule-yield findings (`items` with `severity`, `effective_rejection_rate`, `accepted_lines`, `top_rejection_reasons`), thresholds, counts, and `enforced_failure`. Added in v7.6.0 as an additive field; the schema number is unchanged.
- `rules`: aggregate accepted/rejected/duplicate statistics.
- `anomalies`: baseline comparison and enforcement decision.
- `build_seconds`: elapsed build duration.

## Per-source fields

A source result contains URL, depth, status, bytes, SHA-256 content hash, source metadata (name/category/priority/required), rule counts, rejection rate, and rejection reasons when available. A source with `status: "failed"` additionally carries a `reason` field describing the fetch/validation failure (for example `timeout`, `html-or-error-page`, or `source-limit`).

## Reproducibility

`build_id` is deterministic for the same source configuration, policy, custom rules, and normalized rule set. Operational timestamps are intentionally excluded from the build identity.

## Historical retention

Successful builds are copied to `reports/history/` as `build-<build_id>-<generated_at>-<report_digest>.json`. These are the **anomaly baselines**. When a newer successful run has the same `build_id`, the older archived report is removed, so retention (default 10 reports, chronological by `generated_at`) counts distinct builds. A failed run updates `latest.json` for diagnostics but is never archived or used as a baseline.

## Source outcome history

`reports/source-outcomes.json` (`{"schema": 1, "runs": [...]}`) stores, for every run including failed ones, `generated_at`, `status`, `build_id`, and a `{url: ok}` map. The newest 120 runs are kept. It is the only input to `source_reputation` besides the current run; if it does not exist yet it is seeded from retained successful reports. Reputation counts one observation per source per UTC day, and a day is a success only if every run that day fetched the source successfully.
