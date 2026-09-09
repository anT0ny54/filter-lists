#!/usr/bin/env python3
"""Filter-Lists v6 build orchestrator.

V6 keeps the existing V5 behavior as the compatibility baseline while
separating fetching, normalization/policy, and reporting into modules.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources.txt"
SOURCE_REGISTRY = ROOT / "sources.yaml"
CUSTOM_RULES = ROOT / "custom-rules.txt"
OUTPUT = ROOT / "filters.txt"
REPORT = ROOT / "reports" / "latest.json"
WORKERS = min(16, max(4, (os.cpu_count() or 2) * 2))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import TOTAL_TIMEOUT, collect_sources, valid_url  # noqa: E402
from normalize import normalize_rule, rejection_reason  # noqa: E402
from report import analyze_files, write_report  # noqa: E402


def log(message: str) -> None:
    print(message, flush=True)


def read_sources(path: Path) -> list[str]:
    """Read V6 registry when available, with the original sources.txt fallback."""
    if SOURCE_REGISTRY.is_file():
        try:
            import yaml
            data = yaml.safe_load(SOURCE_REGISTRY.read_text(encoding="utf-8")) or {}
            entries = data.get("sources", [])
            enabled = [x for x in entries if isinstance(x, dict) and x.get("enabled", True) and valid_url(str(x.get("url", "")))]
            enabled.sort(key=lambda x: (int(x.get("priority", 999999)), str(x.get("name", "")).casefold()))
            urls = [str(x["url"]) for x in enabled]
            if urls:
                return list(dict.fromkeys(urls))
            log("[WARN] sources.yaml contains no enabled valid URLs; falling back to sources.txt")
        except Exception as exc:
            log(f"[WARN] Could not parse sources.yaml ({exc}); falling back to sources.txt")
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
    if not source_urls:
        log("[ERROR] No valid source URLs found")
        return 1
    log(f">> Found {len(source_urls)} unique source URLs")
    with tempfile.TemporaryDirectory(prefix="filter-lists-") as temp_dir:
        files, source_stats = collect_sources(source_urls, Path(temp_dir), started, WORKERS, log)
        if source_stats["requested"] and source_stats["successful"] / source_stats["requested"] < 0.50:
            log(f"[ERROR] Source health below 50%: {source_stats['successful']}/{source_stats['requested']} succeeded")
            write_report(REPORT, source_stats=source_stats, rule_stats={"input_lines": 0, "accepted_lines": 0, "rejected_lines": 0, "duplicate_lines": 0, "unique_rules": 0, "rejection_reasons": {}}, elapsed_seconds=time.monotonic() - started, source_urls=source_urls)
            return 1
        rules, rule_stats = analyze_files(files, CUSTOM_RULES)
        if not rules:
            log("[ERROR] No valid strict ABP rules collected")
            return 1
        write_output(rules)
        elapsed = time.monotonic() - started
        write_report(REPORT, source_stats=source_stats, rule_stats=rule_stats, elapsed_seconds=elapsed, source_urls=source_urls)
        log(f">> Accepted lines: {rule_stats['accepted_lines']}; rejected: {rule_stats['rejected_lines']}; unique: {len(rules)}")
        if rule_stats["rejection_reasons"]:
            log(">> Rejections: " + ", ".join(f"{k}={v}" for k, v in rule_stats["rejection_reasons"].items()))
    log(f">> Completed in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
