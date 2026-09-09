#!/usr/bin/env python3
"""Build a strict, de-duplicated Adblock Plus filter list.

The output uses an ABP external-list-safe profile:
- network filters and ABP-supported options only
- ABP element hiding / extended element hiding
- no uBlock/AdGuard-only syntax
- no ABP security-restricted header/addheader/snippet filters
- deterministic normalization and ordering
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources.txt"
CUSTOM_RULES = ROOT / "custom-rules.txt"
OUTPUT = ROOT / "filters.txt"

DOWNLOAD_TIMEOUT = 90
INCLUDE_TIMEOUT = 60
TOTAL_TIMEOUT = 3300
MAX_INCLUDE_DEPTH = 5
CURL_RETRIES = 3
WORKERS = min(16, max(4, (os.cpu_count() or 2) * 2))
MAX_RULE_LENGTH = 100_000

COMMENT_RE = re.compile(r"^\s*!")
DIRECTIVE_RE = re.compile(r"^\s*!#(?:if|else|endif|include|safari|end)\b", re.I)
HOSTS_RE = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)(?:\s+|$)")
HTML_RE = re.compile(r"^\s*(?:<!doctype\b|<html\b|<head\b|<body\b)", re.I)

# ABP external-list-safe network options. Keep this list deliberately closed.
TYPE_OPTIONS = {
    "script", "image", "stylesheet", "object", "xmlhttprequest",
    "subdocument", "ping", "websocket", "webrtc", "document",
    "elemhide", "generichide", "genericblock", "popup", "font",
    "media", "other", "match-case",
}
INVERSE_OPTIONS = {f"~{x}" for x in {
    "script", "image", "stylesheet", "object", "xmlhttprequest",
    "subdocument", "ping", "websocket", "webrtc", "document",
    "elemhide", "other",
}}
SIMPLE_OPTIONS = {"third-party", "~third-party", "match-case"}
VALUE_OPTIONS = {"domain", "sitekey", "csp", "rewrite"}

# ABP docs define these content-filter separators. #?@# is uBO syntax and is
# intentionally rejected in this strict ABP profile.
COSMETIC_SEPARATORS = ("#?#", "#@#", "#$#", "##")
ABP_COSMETIC_SEPARATORS = ("#?#", "#@#", "##")
DOMAIN_RE = re.compile(
    r"^~?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
SITEKEY_RE = re.compile(r"^[A-Za-z0-9+/._-]+={0,2}$")
HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

REWRITE_RESOURCES = {
    "blank-text", "blank-css", "blank-js", "blank-html",
    "blank-mp3", "blank-mp4", "1x1-transparent-gif",
    "2x2-transparent-png", "3x2-transparent-png", "32x32-transparent-png",
}

def log(message: str) -> None:
    print(message, flush=True)

def valid_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        return p.scheme in {"http", "https"} and bool(p.netloc) and not any(c.isspace() for c in url)
    except ValueError:
        return False

def read_sources(path: Path) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        value = raw.strip()
        if not value or value.startswith("#") or not valid_url(value):
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

def download(url: str, output: Path, timeout: int) -> tuple[bool, str]:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location", "--compressed",
        "--retry", str(CURL_RETRIES), "--retry-delay", "2",
        "--connect-timeout", "20", "--max-time", str(timeout),
        "--user-agent", "filter-lists-builder/4.0", "--output", str(output), url,
    ]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout + 30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        output.unlink(missing_ok=True)
        return False, str(exc)
    if proc.returncode:
        output.unlink(missing_ok=True)
        return False, proc.stderr.strip() or f"curl exit {proc.returncode}"
    return True, ""

def validate_download(path: Path) -> bool:
    try:
        if path.stat().st_size < 20:
            return False
        data = path.read_bytes()[:65536]
        if b"\x00" in data:
            return False
        sample = data.decode("utf-8", errors="ignore")
        if re.search(r"^\s*(?:<!doctype|<html|<head|HTTP/[0-9.]\s+[45]\d\d)", sample, re.I | re.M):
            return False
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines()) >= 1
    except OSError:
        return False

def include_urls(path: Path, base_url: str) -> list[str]:
    result: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^\s*!#include\s+(.+?)\s*$", raw, re.I)
            if match:
                child = urljoin(base_url, match.group(1).strip())
                if valid_url(child):
                    result.append(child)
    except OSError:
        pass
    return list(dict.fromkeys(result))

def collect_sources(source_urls: list[str], tmp: Path, started: float) -> list[Path]:
    files: list[Path] = []
    visited: set[str] = set()
    current = [(url, 0) for url in source_urls]
    sequence = 0

    while current and time.monotonic() - started < TOTAL_TIMEOUT:
        batch = []
        for url, depth in current:
            if url not in visited and valid_url(url):
                visited.add(url)
                batch.append((url, depth))
        if not batch:
            break

        log(f">> Download batch: {len(batch)} URL(s), workers={WORKERS}")
        next_batch: list[tuple[str, int]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {}
            for url, depth in batch:
                target = tmp / f"source-{sequence:06d}.txt"
                sequence += 1
                timeout = INCLUDE_TIMEOUT if depth else DOWNLOAD_TIMEOUT
                futures[pool.submit(download, url, target, timeout)] = (url, depth, target)

            for future in concurrent.futures.as_completed(futures):
                url, depth, target = futures[future]
                try:
                    ok, error = future.result()
                except Exception as exc:
                    ok, error = False, str(exc)
                if ok and validate_download(target):
                    files.append(target)
                    log(f"   [OK] {url[:110]}")
                    if depth < MAX_INCLUDE_DEPTH:
                        next_batch.extend((child, depth + 1) for child in include_urls(target, url))
                else:
                    target.unlink(missing_ok=True)
                    log(f"   [SKIP] {url[:110]} — {error or 'invalid response'}")
        current = next_batch

    return files

def split_options(rule: str) -> tuple[str, list[str]]:
    """Split the final unescaped ABP option delimiter from a network filter."""
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

    # In a regex filter, an unescaped `$` is a normal regex end-anchor. If
    # the final unescaped slash comes after the last `$`, there is no ABP
    # option section.
    pattern_start = 2 if rule.startswith("@@/") else 0
    if rule.startswith("/", pattern_start) or rule.startswith("@@/", 0):
        last_slash = rule.rfind("/")
        if last_slash > positions[-1]:
            return rule, []

    pos = positions[-1]
    option_text = rule[pos + 1:]
    if not option_text:
        return rule, []

    # A bare '$' can be part of a regex/pattern. Only treat it as an option
    # delimiter if the suffix has the shape of ABP options.
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
    if pattern.startswith("@@"):
        pattern_body = pattern[2:]
        if not pattern_body:
            return None
    else:
        pattern_body = pattern

    if CONTROL_RE.search(pattern_body) or any(c in pattern_body for c in "\r\n"):
        return None

    # Regex filters must be enclosed by unescaped slash delimiters.
    if pattern_body.startswith("/"):
        if len(pattern_body) < 2 or not pattern_body.endswith("/"):
            return None
        if pattern_body.count("/") < 2:
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

    # Options are semantically order-independent. Duplicate options are invalid.
    if len(normalized) != len(set(normalized)):
        return None

    # ABP restrictions for rewrite filters.
    if any(x.startswith("rewrite=") for x in normalized):
        if "third-party" in normalized:
            return None
        if not (pattern_body == "*" or pattern_body.startswith("||")):
            return None
        if not any(x.startswith("domain=") for x in normalized):
            return None

    return ("@@" if is_exception else "") + pattern_body + "$" + ",".join(
        sorted(normalized, key=str.casefold)
    )

def normalize_cosmetic(rule: str) -> str | None:
    # Match the earliest valid separator; selector bodies may themselves contain
    # '#' characters, so do not split on arbitrary occurrences.
    match = None
    for sep in COSMETIC_SEPARATORS:
        candidate = rule.find(sep)
        if candidate >= 0 and (match is None or candidate < match[0]):
            match = (candidate, sep)
    if match is None:
        return None

    pos, separator = match
    domains = rule[:pos].strip()
    body = rule[pos + len(separator):].strip()

    # Snippets are syntactically ABP but are restricted to custom/vetted lists;
    # exclude them from this public merged list.
    if separator == "#$#":
        return None
    if separator == "#?@#":
        return None
    if not body or CONTROL_RE.search(body):
        return None

    if domains:
        items = [x.strip() for x in domains.split(",")]
        if any(not x or not DOMAIN_RE.fullmatch(x) for x in items):
            return None
        domains = ",".join(sorted(set(items), key=str.casefold))

    # For normal hiding/exception rules, reject the uBO-only procedural syntax.
    if "+js(" in body.lower() or ":has-text(" in body.lower():
        # :has-text is not ABP; ABP's equivalent is :-abp-contains().
        return None

    return f"{domains}{separator}{body}"

def normalize_rule(raw: str) -> str | None:
    line = raw.strip().lstrip("\ufeff")
    if not line or len(line) > MAX_RULE_LENGTH:
        return None
    if COMMENT_RE.match(line) or DIRECTIVE_RE.match(line):
        return None
    if HOSTS_RE.match(line) or HTML_RE.match(line):
        return None
    if CONTROL_RE.search(line):
        return None

    if any(sep in line for sep in COSMETIC_SEPARATORS):
        return normalize_cosmetic(line)

    # Explicitly reject uBO's extended exception separator.
    if "#?@#" in line:
        return None

    return normalize_network(line)

def iter_rules(files: list[Path]) -> tuple[set[str], int, int, Counter]:
    from collections import Counter
    rules: set[str] = set()
    accepted = rejected = 0
    rejected_reasons: Counter = Counter()
    paths = [*files]
    if CUSTOM_RULES.exists():
        paths.append(CUSTOM_RULES)

    for path in paths:
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                for raw in source:
                    stripped = raw.rstrip("\r\n")
                    rule = normalize_rule(stripped)
                    if rule is None:
                        rejected += 1
                        rejected_reasons["invalid-or-non-ABP"] += 1
                    else:
                        rules.add(rule)
                        accepted += 1
        except OSError:
            rejected_reasons["read-error"] += 1
    return rules, accepted, rejected, rejected_reasons

def write_output(rules: set[str]) -> None:
    final_rules = sorted(rules, key=str.casefold)
    now = datetime.now(timezone.utc)
    header = [
        "! Title: Combined Adblock Plus Filter List",
        f"! Version: v{now:%Y.%m.%d.%H%M}",
        f"! Last updated: {now:%Y-%m-%d %H:%M:%S UTC}",
        "! Expires: 1 day",
        "! Homepage: https://github.com/anT0ny54/filter-lists",
        "! License: https://github.com/anT0ny54/filter-lists/blob/main/LICENSE",
        f"! Total rules: {len(final_rules)}",
        "!",
        "! Format: Strict Adblock Plus-compatible syntax",
        "! Profile: ABP external-list-safe; uBlock/AdGuard-only rules are excluded.",
        "! Auto-generated. Do not edit directly.",
        "! Edit sources.txt and rebuild.",
        "!",
    ]
    fd, temporary = tempfile.mkstemp(prefix="filters.", suffix=".tmp", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write("\n".join(header) + "\n")
            output.write("\n".join(final_rules) + "\n")
        os.replace(temporary, OUTPUT)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    log(f">> Unique strict ABP rules: {len(final_rules)}")

def main() -> int:
    started = time.monotonic()
    if not SOURCES.is_file():
        log(f"[ERROR] Missing sources file: {SOURCES}")
        return 1
    if shutil.which("curl") is None:
        log("[ERROR] curl is required")
        return 1

    source_urls = read_sources(SOURCES)
    log(f">> Found {len(source_urls)} unique source URLs")
    with tempfile.TemporaryDirectory(prefix="filter-lists-") as temp_dir:
        files = collect_sources(source_urls, Path(temp_dir), started)
        rules, accepted, rejected, reasons = iter_rules(files)
        if not rules:
            log("[ERROR] No valid strict ABP rules collected")
            return 1
        write_output(rules)
        log(f">> Accepted lines: {accepted}; rejected: {rejected}; unique: {len(rules)}")
        if rejected:
            log(">> Rejections: " + ", ".join(f"{k}={v}" for k, v in reasons.items()))
    log(f">> Completed in {time.monotonic() - started:.1f}s")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
