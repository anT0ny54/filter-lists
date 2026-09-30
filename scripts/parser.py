#!/usr/bin/env python3
"""Small, dependency-free filter-list line classifier."""
from __future__ import annotations

import re
from dataclasses import dataclass

DIRECTIVE_RE = re.compile(r"^\s*!#(?:if|else|endif|include|safari|end)\b", re.I)
HOSTS_RE = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)(?:\s+|$)")
HTML_RE = re.compile(r"^\s*(?:<!doctype\b|<html\b|<head\b|<body\b)", re.I)
# Includes engine-specific separators (AdGuard `#%#`/`#$?#`, `#@$#`, ...) so they
# are classified as cosmetic and then rejected by normalization, instead of
# leaking through as bogus network filters.
COSMETIC_MARKERS = (
    "#?#", "#@#", "#$#", "##", "#?@#",
    "#%#", "#@%#", "#@$#", "#$?#", "#@$?#",
)


@dataclass(frozen=True)
class LineClassification:
    kind: str
    reason: str | None = None


def classify(line: str) -> LineClassification:
    value = line.lstrip("\ufeff").strip()
    if not value:
        return LineClassification("blank")
    # Directives (`!#include`, `!#if`, ...) start with the same `!` prefix as
    # comments, so the directive check must run first or it is unreachable
    # and every directive line is silently misreported as a comment. The value
    # is already stripped, so only a leading `!#` can be a directive; comments
    # (the most common non-rule line) skip the regex entirely.
    if value[0] == "!":
        if value.startswith("!#") and DIRECTIVE_RE.match(value):
            return LineClassification("directive")
        return LineClassification("comment")
    if HOSTS_RE.match(value):
        return LineClassification("invalid", "hosts-format")
    if HTML_RE.match(value):
        return LineClassification("invalid", "html-or-error-page")
    if any(marker in value for marker in COSMETIC_MARKERS):
        return LineClassification("cosmetic")
    # A leading single `#` is a hosts-style comment (e.g. `#domain-note`), not
    # an ABP network pattern; without this it slipped through as a "rule".
    if value.startswith("#"):
        return LineClassification("invalid", "hash-comment")
    return LineClassification("network")
