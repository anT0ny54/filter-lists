#!/usr/bin/env python3
"""Build statistics, source diagnostics, hashes, and anomaly detection."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from normalize import normalize_rule, rejection_reason


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze_files(
    files: list[Path],
    custom_rules: Path | None = None,
    *,
    max_rule_length: int | None = None,
) -> tuple[set[str], dict]:
    rules: set[str] = set()
    accepted = rejected = duplicates = input_lines = 0
    reasons: Counter[str] = Counter()
    per_file: list[dict[str, Any]] = []

    paths = sorted(files, key=lambda p: str(p))
    if custom_rules and custom_rules.exists():
        paths.append(custom_rules)

    for path in paths:
        local_rules: set[str] = set()
        local_reasons: Counter[str] = Counter()
        local_accepted = local_rejected = local_duplicates = local_lines = 0
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                for raw in source:
                    local_lines += 1
                    input_lines += 1
                    rule = normalize_rule(raw.rstrip("\r\n"), max_rule_length=max_rule_length)
                    if rule is None:
                        rejected += 1
                        local_rejected += 1
                        reason = rejection_reason(raw, max_rule_length=max_rule_length)
                        reasons[reason] += 1
                        local_reasons[reason] += 1
                    else:
                        accepted += 1
                        local_accepted += 1
                        local_rules.add(rule)
                        if rule in rules:
                            duplicates += 1
                            local_duplicates += 1
                        rules.add(rule)
            per_file.append({
                "path": str(path),
                "input_lines": local_lines,
                "accepted_lines": local_accepted,
                "rejected_lines": local_rejected,
                "duplicate_lines": local_duplicates,
                "unique_rules": len(local_rules),
                "rejection_rate": round(local_rejected / local_lines, 6) if local_lines else 0.0,
                "rejection_reasons": dict(sorted(local_reasons.items())),
                "sha256": sha256_file(path),
            })
        except OSError as exc:
            reasons["read-error"] += 1
            local_rejected += 1
            per_file.append({
                "path": str(path), "input_lines": local_lines,
                "accepted_lines": local_accepted, "rejected_lines": local_rejected,
                "duplicate_lines": local_duplicates, "unique_rules": len(local_rules),
                "rejection_rate": round(local_rejected / local_lines, 6) if local_lines else 1.0,
                "rejection_reasons": {"read-error": 1}, "error": str(exc),
            })

    return rules, {
        "input_lines": input_lines,
        "accepted_lines": accepted,
        "rejected_lines": rejected,
        "duplicate_lines": duplicates,
        "unique_rules": len(rules),
        "rejection_reasons": dict(sorted(reasons.items())),
        "per_file": per_file,
    }


def _ratio_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 1.0
    return abs(current - previous) / abs(previous)


def detect_anomalies(current_results: list[dict], previous_report: dict | None, policy: dict) -> dict:
    """Compare source metrics with the previous report without failing normal builds."""
    result = {"enabled": bool(policy.get("enabled", True)), "baseline": "none", "count": 0, "items": []}
    if not result["enabled"] or not previous_report:
        return result
    previous = previous_report.get("sources", {}).get("results", [])
    previous_by_url = {item.get("url"): item for item in previous if item.get("url")}
    result["baseline"] = previous_report.get("build_id") or "previous-report"
    min_lines = int(policy.get("min_lines", 100))
    max_bytes = float(policy.get("max_bytes_change_ratio", 0.75))
    max_rules = float(policy.get("max_rule_count_change_ratio", 0.75))
    max_rejection = float(policy.get("max_rejection_rate_change", 0.25))

    for current in current_results:
        if current.get("status") != "ok":
            continue
        old = previous_by_url.get(current.get("url"))
        if not old:
            continue
        current_lines = int(current.get("input_lines", 0))
        old_lines = int(old.get("input_lines", 0))
        current_rules = int(current.get("unique_rules", 0))
        old_rules = int(old.get("unique_rules", 0))
        current_bytes = int(current.get("bytes", 0))
        old_bytes = int(old.get("bytes", 0))
        current_rejection = float(current.get("rejection_rate", 0.0))
        old_rejection = float(old.get("rejection_rate", 0.0))
        if max(current_lines, old_lines) < min_lines:
            continue

        changes = {
            "bytes_ratio": round(_ratio_change(current_bytes, old_bytes), 6),
            "rule_count_ratio": round(_ratio_change(current_rules, old_rules), 6),
            "rejection_rate_delta": round(abs(current_rejection - old_rejection), 6),
        }
        reasons = []
        if changes["bytes_ratio"] > max_bytes:
            reasons.append("bytes-change")
        if changes["rule_count_ratio"] > max_rules:
            reasons.append("rule-count-change")
        if changes["rejection_rate_delta"] > max_rejection:
            reasons.append("rejection-rate-change")
        if reasons:
            severity = "critical" if (current_rules == 0 or current_lines == 0) else "warning"
            result["items"].append({
                "url": current.get("url"),
                "severity": severity,
                "reasons": reasons,
                "changes": changes,
                "previous": {"bytes": old_bytes, "input_lines": old_lines, "unique_rules": old_rules, "rejection_rate": old_rejection, "sha256": old.get("sha256")},
                "current": {"bytes": current_bytes, "input_lines": current_lines, "unique_rules": current_rules, "rejection_rate": current_rejection, "sha256": current.get("sha256")},
            })
    result["count"] = len(result["items"])
    result["critical_count"] = sum(item["severity"] == "critical" for item in result["items"])
    result["warning_count"] = result["count"] - result["critical_count"]
    return result


def write_report(
    path: Path,
    *,
    source_stats: dict,
    rule_stats: dict,
    elapsed_seconds: float,
    source_urls: list[str],
    build_id: str,
    previous_report: dict | None = None,
    anomaly_policy: dict | None = None,
) -> None:
    clean_sources = {k: v for k, v in source_stats.items() if k != "results"}
    results = []
    for item in source_stats.get("results", []):
        results.append({k: v for k, v in item.items() if k != "path"})
    clean_sources["results"] = results
    anomalies = detect_anomalies(results, previous_report, anomaly_policy or {"enabled": False})
    payload = {
        "schema": 4,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "builder": "Filter-Lists v7.2.0",
        "profile": "strict-abp",
        "build_id": build_id,
        "source_count": len(source_urls),
        "sources": clean_sources,
        "rules": {k: v for k, v in rule_stats.items() if k != "per_file"},
        "anomalies": anomalies,
        "build_seconds": round(elapsed_seconds, 3),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
