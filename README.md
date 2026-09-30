# 🚀 Filter-Lists

**Filter-Lists** is a deterministic, compatibility-first filter-list compiler. It fetches configured upstream lists, resolves bounded `!#include` graphs, normalizes and deduplicates rules, applies a strict Adblock Plus (ABP) compatibility policy, validates the generated output, and publishes reproducible build metadata.

**Current builder:** `v7.5.4`  
**Output profile:** `strict-abp`

The project is designed around one principle: **prefer a predictable, portable filter list over accepting engine-specific syntax that may behave differently across blockers.**


## 📥 Subscribe

```text
https://raw.githubusercontent.com/anT0ny54/filter-lists/main/filters.txt
```

The generated `filters.txt` is a **strict ABP-compatible** list. It is intended to be consumable by Adblock Plus and compatible subsets/implementations in other blockers, but the project deliberately does not emit uBlock Origin- or AdGuard-only extensions.

## 🛡️ Syntax and compatibility

The compiler accepts documented ABP syntax and rejects unsupported engine-specific syntax.

### Supported

- Network blocking and exception filters.
- ABP request types and supported inverse types.
- `domain=`, `sitekey=`, `csp=`, and ABP `rewrite=`.
- `header=` response-header matching.
- `addheader=` header injection, including the documented `document` targeting case.
- Element hiding: `##` and `#@#`.
- ABP extended CSS: `#?#`, including supported `:has`, `:has-text`, `:-abp-properties`, `:not`, and `:xpath` forms.
- ABP snippets: `#$#`, with the required domain scope.
- ABP inline CSS declarations under the documented safe property/value grammar.
- ABP `remove: true`.

Security-sensitive features such as snippets, `header=`, and `addheader=` are policy-gated and should only be enabled for trusted sources.

### Rejected

- uBlock Origin procedural filters such as `##+js(...)`.
- uBO-only operators such as `:style()`, `:remove()`, `:upward()`, and `:matches-css()`.
- uBO-only extended-CSS exception syntax `#?@#`.
- AdGuard-only cosmetic extensions.
- Non-ABP network options such as `removeparam`, redirect/scriptlet options, and unknown options.
- Hosts-file syntax.
- HTML/error pages masquerading as filter lists.
- Malformed, duplicate, unsafe, or over-limit rules.

See [docs/SYNTAX-POLICY.md](docs/SYNTAX-POLICY.md) and [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for the exact contract.

## 🏗️ Build pipeline

```text
sources.yaml
    │
    ▼
fetch.py ──► downloads + bounded !#include traversal
    │
    ▼
parser.py ──► rule classification
    │
    ▼
normalize.py ──► canonical rules
    │
    ▼
policy.py ──► strict-ABP compatibility/security gate
    │
    ▼
merge.py ──► deduplication + deterministic ordering
    │
    ├────────► validate.py ──► final integrity / Build-ID validation
    │
    └────────► report.py ────► reproducible build report
    │
    ▼
filters.txt + sources.txt + reports/latest.json
```

## 🔐 Reliability and correctness

The builder currently enforces the following:

- **Single-source configuration:** policy limits are loaded from `policies.yaml`.
- **Authoritative source registry:** `sources.yaml` is the only source registry; `sources.txt` is generated as a URL-only compatibility mirror.
- **Bounded includes:** include depth, total source traversal, and download budgets are enforced globally.
- **Correct source health:** the health ratio is calculated from configured root sources; nested includes cannot inflate it.
- **Required-source gates:** configured required root sources must succeed.
- **SSRF protection:** source/include targets are resolved before connection, non-public addresses are blocked, DNS answers are validated and pinned for curl, proxy environment variables are bypassed, and redirects are validated hop-by-hop.
- **Deadline-aware fetching:** downloads receive only the remaining build deadline; retries are bounded and permanent 4xx failures are not retried.
- **Canonical source identity:** scheme/host/path normalization and fragment removal are used for source identity and include-cycle detection.
- **Deterministic output:** normalization, sorting, deduplication, reporting, and Build-ID generation are deterministic.
- **Full Build-ID validation:** `validate.py` recomputes the build identity from the active configuration and normalized rules.
- **Strict grammar validation:** malformed options, unsupported procedural syntax, unsafe inline styles, malformed regex envelopes, control characters, and over-limit rules are rejected.
- **Detailed diagnostics:** rejection reasons, per-source statistics, SHA-256 hashes, fetch failures, and anomaly information are retained.
- **Historical reports:** successful reports are retained chronologically under `reports/history/` according to the configured retention limit.
- **Safe anomaly handling:** warning-level anomalies are advisory by default; critical anomalies fail the build.

## ⚙️ Limits and policy

The shipped `policies.yaml` currently defines:

| Setting | Value |
|---|---:|
| Maximum rule length | 100,000 |
| Maximum include depth | 5 |
| Maximum per-download bytes | 52,428,800 (50 MiB) |
| Maximum total download bytes | 524,288,000 (500 MiB) |
| Maximum total sources | 500 |
| Total build timeout | 1,800 seconds |
| Minimum root-source success ratio | 80% |
| Successful report retention | 10 |
| Anomaly detection | Enabled |
| Warning anomalies fail build | No |

When upstream syntax is ambiguous, the compiler follows the documented policy and **rejects rather than guessing**.

## 📊 Build reports

`reports/latest.json` uses **schema 5** and records:

- root and nested source requests/results
- total visited sources and download bytes
- source-limit and timeout status
- required-source failures
- root-source health ratio
- input, accepted, rejected, duplicate, and unique-rule counts
- rejection reasons
- per-source diagnostics and content hashes
- anomaly baseline, thresholds, severity, and enforcement
- build duration
- deterministic Build-ID and provenance hashes

See [docs/REPORT-SCHEMA.md](docs/REPORT-SCHEMA.md).

## ⚙️ Source configuration

`sources.yaml` is the **only authoritative source registry**.

To disable a source:

```yaml
enabled: false
```

Do not edit `filters.txt` or `sources.txt` directly; they are generated artifacts.

## 🔧 Local build

Requirements:

- Python 3.12+
- `curl`
- PyYAML (`pip install -r requirements.txt`)

Run:

```bash
pip install -r requirements.txt

bash scripts/merge.sh
python3 scripts/validate.py filters.txt
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/benchmark.py --repeats 3
python3 scripts/differential.py
```

A live build requires network access to the configured upstream lists. The builder fails instead of publishing an incomplete result when the root-source health threshold is missed, a required source fails, the global source limit is reached, or the build deadline is exceeded.

## 🧪 Verification coverage

The repository test suite covers:

- parser classification
- strict ABP normalization and canonicalization
- network options and option validation
- cosmetic and extended-CSS rules
- ABP header/addheader/snippet/inline-style/remove features
- nested includes and canonical include-cycle detection
- source-health and required-source accounting
- global source/download limits and deadlines
- deterministic reporting and Build-ID generation
- per-source diagnostics and hashes
- anomaly detection and historical baselines
- deterministic Unicode/property fuzzing (**5,000 iterations per fuzz property**)
- curated real-world syntax corpus
- regression tests
- optional external-engine differential testing
- repeatable parser benchmark


## 📚 Documentation

- [Syntax policy](docs/SYNTAX-POLICY.md)
- [Compatibility matrix](docs/COMPATIBILITY.md)
- [Build report schema](docs/REPORT-SCHEMA.md)
- [Differential engine testing](docs/DIFFERENTIAL-TESTING.md)
- [Changelog](CHANGELOG.md)

## ⚖️ Legal

See [LICENSE](LICENSE). This project is not affiliated with any upstream filter-list maintainer.

## 🔗 Other projects by the maintainer

These are unrelated to the filter-list compiler above but are run by the same maintainer.

**My Free DNS** — DNS-over-HTTPS resolvers using HaGeZi Blocklists Multi Pro + TIF:

| Service | DNS-over-HTTPS URL |
| --- | --- |
| Multi Pro + TIF (Recommended) | `https://freedns.koyeb.app/dns-query` |
| Multi Pro + TIF (Recommended) | `https://dns-pi.vercel.app/api/doh/dns-query` |
| Multi Pro + TIF (Backup) | `https://dnssix.netlify.app/api/doh/dns-query` |
| Multi Pro + TIF (Recommended, but will sleep if not use in 15 minute) | `https://dns-93aca.containers.snapdeploy.app/dns-query` |
| Multi Pro + TIF (Recommended, but will sleep if not use in 15 minute) | `https://doh-93aca.containers.snapdeploy.app/dns-query` |

**Bandwidth Hero Server** — a lightweight image proxy that fetches remote images, compresses them, and returns optimized versions for faster loading and lower data use: https://bhserv.netlify.app/

## 💜 Support this project

If you'd like to support development, consider donating:

**Bitcoin:** `1HntwKxyGCfnSGvGLMUTRAqLnTvLarAQP`
