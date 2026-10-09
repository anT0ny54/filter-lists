#!/usr/bin/env python3
"""Historical source reliability and health scoring.

Two separate histories exist on purpose:

* ``reports/history/`` holds *successful* reports only. They are the baseline
  for output-change (anomaly) detection.
* ``reports/source-outcomes.json`` records the per-source fetch outcome of
  *every* run, successful or failed. It feeds source reputation only, so a
  failed build still counts against a flaky source without ever becoming an
  anomaly baseline.

Reputation counts one observation per source per UTC day. A day is a success
only if every run that day fetched the source successfully, so frequent
rebuilds (push-triggered runs, retries) cannot overweight a single day and a
failure is never hidden by a later same-day success.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OUTCOMES_FILENAME = "source-outcomes.json"
OUTCOMES_SCHEMA = 1
MAX_STORED_RUNS = 120


def history_reports(history_dir: Path, limit: int = 30) -> list[dict]:
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


def default_outcomes_path(history_dir: Path) -> Path:
    return history_dir.parent / OUTCOMES_FILENAME


def _entry(generated_at: str, status: str, build_id: str, results: list[dict]) -> dict:
    return {
        "generated_at": generated_at,
        "status": status,
        "build_id": build_id,
        "outcomes": {
            item["url"]: item.get("status") == "ok"
            for item in results
            if item.get("url")
        },
    }


def load_outcomes(outcomes_path: Path | None, history_dir: Path | None = None) -> list[dict]:
    """Load stored run outcomes, bootstrapping from successful history once.

    When the outcomes file does not exist yet (first run after upgrading), the
    retained successful reports seed the history so reputation is not reset.
    """
    if outcomes_path is not None and outcomes_path.is_file():
        try:
            data = json.loads(outcomes_path.read_text(encoding="utf-8"))
            runs = data.get("runs", []) if isinstance(data, dict) else []
            return [r for r in runs if isinstance(r, dict) and isinstance(r.get("outcomes"), dict)]
        except (OSError, ValueError):
            pass
    if history_dir is None or not history_dir.is_dir():
        return []
    seeded = []
    for report in history_reports(history_dir, MAX_STORED_RUNS):
        seeded.append(_entry(
            str(report.get("generated_at", "")),
            "success",
            str(report.get("build_id", "")),
            report.get("sources", {}).get("results", []),
        ))
    seeded.sort(key=lambda r: r["generated_at"])
    return seeded


def record_outcomes(
    outcomes_path: Path,
    *,
    history_dir: Path | None,
    generated_at: str,
    status: str,
    build_id: str,
    results: list[dict],
) -> None:
    """Append this run's per-source outcomes (successful or failed) atomically."""
    runs = load_outcomes(outcomes_path, history_dir)
    runs.append(_entry(generated_at, status, build_id, results))
    runs.sort(key=lambda r: str(r.get("generated_at", "")))
    runs = runs[-MAX_STORED_RUNS:]
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="outcomes.", suffix=".tmp", dir=outcomes_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"schema": OUTCOMES_SCHEMA, "runs": runs}, handle, indent=1, ensure_ascii=False)
            handle.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, outcomes_path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def build_source_reputation(
    history_dir: Path,
    current_results: list[dict],
    *,
    history_limit: int = 30,
    outcomes_path: Path | None = None,
    generated_at: str | None = None,
) -> dict:
    """Return per-URL rolling reliability (one observation per source per UTC day).

    Inputs are the stored run outcomes (successful and failed runs; seeded from
    successful reports when no outcomes file exists yet) plus the current run.
    `history_limit` is the number of most recent days considered per source.
    """
    if outcomes_path is None:
        outcomes_path = default_outcomes_path(history_dir)
    runs = load_outcomes(outcomes_path, history_dir)
    now = generated_at or datetime.now(timezone.utc).isoformat()
    runs.append(_entry(now, "current", "", current_results))
    runs.sort(key=lambda r: str(r.get("generated_at", "")))

    days: dict[str, dict[str, bool]] = {}
    for run in runs:
        day = str(run.get("generated_at", ""))[:10]  # "" (undated) sorts first
        for url, ok in run["outcomes"].items():
            per_day = days.setdefault(url, {})
            per_day[day] = per_day.get(day, True) and bool(ok)

    result = {}
    for url, per_day in days.items():
        outcomes = [per_day[d] for d in sorted(per_day)][-history_limit:]
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
