#!/usr/bin/env python3
"""Small, dependency-free filter-list line classifier used by V6."""
from __future__ import annotations

import re
from dataclasses import dataclass

COMMENT_RE = re.compile(r"^\s*!")
DIRECTIVE_RE = re.compile(r"^\s*!#(?:if|else|endif|include|safari|end)\b", re.I)
HOSTS_RE = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)(?:\s+|$)")
HTML_RE = re.compile(r"^\s*(?:<!doctype\b|<html\b|<head\b|<body\b)", re.I)
COSMETIC_MARKERS = ("#?#", "#@#", "#$#", "##", "#?@#")


@dataclass(frozen=True)
class LineClassification:
    kind: str
    reason: str | None = None


def classify(line: str) -> LineClassification:
    value = line.strip().lstrip("\ufeff")
    if not value:
        return LineClassification("blank")
    if COMMENT_RE.match(value):
        return LineClassification("comment")
    if DIRECTIVE_RE.match(value):
        return LineClassification("directive")
    if HOSTS_RE.match(value):
        return LineClassification("invalid", "hosts-format")
    if HTML_RE.match(value):
        return LineClassification("invalid", "html-or-error-page")
    if any(marker in value for marker in COSMETIC_MARKERS):
        return LineClassification("cosmetic")
    return LineClassification("network")
