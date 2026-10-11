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

from config import BUILDER_VERSION, canonical_url, load_rule_policy, sha256_file, valid_url

DOWNLOAD_TIMEOUT = 90
INCLUDE_TIMEOUT = 60
CURL_RETRIES = 5
MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
INCLUDE_RE = re.compile(r"^\s*!#include\s+(.+?)\s*$", re.I)
# `\b` keeps `<header`/`<htmlfoo` from matching. The status-line branch needs
# `[0-9.]+`: with a single-character class `HTTP/1.1 404` never matched, so only
# HTTP/2-style error bodies were detected. A leading BOM (not `\s`) must not
# hide the page, hence `[\s\ufeff]*`.
HTML_ERROR_PAGE_RE = re.compile(
    r"^[\s\ufeff]*(?:<!doctype\b|<html\b|<head\b|HTTP/[0-9.]+\s+[45]\d\d)",
    re.I | re.M,
)


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


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def download(url: str, output: Path, timeout: int, max_download_bytes: int) -> tuple[bool, str, int]:
    """Download one source with bounded retries and SSRF-safe redirects.

    Redirects are handled one hop at a time so every destination is validated
    before the next network connection. curl is run without environment proxy
    settings and the validated DNS address is pinned with --resolve.

    The returned byte count includes every body observed during the download,
    including a partial body removed after a transfer failure.
    """
    timeout = max(1, int(timeout))
    deadline = time.monotonic() + timeout
    current_url = canonical_url(url)
    redirects = 0
    transferred_bytes = 0
    headers = output.with_suffix(output.suffix + ".headers")

    def discard_partial() -> None:
        nonlocal transferred_bytes
        transferred_bytes += _file_size(output)
        output.unlink(missing_ok=True)

    def fail(reason: str) -> tuple[bool, str, int]:
        discard_partial()
        return False, reason, transferred_bytes

    try:
        while True:
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                return fail("global-timeout")

            try:
                parsed = urlsplit(current_url)
                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if not host or parsed.scheme not in {"http", "https"}:
                    return fail("invalid-fetch-url")
            except ValueError as exc:
                return fail(f"invalid-fetch-url: {exc}")

            address, resolution_error = _public_address_for_url(current_url)
            if resolution_error:
                return fail(resolution_error if redirects == 0 else f"redirect-{resolution_error}")

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
                return fail("global-timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc))

            if proc.returncode:
                return fail(proc.stderr.strip() or f"curl exit {proc.returncode}")

            try:
                status = int(proc.stdout.strip() or "0")
            except ValueError:
                return fail("invalid-http-status")

            if status in REDIRECT_STATUSES:
                location = _redirect_location(headers)
                discard_partial()
                if not location:
                    return fail("redirect-missing-location")
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    return fail("too-many-redirects")
                next_url = urljoin(current_url, location)
                if not valid_url(next_url):
                    return fail("redirect-invalid-url")
                current_url = canonical_url(next_url)
                continue

            transferred_bytes += _file_size(output)
            return True, "", transferred_bytes
    finally:
        headers.unlink(missing_ok=True)


def validate_download(
    path: Path,
    max_bytes: int,
    *,
    reject_html_error_pages: bool | None = None,
) -> tuple[bool, str]:
    try:
        size = path.stat().st_size
        if size < 20:
            return False, "too-small"
        if size > max_bytes:
            return False, "too-large"
        with path.open("rb") as handle:
            sample = handle.read(65536)
            if b"\x00" in sample:
                return False, "binary-data"
            if reject_html_error_pages is None:
                reject_html_error_pages = load_rule_policy()["reject_html_error_pages"]
            if reject_html_error_pages and HTML_ERROR_PAGE_RE.search(
                sample.decode("utf-8", errors="ignore")
            ):
                return False, "html-or-error-page"
            if not sample.strip():
                return False, "empty"
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if b"\x00" in chunk:
                    return False, "binary-data"
        return True, ""
    except OSError as exc:
        return False, str(exc)


def include_urls(path: Path, base_url: str) -> list[str]:
    result: list[str] = []
    try:
        # Stream the include scan instead of materializing a potentially
        # 50 MiB source plus all of its split-line objects at once. `utf-8-sig`
        # drops a leading BOM so an include on the first line is still found
        # (the classifier already treats such a line as a directive).
        with path.open(encoding="utf-8-sig", errors="replace") as source:
            for raw in source:
                # Cheap substring gate: nearly every line in a 50 MiB list is
                # not an include, so skip the regex for all of those.
                if "!#" not in raw:
                    continue
                raw = raw.rstrip("\r\n")
                match = INCLUDE_RE.match(raw)
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

    # A source is allowed to consume at most max_download_bytes. Bound the
    # initial worker count by that configured worst case; collect_sources then
    # applies a tighter reservation to every request before it is submitted.
    per_source_limit = min(max_download_bytes, max_total_download_bytes)
    max_parallel_by_budget = max(1, max_total_download_bytes // per_source_limit)
    parallelism = max(1, min(int(workers), max_parallel_by_budget))

    stats = {
        "requested": 0,
        "root_requested": len(source_urls),
        "successful": 0,
        "root_successful": 0,
        "failed": 0,
        "root_failed": 0,
        "included_references": 0,
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

    # One executor is reused for every wave of every batch; creating a fresh
    # pool per wave wasted thread-pool setup on multi-wave builds. Wave sizes
    # never exceed `parallelism`, so one pool of that size covers all waves.
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as pool:
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
            discovered_children: list[tuple[str, int]] = []

            # Schedule by worker capacity and an explicit per-request budget
            # reservation. A request is submitted only while its worst-case
            # allocation still fits in the budget left after both completed
            # transfers and all active reservations. The request itself is
            # capped at that allocation, so the global byte total can never be
            # exceeded by work already in flight.
            wave_start = 0
            reserved_download_bytes = 0
            while wave_start < len(batch):
                if time.monotonic() >= deadline:
                    stats["timed_out"] = True
                    break

                wave_size = min(parallelism, len(batch) - wave_start)
                wave = batch[wave_start:wave_start + wave_size]
                futures = {}
                scheduled_count = 0
                ordered_outcomes: list[
                    tuple[str, int, Path, bool, str, int] | None
                ] = [None] * len(wave)

                for submission_index, (url, depth) in enumerate(wave):
                    remaining_budget = (
                        max_total_download_bytes
                        - stats["total_download_bytes"]
                        - reserved_download_bytes
                    )
                    if remaining_budget <= 0:
                        stats["budget_exhausted"] = True
                        break

                    # The final request near the boundary receives only what is
                    # still unreserved. curl's --max-filesize is set to this
                    # allocation rather than the larger per-source default.
                    request_limit = min(per_source_limit, remaining_budget)
                    reserved_download_bytes += request_limit
                    target = tmp / f"source-{sequence:06d}.txt"
                    sequence += 1
                    remaining = max(1, int(deadline - time.monotonic()))
                    timeout = min(INCLUDE_TIMEOUT if depth else DOWNLOAD_TIMEOUT, remaining)
                    futures[pool.submit(download, url, target, timeout, request_limit)] = (
                        submission_index, url, depth, target, request_limit
                    )
                    scheduled_count += 1

                if not futures:
                    break

                for future in concurrent.futures.as_completed(futures):
                    submission_index, url, depth, target, request_limit = futures[future]
                    try:
                        ok, error, transferred_bytes = future.result()
                    except Exception as exc:
                        ok, error, transferred_bytes = False, str(exc), 0
                    reserved_download_bytes -= request_limit

                    # A failed transfer may already have deleted its partial
                    # output. Trust the byte count returned by download() in
                    # that case instead of reading a now-missing file.
                    size = max(transferred_bytes, _file_size(target))
                    if ok:
                        ok, validation_error = validate_download(target, request_limit)
                        error = validation_error or error
                    ordered_outcomes[submission_index] = (url, depth, target, ok, error, size)

                # Network completion order must decide neither report order nor
                # output-file order. Process outcomes in deterministic submission
                # order even when downloads finish in the opposite order.
                for outcome in ordered_outcomes:
                    if outcome is None:
                        # No reservation remained for this entry. It remains
                        # pending and is accounted for below.
                        continue
                    url, depth, target, ok, error, size = outcome

                    # Reservations make this check redundant for compliant
                    # transfers, but retain it as a hard backstop for a worker
                    # that reports more bytes than its allocation.
                    #
                    # Transferred bytes count against the budget whether or not
                    # the response was accepted. A downloaded HTML error page is
                    # a failed source, but its bytes still consumed bandwidth;
                    # previously only accepted files were added to
                    # `total_download_bytes`, so a wave of invalid responses
                    # could bypass `max_total_download_bytes` entirely. The
                    # original validation/transfer failure reason is preserved;
                    # only an otherwise-accepted source is relabelled
                    # "global-download-budget-exhausted".
                    if stats["total_download_bytes"] + size > max_total_download_bytes:
                        if ok:
                            error = "global-download-budget-exhausted"
                        ok = False
                        stats["budget_exhausted"] = True
                    stats["total_download_bytes"] += size

                    if ok:
                        files.append(target)
                        stats["successful"] += 1
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
                            stats["included_references"] += len(children)
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

                wave_start += scheduled_count

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
            if deferred_by_source_limit or (len(visited) >= max_total_sources and next_batch):
                stats["source_limit_reached"] = True
                record_unattempted(pending, "source-limit")
                current = []
                break

            current = next_batch

    stats["visited"] = len(visited)
    stats["included_requested"] = stats["included_references"]
    # `requested` is the complete success+failure accounting, including
    # queued sources that could not be attempted because of a global limit.
    stats["requested"] = stats["successful"] + stats["failed"]
    stats["included_successful"] = stats["successful"] - stats["root_successful"]
    stats["included_failed"] = stats["failed"] - stats["root_failed"]
    return files, stats

