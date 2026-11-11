# Syntax Policy

## Profile

Filter-Lists emits **strict Adblock Plus syntax**, including the current ABP network and content features documented by Adblock Plus. Engine-specific uBlock Origin and AdGuard extensions remain rejected.

The implementation covers the current ABP filter language documented by ABP, including header matching, header injection, snippets and snippet exceptions, extended CSS, inline CSS styles, and the remove action.

### Accepted network features

- Network blocking and exception filters (`@@`).
- ABP request types: `script`, `image`, `stylesheet`, `object`, `xmlhttprequest`, `subdocument`, `ping`, `websocket`, `webrtc`, `document`, `elemhide`, `generichide`, `genericblock`, `popup`, `font`, `media`, `other`, and `webbundle`.
- ABP inverse types supported by the documented grammar, including `~document`, `~elemhide`, and `~other`.
- `third-party` / `~third-party` and `match-case`.
- `domain=`, `sitekey=`, `csp=`, and ABP `rewrite=` resources.
- ABP `header=` response-header matching, with strict header-name/content validation.
- ABP `addheader=` request/response header injection, including its `document` targeting exception. ABP's six refused names (`x-content-type-options`, `x-download-options`, `x-frame-options`, `x-permitted-cross-domain-policies`, `x-powered-by`, and `x-xss-protection`) are rejected even with the `x-` prefix.
- ABP regular-expression filters, anchors, separators, and canonicalization.

ABP documents `document`, `elemhide`, `generichide`, and `genericblock` as exception-only in ordinary filters. The `addheader` feature is the narrow documented exception that can combine with `document` while remaining a blocking rule.

### Accepted content features

- Element hiding: `##`.
- Element hiding exceptions: `#@#`.
- Extended CSS: `#?#`, including ABP `:has()`, `:has-text()`, `:-abp-has()`, `:-abp-properties()`, `:-abp-contains()`, `:not()`, and `:xpath()`. The ABP-specific forms (`:has-text()`, `:-abp-*()`, `:xpath()`) are accepted only with `#?#`; plain `:has()` is native CSS and is accepted on `##` as well.
- ABP snippets: `#$#`, with a required domain scope; execution is security-sensitive.
- ABP snippet exceptions: `#@$#`, with an optional domain scope (no domain means global); these disable a matching snippet and do not execute code.
- ABP inline CSS declarations on `##` / `#?#` selectors only (a `{...}` block on `#@#`, `#$#`, or `#@$#` is rejected), restricted to ABP's documented safe property/value grammar.
- ABP `remove: true;` action, gated by the `allow_abp_remove_action` policy switch (rejected in any declaration position when the switch is off).

ABP documents snippets as JavaScript snippet commands and restricts them to custom filters or vetted ABP lists for security. The project therefore enables snippet execution only for sources trusted for ABP security-sensitive features. Snippet exceptions (`#@$#`) only disable a matching command and do not require a privileged source or a domain scope.

### Rejected

- uBlock Origin procedural filters such as `##+js(...)`.
- ABP extended pseudo-classes (`:has-text()`, `:-abp-*()`, `:xpath()`) outside `#?#`.
- Inline `{...}` style blocks on `#@#`, `#$#`, and `#@$#` rules.
- uBO-only procedural/style operators such as `:style()`, `:remove()`, `:upward()`, and `:matches-css()`.
- AdGuard-only cosmetic separators (`#%#`, `#@%#`, `#$?#`, `#@$?#`).
- uBO-only extended-CSS exception form `#?@#`.
- Non-ABP network options such as uBO `removeparam`, redirect/scriptlet options, and unknown options.
- Hosts-file lines (`0.0.0.0 host`).
- HTML/error pages masquerading as lists.
- Duplicate or malformed options, invalid header values, unsafe inline-style values, control characters, malformed regex envelopes, and over-limit rules.
- Option-less patterns with no literal content (`*`, `||`, `^`, `@@*`, ...), which would match every request. Scoped forms such as `*$script,domain=example.com` remain valid.

### Directives

`!#if`, `!#else`, `!#endif`, `!#include`, `!#safari` and `!#end` lines are classified as directives and never emitted. Conditionals are not evaluated: the rules inside `!#if` blocks are processed unconditionally. `!#include` targets are fetched (bounded) and their rules merged.

### Canonicalization contract

Lines are first trimmed of surrounding whitespace and a leading BOM (also when whitespace follows it). Normalization is deterministic and idempotent: `normalize_rule(normalize_rule(x)) == normalize_rule(x)` for accepted rules. Options are normalized to lowercase and sorted; cosmetic domain lists are deduplicated and deterministically sorted.

### Compatibility matrix

The compatibility matrix lives in [`COMPATIBILITY.md`](COMPATIBILITY.md), the single canonical copy.

### Compatibility rule

When upstream syntax is ambiguous, the compiler should **reject rather than guess**. For a documented ABP feature, implement its grammar and its context/security restrictions rather than accepting a looser approximation.
