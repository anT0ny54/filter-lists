# Changelog

All notable changes to this project are documented here. Format is loosely
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Earlier history was not tracked in this file; entries begin at the current
release. See `docs/SYNTAX-POLICY.md`, `docs/REPORT-SCHEMA.md`, and
`docs/COMPATIBILITY.md` for the detailed, currently-in-force contracts that
the points below summarize.

## v7.5.3 — current

### Fixed
- `reject_ubo_procedural` only caught `+js(`; roughly 6,400 uBO/AdGuard-only
  cosmetic rules (`:style()`, `:upward()`, `:remove()`, `:matches-path()`,
  `:matches-css()`, `:xpath()`, ...) were leaking into the "strict ABP" list.
  They are now rejected, matching `docs/SYNTAX-POLICY.md`.
- AdGuard `#%#`, `#@%#`, `#@$#`, `#$?#`, `#@$?#` rules were classified as
  network filters and could be emitted as bogus rules; they are now rejected
  as `engine-specific-syntax`. Hosts-style `#comment` lines are rejected as
  `hash-comment`.
- A build rejected by the anomaly policy no longer overwrites `filters.txt`;
  output is staged and only published after the anomaly check passes.
- The global download budget is now enforced in deterministic submission order
  against the running total (it previously used a stale total in completion
  order, so parallel downloads could overshoot it).
- Anomaly detection ignores previously *failed* fetches as a baseline, removing
  false `bytes-change` warnings when a source recovered.
- A UTF-8 BOM followed by whitespace is now stripped correctly.
- `update.yml` no longer hard-codes the builder version/schema; it shares a
  concurrency group with `Keep-Alive.yml` (their crons collided on the 1st and
  15th) and no longer dumps the full report JSON into the log.
- `benchmark.py` resolves its default input relative to the repo, and
  `differential.py` enforces a per-fixture timeout.

### Policy file
- `policies.yaml` keys `version` and `profile` are now validated (a mismatch
  fails the build) instead of being ignored, and unknown top-level keys are
  rejected. The never-read `compatibility` list was removed (documented in
  `docs/COMPATIBILITY.md`).
- The `minimum_success_ratio` fallback is now 0.80 (was 0.50), matching the
  shipped policy, via a single `DEFAULT_MINIMUM_SUCCESS_RATIO` constant.

### Cleanup
- Removed dead code (`version_ok`, unreachable `#?@#` branch, redundant
  `size <= 0` / `not raw_options` / CR-LF checks, unused `limits` re-parse),
  the unused `pytest` requirement, and the no-op benchmark/differential steps
  from the publishing workflow.
- `include_urls` skips the regex on lines without `!#`; `validate.py` no longer
  keeps every rule in memory to check ordering.

