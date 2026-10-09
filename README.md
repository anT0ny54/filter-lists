# 🚀 Filter-Lists

**Filter-Lists** is a deterministic, compatibility-first filter-list compiler. It fetches configured upstream lists, resolves bounded `!#include` graphs, normalizes and deduplicates rules, applies a strict Adblock Plus (ABP) compatibility policy, validates the generated output, and publishes build metadata with deterministic hashes and provenance.

**Current builder:** `v7.6.0`  
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
- **Bounded default concurrency:** the builder uses two download workers by default (override with the `FILTER_LISTS_WORKERS` environment variable); effective concurrency is additionally capped by the configured global download budget.
- **Historical reports:** only *successful* reports are archived under `reports/history/` as anomaly baselines, kept chronologically up to the configured retention limit. A newer run with the same Build-ID replaces the older archived report, so retention counts distinct builds. Failed builds are never archived there.
- **Source reputation:** per-URL success rate, consecutive failures, and a `poor`/`watch`/`good`/`excellent` label are computed from `reports/source-outcomes.json`, which records the per-source fetch outcome of **every** run, including failed builds (up to the last 120 runs). One observation is counted per source per UTC day; a day counts as a success only if every run that day succeeded, so rebuilds cannot overweight a day and failures are not hidden. The first run after upgrading seeds the file from retained successful reports.
- **Source quality gate:** `source_quality` in `policies.yaml` flags sources whose rule lines (comments, blanks and directives excluded) are mostly rejected, recorded in the report and logged as `[WARN]`. Optional `fail_on_critical` makes critical sources fail the build.
- **Safe anomaly handling:** warning-level anomalies are advisory by default; critical anomalies fail the build. Anomalies compare each source against the previous *successful* report; sources that failed in that report are not used as a baseline.
- **Safe publication:** `filters.txt` is staged to a temporary file and only replaced after the report and anomaly checks pass, so a rejected build leaves the last good list in place.

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
| Source-quality gate | Enabled; warn ≥ 30%, critical ≥ 90% effective rejection (sources with ≥ 100 lines) |
| Critical source quality fails build | No |
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
- per-source rolling reliability reputation (daily observations, success rate, consecutive failures)
- per-source rule-yield findings (`source_quality`)
- anomaly baseline, thresholds, severity, and enforcement
- deterministic Build-ID and provenance hashes (successful builds)
- operational timestamps and elapsed build duration

See [docs/REPORT-SCHEMA.md](docs/REPORT-SCHEMA.md).

## ⚙️ Source configuration

`sources.yaml` is the **only authoritative source registry**.

The shipped registry enables 32 root sources (AdGuard Annoyances is present but disabled, see below):

- **EasyList family (ABP-native, `*-minified.txt`):** EasyList, EasyPrivacy, Fanboy Social, and 17 regional lists (China, Dutch, Germany, Liste FR, RU AdList, Portuguese, Spanish, Indo, Vietnam, Bulgarian, Israel, Italy, Lithuania, Polish, Indian, Latvian, RO).
- **AdGuard family (`filters.adtidy.org/extension/ublock/filters/<id>_optimized.txt`):** Base, Tracking Protection, Social Media, and regional lists (Chinese, Dutch, German, Japanese, French, Russian, Spanish, Turkish, Ukrainian) — 12 enabled AdGuard lists in total. These are the **uBlock-flavoured** AdGuard builds, which contain a lot of syntax the strict-ABP profile rejects (see [Source quality](#-source-quality-and-known-limitations)).

EasyList and EasyPrivacy are `required: true`; all others are optional and only count toward the root-source success ratio. Root-source health is judged by download success; rule yield is checked separately by the [source-quality gate](#-source-quality).

**AdGuard Annoyances is disabled** (`enabled: false` in `sources.yaml`): its uBlock build yielded 1 accepted rule from 2,743 lines under the strict-ABP profile. No ABP-compatible upstream variant was verified (no network access during the change), so re-enable it only after finding one.

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

- **`update.yml`** runs daily at 03:17 UTC, on manual dispatch, and on pushes to `main` that touch `sources.yaml`, `custom-rules.txt`, `policies.yaml`, `scripts/**`, `tests/**`, `requirements.txt`, or the workflow itself. It runs the test suite, builds, validates, asserts report invariants (schema, builder version, source health, anomalies), then commits `filters.txt`, `sources.txt`, `reports/latest.json`, `reports/history/`, and `reports/source-outcomes.json` only if they changed. If the build fails, only `reports/source-outcomes.json` is committed (nothing else is published) so failures still count toward source reputation.
- **`validate.yml`** runs on pull requests that touch the same paths (plus `.github/workflows/**`) and on manual dispatch: byte-compile, test suite, benchmark, and the optional differential test. It never publishes.
- **`Keep-Alive.yml`** runs on the 1st and 15th of each month at 03:47 UTC (and manually) and rewrites `.github/keep-alive.txt` with a timestamp so scheduled workflows are not disabled for repository inactivity.

The `update.yml` and `Keep-Alive.yml` jobs share the `repo-write` concurrency group so they cannot race on `git push`.

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
- SSRF-protection and redirect handling in `fetch.py`
- staged-output publication and failed-report baseline handling
- per-source quality gate and failed-run source-outcome history
- download validation (binary data, HTML/error pages, empty files)
- curated real-world syntax corpus
- strict configuration key/type validation and fail-fast policy loading
- generated-list validator hardening (encoding, version/Build-ID suffix, sort order)
- over-broad pattern rejection
- regression tests
- optional external-engine differential testing
- repeatable parser benchmark


## 🔍 Source quality

Download success does not mean a source contributes rules, so each build also evaluates rule yield per source. The **effective rejection rate** is the share of rule lines (input lines minus comments, blanks, and directives) that the strict-ABP profile rejected. With the shipped policy, sources of at least 100 lines at or above 30% are reported as `warning` and at or above 90% as `critical` in `reports/latest.json` (`source_quality`) and in the build log. They are advisory unless `source_quality.fail_on_critical: true`.

Snapshot from the 2026-10-09 report (before AdGuard Annoyances was disabled): 33/33 sources OK, 228,552 input lines, 195,977 accepted, 171,249 unique rules, overall rejection rate 14.25%.

| Source | Input lines | Accepted | Rejection rate | Main reasons |
|---|---:|---:|---:|---|
| AdGuard Annoyances (now disabled) | 2,743 | 1 | 99.96% | `unknown-option` (2,712) |
| AdGuard Ukrainian | 5,537 | 3,614 | 34.73% | `unknown-option` (1,771) |
| AdGuard Social Media | 30,835 | 21,833 | 29.19% | `ubo-only-syntax` (7,334) |
| AdGuard Turkish | 6,811 | 5,254 | 22.86% | `ubo-only-syntax`, `invalid-cosmetic-rule` |
| AdGuard Russian | 7,594 | 5,968 | 21.41% | `unknown-option`, `ubo-only-syntax` |

Most EasyList-family sources reject under 5% of lines (mostly comments). Rejection of AdGuard/uBO-only syntax is intentional under the strict-ABP policy. Figures change with every upstream update; consult `reports/latest.json`.

Other behaviour to be aware of: `!#if` blocks are not evaluated (see above), so rules inside conditional blocks are processed unconditionally.

## 📄 License

[`LICENSE`](LICENSE) is the standard MIT License followed by informational notices (no affiliation, third-party list ownership, no warranty, limitation of liability, compliance with local law, severability). The notices do not restrict the MIT grant. Earlier versions of the file added personal-use-only, no-distribution and no-commercial-use terms that contradicted MIT; those were removed in v7.6.0. This is not legal advice — if you want a restrictive license instead, replace the file with one coherent text and consult a lawyer. Third-party upstream lists remain under their own licenses.

## 📚 Documentation

- [Syntax policy](docs/SYNTAX-POLICY.md)
- [Compatibility matrix](docs/COMPATIBILITY.md)
- [Build report schema](docs/REPORT-SCHEMA.md)
- [Differential engine testing](docs/DIFFERENTIAL-TESTING.md)
- [Changelog](CHANGELOG.md)

## 🌐 Free DNS Services

High-performance DNS utilizing HaGeZi Blocklists (Multi Pro + TIF).

| Blocklist | DNS-over-HTTPS (DoH) |
| :--- | :--- |
| Multi Pro + TIF | `https://freedns.koyeb.app/dns-query` (Recommended) |
| Multi Pro + TIF | `https://dns.mydoh.workers.dev/dns-query` (Recommended) |
| Multi Pro + TIF | `https://dns-pi.vercel.app/api/doh/dns-query` (Recommended) |
| Multi Pro + TIF | `https://dnssix.netlify.app/api/doh/dns-query` |
| Multi Pro + TIF | `https://dns-93aca.containers.snapdeploy.app/dns-query` |
| Multi Pro + TIF | `https://doh-93aca.containers.snapdeploy.app/dns-query` |

## ⚡ Bandwidth Hero Server

A lightweight image optimization proxy designed to slash bandwidth usage and accelerate web browsing.

Bandwidth Hero Server fetches remote images, compresses them on the fly, and delivers optimized versions to the client. This significantly reduces data consumption while improving page load performance.

🖥️ **Live Demo:** [Bandwidth Hero](https://bhserv.netlify.app/).

## Supporting the Project

If you find this project useful, donations are appreciated:

- **Bitcoin**: `1HntwKxyqGCfnSGvGLMUTRAqLnTvLarAQP`
