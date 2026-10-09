#!/usr/bin/env python3
"""Build statistics, provenance, source health, and anomaly detection."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    BUILDER_VERSION, DEFAULT_ANOMALY_MAX_BYTES_CHANGE_RATIO,
    DEFAULT_ANOMALY_MAX_REJECTION_RATE_CHANGE,
    DEFAULT_ANOMALY_MAX_RULE_COUNT_CHANGE_RATIO, DEFAULT_ANOMALY_MIN_LINES,
    load_rule_policy, sha256_file,
)
from normalize import default_max_rule_length, normalize_rule_with_reason
from health import build_source_reputation, default_outcomes_path, record_outcomes
from policy import PROFILE_NAME

SCHEMA_VERSION = 5


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
        local_rules: set[str] = set()
        local_reasons: Counter[str] = Counter()
        local_accepted = local_rejected = local_duplicates = local_lines = 0
        # Constant for the whole file; previously re-evaluated (twice) per line.
        trusted = path in trusted_paths or path == custom_rules
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                for raw in source:
                    local_lines += 1; input_lines += 1
                    rule, reason = normalize_rule_with_reason(raw.rstrip("\r\n"), max_rule_length=max_rule_length, trusted_abp_features=trusted, rule_policy=rule_policy)
                    if rule is None:
                        rejected += 1; local_rejected += 1
                        reasons[reason] += 1; local_reasons[reason] += 1
                    else:
                        accepted += 1; local_accepted += 1; local_rules.add(rule)
                        # One hash lookup instead of `in` followed by `add`.
                        before = len(rules)
                        rules.add(rule)
                        if len(rules) == before:
                            duplicates += 1; local_duplicates += 1
            # Downloaded sources are already hashed once during fetch (see
            # fetch.collect_sources). Reuse that digest instead of re-reading
            # and re-hashing the same file a second time here; only files
            # without a known digest (e.g. custom-rules.txt) get hashed now.
            file_hash = known_hashes.get(path) or sha256_file(path)
            per_file.append({"path": str(path), "input_lines": local_lines, "accepted_lines": local_accepted, "rejected_lines": local_rejected, "duplicate_lines": local_duplicates, "unique_rules": len(local_rules), "rejection_rate": round(local_rejected / local_lines, 6) if local_lines else 0.0, "rejection_reasons": dict(sorted(local_reasons.items())), "sha256": file_hash})
        except OSError as exc:
            reasons["read-error"] += 1; rejected += 1; local_rejected += 1
            per_file.append({"path": str(path), "input_lines": local_lines, "accepted_lines": local_accepted, "rejected_lines": local_rejected, "duplicate_lines": local_duplicates, "unique_rules": len(local_rules), "rejection_rate": round(local_rejected / local_lines, 6) if local_lines else 1.0, "rejection_reasons": {"read-error": 1}, "error": str(exc)})
    return rules, {"input_lines": input_lines, "accepted_lines": accepted, "rejected_lines": rejected, "duplicate_lines": duplicates, "unique_rules": len(rules), "rejection_rate": round(rejected / input_lines, 6) if input_lines else 0.0, "rejection_reasons": dict(sorted(reasons.items())), "per_file": per_file}


def _ratio_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 1.0
    return abs(current - previous) / abs(previous)


def detect_anomalies(current_results: list[dict], previous_report: dict | None, policy: dict) -> dict:
    # `fail_on_warning` / `enforced_failure` are present on every return path.
    # Previously they were only set once a baseline existed, so the very first
    # build (or anomaly_detection.enabled: false) produced a report without
    # `enforced_failure` and the publish workflow's `is False` assertion failed.
    result = {"enabled": bool(policy.get("enabled", True)), "baseline": "none", "count": 0, "critical_count": 0, "warning_count": 0, "items": [], "fail_on_warning": bool(policy.get("fail_on_warning", False)), "enforced_failure": False}
    if not result["enabled"] or not previous_report or previous_report.get("status", "success") != "success":
        return result
    previous = previous_report.get("sources", {}).get("results", [])
    # Only successful previous fetches are a meaningful baseline. A previously
    # failed source has 0 bytes/lines, which made every recovery look like a
    # 100% "bytes-change" anomaly.
    previous_by_url = {item.get("url"): item for item in previous if item.get("url") and item.get("status") == "ok"}
    result["baseline"] = previous_report.get("build_id") or "previous-report"
    min_lines = int(policy.get("min_lines", DEFAULT_ANOMALY_MIN_LINES)); max_bytes = float(policy.get("max_bytes_change_ratio", DEFAULT_ANOMALY_MAX_BYTES_CHANGE_RATIO)); max_rules = float(policy.get("max_rule_count_change_ratio", DEFAULT_ANOMALY_MAX_RULE_COUNT_CHANGE_RATIO)); max_rejection = float(policy.get("max_rejection_rate_change", DEFAULT_ANOMALY_MAX_REJECTION_RATE_CHANGE))
    for current in current_results:
        if current.get("status") != "ok": continue
        old = previous_by_url.get(current.get("url"))
        if not old: continue
        current_lines = int(current.get("input_lines", 0)); old_lines = int(old.get("input_lines", 0))
        current_rules = int(current.get("unique_rules", 0)); old_rules = int(old.get("unique_rules", 0))
        current_bytes = int(current.get("bytes", 0)); old_bytes = int(old.get("bytes", 0))
        current_rejection = float(current.get("rejection_rate", 0.0)); old_rejection = float(old.get("rejection_rate", 0.0))
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
    from config import DEFAULT_SOURCE_QUALITY
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
    payload = {
        "schema": SCHEMA_VERSION, "status": status, "generated_at": generated_at, "builder": f"Filter-Lists v{BUILDER_VERSION}", "profile": PROFILE_NAME, "build_id": build_id, "source_count": len(source_urls),
        "provenance": provenance or {}, "sources": clean_sources, "source_reputation": build_source_reputation(history_dir, results, outcomes_path=outcomes_path, generated_at=generated_at), "source_quality": source_quality,
        "rules": {k: v for k, v in rule_stats.items() if k != "per_file"}, "anomalies": anomalies, "build_seconds": round(elapsed_seconds, 3),
    }
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8"); temporary.replace(path)
    # Every run (including failed ones) contributes source outcomes to the
    # reputation history. This is separate from reports/history/, which only
    # ever holds successful anomaly baselines. Recorded after the reputation
    # above was computed so the current run is not counted twice.
    record_outcomes(outcomes_path, history_dir=history_dir, generated_at=generated_at, status=status, build_id=build_id, results=results)
