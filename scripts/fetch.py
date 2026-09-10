#!/usr/bin/env python3
"""Network fetching and !#include resolution for Filter-Lists."""
from __future__ import annotations

import concurrent.futures
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

DOWNLOAD_TIMEOUT = 90
INCLUDE_TIMEOUT = 60
CURL_RETRIES = 3
HTML_RE = re.compile(r"^\s*(?:<!doctype\b|<html\b|<head\b|<body\b)", re.I)


def canonical_url(url: str) -> str:
    """Canonicalize harmless URL variations for include-cycle detection."""
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


def valid_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        return p.scheme in {"http", "https"} and bool(p.netloc) and not any(c.isspace() for c in url)
    except ValueError:
        return False


def download(url: str, output: Path, timeout: int, max_download_bytes: int) -> tuple[bool, str]:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location", "--compressed",
        "--retry", str(CURL_RETRIES), "--retry-delay", "2",
        "--connect-timeout", "20", "--max-time", str(timeout),
        "--max-filesize", str(max_download_bytes),
        "--user-agent", "filter-lists-builder/7.0", "--output", str(output), url,
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


def validate_download(path: Path, max_bytes: int) -> tuple[bool, str]:
    try:
        size = path.stat().st_size
        if size < 20:
            return False, "too-small"
        if size > max_bytes:
            return False, "too-large"
        data = path.read_bytes()[:65536]
        if b"\x00" in data:
            return False, "binary-data"
        sample = data.decode("utf-8", errors="ignore")
        if re.search(r"^\s*(?:<!doctype|<html|<head|HTTP/[0-9.]\s+[45]\d\d)", sample, re.I | re.M):
            return False, "html-or-error-page"
        if not path.read_text(encoding="utf-8", errors="replace").splitlines():
            return False, "empty"
        return True, ""
    except OSError as exc:
        return False, str(exc)


def include_urls(path: Path, base_url: str) -> list[str]:
    result: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^\s*!#include\s+(.+?)\s*$", raw, re.I)
            if match:
                child = urljoin(base_url, match.group(1).strip())
                if valid_url(child):
                    result.append(canonical_url(child))
    except OSError:
        pass
    return list(dict.fromkeys(result))


def collect_sources(
    source_urls: list[str],
    tmp: Path,
    started: float,
    workers: int,
    log,
    *,
    total_timeout: int,
    max_include_depth: int,
    max_download_bytes: int,
    max_total_download_bytes: int,
    max_total_sources: int,
) -> tuple[list[Path], dict]:
    files: list[Path] = []
    visited: set[str] = set()
    current = [(canonical_url(url), 0) for url in source_urls]
    sequence = 0
    stats = {
        "requested": len(source_urls),
        "root_requested": len(source_urls),
        "successful": 0,
        "root_successful": 0,
        "failed": 0,
        "root_failed": 0,
        "included": 0,
        "included_requested": 0,
        "total_download_bytes": 0,
        "max_total_download_bytes": max_total_download_bytes,
        "max_total_sources": max_total_sources,
        "failures": [],
        "results": [],
    }

    while current and time.monotonic() - started < total_timeout:
        batch: list[tuple[str, int]] = []
        for url, depth in current:
            if len(visited) >= max_total_sources:
                break
            key = canonical_url(url)
            if key not in visited and valid_url(key):
                visited.add(key)
                batch.append((key, depth))
        if not batch:
            break

        log(f">> Download batch: {len(batch)} URL(s), workers={workers}")
        next_batch: list[tuple[str, int]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for url, depth in batch:
                target = tmp / f"source-{sequence:06d}.txt"
                sequence += 1
                timeout = INCLUDE_TIMEOUT if depth else DOWNLOAD_TIMEOUT
                futures[pool.submit(download, url, target, timeout, max_download_bytes)] = (url, depth, target)

            for future in concurrent.futures.as_completed(futures):
                url, depth, target = futures[future]
                try:
                    ok, error = future.result()
                except Exception as exc:
                    ok, error = False, str(exc)
                if ok:
                    ok, validation_error = validate_download(target, max_download_bytes)
                    error = validation_error or error
                size = target.stat().st_size if target.exists() else 0
                if ok and stats["total_download_bytes"] + size > max_total_download_bytes:
                    ok = False
                    error = "global-download-budget-exceeded"
                if ok:
                    files.append(target)
                    stats["successful"] += 1
                    stats["total_download_bytes"] += size
                    if depth == 0:
                        stats["root_successful"] += 1
                    stats["results"].append({"url": url, "depth": depth, "status": "ok", "bytes": size})
                    log(f"   [OK] {url[:110]}")
                    if depth < max_include_depth:
                        children = include_urls(target, url)
                        stats["included"] += len(children)
                        stats["included_requested"] += len(children)
                        next_batch.extend((child, depth + 1) for child in children)
                else:
                    stats["failed"] += 1
                    if depth == 0:
                        stats["root_failed"] += 1
                    stats["results"].append({"url": url, "depth": depth, "status": "failed", "reason": error or "invalid response"})
                    if len(stats["failures"]) < 100:
                        stats["failures"].append({"url": url, "reason": error or "invalid response", "depth": depth})
                    target.unlink(missing_ok=True)
                    log(f"   [SKIP] {url[:110]} — {error or 'invalid response'}")
        current = next_batch

    stats["visited"] = len(visited)
    stats["timed_out"] = bool(current and time.monotonic() - started >= total_timeout)
    stats["source_limit_reached"] = len(visited) >= max_total_sources and bool(current)
    stats["requested"] = len(visited)
    stats["included_successful"] = stats["successful"] - stats["root_successful"]
    stats["included_failed"] = stats["failed"] - stats["root_failed"]
    return files, stats
