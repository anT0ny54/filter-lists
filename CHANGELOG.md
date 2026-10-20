# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** this file was written from the repository contents (code, comments, tests, docs, and generated reports). No git history was available, so every release section below is **reconstructed** from code comments, test names/docstrings and documentation, and no release dates are claimed. Dates appear only where a generated report records them. The older sections list what the code and tests provably contain; they may be incomplete.

## [Unreleased]

### Audit pass (2026-10-20; 252 tests discovered; 240 passed and 12 curl-gated tests skipped under curl 7.88.1; version unchanged at 7.6.0)

Every project file except the intentionally excluded `filters.txt` payload was read or fully parsed before changes were made; the existing report JSON files were also parsed and checked for structural validity.

#### Fixed
- **Documentation/report drift** (`README.md`, `CHANGELOG.md`): the source-quality snapshot now matches `reports/latest.json` generated 2026-10-20T12:31:38Z (231,110 input lines, 201,121 accepted, 175,580 unique rules, 12.98% overall rejection), and the README now states the existing curl >= 8.4.0 runtime requirement.
- **Network-transfer test portability** (`tests/_helpers.py`, `tests/test_fetch.py`, `tests/test_merge.py`): tests that require curl's unknown-length `--max-filesize` behavior are skipped with a clear reason on curl < 8.4.0 instead of failing after the builder's intentional security gate.
- **False source-limit failures on include cycles** (`scripts/fetch.py`): already-visited include targets could trigger the total-source limit when the visited set reached its cap. The traversal now checks canonical identities before applying the cap and only reports truly unvisited targets as source-limit failures.
- **Collapsed malformed reputation timestamps** (`scripts/health.py`): missing or invalid timestamps were all treated as the same empty-day bucket during reputation scoring, contrary to daily compaction's behavior. Valid ISO timestamps are normalized to UTC, while each malformed/undated run remains a separate observation.
- **Empty ABP inline-style blocks** (`scripts/normalize.py`): declaration blocks containing only semicolons or whitespace were accepted despite containing no property/value declaration. They are now rejected while valid declarations and optional trailing semicolons remain accepted.
- **Conflicting rejection reasons** (`scripts/normalize.py`): `rejection_reason()` re-implemented the network-option checks in a different order from the pipeline, so it disagreed with the reason recorded in reports (for example `unknown-option` vs `invalid-option-or-network-rule`, and `context-invalid-option` for `$document` combined with `addheader=`). It also blamed uBO procedural operators on network rules that are never rejected for them. Both paths now use the single `_normalize_network_with_reason()` validator; a 400,000-input differential fuzz found 0 remaining disagreements.
- **Offset-sensitive run ordering** (`scripts/health.py`): timestamps were sorted as strings, which could choose the wrong daily run identity when ISO timestamps used different UTC offsets. History and same-day compaction now compare normalized UTC instants while retaining conservative failure-wins outcome merging; UTC conversion overflow is treated as an undated entry rather than crashing history processing.
- **Large whitespace-prefixed downloads** (`scripts/fetch.py`): download validation judged a file empty when its first 64 KiB were whitespace, even when valid rules followed. Validation now scans the remaining file for content and NUL bytes, and checks a bounded content probe so padded HTML error markers split across read boundaries remain rejected.
- **Partial source reads** (`scripts/report.py`, `scripts/merge.py`): rules parsed before a mid-read I/O error could leak into the aggregate result, and a build could otherwise publish the remaining partial list. Per-file analysis now commits rules and counters only after the read and hash succeed; any source-analysis read error fails the build and preserves the previous `filters.txt`.
- **Misattributed restricted-feature rejections** (`scripts/normalize.py`): the raw `$header=`/`$addheader=` substring scan ran over whole lines, so cosmetic selectors merely containing that text (and network patterns with escaped-`$` text) were rejected as `abp-security-restricted-feature` from untrusted sources despite carrying no restricted option. The check now relies solely on the real option parser; real `header=`/`addheader=` options and `#$#` snippets are still gated exactly as before. Covered by `RestrictedFeatureScopeTests`.
- **Health-gate rounding** (`scripts/merge.py`): the root-source success ratio was rounded to 4 decimals before the threshold comparison, which could mask a marginally failing ratio (0.79995 rounds to 0.8 and passes an 0.8 threshold). The comparison now uses the unrounded ratio; the reported value stays rounded. Covered by `test_main_success_ratio_threshold_uses_unrounded_value`.

#### Removed
- Dead `normalize_network()` wrapper (no remaining callers) and the duplicated option-checking block in `_rejection_reason()`.
- Redundant `rule.strip()` in the network validator (callers already pass cleaned lines).
- Redundant `included_requested` field in fetch statistics (always equal to `included_references`, never read). It disappears from `reports/latest.json` on the next build.
- Defensive `getattr(config, "source_quality", None)` in `merge.py`; `BuildConfig` always defines it. Test stubs now provide the field.
- Dead `RESTRICTED_RAW_RE` pre-filter in `normalize.py` (superseded by the option-parser check) and a stale comment referencing the removed `normalize_network()`.

#### Changed (optimization / cleanup)
- `fetch.py`: already-visited canonical include targets are filtered before source-limit handling and carried forward through `unvisited_next`, preventing duplicate/cyclic references from creating false failures.
- `health.py`: use one strict ISO timestamp-to-UTC-day helper for both history compaction and reputation aggregation.
- `normalize.py`: avoid repeated declaration-block slicing/stripping and redundant trailing-whitespace stripping for already-cleaned cosmetic bodies.
- `normalize.py`: the plain-option name set is precomputed once instead of rebuilt for every option of every network rule.
- `fetch.py`: header parsing shared by `_redirect_location()` and `_response_content_encodings()` via `_header_blocks()`; the curl version probe uses `subprocess.run`.
- `report.py`: the per-file record is built by one helper instead of two near-identical literals.
- `merge.py`: all imports moved to the top of the module.
- `health.py` / `merge.py`: share normalized UTC timestamp ordering for history, daily outcomes, and archive retention rather than sorting offset-bearing ISO strings lexically; treat UTC-conversion overflow as an undated timestamp.
- `fetch.py`: scan beyond the initial download sample when checking for an empty payload and buffer a bounded HTML probe to avoid missing error markers split across chunk boundaries; keep binary rejection active.
- `report.py`: stage each source's rules, reasons, counters and digest locally until the file has been read and hashed successfully; streamline duplicate counting to operate on per-file sets.
- `merge.py`: fail the build and avoid staging/publishing output if any local source cannot be fully analyzed.
- README source-quality snapshot refreshed to `reports/latest.json` generated 2026-10-20T12:31:38Z (231,110 input lines, 201,121 accepted, 175,580 unique rules, 12.98% overall rejection).

#### Added
- Regression coverage for self-including sources at the source cap, cycles with genuinely new children, malformed/undated reputation timestamps, invalid-day compaction, and declarationless inline-style blocks.
- Regression tests for reason agreement (fuzzed), `document` + `addheader` reasons, terminal-`$` reasons, interim-response header blocks, and unreadable-source records.
- Regression tests for offset-aware and out-of-range timestamp handling, archive-retention ordering across UTC offsets, whitespace-prefixed downloads with chunk-split HTML markers, transactional handling of mid-read errors, and stopping publication after analysis errors.



### Audit follow-up (2026-10-20, second pass; 256 tests discovered; all non-skipped tests passed, 12 curl-gated tests skipped; version unchanged at 7.6.0)

Every script, document, configuration file, workflow, and test module was read in full before judgement; generated artifacts (`reports/*.json`, `filters.txt`) were sampled for consistency only.

#### Changed (optimization / cleanup)
- **Duplicate exception gates** (`scripts/normalize.py`): the two exception-only checks for `$header`/`$addheader` in `valid_option()` were merged into a single set-membership branch. No behavior change; the existing header/addheader coverage (`test_merge.py`, `test_audit.py`, `test_regressions.py`) still passes.

#### Verified, deliberately not changed
- `scripts/config.py` still parses `policies.yaml` up to three times per process; caching `_load_policy` was rejected because tests legitimately swap `POLICY_FILE` and monkeypatch `_load_policy` in-process.
- `scripts/fetch.py` `_ADDRESS_PIN_CACHE` is mutated from worker threads; safe under CPython (worst case a duplicate DNS lookup), with `test_hardening.py::DnsPinCacheTests` pinning the current semantics.

#### Re-verified
- README and CHANGELOG claims still match the code (32 enabled root sources, limits/policy table, curl >= 8.4.0 requirement, report schema 5, policy schema 3 / source schema 1). No documentation drift found; the README gained only a one-line note that the other `scripts/` modules are import-only building blocks.
