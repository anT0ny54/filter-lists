# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** release notes are reconstructed from repository contents, generated reports, and verification results where no git history is available.

## [Unreleased]

### Maintenance update (2026-11-19; builder version remains 7.6.0)

#### Fixed

- `scripts/normalize.py`: distinguish an escaped terminal `\$` from an unescaped empty option delimiter, using backslash parity consistent with `split_options()`.
- `scripts/normalize.py`: reject ABP's six explicitly forbidden `addheader=` names (case-insensitively), even when they otherwise match the `x-*` grammar.
- `scripts/normalize.py` and `scripts/policy.py`: support the ABP `webbundle` request type and its inverse.
- `scripts/normalize.py` and `scripts/parser.py`: recognize ABP snippet exceptions (`#@$#`), including global exceptions, without applying the trust gate used for snippet execution. Inline-style blocks remain invalid on snippet exceptions.
- `scripts/fetch.py`: read a redirect `Location` only from the final HTTP response header block; an interim response can no longer supply a stale redirect target when the final response has none.
- `scripts/fetch.py`: replace curl's opaque in-process retry loop with individually accounted attempts. Bytes received before a timeout or transient HTTP response are charged against the per-source/global byte budgets before a retry; `Retry-After` is honored, and the successful attempt alone remains as the source file.
- `scripts/fetch.py`: remove a duplicate `root_successful` dictionary key from the source statistics initializer.
- `scripts/differential.py`: convert engine startup errors (missing executables and invalid process arguments) into normal fixture failures instead of uncaught tracebacks.
- `scripts/fetch.py`: constrain leading whitespace in the multiline HTML/error-page detector to a single line, avoiding quadratic rescanning of whitespace-heavy responses during download validation.
- `scripts/report.py`: decode downloaded and custom rule files as strict UTF-8 (while accepting a leading UTF-8 BOM); malformed byte sequences now fail per-file analysis and discard all partially parsed rules instead of being silently replaced with U+FFFD.
- `scripts/fetch.py`: use strict UTF-8 while scanning `!#include` directives; if a source contains malformed bytes, discard all includes discovered earlier in that file rather than fetching children from a source the analyzer will reject.
- `scripts/config.py`: reject raw control characters and whitespace in source/redirect URLs, and preserve invalid explicit-port errors instead of silently canonicalizing an out-of-range port to the default endpoint.
- `scripts/config.py`: preserve raw source URL text until validation and make `canonical_url()` reject invalid URLs instead of trimming leading/trailing whitespace into a different endpoint.
- `scripts/fetch.py`: apply the shared parser line cleaner during include discovery, so `!#include` directives preceded by whitespace and a BOM (including on later lines) are fetched consistently with classification.
- `scripts/normalize.py`: reject C1 Unicode control characters (`U+0080`–`U+009F`) in ordinary network and cosmetic rules, matching the existing URL and regex control-character policy.
- `scripts/fetch.py`: require public unicast addresses before curl connects; reject multicast, reserved, IPv4-mapped, NAT64, Teredo, 6to4, and non-routable ORCHIDv2 IPv6 destinations even when `ipaddress.is_global` alone would accept them.
- `scripts/config.py`: reject duplicate explicit YAML mapping keys in both `sources.yaml` and `policies.yaml`, preventing PyYAML's last-value-wins behavior from overriding security-sensitive settings; retain safe loading and standard YAML merge-key precedence. Only an actual empty YAML document is treated as an empty mapping, so falsy scalar roots fail the object check.
- `README.md`: document strict source-encoding behavior and the fail-closed handling of malformed UTF-8. The source-quality snapshot remains tied to `reports/latest.json` generated `2026-11-18T11:37:30.161081Z` (226,685 input lines, 196,227 accepted, 172,655 unique rules).
- `docs/SYNTAX-POLICY.md` and `docs/COMPATIBILITY.md`: align the documented syntax and restrictions with current ABP request types, snippet exceptions, and `addheader=` rules.

#### Verified

- Regression tests cover escaped/unescaped terminal dollars, `webbundle` and `~webbundle`, forbidden `addheader=` names and casing, global/untrusted snippet exceptions, interim-response redirect headers, missing external-engine executables, HTML detection after many blank lines, malformed UTF-8 source rejection and include fail-closed behavior, raw URL controls and surrounding whitespace, invalid explicit ports, BOM-prefixed UTF-8 compatibility, BOM-aware include discovery, and C1 controls in non-regex rules.
- Additional regressions verify that multicast, reserved IPv6 translation/transition, IPv4-mapped, and ORCHIDv2 addresses are blocked for both IP-literal URLs and DNS answers; duplicate keys are rejected in source and policy YAML while YAML merge-key precedence remains supported, and falsy non-mapping YAML roots are rejected.
- A retry regression test simulates a timed-out partial body followed by HTTP 503 and a successful retry; it verifies all attempt bytes are charged and each next attempt gets only the remaining budget.
- The follow-up audit read all 70 regular project files except the explicitly excluded generated `filters.txt` payload, parsed all 13 report JSON files, and cross-checked source registry/mirror, report totals, latest/baseline identity, history retention, and daily outcome history. This additional pass also rechecked whitespace-preserving URL validation, include/BOM classifier parity, and the full C1 control range.
- Full unit-test suite: **306 tests passed**. Python byte-compilation, shell syntax checks, and JSON/YAML parsing also passed.
- The large generated `filters.txt` payload is intentionally excluded from the audit and was not read or validated.

No release or builder-version bump; the current builder remains `7.6.0`.
