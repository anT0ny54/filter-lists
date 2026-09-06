#!/usr/bin/env python3
"""Build a single Adblock Plus-compatible filter list.

The builder deliberately validates structure without trying to implement a
browser's complete filter parser. This avoids silently deleting valid ABP
features such as exception rules, extended CSS, snippets, and newer options.
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

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
INCLUDE_RE = re.compile(r"^\s*!#include\s+(.+?)\s*$", re.I)
DIRECTIVE_RE = re.compile(r"^\s*!#(?:if|else|endif|include)\b", re.I)
HOSTS_RE = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)(?:\s+|$)")
COSMETIC_SEPARATOR_RE = re.compile(r"##|#@#|#\?#|#\?@#")


def log(message: str) -> None:
    print(message, flush=True)


def valid_url(url: str) -> bool:
    return bool(re.fullmatch(r"https?://[^\s]+", url, re.I))


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
        "--user-agent", "filter-lists-builder/3.0", "--output", str(output), url,
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
        if path.stat().st_size < 200:
            return False
        data = path.read_bytes()[:65536]
        if b"\x00" in data:
            return False
        sample = data.decode("utf-8", errors="ignore")
        if re.search(r"^\s*(?:<!doctype|<html|<head|HTTP/[0-9.]\s+[45]\d\d)", sample, re.I | re.M):
            return False
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines()) >= 2
    except OSError:
        return False


def include_urls(path: Path, base_url: str) -> list[str]:
    result: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = INCLUDE_RE.match(raw)
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
        batch: list[tuple[str, int]] = []
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


def split_network_options(rule: str) -> tuple[str, list[str]]:
    """Split the final ABP $options section without damaging regex rules."""
    if not rule or rule.startswith("/"):
        # A regex filter normally ends with '/', but options can follow it.
        last = rule.rfind("/")
        if last > 0 and last == len(rule) - 1:
            return rule, []
    if "$" not in rule:
        return rule, []
    pattern, option_text = rule.rsplit("$", 1)
    if not pattern or not option_text:
        return rule, []
    return pattern, [item.strip() for item in option_text.split(",") if item.strip()]


def valid_option(option: str) -> bool:
    """Validate ABP option shape while remaining forward-compatible."""
    if not option or "\r" in option or "\n" in option:
        return False
    if "=" in option:
        name, value = option.split("=", 1)
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", name.strip())) and bool(value.strip())
    return bool(re.fullmatch(r"~?[A-Za-z][A-Za-z0-9-]*", option))


def normalize_network(rule: str) -> str | None:
    pattern, options = split_network_options(rule.strip())
    if not pattern or any(ch in "\r\n" for ch in pattern):
        return None
    if pattern.startswith("/"):
        # ABP regex filter: /.../ or /.../$options
        slash = pattern.rfind("/")
        if slash <= 0:
            return None
    if not options:
        return pattern
    if not all(valid_option(x) for x in options):
        return None
    # Options are semantically order-independent; keep values but canonicalize
    # option names to lowercase. Values are case-sensitive and are preserved.
    normalized = []
    for option in options:
        if "=" in option:
            name, value = option.split("=", 1)
            normalized.append(f"{name.lower()}={value}")
        elif option.startswith("~"):
            normalized.append("~" + option[1:].lower())
        else:
            normalized.append(option.lower())
    if len(normalized) != len(set(normalized)):
        return None
    normalized = sorted(normalized, key=str.casefold)
    return f"{pattern}${','.join(normalized)}"


def normalize_cosmetic(rule: str) -> str | None:
    """Normalize domains only; never rewrite CSS/extended CSS selector bodies."""
    match = re.match(r"^(.*?)(#@#|#\?#|#\?@#|##)(.+)$", rule.strip())
    if not match:
        return None
    domains, separator, body = match.groups()
    body = body.strip()
    if not body:
        return None

    if domains:
        domain_items = [x.strip() for x in domains.split(",")]
        if any(not x for x in domain_items):
            return None
        # ABP domain names can contain negation. Keep unusual but legal selector
        # syntax untouched; only reject whitespace/control characters.
        if any(any(c.isspace() for c in item) for item in domain_items):
            return None
        domains = ",".join(sorted(set(domain_items), key=str.casefold))
    return f"{domains}{separator}{body}"


def normalize_rule(raw: str) -> str | None:
    line = raw.strip().lstrip("\ufeff")
    if not line or len(line) > MAX_RULE_LENGTH:
        return None
    if COMMENT_RE.match(line) or DIRECTIVE_RE.match(line):
        return None
    if HOSTS_RE.match(line):
        return None
    lower = line.lower()
    if "<!doctype" in lower or "<html" in lower:
        return None

    # ABP supports both standard element hiding (##/#@#) and extended
    # element hiding (#?#/#?@#). Preserve the complete selector body.
    if COSMETIC_SEPARATOR_RE.search(line):
        return normalize_cosmetic(line)

    # Non-cosmetic filters may contain spaces inside regex/options values, so
    # do not impose a simplistic whitespace ban. Reject only line breaks here.
    return normalize_network(line)


def iter_rules(files: list[Path]) -> tuple[set[str], int, int]:
    rules: set[str] = set()
    accepted = rejected = 0
    paths = [*files]
    if CUSTOM_RULES.exists():
        paths.append(CUSTOM_RULES)

    for path in paths:
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                for raw in source:
                    rule = normalize_rule(raw.rstrip("\r\n"))
                    if rule is None:
                        rejected += 1
                    else:
                        rules.add(rule)
                        accepted += 1
        except OSError:
            continue
    return rules, accepted, rejected


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
        "! Format: Adblock Plus-compatible syntax",
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
    log(f">> Unique ABP rules: {len(final_rules)}")


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
        rules, accepted, rejected = iter_rules(files)
        if not rules:
            log("[ERROR] No valid ABP rules collected")
            return 1
        write_output(rules)
        log(f">> Accepted lines: {accepted}; rejected: {rejected}; unique: {len(rules)}")
    log(f">> Completed in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
