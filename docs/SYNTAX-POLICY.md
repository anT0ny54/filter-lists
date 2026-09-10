# Syntax Policy

## Profile

Filter-Lists emits a **strict ABP-compatible** subset intended to be safe for external-list consumers. The compiler deliberately rejects engine-specific syntax instead of silently passing it through.

### Accepted

- ABP network filters and exception filters (`@@`).
- ABP anchors, separators, and regular-expression filters.
- Supported ABP request-type and context options.
- `domain=`, `sitekey=`, `csp=`, and the allow-listed `rewrite=` resources.
- ABP element hiding (`##`) and supported extended CSS (`#?#`).
- Comments and directives are consumed as metadata/input and are not emitted as rules.

### Rejected

- uBlock Origin procedural filters such as `##+js(...)`.
- uBO-only extended exceptions such as `#@#` and `#?@#` where unsupported.
- AdGuard/uBO-only options not present in the policy allow-list.
- Duplicate or malformed options.
- Hosts-file lines (`0.0.0.0 host`).
- HTML/error pages masquerading as lists.
- Control characters, whitespace in network patterns, malformed regex envelopes, and over-limit rules.
- `rewrite=` unless its resource is allow-listed and the rule has the required domain-compatible form.

## Canonicalization contract

Normalization is deterministic and idempotent: `normalize_rule(normalize_rule(x)) == normalize_rule(x)` for accepted rules. Options are normalized to lowercase and sorted; cosmetic domain lists are deduplicated and deterministically sorted.

## Compatibility matrix

| Feature | Filter-Lists strict ABP | Adblock Plus | uBlock Origin | AdGuard |
|---|:---:|:---:|:---:|:---:|
| Network filters | Yes | Yes | Yes | Yes |
| Exception filters | Yes | Yes | Yes | Yes |
| ABP options | Allow-list only | Yes | Yes | Yes |
| Element hiding | Yes | Yes | Yes | Yes |
| ABP extended CSS | Yes | Yes | Yes | Yes |
| uBO procedural `+js` | No | No | Yes | Partial/varies |
| Engine-specific extensions | No | Varies | Yes | Yes |
| Hosts-file syntax | No | No | No | Varies |

The matrix describes the compiler's emission policy, not a claim that every downstream engine implements every feature identically.

## Compatibility rule of thumb

When upstream syntax is ambiguous, the compiler should **reject rather than guess**. This protects reproducibility and avoids emitting a rule whose behavior depends on a downstream engine extension.
