#!/usr/bin/env python3
"""Historical source reliability and health scoring."""
from __future__ import annotations

import json
from pathlib import Path


def _history_reports(history_dir: Path, limit: int = 30) -> list[dict]:
    reports = []
    for path in history_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status", "success") == "success":
                reports.append(data)
        except (OSError, ValueError):
            continue
    reports.sort(key=lambda item: item.get("generated_at", ""), reverse=True)
    return reports[:limit]


def build_source_reputation(history_dir: Path, current_results: list[dict], *, history_limit: int = 30) -> dict:
    """Return per-URL rolling reliability from successful historical reports plus current run."""
    records: dict[str, list[bool]] = {}
    for report in reversed(_history_reports(history_dir, history_limit)):
        for item in report.get("sources", {}).get("results", []):
            url = item.get("url")
            if url:
                records.setdefault(url, []).append(item.get("status") == "ok")
    for item in current_results:
        url = item.get("url")
        if url:
            records.setdefault(url, []).append(item.get("status") == "ok")

    result = {}
    for url, outcomes in records.items():
        successes = sum(outcomes)
        total = len(outcomes)
        consecutive_failures = 0
        for ok in reversed(outcomes):
            if ok:
                break
            consecutive_failures += 1
        success_rate = successes / total if total else 0.0
        score = round(success_rate * 100, 2)
        if consecutive_failures >= 3:
            reputation = "poor"
        elif success_rate < 0.80:
            reputation = "watch"
        elif success_rate >= 0.95:
            reputation = "excellent"
        else:
            reputation = "good"
        result[url] = {
            "observations": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate": round(success_rate, 4),
            "score": score,
            "consecutive_failures": consecutive_failures,
            "reputation": reputation,
        }
    return result
