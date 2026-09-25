#!/usr/bin/env python3
"""Network fetching and !#include resolution for Filter-Lists."""
from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from config import BUILDER_VERSION, canonical_url, sha256_file, valid_url

DOWNLOAD_TIMEOUT = 90
INCLUDE_TIMEOUT = 60
CURL_RETRIES = 5
MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _public_address_for_url(url: str) -> tuple[str | None, str]:
    """Resolve a fetch target and reject non-public addresses before curl connects.

    The returned address is also pinned with curl --resolve so a DNS answer
    cannot change between validation and the actual connection. All resolved
    addresses must be globally routable; mixed public/private DNS answers are
    rejected rather than choosing a potentially unsafe address.
    """
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None, "invalid-fetch-url"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host = parsed.hostname
    except ValueError as exc:
        return None, f"invalid-fetch-url: {exc}"

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if not literal.is_global:
            return None, "blocked-non-public-address"
        return literal.compressed, ""

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return None, f"dns-resolution-failed: {exc}"

    addresses: list[str] = []
    for info in infos:
        candidate = info[4][0]
        if candidate not in addresses:
            addresses.append(candidate)
    if not addresses:
        return None, "dns-resolution-empty"

    parsed_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for candidate in addresses:
        try:
            parsed_candidate = ipaddress.ip_address(candidate)
        except ValueError:
            return None, "dns-resolution-invalid-address"
        if not parsed_candidate.is_global:
            return None, "blocked-non-public-address"
        parsed_addresses.append(parsed_candidate)

    # Prefer IPv4 when available for broad runner compatibility; otherwise use
    # the first validated address returned by the resolver.
    parsed_addresses.sort(key=lambda addr: (addr.version != 4, addr.compressed))
    return parsed_addresses[0].compressed, ""


def _resolve_arg(host: str, port: int, address: str) -> str:
    if ":" in address:
        address = f"[{address}]"
    return f"{host}:{port}:{address}"


def _redirect_location(headers: Path) -> str | None:
    try:
        raw = headers.read_text(encoding="iso-8859-1", errors="replace")
    except OSError:
        return None
    # curl normally writes one response header block here because redirect
    # following is disabled. Walk the blocks backwards for robustness against
    # an interim response such as 100 Continue.
    blocks = re.split(r"\r?\n\r?\n", raw)
    for block in reversed(blocks):
        for line in reversed(block.splitlines()):
            if line.lower().startswith("location:"):
                return line.split(":", 1)[1].strip() or None
    return None


def download(url: str, output: Path, timeout: int, max_download_bytes: int) -> tuple[bool, str]:
    """Download one source with bounded retries and SSRF-safe redirects.

    Redirects are handled one hop at a time so every destination is validated
    before the next network connection. curl is run without environment proxy
    settings and the validated DNS address is pinned with --resolve.
    """
    timeout = max(1, int(timeout))
    deadline = time.monotonic() + timeout
    current_url = canonical_url(url)
    redirects = 0
    headers = output.with_suffix(output.suffix + ".headers")

    try:
        while True:
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                output.unlink(missing_ok=True)
                return False, "global-timeout"

            try:
                parsed = urlsplit(current_url)
                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if not host or parsed.scheme not in {"http", "https"}:
                    output.unlink(missing_ok=True)
                    return False, "invalid-fetch-url"
            except ValueError as exc:
                output.unlink(missing_ok=True)
                return False, f"invalid-fetch-url: {exc}"

            address, resolution_error = _public_address_for_url(current_url)
            if resolution_error:
                output.unlink(missing_ok=True)
                return False, resolution_error if redirects == 0 else f"redirect-{resolution_error}"

            connect_timeout = min(20, remaining)
            command = [
                "curl", "--fail", "--silent", "--show-error", "--compressed",
                "--retry", str(CURL_RETRIES), "--retry-connrefused",
                "--retry-max-time", str(remaining),
                "--connect-timeout", str(connect_timeout), "--max-time", str(remaining),
                "--max-filesize", str(max_download_bytes),
                "--noproxy", "*",
                "--proto", "=http,https",
                "--max-redirs", "0",
                "--dump-header", str(headers),
                "--write-out", "%{http_code}",
                "--user-agent", f"filter-lists-builder/{BUILDER_VERSION}",
            ]
            try:
                ipaddress.ip_address(host)
            except ValueError:
                command.extend(["--resolve", _resolve_arg(host, port, address)])
            command.extend(["--output", str(output), current_url])

            headers.unlink(missing_ok=True)
            try:
                proc = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=remaining + 5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                output.unlink(missing_ok=True)
                return False, "global-timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)

            if proc.returncode:
                output.unlink(missing_ok=True)
                return False, proc.stderr.strip() or f"curl exit {proc.returncode}"

            try:
                status = int(proc.stdout.strip() or "0")
            except ValueError:
                output.unlink(missing_ok=True)
                return False, "invalid-http-status"

            if status in REDIRECT_STATUSES:
                location = _redirect_location(headers)
                output.unlink(missing_ok=True)
                if not location:
                    return False, "redirect-missing-location"
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    return False, "too-many-redirects"
                next_url = urljoin(current_url, location)
                if not valid_url(next_url):
                    return False, "redirect-invalid-url"
                current_url = canonical_url(next_url)
                continue

            return True, ""
    finally:
        headers.unlink(missing_ok=True)


def validate_download(path: Path, max_bytes: int) -> tuple[bool, str]:
    try:
        size = path.stat().st_size
        if size < 20:
            return False, "too-small"
        if size > max_bytes:
            return False, "too-large"
        with path.open("rb") as handle:
            data = handle.read(65536)
        if b"\x00" in data:
            return False, "binary-data"
        sample = data.decode("utf-8", errors="ignore")
        if re.search(r"^\s*(?:<!doctype|<html|<head|HTTP/[0-9.]\s+[45]\d\d)", sample, re.I | re.M):
            return False, "html-or-error-page"
        if size <= 0 or not sample.strip():
            return False, "empty"
        return True, ""
    except OSError as exc:
        return False, str(exc)


def include_urls(path: Path, base_url: str) -> list[str]:
    result: list[str] = []
    try:
        # Stream the include scan instead of materializing a potentially
        # 50 MiB source plus all of its split-line objects at once.
        with path.open(encoding="utf-8", errors="replace") as source:
            for raw in source:
                raw = raw.rstrip("\r\n")
                match = re.match(r"^\s*!#include\s+(.+?)\s*$", raw, re.I)
                if not match:
                    continue
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
    # number of simultaneous downloads so that the reserved worst-case
    # bytes can never exceed the global budget. Sources waiting for a slot
    # are queued, not counted as failures.
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
        "included_requested": 0,
        "total_download_bytes": 0,
        "max_total_download_bytes": max_total_download_bytes,
        "max_total_sources": max_total_sources,
        "max_parallel_by_budget": max_parallel_by_budget,
        "parallelism": parallelism,
        "failures": [],
        "results": [],
        "timed_out": False,
        "source_limit_reached": False,
        "budget_exhausted": False,
    }

    def record_unattempted(entries: list[tuple[str, int]], reason: str) -> None:
        """Record queued-but-never-attempted sources so accounting stays complete."""
        already_reported = {item.get("url") for item in stats["results"] if item.get("url")}
        for url, depth in entries:
            url = canonical_url(url)
            if url in already_reported:
                continue
            already_reported.add(url)
            stats["failed"] += 1
            if depth == 0:
                stats["root_failed"] += 1
            result = {
                "url": url,
                "depth": depth,
                "status": "failed",
                "reason": reason,
                "bytes": 0,
                "path": None,
            }
            stats["results"].append(result)
            if len(stats["failures"]) < 100:
                stats["failures"].append({"url": url, "reason": reason, "depth": depth})
            log(f"   [SKIP] {url[:110]} — {reason}")

    while current:
        if time.monotonic() >= deadline:
            stats["timed_out"] = True
            record_unattempted(current, "global-timeout")
            current = []
            break

        if len(visited) >= max_total_sources:
            stats["source_limit_reached"] = True
            record_unattempted(current, "source-limit")
            current = []
            break

        batch: list[tuple[str, int]] = []
        deferred_by_source_limit: list[tuple[str, int]] = []
        for url, depth in current:
            if len(visited) >= max_total_sources:
                deferred_by_source_limit.append((url, depth))
                continue
            key = canonical_url(url)
            if key not in visited and valid_url(key):
                visited.add(key)
                batch.append((key, depth))
        if not batch:
            if deferred_by_source_limit:
                stats["source_limit_reached"] = True
                record_unattempted(deferred_by_source_limit, "source-limit")
            current = []
            break

        log(f">> Download batch: {len(batch)} URL(s), workers={parallelism}")
        next_batch: list[tuple[str, int]] = []
        discovered_children: list[tuple[str, int]] = []

        # Process the batch in budget-safe waves. Each wave reserves the
        # maximum possible bytes for every submitted source.
        wave_start = 0
        while wave_start < len(batch):
            if time.monotonic() >= deadline:
                stats["timed_out"] = True
                break

            remaining_budget = max_total_download_bytes - stats["total_download_bytes"]
            if remaining_budget <= 0:
                stats["budget_exhausted"] = True
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
                    futures[pool.submit(download, url, target, timeout, wave_limit)] = (
                        url, depth, target, wave_limit
                    )

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
                        stats["results"].append({
                            "url": url,
                            "depth": depth,
                            "status": "ok",
                            "bytes": size,
                            "sha256": sha256_file(target),
                            "path": str(target),
                        })
                        log(f"   [OK] {url[:110]}")
                        if depth < max_include_depth:
                            children = include_urls(target, url)
                            stats["included_requested"] += len(children)
                            discovered_children.extend((child, depth + 1) for child in children)
                    else:
                        stats["failed"] += 1
                        if depth == 0:
                            stats["root_failed"] += 1
                        reason = error or "invalid response"
                        stats["results"].append({
                            "url": url,
                            "depth": depth,
                            "status": "failed",
                            "reason": reason,
                            "bytes": size,
                            "path": str(target),
                        })
                        if len(stats["failures"]) < 100:
                            stats["failures"].append({"url": url, "reason": reason, "depth": depth})
                        target.unlink(missing_ok=True)
                        log(f"   [SKIP] {url[:110]} — {reason}")

        # Network completion order must never decide which includes are visited
        # first. Without this stable ordering, a global source limit can make
        # identical builds choose different children depending on timing.
        discovered: dict[str, int] = {}
        for url, depth in discovered_children:
            key = canonical_url(url)
            if key not in discovered or depth < discovered[key]:
                discovered[key] = depth
        next_batch = sorted(discovered.items(), key=lambda item: (item[1], item[0]))

        pending: list[tuple[str, int]] = batch[wave_start:]
        pending.extend(deferred_by_source_limit)
        pending.extend(next_batch)

        if stats["timed_out"]:
            record_unattempted(pending, "global-timeout")
            current = []
            break
        if stats["budget_exhausted"]:
            record_unattempted(pending, "global-download-budget-exhausted")
            current = []
            break
        if deferred_by_source_limit or len(visited) >= max_total_sources and next_batch:
            stats["source_limit_reached"] = True
            record_unattempted(pending, "source-limit")
            current = []
            break

        current = next_batch

    stats["visited"] = len(visited)
    stats["requested"] = len(visited)
    stats["included_successful"] = stats["successful"] - stats["root_successful"]
    stats["included_failed"] = stats["failed"] - stats["root_failed"]
    return files, stats

