# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** this file was written from the repository contents (code, comments, tests, docs, and generated reports). No git history was available, so every release section below is **reconstructed** from code comments, test names/docstrings and documentation, and no release dates are claimed. Dates appear only where a generated report records them. The older sections list what the code and tests provably contain; they may be incomplete.

## [Unreleased]

### Audit pass (2026-10-20; 243 tests, all passing; version unchanged at 7.6.0)

Every project file except the intentionally excluded `filters.txt` payload was read or fully parsed before changes were made; the existing report JSON files were also parsed and checked for structural validity.

#### Fixed
- **False source-limit failures on include cycles** (`scripts/fetch.py`): already-visited include targets could trigger the total-source limit when the visited set reached its cap. The traversal now checks canonical identities before applying the cap and only reports truly unvisited targets as source-limit failures.
- **Collapsed malformed reputation timestamps** (`scripts/health.py`): missing or invalid timestamps were all treated as the same empty-day bucket during reputation scoring, contrary to daily compaction's behavior. Valid ISO timestamps are normalized to UTC, while each malformed/undated run remains a separate observation.
- **Empty ABP inline-style blocks** (`scripts/normalize.py`): declaration blocks containing only semicolons or whitespace were accepted despite containing no property/value declaration. They are now rejected while valid declarations and optional trailing semicolons remain accepted.
- **Conflicting rejection reasons** (`scripts/normalize.py`): `rejection_reason()` re-implemented the network-option checks in a different order from the pipeline, so it disagreed with the reason recorded in reports (for example `unknown-option` vs `invalid-option-or-network-rule`, and `context-invalid-option` for `$document` combined with `addheader=`). It also blamed uBO procedural operators on network rules that are never rejected for them. Both paths now use the single `_normalize_network_with_reason()` validator; a 400,000-input differential fuzz found 0 remaining disagreements.

#### Removed
- Dead `normalize_network()` wrapper (no remaining callers) and the duplicated option-checking block in `_rejection_reason()`.
- Redundant `rule.strip()` in the network validator (callers already pass cleaned lines).
- Redundant `included_requested` field in fetch statistics (always equal to `included_references`, never read). It disappears from `reports/latest.json` on the next build.
- Defensive `getattr(config, "source_quality", None)` in `merge.py`; `BuildConfig` always defines it. Test stubs now provide the field.

#### Changed (optimization / cleanup)
- `fetch.py`: filter already-visited canonical include targets before applying source-limit handling, preventing duplicate/cyclic references from creating false failures.
- `health.py`: use one strict ISO timestamp-to-UTC-day helper for both history compaction and reputation aggregation.
- `normalize.py`: avoid repeated declaration-block slicing/stripping and redundant trailing-whitespace stripping for already-cleaned cosmetic bodies.
- `normalize.py`: the plain-option name set is precomputed once instead of rebuilt for every option of every network rule.
- `fetch.py`: header parsing shared by `_redirect_location()` and `_response_content_encodings()` via `_header_blocks()`; the curl version probe uses `subprocess.run`.
- `report.py`: the per-file record is built by one helper instead of two near-identical literals.
- `merge.py`: all imports moved to the top of the module.
- README source-quality snapshot refreshed to `reports/latest.json` generated 2026-10-20 (230,865 input lines, 200,880 accepted, 175,449 unique rules, 12.99% overall rejection).

#### Added
- Regression coverage for self-including sources at the source cap, cycles with genuinely new children, malformed/undated reputation timestamps, invalid-day compaction, and declarationless inline-style blocks.
- Regression tests for reason agreement (fuzzed), `document` + `addheader` reasons, terminal-`$` reasons, interim-response header blocks, and unreadable-source records.

