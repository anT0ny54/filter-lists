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
- `source_reputation`: rolling historical success/failure score by URL.
- `rules`: aggregate accepted/rejected/duplicate statistics.
- `anomalies`: baseline comparison and enforcement decision.
- `build_seconds`: elapsed build duration.

## Per-source fields

A source result contains URL, depth, status, bytes, SHA-256 content hash, source metadata (name/category/priority/required), rule counts, rejection rate, and rejection reasons when available.

## Reproducibility

`build_id` is deterministic for the same source configuration, policy, custom rules, and normalized rule set. Operational timestamps are intentionally excluded from the build identity.

## Historical retention

Successful builds are copied to `reports/history/` using the full deterministic build ID (`build-<build_id>.json`), so identical builds are archived only once. A failed run updates `latest.json` for diagnostics but is never treated as a successful historical baseline.
