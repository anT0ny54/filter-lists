#!/usr/bin/env python3
"""Filter-Lists V7.1 deterministic build orchestrator."""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_RULES = ROOT / "custom-rules.txt"
OUTPUT = ROOT / "filters.txt"
REPORT = ROOT / "reports" / "latest.json"
SOURCES_TXT = ROOT / "sources.txt"
WORKERS = min(16, max(4, (os.cpu_count() or 2) * 2))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import load_config  # noqa: E402
from fetch import collect_sources, valid_url  # noqa: E402
from report import analyze_files, write_report  # noqa: E402
from normalize import normalize_rule  # noqa: E402


def log(message: str) -> None:
    print(message, flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def config_fingerprint(config) -> str:
    h = hashlib.sha256()
    for source in config.sources:
        h.update(f"{source.name}\0{source.url}\0{source.category}\0{source.priority}\0{source.required}\n".encode())
    for path in (ROOT / "policies.yaml", CUSTOM_RULES):
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()


def sync_legacy_sources(config) -> None:
    """Keep sources.txt as a generated compatibility mirror, never as input."""
    text = "# Generated compatibility mirror of sources.yaml. Do not edit directly.\n"
    text += "\n".join(source.url for source in config.sources) + "\n"
    current = SOURCES_TXT.read_text(encoding="utf-8") if SOURCES_TXT.exists() else ""
    if current != text:
        SOURCES_TXT.write_text(text, encoding="utf-8", newline="\n")


def write_output(rules: set[str], build_id: str) -> None:
    final_rules = sorted(rules, key=lambda x: (x.casefold(), x))
    now = datetime.now(timezone.utc)
    header = [
        "! Title: Combined Adblock Plus Filter List",
        f"! Version: v7.1.1-{build_id[:12]}",
        f"! Last updated: {now:%Y-%m-%d %H:%M:%S UTC}",
        "! Expires: 1 day",
        "! Homepage: https://github.com/anT0ny54/filter-lists",
        "! License: https://github.com/anT0ny54/filter-lists/blob/main/LICENSE",
        f"! Build-ID: {build_id}",
        f"! Total rules: {len(final_rules)}",
        "!",
        "! Format: Strict Adblock Plus-compatible syntax",
        "! Profile: Strict Adblock Plus-compatible syntax; uBlock/AdGuard-only rules are excluded.",
        "! Auto-generated. Do not edit directly.",
        "! Edit sources.yaml and rebuild.",
        "!",
    ]
    fd, temporary = tempfile.mkstemp(prefix="filters.", suffix=".tmp", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write("\n".join(header) + "\n")
            output.write("\n".join(final_rules) + "\n")
        os.replace(temporary, OUTPUT)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    log(f">> Unique strict ABP rules: {len(final_rules)}")


def main() -> int:
    started = time.monotonic()
    if shutil.which("curl") is None:
        log("[ERROR] curl is required")
        return 1
    try:
        config = load_config()
    except Exception as exc:
        log(f"[ERROR] Configuration: {exc}")
        return 1
    sync_legacy_sources(config)
    source_urls = [s.url for s in config.sources if valid_url(s.url)]
    if not source_urls:
        log("[ERROR] No enabled source URLs found")
        return 1
    log(f">> Found {len(source_urls)} enabled source URLs")
    with tempfile.TemporaryDirectory(prefix="filter-lists-") as temp_dir:
        files, source_stats = collect_sources(source_urls, Path(temp_dir), started, WORKERS, log, total_timeout=config.total_timeout_seconds, max_include_depth=config.max_include_depth, max_download_bytes=config.max_download_bytes, max_total_download_bytes=config.max_total_download_bytes, max_total_sources=config.max_total_sources)
        source_stats["required"] = [s.url for s in config.sources if s.required]
        failed_root_urls = {x["url"] for x in source_stats.get("results", []) if x.get("status") == "failed" and x.get("depth") == 0}
        source_stats["required_failed"] = [u for u in source_stats["required"] if u in failed_root_urls]
        source_stats["success_ratio"] = round(source_stats["root_successful"] / source_stats["root_requested"], 4) if source_stats["root_requested"] else 0.0
        source_stats["health_basis"] = "root sources only; nested !#include sources are reported separately"
        source_stats["health_threshold"] = config.minimum_success_ratio
        unhealthy = ((config.fail_if_zero_sources and source_stats["root_successful"] == 0) or source_stats["success_ratio"] < config.minimum_success_ratio or bool(source_stats["required_failed"]) or source_stats.get("source_limit_reached") or source_stats.get("timed_out"))
        if unhealthy:
            log(f"[ERROR] Source health failed: {source_stats['root_successful']}/{source_stats['root_requested']} root sources ({source_stats['success_ratio']:.1%})")
            if source_stats["required_failed"]:
                log(f"[ERROR] Required sources failed: {len(source_stats['required_failed'])}")
            failed_roots = [x for x in source_stats.get("failures", []) if x.get("depth") == 0]
            for item in failed_roots:
                log(f"[ERROR] Root source failed: {item.get('url')} — {item.get('reason', 'unknown error')}")
            if source_stats.get("timed_out"):
                log("[ERROR] Global fetch deadline was reached before all queued sources completed")
            if source_stats.get("source_limit_reached"):
                log("[ERROR] Global source traversal limit was reached before all queued sources completed")
            stats = {"input_lines": 0, "accepted_lines": 0, "rejected_lines": 0, "duplicate_lines": 0, "unique_rules": 0, "rejection_reasons": {}}
            write_report(REPORT, source_stats=source_stats, rule_stats=stats, elapsed_seconds=time.monotonic()-started, source_urls=source_urls, build_id=config_fingerprint(config))
            return 1
        rules, rule_stats = analyze_files(files, CUSTOM_RULES, max_rule_length=config.max_rule_length)
        build_id = hashlib.sha256((config_fingerprint(config) + "\n" + "\n".join(sorted(rules, key=lambda x: (x.casefold(), x)))).encode()).hexdigest()
        write_output(rules, build_id)
        write_report(REPORT, source_stats=source_stats, rule_stats=rule_stats, elapsed_seconds=time.monotonic()-started, source_urls=source_urls, build_id=build_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
