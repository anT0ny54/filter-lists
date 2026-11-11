# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** release notes are reconstructed from repository contents, generated reports, and verification results where no git history is available.

## [Unreleased]

### Maintenance update (2026-11-11; builder version remains 7.6.0)

#### Fixed

- `scripts/normalize.py`: distinguish an escaped terminal `\$` from an unescaped empty option delimiter, using backslash parity consistent with `split_options()`.
- `scripts/normalize.py`: reject ABP's six explicitly forbidden `addheader=` names (case-insensitively), even when they otherwise match the `x-*` grammar.
- `scripts/normalize.py` and `scripts/policy.py`: support the ABP `webbundle` request type and its inverse.
- `scripts/normalize.py` and `scripts/parser.py`: recognize ABP snippet exceptions (`#@$#`), including global exceptions, without applying the trust gate used for snippet execution. Inline-style blocks remain invalid on snippet exceptions.
- `scripts/fetch.py`: read a redirect `Location` only from the final HTTP response header block; an interim response can no longer supply a stale redirect target when the final response has none.
- `scripts/fetch.py`: replace curl's opaque in-process retry loop with individually accounted attempts. Bytes received before a timeout or transient HTTP response are charged against the per-source/global byte budgets before a retry; `Retry-After` is honored, and the successful attempt alone remains as the source file.
- `scripts/fetch.py`: remove a duplicate `root_successful` dictionary key from the source statistics initializer.
- `README.md`: refresh the source-quality snapshot from `reports/latest.json` (generated `2026-11-11T04:43:00.748304Z`): 224,696 input lines, 194,333 accepted, and 171,170 unique rules.
- `docs/SYNTAX-POLICY.md` and `docs/COMPATIBILITY.md`: align the documented syntax and restrictions with current ABP request types, snippet exceptions, and `addheader=` rules.

#### Verified

- Regression tests cover escaped/unescaped terminal dollars, `webbundle` and `~webbundle`, forbidden `addheader=` names and casing, global/untrusted snippet exceptions, and interim-response redirect headers.
- A retry regression test simulates a timed-out partial body followed by HTTP 503 and a successful retry; it verifies all attempt bytes are charged and each next attempt gets only the remaining budget.
- The second-pass audit read all 69 regular project files except the explicitly excluded generated `filters.txt` payload, parsed all 13 report JSON files, and cross-checked source registry/mirror, report totals, latest/baseline identity, history retention, and daily outcome history.
- Full unit-test suite: **289 tests passed**. Python byte-compilation, shell syntax checks, and JSON/YAML parsing also passed.
- The large generated `filters.txt` payload is intentionally excluded from the audit and was not read or validated.

No release or builder-version bump; the current builder remains `7.6.0`.
