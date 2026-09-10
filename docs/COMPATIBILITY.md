# Compatibility Matrix

This document is the public compatibility contract for the strict-ABP output.

| Syntax family | Output | Notes |
|---|---|---|
| ABP network | Supported | Canonicalized and validated. |
| ABP exception | Supported | `@@` form validated with exception-specific options. |
| Element hiding | Supported | Domain list is normalized. |
| Extended CSS | Supported | ABP-style `#?#`; procedural uBO forms rejected. |
| uBO procedural | Rejected | Prevents engine-specific behavior. |
| AdGuard-only extensions | Rejected unless in policy | Strict profile is intentionally conservative. |
| Hosts format | Rejected | Not an ABP filter rule. |

See [`SYNTAX-POLICY.md`](SYNTAX-POLICY.md) for exact policy boundaries and examples.
