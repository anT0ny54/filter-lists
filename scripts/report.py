#!/usr/bin/env python3
"""Build statistics, provenance, source health, and anomaly detection."""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    BUILDER_VERSION, DEFAULT_ANOMALY_MAX_BYTES_CHANGE_RATIO,
    DEFAULT_ANOMALY_MAX_REJECTION_RATE_CHANGE,
    DEFAULT_ANOMALY_MAX_RULE_COUNT_CHANGE_RATIO, DEFAULT_ANOMALY_MIN_LINES,
    DEFAULT_SOURCE_QUALITY, load_rule_policy, sha256_file,
)
from normalize import default_max_rule_length, normalize_rule_with_reason
from health import build_source_reputation, default_outcomes_path, record_outcomes
from policy import PROFILE_NAME

SCHEMA_VERSION = 5


def _file_record(path: Path, lines: int, accepted: int, rejected: int, duplicates: int, unique: int, reasons, **extra: Any) -> dict[str, Any]:
    """One per-file statistics record (shared by the normal and read-error paths)."""
    # A file that could not be read at all counts as fully rejected.
    default_rate = 1.0 if "error" in extra else 0.0
    return {
        "path": str(path), "input_lines": lines, "accepted_lines": accepted,
        "rejected_lines": rejected, "duplicate_lines": duplicates, "unique_rules": unique,
        "rejection_rate": round(rejected / lines, 6) if lines else default_rate,
        "rejection_reasons": dict(sorted(reasons.items())), **extra,
    }


def analyze_files(files: list[Path], custom_rules: Path | None = None, *, max_rule_length: int | None = None, known_hashes: dict[Path, str] | None = None, trusted_paths: set[Path] | None = None) -> tuple[set[str], dict]:
    rules: set[str] = set()
    accepted = rejected = duplicates = input_lines = 0
    reasons: Counter[str] = Counter()
    per_file: list[dict[str, Any]] = []
    known_hashes = known_hashes or {}
    trusted_paths = trusted_paths or set()
    # Resolved once per call instead of once per input line.
    rule_policy = load_rule_policy()
    if max_rule_length is None:
        max_rule_length = default_max_rule_length()
    paths = sorted(files, key=lambda p: str(p))
    if custom_rules and custom_rules.exists():
        paths.append(custom_rules)
    for path in paths:
        # Stage each file's parsing results locally and merge them only after
        # reading and hashing both succeed. Otherwise a mid-stream I/O error
        # could leave a partially parsed source in the output rules.
        local_rules: set[str] = set()
        local_reasons: Counter[str] = Counter()
        local_accepted = local_rejected = local_lines = 0
        trusted = path in trusted_paths or path == custom_rules
        failure_reason = "read-error"
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                for raw in source:
                    local_lines += 1
                    rule, reason = normalize_rule_with_reason(
                        raw.rstrip("\r\n"), max_rule_length=max_rule_length,
                        trusted_abp_features=trusted, rule_policy=rule_policy,
                    )
                    if rule is None:
                        local_rejected += 1
                        local_reasons[reason] += 1
                    else:
                        local_accepted += 1
                        local_rules.add(rule)
            # Downloaded sources are already hashed once during fetch (see
            # fetch.collect_sources). Reuse that digest instead of re-reading
            # and re-hashing the same file a second time here; only files
            # without a known digest (e.g. custom-rules.txt) get hashed now.
            failure_reason = "hash-error"
            file_hash = known_hashes.get(path) or sha256_file(path)
        except OSError as exc:
            # A failed file is rejected as a unit: none of its partially read
            # rules enter the global set. Count only lines actually observed;
            # an unreadable empty file still has an explicit per-file error
            # without inventing a synthetic input/rejection line.
            failed_lines = local_lines
            input_lines += failed_lines
            rejected += failed_lines
            if failed_lines:
                reasons[failure_reason] += failed_lines
            per_file.append(_file_record(
                path, failed_lines, 0, failed_lines, 0, 0,
                {failure_reason: failed_lines} if failed_lines else {}, error=str(exc),
            ))
            continue

        # Accepted duplicates include repeated rules within this file and
        # rules already committed by an earlier source. Computing this once
        # avoids a global-set membership/length check on every accepted line.
        local_duplicates = local_accepted - len(local_rules) + len(local_rules & rules)
        input_lines += local_lines
        accepted += local_accepted
        rejected += local_rejected
        duplicates += local_duplicates
        reasons.update(local_reasons)
        rules.update(local_rules)
        per_file.append(_file_record(
            path, local_lines, local_accepted, local_rejected, local_duplicates,
            len(local_rules), local_reasons, sha256=file_hash,
        ))
    rejection_rate = round(rejected / input_lines, 6) if input_lines else 0.0
    return rules, {
        "input_lines": input_lines, "accepted_lines": accepted,
        "rejected_lines": rejected, "duplicate_lines": duplicates,
        "unique_rules": len(rules), "rejection_rate": rejection_rate,
        "rejection_reasons": dict(sorted(reasons.items())), "per_file": per_file,
    }


def _ratio_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 1.0
    return abs(current - previous) / abs(previous)


def _anomaly_metrics(item: dict) -> tuple[int, int, int, float] | None:
    """Return validated counters for one source result, or skip malformed data."""
    integer_fields = ("input_lines", "unique_rules", "bytes")
    values = [item.get(key) for key in integer_fields]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        return None
    raw_rejection_rate = item.get("rejection_rate")
    if isinstance(raw_rejection_rate, bool) or not isinstance(raw_rejection_rate, (int, float)):
        return None
    try:
        rejection_rate = float(raw_rejection_rate)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(rejection_rate) or not 0.0 <= rejection_rate <= 1.0:
        return None
    input_lines, unique_rules, byte_count = values
    return input_lines, unique_rules, byte_count, rejection_rate


def detect_anomalies(current_results: list[dict], previous_report: dict | None, policy: dict) -> dict:
    # `fail_on_warning` / `enforced_failure` are present on every return path.
    # Previously they were only set once a baseline existed, so the very first
    # build (or anomaly_detection.enabled: false) produced a report without
    # `enforced_failure` and the publish workflow's `is False` assertion failed.
    result = {"enabled": bool(policy.get("enabled", True)), "baseline": "none", "count": 0, "critical_count": 0, "warning_count": 0, "items": [], "fail_on_warning": bool(policy.get("fail_on_warning", False)), "enforced_failure": False}
    if (
        not result["enabled"]
        or not isinstance(previous_report, dict)
        or previous_report.get("status", "success") != "success"
    ):
        return result
    source_data = previous_report.get("sources")
    previous = source_data.get("results", []) if isinstance(source_data, dict) else []
    if not isinstance(previous, list):
        previous = []
    # Only successful previous fetches are a meaningful baseline. Ignore
    # malformed rows so a manually damaged/truncated-but-valid JSON report
    # cannot abort a new build's anomaly check.
    previous_by_url = {}
    for item in previous:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if (
            not isinstance(url, str)
            or not url
            or item.get("status") != "ok"
            or _anomaly_metrics(item) is None
        ):
            continue
        previous_by_url[url] = item
    build_id = previous_report.get("build_id")
    result["baseline"] = build_id if isinstance(build_id, str) and build_id else "previous-report"
    min_lines = int(policy.get("min_lines", DEFAULT_ANOMALY_MIN_LINES)); max_bytes = float(policy.get("max_bytes_change_ratio", DEFAULT_ANOMALY_MAX_BYTES_CHANGE_RATIO)); max_rules = float(policy.get("max_rule_count_change_ratio", DEFAULT_ANOMALY_MAX_RULE_COUNT_CHANGE_RATIO)); max_rejection = float(policy.get("max_rejection_rate_change", DEFAULT_ANOMALY_MAX_REJECTION_RATE_CHANGE))
    for current in current_results:
        if not isinstance(current, dict) or current.get("status") != "ok": continue
        old = previous_by_url.get(current.get("url"))
        if not old: continue
        current_metrics = _anomaly_metrics(current)
        old_metrics = _anomaly_metrics(old)
        if current_metrics is None or old_metrics is None:
            continue
        current_lines, current_rules, current_bytes, current_rejection = current_metrics
        old_lines, old_rules, old_bytes, old_rejection = old_metrics
        if max(current_lines, old_lines) < min_lines: continue
        changes = {"bytes_ratio": round(_ratio_change(current_bytes, old_bytes), 6), "rule_count_ratio": round(_ratio_change(current_rules, old_rules), 6), "rejection_rate_delta": round(abs(current_rejection - old_rejection), 6)}
        reasons = []
        if changes["bytes_ratio"] > max_bytes: reasons.append("bytes-change")
        if changes["rule_count_ratio"] > max_rules: reasons.append("rule-count-change")
        if changes["rejection_rate_delta"] > max_rejection: reasons.append("rejection-rate-change")
        if reasons:
            severity = "critical" if (current_rules == 0 or current_lines == 0) else "warning"
            result["items"].append({"url": current.get("url"), "severity": severity, "reasons": reasons, "changes": changes, "previous": {"bytes": old_bytes, "input_lines": old_lines, "unique_rules": old_rules, "rejection_rate": old_rejection, "sha256": old.get("sha256")}, "current": {"bytes": current_bytes, "input_lines": current_lines, "unique_rules": current_rules, "rejection_rate": current_rejection, "sha256": current.get("sha256")}})
    result["count"] = len(result["items"]); result["critical_count"] = sum(x["severity"] == "critical" for x in result["items"]); result["warning_count"] = result["count"] - result["critical_count"]
    result["enforced_failure"] = result["critical_count"] > 0 or (result["fail_on_warning"] and result["warning_count"] > 0)
    return result


# Reasons that are ordinary non-rule lines, not evidence of an incompatible feed.
NON_RULE_REASONS = ("comment", "blank", "directive")


def evaluate_source_quality(results: list[dict], policy: dict | None) -> dict:
    """Flag sources whose *rule* lines are mostly rejected.

    Download success says nothing about rule yield: a feed in an incompatible
    syntax downloads fine and then contributes almost nothing. The effective
    rejection rate ignores comments, blanks and directives so a heavily
    commented but compatible list is not penalised.
    """
    policy = {**DEFAULT_SOURCE_QUALITY, **(policy or {})}
    result = {
        "enabled": bool(policy["enabled"]), "min_lines": int(policy["min_lines"]),
        "warn_rejection_rate": float(policy["warn_rejection_rate"]),
        "critical_rejection_rate": float(policy["critical_rejection_rate"]),
        "fail_on_critical": bool(policy["fail_on_critical"]),
        "count": 0, "critical_count": 0, "warning_count": 0, "items": [], "enforced_failure": False,
    }
    if not result["enabled"]:
        return result
    for item in results:
        if item.get("status") != "ok" or "input_lines" not in item:
            continue
        input_lines = int(item.get("input_lines", 0))
        reasons = item.get("rejection_reasons", {}) or {}
        non_rule = sum(int(reasons.get(r, 0)) for r in NON_RULE_REASONS)
        rule_lines = input_lines - non_rule
        if input_lines < result["min_lines"] or rule_lines <= 0:
            continue
        accepted = int(item.get("accepted_lines", 0))
        rejected_rules = max(0, rule_lines - accepted)
        rate = rejected_rules / rule_lines
        if rate < result["warn_rejection_rate"]:
            continue
        severity = "critical" if rate >= result["critical_rejection_rate"] else "warning"
        top = sorted(((k, v) for k, v in reasons.items() if k not in NON_RULE_REASONS), key=lambda kv: (-kv[1], kv[0]))[:3]
        result["items"].append({
            "url": item.get("url"), "name": item.get("name"), "severity": severity,
            "effective_rejection_rate": round(rate, 6), "rule_lines": rule_lines,
            "accepted_lines": accepted, "input_lines": input_lines,
            "top_rejection_reasons": dict(top),
        })
    result["items"].sort(key=lambda x: (-x["effective_rejection_rate"], str(x["url"])))
    result["count"] = len(result["items"])
    result["critical_count"] = sum(x["severity"] == "critical" for x in result["items"])
    result["warning_count"] = result["count"] - result["critical_count"]
    result["enforced_failure"] = result["fail_on_critical"] and result["critical_count"] > 0
    return result


def write_report(path: Path, *, source_stats: dict, rule_stats: dict, elapsed_seconds: float, source_urls: list[str], build_id: str, previous_report: dict | None = None, anomaly_policy: dict | None = None, provenance: dict | None = None, source_metadata: dict | None = None, history_dir: Path | None = None, status: str = "success", source_quality_policy: dict | None = None, outcomes_path: Path | None = None) -> None:
    clean_sources = {k: v for k, v in source_stats.items() if k != "results"}
    results = []
    for item in source_stats.get("results", []):
        result = {k: v for k, v in item.items() if k != "path"}
        meta = (source_metadata or {}).get(result.get("url"), {})
        result.update({k: v for k, v in meta.items() if k not in result})
        results.append(result)
    # Fetch completion order is network-dependent. Sort report records by
    # stable traversal identity so reports are reproducible across runs.
    results.sort(key=lambda item: (int(item.get("depth", 0)), str(item.get("url", "")), str(item.get("status", ""))))
    clean_sources["results"] = results
    anomalies = detect_anomalies(results, previous_report, anomaly_policy or {"enabled": False})
    source_quality = evaluate_source_quality(results, source_quality_policy)
    history_dir = history_dir or path.parent / "history"
    outcomes_path = outcomes_path or default_outcomes_path(history_dir)
    generated_at = datetime.now(timezone.utc).isoformat()
    # Outcome history keeps every URL ever seen, so a since-disabled source
    # (AdGuard Annoyances) would still be listed. Report reputation only for
    # the sources of this run; its history is retained if it is re-enabled.
    current_urls = {item.get("url") for item in results}
    reputation = {
        url: value
        for url, value in build_source_reputation(history_dir, results, outcomes_path=outcomes_path, generated_at=generated_at).items()
        if url in current_urls
    }
    payload = {
        "schema": SCHEMA_VERSION, "status": status, "generated_at": generated_at, "builder": f"Filter-Lists v{BUILDER_VERSION}", "profile": PROFILE_NAME, "build_id": build_id, "source_count": len(source_urls),
        "provenance": provenance or {}, "sources": clean_sources, "source_reputation": reputation, "source_quality": source_quality,
        "rules": {k: v for k, v in rule_stats.items() if k != "per_file"}, "anomalies": anomalies, "build_seconds": round(elapsed_seconds, 3),
    }
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8"); temporary.replace(path)
    # Every run (including failed ones) contributes source outcomes to the
    # reputation history. This is separate from reports/history/, which only
    # ever holds successful anomaly baselines. Recorded after the reputation
    # above was computed so the current run is not counted twice.
    record_outcomes(outcomes_path, history_dir=history_dir, generated_at=generated_at, status=status, build_id=build_id, results=results)
