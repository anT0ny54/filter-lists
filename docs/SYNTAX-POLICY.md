# Syntax Policy

## Profile

Filter-Lists emits **strict Adblock Plus syntax**, including the current ABP network and content features documented by Adblock Plus. Engine-specific uBlock Origin and AdGuard extensions remain rejected.

The implementation covers the current ABP filter language documented by ABP, including header matching, header injection, snippets, extended CSS, inline CSS styles, and the remove action.

### Accepted network features

- Network blocking and exception filters (`@@`).
- ABP request types: `script`, `image`, `stylesheet`, `object`, `xmlhttprequest`, `subdocument`, `ping`, `websocket`, `webrtc`, `document`, `elemhide`, `generichide`, `genericblock`, `popup`, `font`, `media`, and `other`.
- ABP inverse types supported by the documented grammar, including `~document`, `~elemhide`, and `~other`.
- `third-party` / `~third-party` and `match-case`.
- `domain=`, `sitekey=`, `csp=`, and ABP `rewrite=` resources.
- ABP `header=` response-header matching, with strict header-name/content validation.
- ABP `addheader=` request/response header injection, including its `document` targeting exception.
- ABP regular-expression filters, anchors, separators, and canonicalization.

ABP documents `document`, `elemhide`, `generichide`, and `genericblock` as exception-only in ordinary filters. The `addheader` feature is the narrow documented exception that can combine with `document` while remaining a blocking rule.

### Accepted content features

- Element hiding: `##`.
- Element hiding exceptions: `#@#`.
- Extended CSS: `#?#`, including ABP `:-abp-has()`, `:-abp-contains()` / `:has-text()`, `:-abp-properties()`, `:not()`, and `:xpath()`.
- ABP snippets: `#$#`, with a required domain scope.
- ABP inline CSS declarations on `##` / `#?#` selectors, restricted to ABP's documented safe property/value grammar.
- ABP `remove: true;` action.

ABP documents snippets as JavaScript snippet commands and restricts them to custom filters or vetted ABP lists for security. The syntax is therefore implemented, while the project should only enable snippet/header/addheader features for sources that are trusted for those ABP security-sensitive features.

### Rejected

- uBlock Origin procedural filters such as `##+js(...)`.
- uBO-only procedural/style operators such as `:style()`, `:remove()`, `:upward()`, and `:matches-css()`.
- AdGuard-only cosmetic separators (`#%#`, `#@%#`, `#@$#`, `#$?#`, `#@$?#`).
- uBO-only extended-CSS exception form `#?@#`.
- Non-ABP network options such as uBO `removeparam`, redirect/scriptlet options, and unknown options.
- Hosts-file lines (`0.0.0.0 host`).
- HTML/error pages masquerading as lists.
- Duplicate or malformed options, invalid header values, unsafe inline-style values, control characters, malformed regex envelopes, and over-limit rules.

### Canonicalization contract

Normalization is deterministic and idempotent: `normalize_rule(normalize_rule(x)) == normalize_rule(x)` for accepted rules. Options are normalized to lowercase and sorted; cosmetic domain lists are deduplicated and deterministically sorted.

### Compatibility matrix

The compatibility matrix lives in [`COMPATIBILITY.md`](COMPATIBILITY.md), the single canonical copy.

### Compatibility rule

When upstream syntax is ambiguous, the compiler should **reject rather than guess**. For a documented ABP feature, implement its grammar and its context/security restrictions rather than accepting a looser approximation.
