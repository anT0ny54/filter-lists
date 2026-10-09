# Compatibility Matrix

This document is the public compatibility contract for the strict-ABP output, and the single canonical copy of the compatibility matrix (other docs link here).

## Output policy

| Syntax family | Output | Notes |
|---|---|---|
| ABP network | Supported | Canonicalized and validated. |
| ABP exception | Supported | `@@` form validated with exception-specific options. |
| ABP request types/inverse types | Supported | Includes current documented type and inverse forms. |
| `domain=` / `sitekey=` | Supported | Values are strictly validated. |
| `csp=` | Supported | Control characters and empty values rejected. |
| `rewrite=` | Supported | Only ABP `abp-resource:` resources; domain requirement retained. |
| `header=` | Supported | ABP header matching grammar; exception rules rejected. |
| `addheader=` | Supported | Request/response injection; `x-*` / `set-cookie`; `document` targeting supported. |
| Element hiding | Supported | `##` and `#@#`. |
| ABP extended CSS | Supported | `#?#`, including `:has`, `:has-text`, `:-abp-properties`, `:not`, and `:xpath`. |
| ABP snippets | Supported | `#$#` with domain scope; security-sensitive feature. |
| Inline CSS styles | Supported | ABP documented safe property/value grammar. |
| `remove: true` | Supported | ABP remove action. |
| uBO procedural | Rejected | Prevents engine-specific behavior. |
| uBO extended exception | Rejected | `#?@#` remains outside strict ABP. |
| AdGuard-only extensions | Rejected | Strict profile intentionally excludes them. |
| Hosts format | Rejected | Not an ABP filter rule. |

ABP's current documentation describes the supported network options and the newer `header=`, `addheader=`, inline-style, remove, XPath, and snippet features.

## Engine support

| Feature | Filter-Lists strict ABP | Adblock Plus | uBlock Origin | AdGuard |
|---|:---:|:---:|:---:|:---:|
| Network filters | Yes | Yes | Yes | Yes |
| Exception filters | Yes | Yes | Yes | Yes |
| ABP network options | Yes | Yes | Yes | Yes |
| `header=` | Yes | Yes | Partial/Firefox | Varies |
| `addheader=` | Yes | Yes | Varies | Varies |
| Element hiding | Yes | Yes | Yes | Yes |
| ABP extended CSS | Yes | Yes | Partial/compatible subsets | Partial/compatible subsets |
| ABP snippets | Yes, policy-gated | Yes | No/varies | No/varies |
| ABP inline styles | Yes | Yes | Varies | Varies |
| ABP `remove: true` | Yes | Yes | Varies | Varies |
| uBO procedural `+js` | No | No | Yes | Partial/varies |
| AdGuard-only extensions | No | Varies | Varies | Yes |
| Hosts-file syntax | No | No | No | Varies |

The matrix describes the compiler's syntax/emission policy, not identical runtime behavior in every browser or engine.

See [`SYNTAX-POLICY.md`](SYNTAX-POLICY.md) for exact policy boundaries and examples.
