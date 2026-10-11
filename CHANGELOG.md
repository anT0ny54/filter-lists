# Changelog

All notable changes to Filter-Lists are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Provenance note:** this file was written from the repository contents (code, comments, tests, docs, and generated reports). No git history was available, so every release section below is **reconstructed** from code comments, test names/docstrings and documentation, and no release dates are claimed. Dates appear only where a generated report records them. The older sections list what the code and tests provably contain; they may be incomplete.

## [Unreleased]

Audit and maintenance pass over the whole repository (all scripts, tests, workflows, configs and docs read; baseline of 186 tests passing before changes, 208 after). `BUILDER_VERSION` remains `7.6.0`; report schema (5), policy schema (3) and sources schema (1) are unchanged, and `policies.yaml` / `sources.yaml` / `custom-rules.txt` are untouched, so the shipped `filters.txt` still validates and every one of its 172,089 rules normalizes exactly as before.

### Fixed (this audit)
Every item below was reproduced against the previous code by running it, and has a regression test (in `tests/test_hardening.py` unless noted) that fails when the fix is reverted.
- **`scripts/publish.sh` retried permanent rejections.** The retry filter matched the bare word `rejected`, which also appears in `! [remote rejected] ... (protected branch hook declined)`. A branch-protection or hook decline was therefore retried up to `PUBLISH_MAX_ATTEMPTS` times under a misleading "moved during the build" warning. Only git's `[rejected]` form (non-fast-forward / fetch first), stale-info, different-commit and ref-lock errors are retried now; everything else fails immediately. Test: `test_publish.py::test_permanent_remote_rejection_is_not_retried`.
- **`allow_abp_remove_action: false` could be bypassed** (`scripts/normalize.py`). The switch was checked with a space-stripped `{remove:` prefix test, so `example.com##.a {margin: 0; remove: true}` and `{remove<TAB>: true}` were accepted with the switch off. The gate now lives in the declaration parser (`valid_inline_style(body, allow_remove)`), so `remove` is rejected in any position, spelling and case. The separate prefix check was removed.
- **A BOM that followed leading whitespace stayed inside an accepted rule** (`scripts/parser.py`, `scripts/normalize.py`). `classify()` and the normalizers stripped BOM and whitespace in different orders, so `"  \ufeffads.js$script"` was emitted with the BOM and `validate.py`, which re-normalizes, then reported `NONCANONICAL` and failed the build. A shared `parser.clean_line()` now trims whitespace and any leading BOM, in any order. A 400,000-case fuzz run found 199 non-idempotent results before and 0 after.
- **Comments mentioning `$header=`, `$addheader=` or `#$#` were mislabelled** (`scripts/normalize.py`). In untrusted sources they were rejected as `abp-security-restricted-feature` instead of `comment`/`directive`, which also skewed the source-quality rate (non-rule lines were undercounted). Comment, directive and blank lines are now never treated as restricted features. The shipped report records one `abp-security-restricted-feature` rejection (AdGuard Russian); the line itself is not retained, so it is unknown whether it was such a comment.
- **A non-string YAML key under `rules:` crashed with a raw `TypeError`** (`scripts/config.py`) instead of the clean `[ERROR] Configuration` message (`rules:\n  1: true` mixed with a string key could not be sorted). Keys are now sorted and joined via `str()`.
- **A BOM-prefixed HTML error page passed `validate_download`** (`scripts/fetch.py`). `\s` does not match U+FEFF, so `\ufeff<!DOCTYPE html>...` was accepted as a filter list. The detector now allows a BOM before the page marker.
- **`!#include` on the first line of a BOM-prefixed source was not followed** (`scripts/fetch.py`): `include_urls` now reads with `utf-8-sig`. The classifier already treated such a line as a directive, so the include was silently lost.
- **`source_reputation` listed a disabled source** (`scripts/report.py`). `reports/latest.json` had 33 reputation entries for 32 sources; the extra one was the disabled AdGuard Annoyances list, kept alive by the outcome history. The report now lists reputation only for URLs present in the current run (history is retained, so re-enabling a source restores its record).
- **`validate.py` did not flag a duplicate `! Version:` header**, unlike the other three metadata headers. It now reports `[METADATA] ... duplicate '! Version:' header`.
- **Non-object JSON in report history** (`scripts/health.py`, `scripts/merge.py`): a history or `latest.json` file holding a JSON list or scalar raised `AttributeError` while selecting a baseline; such files are now skipped like any other unreadable report.

### Changed (this audit)
- **`scripts/parser.py`**: new `clean_line()` (see above), used by `classify()` and by `normalize_rule`, `normalize_rule_with_reason` and `rejection_reason`.
- **`scripts/normalize.py`**: new `rule_sort_key()` is the single definition of the output order. `merge.py`, `validate.py`, `benchmark.py` and the cosmetic-domain sort previously each spelled out `(x.casefold(), x)`. A line is classified once and the classification is shared with the restricted-feature check (it was classified up to twice per untrusted line). Regex searches for the literal markers `#$#` and `#?#` became `str.find`.
- **`scripts/merge.py`** imports `ROOT` and `CUSTOM_RULES` from `config.py` instead of redefining them.
- **README and docs aligned with the code.** README: `!#safari` and `!#end` are also dropped; the "2026-10-09" source-quality snapshot (171,249 unique rules, 33 sources) matched no retained report and was replaced with the figures of the newest retained report (172,089 unique rules, 226,665 input lines, 32/32 sources); behaviour of `remove`, BOM trimming, reputation scope, `publish.sh` failure classes and the differential timeout is documented. `docs/REPORT-SCHEMA.md`: failure reasons now name `global-timeout` (the code never emits `timeout`) and `global-download-budget-exhausted`. `docs/DIFFERENTIAL-TESTING.md`: `{input}` requirement (exit status 2) and the 300 s per-fixture timeout. `docs/SYNTAX-POLICY.md`: new Directives section, BOM/whitespace trimming and the `remove` switch.

### Added (this audit)
- **`tests/test_hardening.py`**: regression tests for each fix above, including a BOM fuzz idempotency check and the non-object report JSON guard.
- **`tests/test_publish.py::test_permanent_remote_rejection_is_not_retried`**: a `pre-receive` hook on the bare remote declines the push; the script must fail fast without the "moved during the build" warning.

### Removed (this audit)
- Tautological tests replaced by tests of real behaviour: `test_v70.py` hashed identical input twice and sorted with Python's `sorted()` (now checks `rule_sort_key` and canonical collapse of equal rules); `test_merge.py::test_include_url_resolution` only exercised `urllib.parse.urljoin` (now drives `fetch.include_urls`).
- Unused `Path` import in `tests/test_cleanup.py`; unused `urljoin` import in `tests/test_merge.py`.

### Reviewed, left unchanged
- `fetch.collect_sources` can set `budget_exhausted` from reservations alone in principle, but `parallelism` is capped at `max_total_download_bytes // per_source_limit`, so the shipped limits (and any limits the loader accepts) cannot trigger it.
- `getattr(config, "source_quality", None)` in `merge.py` is kept: several tests pass stand-in config objects without that attribute.
- `stats["included_requested"]` duplicates `included_references`; it is kept because it appears in published reports.
- `rejection_reason()` is exercised only by tests; it remains a public helper next to `normalize_rule_with_reason()`.
- curl 8.5 does cap chunked downloads at `--max-filesize` (exit 63 at exactly the limit), so the README's transfer-limit claim holds.
- Performance: `benchmark.py` measures roughly 170k lines/s for normalization in this environment, while the newest recorded build took 17.7 s (`build_seconds`), dominated by network I/O, so no hotspot is worth changing.

### Added (earlier maintenance pass)
- **`scripts/publish.sh`** — race-safe commit-and-push helper used by every CI step that writes to the repository. Usage: `publish.sh -m MESSAGE [--guard PATHSPEC]... -- PATH...`. Options via environment: `PUBLISH_REMOTE`, `PUBLISH_BRANCH` (default `$GITHUB_REF_NAME`), `PUBLISH_MAX_ATTEMPTS` (default 5), `PUBLISH_RETRY_DELAY` (default 2 s, multiplied by the attempt number).
- **`tests/test_publish.py`** — 11 tests (12 after the hook-decline test added below) that run the script against a real bare remote with shallow clones (as in CI): clean push, nothing to publish, branch moved by an unrelated commit, conflicting generated file, pruned history files propagating, stale-input guard, guard-less mode, a branch that moves again during the retry, giving up after the attempt limit, non-retryable failure, missing optional path, usage errors.

### Fixed (earlier maintenance pass)
- **High: `Update Filter List` failed with a push conflict when `main` moved during the build** (`.github/workflows/update.yml`, `.github/workflows/Keep-Alive.yml`). The jobs check out `main` (depth 1), build for minutes, then ran a bare `git push origin HEAD:main`. Any push by someone else in between (the `repo-write` concurrency group only serializes the two workflows with each other, not people) made the push fail as a non-fast-forward after build, tests and strict validation had already passed. All pushes now go through `scripts/publish.sh`, which on a rejection fetches the new tip, resets onto it, re-applies the freshly built generated files (overwrite, not merge, so there is no conflict to resolve; deletions from history pruning are carried over) and retries with backoff. If a build input (`sources.yaml`, `custom-rules.txt`, `policies.yaml`, `scripts/`, `tests/`, `requirements.txt`, `update.yml`) changed on the new tip, the stale output is not published and the step exits 0 with a warning, since the change's own run (or the next scheduled run) rebuilds. Non-retryable push errors (permissions, branch protection) fail immediately. Both `update.yml` push steps, including the failed-build `source-outcomes.json` step, use it, as does the keep-alive job.
- **Global download-byte budget bypass via rejected responses** (`scripts/fetch.py`): transferred bytes are now counted against `max_total_download_bytes` for every completed download, including responses that fail validation (e.g. HTML error pages). Previously only accepted files consumed budget, so repeated invalid responses could transfer unbounded data. The budget remains enforced in deterministic submission order after each wave; an already-failed source keeps its original failure reason instead of being relabelled. Regression test in `tests/test_fetch.py`.
- **Soft global download-byte limit under concurrent transfers** (`scripts/fetch.py`): every scheduled request now reserves its worst-case byte allocation against the remaining global budget before it starts, and the request’s transfer limit is reduced to that reservation near the boundary. Active transfers therefore cannot collectively exceed `max_total_download_bytes`. Regression coverage for concurrent requests near the budget boundary was added in `tests/test_fetch.py`.
- **Lost byte accounting for partial transfer failures** (`scripts/fetch.py`): `download()` now returns the number of body bytes observed before it removes failed partial output, and `collect_sources()` records those bytes even when the source fails. Regression coverage for deleted partial bodies and failed downloads was added in `tests/test_fetch.py`.
- **Malformed inline styles bypassing validation** (`scripts/normalize.py`): any `{` or `}` in a cosmetic body is now treated as an intended `{...}` inline-style block. Unbalanced braces, trailing text after the block, and blocks outside the safe declaration grammar are rejected instead of being accepted as ordinary cosmetic selectors. Tests added for an unmatched opening brace, an unmatched closing brace, and trailing text after a style block.
- **Duplicate metadata headers in generated lists** (`scripts/validate.py`): the validator now rejects duplicate `! Total rules:`, `! Build-ID:`, and `! Source manifest SHA-256:` headers (`[METADATA]`) instead of silently overwriting earlier values and checking only the final one.
- **README / CHANGELOG consistency.** The README states that the DNS and Bandwidth Hero sections live under "Related projects (not part of this repository)" and the project documentation refers to a 7.6.0 changelog entry. The README section is in place with an explicit disclaimer, and this file now contains the 7.6.0 entry (reconstructed below).
- **Dead in-page anchor** in the Source configuration section of the README: the link now points to `#-source-quality`, matching the `## 🔍 Source quality` heading.
- **Documentation coverage for over-broad patterns.** `docs/SYNTAX-POLICY.md` (Rejected section) and `docs/COMPATIBILITY.md` (output-policy matrix) now document the option-less over-broad-pattern rejection (`*`, `||`, `^`, `@@*` with no options), matching the code, README and tests.
- **Version-marker audit.** Re-checked the builder-version markers: README, this changelog and `config.BUILDER_VERSION` all agree on `7.6.0`; no stale "current builder" tag remains on an older release.

### Changed (earlier maintenance pass)
- **`.github/workflows/update.yml`**: the commit/push step and the failed-build outcomes step call `scripts/publish.sh`; `chmod +x` now includes it; the concurrency comment no longer claims the group prevents all push races.
- **`scripts/report.py`**: `DEFAULT_SOURCE_QUALITY` is imported at module level with the other `config` imports instead of inside `evaluate_source_quality()`.
- **README**: pipeline diagram now matches the code (`validate.py` and `publish.sh` are separate workflow steps, not called by `merge.py`; `reports/history/` and `reports/source-outcomes.json` listed as outputs); Automation section documents `publish.sh`; Verification coverage and Local build updated.
- **`scripts/benchmark.py`** now measures both phases it reports: the existing per-line normalization benchmark plus a representative merge workload (normalize → deduplicate → deterministic sort), so a regression in the actual merge pipeline cannot pass CI while only normalization is measured. `--skip-merge` restores the previous normalization-only behaviour.
- **README** Local-build and Verification-coverage sections updated for the two-phase benchmark and the new regression coverage; the Reliability bullets on bounded includes and bounded concurrency now state that requests reserve global download budget before scheduling, and that rejected and partial transfers consume budget.
- **Extended-CSS naming aligned** across README, `docs/SYNTAX-POLICY.md` and `docs/COMPATIBILITY.md`: all three now list the same supported set — `:has()`, `:has-text()`, `:-abp-has()`, `:-abp-properties()`, `:-abp-contains()`, `:not()` and `:xpath()`.
- **Test module isolation:** `tests/test_v753.py` and `tests/test_v760.py` now load `merge.py` through `_helpers.load_script()` (fresh module instance), like `test_cleanup.py`, `test_merge.py` and `test_regressions.py`, instead of sharing one `import merge` object whose patched module globals could leak between tests if ordering or parallelism ever changes.
- **`canonical_url` imports** in tests now consistently come from `config` (where the function is defined); `tests/test_fetch.py` no longer relies on `fetch.py`'s re-export.
- **`fetch.collect_sources`** now creates a single `ThreadPoolExecutor` (sized to `parallelism`) and reuses it across all download waves of all batches, instead of constructing and tearing down a new pool per wave.
- **Shared test helpers:** new `_helpers.setup_config_root()` centralizes the repeated temp-dir + `sources.yaml`/`policies.yaml` + `patch(SOURCE_REGISTRY/POLICY_FILE)` + `load_config()` setup used across seven test files, and `tests/test_v760.py` now uses the existing `_helpers.setup_merge_root()` instead of hand-rolling the same module-global patching.
- The four copies of the normalization-idempotency check (`test_corpus.py`, `test_properties.py`, `test_v70.py`, `test_v754.py`) were consolidated into one parameterized test (`tests/test_idempotency.py`) covering every former input, including the curated corpus files.

### Removed (earlier maintenance pass)
- **`tests/test_policy.py`** — its three tests were exact duplicates of `test_merge.py::test_ubo_snippet_is_rejected`, `test_merge.py::test_unknown_ubo_option_rejected` and `test_merge.py::test_rewrite_requires_domain`; coverage is unchanged.
- Dead `import importlib.util` in `tests/test_regressions.py` (module loading is handled by `_helpers.load_script`).
- One stray blank line in `scripts/normalize.py` between the import block and `default_max_rule_length()` (three blank lines reduced to the PEP 8 standard two).

## [7.6.0]

Reconstructed from `tests/test_v760.py`, the `sources.yaml` and `policies.yaml` headers, `docs/REPORT-SCHEMA.md` and the README.
- **Source-quality gate**: `source_quality` section in `policies.yaml` (`enabled`, `min_lines`, `warn_rejection_rate`, `critical_rejection_rate`, `fail_on_critical`), `report.evaluate_source_quality()` and a `source_quality` block in the report. The effective rejection rate ignores comments, blanks and directives. Advisory by default; `fail_on_critical` can fail the build. Added to the report as an additive field, schema stays 5.
- **Failed-run source outcomes**: `scripts/health.py` and `reports/source-outcomes.json` record per-source fetch outcomes of every run (kept: last 120 runs), including failed ones, and feed `source_reputation` with one observation per source per UTC day. The first run seeds the file from retained successful reports. A build rejected after its report was written is corrected to `failed` in both the report and the outcome history.
- **AdGuard Annoyances disabled** in `sources.yaml` (2,712 of 2,743 lines hit `unknown-option`, one rule accepted under the strict-ABP profile).
- **`policies.yaml`** carries the v7.6.0 header, `version: 3`, and accepts the new `source_quality` top-level section.
- **LICENSE** reduced to standard MIT plus informational notices (earlier personal-use-only, no-distribution and no-commercial-use terms contradicted MIT and were removed).
- **README** rewritten with the DNS and Bandwidth Hero services under a "Related projects (not part of this repository)" note.

## [7.5.4]

Reconstructed from `tests/test_audit.py` and `tests/test_audit_followup.py` ("v7.5.4 audit fixes" and "audit follow-up"), `tests/test_v754.py` and code comments.
- **Trusted ABP features**: per-source `trusted_abp_features` flag in `sources.yaml` (real boolean required, part of the Build-ID). `#$#` snippets and `header=` / `addheader=` in any option position are rejected from untrusted sources as `abp-security-restricted-feature`; `custom-rules.txt` is always trusted.
- **Regex rules with options**: a rule whose option value ends in `/` (for example `header=etag:/.../`) is no longer mistaken for one large regex that skipped option validation.
- **Over-broad patterns** (`*`, `||`, `^`, `@@*`, ... with no options) are rejected as `overbroad-pattern`.
- **Lazy policy loading**: a malformed `policies.yaml` produces the clean `[ERROR] Configuration` message instead of a traceback at `import normalize`.
- **Strict configuration keys**: unknown keys in `sources.yaml` items and in each `policies.yaml` section are rejected, so a typo cannot silently relax a gate.
- **Download validation**: `HTTP/1.x` error status lines are detected (not just HTTP/2), look-alike tags such as `<header-ish>` are not rejected, whitespace-only files are `empty`, and a NUL byte beyond the first 64 KiB chunk marks a file as binary.
- **Validator hardening**: the `! Version:` hash suffix must match the Build-ID; invalid UTF-8 is reported as `[ENCODING]` instead of raising.
- **Syntax**: IDN `xn--` TLDs are accepted in domains; path patterns starting with `/` (for example `/ads/banner.gif`) are no longer run through the regex-envelope check; the parser got a single compiled cosmetic-marker alternation and a comment/directive fast path.
- `scripts/differential.py` rejects a `FILTER_ENGINE_CMD` without the `{input}` placeholder (exit status 2).

## [7.5.3]

Reconstructed from `tests/test_v753.py`.
- uBO procedural operators (`:style()`, `:remove()`, `:upward()`, `:matches-path()`, `:matches-css()`, ...) are rejected as `ubo-only-syntax` under `reject_ubo_procedural`; `:xpath()` is accepted in `#?#` rules.
- AdGuard cosmetic separators (`#%#`, `#@%#`, `#@$#`, `#$?#`, ...) are classified as cosmetic and rejected as `engine-specific-syntax` instead of leaking through as network rules.
- Lines starting with a single `#` are rejected as `hash-comment`; a leading BOM followed by a space is stripped.
- A source that failed in the previous report is not used as an anomaly baseline.
- **Staged publication**: `stage_output()` writes a temporary file and `commit_output()` replaces `filters.txt` only after the report and anomaly checks pass, so a rejected build keeps the last good list.
- Policy file validation: unknown top-level keys, and a `profile` or `version` mismatch, fail the build; the fallback `minimum_success_ratio` matches the shipped policy.

## [7.0]

Reconstructed from `tests/test_v70.py`, the "Strict V7 validation" workflow step and the policy modules.
- Strict ABP (`strict-abp`) profile with specific rejection reasons (`unknown-option`, `duplicate-option`, `invalid-option-value`).
- Deterministic output ordering by `(casefold, raw)` with a tie-breaker, and a stable Build-ID hash over the normalized rules.
