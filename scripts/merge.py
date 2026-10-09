#!/usr/bin/env python3
"""Filter-Lists deterministic build orchestrator."""
from __future__ import annotations

import hashlib
import json
import os
import re
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
HISTORY_DIR = ROOT / "reports" / "history"
SOURCES_TXT = ROOT / "sources.txt"
# Download parallelism. fetch.collect_sources still caps this by the download
# byte budget (`max_parallel_by_budget`). Override with FILTER_LISTS_WORKERS.
DEFAULT_WORKERS = 2


def _workers() -> int:
    raw = os.environ.get("FILTER_LISTS_WORKERS", "").strip()
    if not raw:
        return DEFAULT_WORKERS
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"FILTER_LISTS_WORKERS must be an integer, got {raw!r}") from None
    if value < 1:
        raise ValueError("FILTER_LISTS_WORKERS must be >= 1")
    return value

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import BUILDER_VERSION, config_fingerprint, load_config, source_manifest_sha256  # noqa: E402
from fetch import collect_sources  # noqa: E402
from report import analyze_files, write_report  # noqa: E402
from policy import PROFILE_DESCRIPTION  # noqa: E402
from health import history_reports  # noqa: E402


_RULE_SORT_KEY = lambda x: (x.casefold(), x)


def log(message: str) -> None:
    print(message, flush=True)


def load_previous_report() -> dict | None:
    if REPORT.is_file():
        try:
            data = json.loads(REPORT.read_text(encoding="utf-8"))
            if data.get("status", "success") == "success":
                return data
        except (OSError, ValueError):
            pass
    # Build IDs are hashes, so filename order is not chronological. Use the
    # report timestamp when selecting the newest successful baseline.
    newest = history_reports(HISTORY_DIR, 1)
    return newest[0] if newest else None


def archive_successful_report(build_id: str, *, retention: int = 10) -> None:
    """Archive one successful build identity, then retain only the newest N reports."""
    if not REPORT.is_file():
        return
    if retention < 1:
        raise ValueError("history retention must be >= 1")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    data = json.loads(REPORT.read_text(encoding="utf-8"))
    generated_at = str(data.get("generated_at", ""))
    timestamp_slug = re.sub(r"[^0-9A-Za-z]+", "-", generated_at).strip("-")[:48] or "unknown-time"
    report_digest = hashlib.sha256(REPORT.read_bytes()).hexdigest()[:12]

    # Build IDs are deterministic configuration/output identities, while
    # generated_at distinguishes repeated successful runs. Include both so a
    # later report with the same Build-ID is not silently lost.
    target = HISTORY_DIR / f"build-{build_id}-{timestamp_slug}-{report_digest}.json"
    if not target.exists():
        shutil.copy2(REPORT, target)

    # Retention counts distinct builds: an older archived report with the same
    # Build-ID describes the same configuration and output, so only the newest
    # run is kept. (Per-source run outcomes live in source-outcomes.json.)
    for path in HISTORY_DIR.glob("*.json"):
        if path == target:
            continue
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if existing.get("build_id") == build_id and existing.get("status", "success") == "success":
            try:
                path.unlink()
                log(f">> Removed superseded duplicate-build report: {path.name}")
            except OSError as exc:
                log(f"[WARN] Could not remove duplicate report {path.name}: {exc}")

    # Keep retention based on generated_at, not filenames: build IDs are hashes.
    reports = []
    for path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status", "success") == "success":
                reports.append((str(data.get("generated_at", "")), path))
        except (OSError, ValueError):
            continue
    reports.sort(key=lambda item: (item[0], item[1].name), reverse=True)

    for _, path in reports[retention:]:
        try:
            path.unlink()
            log(f">> Removed old history report: {path.name}")
        except OSError as exc:
            log(f"[WARN] Could not remove old history report {path.name}: {exc}")


def sync_legacy_sources(config) -> None:
    """Keep sources.txt as a generated compatibility mirror, never as input."""
    text = "# Generated compatibility mirror of sources.yaml. Do not edit directly.\n"
    text += "\n".join(source.url for source in config.sources) + "\n"
    current = SOURCES_TXT.read_text(encoding="utf-8") if SOURCES_TXT.exists() else ""
    if current != text:
        SOURCES_TXT.write_text(text, encoding="utf-8", newline="\n")


def stage_output(final_rules: list[str], build_id: str, *, manifest_sha256: str, source_count: int) -> Path:
    """Write the list to a temp file next to OUTPUT; nothing is published yet.

    Publishing is a separate step (`commit_output`) so that a build rejected by
    the anomaly policy can never clobber the last good filters.txt.
    """
    now = datetime.now(timezone.utc)
    header = [
        "! Title: Combined Adblock Plus Filter List",
        f"! Version: v{BUILDER_VERSION}-{build_id[:12]}",
        f"! Last updated: {now:%Y-%m-%d %H:%M:%S UTC}",
        "! Expires: 1 day",
        "! Homepage: https://github.com/anT0ny54/filter-lists",
        "! License: https://github.com/anT0ny54/filter-lists/blob/main/LICENSE",
        f"! Build-ID: {build_id}",
        f"! Source manifest SHA-256: {manifest_sha256}",
        f"! Root sources: {source_count}",
        f"! Total rules: {len(final_rules)}",
        "!",
        "! Format: Strict Adblock Plus-compatible syntax",
        f"! Profile: {PROFILE_DESCRIPTION}",
        "! Diagnostics: per-source hashes/statistics and anomaly detection are recorded in reports/latest.json.",
        "! Auto-generated. Do not edit directly.",
        "! Edit sources.yaml and rebuild.",
        "!",
    ]
    fd, temporary = tempfile.mkstemp(prefix="filters.", suffix=".tmp", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write("\n".join(header) + "\n")
            output.write("\n".join(final_rules) + "\n")
        # mkstemp creates the file 0600; a published list must be world-readable
        # (it is served as a static file), like any file written by open().
        os.chmod(temporary, 0o644)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    log(f">> Unique strict ABP rules: {len(final_rules)}")
    return Path(temporary)


def commit_output(staged: Path) -> None:
    os.replace(staged, OUTPUT)


def main() -> int:
    started = time.monotonic()
    previous_report = load_previous_report()
    if shutil.which("curl") is None:
        log("[ERROR] curl is required")
        return 1
    try:
        config = load_config()
    except Exception as exc:
        log(f"[ERROR] Configuration: {exc}")
        return 1
    sync_legacy_sources(config)
    # load_config() already validates and canonicalizes every enabled source.
    # Revalidating and recanonicalizing here only adds work and another place
    # where source-selection logic could drift from configuration semantics.
    source_urls = [s.url for s in config.sources]
    if not source_urls and config.fail_if_zero_sources:
        log("[ERROR] No enabled source URLs found")
        return 1
    if not source_urls:
        log(">> No enabled source URLs; building custom rules only")
    log(f">> Found {len(source_urls)} enabled source URLs")
    fingerprint = config_fingerprint(config)
    try:
        workers = _workers()
    except ValueError as exc:
        log(f"[ERROR] Configuration: {exc}")
        return 1
    with tempfile.TemporaryDirectory(prefix="filter-lists-") as temp_dir:
        files, source_stats = collect_sources(source_urls, Path(temp_dir), started, workers, log, total_timeout=config.total_timeout_seconds, max_include_depth=config.max_include_depth, max_download_bytes=config.max_download_bytes, max_total_download_bytes=config.max_total_download_bytes, max_total_sources=config.max_total_sources)
        source_stats["required"] = [s.url for s in config.sources if s.required]
        source_metadata = {s.url: {"name": s.name, "category": s.category, "priority": s.priority, "required": s.required, "trusted_abp_features": s.trusted_abp_features} for s in config.sources}
        provenance = {"source_manifest_sha256": source_manifest_sha256(config), "source_registry": "sources.yaml", "source_registry_sha256": hashlib.sha256((ROOT / "sources.yaml").read_bytes()).hexdigest(), "builder": f"Filter-Lists v{BUILDER_VERSION}", "policy_sha256": hashlib.sha256((ROOT / "policies.yaml").read_bytes()).hexdigest()}
        failed_root_urls = {x["url"] for x in source_stats.get("results", []) if x.get("status") == "failed" and x.get("depth") == 0}
        source_stats["required_failed"] = [u for u in source_stats["required"] if u in failed_root_urls]
        source_stats["success_ratio"] = round(source_stats["root_successful"] / source_stats["root_requested"], 4) if source_stats["root_requested"] else 0.0
        source_stats["health_basis"] = "root sources only; nested !#include sources are reported separately"
        source_stats["health_threshold"] = config.minimum_success_ratio
        zero_source_failure = (
            config.fail_if_zero_sources and source_stats["root_requested"] == 0
        )
        success_ratio_failure = (
            source_stats["root_requested"] > 0
            and source_stats["success_ratio"] < config.minimum_success_ratio
        )
        unhealthy = (
            zero_source_failure
            or success_ratio_failure
            or bool(source_stats["required_failed"])
            or source_stats.get("source_limit_reached")
            or source_stats.get("timed_out")
            or source_stats.get("budget_exhausted")
        )
        if unhealthy:
            log(f"[ERROR] Source health failed: {source_stats['root_successful']}/{source_stats['root_requested']} root sources ({source_stats['success_ratio']:.1%})")
            if source_stats["required_failed"]:
                log(f"[ERROR] Required sources failed: {len(source_stats['required_failed'])}")
            failed_roots = [x for x in source_stats.get("failures", []) if x.get("depth") == 0]
            for item in failed_roots:
                log(f"[ERROR] Root source failed: {item.get('url')} — {item.get('reason', 'unknown error')}")
            if source_stats.get("timed_out"):
                log("[ERROR] Global fetch deadline was reached before all queued sources completed")
            if source_stats.get("budget_exhausted"):
                log("[ERROR] Global download budget was exhausted before all queued sources completed")
            if source_stats.get("source_limit_reached"):
                log("[ERROR] Global source traversal limit was reached before all queued sources completed")
            stats = {"input_lines": 0, "accepted_lines": 0, "rejected_lines": 0, "duplicate_lines": 0, "unique_rules": 0, "rejection_reasons": {}}
            write_report(REPORT, source_stats=source_stats, rule_stats=stats, elapsed_seconds=time.monotonic()-started, source_urls=source_urls, build_id=fingerprint, previous_report=previous_report, anomaly_policy=config.anomaly_detection, provenance=provenance, source_metadata=source_metadata, history_dir=HISTORY_DIR, status="failed", source_quality_policy=getattr(config, "source_quality", None))
            return 1
        # Reuse the per-source digest fetch.collect_sources already computed
        # instead of hashing every downloaded file a second time in analyze_files.
        known_hashes = {
            Path(item["path"]): item["sha256"]
            for item in source_stats.get("results", [])
            if item.get("status") == "ok" and item.get("path") and item.get("sha256")
        }
        trusted_urls = {s.url for s in config.sources if s.trusted_abp_features}
        trusted_paths = {Path(item["path"]) for item in source_stats.get("results", []) if item.get("status") == "ok" and item.get("path") and item.get("url") in trusted_urls}
        rules, rule_stats = analyze_files(files, CUSTOM_RULES, max_rule_length=config.max_rule_length, known_hashes=known_hashes, trusted_paths=trusted_paths)
        by_path = {item.get("path"): item for item in rule_stats.get("per_file", [])}
        for item in source_stats.get("results", []):
            detail = by_path.get(item.get("path"))
            if detail:
                item.update({k: v for k, v in detail.items() if k != "path"})
        source_stats["content_hash_algorithm"] = "sha256"
        final_rules = sorted(rules, key=_RULE_SORT_KEY)
        build_id = hashlib.sha256((fingerprint + "\n" + "\n".join(final_rules)).encode()).hexdigest()
        staged = stage_output(final_rules, build_id, manifest_sha256=provenance["source_manifest_sha256"], source_count=len(source_urls))
        write_report(REPORT, source_stats=source_stats, rule_stats=rule_stats, elapsed_seconds=time.monotonic()-started, source_urls=source_urls, build_id=build_id, previous_report=previous_report, anomaly_policy=config.anomaly_detection, provenance=provenance, source_metadata=source_metadata, history_dir=HISTORY_DIR, status="success", source_quality_policy=getattr(config, "source_quality", None))
        data = json.loads(REPORT.read_text(encoding="utf-8"))
        quality = data.get("source_quality", {})
        for item in quality.get("items", []):
            log(f"[WARN] Source quality ({item.get('severity')}): {item.get('name') or item.get('url')} rejected {item.get('effective_rejection_rate', 0):.1%} of rule lines ({item.get('accepted_lines')}/{item.get('rule_lines')} accepted)")
        if data.get("anomalies", {}).get("enforced_failure", False) or quality.get("enforced_failure", False):
            staged.unlink(missing_ok=True)  # keep the previous good filters.txt intact
            data["status"] = "failed"
            tmp_report = REPORT.with_suffix(REPORT.suffix + ".tmp")
            tmp_report.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp_report.replace(REPORT)
            log("[ERROR] Anomaly or source-quality policy rejected this build")
            return 1
        commit_output(staged)
        archive_successful_report(build_id, retention=config.history_retention)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
