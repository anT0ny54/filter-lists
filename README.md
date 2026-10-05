# 🚀 Filter-Lists

**Filter-Lists** is a deterministic, compatibility-first filter-list compiler. It fetches configured upstream lists, resolves bounded `!#include` graphs, normalizes and deduplicates rules, applies a strict Adblock Plus (ABP) compatibility policy, validates the generated output, and publishes build metadata with deterministic hashes and provenance.

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
- Option-less patterns with no literal content (`*`, `||`, `^`, `@@*`, ...), which would match every request. Scoped forms such as `*$script,domain=example.com` remain valid.

`!#if` / `!#else` / `!#endif` conditional directives are **not evaluated**: the directive lines are dropped and the rules inside the blocks are processed like any other rule. `!#include` is resolved (bounded, see below).

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
policy.py (constants) + normalize.py policy gate ──► strict-ABP compatibility/security enforcement
    │
    ▼
merge.py ──► deduplication + deterministic ordering
    │
    ├────────► validate.py ──► final integrity / Build-ID validation
    │
    └────────► report.py ────► build report (deterministic identity + operational metadata)
                  └─ health.py ──► per-source rolling reliability reputation
    │
    ▼
filters.txt + sources.txt + reports/latest.json
```

## 🔐 Reliability and correctness

The builder currently enforces the following:

- **Single-source configuration:** policy limits are loaded from `policies.yaml`.
- **Strict configuration validation:** unknown keys in `policies.yaml` (including every `rules:` switch) and `sources.yaml`, wrong value types, and a mismatched policy `version`/`profile` fail the build immediately with a clean `[ERROR] Configuration` message, before any download starts.
- **Authoritative source registry:** `sources.yaml` is the only source registry; `sources.txt` is generated as a URL-only compatibility mirror.
- **Bounded includes:** include depth, total source traversal, and download budgets are enforced globally.
- **Correct source health:** the health ratio is calculated from configured root sources; nested includes cannot inflate it.
- **Required-source gates:** configured required root sources must succeed.
- **SSRF protection:** source/include targets are resolved before connection, non-public addresses are blocked, DNS answers are validated and pinned for curl, proxy environment variables are bypassed, and redirects are validated hop-by-hop.
- **Deadline-aware fetching:** downloads receive only the remaining build deadline; retries are bounded and permanent 4xx failures are not retried.
- **Canonical source identity:** scheme/host/path normalization and fragment removal are used for source identity and include-cycle detection.
- **Deterministic rule output and identity:** normalization, sorting, deduplication, and Build-ID generation are deterministic. `filters.txt` also contains a `Last updated` timestamp, while `reports/latest.json` records `generated_at` and `build_seconds`; those operational fields intentionally vary between runs.
- **Full Build-ID validation:** `validate.py` recomputes the build identity from the active configuration and normalized rules.
- **Strict grammar validation:** malformed options, unsupported procedural syntax, unsafe inline styles, malformed regex envelopes, control characters, and over-limit rules are rejected.
- **Detailed diagnostics:** rejection reasons, per-source statistics, SHA-256 hashes, fetch failures, and anomaly information are retained.
- **Bounded default concurrency:** the builder uses two download workers by default; effective concurrency is additionally capped by the configured global download budget.
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

Anomaly thresholds accept byte/rule change ratios from 0–10 (0–1000%) and a rejection-rate change from 0–1; the shipped `policies.yaml` uses 0.75 / 0.75 / 0.25.

## 📊 Build reports

`reports/latest.json` uses **schema 5**. Per-source `input_lines` and rejection counts include every input line, so comments, blank lines, and directives are accounted for with the reasons `comment`, `blank`, and `directive`. Successful-build `build_id` values are deterministic hashes of the active source manifest, policy/custom-rule content, and normalized rules. A pre-analysis source-health failure uses the configuration fingerprint as its diagnostic `build_id` because no normalized output has been assembled yet.

The report records:

- root and nested source requests/results
- total visited sources and download bytes
- source-limit and timeout status
- required-source failures
- root-source health ratio
- input, accepted, rejected, duplicate, and unique-rule counts
- rejection reasons
- per-source diagnostics and content hashes
- per-source rolling reliability reputation (observations, success rate, consecutive failures)
- anomaly baseline, thresholds, severity, and enforcement
- deterministic Build-ID and provenance hashes (successful builds)
- operational timestamps and elapsed build duration

See [docs/REPORT-SCHEMA.md](docs/REPORT-SCHEMA.md).

## ⚙️ Source configuration

`sources.yaml` is the **only authoritative source registry**.

The shipped registry enables 33 root sources (EasyList, EasyPrivacy, Fanboy Social, AdGuard base/privacy/social/annoyance/regional lists, and EasyList/ABP regional lists). EasyList and EasyPrivacy are `required: true`; all others are optional and only count toward the root-source success ratio.

To disable a source:

```yaml
enabled: false
```

ABP security-sensitive features (`#$#` snippets, `header=`, `addheader=`) are rejected from every
source by default. To allow them for a source you trust, opt in per source:

```yaml
trusted_abp_features: true
```

`custom-rules.txt` is always trusted. The flag must be a real YAML boolean.

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

`benchmark.py` repeats its small fixture `--multiplier` times (default 5000) so the reported lines/second is stable. `differential.py` is skipped unless `FILTER_ENGINE_CMD` is set; the command must contain the `{input}` placeholder or the script exits with an error.

A live build requires network access to the configured upstream lists. The builder fails instead of publishing an incomplete result when the root-source health threshold is missed, a required source fails, the global source limit is reached, or the build deadline is exceeded.

## 🤖 Automation

- **`update.yml`** runs daily at 03:17 UTC, on manual dispatch, and on pushes to `main` that touch `sources.yaml`, `custom-rules.txt`, `policies.yaml`, `scripts/**`, `tests/**`, `requirements.txt`, or the workflow itself. It runs the test suite, builds, validates, asserts report invariants (schema, builder version, source health, anomalies), then commits `filters.txt`, `sources.txt`, `reports/latest.json`, and `reports/history/` only if they changed.
- **`validate.yml`** runs on pull requests (and manually): byte-compile, test suite, benchmark, and the optional differential test. It never publishes.

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
- stable report record ordering and Build-ID generation
- per-source diagnostics and hashes
- anomaly detection and historical baselines
- deterministic Unicode/property fuzzing (**5,000 iterations per fuzz property**)
- curated real-world syntax corpus
- strict configuration key/type validation and fail-fast policy loading
- generated-list validator hardening (encoding, version/Build-ID suffix, sort order)
- over-broad pattern rejection
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
