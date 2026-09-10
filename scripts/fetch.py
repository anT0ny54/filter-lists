#!/usr/bin/env python3
"""Network fetching and !#include resolution for Filter-Lists."""
from __future__ import annotations

import concurrent.futures
import hashlib
import re
import subprocess
import time
import threading
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

DOWNLOAD_TIMEOUT = 90
INCLUDE_TIMEOUT = 60
CURL_RETRIES = 5
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
    """Download one source with bounded, transient-error-aware curl retries.

    curl handles retryable HTTP responses (including 429/5xx) and transport
    failures, and honors Retry-After when supplied by the server.  We avoid
    --retry-all-errors so permanent HTTP failures such as 404 are not retried
    unnecessarily.
    """
    timeout = max(1, int(timeout))
    connect_timeout = min(20, timeout)
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location", "--compressed",
        "--retry", str(CURL_RETRIES), "--retry-connrefused",
        "--retry-max-time", str(timeout),
        "--connect-timeout", str(connect_timeout), "--max-time", str(timeout),
        "--max-filesize", str(max_download_bytes),
        "--user-agent", "filter-lists-builder/7.2.0", "--output", str(output), url,
    ]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        output.unlink(missing_ok=True)
        return False, str(exc)
    if proc.returncode:
        output.unlink(missing_ok=True)
        return False, proc.stderr.strip() or f"curl exit {proc.returncode}"
    return True, ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    deadline = started + total_timeout

    # A source is allowed to consume at most max_download_bytes.  Bound the
    # number of simultaneous downloads so that the *reserved* worst-case
    # bytes can never exceed the global budget.  Sources waiting for a slot
    # are queued, not counted as failures.  This fixes the V7.1 bug where a
    # 500 MiB global budget + 50 MiB per-source limit caused only 10 of 33
    # root sources to be submitted and the remaining 23 to be falsely marked
    # failed.
    per_source_limit = min(max_download_bytes, max_total_download_bytes)
    max_parallel_by_budget = max(1, max_total_download_bytes // per_source_limit)
    parallelism = max(1, min(int(workers), max_parallel_by_budget))

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
        "max_parallel_by_budget": max_parallel_by_budget,
        "parallelism": parallelism,
        "failures": [],
        "results": [],
    }

    while current and time.monotonic() < deadline:
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

        log(f">> Download batch: {len(batch)} URL(s), workers={parallelism}")
        next_batch: list[tuple[str, int]] = []

        # Process the batch in budget-safe waves.  Each wave reserves the
        # maximum possible bytes for every submitted source.  Once a wave
        # finishes, the next wave is sized from the *remaining* global budget.
        # This gives a real global upper bound without treating queued sources
        # as failed.
        wave_start = 0
        while wave_start < len(batch):
            if time.monotonic() >= deadline:
                break
            remaining_budget = max_total_download_bytes - stats["total_download_bytes"]
            if remaining_budget <= 0:
                log("   [STOP] Global download budget exhausted; remaining sources were not attempted")
                break
            wave_limit = min(per_source_limit, remaining_budget)
            available_slots = max(1, remaining_budget // wave_limit)
            wave_size = min(parallelism, available_slots, len(batch) - wave_start)
            wave = batch[wave_start:wave_start + wave_size]
            wave_start += wave_size
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(wave)) as pool:
                futures = {}
                for url, depth in wave:
                    target = tmp / f"source-{sequence:06d}.txt"
                    sequence += 1
                    remaining = max(1, int(deadline - time.monotonic()))
                    timeout = min(INCLUDE_TIMEOUT if depth else DOWNLOAD_TIMEOUT, remaining)
                    futures[pool.submit(download, url, target, timeout, wave_limit)] = (url, depth, target, wave_limit)

                for future in concurrent.futures.as_completed(futures):
                    url, depth, target, wave_limit = futures[future]
                    try:
                        ok, error = future.result()
                    except Exception as exc:
                        ok, error = False, str(exc)

                    size = target.stat().st_size if target.exists() else 0
                    if ok:
                        ok, validation_error = validate_download(target, wave_limit)
                        error = validation_error or error
                    if ok and stats["total_download_bytes"] + size > max_total_download_bytes:
                        ok = False
                        error = "global-download-budget-exceeded"

                    if ok:
                        files.append(target)
                        stats["successful"] += 1
                        stats["total_download_bytes"] += size
                        if depth == 0:
                            stats["root_successful"] += 1
                        stats["results"].append({"url": url, "depth": depth, "status": "ok", "bytes": size, "sha256": sha256_file(target), "path": str(target)})
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
                        reason = error or "invalid response"
                        stats["results"].append({"url": url, "depth": depth, "status": "failed", "reason": reason, "bytes": size, "path": str(target)})
                        if len(stats["failures"]) < 100:
                            stats["failures"].append({"url": url, "reason": reason, "depth": depth})
                        target.unlink(missing_ok=True)
                        log(f"   [SKIP] {url[:110]} — {reason}")

        current = next_batch

    stats["visited"] = len(visited)
    stats["timed_out"] = bool(current and time.monotonic() >= deadline)
    stats["source_limit_reached"] = len(visited) >= max_total_sources and bool(current)
    stats["requested"] = len(visited)
    stats["included_successful"] = stats["successful"] - stats["root_successful"]
    stats["included_failed"] = stats["failed"] - stats["root_failed"]
    return files, stats

