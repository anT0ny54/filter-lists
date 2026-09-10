# 🚀 Filter-Lists v7.5.0

**A compatibility-first, deterministic filter-list compiler** that fetches trusted sources, resolves bounded `!#include` graphs, canonicalizes rules, applies a strict ABP-compatible policy, validates the generated list, and publishes reproducible build metadata.

## ✨ Why use this project?

- **Compatibility-first:** emits a conservative strict-ABP profile instead of leaking engine-specific syntax.
- **Deterministic:** identical configuration + normalized rules produce the same Build-ID.
- **Reproducible:** source, policy, and content hashes provide provenance for every build.
- **Resilient:** bounded includes, download budgets, deadlines, required-source gates, and anomaly detection protect the build.
- **Observable:** per-source diagnostics and rolling source reputation make upstream failures explainable.
- **Tested:** curated corpus, regression/property/fuzz tests, optional differential engine tests, and a repeatable benchmark.

## 📚 Compatibility & reproducibility

- [Syntax policy](docs/SYNTAX-POLICY.md)
- [Compatibility matrix](docs/COMPATIBILITY.md)
- [Build report schema](docs/REPORT-SCHEMA.md)
- [Differential engine testing](docs/DIFFERENTIAL-TESTING.md)

## 📥 Subscribe

```text
https://raw.githubusercontent.com/anT0ny54/filter-lists/main/filters.txt
```

### 🛡️ Compatibility

The generated list targets a **strict Adblock Plus-compatible syntax profile**. ABP network filters, exceptions, supported ABP options, element hiding, and ABP extended CSS are accepted; uBlock/AdGuard-only syntax is rejected.

The goal is **syntax compatibility first, not maximum engine-specific filtering power**. A downstream blocker may support additional features, but this project will not emit those non-ABP extensions.

## 🏗️ V7.5 architecture

```text
sources.yaml                 # authoritative source registry
     │
     ▼
 fetch.py ──► downloads + bounded !#include graph
     │
     ▼
 parser.py ──► classification
     │
     ▼
 normalize.py ──► canonical strict-ABP rules
     │
     ▼
 policy.py ──► compatibility gate
     │
     ▼
 merge.py ──► deduplicate + deterministic output
     │
     ├────────► validate.py ──► final integrity / Build-ID check
     │
     └────────► report.py ────► build statistics
     │
     ▼
 filters.txt + reports/latest.json + generated sources.txt
```

## 🔐 V7.5.0 hardening

V7.2.0 preserves the established strict-ABP behavior while fixing the previous P0–P3 issues:

- **Single-source configuration:** policy limits are loaded from `policies.yaml`; Python modules no longer maintain independent copies of those limits.
- **Correct source health:** the health ratio is calculated from **root sources only**. Nested `!#include` sources are reported separately and cannot artificially inflate the health ratio.
- **Required-source correctness:** required-source failures are evaluated only against configured root sources.
- **Global include protection:** bounded total source traversal prevents pathological include graphs even when individual include depth is valid.
- **Global download budget:** downloads are processed in budget-safe waves. Queued sources are not counted as failures, and each new wave is sized from the remaining byte budget.
- **URL canonicalization:** include-cycle detection normalizes scheme/host/path and removes fragments.
- **Deadline-aware fetching:** each download receives only the remaining build deadline, and timeout/limit failures are fatal. Retry attempts are bounded and transient HTTP/connection failures are retried without retrying permanent 4xx failures.
- **Full Build-ID validation:** `validate.py` recomputes the build hash from the active configuration and normalized rules.
- **Strict ABP grammar gate:** network filters reject interior `|`, whitespace/control characters, malformed regex envelopes, duplicate/unknown options, and non-ABP procedural syntax.
- **Source-health diagnostics:** failed root URLs and exact fetch/validation reasons are printed when the health gate fails.
- **Action pinning:** GitHub Actions are pinned to immutable commit SHAs rather than floating tags.
- **Generated-source hygiene:** `sources.txt` is generated from `sources.yaml` and no longer triggers its own update workflow.
- **Historical build deltas:** the report format is prepared for deterministic operational comparisons.
- **Per-source observability:** every successful source records bytes, input/accepted/rejected/duplicate counts, unique-rule count, rejection rate, rejection reasons, and a SHA-256 content hash.
- **Rejection diagnostics:** rejection reasons are retained globally and per source, making upstream format changes attributable instead of opaque.
- **Anomaly detection:** the builder compares current source size, line count, rule count, and rejection rate with the previous report and records warning/critical anomalies without confusing expected content-hash changes with failures.
- **Deterministic property/fuzz testing:** the test suite exercises normalization with 2,000 deterministic fuzz inputs and checks canonicalization idempotence/determinism plus anomaly behavior without adding a runtime testing dependency.

## ⚙️ Reliability policy

Warning-level anomalies are advisory by default. To make anomaly warnings fail the build, set:

```yaml
anomaly_detection:
  fail_on_warning: true
```

Successful builds are archived under `reports/history/`. Failed builds remain in `reports/latest.json` for diagnostics but are excluded from future anomaly baselines.

## 📊 Build reporting

`reports/latest.json` records:

- root requested / successful / failed sources
- nested include requested / successful / failed sources
- total visited sources
- global download bytes and configured limits
- source-limit / timeout status
- required-source failures
- health ratio based on root sources
- input / accepted / rejected / duplicate rules
- final unique-rule count
- rejection reasons
- per-source rule diagnostics and SHA-256 content hashes
- anomaly baseline, thresholds, severity, and affected sources
- build duration

## ⚙️ Source configuration

`sources.yaml` is the **only authoritative source registry**. `sources.txt` is generated automatically as a URL-only compatibility mirror.

To disable a source:

```yaml
enabled: false
```

Do not edit `filters.txt` or `sources.txt` directly.

## 🔧 Local build

Requirements:

- Python 3.12+
- curl
- PyYAML (`pip install -r requirements.txt`)

Then:

```bash
./scripts/merge.sh
python3 scripts/validate.py filters.txt
python3 -m unittest discover -s tests -p 'test_*.py' -v
cat reports/latest.json
```

A live build requires network access to the upstream lists. If fewer than 80% of configured **root** sources succeed, any required source fails, the traversal reaches its global source limit, or the build times out, V7 fails instead of publishing a dangerously incomplete list.

## 🧪 Tests & verification

The suite covers:

- parser classification
- strict ABP normalization
- option validation and canonicalization
- cosmetic rules
- nested includes
- include-cycle URL canonicalization
- source-health accounting
- global source/download limits
- deterministic reporting
- per-source hashes and diagnostics
- anomaly detection
- deterministic property/fuzz tests for arbitrary input (5,000 iterations per fuzz property)
- curated real-world syntax corpus
- optional differential engine testing via `scripts/differential.py`
- performance benchmark via `python3 scripts/benchmark.py`
- regression behavior

## 🏪 My Free DNS Server

Use **HaGeZi Blocklists Multi Pro + TIF** with My Free DNS.

| Service | DNS-over-HTTPS URL |
| --- | --- |
| Multi Pro + TIF (Recommended) | `https://freedns.koyeb.app/dns-query` |
| Multi Pro + TIF (Recommended) | `https://freedns-six.vercel.app/api/doh/dns-query` |
| Multi Pro + TIF (Backup) | `https://dnssix.netlify.app/api/doh/dns-query` |

## ⚡ Bandwidth Hero Server

A lightweight image proxy that cuts bandwidth and speeds up browsing. Fetches remote images, compresses them, and returns optimized versions for faster loading and lower data use.

🖥️ **Try it out:** https://bhserv.netlify.app/

## 🚀 Release model

V7.5 focused on compatibility/reproducibility. adds advanced reliability: historical reports, source reputation, configurable anomaly enforcement, optional differential testing, stronger fuzzing, and benchmarking.

## ⚖️ Legal

See [LICENSE](LICENSE). This project is not affiliated with any upstream filter-list maintainer.

## 💜 Support This Project

If you'd like to support development, consider donating:

**Bitcoin:** `1HntwKxyGCfnSGvGLMUTRAqLnTvLarAQP`
