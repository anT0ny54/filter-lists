# 🚀 Filter-Lists v6.6

**A compatibility-first, deterministic filter-list build system** that keeps the project's original merge behavior while making fetching, normalization, policy, validation, testing, and reporting easier to maintain.


## 📥 Subscribe

```text
https://raw.githubusercontent.com/anT0ny54/filter-lists/main/filters.txt
```


### 🛡️ Compatibility

The generated list targets the **strict ABP-compatible core profile** and is intended for Adblock Plus, uBlock Origin, AdGuard, and compatible blockers.

V6 deliberately excludes engine-specific syntax such as uBlock procedural snippets and extended exception syntax. This trades some engine-specific filtering power for predictable cross-engine compatibility.


## 🏗️ V6 architecture

```text
filter-lists/
├── sources.yaml                 # single source of truth
├── sources.txt                  # generated URL-only compatibility mirror
├── policies.yaml                # documented compatibility policy
├── custom-rules.txt             # local rules
│
├── scripts/
│   ├── fetch.py                 # downloads + nested !#include handling
│   ├── parser.py                # line classification
│   ├── normalize.py             # canonicalization + strict validation
│   ├── policy.py                # explicit compatibility policy
│   ├── config.py                # centralized config + source validation
│   ├── merge.py                 # build orchestrator + deterministic output
│   ├── validate.py              # final generated-file validation
│   └── report.py                # build statistics / rejection report
│
├── tests/
│   ├── test_parser.py
│   ├── test_normalize.py
│   ├── test_policy.py
│   ├── test_merge.py
│   └── fixtures/
│
├── reports/
│   └── latest.json              # latest build statistics
│
└── filters.txt                  # generated filter list
```

### Build flow

```text
sources.yaml / sources.txt
          │
          ▼
      fetch.py ──► raw lists + nested includes
          │
          ▼
      parser.py ──► network / cosmetic / invalid classification
          │
          ▼
    normalize.py ──► canonical rules
          │
          ▼
      policy.py ──► strict ABP compatibility gate
          │
          ▼
       merge.py ──► deduplicate + deterministic sort
          │
          ├────────► validate.py ──► final safety check
          │
          └────────► report.py ────► reports/latest.json
          │
          ▼
       filters.txt
```


## 🔒 What V6 preserves

V6.6 is an evolution of the existing project, **not a replacement rewrite**. The original strict behavior is preserved as the compatibility baseline:

- source downloading with curl
- concurrent downloads
- nested `!#include` support
- include cycle/depth protection
- strict ABP-compatible normalization
- duplicate removal
- deterministic sorting
- atomic output replacement
- local `custom-rules.txt`
- existing generated-list format
- existing regression cases

The code is separated into modules so individual pieces can be improved without changing the established behavior accidentally.


## 🧪 Tests

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The V6 suite covers parser classification, normalization edge cases, policy rejection, option handling, cosmetic rules, includes, rewrites, duplicates, and compatibility behavior.


## 🔧 Local build

Requirements:

- Python 3.12+
- curl
- PyYAML (`pip install -r requirements.txt`)

Then:

```bash
./scripts/merge.sh
python3 scripts/validate.py filters.txt
cat reports/latest.json
```

A live build requires network access to the upstream lists. If upstream sources are unavailable or fewer than 80% of configured sources succeed, or any required source fails, V6 fails instead of silently publishing a dangerously incomplete list.


## 📊 Build reporting

`reports/latest.json` records:

- requested / visited / successful / failed sources
- include counts
- source failures
- input lines
- accepted / rejected rules
- duplicate count
- final unique-rule count
- rejection reasons
- build duration

This makes upstream breakage and unexpectedly aggressive filtering visible instead of hiding it behind one generic rejection count.


## ⚙️ Source configuration

`sources.yaml` is the structured V6 registry. `sources.txt` remains in the repository as a compatibility fallback for tooling that expects a URL-per-line file.

To disable a source, set:

```yaml
enabled: false
```

Do not edit `filters.txt` directly; it is generated output.


## 🏪 My Free DNS Server

Use **HaGeZi Blocklists Multi Pro + TIF** with [My Free DNS].

| Service | DNS-over-HTTPS URL |
| --- | --- |
| Multi Pro + TIF (Recommended) | `https://freedns.koyeb.app/dns-query` |
| Multi Pro + TIF (Recommended) | `https://freedns-six.vercel.app/api/doh/dns-query` |
| Multi Pro + TIF (Backup) | `https://dnssix.netlify.app/api/doh/dns-query` |


## ⚡ Bandwidth Hero Server

A lightweight image proxy that cuts bandwidth and speeds up browsing. Fetches remote images, compresses them, and returns optimized versions for faster loading and lower data use.

🖥️ **Try it out:** [Bandwidth Hero](https://bhserv.netlify.app/)


## ⚖️ Legal

See [LICENSE](LICENSE). This project is not affiliated with any upstream filter-list maintainer.

## 💜 Support This Project

If you'd like to support development, consider donating:


**Bitcoin:** `1HntwKxyqGCfnSGvGLMUTRAqLnTvLarAQP`


## V6.6 improvements

- `sources.yaml` is the only authoritative source registry; `sources.txt` is generated as a compatibility mirror.
- Required sources can fail the build independently of the overall success ratio.
- Source-health reporting includes success ratio and required-source failures.
- Rejection reporting distinguishes unknown options, invalid option values, duplicate options, and generic network failures.
- Canonicalization has idempotence regression coverage.
- Generated output carries a deterministic SHA-256 Build-ID and V6.6 version marker.
- Validation checks canonical form, ordering, duplicates, count, and build metadata.
- The obsolete duplicated V5 implementation/test copy was removed from the active tree.
