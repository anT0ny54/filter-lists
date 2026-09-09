#!/usr/bin/env python3
"""Canonicalization and strict ABP validation.

This is deliberately compatible with the working V5 implementation. Keep
behavior changes covered by regression tests before changing this module.
"""
from __future__ import annotations

import re
from collections import Counter

from parser import classify
from policy import (
    INVERSE_OPTIONS, REWRITE_RESOURCES, SIMPLE_OPTIONS, TYPE_OPTIONS,
    VALUE_OPTIONS,
)

MAX_RULE_LENGTH = 100_000
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
DOMAIN_RE = re.compile(
    r"^~?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
SITEKEY_RE = re.compile(r"^[A-Za-z0-9+/._-]+={0,2}$")


def split_options(rule: str) -> tuple[str, list[str]]:
    if "$" not in rule:
        return rule, []
    positions = []
    escaped = False
    for i, char in enumerate(rule):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "$" and not escaped:
            positions.append(i)
        escaped = False
    if not positions:
        return rule, []
    pattern_start = 2 if rule.startswith("@@/") else 0
    if rule.startswith("/", pattern_start) or rule.startswith("@@/", 0):
        last_slash = rule.rfind("/")
        if last_slash > positions[-1]:
            return rule, []
    pos = positions[-1]
    option_text = rule[pos + 1:]
    if not option_text:
        return rule, []
    options = [x.strip() for x in option_text.split(",")]
    if not options or any(not x for x in options):
        return rule, []
    return rule[:pos], options


def valid_domain_list(value: str) -> bool:
    parts = value.split("|")
    return bool(parts) and all(DOMAIN_RE.fullmatch(x) for x in parts)


def valid_sitekeys(value: str) -> bool:
    parts = value.split("|")
    return bool(parts) and all(x and SITEKEY_RE.fullmatch(x) for x in parts)


def valid_csp(value: str) -> bool:
    return bool(value.strip()) and not CONTROL_RE.search(value)


def valid_rewrite(value: str) -> bool:
    return value.startswith("abp-resource:") and value.removeprefix("abp-resource:") in REWRITE_RESOURCES


def valid_option(option: str, is_exception: bool) -> bool:
    if not option or CONTROL_RE.search(option):
        return False
    if "=" not in option:
        low = option.lower()
        if low in TYPE_OPTIONS or low in INVERSE_OPTIONS or low in SIMPLE_OPTIONS:
            if low in {"document", "elemhide", "generichide", "genericblock"} and not is_exception:
                return False
            if low in {"~document", "~elemhide"} and not is_exception:
                return False
            return True
        return False
    name, value = option.split("=", 1)
    name = name.strip().lower()
    if name not in VALUE_OPTIONS or not value:
        return False
    if name == "domain":
        return valid_domain_list(value)
    if name == "sitekey":
        return valid_sitekeys(value)
    if name == "csp":
        return valid_csp(value)
    if name == "rewrite":
        return valid_rewrite(value)
    return False


def normalize_network(rule: str) -> str | None:
    is_exception = rule.startswith("@@")
    pattern, options = split_options(rule.strip())
    if not pattern:
        return None
    pattern_body = pattern[2:] if pattern.startswith("@@") else pattern
    if not pattern_body or (rule.startswith("@@") and not pattern_body):
        return None
    if CONTROL_RE.search(pattern_body) or any(c in pattern_body for c in "\r\n"):
        return None
    if pattern_body.startswith("/"):
        if len(pattern_body) < 2 or not pattern_body.endswith("/") or pattern_body.count("/") < 2:
            return None
    if not options:
        return pattern
    normalized: list[str] = []
    for option in options:
        if not valid_option(option, is_exception):
            return None
        if "=" in option:
            name, value = option.split("=", 1)
            normalized.append(f"{name.lower()}={value}")
        elif option.startswith("~"):
            normalized.append("~" + option[1:].lower())
        else:
            normalized.append(option.lower())
    if len(normalized) != len(set(normalized)):
        return None
    if any(x.startswith("rewrite=") for x in normalized):
        if "third-party" in normalized:
            return None
        if not (pattern_body == "*" or pattern_body.startswith("||")):
            return None
        if not any(x.startswith("domain=") for x in normalized):
            return None
    return ("@@" if is_exception else "") + pattern_body + "$" + ",".join(sorted(normalized, key=str.casefold))


def normalize_cosmetic(rule: str) -> str | None:
    markers = ("#?#", "#@#", "#$#", "##")
    match = None
    for sep in markers:
        candidate = rule.find(sep)
        if candidate >= 0 and (match is None or candidate < match[0]):
            match = (candidate, sep)
    if match is None:
        return None
    pos, separator = match
    domains = rule[:pos].strip()
    body = rule[pos + len(separator):].strip()
    if separator == "#$#" or "#?@#" in rule:
        return None
    if not body or CONTROL_RE.search(body):
        return None
    if domains:
        items = [x.strip() for x in domains.split(",")]
        if any(not x or not DOMAIN_RE.fullmatch(x) for x in items):
            return None
        domains = ",".join(sorted(set(items), key=str.casefold))
    if "+js(" in body.lower() or ":has-text(" in body.lower():
        return None
    return f"{domains}{separator}{body}"


def normalize_rule(raw: str) -> str | None:
    line = raw.strip().lstrip("\ufeff")
    if not line or len(line) > MAX_RULE_LENGTH:
        return None
    classification = classify(line)
    if classification.kind in {"comment", "directive", "blank", "invalid"}:
        return None
    if any(sep in line for sep in ("#?#", "#@#", "#$#", "##")):
        return normalize_cosmetic(line)
    if "#?@#" in line:
        return None
    # A terminal, unescaped `$` on a normal network filter is an empty
    # option section, not a valid pattern. Regex filters are handled by
    # normalize_network/split_options and may legitimately contain `$`.
    if line.endswith("$") and not line.startswith(("/", "@@/")):
        return None
    return normalize_network(line)


def rejection_reason(raw: str) -> str:
    line = raw.strip().lstrip("\ufeff")
    if not line:
        return "blank"
    c = classify(line)
    if c.reason:
        return c.reason
    if c.kind in {"comment", "directive"}:
        return c.kind
    if len(line) > MAX_RULE_LENGTH:
        return "rule-too-long"
    if "#?@#" in line or "+js(" in line.lower() or ":has-text(" in line.lower():
        return "ubo-only-syntax"
    if "$" in line:
        pattern, options = split_options(line)
        if options:
            names = []
            for option in options:
                name = option.split("=", 1)[0].strip().lower()
                if name.startswith("~"):
                    name = name[1:]
                names.append(name)
                if "=" in option and name not in VALUE_OPTIONS:
                    return "unknown-option"
                if "=" not in option and name not in TYPE_OPTIONS and name not in INVERSE_OPTIONS and name not in SIMPLE_OPTIONS:
                    return "unknown-option"
                if not valid_option(option, line.startswith("@@")):
                    return "invalid-option-value" if "=" in option else "context-invalid-option"
            if len(names) != len(set(names)):
                return "duplicate-option"
        if normalize_network(line) is None:
            return "invalid-option-or-network-rule"
    if c.kind == "cosmetic":
        return "invalid-cosmetic-rule"
    return "invalid-network-rule"
