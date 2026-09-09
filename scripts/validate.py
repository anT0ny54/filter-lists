#!/usr/bin/env python3
"""Validate an existing generated filter file against the V6 ABP profile."""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from normalize import normalize_rule  # noqa: E402

TOTAL_RE = re.compile(r"^! Total rules: ([0-9]+)$")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SCRIPT_DIR.parent / "filters.txt"
    if not path.is_file():
        print(f"[ERROR] Missing filter file: {path}")
        return 1
    accepted = rejected = duplicates = 0
    seen: set[str] = set()
    previous = None
    errors: list[str] = []
    declared_total = None
    with path.open(encoding="utf-8", errors="strict") as source:
        for number, raw in enumerate(source, 1):
            line = raw.rstrip("\r\n")
            match = TOTAL_RE.match(line)
            if match:
                declared_total = int(match.group(1))
                continue
            if not line or line.lstrip().startswith("!"):
                continue
            normalized = normalize_rule(line)
            if normalized is None:
                rejected += 1
                errors.append(f"[INVALID] line {number}: {line[:180]}")
                continue
            accepted += 1
            if normalized in seen:
                duplicates += 1
                errors.append(f"[DUPLICATE] line {number}: {line[:180]}")
            seen.add(normalized)
            if previous is not None and line.casefold() < previous.casefold():
                errors.append(f"[UNSORTED] line {number}: {line[:180]}")
            previous = line
            if normalized != line:
                errors.append(f"[NONCANONICAL] line {number}: {line[:180]}")
    if declared_total is not None and declared_total != len(seen):
        errors.append(f"[COUNT] declared {declared_total}, found {len(seen)} unique rules")
    for error in errors[:100]:
        print(error)
    print(f"Accepted rules: {accepted}")
    print(f"Unique rules:   {len(seen)}")
    print(f"Duplicates:     {duplicates}")
    print(f"Invalid rules:  {rejected}")
    print(f"Errors:         {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
