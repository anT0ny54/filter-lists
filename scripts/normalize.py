#!/usr/bin/env python3
"""Canonicalization and strict ABP validation.

Behavior here is the compatibility baseline for the whole build. Keep any
behavior change covered by regression tests before changing this module.
"""
from __future__ import annotations

import re
from config import load_policy_limits, load_rule_policy
from parser import COSMETIC_MARKERS, classify
from policy import (
    INVERSE_OPTIONS, REWRITE_RESOURCES, SIMPLE_OPTIONS, TYPE_OPTIONS,
    VALUE_OPTIONS,
)

MAX_RULE_LENGTH = load_policy_limits()[0]
# Shared control-character gate (network patterns, options, cosmetic bodies).
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Regex filters may contain ordinary whitespace, but raw control characters
# (including TAB) are never valid in the ABP regex payload.
REGEX_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# The TLD may be alphabetic or an IDN A-label (`xn--p1ai`); the latter was
# previously rejected, silently dropping rules for internationalized TLDs.
DOMAIN_RE = re.compile(
    r"^~?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{1,59}[A-Za-z0-9])$"
)
SITEKEY_RE = re.compile(r"^[A-Za-z0-9+/._-]+={0,2}$")
# uBlock Origin / AdGuard procedural and style-injection operators. They are not
# ABP syntax, so `reject_ubo_procedural` must cover them and not just `+js(`.
UBO_PROCEDURAL_RE = re.compile(
    r"\+js\(|:(?:style|remove|upward|nth-ancestor|matches-css(?:-before|-after)?"
    r"|matches-path|matches-media|matches-attr|matches-property|min-text-length"
    r"|watch-attr|others|remove-attr|remove-class)\(",
    re.I,
)
ALLOWED_COSMETIC_SEPARATORS = frozenset({"##", "#@#", "#?#", "#$#"})

ABP_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
ABP_ADDHEADER_NAME_RE = re.compile(r"^(?:x-[!#$%&'*+.^_`|~0-9A-Za-z-]+|set-cookie)$", re.I)
ABP_PRINTABLE_ASCII_RE = re.compile(r"^[\x20-\x7e]*$")
ABP_CSS_VALUE_RE = re.compile(
    r"^(?:#[0-9a-f]{3,8}|[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?"
    r"(?:cm|mm|q|in|pc|pt|px|em|ex|ch|rem|lh|rlh|vw|vh|vmin|vmax|vb|vi|"
    r"svw|svh|lvw|lvh|dvw|dvh|%|fr)?|inherit|initial|none|revert|revert-layer|"
    r"unset|currentcolor|absolute|all|auto|block|both|clip|collapse|contain|"
    r"dashed|default|dotted|double|element|fit-content|fixed|flex|flow-root|"
    r"flow|grid|groove|hidden|inline-block|inline-flex|inline-grid|inline-table|"
    r"inline|inset|left|list-item|max-content|min-content|outset|pointer|relative|"
    r"ridge|right|ruby|scroll|solid|static|sticky|table-row|table|text|thin|"
    r"transparent|true|visible)$", re.I
)


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
    return not REGEX_CONTROL_RE.search(payload)


def valid_network_pattern(pattern: str) -> bool:
    """Conservative ABP network-filter grammar gate."""
    if not pattern or CONTROL_RE.search(pattern):
        return False
    # ABP treats a filter as a regular expression only when it both starts and
    # ends with `/`. A leading `/` alone is an ordinary path pattern such as
    # `/ads/banner.gif` or `/adframe.`; those were previously run through the
    # regex-envelope check and wrongly rejected. A lone `/` is too broad to be
    # a meaningful rule and stays rejected.
    if pattern.startswith("/"):
        if pattern.endswith("/"):
            return valid_regex_filter(pattern)
        if pattern == "/":
            return False
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
    options = option_text.split(",")
    # Whitespace around option tokens is not part of the canonical ABP option
    # grammar. CSP values may contain spaces, so whitespace checks are applied
    # to token boundaries here and to option names later.
    if any(not x or x != x.strip() for x in options):
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


def valid_header(value: str) -> bool:
    if not value or CONTROL_RE.search(value):
        return False
    if "=" in value:
        name, content = value.split("=", 1)
    else:
        name, content = value, ""
    if not ABP_HEADER_NAME_RE.fullmatch(name):
        return False
    if content.startswith("/") and content.endswith("/") and len(content) > 1:
        # ABP reserves regex header-content syntax for future use.
        return False
    # A literal comma must be represented by ABP's \x2c escape.
    if "," in content:
        return False
    return not any(ord(ch) < 0x20 or ord(ch) > 0x7e for ch in content)


def valid_addheader(value: str) -> bool:
    parts = value.split(":", 2)
    if len(parts) == 2:
        header, content = parts
        kind = "response"
    elif len(parts) == 3:
        kind, header, content = parts
    else:
        return False
    if kind not in {"request", "response"} or not ABP_ADDHEADER_NAME_RE.fullmatch(header):
        return False
    if not ABP_PRINTABLE_ASCII_RE.fullmatch(content):
        return False
    return True


def valid_inline_style(body: str) -> bool:
    # ABP inline styles are a selector followed by a single declaration block.
    # The property/value grammar is intentionally security-restricted to ABP's
    # documented allowlist; custom properties and arbitrary CSS are rejected.
    if "{" not in body or not body.endswith("}"):
        return False
    selector, declarations = body.rsplit("{", 1)
    if not selector.strip() or not declarations[:-1].strip():
        return False
    declarations = declarations[:-1].strip()
    for declaration in declarations.split(";"):
        declaration = declaration.strip()
        if not declaration:
            continue
        if ":" not in declaration:
            return False
        name, value = declaration.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name or name.startswith("--") or not re.fullmatch(r"[A-Za-z_-][A-Za-z0-9_-]*", name):
            return False
        if name.lower() == "remove":
            if value.lower() != "true":
                return False
            continue
        if not ABP_CSS_VALUE_RE.fullmatch(value):
            return False
    return True


def has_inline_style(body: str) -> bool:
    return "{" in body and body.rstrip().endswith("}")


def valid_option(
    option: str,
    is_exception: bool,
    rule_policy: dict[str, bool] | None = None,
) -> bool:
    policy = load_rule_policy() if rule_policy is None else rule_policy
    if not option or CONTROL_RE.search(option):
        return False
    if "=" not in option:
        low = option.lower()
        if low in TYPE_OPTIONS or low in INVERSE_OPTIONS or low in SIMPLE_OPTIONS:
            if low in {"document", "elemhide", "generichide", "genericblock"} and not is_exception:
                return False
            return True
        return not policy["reject_unknown_options"]
    name, value = option.split("=", 1)
    if not name or name != name.strip() or any(char.isspace() for char in name):
        return False
    name = name.lower()
    if not value:
        return False
    if name == "addheader" and is_exception:
        return False
    if name == "header" and is_exception:
        return False
    if name == "header" and not policy["allow_abp_header"]:
        return False
    if name == "addheader" and not policy["allow_abp_addheader"]:
        return False
    if name not in VALUE_OPTIONS:
        return not policy["reject_unknown_options"]
    if name == "domain":
        return valid_domain_list(value)
    if name == "sitekey":
        return valid_sitekeys(value)
    if name == "csp":
        return valid_csp(value)
    if name == "rewrite":
        return valid_rewrite(value)
    if name == "header":
        return valid_header(value)
    if name == "addheader":
        return valid_addheader(value)
    return False


def normalize_network(rule: str, rule_policy: dict[str, bool] | None = None) -> str | None:
    policy = load_rule_policy() if rule_policy is None else rule_policy
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
    has_addheader = any(option.split("=", 1)[0].casefold() == "addheader" for option in options)
    for option in options:
        option_name = option.split("=", 1)[0].casefold()
        # ABP explicitly permits $addheader rules to target top-level
        # documents with the `document` type even though ordinary `$document`
        # is exception-only. This is a narrow, documented exception to the
        # normal context rule.
        option_valid = (
            option_name == "document" and has_addheader and not is_exception
        ) or valid_option(option, is_exception, policy)
        if not option_valid:
            return None
        if "=" in option:
            name, value = option.split("=", 1)
            name = name.lower()
            if name == "domain":
                value = "|".join(item.lower() for item in value.split("|"))
            normalized.append(f"{name}={value}")
        elif option.startswith("~"):
            normalized.append("~" + option[1:].lower())
        else:
            normalized.append(option.lower())
    # `foo` and `~foo` are opposite forms of the same option name and cannot
    # be combined. Keep this canonical name check aligned with rejection_reason().
    option_names = [option.split("=", 1)[0].lstrip("~").lower() for option in normalized]
    if policy["reject_duplicate_options"] and len(option_names) != len(set(option_names)):
        return None
    if any(x.startswith("rewrite=") for x in normalized):
        if "third-party" in normalized or "~third-party" in normalized:
            return None
        if not (pattern_body == "*" or pattern_body.startswith("||")):
            return None
        if policy["require_domain_for_rewrite"] and not any(
            x.startswith("domain=") for x in normalized
        ):
            return None
    return ("@@" if is_exception else "") + pattern_body + "$" + ",".join(sorted(normalized, key=str.casefold))


def normalize_cosmetic(rule: str, rule_policy: dict[str, bool] | None = None) -> str | None:
    policy = load_rule_policy() if rule_policy is None else rule_policy
    match = None
    for sep in COSMETIC_MARKERS:
        candidate = rule.find(sep)
        if candidate >= 0 and (match is None or candidate < match[0]):
            match = (candidate, sep)
    if match is None:
        return None
    pos, separator = match
    domains = rule[:pos].strip()
    body = rule[pos + len(separator):].strip()
    allowed_separators = ALLOWED_COSMETIC_SEPARATORS
    if separator == "#?@#" and not policy["reject_ubo_extended_exceptions"]:
        allowed_separators = allowed_separators | {"#?@#"}
    if separator not in allowed_separators:
        return None
    if separator == "#?#" and not policy["allow_extended_css"]:
        return None
    if separator == "#?@#" and policy["reject_ubo_extended_exceptions"]:
        return None
    if separator == "#$#":
        if not policy["allow_abp_snippets"] or not domains:
            return None
    if not body or CONTROL_RE.search(body):
        return None
    if has_inline_style(body):
        if not policy["allow_abp_inline_styles"] or not valid_inline_style(body):
            return None
    if "{remove:" in body.replace(" ", "").lower() or "{remove :" in body.replace(" ", "").lower():
        if not policy["allow_abp_remove_action"]:
            return None
    if domains:
        items = [x.strip().lower() for x in domains.split(",")]
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
    if policy["reject_ubo_procedural"] and UBO_PROCEDURAL_RE.search(body):
        return None
    # :xpath() is an ABP extended-CSS selector (3.13+), not uBO syntax.
    if separator != "#?#" and re.search(r":xpath\(", body, re.I):
        return None
    return f"{domains}{separator}{body}"


def normalize_rule(raw: str, *, max_rule_length: int | None = None, trusted_abp_features: bool = True) -> str | None:
    line = raw.lstrip("\ufeff").strip()
    limit = MAX_RULE_LENGTH if max_rule_length is None else max_rule_length
    if not line or len(line) > limit:
        return None
    policy = load_rule_policy()
    if not trusted_abp_features and ("#$#" in line or re.search(r"\$(?:header|addheader)=", line, re.I)):
        return None
    classification = classify(line)
    if classification.kind == "invalid":
        if classification.reason == "hosts-format" and not policy["reject_hosts_format"]:
            return line
        if classification.reason == "html-or-error-page" and not policy["reject_html_error_pages"]:
            return line
    if classification.kind in {"comment", "directive", "blank", "invalid"}:
        return None
    if classification.kind == "network" and not policy["allow_network_filters"]:
        return None
    if classification.kind == "cosmetic" and not policy["allow_abp_cosmetic"]:
        return None
    if classification.kind == "cosmetic":
        return normalize_cosmetic(line, policy)
    # A terminal, unescaped `$` on a normal network filter is an empty
    # option section, not a valid pattern. Regex filters are handled by
    # normalize_network/split_options and may legitimately contain `$`.
    if line.endswith("$") and not line.startswith(("/", "@@/")):
        return None
    return normalize_network(line, policy)


def rejection_reason(raw: str, *, max_rule_length: int | None = None, trusted_abp_features: bool = True) -> str:
    line = raw.lstrip("\ufeff").strip()
    if not line:
        return "blank"
    policy = load_rule_policy()
    if not trusted_abp_features and ("#$#" in line or re.search(r"\$(?:header|addheader)=", line, re.I)):
        return "abp-security-restricted-feature"
    c = classify(line)
    if c.reason == "hosts-format" and not policy["reject_hosts_format"]:
        return "hosts-format-allowed"
    if c.reason == "html-or-error-page" and not policy["reject_html_error_pages"]:
        return "html-or-error-page-allowed"
    if c.reason:
        return c.reason
    if c.kind in {"comment", "directive"}:
        return c.kind
    limit = MAX_RULE_LENGTH if max_rule_length is None else max_rule_length
    if len(line) > limit:
        return "rule-too-long"
    if c.kind == "network" and not policy["allow_network_filters"]:
        return "network-filters-disabled"
    if c.kind == "cosmetic" and not policy["allow_abp_cosmetic"]:
        return "cosmetic-filters-disabled"
    if "#?#" in line and not policy["allow_extended_css"]:
        return "extended-css-disabled"
    if "#?@#" in line and policy["reject_ubo_extended_exceptions"]:
        return "ubo-only-syntax"
    if policy["reject_ubo_procedural"] and UBO_PROCEDURAL_RE.search(line):
        return "ubo-only-syntax"
    if c.kind == "cosmetic":
        engine_only = [sep for sep in COSMETIC_MARKERS if sep not in ALLOWED_COSMETIC_SEPARATORS and sep in line]
        if engine_only:
            return "engine-specific-syntax"
        if "#$#" in line:
            snippet_match = re.search(r"#\$#", line)
            if snippet_match and not line[:snippet_match.start()].strip():
                return "snippet-domain-required"
            if not policy["allow_abp_snippets"]:
                return "abp-snippets-disabled"
        if "#?#" in line:
            cosmetic_match = re.search(r"#\?#", line)
            if cosmetic_match and not line[:cosmetic_match.start()].strip():
                return "extended-css-domain-required"
        if ":has-text(" in line.lower() and "#?#" not in line:
            return "extended-css-selector-requires-#?#"
        if re.search(r":xpath\(", line, re.I) and "#?#" not in line:
            return "extended-css-selector-requires-#?#"
        return "invalid-cosmetic-rule"
    if "$" in line:
        _, options = split_options(line)
        if options:
            names = []
            for option in options:
                name = option.split("=", 1)[0].strip().lower()
                if name.startswith("~"):
                    name = name[1:]
                names.append(name)
                if (
                    "=" in option
                    and name not in VALUE_OPTIONS
                    and policy["reject_unknown_options"]
                ):
                    return "unknown-option"
                if (
                    "=" not in option
                    and name not in TYPE_OPTIONS
                    and name not in INVERSE_OPTIONS
                    and name not in SIMPLE_OPTIONS
                    and policy["reject_unknown_options"]
                ):
                    return "unknown-option"
                if not valid_option(option, line.startswith("@@"), policy):
                    return "invalid-option-value" if "=" in option else "context-invalid-option"
            if policy["reject_duplicate_options"] and len(names) != len(set(names)):
                return "duplicate-option"
        if normalize_network(line) is None:
            return "invalid-option-or-network-rule"
    return "invalid-network-rule"
