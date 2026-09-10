#!/usr/bin/env python3
"""Deterministic V7.0 build statistics."""
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from normalize import normalize_rule, rejection_reason


def analyze_files(files: list[Path], custom_rules: Path | None = None, *, max_rule_length: int | None = None) -> tuple[set[str], dict]:
    rules: set[str] = set()
    accepted = rejected = duplicates = input_lines = 0
    reasons: Counter[str] = Counter()
    for path in [*files] + ([custom_rules] if custom_rules and custom_rules.exists() else []):
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                for raw in source:
                    input_lines += 1
                    rule = normalize_rule(raw.rstrip("\r\n"), max_rule_length=max_rule_length)
                    if rule is None:
                        rejected += 1
                        reasons[rejection_reason(raw, max_rule_length=max_rule_length)] += 1
                    else:
                        accepted += 1
                        if rule in rules:
                            duplicates += 1
                        rules.add(rule)
        except OSError:
            reasons["read-error"] += 1
    return rules, {"input_lines": input_lines, "accepted_lines": accepted, "rejected_lines": rejected, "duplicate_lines": duplicates, "unique_rules": len(rules), "rejection_reasons": dict(sorted(reasons.items()))}


def write_report(path: Path, *, source_stats: dict, rule_stats: dict, elapsed_seconds: float, source_urls: list[str], build_id: str) -> None:
    clean_sources = {k: v for k, v in source_stats.items() if k != "results"}
    clean_sources["results"] = [
        {k: v for k, v in item.items() if k != "path"} for item in source_stats.get("results", [])
    ]
    payload = {
        "schema": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "builder": "Filter-Lists v7.0",
        "profile": "strict-abp",
        "build_id": build_id,
        "source_count": len(source_urls),
        "sources": clean_sources,
        "rules": rule_stats,
        "build_seconds": round(elapsed_seconds, 3),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    temporary.replace(path)
