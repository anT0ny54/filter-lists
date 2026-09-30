# Changelog

All notable changes to this project are documented here. Format is loosely
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Earlier history was not tracked in this file; entries begin at the current
release. See `docs/SYNTAX-POLICY.md`, `docs/REPORT-SCHEMA.md`, and
`docs/COMPATIBILITY.md` for the detailed, currently-in-force contracts that
the points below summarize.

## v7.5.4 — current

### Fixed
- **Path-style network filters were rejected.** Any pattern starting with `/`
  was validated as a regex, so ordinary ABP filters such as `/ads/banner.gif`,
  `/adframe.` or `/banner/*/img^` (and their `@@` forms) were dropped as
  `invalid-network-rule`. A filter is now treated as a regex only when it both
  starts and ends with `/`; a lone `/` is still rejected.
- **IDN top-level domains were rejected** in `domain=` lists and cosmetic
  domain prefixes (`xn--p1ai`, ...). Punycode A-label TLDs are now accepted.
- **Publish workflow could fail on the first build.** `detect_anomalies` only
  set `enforced_failure` once a baseline existed, so `update.yml`'s
  `enforced_failure is False` assertion failed with no baseline or with
  detection disabled. The key is now always present.
- `validate_download` never detected `HTTP/1.1 404`-style error bodies (the
  status-line pattern used a single-character class); it now also anchors
  `<!doctype`/`<html`/`<head` on a word boundary and does the empty check
  before scanning the remainder of the file.
- `validate.py` no longer crashes with a traceback on invalid UTF-8 (reports
  `[ENCODING]`) and now checks that the `! Version:` hash suffix matches the
  `Build-ID`.
- `merge.py` staged `filters.txt` via `mkstemp`, leaving it mode `0600`; it is
  now `0644`.

### Configuration hardening
- Unknown keys inside `limits`, `history`, `source_health`,
  `anomaly_detection`, `sources.yaml` top level and each source entry are now
  rejected. Previously a typo (e.g. `requried: true`) was silently ignored and
  fell back to a looser default.

### Cleanup / performance
- Removed dead code: the unused `COMMENT_RE`, the `NETWORK_FORBIDDEN_RE` alias,
  the unreachable trailing `return False` in `valid_option`, the unused
  `write_output` wrapper, and an unused test import.
- `classify()` short-circuits `!` lines (comments are the most common
  non-rule line) without running the directive regex.

