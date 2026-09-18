#!/usr/bin/env python3
"""Canonicalization and strict ABP validation.

Behavior here is the compatibility baseline for the whole build. Keep any
behavior change covered by regression tests before changing this module.
"""
from __future__ import annotations

import re
from config import load_policy_limits
from parser import classify
from policy import (
    INVERSE_OPTIONS, REWRITE_RESOURCES, SIMPLE_OPTIONS, TYPE_OPTIONS,
    VALUE_OPTIONS,
)

MAX_RULE_LENGTH = load_policy_limits()[0]
# Shared control-character gate. Same pattern is reused under a second name
# below (NETWORK_FORBIDDEN_RE) purely so call sites read as domain-specific;
# keep both names pointed at one compiled pattern instead of two copies.
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
NETWORK_FORBIDDEN_RE = CONTROL_RE
DOMAIN_RE = re.compile(
    r"^~?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
SITEKEY_RE = re.compile(r"^[A-Za-z0-9+/._-]+={0,2}$")
ASCII_WS_RE = re.compile(r"[\t\n\r\f\v ]")


def valid_regex_filter(pattern: str) -> bool:
    """Validate the ABP regex envelope without interpreting regex semantics.

    ABP regex filters are delimited by the first/last unescaped slash. The
    payload is intentionally not compiled with Python's regex engine because
    ABP engines use JavaScript-compatible regex semantics and Python would
    reject some valid ABP expressions.
    """
    if len(pattern) < 2 or not pattern.startswith("/"):
        return False
    escaped = False
    last = -1
    for i in range(1, len(pattern)):
        ch = pattern[i]
        if ch == "\\" and not escaped:
            escaped = True
            continue
        if ch == "/" and not escaped:
            last = i
        escaped = False
    if last != len(pattern) - 1 or last <= 1:
        return False
    payload = pattern[1:-1]
    return not NETWORK_FORBIDDEN_RE.search(payload) and not ASCII_WS_RE.search(payload)


def valid_network_pattern(pattern: str) -> bool:
    """Conservative ABP network-filter grammar gate."""
    if not pattern or NETWORK_FORBIDDEN_RE.search(pattern):
        return False
    if any(c in pattern for c in "\r\n"):
        return False
    if pattern.startswith("/"):
        return valid_regex_filter(pattern)
    if any(c.isspace() for c in pattern):
        return False
    # ABP allows an unescaped `|` only as a start/end anchor (`|` or `||` at
    # the beginning, `|` at the end). Escaped pipes are literal pattern data.
    unescaped_pipes: list[int] = []
    escaped = False
    for index, char in enumerate(pattern):
        if char == "|" and not escaped:
            unescaped_pipes.append(index)
        escaped = char == "\\" and not escaped
    allowed_pipes: set[int] = set()
    if pattern.startswith("||"):
        allowed_pipes.update((0, 1))
    elif pattern.startswith("|"):
        allowed_pipes.add(0)
    if pattern.endswith("|"):
        allowed_pipes.add(len(pattern) - 1)
    if any(index not in allowed_pipes for index in unescaped_pipes):
        return False
    # An exception marker is parsed outside this function. No bare @@ here.
    if pattern.startswith("@@"):
        return False
    # A caret is an ABP separator token; it may occur anywhere in a pattern.
    # Empty patterns and whitespace/control characters are the only universal
    # lexical exclusions at this stage.
    return True


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
    if rule.startswith("/", pattern_start):
        last_slash = rule.rfind("/")
        if last_slash > positions[-1]:
            return rule, []
    pos = positions[-1]
    option_text = rule[pos + 1:]
    if not option_text:
        return rule, []
    raw_options = option_text.split(",")
    # Whitespace around option tokens is not part of the canonical ABP option
    # grammar. CSP values may contain spaces, so whitespace checks are applied
    # to token boundaries here and to option names later.
    if not raw_options or any(not x or x != x.strip() for x in raw_options):
        return rule, []
    options = raw_options
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
    if not name or name != name.strip() or any(char.isspace() for char in name):
        return False
    name = name.lower()
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
    if not pattern_body:
        return None
    if not valid_network_pattern(pattern_body):
        return None
    if not options:
        return pattern
    normalized: list[str] = []
    for option in options:
        if not valid_option(option, is_exception):
            return None
        if "=" in option:
            name, value = option.split("=", 1)
            name = name.lower()
            normalized.append(f"{name}={value}")
        elif option.startswith("~"):
            normalized.append("~" + option[1:].lower())
        else:
            normalized.append(option.lower())
    if len(normalized) != len(set(normalized)):
        return None
    if any(x.startswith("rewrite=") for x in normalized):
        if "third-party" in normalized or "~third-party" in normalized:
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
    if separator == "#$#":
        return None
    if not body or CONTROL_RE.search(body):
        return None
    if domains:
        items = [x.strip() for x in domains.split(",")]
        if any(not x or not DOMAIN_RE.fullmatch(x) for x in items):
            return None
        domains = ",".join(sorted(set(items), key=lambda x: (x.casefold(), x)))
    # Extended CSS is deliberately domain-scoped in this strict profile.
    if separator == "#?#" and not domains:
        return None
    body_lower = body.lower()
    # ABP documents :has-text() as an alias of :-abp-contains(). Accept it
    # only in #?# extended-CSS rules; it is not a uBO-only construct.
    if ":has-text(" in body_lower and separator != "#?#":
        return None
    if "+js(" in body_lower:
        return None
    return f"{domains}{separator}{body}"


def normalize_rule(raw: str, *, max_rule_length: int | None = None) -> str | None:
    line = raw.strip().lstrip("\ufeff")
    limit = MAX_RULE_LENGTH if max_rule_length is None else max_rule_length
    if not line or len(line) > limit:
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


def rejection_reason(raw: str, *, max_rule_length: int | None = None) -> str:
    line = raw.strip().lstrip("\ufeff")
    if not line:
        return "blank"
    c = classify(line)
    if c.reason:
        return c.reason
    if c.kind in {"comment", "directive"}:
        return c.kind
    limit = MAX_RULE_LENGTH if max_rule_length is None else max_rule_length
    if len(line) > limit:
        return "rule-too-long"
    if "#?@#" in line or "+js(" in line.lower():
        return "ubo-only-syntax"
    if c.kind == "cosmetic":
        if "#?#" in line:
            cosmetic_match = re.search(r"#\?#", line)
            if cosmetic_match and not line[:cosmetic_match.start()].strip():
                return "extended-css-domain-required"
        if ":has-text(" in line.lower() and "#?#" not in line:
            return "extended-css-selector-requires-#?#"
        return "invalid-cosmetic-rule"
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
    return "invalid-network-rule"
